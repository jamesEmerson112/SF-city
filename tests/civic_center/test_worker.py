"""Exercise the real TCP worker and simulation without starting a renderer."""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import select
import socket
import subprocess
import sys
import threading
import time

import pytest

from civic_center import worker as worker_module
from civic_center.checkpoint import save_checkpoint
from civic_center.model import CivicSimulation
from civic_center.shared_geometry import GeometryEncodingCancelled, SharedGeometryDecoder
from civic_center.worker import CivicWorker, Client, encode_frame


TOKEN = "worker-test-secret"


@pytest.fixture
def scenario():
    return {
        "schema_version": 1,
        "id": "worker-test",
        "label": "Short commute",
        "seed": 7,
        "tick_hz": 200,
        "start_time_seconds": 28790,
        "nodes": [
            {"id": "a", "position": [0, 0, 0]},
            {"id": "b", "position": [2, 0, 0]},
            {"id": "c", "position": [2, 3, 0]},
        ],
        "edges": [
            {"id": "ab", "from": "a", "to": "b", "bidirectional": True},
            {"id": "bc", "from": "b", "to": "c", "bidirectional": True},
        ],
        "buildings": [
            {"id": "home", "entrance_node_id": "a", "kind": "home", "capacity": 1},
            {"id": "work", "entrance_node_id": "c", "kind": "work", "capacity": 1},
        ],
        "residents": [
            {
                "id": "alice",
                "label": "Alice",
                "home_id": "home",
                "work_id": "work",
                "departure_tick": 2000,
                "return_tick": 10000,
                "speed_mps": 1.0,
            }
        ],
    }


class Peer:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.socket.settimeout(3)
        self.buffer = bytearray()
        self.counter = 0
        self.geometries = {}
        self.geometry_frames_received = 0
        self.shared_geometry = None

    def close(self):
        self.socket.close()

    def send(self, message):
        self.socket.sendall(encode_frame(message))

    def receive(self):
        while b"\n" not in self.buffer:
            data = self.socket.recv(65536)
            if not data:
                raise EOFError("worker closed the connection")
            self.buffer.extend(data)
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        message = json.loads(line)
        if message["type"] == "scene":
            self.geometries.clear()
            self.shared_geometry = (SharedGeometryDecoder(message["session_id"])
                                    if message.get("route_geometry_encoding") == worker_module.CITY_POINTS_ENCODING else None)
        elif message["type"] in ("route_coordinate_pool", "trip_geometry_indices"):
            assert self.shared_geometry is not None
            self.shared_geometry.apply(message)
            if message["type"] == "trip_geometry_indices":
                for record in message["geometries"]:
                    self.geometries[record["id"]] = self.shared_geometry.expand([record["id"]])[0]
        elif message["type"] == "trip_geometries":
            self.geometry_frames_received += 1
            for definition in message["geometries"]:
                assert definition["id"] not in self.geometries
                self.geometries[definition["id"]] = definition
        elif message["type"] == "forget_trip_geometries":
            if self.shared_geometry is not None:
                self.shared_geometry.apply(message)
            for trip_id in message["ids"]:
                del self.geometries[trip_id]
        return message

    def until(self, kind, **matching):
        for _ in range(100):
            message = self.receive()
            if message["type"] == kind and all(
                message.get(key) == value for key, value in matching.items()
            ):
                return message
        raise AssertionError(f"no matching {kind} response")

    def hello(self, snapshot_encoding=None, *, command_status=False, points=False):
        message = {"type": "hello", "protocol_version": 1, "token": TOKEN}
        if snapshot_encoding is not None:
            message["snapshot_encoding"] = snapshot_encoding
        if command_status:
            message["command_status"] = True
        if points:
            message["route_geometry_encoding"] = worker_module.CITY_POINTS_ENCODING
        self.send(message)
        scene = self.until("scene")
        snapshot = self.until("snapshot", session_id=scene["session_id"])
        return scene, snapshot

    def command(self, action, value=None, *, response="ack"):
        self.counter += 1
        request_id = str(self.counter)
        message = {"type": "command", "request_id": request_id, "action": action}
        if value is not None:
            message["value"] = value
        self.send(message)
        return self.until(response, request_id=request_id)


@pytest.fixture
def running(scenario, tmp_path):
    instances = []

    @contextmanager
    def start(*, paused=True, ready_file=None, save_dir=None, job_backend="thread"):
        instance = CivicWorker(
            scenario,
            TOKEN,
            ready_file=ready_file,
            save_dir=save_dir if save_dir is not None else tmp_path / "saves",
            job_backend=job_backend,
        )
        instance.simulation.set_paused(paused)
        failures = []

        def run():
            try:
                instance.run()
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        instances.append((instance, thread, failures))
        thread.start()
        peer = Peer(instance.port)
        try:
            yield instance, peer, thread
        finally:
            peer.close()
            instance.stop()
            thread.join(3)
            assert not thread.is_alive(), "worker did not stop"
            assert not failures, failures

    yield start
    for instance, thread, _ in instances:
        instance.stop()
        thread.join(3)


def test_fragmented_hello_waits_for_complete_frame_and_returns_full_state(running):
    with running() as (_worker, peer, _thread):
        hello = encode_frame({"type": "hello", "protocol_version": 1, "token": TOKEN})
        peer.socket.sendall(hello[:7])
        peer.socket.sendall(hello[7:-1])
        peer.socket.settimeout(0.05)
        with pytest.raises(socket.timeout):
            peer.receive()
        peer.socket.settimeout(3)
        peer.socket.sendall(hello[-1:])
        scene = peer.receive()
        snapshot = peer.receive()
        assert scene["type"] == "scene"
        assert scene["visual_asset"] == "res://assets/civic-center.glb"
        assert snapshot["type"] == "snapshot"
        assert snapshot["session_id"] == scene["session_id"]
        assert snapshot["tick"] == 0
        assert snapshot["residents"][0]["id"] == "alice"
        assert sum(building["occupancy"] for building in snapshot["buildings"]) == 1


@pytest.mark.parametrize(
    "hello",
    [
        {"type": "hello", "protocol_version": 1, "token": "wrong-secret"},
        {"type": "hello", "protocol_version": 2, "token": TOKEN},
        {"type": "hello", "protocol_version": True, "token": TOKEN},
        {"type": "hello", "protocol_version": 1, "token": "\ud800"},
        {"type": "command", "action": "shutdown", "request_id": "unauthorized"},
    ],
)
def test_invalid_authentication_never_returns_scene_or_mutates_state(running, hello):
    with running() as (instance, peer, thread):
        peer.send(hello)
        error = peer.receive()
        assert error["type"] == "error"
        assert error["code"] == "authentication_failed"
        assert TOKEN not in json.dumps(error)
        assert "session_id" not in error
        with pytest.raises(EOFError):
            peer.receive()
        assert instance.simulation.tick == 0
        assert thread.is_alive()
        reconnect = Peer(instance.port)
        try:
            assert reconnect.hello()[1]["tick"] == 0
        finally:
            reconnect.close()


def test_combined_commands_preserve_all_acknowledgments(running):
    with running() as (_instance, peer, _thread):
        peer.hello()
        commands = [
            {
                "type": "command",
                "request_id": f"speed-{speed}",
                "action": "speed",
                "value": speed,
            }
            for speed in (1, 4, 60, 600)
        ]
        peer.socket.sendall(b"".join(encode_frame(command) for command in commands))
        acknowledgments = []
        while len(acknowledgments) < 4:
            message = peer.receive()
            if message["type"] == "ack":
                acknowledgments.append(message["request_id"])
        assert acknowledgments == [f"speed-{speed}" for speed in (1, 4, 60, 600)]
        assert peer.until("snapshot", speed=600)["paused"] is True


