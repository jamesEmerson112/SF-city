"""Authenticated local NDJSON transport for the deterministic civic simulation.

The simulation owns all world state. This worker translates elapsed wall time
into simulation ticks and publishes complete snapshots to disposable viewers.
"""

from __future__ import annotations

import argparse
import copy
import hmac
import ipaddress
import json
import math
import multiprocessing
import os
import pickle
import queue
import re
import selectors
import socket
import tempfile
import threading
import time
import uuid
import weakref
import zlib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from civic_center.checkpoint import (
    PreparedCheckpointCapture,
    capture_checkpoint,
    load_checkpoint,
    prepare_checkpoint_capture,
    write_captured_checkpoint,
)
from civic_center.model import CivicSimulation
from civic_center.point_transport import PointRequest, PointTransportService, PoolFrame
from civic_center.population import (
    MAX_POPULATION,
    MIN_POPULATION,
    PopulationDelta,
    commit_population,
    frozen_population_view,
    prepare_population_delta,
    preview_population,
    validate_population,
    world_identity,
)
from civic_center.scenario import load_scenario, make_scenario
from civic_center.shared_geometry import SharedGeometryEncoder

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_QUEUE_BYTES = 32 * 1024 * 1024
MAX_STEP_TICKS = 86400 * 200
POPULATIONS = (1, 20, 200, 1000, 5000)
SPEEDS = (1, 4, 60, 600)
SNAPSHOT_INTERVAL = 0.1
AUTH_TIMEOUT = 5.0
MAX_CLIENTS = 16
VISUAL_ASSET = "res://assets/civic-center.glb"
DEFAULT_SAVE_DIR = Path(__file__).resolve().parents[1] / ".local" / "civic" / "saves"
SLOT_NAME = re.compile(r"[A-Za-z0-9_-]{1,48}")
CITY_DYNAMIC_ENCODING = "city-dynamic-v1"
CITY_ROUTES_ENCODING = "city-routes-v1"
CITY_ROWS_ENCODING = "city-rows-v1"
CITY_POINTS_ENCODING = "city-points-v1"
POINT_STAGE_BYTES = 256 * 1024
MAX_TRIP_GEOMETRY_BYTES = 32 * 1024 * 1024
MAX_TRIP_DEFINITIONS = 20000
MAX_JOB_TRANSFER_BYTES = 192 * 1024 * 1024


def transport_mode(scenario: dict[str, Any], requested: str) -> tuple[bool, bool, bool]:
    compact = bool(scenario.get("geography_manifest")) and requested in (
        CITY_DYNAMIC_ENCODING,
        CITY_ROUTES_ENCODING,
        CITY_ROWS_ENCODING,
    )
    return (
        compact,
        compact and requested in (CITY_ROUTES_ENCODING, CITY_ROWS_ENCODING),
        compact and requested == CITY_ROWS_ENCODING,
    )


def _snapshot_rows(state: dict[str, Any]) -> None:
    """Fixed city-rows-v1 columns; retain every ID and original numeric value."""
    residents = []
    for person in state["residents"]:
        trip = person["trip"]
        if trip is not None:
            trip = [
                trip["id"],
                trip["segment_index"],
                trip["segment_progress"],
                trip["departure_tick"],
                trip["arrival_tick"],
                trip["origin_id"],
                trip["destination_id"],
            ]
        residents.append(
            [
                person["id"],
                person["activity"],
                person["building_id"],
                person["position"],
                person["heading"],
                person["visible"],
                person["moving"],
                trip,
                person["blocked_reason"],
            ]
        )
    state["residents"] = residents
    state["buildings"] = [
        [building["id"], building["occupancy"], building["resident_ids"]]
        for building in state["buildings"]
    ]


def _active_trip_ids(message: dict[str, Any]) -> list[str]:
    if message.get("encoding") == CITY_ROWS_ENCODING:
        return [row[7][0] for row in message["residents"] if row[7] is not None]
    return [
        person["trip"]["id"]
        for person in message["residents"]
        if person["trip"] is not None
    ]


def encode_frame(message: dict[str, Any]) -> bytes:
    """Encode exactly one JSON object, never JSON NaN/Infinity extensions."""
    frame = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError("outgoing frame exceeds the 16 MiB limit")
    return frame + b"\n"


