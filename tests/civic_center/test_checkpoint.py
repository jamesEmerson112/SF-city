"""Checkpoint integrity, exact continuation and atomic-file acceptance checks."""

import base64
import hashlib
import json
import pickle
import zlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from civic_center import checkpoint
from civic_center.checkpoint import (
    capture_checkpoint,
    load_checkpoint,
    prepare_checkpoint_capture,
    save_checkpoint,
    write_captured_checkpoint,
)
from civic_center.model import CivicSimulation
from civic_center.scenario import make_scenario, scenario_hash


def checksum(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rewrite(path, mutate, *, state_hash=False, scenario_hashes=False):
    """Re-sign selected levels so each test exercises the deeper validation too."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    compressed = payload["checkpoint_version"] == 2
    if compressed:
        payload["scenario"] = checkpoint._decode_scenario(payload["scenario"])
    mutate(payload)
    if state_hash:
        payload["state_sha256"] = checksum(payload["state"])
    if scenario_hashes:
        payload["scenario_sha256"] = scenario_hash(payload["scenario"])
        if "sha256" in payload["scenario"]:
            payload["scenario"]["sha256"] = payload["scenario_sha256"]
    if compressed:
        payload["scenario"] = checkpoint._encode_scenario(payload["scenario"])
    payload["sha256"] = checksum(
        {key: value for key, value in payload.items() if key != "sha256"}
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def saved(tmp_path):
    simulation = CivicSimulation(make_scenario(1))
    simulation.advance_ticks(10_000)
    path = save_checkpoint(simulation, tmp_path / "quick.json")
    return simulation, path


def test_midtrip_paused_pose_and_subsequent_day_are_exactly_preserved(tmp_path):
    simulation = CivicSimulation(make_scenario(1))
    simulation.advance_ticks(12_345)
    simulation.set_paused(True)
    simulation.set_speed(120)
    before = simulation.snapshot()
    assert before["residents"][0]["activity"] == "walking_to_work"
    assert before["residents"][0]["moving"]
    path = save_checkpoint(simulation, tmp_path / "nested" / "morning.json")
    restored = load_checkpoint(path)
    assert restored is not simulation
    assert restored.scenario == simulation.scenario
    assert restored.snapshot() == before
    assert restored.next_event_tick() == simulation.next_event_tick()
    restored.advance_ticks(500)
    assert restored.snapshot() == before
    for model in (simulation, restored):
        model.set_paused(False)
        model.advance_ticks(11 * 3600 * model.tick_hz)
    assert restored.snapshot() == simulation.snapshot()
    assert restored.snapshot()["event_count"] == 4


def test_cohort_at_work_keeps_all_ids_occupancy_and_return_events(tmp_path):
    simulation = CivicSimulation(make_scenario(200, 81))
    simulation.advance_ticks(3600 * simulation.tick_hz)
    before = simulation.snapshot()
    assert all(person["activity"] == "at_work" for person in before["residents"])
    path = save_checkpoint(simulation, tmp_path / "at-work.json")
    restored = load_checkpoint(path)
    assert restored.snapshot() == before
    assert len(restored.snapshot()["residents"]) == 200
    assert (
        sum(building["occupancy"] for building in restored.snapshot()["buildings"])
        == 200
    )
    for model in (simulation, restored):
        model.advance_ticks(10 * 3600 * model.tick_hz)
    assert restored.snapshot() == simulation.snapshot()
    assert restored.snapshot()["event_count"] == 800
    assert all(
        person["activity"] == "home" for person in restored.snapshot()["residents"]
    )


def test_blocked_resident_and_reason_survive_checkpoint(tmp_path):
    scenario = make_scenario(1)
    scenario["edges"] = []
    scenario["sha256"] = scenario_hash(scenario)
    simulation = CivicSimulation(scenario)
    simulation.advance_ticks(5000)
    path = save_checkpoint(simulation, tmp_path / "blocked.json")
    restored = load_checkpoint(path)
    assert restored.snapshot() == simulation.snapshot()
    assert restored.snapshot()["residents"][0]["activity"] == "blocked"


def test_saved_document_contains_version_mode_full_scenario_compact_state_and_proofs(
    saved,
):
    simulation, path = saved
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["checkpoint_version"] == 2
    assert payload["reconstruction_mode"] == "deterministic-scenario-v1"
    assert checkpoint._decode_scenario(payload["scenario"]) == simulation.scenario
    compact = simulation.snapshot(include_static=False, include_trip_geometry=False)
    assert payload["state"] == compact
    assert payload["scenario_sha256"] == scenario_hash(simulation.scenario)
    assert payload["state_sha256"] == checksum(compact)
    assert payload["verification"] == checkpoint._state_verification(simulation)
    assert "points" not in compact["residents"][0]["trip"]
    assert "home_id" not in compact["residents"][0]
    assert "entrance_node_id" not in compact["buildings"][0]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("checkpoint_version", 4, "checkpoint_version"),
        ("checkpoint_version", True, "checkpoint_version"),
        ("reconstruction_mode", "arbitrary-state-v2", "reconstruction_mode"),
        ("tick", -1, "tick"),
        ("tick", True, "tick"),
        ("tick", 10.5, "tick"),
        ("paused", 1, "paused"),
        ("speed", True, "speed"),
        ("speed", 0, "speed"),
        ("speed", -1, "speed"),
    ],
)
def test_strict_header_scalar_types_and_versions(saved, field, value, message):
    _simulation, path = saved
    rewrite(path, lambda payload: payload.update({field: value}))
    with pytest.raises(ValueError, match=message):
        load_checkpoint(path)


def test_unknown_top_level_fields_are_rejected(saved):
    _simulation, path = saved
    rewrite(path, lambda payload: payload.update(unhandled_state="future"))
    with pytest.raises(ValueError, match="unsupported fields"):
        load_checkpoint(path)


def test_document_checksum_catches_edits_before_reconstruction(saved):
    _simulation, path = saved
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tick"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Checkpoint checksum"):
        load_checkpoint(path)


def test_scenario_checksum_catches_corrupted_route(saved):
    _simulation, path = saved
    rewrite(
        path,
        lambda payload: payload["scenario"]["nodes"][0]["position"].__setitem__(
            0, -100
        ),
    )
    with pytest.raises(ValueError, match="scenario checksum"):
        load_checkpoint(path)


def test_embedded_scenario_checksum_is_verified_even_when_envelope_is_signed(saved):
    _simulation, path = saved
    rewrite(path, lambda payload: payload["scenario"].update(sha256="0" * 64))
    with pytest.raises(ValueError, match="embedded scenario checksum"):
        load_checkpoint(path)


def test_state_checksum_catches_corrupted_position(saved):
    _simulation, path = saved
    rewrite(
        path,
        lambda payload: payload["state"]["residents"][0]["position"].__setitem__(
            0, 999
        ),
    )
    with pytest.raises(ValueError, match="state checksum"):
        load_checkpoint(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["state"]["residents"][0]["position"].__setitem__(0, 999),
        lambda p: p["state"]["residents"][0].update(id="different-person"),
        lambda p: p["state"]["residents"][0]["trip"].update(segment_progress=0.999),
        lambda p: p["state"]["buildings"][0].update(occupancy=999),
        lambda p: p["state"]["events"][0].update(type="arrival"),
        lambda p: p["state"].update(event_count=999),
    ],
)
def test_resigned_but_inconsistent_authoritative_state_is_rejected(saved, mutation):
    simulation, path = saved
    original = simulation.snapshot()
    rewrite(path, mutation, state_hash=True)
    with pytest.raises(ValueError, match="deterministic reconstruction"):
        load_checkpoint(path)
    assert simulation.snapshot() == original


def test_boolean_occupancy_cannot_compare_equal_to_integer_occupancy(saved):
    _simulation, path = saved
    rewrite(
        path,
        lambda p: p["state"]["buildings"][0].update(occupancy=False),
        state_hash=True,
    )
    with pytest.raises(ValueError, match="deterministic reconstruction"):
        load_checkpoint(path)


def test_resigned_invalid_scenario_is_rejected_cleanly(saved):
    _simulation, path = saved
    rewrite(
        path,
        lambda p: p["scenario"]["edges"][0].update(to=["not-a-node"]),
        scenario_hashes=True,
    )
    with pytest.raises(ValueError, match="could not be reconstructed"):
        load_checkpoint(path)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"checkpoint_version":1,',
        b'{"checkpoint_version":1,"checkpoint_version":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b"\xff\xfe",
        b"[]",
    ],
)
def test_malformed_truncated_duplicate_nonfinite_and_nonobject_json(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        load_checkpoint(path)


def test_oversized_read_is_bounded_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "MAX_CHECKPOINT_BYTES", 64)
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 65)
    with pytest.raises(ValueError, match="exceeds 64 bytes"):
        load_checkpoint(path)


def test_oversized_save_preserves_previous_file(saved, monkeypatch):
    simulation, path = saved
    original = path.read_bytes()
    monkeypatch.setattr(checkpoint, "MAX_CHECKPOINT_BYTES", 64)
    with pytest.raises(ValueError, match="exceeds 64 bytes"):
        save_checkpoint(simulation, path)
    assert path.read_bytes() == original
    assert list(path.parent.glob("*.tmp")) == []


def test_failed_atomic_replace_preserves_save_and_cleans_own_temporary(
    saved, monkeypatch
):
    simulation, path = saved
    original = path.read_bytes()
    simulation.advance_ticks(100)

    def fail_replace(source, destination):
        assert Path(source).parent == path.parent
        assert Path(destination) == path
        assert load_checkpoint(source).snapshot() == simulation.snapshot()
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(checkpoint.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        save_checkpoint(simulation, path)
    assert path.read_bytes() == original
    assert list(path.parent.glob("*.tmp")) == []


def test_overwrite_replaces_checkpoint_with_current_tick(saved):
    simulation, path = saved
    simulation.advance_ticks(10_000)
    assert save_checkpoint(simulation, path) == path
    assert load_checkpoint(path).snapshot() == simulation.snapshot()
    assert list(path.parent.glob("*.tmp")) == []


def test_missing_file_preserves_filesystem_error_type(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_checkpoint(tmp_path / "missing.json")


def hill_scenario():
    return {
        "schema_version": 1,
        "id": "hill-day",
        "tick_hz": 10,
        "start_time_seconds": 28790,
        "nodes": [
            {"id": "a", "position": [0, 0, 0]},
            {"id": "b", "position": [6, 0, 0]},
        ],
        "edges": [
            {
                "id": "hill",
                "from": "a",
                "to": "b",
                "bidirectional": True,
                "points": [[0, 0, 0], [3, 0, 4], [6, 0, 0]],
            }
        ],
        "buildings": [
            {"id": "home", "entrance_node_id": "a"},
            {"id": "work", "entrance_node_id": "b"},
        ],
        "residents": [
            {
                "id": "walker",
                "home_id": "home",
                "work_id": "work",
                "departure_tick": 10,
                "return_tick": 200,
                "speed_mps": 1.0,
            }
        ],
    }


def test_polyline_hill_checkpoint_preserves_geometry_grade_and_batched_continuation(
    tmp_path,
):
    model = CivicSimulation(hill_scenario())
    model.step_ticks(35)
    person = model.snapshot()["residents"][0]
    assert person["position"] == [1.5, 0.0, 2.0]
    assert person["trip"]["node_ids"] == ["a", "b"]
    assert len(person["trip"]["points"]) == 3
    assert person["trip"]["length_m"] == 10
    assert person["trip"]["arrival_tick"] == 110
    model.set_paused(True)
    restored = load_checkpoint(save_checkpoint(model, tmp_path / "hill.json"))
    assert restored.snapshot() == model.snapshot()
    model.step_ticks(265)
    for ticks in (25, 50, 89, 1, 99, 1):
        restored.step_ticks(ticks)
    assert restored.snapshot() == model.snapshot()
    assert [e["tick"] for e in model.snapshot()["events"]] == [10, 110, 200, 300]
    assert model.snapshot()["event_count"] == 4


def test_legacy_checkpoint_keeps_endpoint_routes_without_terrain_regeneration(tmp_path):
    scenario = hill_scenario()
    del scenario["edges"][0]["points"]
    model = CivicSimulation(scenario)
    model.step_ticks(35)
    restored = load_checkpoint(save_checkpoint(model, tmp_path / "legacy.json"))
    assert restored.scenario == scenario
    assert "points" not in restored.scenario["edges"][0]
    person = restored.snapshot()["residents"][0]
    assert person["position"] == [2.5, 0.0, 0.0]
    assert person["trip"]["length_m"] == 6
    assert person["trip"]["arrival_tick"] == 70


@pytest.mark.parametrize(
    "field,limit,value,message",
    [
        ("MAX_JSON_VALUES", 3, [1, 2, 3], "too many JSON values"),
        ("MAX_CONTAINER_ITEMS", 2, [1, 2, 3], "container is too large"),
        ("MAX_JSON_DEPTH", 2, [[[1]]], "nesting is too deep"),
        ("MAX_STRING_LENGTH", 2, "long", "string is too long"),
    ],
)
def test_tree_guards_remain_bounded(monkeypatch, field, limit, value, message):
    monkeypatch.setattr(checkpoint, field, limit)
    with pytest.raises(ValueError, match=message):
        checkpoint._validate_tree(value)


def test_capture_stays_at_exact_tick_after_live_advance_reset_and_scenario_edit(
    tmp_path,
):
    model = CivicSimulation(hill_scenario())
    prepared = prepare_checkpoint_capture(model)
    model.step_ticks(35)
    model.set_paused(True)
    model.set_speed(120)
    expected = model.snapshot()
    capture = capture_checkpoint(model, prepared)
    assert type(capture.scenario_json) is bytes
    assert type(capture.state_json) is bytes
    with pytest.raises(FrozenInstanceError):
        capture.tick = 999
    model.step_ticks(400)
    model.reset()
    model.scenario["edges"][0]["points"][1][2] = 900
    path = write_captured_checkpoint(capture, tmp_path / "captured.json")
    restored = load_checkpoint(path)
    assert restored.snapshot() == expected
    assert restored.scenario["edges"][0]["points"][1][2] == 4


def test_preparation_is_explicit_reusable_and_bound_to_model(tmp_path):
    model = CivicSimulation(hill_scenario())
    prepared = prepare_checkpoint_capture(model)
    first = capture_checkpoint(model, prepared)
    model.step_ticks(60)
    second = capture_checkpoint(model, prepared)
    assert first.scenario_json is second.scenario_json
    assert first.state_json != second.state_json
    with pytest.raises(ValueError, match="different simulation"):
        capture_checkpoint(CivicSimulation(hill_scenario()), prepared)
    restored = load_checkpoint(
        write_captured_checkpoint(second, tmp_path / "second.json")
    )
    assert restored.snapshot() == model.snapshot()


@pytest.mark.parametrize(
    "change",
    [
        {"tick": -1},
        {"tick": True},
        {"paused": 1},
        {"speed": 0},
        {"state_json": b"{}"},
        {"scenario_json": b"{"},
        {"scenario_json": b'{"schema_version":1,"schema_version":1}'},
    ],
)
def test_invalid_detached_capture_cannot_replace_existing_save(tmp_path, change):
    model = CivicSimulation(hill_scenario())
    path = save_checkpoint(model, tmp_path / "existing.json")
    original = path.read_bytes()
    capture = replace(capture_checkpoint(model), **change)
    with pytest.raises(ValueError):
        write_captured_checkpoint(capture, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("cycle", [3, 100_000])
def test_later_daily_checkpoint_and_capture_continue_exactly_across_midnight(
    tmp_path, cycle
):
    scenario = hill_scenario()
    scenario["schedule"] = {"mode": "daily-v1"}
    scenario["start_time_seconds"] = 86_395
    model = CivicSimulation(scenario)
    period = 86_400 * model.tick_hz
    model.step_ticks(cycle * period + 65)
    model.set_paused(True)
    model.set_speed(120)
    before = model.snapshot()
    assert before["day_index"] == cycle + 1
    assert before["day_seconds"] == 1.5
    assert before["residents"][0]["trip"]["id"] == f"walker:outbound:{cycle}"
    restored = load_checkpoint(save_checkpoint(model, tmp_path / "later.json"))
    captured = load_checkpoint(
        write_captured_checkpoint(
            capture_checkpoint(model), tmp_path / "captured-later.json"
        )
    )
    assert restored.snapshot() == captured.snapshot() == before
    target = (cycle + 4) * period + 300
    model.step_ticks(target - model.tick)
    for candidate in (restored, captured):
        candidate.step_ticks(period - 65)
        candidate.step_ticks(2 * period + 35)
        candidate.step_ticks(target - candidate.tick)
        assert candidate.snapshot() == model.snapshot()
        assert candidate.next_event_tick() == model.next_event_tick()


@pytest.mark.parametrize(
    "field,value",
    [
        ("day_index", True),
        ("day_seconds", -1),
        ("day_seconds", 86_400),
        ("day_index", 900),
    ],
)
def test_daily_calendar_state_is_validated_and_reconstructed(tmp_path, field, value):
    scenario = hill_scenario()
    scenario["schedule"] = {"mode": "daily-v1"}
    model = CivicSimulation(scenario)
    path = save_checkpoint(model, tmp_path / "calendar.json")
    rewrite(path, lambda p: p["state"].update({field: value}), state_hash=True)
    with pytest.raises(ValueError, match="day_|reconstruction"):
        load_checkpoint(path)


def test_checkpoint_capture_after_private_worker_model_transfer(tmp_path):
    scenario = hill_scenario()
    scenario["schedule"] = {"mode": "daily-v1"}
    original = CivicSimulation(scenario)
    original.step_ticks(3 * 86_400 * original.tick_hz + 35)
    received = pickle.loads(pickle.dumps(original, protocol=pickle.HIGHEST_PROTOCOL))
    prepared = prepare_checkpoint_capture(received)
    capture = capture_checkpoint(received, prepared)
    received.step_ticks(10_000)
    restored = load_checkpoint(
        write_captured_checkpoint(capture, tmp_path / "transferred.json")
    )
    assert restored.snapshot() == original.snapshot()


def write_legacy_checkpoint(model, path):
    """Independent v1 fixture: historical full scenario and full snapshot."""
    state = model.snapshot()
    document = {
        "checkpoint_version": 1,
        "reconstruction_mode": "deterministic-scenario-v1",
        "scenario": model.scenario,
        "scenario_sha256": scenario_hash(model.scenario),
        "tick": model.tick,
        "paused": model.paused,
        "speed": model.speed,
        "state": state,
        "state_sha256": checksum(state),
    }
    document["sha256"] = checksum(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_v1_read_v2_write_and_repeating_day_resume_are_exact(tmp_path):
    scenario = hill_scenario()
    scenario["schedule"] = {"mode": "daily-v1"}
    scenario["start_time_seconds"] = 86_395
    model = CivicSimulation(scenario)
    period = 86_400 * model.tick_hz
    model.step_ticks(3 * period + 65)
    model.set_paused(True)
    model.set_speed(120)
    legacy = load_checkpoint(write_legacy_checkpoint(model, tmp_path / "v1.json"))
    modern_path = save_checkpoint(legacy, tmp_path / "v2.json")
    assert json.loads(modern_path.read_text())["checkpoint_version"] == 2
    modern = load_checkpoint(modern_path)
    assert model.snapshot() == legacy.snapshot() == modern.snapshot()
    for candidate in (model, legacy, modern):
        candidate.step_ticks(4 * period + 235)
    assert model.snapshot() == legacy.snapshot() == modern.snapshot()
    assert modern.snapshot()["event_count"] == 32


def rewrite_envelope(path, mutate):
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    payload["sha256"] = checksum(
        {key: value for key, value in payload.items() if key != "sha256"}
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def replace_compressed_bytes(descriptor, transform):
    compressed = b"".join(base64.b64decode(chunk) for chunk in descriptor["chunks"])
    descriptor["chunks"] = [base64.b64encode(transform(compressed)).decode("ascii")]


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda d: d.update(encoding="pickle"), "encoding"),
        (lambda d: d.update(uncompressed_bytes=True), "scenario size"),
        (lambda d: d.update(uncompressed_bytes=0), "empty"),
        (
            lambda d: d.update(uncompressed_bytes=checkpoint.MAX_SCENARIO_BYTES + 1),
            "expanded scenario exceeds",
        ),
        (
            lambda d: d.update(uncompressed_bytes=d["uncompressed_bytes"] - 1),
            "size does not match",
        ),
        (
            lambda d: d.update(uncompressed_bytes=d["uncompressed_bytes"] + 1),
            "size does not match",
        ),
        (lambda d: d.update(chunks=[]), "nonempty strings"),
        (lambda d: d.update(chunks=[""]), "nonempty strings"),
        (lambda d: d.update(chunks=["!invalid!"]), "base64"),
        (lambda d: d.update(json_sha256="0" * 64), "scenario JSON checksum"),
        (lambda d: d.update(unknown=1), "unsupported fields"),
        (
            lambda d: replace_compressed_bytes(d, lambda b: b[:-4]),
            "truncated|size does not match",
        ),
        (
            lambda d: replace_compressed_bytes(d, lambda b: b + b"trailing"),
            "trailing or concatenated",
        ),
        (
            lambda d: replace_compressed_bytes(d, lambda b: b + zlib.compress(b"{}")),
            "trailing or concatenated",
        ),
    ],
)
def test_compressed_scenario_corruption_and_resource_declarations_are_rejected(
    saved, mutation, message
):
    _model, path = saved
    rewrite_envelope(path, lambda p: mutation(p["scenario"]))
    with pytest.raises(ValueError, match=message):
        load_checkpoint(path)


def test_compression_bomb_stops_at_declared_output_size(saved):
    _model, path = saved

    def insert_bomb(payload):
        encoded = b" " * 2_000_000
        payload["scenario"].update(
            uncompressed_bytes=128,
            chunks=[base64.b64encode(zlib.compress(encoded)).decode("ascii")],
        )

    rewrite_envelope(path, insert_bomb)
    with pytest.raises(ValueError, match="size does not match"):
        load_checkpoint(path)


def test_expanded_tree_value_limit_cannot_be_bypassed_with_compression(
    tmp_path, monkeypatch
):
    scenario = hill_scenario()
    scenario["extra_values"] = list(range(5000))
    path = save_checkpoint(CivicSimulation(scenario), tmp_path / "many-values.json")
    payload = json.loads(path.read_text())
    monkeypatch.setattr(checkpoint, "MAX_JSON_VALUES", 1000)
    checkpoint._validate_tree(payload)  # Encoded envelope itself is small enough.
    with pytest.raises(ValueError, match="too many JSON values"):
        load_checkpoint(path)


def test_expanded_scenario_and_state_share_bounded_total_bytes(saved, monkeypatch):
    _model, path = saved
    payload = json.loads(path.read_text())
    monkeypatch.setattr(
        checkpoint, "MAX_SCENARIO_BYTES", payload["scenario"]["uncompressed_bytes"]
    )
    with pytest.raises(ValueError, match="scenario and state exceed"):
        load_checkpoint(path)


@pytest.mark.parametrize(
    "encoded",
    [
        b'{"schema_version":1,"schema_version":1}',
        b'{"unexpected":NaN}',
        b'{"unexpected":Infinity}',
        b"\xff",
    ],
)
def test_expanded_json_retains_duplicate_nonfinite_and_unicode_checks(saved, encoded):
    _model, path = saved

    def change_source(payload):
        payload["scenario"].update(
            uncompressed_bytes=len(encoded),
            json_sha256=hashlib.sha256(encoded).hexdigest(),
            chunks=[base64.b64encode(zlib.compress(encoded)).decode("ascii")],
        )

    rewrite_envelope(path, change_source)
    with pytest.raises(ValueError, match="Invalid expanded checkpoint scenario JSON"):
        load_checkpoint(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["verification"].update(unsupported="field"),
        lambda p: p["verification"].update(metadata_state_sha256=True),
        lambda p: p["verification"].update(trip_geometry_sha256=[]),
        lambda p: p["verification"].update(trip_geometry_sha256={"trip": "invalid"}),
    ],
)
def test_verification_structure_and_digest_types_are_strict(saved, mutation):
    _model, path = saved
    rewrite_envelope(path, mutation)
    with pytest.raises(ValueError, match="verification|checksum"):
        load_checkpoint(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata_state_sha256", "0" * 64),
        ("trip_geometry_sha256", {}),
        ("trip_geometry_sha256", {"unknown:outbound:0": "0" * 64}),
    ],
)
def test_resigned_incorrect_verification_is_rejected(saved, field, value):
    _model, path = saved
    rewrite_envelope(path, lambda p: p["verification"].update({field: value}))
    with pytest.raises(ValueError, match="deterministic reconstruction"):
        load_checkpoint(path)


def test_static_metadata_is_verified_without_repeating_it_in_dynamic_state(saved):
    _model, path = saved
    rewrite(
        path,
        lambda p: p["scenario"]["residents"][0].update(label="changed source label"),
        scenario_hashes=True,
    )
    with pytest.raises(ValueError, match="metadata or trip geometry"):
        load_checkpoint(path)


def test_equal_length_alternate_future_geometry_cannot_pass_same_current_pose(tmp_path):
    scenario = hill_scenario()
    scenario["edges"][0]["points"] = [[0, 0, 0], [2, 0, 0], [4, 1, 0], [6, 0, 0]]
    model = CivicSimulation(scenario)
    model.step_ticks(15)
    before = model.snapshot(include_static=False, include_trip_geometry=False)
    path = save_checkpoint(model, tmp_path / "alternate.json")
    scenario["edges"][0]["points"][2][1] = -1
    alternate = CivicSimulation(scenario)
    alternate.step_ticks(15)
    assert (
        alternate.snapshot(include_static=False, include_trip_geometry=False) == before
    )
    rewrite(
        path,
        lambda p: p["scenario"]["edges"][0]["points"][2].__setitem__(1, -1),
        scenario_hashes=True,
    )
    with pytest.raises(ValueError, match="metadata or trip geometry"):
        load_checkpoint(path)


def test_large_encoded_scenario_is_split_without_relaxing_string_limit(tmp_path):
    scenario = hill_scenario()
    scenario["opaque_source_values"] = [
        hashlib.sha256(str(i).encode()).hexdigest() for i in range(5000)
    ]
    model = CivicSimulation(scenario)
    path = save_checkpoint(model, tmp_path / "chunked.json")
    chunks = json.loads(path.read_text())["scenario"]["chunks"]
    assert len(chunks) > 1
    assert max(map(len, chunks)) == checkpoint.MAX_STRING_LENGTH
    assert load_checkpoint(path).scenario == model.scenario


def test_shared_dense_routes_are_stored_once_with_per_trip_verification(tmp_path):
    scenario = hill_scenario()
    scenario["nodes"][1]["position"] = [200, 0, 0]
    scenario["edges"][0]["points"] = [[i, i % 2, 0] for i in range(201)]
    resident = scenario["residents"][0]
    scenario["residents"] = [
        dict(resident, id=f"walker-{i}", return_tick=10_000) for i in range(20)
    ]
    model = CivicSimulation(scenario)
    model.step_ticks(35)
    legacy_path = write_legacy_checkpoint(model, tmp_path / "repeated-v1.json")
    path = save_checkpoint(model, tmp_path / "shared-v2.json")
    payload = json.loads(path.read_text())
    hashes = payload["verification"]["trip_geometry_sha256"]
    assert len(hashes) == 20
    assert len(set(hashes.values())) == 1
    assert all(
        "points" not in person["trip"] for person in payload["state"]["residents"]
    )
    assert path.stat().st_size < legacy_path.stat().st_size / 4
    assert (
        load_checkpoint(path).snapshot()
        == load_checkpoint(legacy_path).snapshot()
        == model.snapshot()
    )