def test_paused_step_obeys_exact_departure_and_arrival_ticks(running):
    with running() as (_instance, peer, _thread):
        peer.hello()
        assert peer.command("step", 1999)["tick"] == 1999
        assert peer.until("snapshot", tick=1999)["residents"][0]["activity"] == "home"
        assert peer.command("step", 1)["tick"] == 2000
        walking = peer.until("snapshot", tick=2000)
        assert walking["residents"][0]["activity"] == "walking_to_work"
        assert walking["residents"][0]["trip"]["arrival_tick"] == 3000
        assert peer.command("step", 1000)["tick"] == 3000
        arrived = peer.until("snapshot", tick=3000)
        assert arrived["residents"][0]["activity"] == "at_work"
        assert arrived["residents"][0]["visible"] is False
        assert arrived["buildings"][1]["resident_ids"] == ["alice"]
        later = peer.until("snapshot", tick=3000)
        assert later["sequence"] > arrived["sequence"]


def test_pause_stops_clock_and_resuming_advances_it(running):
    with running(paused=False) as (_instance, peer, _thread):
        peer.hello()
        ack = peer.command("pause", True)
        first = peer.until("snapshot", paused=True)
        second = peer.until("snapshot", paused=True)
        assert first["tick"] == second["tick"] == ack["tick"]
        peer.command("pause", False)
        resumed = peer.until("snapshot", paused=False)
        later = peer.until("snapshot", paused=False)
        assert later["tick"] > resumed["tick"]


@pytest.mark.parametrize(
    ("action", "value"),
    [
        ("pause", 1),
        ("speed", 0),
        ("speed", True),
        ("speed", 4.0),
        ("step", -1),
        ("step", 1.5),
        ("step", True),
        ("step", 17280001),
        ("population", 2),
        ("population", True),
        ("unknown", None),
    ],
)
def test_invalid_commands_are_clear_and_leave_paused_state_unchanged(
    running, action, value
):
    with running() as (_instance, peer, _thread):
        scene, initial = peer.hello()
        error = peer.command(action, value, response="error")
        assert error["code"] == "invalid_command"
        assert error["message"]
        current = peer.until("snapshot")
        assert current["tick"] == 0
        assert current["session_id"] == scene["session_id"]
        assert current["residents"] == initial["residents"]


def test_step_requires_pause(running):
    with running(paused=False) as (_instance, peer, _thread):
        peer.hello()
        error = peer.command("step", 1, response="error")
        assert "paused" in error["message"]


def test_reset_repeats_scenario_in_new_session_and_reconnect_is_complete(running):
    with running() as (instance, peer, _thread):
        original_scene, initial = peer.hello()
        peer.command("step", 2500)
        advanced = peer.until("snapshot", tick=2500)
        reconnect = Peer(instance.port)
        try:
            scene, snapshot = reconnect.hello()
            assert scene == original_scene
            assert snapshot["tick"] == 2500
            assert snapshot["residents"] == advanced["residents"]
        finally:
            reconnect.close()
        peer.send({"type": "command", "request_id": "reset", "action": "reset"})
        reset_scene = peer.until("scene")
        assert reset_scene["session_id"] != original_scene["session_id"]
        assert reset_scene["scenario"] == original_scene["scenario"]
        ack = peer.until("ack", request_id="reset")
        assert ack["tick"] == 0
        assert ack["session_id"] == reset_scene["session_id"]
        reset = peer.until("snapshot", session_id=reset_scene["session_id"])
        assert reset["residents"] == initial["residents"]
        assert reset["speed"] == 1
        assert reset["paused"] is False


def test_population_replaces_scene_and_preserves_seed(running):
    with running() as (_instance, peer, _thread):
        original, _ = peer.hello()
        scenes = []
        for attempt in range(2):
            peer.send(
                {
                    "type": "command",
                    "request_id": str(attempt),
                    "action": "population",
                    "value": 20,
                }
            )
            scene = peer.until("scene")
            ack = peer.until("ack", request_id=str(attempt))
            assert ack["tick"] == 0
            assert len(scene["scenario"]["residents"]) == 20
            assert scene["scenario"]["seed"] == original["scenario"]["seed"]
            scenes.append(scene)
        assert scenes[0]["session_id"] != scenes[1]["session_id"]
        assert scenes[0]["scenario"] == scenes[1]["scenario"]


def test_city_population_restart_preserves_geography_and_terrain(
    scenario, running, monkeypatch
):
    from civic_center import city_scenario

    scenario.update(
        geography_manifest="observed-city.json",
        terrain_manifest="observed-hills.json",
        landuse_manifest="observed-landuse.json",
        population_presets=[1, 20],
    )
    calls = []

    def build(manifest_path, *, population, seed, terrain_path, landuse_path=None):
        calls.append((manifest_path, population, seed, terrain_path, landuse_path))
        replacement = deepcopy(scenario)
        replacement["residents"] = [
            dict(scenario["residents"][0], id=f"city-person-{index}")
            for index in range(population)
        ]
        return replacement

    monkeypatch.setattr(city_scenario, "build_city_scenario", build)
    with running() as (_instance, peer, _thread):
        initial, _ = peer.hello()
        peer.send(
            {
                "type": "command",
                "request_id": "city-population",
                "action": "population",
                "value": 20,
            }
        )
        updated = peer.until("scene")
        peer.until("ack", request_id="city-population")
        assert updated["session_id"] != initial["session_id"]
        assert updated["scenario"]["geography_manifest"] == "observed-city.json"
        assert len(updated["scenario"]["residents"]) == 20
        assert calls == [
            (
                "observed-city.json",
                20,
                7,
                "observed-hills.json",
                "observed-landuse.json",
            )
        ]


def test_city_population_failure_preserves_running_day(scenario, running, monkeypatch):
    from civic_center import city_scenario

    scenario.update(geography_manifest="missing-city.json", population_presets=[1, 20])

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("City source data is unavailable")

    monkeypatch.setattr(city_scenario, "build_city_scenario", unavailable)
    with running() as (_instance, peer, _thread):
        scene, original = peer.hello()
        peer.command("population", 20, response="error")
        snapshot = peer.until("snapshot")
        assert snapshot["session_id"] == scene["session_id"]
        assert snapshot["residents"] == original["residents"]
        peer.command("population", 5000, response="error")
        snapshot = peer.until("snapshot")
        assert snapshot["session_id"] == scene["session_id"]


def test_next_event_advances_exactly_and_stays_paused(running):
    with running() as (_instance, peer, _thread):
        peer.hello()
        for tick, activity in (
            (2000, "walking_to_work"),
            (3000, "at_work"),
            (10000, "walking_home"),
            (11000, "home"),
            (11000, "home"),
        ):
            assert peer.command("next_event")["tick"] == tick
            snapshot = peer.until("snapshot", tick=tick)
            assert snapshot["paused"] is True
            assert snapshot["residents"][0]["activity"] == activity
        assert snapshot["event_count"] == 4