def presentation_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Send city presentation metadata without duplicating the core's full graph.

    Routes travel in authoritative resident snapshots; geographic street geometry
    comes from the local map. This projection must never become a saved scenario.
    """
    if not scenario.get("geography_manifest"):
        return scenario
    entrance_ids = {building["entrance_node_id"] for building in scenario["buildings"]}
    projection = {
        **scenario,
        "nodes": [
            {"id": node["id"], "position": node["position"]}
            for node in scenario["nodes"]
            if node["id"] in entrance_ids
        ],
        "edges": [],
        "presentation_only": True,
        "authoritative_scenario_sha256": scenario.get("sha256"),
        "routing_graph_counts": {
            "nodes": len(scenario["nodes"]),
            "edges": len(scenario["edges"]),
        },
    }
    projection.pop("sha256", None)
    return projection


def scene_message(
    scenario: dict[str, Any],
    session_id: str,
    *,
    compact: bool = False,
    trip_references: bool = False,
    rows: bool = False,
    world_fingerprint: str | None = None,
) -> dict[str, Any]:
    if rows and not (compact and trip_references):
        raise ValueError("resident rows require static metadata and reliable trips")
    message = {
        "type": "scene",
        "protocol_version": PROTOCOL_VERSION,
        "session_id": session_id,
        "scenario": presentation_scenario(scenario),
        "visual_asset": VISUAL_ASSET,
        "capabilities": {
            "set_population": True,
            "set_population_session_guard": True,
            "population_min": MIN_POPULATION,
            "population_max": MAX_POPULATION,
        },
        "population": len(scenario["residents"]),
        "roster_revision": scenario.get("roster_revision", 0),
        "world_identity": world_fingerprint or world_identity(scenario),
    }
    if compact:
        message["snapshot_encoding"] = (
            CITY_ROWS_ENCODING
            if rows
            else CITY_ROUTES_ENCODING if trip_references else CITY_DYNAMIC_ENCODING
        )
    return message


def snapshot_message(
    simulation: CivicSimulation,
    session_id: str,
    sequence: int,
    *,
    compact: bool = False,
    trip_references: bool = False,
    rows: bool = False,
) -> dict[str, Any]:
    if rows and not (compact and trip_references):
        raise ValueError("resident rows require static metadata and reliable trips")
    state = simulation.snapshot(
        include_static=not compact, include_trip_geometry=not trip_references
    )
    if rows:
        _snapshot_rows(state)
    message = {
        **state,
        "type": "snapshot",
        "protocol_version": PROTOCOL_VERSION,
        "session_id": session_id,
        "sequence": sequence,
        "population": len(simulation._sources),
        "roster_revision": simulation.roster_revision,
        "world_identity": simulation.world_identity,
        "population_change": simulation.population_change,
        "worker_metrics": getattr(simulation, "worker_metrics", {}),
    }
    if compact:
        message["encoding"] = (
            CITY_ROWS_ENCODING
            if rows
            else CITY_ROUTES_ENCODING if trip_references else CITY_DYNAMIC_ENCODING
        )
    return message


def trip_geometry_frames(
    definitions: list[dict[str, Any]],
    session_id: str,
) -> tuple[list[bytes], int]:
    """Split reliable geometry definitions without exceeding any frame limit."""
    prefix = (
        encode_frame(
            {
                "type": "trip_geometries",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": session_id,
            }
        )[:-2]
        + b',"geometries":['
    )
    suffix = b"]}\n"
    frames: list[bytes] = []
    records: list[bytes] = []
    frame_size = len(prefix) + len(suffix)
    for definition in definitions:
        encoded = encode_frame(definition)[:-1]
        if len(prefix) + len(encoded) + len(suffix) > MAX_FRAME_BYTES + 1:
            raise ValueError("one trip geometry exceeds the transport frame limit")
        if frame_size + len(encoded) + bool(records) > MAX_FRAME_BYTES + 1:
            frames.append(prefix + b",".join(records) + suffix)
            records = []
            frame_size = len(prefix) + len(suffix)
        frame_size += len(encoded) + bool(records)
        records.append(encoded)
    if records:
        frames.append(prefix + b",".join(records) + suffix)
    return frames, sum(len(frame) for frame in frames)


@dataclass
class PreparedSession:
    """Trusted local process result; never accepted through the TCP protocol."""

    simulation: CivicSimulation
    scenario_json: bytes
    session_id: str
    scenes: dict[tuple[bool, bool, bool], bytes]
    snapshots: dict[tuple[bool, bool, bool], bytes]
    invalid_modes: dict[tuple[bool, bool, bool], str]
    geometry_frames: list[bytes]
    geometry_sizes: dict[str, int]
    reference_scenes: dict[tuple[bool, bool, bool], bytes] = field(default_factory=dict)
    points_validated: bool = False


def prepare_session(
    simulation: CivicSimulation, *, points: bool = False
) -> PreparedSession:
    preparation = prepare_checkpoint_capture(simulation)
    session_id = str(uuid.uuid4())
    result = PreparedSession(
        simulation, preparation.scenario_json, session_id, {}, {}, {}, [], {}
    )
    if points and simulation.scenario.get("geography_manifest"):
        encoder = SharedGeometryEncoder(session_id)
        encoder.encode(simulation.capture_trip_geometries(simulation.active_trip_ids()))
        result.points_validated = True
    modes = [(False, False, False)]
    if simulation.scenario.get("geography_manifest"):
        modes.extend([(True, False, False), (True, True, False), (True, True, True)])
    for compact, references, rows in modes:
        mode = (compact, references, rows)
        try:
            result.scenes[mode] = encode_frame(
                scene_message(
                    simulation.scenario,
                    session_id,
                    compact=compact,
                    trip_references=references,
                    rows=rows,
                    world_fingerprint=simulation.world_identity,
                )
            )
            message = snapshot_message(
                simulation,
                session_id,
                1,
                compact=compact,
                trip_references=references,
                rows=rows,
            )
            result.snapshots[mode] = encode_frame(message)
            if references:
                result.reference_scenes[mode] = result.scenes[mode]
                ids = _active_trip_ids(message)
                if not result.geometry_frames:
                    definitions = simulation.trip_geometries(ids)
                    result.geometry_frames, _ = trip_geometry_frames(
                        definitions, session_id
                    )
                    result.geometry_sizes = {
                        record["id"]: len(encode_frame(record)) - 1
                        for record in definitions
                    }
                if (
                    len(ids) > MAX_TRIP_DEFINITIONS
                    or sum(result.geometry_sizes.values()) > MAX_TRIP_GEOMETRY_BYTES
                ):
                    raise ValueError(
                        "saved active trip geometries exceed the connection cache limit"
                    )
        except ValueError as exc:
            result.invalid_modes[mode] = str(exc)
            result.scenes.pop(mode, None)
            result.snapshots.pop(mode, None)
    return result


@dataclass
class PreparedPopulation:
    delta: PopulationDelta
    session: PreparedSession
    route_cache: dict
    scenario_values: int


def _prepare_live_population(
    frozen: CivicSimulation, target: int, *, points: bool
) -> PreparedPopulation:
    """Prepare static roster/scene bytes and all-phase route budgets off the owner loop."""
    delta = prepare_population_delta(frozen, target)
    candidate = preview_population(frozen, delta)
    if points and candidate.scenario.get("geography_manifest"):
        # Validate a complete outbound cohort and then its complete return cohort.
        # The retained coordinate pool includes both directions. Reserve independent
        # per-resident maxima as well, so a mixture cannot exceed reference budgets.
        from civic_center.shared_geometry import (
            MAX_NODE_REFERENCES,
            MAX_POINT_REFERENCES,
        )

        encoder = SharedGeometryEncoder("population-preflight".ljust(128, "-"))
        outbound, inbound = [], []
        references = nodes = 0
        for identity, source in candidate._sources.items():
            definitions = []
            for direction, origin, destination in (
                ("outbound", source["home_id"], source["work_id"]),
                ("return", source["work_id"], source["home_id"]),
            ):
                route = candidate.graph.route(
                    candidate._buildings[origin]["entrance_node_id"],
                    candidate._buildings[destination]["entrance_node_id"],
                )
                if route is not None:
                    definitions.append(
                        {
                            "id": f"{identity}:{direction}:9007199254740991",
                            "points": route.points,
                            "node_ids": route.node_ids,
                            "length_m": route.length,
                        }
                    )
                else:
                    definitions.append(None)
            references += max(
                (len(item["points"]) for item in definitions if item), default=0
            )
            nodes += max(
                (len(item["node_ids"]) for item in definitions if item), default=0
            )
            if definitions[0]:
                outbound.append(definitions[0])
            if definitions[1]:
                inbound.append(definitions[1])
        if references > MAX_POINT_REFERENCES or nodes > MAX_NODE_REFERENCES:
            raise ValueError(
                "Requested population exceeds shared route reference budgets"
            )
        encoder.encode(outbound)
        path_sizes = {
            record.identity.rsplit(":", 2)[0]: len(encode_frame(record.record()))
            + encoder._path_frame_overhead
            for record in encoder._paths.values()
        }
        encoder.encode(inbound, retire_ids=[item["id"] for item in outbound])
        for record in encoder._paths.values():
            identity = record.identity.rsplit(":", 2)[0]
            path_sizes[identity] = max(
                path_sizes.get(identity, 0),
                len(encode_frame(record.record())) + encoder._path_frame_overhead,
            )
        from civic_center.shared_geometry import MAX_CACHE_BYTES, WIRE_ENVELOPE_RESERVE

        if (
            encoder.stats()["pool_wire_bytes"]
            + sum(path_sizes.values())
            + WIRE_ENVELOPE_RESERVE
            > MAX_CACHE_BYTES
        ):
            raise ValueError(
                "Requested population exceeds mixed-direction route cache budget"
            )
    prepared = prepare_session(candidate, points=points)
    from civic_center.checkpoint import _validate_tree

    scenario_values = _validate_tree({"scenario": candidate.scenario})
    return PreparedPopulation(
        delta, prepared, dict(candidate.graph._cache), scenario_values
    )


def _append_frame_fields(frame: bytes, fields: dict) -> bytes:
    result = (
        frame[:-2]
        + b","
        + json.dumps(fields, separators=(",", ":"), allow_nan=False).encode()[1:]
        + b"\n"
    )
    if len(result) > MAX_FRAME_BYTES + 1:
        raise ValueError("Population scene exceeds the frame limit")
    return result


def _process_job_main(connection: Any, action: str, payload: Any) -> None:
    """Child endpoint of a parent-owned anonymous pipe, with bounded pickle IPC."""
    started = time.monotonic()
    try:
        if action == "save":
            capture, path = payload
            result = write_captured_checkpoint(capture, path)
        elif action == "load":
            path = payload["path"] if isinstance(payload, dict) else payload
            result = prepare_session(
                load_checkpoint(path),
                points=isinstance(payload, dict) and payload.get("points", False),
            )
        elif action == "set_population":
            frozen, target, points = payload
            result = _prepare_live_population(frozen, target, points=points)
        elif action == "population":
            geography, terrain, landuse, population, seed, *point_option = payload
            if geography:
                from civic_center.city_scenario import build_city_scenario

                options = {
                    "population": population,
                    "seed": seed,
                    "terrain_path": terrain,
                }
                if landuse:
                    options["landuse_path"] = landuse
                scenario = build_city_scenario(geography, **options)
            else:
                scenario = make_scenario(population=population, seed=seed)
            result = prepare_session(
                CivicSimulation(scenario), points=bool(point_option and point_option[0])
            )
        else:
            raise ValueError("unknown isolated operation")
        prepared_at = time.monotonic()
        encoded = pickle.dumps(
            {"ok": True, "result": result, "child_work_seconds": prepared_at - started},
            protocol=5,
        )
        if len(encoded) > MAX_JOB_TRANSFER_BYTES:
            raise ValueError(
                "prepared operation exceeds the 192 MiB local transfer limit"
            )
    except Exception as exc:
        encoded = pickle.dumps(
            {"ok": False, "message": str(exc), "io_error": isinstance(exc, OSError)}
        )
    try:
        # Compression reduces anonymous-pipe copying; the decompressed size is
        # independently bounded by the parent before it unpickles trusted data.
        connection.send_bytes(zlib.compress(encoded, level=1))
    finally:
        connection.close()


@dataclass
class PendingFrame:
    data: bytes
    snapshot: bool = False
    offset: int = 0
    scene_barrier: bool = False
    priority: bool = False


@dataclass(eq=False)
class Client:
    sock: socket.socket
    accepted_at: float
    incoming: bytearray = field(default_factory=bytearray)
    outgoing: deque[PendingFrame] = field(default_factory=deque)
    legacy_bootstrap: deque[PendingFrame] = field(default_factory=deque)
    queued_bytes: int = 0
    authenticated: bool = False
    close_after_flush: bool = False
    command_client_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    population_session_guard: bool = False
    requested_snapshot_encoding: str = ""
    known_trip_ids: set[str] = field(default_factory=set)
    trip_geometry_sizes: dict[str, int] = field(default_factory=dict)
    trip_geometry_bytes: int = 0
    wants_command_status: bool = False
    requested_route_encoding: str = ""
    point_scene_session: str = ""
    point_frame_index: int = 0
    point_cursor: int = 0
    point_snapshot_version: int = -1
    point_status: str = ""
    next_point_status: float = 0.0

    def enqueue(
        self,
        frame: bytes,
        *,
        snapshot: bool = False,
        scene_barrier: bool = False,
        priority: bool = False,
    ) -> bool:
        """Coalesce unsent snapshots, preserving partial frames and control replies."""
        if snapshot:
            retained = deque()
            for pending in self.outgoing:
                if pending.snapshot and pending.offset == 0:
                    self.queued_bytes -= len(pending.data)
                else:
                    retained.append(pending)
            self.outgoing = retained
        if self.queued_bytes + len(frame) > MAX_QUEUE_BYTES:
            return False
        pending = PendingFrame(
            frame, snapshot=snapshot, scene_barrier=scene_barrier, priority=priority
        )
        if priority:
            insertion = 0
            for index, queued in enumerate(self.outgoing):
                if queued.offset or queued.scene_barrier or queued.priority:
                    insertion = index + 1
            self.outgoing.insert(insertion, pending)
        else:
            self.outgoing.append(pending)
        self.queued_bytes += len(frame)
        return True


@dataclass
class PendingJob:
    client: Client
    request: dict[str, Any]
    session_id: str
    tick: int
    slot: str | None
    started_at: float
    result: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    thread: threading.Thread | None = None
    next_status: float = 0.0
    process: Any = None
    lifecycle_lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: threading.Event = field(default_factory=threading.Event)
    metrics: dict[str, Any] = field(default_factory=dict)


class CivicWorker:
    """One authoritative simulation, with bounded nonblocking loopback clients."""

    def __init__(
        self,
        scenario: dict[str, Any],
        token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        ready_file: str | Path | None = None,
        save_dir: str | Path | None = None,
        simulation: CivicSimulation | None = None,
        job_backend: str = "process",
    ) -> None:
        address = ipaddress.ip_address(host)
        if not address.is_loopback:
            raise ValueError("the civic worker only binds to a loopback address")
        if not isinstance(token, str) or not token:
            raise ValueError("a nonempty authentication token is required")
        if job_backend not in ("thread", "process"):
            raise ValueError("job_backend must be thread or process")
        self.job_backend = job_backend
        self.last_job_metrics: dict[str, Any] = {}
        self._population_responses: dict[tuple[str, str], tuple[tuple, dict]] = {}
        self._advance_ms = 0.0
        self._advanced_ticks = 0
        self._advance_wall = 0.0
        self._snapshot_ms = 0.0
        self._encode_ms = 0.0
        self._snapshot_bytes = 0
        self._snapshots_encoded = 0
        self.simulation = (
            simulation if simulation is not None else CivicSimulation(scenario)
        )
        # Freeze scenario bytes before readiness; later save captures contain
        # only detached dynamic state and never serialize the full map here.
        self._checkpoint_preparation = prepare_checkpoint_capture(self.simulation)
        self.scenario = self.simulation.scenario
        self.seed = self.scenario.get("seed", 7)
        self.tick_hz = float(self.simulation.tick_hz)
        if not math.isfinite(self.tick_hz) or self.tick_hz <= 0:
            raise ValueError("scenario tick_hz must be positive and finite")
        self._token = token.encode("utf-8")
        self.ready_file = Path(ready_file) if ready_file else None
        self.save_dir = Path(
            save_dir if save_dir is not None else DEFAULT_SAVE_DIR
        ).resolve()
        self.session_id = str(uuid.uuid4())
        self.sequence = 0
        self._scene_frames: dict[tuple[bool, bool, bool], bytes] = {}
        self.selector = selectors.DefaultSelector()
        self.listener = socket.socket(
            socket.AF_INET6 if address.version == 6 else socket.AF_INET,
            socket.SOCK_STREAM,
        )
        try:
            self.listener.bind((host, port))
            self.listener.listen(MAX_CLIENTS)
            self.listener.setblocking(False)
            self.port = self.listener.getsockname()[1]
            self.selector.register(self.listener, selectors.EVENT_READ)
        except BaseException:
            self.listener.close()
            self.selector.close()
            raise
        self.clients: dict[socket.socket, Client] = {}
        self._stop = threading.Event()
        self._shutdown_deadline: float | None = None
        self._last_time = time.monotonic()
        self._tick_fraction = 0.0
        self._next_snapshot = self._last_time
        self._closed = False
        self._pending_job: PendingJob | None = None
        self._point_service: PointTransportService | None = None
        self._point_pool: list[PoolFrame] = []
        self._point_pool_bytes = 0
        self._point_paths: dict[str, bytes] = {}
        self._point_active: frozenset[str] = frozenset()
        self._point_ids: tuple[str, ...] = ()
        self._point_state: dict[str, Any] | None = None
        self._point_version = 0
        self._point_snapshots: dict[bool, bytes] = {}
        self._point_scenes: dict[bool, bytes] = {}
        self._point_stats: dict[str, Any] = {}

    def ready_message(self) -> dict[str, Any]:
        return {
            "type": "ready",
            "protocol_version": PROTOCOL_VERSION,
            "port": self.port,
            "pid": os.getpid(),
        }

    def _publish_ready(self) -> None:
        ready = self.ready_message()
        if self.ready_file is not None:
            self.ready_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=self.ready_file.name + ".",
                suffix=".tmp",
                dir=self.ready_file.parent,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(ready, stream, separators=(",", ":"))
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.ready_file)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        print(json.dumps(ready, separators=(",", ":")), flush=True)

    def run(self) -> None:
        try:
            self._publish_ready()
            self._last_time = time.monotonic()
            self._next_snapshot = self._last_time
            while not self._stop.is_set():
                now = time.monotonic()
                if self._shutdown_deadline is not None:
                    if now >= self._shutdown_deadline or not any(
                        client.outgoing for client in self.clients.values()
                    ):
                        break
                else:
                    self._advance_elapsed(now)
                    self._poll_points()
                    self._poll_job()
                    if now >= self._next_snapshot:
                        self._broadcast_snapshot()
                        self._next_snapshot = now + SNAPSHOT_INTERVAL
                    for client in list(self.clients.values()):
                        if (
                            not client.authenticated
                            and now - client.accepted_at > AUTH_TIMEOUT
                        ):
                            self._close_client(client)
                timeout = min(0.02, max(0.0, self._next_snapshot - time.monotonic()))
                if self._shutdown_deadline is not None:
                    timeout = 0.02
                for key, events in self.selector.select(timeout):
                    if key.fileobj is self.listener:
                        self._accept()
                        continue
                    client = key.data
                    if events & selectors.EVENT_READ:
                        self._read(client)
                    if client.sock in self.clients and events & selectors.EVENT_WRITE:
                        self._write(client)
        finally:
            self.close()

    def stop(self) -> None:
        """Ask a running worker to stop; the select timeout bounds response latency."""
        self._stop.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_pending_job()
        if self._point_service is not None:
            self._point_service.close()
            self._point_service = None
        for client in list(self.clients.values()):
            self._close_client(client)
        self.listener.close()
        self.selector.close()

    def _advance_elapsed(self, now: float) -> None:
        started = time.perf_counter()
        elapsed = max(0.0, now - self._last_time)
        self._last_time = now
        if self.simulation.paused:
            self._advance_ms = 0.0
            return
        self._advance_wall += elapsed
        due = self._tick_fraction + elapsed * self.tick_hz * self.simulation.speed
        count = int(due)
        self._tick_fraction = due - count
        if count:
            self.simulation.advance_ticks(count)
            self._advanced_ticks += count
        self._advance_ms = (time.perf_counter() - started) * 1000

    def _accept(self) -> None:
        for _ in range(MAX_CLIENTS):
            try:
                connection, _ = self.listener.accept()
            except (BlockingIOError, OSError):
                return
            if len(self.clients) >= MAX_CLIENTS or self._shutdown_deadline is not None:
                connection.close()
                continue
            connection.setblocking(False)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client = Client(connection, time.monotonic())
            self.clients[connection] = client
            self.selector.register(connection, selectors.EVENT_READ, client)

    def _close_client(self, client: Client) -> None:
        self.clients.pop(client.sock, None)
        try:
            self.selector.unregister(client.sock)
        except (KeyError, ValueError):
            pass
        client.sock.close()

    def _interest(self, client: Client) -> None:
        if client.sock not in self.clients:
            return
        if client.close_after_flush and not client.outgoing:
            self._close_client(client)
            return
        events = 0 if client.close_after_flush else selectors.EVENT_READ
        if client.outgoing:
            events |= selectors.EVENT_WRITE
        self.selector.modify(client.sock, events, client)

    def _queue(
        self,
        client: Client,
        frame: bytes,
        *,
        snapshot: bool = False,
        scene_barrier: bool = False,
        priority: bool = False,
    ) -> None:
        if client.sock not in self.clients or client.close_after_flush:
            return
        if not client.enqueue(
            frame,
            snapshot=snapshot,
            scene_barrier=scene_barrier,
            priority=priority and self._uses_points(client),
        ):
            self._close_client(client)
            return
        self._interest(client)

    def _error(
        self,
        client: Client,
        code: str,
        message: str,
        *,
        request: dict[str, Any] | None = None,
        close: bool = False,
    ) -> None:
        response: dict[str, Any] = {
            "type": "error",
            "protocol_version": PROTOCOL_VERSION,
            "code": code,
            "message": message,
        }
        if client.authenticated:
            response["session_id"] = self.session_id
        if request is not None:
            for name in ("request_id", "action"):
                if isinstance(request.get(name), str):
                    response[name] = request[name][:128]
        self._queue(client, encode_frame(response), priority=True)
        if close and client.sock in self.clients:
            client.close_after_flush = True
            self._interest(client)

    def _read(self, client: Client) -> None:
        if client.close_after_flush:
            return
        for _ in range(4):
            try:
                data = client.sock.recv(65536)
            except BlockingIOError:
                return
            except OSError:
                self._close_client(client)
                return
            if not data:
                self._close_client(client)
                return
            client.incoming.extend(data)
            while True:
                newline = client.incoming.find(b"\n")
                if newline < 0:
                    if len(client.incoming) > MAX_FRAME_BYTES:
                        self._error(
                            client,
                            "frame_too_large",
                            "frame exceeds the 16 MiB limit",
                            close=True,
                        )
                    break
                if newline > MAX_FRAME_BYTES:
                    self._error(
                        client,
                        "frame_too_large",
                        "frame exceeds the 16 MiB limit",
                        close=True,
                    )
                    return
                line = bytes(client.incoming[:newline])
                del client.incoming[: newline + 1]
                try:
                    message = json.loads(line.decode("utf-8"))
                    if not isinstance(message, dict):
                        raise ValueError("expected a JSON object")
                except (ValueError, UnicodeDecodeError, RecursionError):
                    self._error(
                        client,
                        "invalid_json",
                        "each frame must contain one UTF-8 JSON object",
                        close=True,
                    )
                    return
                self._handle(client, message)
                if client.sock not in self.clients or client.close_after_flush:
                    return
            if client.close_after_flush or len(data) < 65536:
                return

    def _write(self, client: Client) -> None:
        budget = 256 * 1024
        while client.outgoing and budget:
            pending = client.outgoing[0]
            try:
                sent = client.sock.send(
                    memoryview(pending.data)[pending.offset : pending.offset + budget]
                )
            except BlockingIOError:
                break
            except OSError:
                self._close_client(client)
                return
            if sent == 0:
                self._close_client(client)
                return
            pending.offset += sent
            client.queued_bytes -= sent
            budget -= sent
            if pending.offset == len(pending.data):
                client.outgoing.popleft()
        self._interest(client)

        if self._shutdown_deadline is None:
            self._pump_legacy_bootstrap(client)
            if self._uses_points(client):
                self._pump_points(client)

    def _stage_legacy_bootstrap(
        self, client: Client, geometry: list[bytes], snapshot: bytes
    ) -> None:
        """Retain bounded immutable frames separately, draining them in wire order.

        Legacy route geometry has its own 32 MiB cache budget. Its scene plus
        geometry need not fit simultaneously in the separate outgoing queue.
        No new snapshot is generated for this client until its definitions and
        captured snapshot have entered that queue in order.
        """
        client.legacy_bootstrap.extend(PendingFrame(frame) for frame in geometry)
        client.legacy_bootstrap.append(PendingFrame(snapshot, snapshot=True))
        self._pump_legacy_bootstrap(client)

    def _pump_legacy_bootstrap(self, client: Client) -> None:
        if client.sock not in self.clients or client.close_after_flush:
            return
        while client.legacy_bootstrap:
            frame = client.legacy_bootstrap[0]
            if client.queued_bytes and client.queued_bytes + len(frame.data) > min(
                POINT_STAGE_BYTES, MAX_QUEUE_BYTES
            ):
                return
            client.legacy_bootstrap.popleft()
            self._queue(client, frame.data, snapshot=frame.snapshot)
            if client.sock not in self.clients:
                return

    def _compact(self, client: Client) -> bool:
        return transport_mode(self.scenario, client.requested_snapshot_encoding)[0]

    def _trip_references(self, client: Client) -> bool:
        return transport_mode(self.scenario, client.requested_snapshot_encoding)[1]

    def _rows(self, client: Client) -> bool:
        return transport_mode(self.scenario, client.requested_snapshot_encoding)[2]

    def _uses_points(
        self, client: Client, scenario: dict[str, Any] | None = None
    ) -> bool:
        source = self.scenario if scenario is None else scenario
        return (
            client.requested_route_encoding == CITY_POINTS_ENCODING
            and transport_mode(source, client.requested_snapshot_encoding)[1]
        )

    def _reset_points(self) -> None:
        if self._point_service is not None:
            self._point_service.cancel()
        self._point_pool = []
        self._point_pool_bytes = 0
        self._point_paths = {}
        self._point_active = frozenset()
        self._point_ids = ()
        self._point_state = None
        self._point_version += 1
        self._point_snapshots.clear()
        self._point_scenes.clear()
        self._point_stats = {}

    def _queue_point_scene(self, client: Client) -> None:
        rows = self._rows(client)
        if rows not in self._point_scenes:
            base = self._scene(compact=True, trip_references=True, rows=rows)
            frame = base[:-2] + b',"route_geometry_encoding":"city-points-v1"}\n'
            if len(frame) > MAX_FRAME_BYTES + 1:
                raise ValueError("shared city scene exceeds the 16 MiB frame limit")
            self._point_scenes[rows] = frame
        self._queue(client, self._point_scenes[rows], scene_barrier=True)
        client.point_scene_session = self.session_id
        client.point_frame_index = client.point_cursor = 0
        client.point_snapshot_version = -1
        client.point_status = ""
        client.known_trip_ids.clear()
        client.trip_geometry_sizes.clear()
        client.trip_geometry_bytes = 0

    def _point_status_message(self, client: Client, status: str) -> None:
        now = time.monotonic()
        if status == client.point_status and (
            status == "ready" or now < client.next_point_status
        ):
            return
        client.point_status = status
        client.next_point_status = now + 1.0
        self._queue(
            client,
            encode_frame(
                {
                    "type": "geometry_status",
                    "protocol_version": 1,
                    "session_id": self.session_id,
                    "status": status,
                    "tick": self.simulation.tick,
                    "point_count": client.point_cursor,
                    "trip_count": len(client.known_trip_ids),
                }
            ),
            priority=status == "preparing",
        )

    def _point_ready(self, client: Client) -> bool:
        return (
            self._point_state is not None
            and client.point_scene_session == self.session_id
            and client.point_frame_index == len(self._point_pool)
            and client.known_trip_ids == self._point_active
        )

    def _request_points(self) -> None:
        if self._point_service is None:
            self._point_service = PointTransportService()
        if self._point_service.busy:
            return
        ids = self.simulation.active_trip_ids()
        if self._point_state is not None and frozenset(ids) == self._point_active:
            return
        state = self._capture_point_state()
        definitions = self.simulation.capture_trip_geometries(ids)
        cursor = (
            self._point_pool[-1].start + self._point_pool[-1].count
            if self._point_pool
            else 0
        )
        self._point_service.submit(
            PointRequest(
                self.session_id,
                state,
                definitions,
                ids,
                frozenset(self._point_paths),
                cursor,
            )
        )

    def _poll_points(self) -> None:
        if self._point_service is None:
            return
        result = self._point_service.poll()
        if result is None or result.session_id != self.session_id or result.cancelled:
            return
        clients = [
            client
            for client in self.clients.values()
            if client.authenticated and self._uses_points(client)
        ]
        try:
            if result.error:
                raise ValueError(result.error)
            cursor = (
                self._point_pool[-1].start + self._point_pool[-1].count
                if self._point_pool
                else 0
            )
            for frame in result.pool_frames:
                if frame.start != cursor or len(frame.data) > MAX_FRAME_BYTES + 1:
                    raise ValueError("prepared point pool has a gap or oversized frame")
                cursor += frame.count
            active = frozenset(result.active_ids)
            paths = {
                identity: frame
                for identity, frame in self._point_paths.items()
                if identity in active
            }
            paths.update(result.path_frames)
            if frozenset(paths) != active:
                raise ValueError(
                    "prepared shared paths do not match the captured active trips"
                )
            pool_bytes = self._point_pool_bytes + sum(
                len(frame.data) for frame in result.pool_frames
            )
            if pool_bytes + sum(map(len, paths.values())) > MAX_TRIP_GEOMETRY_BYTES:
                raise ValueError("shared route wire cache exceeds the 32 MiB limit")
        except ValueError as exc:
            for client in clients:
                self._error(client, "geometry_cache_limit", str(exc), close=True)
            return
        self._point_pool.extend(result.pool_frames)
        self._point_pool_bytes = pool_bytes
        self._point_paths = paths
        self._point_active = active
        self._point_ids = result.active_ids
        self._point_state = result.state
        self._point_stats = {
            **result.stats,
            "preparation_seconds": result.elapsed_seconds,
            "cached_frame_bytes": pool_bytes + sum(map(len, paths.values())),
        }
        # Capture the latest controls/pose when the completed geometry still
        # covers the live set. A newly departed trip requires another update.
        if frozenset(self.simulation.active_trip_ids()) == active:
            self._point_state = self._capture_point_state()
        self._point_version += 1
        self._point_snapshots.clear()
        for client in clients:
            self._pump_points(client)

    def _capture_point_state(self) -> dict:
        started = time.perf_counter()
        state = self.simulation.snapshot(
            include_static=False, include_trip_geometry=False
        )
        self._snapshot_ms = (time.perf_counter() - started) * 1000
        return state

    def _point_snapshot(self, rows: bool) -> bytes:
        if rows not in self._point_snapshots:
            self.sequence += 1
            message = {
                **self._point_state,
                "type": "snapshot",
                "protocol_version": 1,
                "session_id": self.session_id,
                "sequence": self.sequence,
                "encoding": CITY_ROWS_ENCODING if rows else CITY_ROUTES_ENCODING,
                "population": len(self.simulation._sources),
                "roster_revision": self.simulation.roster_revision,
                "world_identity": self.simulation.world_identity,
                "population_change": self.simulation.population_change,
            }
            if rows:
                _snapshot_rows(message)
            self._point_snapshots[rows] = self._encode_snapshot_frame(message)
        return self._point_snapshots[rows]

    def _stage_point_frame(
        self, client: Client, frame: bytes, *, snapshot: bool = False
    ) -> bool:
        # At most one large indivisible frame can exceed the soft watermark.
        # Source frames remain in the shared bounded cache, not in a second
        # per-client byte queue. Reserve room for control replies at all times.
        if client.queued_bytes and client.queued_bytes + len(frame) > POINT_STAGE_BYTES:
            return False
        self._queue(client, frame, snapshot=snapshot)
        return client.sock in self.clients

    def _pump_points(self, client: Client) -> None:
        if (
            self._shutdown_deadline is not None
            or client.sock not in self.clients
            or client.close_after_flush
        ):
            return
        if self._point_state is None or client.point_scene_session != self.session_id:
            self._point_status_message(client, "preparing")
            return
        expired = sorted(client.known_trip_ids - self._point_active)
        if expired:
            frame = encode_frame(
                {
                    "type": "forget_trip_geometries",
                    "protocol_version": 1,
                    "session_id": self.session_id,
                    "ids": expired,
                }
            )
            if not self._stage_point_frame(client, frame):
                return
            client.known_trip_ids.difference_update(expired)
        while client.point_frame_index < len(self._point_pool):
            frame = self._point_pool[client.point_frame_index]
            if frame.start != client.point_cursor:
                self._error(
                    client,
                    "geometry_cursor",
                    "shared coordinate cursor is inconsistent",
                    close=True,
                )
                return
            if not self._stage_point_frame(client, frame.data):
                self._point_status_message(client, "streaming")
                return
            client.point_frame_index += 1
            client.point_cursor += frame.count
        for identity in self._point_ids:
            if identity not in client.known_trip_ids:
                if not self._stage_point_frame(client, self._point_paths[identity]):
                    self._point_status_message(client, "streaming")
                    return
                client.known_trip_ids.add(identity)
        if client.point_snapshot_version != self._point_version:
            try:
                frame = self._point_snapshot(self._rows(client))
            except ValueError as exc:
                self._error(client, "frame_too_large", str(exc), close=True)
                return
            if not self._stage_point_frame(client, frame, snapshot=True):
                return
            client.point_snapshot_version = self._point_version
            self._point_status_message(client, "ready")

    def _publish_point_clients(
        self, clients: list[Client], *, force: bool = False
    ) -> None:
        self._request_points()
        active = frozenset(self.simulation.active_trip_ids())
        if (
            self._point_state is not None
            and active == self._point_active
            and any(self._point_ready(client) for client in clients)
        ):
            changed = any(
                self._point_state[name] != getattr(self.simulation, name)
                for name in ("tick", "paused", "speed")
            )
            if changed or force:
                self._point_state = self._capture_point_state()
                self._point_version += 1
                self._point_snapshots.clear()
        for client in clients:
            if self._point_state is None or active != self._point_active:
                self._point_status_message(client, "preparing")
            self._pump_points(client)

    def _scene(
        self,
        *,
        compact: bool = False,
        trip_references: bool = False,
        rows: bool = False,
    ) -> bytes:
        key = (compact, trip_references, rows)
        if key not in self._scene_frames:
            self._scene_frames[key] = encode_frame(
                scene_message(
                    self.scenario,
                    self.session_id,
                    world_fingerprint=self.simulation.world_identity,
                    compact=compact,
                    trip_references=trip_references,
                    rows=rows,
                )
            )
        return self._scene_frames[key]

    def _worker_metrics(self) -> dict:
        return {
            "monotonic_seconds": time.monotonic(),
            "advance_ms": round(self._advance_ms, 3),
            "advanced_ticks": self._advanced_ticks,
            "simulated_seconds_per_wall_second": (
                self._advanced_ticks / self.tick_hz / self._advance_wall
                if self._advance_wall > 0
                else None
            ),
            "requested_speed": self.simulation.speed,
            "paused": self.simulation.paused,
            "snapshot_ms": round(self._snapshot_ms, 3),
            "encode_ms": round(self._encode_ms, 3),
            "snapshot_bytes": self._snapshot_bytes,
            "snapshots_published": self._snapshots_encoded,
            "transport_queue_bytes": sum(
                client.queued_bytes for client in self.clients.values()
            ),
            "route_cache_entries": len(self.simulation.graph._cache),
            "geometry_cache_bytes": self._point_pool_bytes
            + sum(map(len, self._point_paths.values())),
            "measurement": "advance last call; achieved speed since current controls/roster; last encoded snapshot; encoded count excludes sequence-only updates",
        }

    def _encode_snapshot_frame(self, message: dict) -> bytes:
        message["worker_metrics"] = self._worker_metrics()
        started = time.perf_counter()
        frame = encode_frame(message)
        self._encode_ms = (time.perf_counter() - started) * 1000
        self._snapshot_bytes = len(frame)
        self._snapshots_encoded += 1
        return frame

    def _snapshot(self, *, compact: bool = False) -> bytes:
        self.sequence += 1
        return self._encode_snapshot_frame(
            snapshot_message(
                self.simulation, self.session_id, self.sequence, compact=compact
            )
        )

    def _broadcast_snapshot(self, *, force: bool = False) -> None:
        authenticated = [
            client
            for client in self.clients.values()
            if client.authenticated and not client.close_after_flush
        ]
        if not authenticated:
            return
        self._publish_snapshots(authenticated, force=force)

    def _publish_snapshots(self, clients: list[Client], *, force: bool = False) -> None:
        point_clients = [client for client in clients if self._uses_points(client)]
        if point_clients:
            self._publish_point_clients(point_clients, force=force)
        clients = [client for client in clients if not self._uses_points(client)]
        frames: dict[tuple[bool, bool, bool], bytes] = {}
        invalid_frames: dict[tuple[bool, bool, bool], str] = {}
        trip_ids: list[str] = []
        definitions: dict[str, dict[str, Any]] = {}
        for client in clients:
            if client.legacy_bootstrap:
                self._pump_legacy_bootstrap(client)
                continue
            key = transport_mode(self.scenario, client.requested_snapshot_encoding)
            compact, trip_references, rows = key
            if key not in frames and key not in invalid_frames:
                self.sequence += 1
                snapshot_started = time.perf_counter()
                message = snapshot_message(
                    self.simulation,
                    self.session_id,
                    self.sequence,
                    compact=compact,
                    trip_references=trip_references,
                    rows=rows,
                )
                try:
                    self._snapshot_ms = (time.perf_counter() - snapshot_started) * 1000
                    frames[key] = self._encode_snapshot_frame(message)
                except ValueError as exc:
                    invalid_frames[key] = str(exc)
                if trip_references:
                    trip_ids = _active_trip_ids(message)
            if key in invalid_frames:
                self._error(client, "frame_too_large", invalid_frames[key], close=True)
                continue
            if trip_references:
                expired = sorted(client.known_trip_ids - set(trip_ids))
                if expired:
                    self._queue(
                        client,
                        encode_frame(
                            {
                                "type": "forget_trip_geometries",
                                "protocol_version": PROTOCOL_VERSION,
                                "session_id": self.session_id,
                                "ids": expired,
                            }
                        ),
                    )
                    for trip_id in expired:
                        client.known_trip_ids.remove(trip_id)
                        client.trip_geometry_bytes -= client.trip_geometry_sizes.pop(
                            trip_id
                        )
                missing = [
                    trip_id
                    for trip_id in trip_ids
                    if trip_id not in client.known_trip_ids
                ]
                needed = [trip_id for trip_id in missing if trip_id not in definitions]
                if needed:
                    definitions.update(
                        (record["id"], record)
                        for record in self.simulation.trip_geometries(needed)
                    )
                try:
                    reliable, _wire_bytes = trip_geometry_frames(
                        [definitions[trip_id] for trip_id in missing], self.session_id
                    )
                    sizes = {
                        trip_id: len(encode_frame(definitions[trip_id])) - 1
                        for trip_id in missing
                    }
                    geometry_bytes = sum(sizes.values())
                    if (
                        len(client.known_trip_ids) + len(missing) > MAX_TRIP_DEFINITIONS
                        or client.trip_geometry_bytes + geometry_bytes
                        > MAX_TRIP_GEOMETRY_BYTES
                    ):
                        raise ValueError(
                            "trip geometry cache reached its limit; reconnect to load only current routes"
                        )
                except ValueError as exc:
                    self._error(client, "geometry_cache_limit", str(exc), close=True)
                    continue
                client.known_trip_ids.update(missing)
                client.trip_geometry_sizes.update(sizes)
                client.trip_geometry_bytes += geometry_bytes
                if reliable:
                    self._stage_legacy_bootstrap(client, reliable, frames[key])
                    continue
            self._queue(client, frames[key], snapshot=True)

    def _slot_path(self, value: Any) -> tuple[str, Path]:
        if not isinstance(value, str) or SLOT_NAME.fullmatch(value) is None:
            raise ValueError(
                "save slot must contain 1 to 48 ASCII letters, numbers, underscores, or hyphens"
            )
        try:
            path = (self.save_dir / f"{value}.json").resolve()
        except RuntimeError as exc:
            raise ValueError("save slot path could not be resolved") from exc
        if path.parent != self.save_dir:
            raise ValueError(
                "save slot must resolve directly inside the configured save directory"
            )
        return value, path

    def _new_session(
        self,
        simulation: CivicSimulation | None = None,
        *,
        preparation: PreparedCheckpointCapture | None = None,
    ) -> None:
        candidate = simulation if simulation is not None else self.simulation
        if preparation is None:
            preparation = (
                self._checkpoint_preparation
                if candidate is self.simulation
                else prepare_checkpoint_capture(candidate)
            )
        session_id = str(uuid.uuid4())
        # Validate both transfer frames before replacing active state. A valid
        # checkpoint can still contain more data than this transport permits.
        encodings = {
            transport_mode(candidate.scenario, client.requested_snapshot_encoding)
            for client in self.clients.values()
            if client.authenticated
        } or {(False, False, False)}
        legacy_modes = {
            transport_mode(candidate.scenario, client.requested_snapshot_encoding)
            for client in self.clients.values()
            if client.authenticated
            and not self._uses_points(client, candidate.scenario)
        }
        scene_frames = {}
        for compact, trip_references, rows in encodings:
            scene_frames[(compact, trip_references, rows)] = encode_frame(
                scene_message(
                    candidate.scenario,
                    session_id,
                    compact=compact,
                    trip_references=trip_references,
                    rows=rows,
                )
            )
            snapshot = snapshot_message(
                candidate,
                session_id,
                1,
                compact=compact,
                trip_references=trip_references,
                rows=rows,
            )
            encode_frame(snapshot)
            if trip_references and (compact, trip_references, rows) in legacy_modes:
                trip_ids = _active_trip_ids(snapshot)
                _, geometry_bytes = trip_geometry_frames(
                    candidate.trip_geometries(trip_ids), session_id
                )
                if (
                    len(trip_ids) > MAX_TRIP_DEFINITIONS
                    or geometry_bytes > MAX_TRIP_GEOMETRY_BYTES
                ):
                    raise ValueError(
                        "saved active trip geometries exceed the connection cache limit"
                    )
        self._population_responses.clear()
        self._advanced_ticks = 0
        self._advance_wall = 0.0
        self.simulation = candidate
        self._checkpoint_preparation = preparation
        self.scenario = candidate.scenario
        self.seed = self.scenario.get("seed", 7)
        self.tick_hz = float(candidate.tick_hz)
        self.session_id = session_id
        self.sequence = 0
        self._scene_frames = scene_frames
        self._tick_fraction = 0.0
        self._last_time = time.monotonic()
        self._reset_points()
        for client in list(self.clients.values()):
            if client.authenticated:
                if self._uses_points(client):
                    self._queue_point_scene(client)
                    continue
                client.legacy_bootstrap.clear()
                client.known_trip_ids.clear()
                client.trip_geometry_sizes.clear()
                client.trip_geometry_bytes = 0
                self._queue(
                    client,
                    self._scene(
                        compact=self._compact(client),
                        trip_references=self._trip_references(client),
                        rows=self._rows(client),
                    ),
                    scene_barrier=True,
                )

    def _job_status(self, job: PendingJob, *, running: bool = False) -> None:
        if not job.client.wants_command_status:
            return
        message = {
            "type": "command_status",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": job.request["request_id"],
            "action": job.request["action"],
            "status": "running" if running else "pending",
            "session_id": job.session_id,
            "tick": job.tick,
            "elapsed_seconds": round(max(0.0, time.monotonic() - job.started_at), 3),
        }
        if job.slot is not None:
            message["slot"] = job.slot
        self._queue(job.client, encode_frame(message), priority=True)

    def _start_job(
        self,
        client: Client,
        request: dict[str, Any],
        work: Callable[[], Any],
        *,
        slot: str | None = None,
        process_payload: Any = None,
    ) -> None:
        job = PendingJob(
            client,
            request.copy(),
            self.session_id,
            self.simulation.tick,
            slot,
            time.monotonic(),
        )
        job.next_status = job.started_at + 1.0
        self._pending_job = job

        def execute() -> None:
            try:
                result = (
                    (
                        self._run_isolated_job(job, process_payload)
                        if self.job_backend == "process"
                        else work()
                    ),
                    None,
                )
            except Exception as exc:
                result = (None, exc)
            job.metrics["preparation_finished_monotonic"] = time.monotonic()
            job.result.put(result)

        job.thread = threading.Thread(target=execute, name="civic-command", daemon=True)
        self._job_status(job)
        job.thread.start()

    def _run_isolated_job(self, job: PendingJob, payload: Any) -> Any:
        context = multiprocessing.get_context("spawn")
        reader, writer = context.Pipe(duplex=False)
        process = context.Process(
            target=_process_job_main,
            args=(writer, job.request["action"], payload),
            name="civic-command",
        )
        started = time.monotonic()
        try:
            with job.lifecycle_lock:
                if job.cancelled.is_set():
                    raise RuntimeError("operation cancelled")
                job.process = process
                process.start()
                job.metrics["pid"] = process.pid
                job.metrics["spawn_seconds"] = time.monotonic() - started
            writer.close()
            try:
                compressed = reader.recv_bytes(MAX_JOB_TRANSFER_BYTES)
            except EOFError as exc:
                raise RuntimeError(
                    "isolated operation exited before returning a complete result"
                ) from exc
            except OSError as exc:
                raise ValueError(
                    "isolated operation transfer failed or exceeded its 192 MiB bound"
                ) from exc
            if job.cancelled.is_set():
                raise RuntimeError("operation cancelled")
            decoder = zlib.decompressobj()
            encoded = decoder.decompress(compressed, MAX_JOB_TRANSFER_BYTES + 1)
            if (
                len(encoded) > MAX_JOB_TRANSFER_BYTES
                or not decoder.eof
                or decoder.unused_data
            ):
                raise ValueError(
                    "isolated operation exceeds the 192 MiB local transfer limit"
                )
            before_decode = time.monotonic()
            # This anonymous pipe is created and owned by this parent. TCP only
            # accepts JSON; no network/client bytes are ever unpickled.
            response = pickle.loads(encoded)
            job.metrics.update(
                compressed_bytes=len(compressed),
                pickle_bytes=len(encoded),
                unpickle_seconds=time.monotonic() - before_decode,
                child_work_seconds=response.get("child_work_seconds"),
            )
            if not response["ok"]:
                exception = OSError if response.get("io_error") else ValueError
                raise exception(response["message"])
            return response["result"]
        finally:
            reader.close()
            writer.close()
            with job.lifecycle_lock:
                if process.pid is not None:
                    process.join(2)
                    if process.is_alive():
                        process.terminate()
                        process.join(2)
                    if process.is_alive():
                        process.kill()
                        process.join(2)

    def _cancel_pending_job(self) -> None:
        job = self._pending_job
        if job is None:
            return
        job.cancelled.set()
        with job.lifecycle_lock:
            process = job.process
            if process is not None and process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(2)
                if process.is_alive():
                    process.kill()
                    process.join(2)
        if job.thread is not None and job.thread is not threading.current_thread():
            job.thread.join(2)
        self._pending_job = None
        self.last_job_metrics = {
            **job.metrics,
            "action": job.request["action"],
            "cancelled": True,
        }

    def _install_prepared_session(self, result: PreparedSession) -> None:
        candidate = result.simulation
        modes = {
            transport_mode(candidate.scenario, client.requested_snapshot_encoding)
            for client in self.clients.values()
            if client.authenticated
            and not self._uses_points(client, candidate.scenario)
        }
        point_modes = {
            transport_mode(candidate.scenario, client.requested_snapshot_encoding)
            for client in self.clients.values()
            if client.authenticated and self._uses_points(client, candidate.scenario)
        }
        if point_modes and not result.points_validated:
            raise ValueError(
                "shared route capability changed during preparation; retry the operation"
            )
        if any(mode not in result.reference_scenes for mode in point_modes):
            raise ValueError(
                "prepared shared city scene or snapshot exceeds the frame limit"
            )
        for mode in modes:
            if mode in result.invalid_modes:
                raise ValueError(result.invalid_modes[mode])
            if mode not in result.scenes or mode not in result.snapshots:
                raise ValueError(
                    "prepared candidate is missing a negotiated transport mode"
                )
        self._population_responses.clear()
        self._advanced_ticks = 0
        self._advance_wall = 0.0
        self.simulation = candidate
        self._checkpoint_preparation = PreparedCheckpointCapture(
            result.scenario_json, weakref.ref(candidate), candidate.roster_revision
        )
        self.scenario = candidate.scenario
        self.seed = self.scenario.get("seed", 7)
        self.tick_hz = float(candidate.tick_hz)
        self.session_id = result.session_id
        self.sequence = 1
        self._scene_frames = {**result.scenes, **result.reference_scenes}
        self._tick_fraction = 0.0
        self._last_time = time.monotonic()
        self._next_snapshot = self._last_time + SNAPSHOT_INTERVAL
        self._reset_points()
        for client in list(self.clients.values()):
            if client.authenticated:
                if self._uses_points(client):
                    self._queue_point_scene(client)
                    continue
                client.legacy_bootstrap.clear()
                client.known_trip_ids.clear()
                client.trip_geometry_sizes.clear()
                client.trip_geometry_bytes = 0
                self._queue(
                    client,
                    result.scenes[
                        transport_mode(
                            self.scenario, client.requested_snapshot_encoding
                        )
                    ],
                    scene_barrier=True,
                )

    def _publish_prepared_session(self, result: PreparedSession) -> None:
        for client in list(self.clients.values()):
            if not client.authenticated or client.close_after_flush:
                continue
            if self._uses_points(client):
                self._publish_point_clients([client], force=True)
                continue
            references = self._trip_references(client)
            if references:
                client.known_trip_ids.update(result.geometry_sizes)
                client.trip_geometry_sizes.update(result.geometry_sizes)
                client.trip_geometry_bytes = sum(result.geometry_sizes.values())
            self._stage_legacy_bootstrap(
                client,
                result.geometry_frames if references else [],
                result.snapshots[
                    transport_mode(self.scenario, client.requested_snapshot_encoding)
                ],
            )

    def _poll_job(self) -> None:
        job = self._pending_job
        if job is None:
            return
        try:
            result, error = job.result.get_nowait()
        except queue.Empty:
            if time.monotonic() >= job.next_status:
                self._job_status(job, running=True)
                job.next_status = time.monotonic() + 1.0
            return
        self._pending_job = None
        action = job.request["action"]
        commit_started = time.monotonic()
        if error is None and action == "set_population":
            try:
                self._commit_live_population(job, result)
            except (OSError, ValueError, TypeError) as exc:
                self._error(
                    job.client,
                    "invalid_command",
                    f"set_population failed: {exc}",
                    request=job.request,
                )
            return
        if error is None and action in ("load", "population"):
            try:
                self._install_prepared_session(result)
            except (OSError, ValueError, TypeError) as exc:
                error = exc
        self.last_job_metrics = {
            **job.metrics,
            "action": action,
            "commit_seconds": time.monotonic() - commit_started,
            "elapsed_seconds": time.monotonic() - job.started_at,
        }
        if error is not None:
            code = (
                "checkpoint_error" if isinstance(error, OSError) else "invalid_command"
            )
            self._error(
                job.client,
                code,
                f"{action} failed: {getattr(error, 'strerror', None) or str(error)}",
                request=job.request,
            )
            return
        acknowledgment = {
            "type": "ack",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": job.request["request_id"],
            "action": action,
            "session_id": self.session_id,
            "tick": job.tick if action == "save" else self.simulation.tick,
        }
        if job.slot is not None:
            acknowledgment["slot"] = job.slot
        if action == "save":
            acknowledgment["captured_tick"] = job.tick
        self._queue(job.client, encode_frame(acknowledgment), priority=True)
        if isinstance(result, PreparedSession):
            self._publish_prepared_session(result)
        else:
            self._broadcast_snapshot(force=True)

    def _remember_population(
        self, client: Client, request: dict, response: dict
    ) -> None:
        self._population_responses[
            (client.command_client_id, request["request_id"])
        ] = (
            (
                request.get("value"),
                request.get("expected_roster_revision"),
                request.get("expected_session_id"),
            ),
            response,
        )
        while len(self._population_responses) > 128:
            self._population_responses.pop(next(iter(self._population_responses)))

    def _commit_live_population(
        self, job: PendingJob, result: PreparedPopulation
    ) -> None:
        from civic_center.checkpoint import (
            MAX_SCENARIO_BYTES,
            _canonical,
            _validate_tree,
        )
        from civic_center.population import capture_runtime

        started = time.perf_counter()
        old_count = len(self.simulation._sources)
        # Route caches contain immutable values; warming them changes no domain state.
        self.simulation.graph._cache.update(result.route_cache)
        candidate = preview_population(self.simulation, result.delta)
        modes = {
            transport_mode(candidate.scenario, client.requested_snapshot_encoding)
            for client in self.clients.values()
            if client.authenticated and not self._uses_points(client)
        }
        point_modes = {
            transport_mode(candidate.scenario, client.requested_snapshot_encoding)
            for client in self.clients.values()
            if client.authenticated and self._uses_points(client)
        }
        prepared = copy.copy(result.session)
        prepared.simulation = candidate
        prepared.snapshots = {}
        snapshot_messages = {}
        for mode in modes:
            if mode not in prepared.scenes:
                detail = prepared.invalid_modes.get(
                    mode, "Missing negotiated population format"
                )
                if "geometr" in detail:
                    raise ValueError(
                        "Requested population exceeds the current route-data limit; try a smaller target. "
                        + detail
                    )
                raise ValueError(detail)
            compact, references, rows = mode
            message = snapshot_message(
                candidate,
                prepared.session_id,
                1,
                compact=compact,
                trip_references=references,
                rows=rows,
            )
            snapshot_messages[mode] = message
        if point_modes and (
            not prepared.points_validated
            or any(mode not in prepared.reference_scenes for mode in point_modes)
        ):
            raise ValueError(
                "Population shared-route capability changed during preparation; retry"
            )
        if point_modes:
            active_definitions = candidate.trip_geometries(candidate.active_trip_ids())
            SharedGeometryEncoder(prepared.session_id).encode(active_definitions)
        if modes:
            active = candidate.active_trip_ids()
            definitions = (
                candidate.trip_geometries(active)
                if any(mode[1] for mode in modes)
                else []
            )
            prepared.geometry_frames, _ = trip_geometry_frames(
                definitions, prepared.session_id
            )
            prepared.geometry_sizes = {
                definition["id"]: len(encode_frame(definition)) - 1
                for definition in definitions
            }
            if (
                len(active) > MAX_TRIP_DEFINITIONS
                or sum(prepared.geometry_sizes.values()) > MAX_TRIP_GEOMETRY_BYTES
            ):
                raise ValueError(
                    "Requested population exceeds the current route-data limit; try a smaller target."
                )
        compact_state = candidate.snapshot(
            include_static=False, include_trip_geometry=False
        )
        runtime = capture_runtime(candidate)
        proof = {
            "metadata_state_sha256": "0" * 64,
            "trip_geometry_sha256": {
                identity: "0" * 64 for identity in candidate.active_trip_ids()
            },
        }
        _validate_tree(
            {"state": compact_state, "runtime": runtime, "verification": proof},
            initial_values=result.scenario_values - 1,
        )
        if (
            len(prepared.scenario_json)
            + len(_canonical(compact_state))
            + len(_canonical(runtime))
            + len(_canonical(proof))
            > MAX_SCENARIO_BYTES
        ):
            raise ValueError("Population state exceeds checkpoint budget")
        change = {
            "request_id": job.request["request_id"],
            "old_count": old_count,
            "new_count": result.delta.target,
            "roster_revision": candidate.roster_revision,
            "committed_tick": candidate.tick,
            "committed_at_unix": time.time(),
            "committed_monotonic_seconds": time.monotonic(),
            "preparation_ms": (
                job.metrics["preparation_finished_monotonic"] - job.started_at
            )
            * 1000,
            "commit_ms": (time.perf_counter() - started) * 1000,
        }
        fields = {"reason": "population_adjustment", "population_change": change}
        scene_frames = {
            mode: _append_frame_fields(frame, fields)
            for mode, frame in {**prepared.scenes, **prepared.reference_scenes}.items()
        }
        for mode in point_modes:
            _append_frame_fields(
                scene_frames[mode], {"route_geometry_encoding": CITY_POINTS_ENCODING}
            )
        for mode, message in snapshot_messages.items():
            message["population_change"] = change
            message["worker_metrics"] = self._worker_metrics()
            prepared.snapshots[mode] = encode_frame(message)
        # Reject an indivisible frame or congested new-scene barrier before the
        # domain changes. Geometry frames themselves are staged after that barrier.
        if any(len(frame) > MAX_QUEUE_BYTES for frame in prepared.geometry_frames):
            raise ValueError("Population geometry frame exceeds outgoing queue budget")
        for connection in self.clients.values():
            if connection.authenticated:
                mode = transport_mode(
                    candidate.scenario, connection.requested_snapshot_encoding
                )
                if (
                    connection.queued_bytes + len(scene_frames[mode]) + 4096
                    > MAX_QUEUE_BYTES
                ):
                    raise ValueError(
                        "Population scene cannot be queued while this connection is congested; retry"
                    )
        candidate.population_change = change
        # All fallible validation and encoding above precedes this atomic update.
        commit_population(self.simulation, candidate)
        self._advanced_ticks = 0
        self._advance_wall = 0.0
        self.scenario = self.simulation.scenario
        self._checkpoint_preparation = PreparedCheckpointCapture(
            prepared.scenario_json,
            weakref.ref(self.simulation),
            self.simulation.roster_revision,
        )
        self.session_id = prepared.session_id
        self.sequence = 1
        self._scene_frames = scene_frames
        self._reset_points()
        for connection in list(self.clients.values()):
            if not connection.authenticated:
                continue
            if self._uses_points(connection):
                self._queue_point_scene(connection)
            else:
                mode = transport_mode(
                    self.scenario, connection.requested_snapshot_encoding
                )
                connection.legacy_bootstrap.clear()
                connection.known_trip_ids.clear()
                connection.trip_geometry_sizes.clear()
                connection.trip_geometry_bytes = 0
                self._queue(connection, scene_frames[mode], scene_barrier=True)
        response = {
            "type": "ack",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": job.request["request_id"],
            "action": "set_population",
            "session_id": self.session_id,
            "count": result.delta.target,
            "population": result.delta.target,
            "requested_count": result.delta.target,
            "roster_revision": candidate.roster_revision,
            "tick": candidate.tick,
            "committed_tick": candidate.tick,
            "noop": False,
            "added_count": len(result.delta.additions),
            "removed_count": len(result.delta.removals),
            "world_identity": candidate.world_identity,
            "population_change": change,
            "prepare_ms": change["preparation_ms"],
            "commit_ms": change["commit_ms"],
            "worker_monotonic_seconds": time.monotonic(),
        }
        self.last_job_metrics = {**job.metrics, "action": "set_population", **change}
        self._remember_population(job.client, job.request, response)
        self._queue(job.client, encode_frame(response), priority=True)
        # Publish the CURRENT candidate frames validated above, not the child's
        # preparation-tick snapshot and not another expensive geometry encoding.
        prepared.scenes = scene_frames
        self._publish_prepared_session(prepared)

    def _handle(self, client: Client, message: dict[str, Any]) -> None:
        if not client.authenticated:
            candidate = message.get("token")
            version = message.get("protocol_version")
            try:
                candidate_bytes = (
                    candidate.encode("utf-8") if isinstance(candidate, str) else None
                )
            except UnicodeEncodeError:
                candidate_bytes = None
            if (
                message.get("type") != "hello"
                or type(version) is not int
                or version != PROTOCOL_VERSION
                or candidate_bytes is None
                or not hmac.compare_digest(candidate_bytes, self._token)
            ):
                self._error(
                    client,
                    "authentication_failed",
                    "a valid hello, protocol version, and token are required",
                    close=True,
                )
                return
            namespace = message.get("command_client_id")
            if namespace is not None:
                if (
                    not isinstance(namespace, str)
                    or not namespace
                    or len(namespace) > 128
                ):
                    self._error(
                        client,
                        "invalid_message",
                        "command_client_id must be a nonempty string of at most 128 characters",
                        close=True,
                    )
                    return
                client.command_client_id = namespace
                client.population_session_guard = True
            client.authenticated = True
            client.wants_command_status = message.get("command_status") is True
            if message.get("snapshot_encoding") in (
                CITY_DYNAMIC_ENCODING,
                CITY_ROUTES_ENCODING,
                CITY_ROWS_ENCODING,
            ):
                client.requested_snapshot_encoding = message["snapshot_encoding"]
            if message.get("route_geometry_encoding") == CITY_POINTS_ENCODING:
                client.requested_route_encoding = CITY_POINTS_ENCODING
            if self._uses_points(client):
                try:
                    self._queue_point_scene(client)
                    self._publish_point_clients([client])
                except ValueError as exc:
                    self._error(client, "frame_too_large", str(exc), close=True)
                return
            compact = self._compact(client)
            try:
                scene = self._scene(
                    compact=compact,
                    trip_references=self._trip_references(client),
                    rows=self._rows(client),
                )
            except ValueError as exc:
                self._error(client, "frame_too_large", str(exc), close=True)
                return
            self._queue(client, scene, scene_barrier=True)
            try:
                self._publish_snapshots([client])
            except ValueError as exc:
                self._error(client, "frame_too_large", str(exc), close=True)
            return
        if self._shutdown_deadline is not None:
            self._error(
                client, "shutting_down", "the worker is shutting down", request=message
            )
            return
        if message.get("type") != "command":
            self._error(
                client,
                "invalid_message",
                "authenticated clients must send command objects",
                request=message,
            )
            return
        request_id = message.get("request_id")
        action = message.get("action")
        value = message.get("value")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            self._error(
                client,
                "invalid_command",
                "request_id must be a nonempty string of at most 128 characters",
                request=message,
            )
            return
        self._advance_elapsed(time.monotonic())
        if action == "set_population":
            if (
                type(value) is not int
                or type(message.get("expected_roster_revision")) is not int
            ):
                self._error(
                    client,
                    "invalid_command",
                    "Population count and expected roster revision must be integers",
                    request=message,
                )
                return
            signature = (
                message.get("value"),
                message.get("expected_roster_revision"),
                message.get("expected_session_id"),
            )
            previous = self._population_responses.get(
                (client.command_client_id, request_id)
            )
            if previous is not None:
                if signature != previous[0]:
                    self._error(
                        client,
                        "request_id_conflict",
                        "Request ID was already used with different population arguments",
                        request=message,
                    )
                else:
                    self._queue(client, encode_frame(previous[1]), priority=True)
                return
        if self._pending_job is not None and action in (
            "save",
            "load",
            "population",
            "set_population",
            "reset",
        ):
            self._error(
                client,
                "operation_pending",
                "another save, load, or population operation is still pending",
                request=message,
            )
            return
        acknowledgment_fields: dict[str, Any] = {}
        try:
            if action == "pause":
                if type(value) is not bool:
                    raise ValueError("pause value must be a boolean")
                self.simulation.set_paused(value)
                self._advanced_ticks = 0
                self._advance_wall = 0.0
            elif action == "speed":
                if type(value) is not int or value not in SPEEDS:
                    raise ValueError("speed value must be 1, 4, 60, or 600")
                self.simulation.set_speed(value)
                self._advanced_ticks = 0
                self._advance_wall = 0.0
            elif action == "reset":
                self.simulation.reset()
                self._new_session()
            elif action == "step":
                if not self.simulation.paused:
                    raise ValueError("step is available only while paused")
                if type(value) is not int or not 0 <= value <= MAX_STEP_TICKS:
                    raise ValueError(
                        f"step value must be an integer from 0 to {MAX_STEP_TICKS}"
                    )
                self.simulation.step_ticks(value)
            elif action == "next_event":
                next_tick = self.simulation.next_event_tick()
                if next_tick is not None:
                    self.simulation.step_ticks(max(0, next_tick - self.simulation.tick))
                self.simulation.set_paused(True)
                self._tick_fraction = 0.0
                self._last_time = time.monotonic()
            elif action == "set_population":
                if (
                    client.population_session_guard or "expected_session_id" in message
                ) and message.get("expected_session_id") != self.session_id:
                    self._error(
                        client,
                        "stale_session",
                        "Simulation session changed; use the latest complete scene",
                        request=message,
                    )
                    return
                value = validate_population(value)
                revision = message.get("expected_roster_revision")
                if (
                    type(revision) is not int
                    or revision != self.simulation.roster_revision
                ):
                    self._error(
                        client,
                        "stale_roster_revision",
                        "Population roster changed; use the latest roster revision",
                        request=message,
                    )
                    return
                if value == len(self.simulation._sources):
                    response = {
                        "type": "ack",
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request_id,
                        "action": action,
                        "session_id": self.session_id,
                        "count": value,
                        "population": value,
                        "requested_count": value,
                        "roster_revision": revision,
                        "committed_tick": self.simulation.tick,
                        "tick": self.simulation.tick,
                        "noop": True,
                        "added_count": 0,
                        "removed_count": 0,
                        "world_identity": self.simulation.world_identity,
                    }
                    self._remember_population(client, message, response)
                    self._queue(client, encode_frame(response), priority=True)
                    return
                frozen = frozen_population_view(self.simulation)
                points = any(
                    self._uses_points(connection)
                    for connection in self.clients.values()
                    if connection.authenticated
                )
                self._start_job(
                    client,
                    message,
                    lambda: _prepare_live_population(frozen, value, points=points),
                    process_payload=(frozen, value, points),
                )
                return
            elif action == "population":
                presets = self.scenario.get("population_presets", POPULATIONS)
                if type(value) is not int or value not in presets:
                    raise ValueError(f"population value must be one of {list(presets)}")
                geography = self.scenario.get("geography_manifest")
                terrain = self.scenario.get("terrain_manifest")
                landuse = self.scenario.get("landuse_manifest")
                seed = self.seed
                points = any(
                    self._uses_points(connection)
                    for connection in self.clients.values()
                    if connection.authenticated
                )

                def prepare_population() -> PreparedSession:
                    if geography:
                        from civic_center.city_scenario import build_city_scenario

                        options = {
                            "population": value,
                            "seed": seed,
                            "terrain_path": terrain,
                        }
                        if landuse:
                            options["landuse_path"] = landuse
                        scenario = build_city_scenario(geography, **options)
                    else:
                        scenario = make_scenario(population=value, seed=seed)
                    candidate = CivicSimulation(scenario)
                    return prepare_session(candidate, points=points)

                self._start_job(
                    client,
                    message,
                    prepare_population,
                    process_payload=(geography, terrain, landuse, value, seed, points),
                )
                return
            elif action in ("save", "load"):
                slot, path = self._slot_path(message.get("value", "quick"))
                if action == "save":
                    capture = capture_checkpoint(
                        self.simulation, self._checkpoint_preparation
                    )
                    work = lambda: write_captured_checkpoint(capture, path)
                    process_payload = (capture, path)
                else:
                    points = any(
                        self._uses_points(connection)
                        for connection in self.clients.values()
                        if connection.authenticated
                    )

                    def work() -> PreparedSession:
                        candidate = load_checkpoint(path)
                        return prepare_session(candidate, points=points)

                    process_payload = {"path": path, "points": points}

                self._start_job(
                    client, message, work, slot=slot, process_payload=process_payload
                )
                return
            elif action == "shutdown":
                self._cancel_pending_job()
                if self._point_service is not None:
                    self._point_service.close()
                    self._point_service = None
                self._shutdown_deadline = time.monotonic() + 2.0
            else:
                raise ValueError(
                    "unknown action; expected pause, speed, reset, step, next_event, population, save, load, or shutdown"
                )
        except OSError as exc:
            self._error(
                client,
                "checkpoint_error",
                f"{action} failed: {exc.strerror or str(exc)}",
                request=message,
            )
            return
        except (ValueError, TypeError) as exc:
            self._error(client, "invalid_command", str(exc), request=message)
            return
        self._queue(
            client,
            encode_frame(
                {
                    "type": "ack",
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": request_id,
                    "action": action,
                    "session_id": self.session_id,
                    "tick": self.simulation.tick,
                    **acknowledgment_fields,
                }
            ),
            priority=True,
        )
        if action != "shutdown":
            self._broadcast_snapshot(force=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--population",
        type=int,
        choices=POPULATIONS,
        default=200,
        help="generated resident count; ignored when --scenario or --load is supplied",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=DEFAULT_SAVE_DIR,
        help="directory for named save/load slots",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scenario", type=Path)
    source.add_argument(
        "--load",
        type=Path,
        help="resume a checkpoint; its scenario and seed replace generated options",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be from 0 to 65535")
    if not args.token:
        parser.error("--token must be nonempty")
    try:
        simulation = load_checkpoint(args.load) if args.load is not None else None
        if simulation is not None:
            scenario = simulation.scenario
        elif args.scenario is not None:
            scenario = load_scenario(args.scenario)
        else:
            scenario = make_scenario(population=args.population, seed=args.seed)
        worker = CivicWorker(
            scenario,
            args.token,
            port=args.port,
            ready_file=args.ready_file,
            save_dir=args.save_dir,
            simulation=simulation,
        )
        worker.run()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        # Never include command line arguments or the authentication token.
        parser.exit(1, f"civic worker: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
