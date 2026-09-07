"""Live population mutations preserve the running day and survive saved-game reload."""

from __future__ import annotations

import json

import pytest

from civic_center.checkpoint import (
    capture_checkpoint,
    load_checkpoint,
    prepare_checkpoint_capture,
    save_checkpoint,
    write_captured_checkpoint,
)
from civic_center.model import CivicSimulation
from civic_center.population import (
    commit_population,
    frozen_population_view,
    prepare_population_delta,
    preview_population,
    validate_population,
)
from civic_center.scenario import make_scenario


def adjust(simulation, target):
    frozen = frozen_population_view(simulation)
    delta = prepare_population_delta(frozen, target)
    candidate = preview_population(simulation, delta)
    commit_population(simulation, candidate)
    return delta


def by_id(snapshot):
    return {row["id"]: row for row in snapshot["residents"]}


@pytest.mark.parametrize("value", [0, -1, 5001, True, 1.0, "200", None])
def test_live_count_validation_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_population(value)


@pytest.mark.parametrize("tick", [0, 4000, 500000, 7000000, 19000000])
def test_additions_preserve_exact_survivor_state_and_controls(tick):
    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    simulation.step_ticks(tick)
    simulation.set_paused(True)
    simulation.set_speed(60)
    before = simulation.snapshot()
    old_objects = dict(simulation._residents)
    adjust(simulation, 57)
    after = simulation.snapshot()
    assert simulation.tick == tick
    assert simulation.paused and simulation.speed == 60
    assert by_id(before) == {
        key: value for key, value in by_id(after).items() if key in old_objects
    }
    assert all(
        simulation._residents[key] is value for key, value in old_objects.items()
    )
    assert len(after["residents"]) == 57
    assert (
        sum(row["occupancy"] for row in after["buildings"])
        + len(simulation._active_trips)
        == 57
    )
    assert all(event[0] > tick for event in simulation._queue)
    assert set(simulation.joined_at.values()) == {tick}
    assert after["event_count"] == before["event_count"] + 37


def test_candidate_commits_at_actual_current_tick_not_preparation_tick():
    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    frozen = frozen_population_view(simulation)
    delta = prepare_population_delta(frozen, 100)
    simulation.step_ticks(900000)
    before = by_id(simulation.snapshot())
    candidate = preview_population(simulation, delta)
    commit_population(simulation, candidate)
    assert simulation.tick == 900000
    assert {
        key: value
        for key, value in by_id(simulation.snapshot()).items()
        if key in before
    } == before
    assert set(simulation.joined_at.values()) == {900000}


def test_newcomer_state_matches_current_schedule_without_past_event_insertion():
    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    simulation.step_ticks(3600 * 200)
    before_count = simulation._event_count
    adjust(simulation, 21)
    identity = next(iter(simulation.joined_at))
    baseline = CivicSimulation(simulation.scenario)
    baseline.step_ticks(simulation.tick)
    assert (
        by_id(simulation.snapshot())[identity] == by_id(baseline.snapshot())[identity]
    )
    assert simulation._event_count == before_count + 1
    assert simulation.snapshot()["events"][-1]["type"] == "resident_added"


def test_remove_newest_first_and_never_resurrect_or_reuse_ids():
    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    original = set(simulation._sources)
    adjust(simulation, 35)
    first_added = set(simulation._sources) - original
    simulation.step_ticks(180000)
    delta = adjust(simulation, 22)
    assert len(set(delta.removals) & first_added) == 13
    survivors = set(simulation._sources)
    simulation.step_ticks(3 * 86400 * 200)
    assert set(simulation._sources) == survivors
    assert all(row[2] in survivors for row in simulation._queue)
    adjust(simulation, 35)
    assert not (set(simulation._sources) - survivors) & set(delta.removals)
    assert simulation.next_resident_identity == 28
    adjust(simulation, 1)
    assert len(simulation._sources) == 1
    assert set(simulation._sources) <= original


def test_survivors_evolve_identically_after_removal():
    scenario = make_scenario(20, repeat_days=True)
    simulation = CivicSimulation(scenario)
    control = CivicSimulation(scenario)
    simulation.step_ticks(90000)
    control.step_ticks(90000)
    adjust(simulation, 7)
    simulation.step_ticks(86400 * 200)
    control.step_ticks(86400 * 200)
    actual = by_id(simulation.snapshot())
    assert actual == {
        key: value for key, value in by_id(control.snapshot()).items() if key in actual
    }


def test_noop_has_no_side_effects_and_stale_candidate_is_rejected():
    simulation = CivicSimulation(make_scenario(20))
    before = simulation.snapshot()
    delta = prepare_population_delta(frozen_population_view(simulation), 20)
    assert preview_population(simulation, delta) is simulation
    commit_population(simulation, simulation)
    assert simulation.snapshot() == before and simulation.roster_revision == 0
    candidate = preview_population(
        simulation, prepare_population_delta(frozen_population_view(simulation), 21)
    )
    simulation.step_ticks(1)
    with pytest.raises(ValueError, match="current"):
        commit_population(simulation, candidate)