def test_quick_save_load_restores_midtrip_state_in_new_session(running):
    with running() as (instance, peer, _thread):
        original_scene, _ = peer.hello()
        peer.command("speed", 60)
        peer.command("step", 2500)
        saved = peer.until("snapshot", tick=2500)
        save_ack = peer.command("save")
        assert save_ack["slot"] == "quick"
        assert save_ack["tick"] == 2500
        assert save_ack["session_id"] == original_scene["session_id"]
        assert (instance.save_dir / "quick.json").is_file()
        peer.command("step", 8500)
        assert peer.until("snapshot", tick=11000)["residents"][0]["activity"] == "home"
        peer.send({"type": "command", "request_id": "restore", "action": "load"})
        restored_scene = peer.until("scene")
        restored_ack = peer.until("ack", request_id="restore")
        restored = peer.until("snapshot", session_id=restored_scene["session_id"])
        assert restored_scene["session_id"] != original_scene["session_id"]
        assert restored_scene["scenario"] == original_scene["scenario"]
        assert restored_ack["slot"] == "quick"
        assert restored_ack["tick"] == 2500
        assert restored["paused"] is True
        assert restored["speed"] == 60
        assert restored["sequence"] == 1
        for field in (
            "tick",
            "clock_seconds",
            "simulation_time",
            "residents",
            "buildings",
            "events",
            "event_count",
        ):
            assert restored[field] == saved[field]
        assert instance._tick_fraction == 0
        peer.command("step", 500)
        arrival = peer.until("snapshot", tick=3000)
        assert arrival["residents"][0]["activity"] == "at_work"
        peer.command("step", 8000)
        returned = peer.until("snapshot", tick=11000)
        assert returned["residents"][0]["activity"] == "home"
        assert returned["event_count"] == 4


@pytest.mark.parametrize("slot", ["Slot_09-a", "a" * 48])
def test_named_save_slots_work(running, slot):
    with running() as (instance, peer, _thread):
        peer.hello()
        assert peer.command("save", slot)["slot"] == slot
        assert (instance.save_dir / f"{slot}.json").is_file()
        assert peer.command("load", slot)["slot"] == slot


def test_load_restores_a_running_clock_and_saved_speed(running):
    with running() as (instance, peer, _thread):
        original_scene, _ = peer.hello()
        peer.command("speed", 4)
        peer.command("step", 2500)
        peer.command("pause", False)
        saved = peer.command("save", "running")
        document = json.loads(
            (instance.save_dir / "running.json").read_text(encoding="utf-8")
        )
        assert document["tick"] == saved["tick"]
        assert document["paused"] is False
        peer.command("pause", True)
        peer.command("speed", 600)
        peer.command("step", 1000)
        restored = peer.command("load", "running")
        assert restored["tick"] == saved["tick"]
        assert restored["session_id"] != original_scene["session_id"]
        snapshot = peer.until("snapshot", session_id=restored["session_id"])
        assert snapshot["paused"] is False
        assert snapshot["speed"] == 4


@pytest.mark.parametrize("action", ["save", "load"])
@pytest.mark.parametrize(
    "slot",
    [
        "",
        ".",
        "..",
        "../escape",
        "..\\escape",
        "/absolute",
        "C:\\outside",
        "slot.json",
        "foo/bar",
        "a" * 49,
        "caf\u00e9",
        23,
        None,
    ],
)
def test_save_load_rejects_invalid_slots_without_mutating_state(running, action, slot):
    with running() as (instance, peer, _thread):
        scene, initial = peer.hello()
        original_model = instance.simulation
        peer.send(
            {
                "type": "command",
                "request_id": "bad-slot",
                "action": action,
                "value": slot,
            }
        )
        error = peer.until("error", request_id="bad-slot")
        assert error["code"] == "invalid_command"
        assert "slot" in error["message"]
        snapshot = peer.until("snapshot")
        assert snapshot["tick"] == 0
        assert snapshot["residents"] == initial["residents"]
        assert snapshot["session_id"] == scene["session_id"]
        assert instance.simulation is original_model
        assert not instance.save_dir.exists()


@pytest.mark.parametrize("contents", [None, "{not json", "{}"])
def test_missing_or_corrupt_load_keeps_current_session(running, contents):
    with running() as (instance, peer, _thread):
        scene, _ = peer.hello()
        peer.command("step", 2500)
        original = peer.until("snapshot", tick=2500)
        original_model = instance.simulation
        if contents is not None:
            instance.save_dir.mkdir(parents=True)
            (instance.save_dir / "broken.json").write_text(contents, encoding="utf-8")
        error = peer.command("load", "broken", response="error")
        assert error["message"]
        unchanged = peer.until("snapshot", tick=2500)
        assert unchanged["session_id"] == scene["session_id"]
        assert unchanged["residents"] == original["residents"]
        assert unchanged["buildings"] == original["buildings"]
        assert instance.simulation is original_model


def test_load_rejects_valid_checkpoint_that_exceeds_transport_frame_limit(
    running, scenario, monkeypatch
):
    with running() as (instance, peer, _thread):
        scene, initial = peer.hello()
        original_model = instance.simulation
        oversized = CivicSimulation(dict(scenario, label="x" * 5000))
        save_checkpoint(oversized, instance.save_dir / "too-large.json")
        monkeypatch.setattr(worker_module, "MAX_FRAME_BYTES", 4096)
        error = peer.command("load", "too-large", response="error")
        assert "limit" in error["message"]
        unchanged = peer.until("snapshot")
        assert unchanged["session_id"] == scene["session_id"]
        assert unchanged["residents"] == initial["residents"]
        assert instance.simulation is original_model


def test_save_filesystem_error_is_reported_without_changing_model(running, tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("existing file", encoding="utf-8")
    with running(save_dir=blocked) as (instance, peer, _thread):
        scene, initial = peer.hello()
        original_model = instance.simulation
        error = peer.command("save", response="error")
        assert error["code"] == "checkpoint_error"
        assert "save failed" in error["message"]
        unchanged = peer.until("snapshot")
        assert unchanged["session_id"] == scene["session_id"]
        assert unchanged["residents"] == initial["residents"]
        assert instance.simulation is original_model
        assert blocked.read_text(encoding="utf-8") == "existing file"


def test_shutdown_acknowledges_before_closing(running):
    with running() as (_instance, peer, thread):
        peer.hello()
        ack = peer.command("shutdown")
        assert ack["action"] == "shutdown"
        thread.join(3)
        assert not thread.is_alive()


@pytest.mark.parametrize("payload", [b"[]\n", b"{no}\n", b"\xff\n"])
def test_malformed_frame_disconnects_only_its_client(running, payload):
    with running() as (_instance, peer, thread):
        peer.socket.sendall(payload)
        assert peer.receive()["code"] == "invalid_json"
        with pytest.raises(EOFError):
            peer.receive()
        assert thread.is_alive()


def test_oversized_unterminated_frame_is_rejected(running, monkeypatch):
    monkeypatch.setattr(worker_module, "MAX_FRAME_BYTES", 512)
    with running() as (_instance, peer, _thread):
        peer.socket.sendall(b"x" * 513)
        assert peer.receive()["code"] == "frame_too_large"
        with pytest.raises(EOFError):
            peer.receive()


def test_elapsed_tick_accumulator_retains_fractions_and_long_intervals(scenario):
    instance = CivicWorker(scenario, TOKEN)
    try:
        instance._last_time = 0.0
        instance._advance_elapsed(0.0625)
        assert instance.simulation.tick == 12
        assert instance._tick_fraction == 0.5
        instance._advance_elapsed(0.125)
        assert instance.simulation.tick == 25
        assert instance._tick_fraction == 0
        instance.simulation.set_speed(600)
        instance._advance_elapsed(2.125)
        assert instance.simulation.tick == 240025
        assert instance.simulation.snapshot()["event_count"] == 4
        instance.simulation.set_paused(True)
        instance._advance_elapsed(100)
        assert instance.simulation.tick == 240025
        instance.simulation.set_paused(False)
        instance._advance_elapsed(100.125)
        assert instance.simulation.tick == 255025
    finally:
        instance.close()


def test_snapshot_coalescing_preserves_partial_frame_and_acknowledgments():
    connection = socket.socket()
    try:
        client = Client(connection, time.monotonic())
        first = encode_frame({"type": "snapshot", "sequence": 1})
        ack = encode_frame({"type": "ack", "request_id": "one"})
        assert client.enqueue(first, snapshot=True)
        client.outgoing[0].offset = 5
        client.queued_bytes -= 5
        assert client.enqueue(ack)
        assert client.enqueue(
            encode_frame({"type": "snapshot", "sequence": 2}), snapshot=True
        )
        latest = encode_frame({"type": "snapshot", "sequence": 3})
        assert client.enqueue(latest, snapshot=True)
        assert [pending.data for pending in client.outgoing] == [first, ack, latest]
        assert client.outgoing[0].offset == 5
        assert client.queued_bytes == len(first) - 5 + len(ack) + len(latest)
    finally:
        connection.close()


def test_outbound_queue_is_bounded(monkeypatch):
    monkeypatch.setattr(worker_module, "MAX_QUEUE_BYTES", 20)
    connection = socket.socket()
    try:
        client = Client(connection, time.monotonic())
        assert client.enqueue(b"a" * 15)
        assert not client.enqueue(b"b" * 6)
        assert client.queued_bytes == 15
        assert len(client.outgoing) == 1
    finally:
        connection.close()


@pytest.mark.parametrize("first_type", ["snapshot", "trip_geometries"])
def test_partial_socket_write_finishes_frame_before_ack_and_latest_snapshot(
    scenario, first_type
):
    instance = CivicWorker(scenario, TOKEN)
    sender, receiver = socket.socketpair()
    sender.setblocking(False)
    receiver.setblocking(False)
    try:
        client = Client(sender, time.monotonic())
        instance.clients[sender] = client
        instance.selector.register(sender, worker_module.selectors.EVENT_READ, client)
        first = {"type": first_type, "sequence": 1, "payload": "x" * 400000}
        ack = {"type": "ack", "request_id": "important"}
        latest = {"type": "snapshot", "sequence": 3}
        client.enqueue(encode_frame(first), snapshot=first_type == "snapshot")
        instance._write(client)
        assert 0 < client.outgoing[0].offset < len(client.outgoing[0].data)
        client.enqueue(encode_frame(ack))
        client.enqueue(encode_frame({"type": "snapshot", "sequence": 2}), snapshot=True)
        client.enqueue(encode_frame(latest), snapshot=True)
        received = bytearray()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            # Windows socketpair uses TCP; allow its delayed ACK/writable event
            # to run instead of assuming 1,000 tight spins span a network turn.
            select.select([receiver], [sender] if client.outgoing else [], [], 0.01)
            instance._write(client)
            while True:
                try:
                    received.extend(receiver.recv(65536))
                except BlockingIOError:
                    break
            if not client.outgoing:
                break
        assert not client.outgoing
        assert client.queued_bytes == 0
        assert [json.loads(line) for line in received.splitlines()] == [
            first,
            ack,
            latest,
        ]
    finally:
        instance.close()
        receiver.close()


def test_worker_refuses_non_loopback_binding(scenario):
    with pytest.raises(ValueError, match="loopback"):
        CivicWorker(scenario, TOKEN, host="0.0.0.0")


@pytest.mark.parametrize("resume", [False, True])
def test_cli_publishes_atomic_ready_file_and_shuts_down(tmp_path, scenario, resume):
    ready_file = tmp_path / "worker-ready.json"
    save_dir = tmp_path / "saves"
    project_root = Path(__file__).resolve().parents[2]
    startup_options = []
    if resume:
        simulation = CivicSimulation(scenario)
        simulation.step_ticks(2500)
        simulation.set_paused(True)
        simulation.set_speed(60)
        startup_path = save_checkpoint(simulation, tmp_path / "startup.json")
        startup_options = ["--load", str(startup_path)]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "civic_center.worker",
            "--port",
            "0",
            "--token",
            TOKEN,
            "--population",
            "5000" if resume else "1",
            "--seed",
            "17",
            "--ready-file",
            str(ready_file),
            "--save-dir",
            str(save_dir),
            *startup_options,
        ],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    peer = None
    try:
        deadline = time.monotonic() + 5
        while not ready_file.exists() and time.monotonic() < deadline:
            assert process.poll() is None, process.communicate()
            time.sleep(0.01)
        assert ready_file.exists(), "worker did not publish readiness"
        ready = json.loads(ready_file.read_text(encoding="utf-8"))
        assert ready["type"] == "ready"
        # A Windows virtualenv launcher can have a different PID from the child
        # Python interpreter which owns the listening socket.
        assert isinstance(ready["pid"], int) and ready["pid"] > 0
        assert ready["protocol_version"] == 1
        peer = Peer(ready["port"])
        scene, snapshot = peer.hello()
        assert scene["scenario"]["seed"] == (7 if resume else 17)
        assert len(snapshot["residents"]) == 1
        if resume:
            assert snapshot["tick"] == 2500
            assert snapshot["paused"] is True
            assert snapshot["speed"] == 60
            assert snapshot["residents"][0]["activity"] == "walking_to_work"
        assert peer.command("save", "cli")["slot"] == "cli"
        assert (save_dir / "cli.json").is_file()
        peer.command("shutdown")
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert json.loads(stdout) == ready
        assert TOKEN not in stdout + stderr
        assert set(tmp_path.iterdir()) == {ready_file, save_dir} | (
            {startup_path} if resume else set()
        )
    finally:
        if peer is not None:
            peer.close()
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)


def test_cli_scenario_and_checkpoint_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as error:
        worker_module.main(
            ["--token", TOKEN, "--scenario", "scenario.json", "--load", "save.json"]
        )
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "not allowed" in output.err
    assert TOKEN not in output.out + output.err