@pytest.mark.parametrize("paused", [True, False])
def test_live_checkpoint_exact_roundtrip_and_future_resize(tmp_path, paused):
    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    simulation.step_ticks(180000)
    adjust(simulation, 55)
    simulation.step_ticks(5000)
    adjust(simulation, 29)
    simulation.set_paused(paused)
    simulation.set_speed(4)
    before = simulation.snapshot()
    path = save_checkpoint(simulation, tmp_path / "day.json")
    assert json.loads(path.read_text())["checkpoint_version"] == 3
    loaded = load_checkpoint(path)
    assert loaded.snapshot() == before
    assert loaded.roster_revision == 2
    assert loaded.next_resident_identity == 35
    assert loaded.joined_at == simulation.joined_at
    loaded.step_ticks(200000)
    simulation.step_ticks(200000)
    assert loaded.snapshot() == simulation.snapshot()
    adjust(loaded, 40)
    assert loaded.next_resident_identity == 46


def test_prepared_checkpoint_detects_changed_roster_and_capture_is_detached(tmp_path):
    simulation = CivicSimulation(make_scenario(20))
    prepared = prepare_checkpoint_capture(simulation)
    adjust(simulation, 30)
    with pytest.raises(ValueError, match="stale roster"):
        capture_checkpoint(simulation, prepared)
    capture = capture_checkpoint(simulation)
    before = simulation.snapshot()
    adjust(simulation, 5)
    path = write_captured_checkpoint(capture, tmp_path / "captured.json")
    assert load_checkpoint(path).snapshot() == before


def test_reset_keeps_current_roster_and_allocator_and_saves_again(tmp_path):
    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    simulation.step_ticks(90000)
    adjust(simulation, 40)
    identities = set(simulation._sources)
    simulation.reset()
    assert simulation.tick == 0 and set(simulation._sources) == identities
    assert simulation.next_resident_identity == 20
    assert set(simulation.joined_at.values()) == {0}
    assert (
        load_checkpoint(save_checkpoint(simulation, tmp_path / "reset.json")).snapshot()
        == simulation.snapshot()
    )


def test_failed_preparation_does_not_change_live_model():
    simulation = CivicSimulation(make_scenario(20))
    before = simulation.snapshot()
    with pytest.raises(ValueError):
        prepare_population_delta(frozen_population_view(simulation), 5001)
    assert simulation.snapshot() == before


@pytest.mark.parametrize("field", ["allocator", "joined", "queue", "duplicate", "trip"])
def test_live_checkpoint_rejects_resigned_invalid_runtime(tmp_path, field):
    from civic_center.checkpoint import _digest

    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    simulation.step_ticks(180000)
    adjust(simulation, 35)
    path = save_checkpoint(simulation, tmp_path / "tampered.json")
    document = json.loads(path.read_text())
    runtime = document["runtime"]
    if field == "allocator":
        runtime["next_resident_identity"] = 1
    elif field == "joined":
        runtime["joined_at"][next(iter(runtime["joined_at"]))] = simulation.tick + 1
    elif field == "queue":
        runtime["queue"][0][2] = "retired-nonexistent-id"
    elif field == "duplicate":
        runtime["residents"].append(runtime["residents"][0])
    else:
        row = next(row for row in runtime["residents"] if row["trip"] is not None)
        row["trip"]["arrival_tick"] += 1
    document["sha256"] = _digest(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_checkpoint(path)


@pytest.mark.parametrize(
    "tick", [1999, 2000, 2001, 2999, 3000, 3001, 10000, 11000, 17_280_000]
)
def test_join_exact_departure_arrival_and_daily_boundary(tick):
    scenario = make_scenario(1, repeat_days=True)
    source = scenario["residents"][0]
    source["departure_tick"] = 2000
    source["return_tick"] = 10000
    source["speed_mps"] = 10000.0
    simulation = CivicSimulation(scenario)
    simulation.step_ticks(tick)
    adjust(simulation, 2)
    identity = next(iter(simulation.joined_at))
    oracle = CivicSimulation(simulation.scenario)
    oracle.step_ticks(tick)
    assert by_id(simulation.snapshot())[identity] == by_id(oracle.snapshot())[identity]
    assert all(event[0] > tick for event in simulation._queue)


def test_live_checkpoint_runtime_shares_expanded_json_value_budget(
    tmp_path, monkeypatch
):
    import civic_center.checkpoint as checkpoint_module

    simulation = CivicSimulation(make_scenario(20, repeat_days=True))
    simulation.step_ticks(180000)
    adjust(simulation, 35)
    path = save_checkpoint(simulation, tmp_path / "bounded.json")
    document = json.loads(path.read_text())
    prior_count = checkpoint_module._validate_tree(
        {
            "scenario": simulation.scenario,
            "state": document["state"],
            "verification": document["verification"],
        }
    )
    runtime_count = checkpoint_module._validate_tree(document["runtime"])
    monkeypatch.setattr(
        checkpoint_module, "MAX_JSON_VALUES", prior_count + runtime_count // 2
    )
    with pytest.raises(ValueError, match="too many JSON values"):
        load_checkpoint(path)