def test_cli_invalid_checkpoint_fails_before_publishing_readiness(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "civic_center.worker",
            "--token",
            TOKEN,
            "--load",
            str(invalid),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert process.returncode == 1
    assert process.stdout == ""
    assert "Checkpoint" in process.stderr
    assert TOKEN not in process.stderr


def _expand_city_snapshot(scene, snapshot, geometries=None):
    if snapshot.get("encoding") == worker_module.CITY_ROWS_ENCODING:
        snapshot = deepcopy(snapshot)
        snapshot["residents"] = [
            dict(
                zip(
                    (
                        "id",
                        "activity",
                        "building_id",
                        "position",
                        "heading",
                        "visible",
                        "moving",
                        "trip",
                        "blocked_reason",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in snapshot["residents"]
        ]
        for person in snapshot["residents"]:
            if person["trip"] is not None:
                person["trip"] = dict(
                    zip(
                        (
                            "id",
                            "segment_index",
                            "segment_progress",
                            "departure_tick",
                            "arrival_tick",
                            "origin_id",
                            "destination_id",
                        ),
                        person["trip"],
                        strict=True,
                    )
                )
        snapshot["buildings"] = [
            dict(zip(("id", "occupancy", "resident_ids"), row, strict=True))
            for row in snapshot["buildings"]
        ]
        snapshot["encoding"] = worker_module.CITY_ROUTES_ENCODING
    result = {key: value for key, value in snapshot.items() if key != "encoding"}
    for collection in ("residents", "buildings"):
        static = {record["id"]: record for record in scene["scenario"][collection]}
        result[collection] = [
            {**deepcopy(static[record["id"]]), **record}
            for record in snapshot[collection]
        ]
    if snapshot.get("encoding") == worker_module.CITY_ROUTES_ENCODING:
        for resident in result["residents"]:
            trip = resident["trip"]
            if trip is not None:
                resident["trip"] = {**geometries[trip["id"]], **trip}
    return result


def _assert_authoritative_snapshot(instance, scene, message, geometries=None):
    expanded = _expand_city_snapshot(scene, message, geometries)
    for name, expected in instance.simulation.snapshot().items():
        assert expanded[name] == expected, name


def test_rows_mixed_clients_and_spawned_load_keep_exact_public_state(running, scenario):
    scenario["geography_manifest"] = "fixture-map.json"
    scenario["residents"][0]["label"] = "Alice — resident"
    scenario["buildings"][0]["footprint"] = [
        [0.1234567890123456, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
    ]
    with running(job_backend="process") as (instance, peer, _thread):
        peers = [peer, Peer(instance.port), Peer(instance.port), Peer(instance.port)]
        try:
            modes = [
                worker_module.CITY_ROWS_ENCODING,
                worker_module.CITY_ROUTES_ENCODING,
                worker_module.CITY_DYNAMIC_ENCODING,
                None,
            ]
            scenes = [
                connection.hello(mode)[0] for connection, mode in zip(peers, modes)
            ]
            assert scenes[0]["snapshot_encoding"] == worker_module.CITY_ROWS_ENCODING
            peer.command("step", 2500)
            for connection, scene in zip(peers, scenes):
                state = connection.until("snapshot", tick=2500)
                _assert_authoritative_snapshot(
                    instance, scene, state, connection.geometries
                )
            peer.command("save", "rows")
            peer.until("snapshot", tick=2500)
            peer.command("step", 500)
            peer.until("snapshot", tick=3000)
            peer.send(
                {
                    "type": "command",
                    "request_id": "restore-rows",
                    "action": "load",
                    "value": "rows",
                }
            )
            restored_scene = peer.until("scene")
            peer.until("ack", request_id="restore-rows")
            state = peer.until("snapshot", session_id=restored_scene["session_id"])
            assert state["tick"] == 2500
            assert restored_scene["session_id"] != scenes[0]["session_id"]
            _assert_authoritative_snapshot(
                instance, restored_scene, state, peer.geometries
            )
            for connection, mode in zip(peers[1:], modes[1:]):
                new_scene = connection.until(
                    "scene", session_id=restored_scene["session_id"]
                )
                state = connection.until("snapshot", session_id=new_scene["session_id"])
                assert new_scene.get("snapshot_encoding") == mode
                _assert_authoritative_snapshot(
                    instance, new_scene, state, connection.geometries
                )
        finally:
            for connection in peers[1:]:
                connection.close()


@pytest.mark.parametrize(
    "compact,references", [(False, False), (True, False), (False, True)]
)
def test_row_helpers_reject_missing_metadata_or_definitions(
    scenario, compact, references
):
    with pytest.raises(ValueError, match="require"):
        worker_module.scene_message(
            scenario, "test", compact=compact, trip_references=references, rows=True
        )
    with pytest.raises(ValueError, match="require"):
        worker_module.snapshot_message(
            CivicSimulation(scenario),
            "test",
            1,
            compact=compact,
            trip_references=references,
            rows=True,
        )


def test_prepared_rows_cannot_bypass_reused_geometry_cache_limit(scenario, monkeypatch):
    scenario["geography_manifest"] = "fixture-map.json"
    model = CivicSimulation(scenario)
    model.step_ticks(2500)
    monkeypatch.setattr(worker_module, "MAX_TRIP_GEOMETRY_BYTES", 1)
    result = worker_module.prepare_session(model)
    for mode in ((True, True, False), (True, True, True)):
        assert "cache limit" in result.invalid_modes[mode]
        assert mode not in result.scenes
        assert mode not in result.snapshots


@pytest.mark.parametrize("encoding", [worker_module.CITY_ROUTES_ENCODING, worker_module.CITY_ROWS_ENCODING])
def test_shared_points_network_parity_load_reconnect_and_repeating_days(running, scenario, encoding):
    scenario["geography_manifest"] = "fixture-map.json"
    scenario["schedule"] = {"mode":"daily-v1"}
    with running() as (instance, peer, _thread):
        scene, first = peer.hello(encoding, points=True)
        assert scene["route_geometry_encoding"] == worker_module.CITY_POINTS_ENCODING
        _assert_authoritative_snapshot(instance, scene, first, peer.geometries)
        peer.command("step", 2500)
        state = peer.until("snapshot", tick=2500)
        _assert_authoritative_snapshot(instance, scene, state, peer.geometries)
        point_count = peer.shared_geometry.point_count
        reconnect = Peer(instance.port)
        try:
            replacement_scene, current = reconnect.hello(encoding, points=True)
            assert replacement_scene == scene
            _assert_authoritative_snapshot(instance, scene, current, reconnect.geometries)
        finally:
            reconnect.close()
        peer.command("save", "shared")
        peer.until("snapshot", tick=2500)
        peer.command("step", 500)
        _assert_authoritative_snapshot(instance, scene, peer.until("snapshot", tick=3000), peer.geometries)
        assert peer.geometries == {}
        peer.command("step", 86400 * 200 - 500)
        state = peer.until("snapshot", tick=86400 * 200 + 2500)
        _assert_authoritative_snapshot(instance, scene, state, peer.geometries)
        assert peer.shared_geometry.point_count == point_count
        assert len(peer.shared_geometry.active_trip_ids) == 1
        peer.send({"type":"command", "request_id":"shared-load", "action":"load", "value":"shared"})
        loaded_scene = peer.until("scene")
        peer.until("ack", request_id="shared-load")
        loaded = peer.until("snapshot", session_id=loaded_scene["session_id"])
        assert loaded_scene["session_id"] != scene["session_id"]
        _assert_authoritative_snapshot(instance, loaded_scene, loaded, peer.geometries)
        peer.send({"type":"command", "request_id":"shared-reset", "action":"reset"})
        reset_scene = peer.until("scene")
        peer.until("ack", request_id="shared-reset")
        reset = peer.until("snapshot", session_id=reset_scene["session_id"])
        assert reset["tick"] == 0
        assert peer.shared_geometry.point_count == 0


def test_shared_points_controls_and_shutdown_during_cold_preparation(running, scenario, monkeypatch):
    from civic_center import point_transport

    scenario["geography_manifest"] = "fixture-map.json"
    entered = threading.Event()

    def prepare(_self, _definitions, *, retire_ids=(), should_cancel=None):
        entered.set()
        while not should_cancel():
            time.sleep(0.001)
        raise GeometryEncodingCancelled("cancelled fixture")

    monkeypatch.setattr(point_transport.SharedGeometryEncoder, "encode", prepare)
    with running() as (instance, peer, thread):
        peer.send({"type":"hello", "protocol_version":1, "token":TOKEN,
                   "snapshot_encoding":worker_module.CITY_ROWS_ENCODING,
                   "route_geometry_encoding":worker_module.CITY_POINTS_ENCODING})
        scene = peer.until("scene")
        assert entered.wait(1)
        service = instance._point_service
        assert service.busy
        assert peer.command("step", 1)["tick"] == 1
        assert peer.command("pause", True)["session_id"] == scene["session_id"]
        started = time.monotonic()
        peer.command("shutdown")
        thread.join(2)
        assert not thread.is_alive()
        assert not service._thread.is_alive()
        assert time.monotonic() - started < 2


def test_priority_controls_preserve_partial_frame_and_scene_barriers():
    connection, receiver = socket.socketpair()
    try:
        client = Client(connection, time.monotonic())
        client.enqueue(b"old-partial\n")
        client.outgoing[0].offset = 2
        client.enqueue(b"scene\n", scene_barrier=True)
        client.enqueue(b"pool\n")
        client.enqueue(b"ack-one\n", priority=True)
        client.enqueue(b"ack-two\n", priority=True)
        assert [item.data for item in client.outgoing] == [b"old-partial\n", b"scene\n", b"ack-one\n", b"ack-two\n", b"pool\n"]
        assert client.outgoing[0].offset == 2
    finally:
        connection.close()
        receiver.close()


def test_city_dynamic_transport_matches_authority_and_legacy_clients(running, scenario):
    scenario["geography_manifest"] = "fixture-map.json"
    scenario["buildings"][0]["footprint"] = [[i, i + 1, 0] for i in range(100)]
    scenario["residents"][0]["appearance"] = {"colors": [[1, 0, 0]]}
    with running() as (instance, peer, _thread):
        scene, first = peer.hello(worker_module.CITY_DYNAMIC_ENCODING)
        assert scene["snapshot_encoding"] == worker_module.CITY_DYNAMIC_ENCODING
        assert first["encoding"] == worker_module.CITY_DYNAMIC_ENCODING
        assert "appearance" not in first["residents"][0]
        assert "footprint" not in first["buildings"][0]
        _assert_authoritative_snapshot(instance, scene, first)
        legacy = Peer(instance.port)
        try:
            legacy_scene, full = legacy.hello()
            assert "snapshot_encoding" not in legacy_scene
            assert "encoding" not in full
            assert "footprint" in full["buildings"][0]
            assert len(encode_frame(first)) < len(encode_frame(full))
            peer.command("step", 2500)
            walking = peer.until("snapshot", tick=2500)
            _assert_authoritative_snapshot(instance, scene, walking)
            assert walking["residents"][0]["trip"]["points"] == [
                [0, 0, 0],
                [2, 0, 0],
                [2, 3, 0],
            ]
            full_walking = legacy.until("snapshot", tick=2500)
            assert (
                _expand_city_snapshot(scene, walking)["residents"]
                == full_walking["residents"]
            )
            peer.command("step", 500)
            arrived = peer.until("snapshot", tick=3000)
            _assert_authoritative_snapshot(instance, scene, arrived)
            assert arrived["residents"][0]["visible"] is False
            assert len(arrived["residents"]) == 1
        finally:
            legacy.close()


def test_dynamic_reconnect_and_checkpoint_load_resend_static_scene(running, scenario):
    scenario["geography_manifest"] = "fixture-map.json"
    with running() as (instance, peer, _thread):
        scene, _initial = peer.hello(worker_module.CITY_DYNAMIC_ENCODING)
        peer.command("step", 2500)
        walking = peer.until("snapshot", tick=2500)
        reconnect = Peer(instance.port)
        try:
            other_scene, other_state = reconnect.hello(
                worker_module.CITY_DYNAMIC_ENCODING
            )
            assert other_scene == scene
            assert other_state["residents"] == walking["residents"]
            _assert_authoritative_snapshot(instance, other_scene, other_state)
        finally:
            reconnect.close()
        replacement = deepcopy(scenario)
        replacement["residents"][0]["label"] = "Changed saved label"
        saved = CivicSimulation(replacement)
        saved.step_ticks(2500)
        saved.set_paused(True)
        save_checkpoint(saved, instance.save_dir / "replacement.json")
        peer.send(
            {
                "type": "command",
                "request_id": "load",
                "action": "load",
                "value": "replacement",
            }
        )
        new_scene = peer.until("scene")
        ack = peer.until("ack", request_id="load")
        state = peer.until("snapshot", session_id=new_scene["session_id"])
        assert new_scene["session_id"] != scene["session_id"]
        assert ack["session_id"] == new_scene["session_id"]
        assert new_scene["snapshot_encoding"] == worker_module.CITY_DYNAMIC_ENCODING
        assert new_scene["scenario"]["residents"][0]["label"] == "Changed saved label"
        assert state["tick"] == 2500
        _assert_authoritative_snapshot(instance, new_scene, state)


def test_dynamic_reset_starts_a_new_metadata_session(running, scenario):
    scenario["geography_manifest"] = "fixture-map.json"
    with running() as (_instance, peer, _thread):
        scene, first = peer.hello(worker_module.CITY_DYNAMIC_ENCODING)
        peer.command("step", 2500)
        peer.until("snapshot", tick=2500)
        peer.send({"type": "command", "request_id": "reset", "action": "reset"})
        reset_scene = peer.until("scene")
        peer.until("ack", request_id="reset")
        reset = peer.until("snapshot", session_id=reset_scene["session_id"])
        assert reset_scene["session_id"] != scene["session_id"]
        assert reset_scene["scenario"] == scene["scenario"]
        assert reset["tick"] == 0
        assert reset["residents"] == first["residents"]


@pytest.mark.parametrize(
    "city,encoding",
    [(False, "city-dynamic-v1"), (False, "city-rows-v1"), (True, "unknown")],
)
def test_unnegotiated_dynamic_transport_retains_full_snapshots(
    running, scenario, city, encoding
):
    if city:
        scenario["geography_manifest"] = "fixture-map.json"
    with running() as (_instance, peer, _thread):
        scene, snapshot = peer.hello(encoding)
        assert "snapshot_encoding" not in scene
        assert "encoding" not in snapshot
        assert snapshot["residents"][0]["label"] == "Alice"


@pytest.mark.parametrize(
    "encoding", [worker_module.CITY_ROUTES_ENCODING, worker_module.CITY_ROWS_ENCODING]
)
def test_reliable_route_definitions_precede_refs_and_refresh_on_load_and_reconnect(
    running, scenario, encoding
):
    scenario["geography_manifest"] = "fixture-map.json"
    with running() as (instance, peer, _thread):
        scene, first = peer.hello(encoding)
        assert scene["snapshot_encoding"] == encoding
        assert first["encoding"] == encoding
        assert peer.geometries == {}
        peer.command("step", 2500)
        walking = peer.until("snapshot", tick=2500)
        assert peer.geometry_frames_received == 1
        assert "points" not in (
            walking["residents"][0][7]
            if encoding == worker_module.CITY_ROWS_ENCODING
            else walking["residents"][0]["trip"]
        )
        _assert_authoritative_snapshot(instance, scene, walking, peer.geometries)
        peer.until("snapshot", tick=2500)
        peer.until("snapshot", tick=2500)
        assert peer.geometry_frames_received == 1
        reconnect = Peer(instance.port)
        try:
            new_scene, current = reconnect.hello(encoding)
            assert new_scene == scene
            assert reconnect.geometry_frames_received == 1
            _assert_authoritative_snapshot(
                instance, new_scene, current, reconnect.geometries
            )
        finally:
            reconnect.close()
        peer.command("save", "walking")
        peer.until("snapshot", tick=2500)
        peer.command("step", 500)
        arrived = peer.until("snapshot", tick=3000)
        _assert_authoritative_snapshot(instance, scene, arrived, peer.geometries)
        peer.send(
            {
                "type": "command",
                "request_id": "restore",
                "action": "load",
                "value": "walking",
            }
        )
        restored_scene = peer.until("scene")
        assert peer.geometries == {}
        peer.until("ack", request_id="restore")
        restored = peer.until("snapshot", session_id=restored_scene["session_id"])
        assert peer.geometry_frames_received == 2
        _assert_authoritative_snapshot(
            instance, restored_scene, restored, peer.geometries
        )
        peer.send({"type": "command", "request_id": "reset", "action": "reset"})
        reset_scene = peer.until("scene")
        peer.until("ack", request_id="reset")
        reset = peer.until("snapshot", session_id=reset_scene["session_id"])
        assert (
            reset["residents"][0][7]
            if encoding == worker_module.CITY_ROWS_ENCODING
            else reset["residents"][0]["trip"]
        ) is None
        assert peer.geometries == {}


@pytest.mark.parametrize(
    "encoding", [worker_module.CITY_ROUTES_ENCODING, worker_module.CITY_ROWS_ENCODING]
)
def test_route_definitions_survive_snapshot_coalescing_and_only_new_ids_are_sent(
    scenario,
    encoding,
):
    scenario["geography_manifest"] = "fixture-map.json"
    instance = CivicWorker(scenario, TOKEN)
    connection, receiver = socket.socketpair()
    try:
        instance.simulation.set_paused(True)
        instance.simulation.step_ticks(2500)
        client = Client(
            connection,
            time.monotonic(),
            authenticated=True,
            requested_snapshot_encoding=encoding,
        )
        instance.clients[connection] = client
        instance.selector.register(
            connection, worker_module.selectors.EVENT_READ, client
        )
        instance._publish_snapshots([client])
        instance.simulation.step_ticks(20)
        instance._publish_snapshots([client])
        messages = [json.loads(pending.data) for pending in client.outgoing]
        assert [message["type"] for message in messages] == [
            "trip_geometries",
            "snapshot",
        ]
        assert not client.outgoing[0].snapshot
        assert messages[-1]["tick"] == 2520
        assert (
            worker_module._active_trip_ids(messages[-1])[0]
            == messages[0]["geometries"][0]["id"]
        )
        assert len(client.known_trip_ids) == 1
    finally:
        instance.close()
        receiver.close()


def test_route_geometry_frames_are_batched_and_bounded(monkeypatch):
    monkeypatch.setattr(worker_module, "MAX_FRAME_BYTES", 300)
    definitions = [
        {
            "id": f"route-{i}",
            "points": [[0, 0, 0], [1, 1, 0]],
            "node_ids": ["a", "b"],
            "length_m": 1.41,
        }
        for i in range(8)
    ]
    frames, size = worker_module.trip_geometry_frames(definitions, "session")
    assert len(frames) > 1
    assert size == sum(len(frame) for frame in frames)
    assert all(len(frame) <= 301 for frame in frames)
    assert [
        definition for frame in frames for definition in json.loads(frame)["geometries"]
    ] == definitions
    with pytest.raises(ValueError, match="limit"):
        worker_module.trip_geometry_frames(
            [{**definitions[0], "points": [[1, 2, 3]] * 100}], "session"
        )


@pytest.mark.parametrize(
    "encoding", [worker_module.CITY_ROUTES_ENCODING, worker_module.CITY_ROWS_ENCODING]
)
def test_inactive_route_eviction_preserves_partial_old_snapshot_and_bounds_next_trip(
    scenario, monkeypatch, encoding
):
    scenario["geography_manifest"] = "fixture-map.json"
    instance = CivicWorker(scenario, TOKEN)
    connection, receiver = socket.socketpair()
    try:
        instance.simulation.set_paused(True)
        instance.simulation.step_ticks(2500)
        client = Client(
            connection,
            time.monotonic(),
            authenticated=True,
            requested_snapshot_encoding=encoding,
        )
        instance.clients[connection] = client
        instance.selector.register(
            connection, worker_module.selectors.EVENT_READ, client
        )
        instance._publish_snapshots([client])
        outbound_id = next(iter(client.known_trip_ids))
        monkeypatch.setattr(
            worker_module, "MAX_TRIP_GEOMETRY_BYTES", client.trip_geometry_bytes + 20
        )
        # The definition has reached the reader; the following snapshot is only
        # partially transmitted when an arrival replaces the authoritative state.
        sent_definition = client.outgoing.popleft()
        client.queued_bytes -= len(sent_definition.data)
        client.outgoing[0].offset = 7
        client.queued_bytes -= 7
        instance.simulation.step_ticks(500)
        instance._publish_snapshots([client])
        assert client.known_trip_ids == set()
        assert client.trip_geometry_bytes == 0
        assert [json.loads(frame.data)["type"] for frame in client.outgoing] == [
            "snapshot",
            "forget_trip_geometries",
            "snapshot",
        ]
        instance.simulation.step_ticks(7000)
        instance._publish_snapshots([client])
        assert connection in instance.clients
        assert len(client.known_trip_ids) == 1
        assert outbound_id not in client.known_trip_ids
        assert client.trip_geometry_bytes <= worker_module.MAX_TRIP_GEOMETRY_BYTES
        assert [json.loads(frame.data)["type"] for frame in client.outgoing] == [
            "snapshot",
            "forget_trip_geometries",
            "trip_geometries",
            "snapshot",
        ]
        assert client.outgoing[0].offset == 7
    finally:
        instance.close()
        receiver.close()


@pytest.mark.parametrize(
    "encoding", [worker_module.CITY_ROUTES_ENCODING, worker_module.CITY_ROWS_ENCODING]
)
def test_route_cache_limit_disconnects_only_the_slow_or_oversized_client(
    running, scenario, monkeypatch, encoding
):
    scenario["geography_manifest"] = "fixture-map.json"
    with running() as (instance, peer, thread):
        peer.hello(encoding)
        monkeypatch.setattr(worker_module, "MAX_TRIP_GEOMETRY_BYTES", 1)
        peer.command("step", 2500)
        assert peer.until("error")["code"] == "geometry_cache_limit"
        with pytest.raises(EOFError):
            peer.receive()
        assert thread.is_alive()
        assert instance.simulation.tick == 2500


def test_async_save_captures_exact_tick_while_controls_and_snapshots_continue(
    running, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    writer = worker_module.write_captured_checkpoint
    writer_threads = []

    def delayed_write(capture, path):
        writer_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5), "test did not release checkpoint writer"
        return writer(capture, path)

    monkeypatch.setattr(worker_module, "write_captured_checkpoint", delayed_write)
    with running() as (instance, peer, thread):
        scene, _ = peer.hello(command_status=True)
        peer.command("step", 2500)
        peer.until("snapshot", tick=2500)
        peer.send({"type": "command", "request_id": "slow-save", "action": "save"})
        try:
            status = peer.until(
                "command_status", request_id="slow-save", status="pending"
            )
            assert status["tick"] == 2500
            assert entered.wait(1)
            assert writer_threads != [thread.ident]
            assert peer.command("step", 500)["tick"] == 3000
            assert (
                peer.until("snapshot", tick=3000)["residents"][0]["activity"]
                == "at_work"
            )
            assert peer.command("speed", 60)["tick"] == 3000
            assert (
                peer.command("reset", response="error")["code"] == "operation_pending"
            )
            assert peer.command("load", response="error")["code"] == "operation_pending"
            assert peer.command("save", response="error")["code"] == "operation_pending"
            progress = peer.until(
                "command_status", request_id="slow-save", status="running"
            )
            assert progress["elapsed_seconds"] >= 1
            assert instance.session_id == scene["session_id"]
            assert instance.simulation.tick == 3000
        finally:
            release.set()
        ack = peer.until("ack", request_id="slow-save")
        assert ack["tick"] == ack["captured_tick"] == 2500
        assert ack["session_id"] == scene["session_id"]
        assert instance.simulation.tick == 3000
        saved = worker_module.load_checkpoint(instance.save_dir / "quick.json")
        assert saved.tick == 2500
        assert saved.speed == 1
        assert saved.paused is True
        assert saved.snapshot()["residents"][0]["activity"] == "walking_to_work"


@pytest.mark.parametrize("action", ["load", "population"])
@pytest.mark.parametrize(
    "encoding", [worker_module.CITY_ROUTES_ENCODING, worker_module.CITY_ROWS_ENCODING]
)
def test_async_candidate_preparation_preserves_live_day_until_main_loop_commit(
    running, scenario, monkeypatch, action, encoding
):
    from civic_center import city_scenario

    scenario["geography_manifest"] = "fixture-map.json"
    entered, release = threading.Event(), threading.Event()
    replacement = deepcopy(scenario)
    replacement["label"] = "Prepared replacement"
    replacement["residents"] = [
        dict(scenario["residents"][0], id=f"person-{i}") for i in range(20)
    ]

    def prepare(*_args, **_kwargs):
        entered.set()
        assert release.wait(5), "test did not release candidate construction"
        if action == "population":
            return replacement
        model = CivicSimulation(replacement)
        model.step_ticks(400)
        model.set_paused(True)
        model.set_speed(4)
        return model

    monkeypatch.setattr(
        city_scenario if action == "population" else worker_module,
        "build_city_scenario" if action == "population" else "load_checkpoint",
        prepare,
    )
    with running() as (instance, peer, _thread):
        scene, _ = peer.hello(encoding, command_status=True)
        original = instance.simulation
        peer.send(
            {
                "type": "command",
                "request_id": "prepare",
                "action": action,
                "value": 20 if action == "population" else "quick",
            }
        )
        try:
            peer.until("command_status", request_id="prepare", status="pending")
            assert entered.wait(1)
            assert peer.command("step", 10)["tick"] == 10
            assert peer.until("snapshot", tick=10)["session_id"] == scene["session_id"]
            assert (
                peer.command("population", 20, response="error")["code"]
                == "operation_pending"
            )
            assert instance.simulation is original
            reconnect = Peer(instance.port)
            try:
                active_scene, active_state = reconnect.hello(encoding)
                assert active_scene == scene
                assert active_state["tick"] == 10
            finally:
                reconnect.close()
        finally:
            release.set()
        next_scene = peer.until("scene")
        ack = peer.until("ack", request_id="prepare")
        snapshot = peer.until("snapshot", session_id=next_scene["session_id"])
        assert instance.simulation is not original
        assert next_scene["session_id"] != scene["session_id"]
        assert next_scene["scenario"]["label"] == "Prepared replacement"
        assert len(snapshot["residents"]) == 20
        assert ack["session_id"] == next_scene["session_id"]
        assert snapshot["tick"] == ack["tick"] == (0 if action == "population" else 400)
        if action == "load":
            assert snapshot["paused"] is True
            assert snapshot["speed"] == 4


def test_background_failure_preserves_day_and_releases_operation_slot(
    running, monkeypatch
):
    def failure(_path):
        raise RuntimeError("fixture background failure")

    monkeypatch.setattr(worker_module, "load_checkpoint", failure)
    with running() as (instance, peer, thread):
        scene, _ = peer.hello(command_status=True)
        peer.send({"type": "command", "request_id": "bad-load", "action": "load"})
        peer.until("command_status", request_id="bad-load", status="pending")
        error = peer.until("error", request_id="bad-load")
        assert "fixture background failure" in error["message"]
        assert instance.session_id == scene["session_id"]
        assert instance._pending_job is None
        assert peer.command("step", 1)["tick"] == 1
        assert thread.is_alive()


def test_shutdown_during_preparation_does_not_commit_candidate(
    running, scenario, monkeypatch
):
    entered, release = threading.Event(), threading.Event()

    def delayed(_path):
        entered.set()
        assert release.wait(5)
        return CivicSimulation(scenario)

    monkeypatch.setattr(worker_module, "load_checkpoint", delayed)
    with running() as (instance, peer, thread):
        peer.hello(command_status=True)
        original = instance.simulation
        peer.send({"type": "command", "request_id": "loading", "action": "load"})
        peer.until("command_status", request_id="loading", status="pending")
        assert entered.wait(1)
        job = instance._pending_job
        try:
            peer.command("shutdown")
            thread.join(2)
            assert not thread.is_alive()
            assert instance.simulation is original
        finally:
            release.set()
            job.thread.join(2)
        assert instance.simulation is original


def test_spawned_save_load_and_population_transfer_validated_models(running, scenario):
    scenario["buildings"][0]["footprint"] = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    with running(job_backend="process") as (instance, peer, _thread):
        original_scene, _ = peer.hello(command_status=True)
        peer.command("step", 2500)
        peer.until("snapshot", tick=2500)
        ack = peer.command("save", "spawned")
        assert ack["captured_tick"] == 2500
        assert instance.last_job_metrics["pid"] != worker_module.os.getpid()
        peer.command("step", 500)
        peer.until("snapshot", tick=3000)
        peer.send(
            {
                "type": "command",
                "request_id": "load-process",
                "action": "load",
                "value": "spawned",
            }
        )
        restored_scene = peer.until("scene")
        ack = peer.until("ack", request_id="load-process")
        restored = peer.until("snapshot", session_id=restored_scene["session_id"])
        assert restored_scene["session_id"] != original_scene["session_id"]
        assert restored["tick"] == ack["tick"] == 2500
        assert restored["residents"][0]["trip"]["points"] == [
            [0, 0, 0],
            [2, 0, 0],
            [2, 3, 0],
        ]
        assert instance.last_job_metrics["pickle_bytes"] > 0
        peer.send(
            {
                "type": "command",
                "request_id": "population-process",
                "action": "population",
                "value": 20,
            }
        )
        scene = peer.until("scene")
        peer.until("ack", request_id="population-process")
        snapshot = peer.until("snapshot", session_id=scene["session_id"])
        assert len(snapshot["residents"]) == 20
        assert snapshot["tick"] == 0


def _delayed_spawned_writer(connection, _action, payload):
    """Test child proves cancellation owns a real descendant before its write."""
    _capture, path = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".started").write_text("started", encoding="utf-8")
    time.sleep(3)
    path.write_text("unexpected late write", encoding="utf-8")
    connection.close()


def test_shutdown_terminates_and_joins_owned_job_before_save_can_write(
    running, monkeypatch
):
    monkeypatch.setattr(worker_module, "_process_job_main", _delayed_spawned_writer)
    with running(job_backend="process") as (instance, peer, thread):
        peer.hello(command_status=True)
        target = instance.save_dir / "protected.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("existing save", encoding="utf-8")
        peer.send(
            {
                "type": "command",
                "request_id": "pending-save",
                "action": "save",
                "value": "protected",
            }
        )
        peer.until("command_status", request_id="pending-save", status="pending")
        deadline = time.monotonic() + 2
        while (
            not target.with_suffix(".started").exists() and time.monotonic() < deadline
        ):
            peer.until("snapshot")
        assert target.with_suffix(".started").exists()
        job = instance._pending_job
        process = job.process
        assert process.is_alive()
        peer.command("shutdown")
        thread.join(2)
        assert not thread.is_alive()
        assert not process.is_alive()
        assert not job.thread.is_alive()
        assert target.read_text(encoding="utf-8") == "existing save"


def test_oversized_local_process_transfer_leaves_current_day_intact(
    running, scenario, monkeypatch
):
    with running(job_backend="process") as (instance, peer, thread):
        scene, _ = peer.hello(command_status=True)
        save_checkpoint(CivicSimulation(scenario), instance.save_dir / "fixture.json")
        original = instance.simulation
        monkeypatch.setattr(worker_module, "MAX_JOB_TRANSFER_BYTES", 1024)
        error = peer.command("load", "fixture", response="error")
        assert error["message"]
        assert instance.simulation is original
        assert instance.session_id == scene["session_id"]
        assert thread.is_alive()
