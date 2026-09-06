"""Persistent person, occupancy, schedule and exact-clock acceptance fixtures."""

from copy import deepcopy
import json
import math
import pickle

import pytest

from civic_center.model import CivicSimulation


def scenario():
    return {
        "schema_version": 1,
        "id": "fixture-day",
        "label": "One resident day",
        "tick_hz": 10,
        "start_time_seconds": 28790,
        "nodes": [
            {"id": "front-door", "position": [0, 0, 0]},
            {"id": "corner", "position": [1, 0, 0]},
            {"id": "work-door", "position": [1, 2, 0]},
        ],
        "edges": [
            {"id": "east", "from": "front-door", "to": "corner", "bidirectional": True},
            {"id": "north", "from": "corner", "to": "work-door", "bidirectional": True},
        ],
        "buildings": [
            {"id": "home", "label": "Home", "entrance_node_id": "front-door", "kind": "home", "capacity": 10},
            {"id": "office", "label": "Office", "entrance_node_id": "work-door", "kind": "work", "capacity": 10},
        ],
        "residents": [
            {
                "id": "resident-1", "label": "Casey", "home_id": "home", "work_id": "office",
                "departure_tick": 10, "return_tick": 100, "speed_mps": 1.0,
                "color": [0.2, 0.4, 0.6], "skin_color": [0.6, 0.4, 0.2],
                "trouser_color": [0.1, 0.2, 0.3], "bag_color": [0.4, 0.2, 0.1], "phase": 0.0,
            }
        ],
    }


def person(sim):
    return sim.snapshot()["residents"][0]


def occupancy(sim):
    return {b["id"]: b["occupancy"] for b in sim.snapshot()["buildings"]}


def daily_scenario():
    seed = scenario()
    seed["schedule"] = {"mode": "daily-v1"}
    return seed


def test_repeating_days_preserve_people_and_use_unique_cycle_trip_ids():
    sim = CivicSimulation(daily_scenario())
    period = 86_400 * sim.tick_hz
    for day in range(4):
        sim.step_ticks(day * period + 20 - sim.tick)
        assert person(sim)["trip"]["id"] == f"resident-1:outbound:{day}"
        assert person(sim)["trip"]["departure_tick"] == day * period + 10
        assert person(sim)["position"] == [1, 0, 0]
        sim.step_ticks(110)
        assert person(sim)["activity"] == "home"
        assert occupancy(sim) == {"home": 1, "office": 0}
        assert sim.snapshot()["event_count"] == (day + 1) * 4
        assert sim.next_event_tick() == (day + 1) * period + 10
    assert len({e["trip_id"] for e in sim.snapshot()["events"]}) == 8


def test_midnight_calendar_metadata_is_independent_of_schedule_cycle():
    seed = daily_scenario()
    seed["start_time_seconds"] = 86_390
    seed["residents"][0].update(departure_tick=90, return_tick=300)
    sim = CivicSimulation(seed)
    sim.step_ticks(100)
    assert sim.snapshot()["day_index"] == 1
    assert sim.snapshot()["day_seconds"] == 0
    assert person(sim)["trip"]["id"] == "resident-1:outbound:0"
    assert person(sim)["activity"] == "walking_to_work"
    sim.step_ticks(5)
    assert sim.snapshot()["day_seconds"] == .5
    assert person(sim)["position"] == [1, .5, 0]
    sim.reset()
    assert sim.snapshot()["day_index"] == 0
    assert sim.snapshot()["day_seconds"] == 86_390


def test_trip_crossing_schedule_period_survives_fast_forward_with_its_original_cycle():
    seed = daily_scenario()
    period = 86_400 * seed["tick_hz"]
    seed["residents"][0].update(departure_tick=period - 20, return_tick=period + 20)
    sim = CivicSimulation(seed)
    sim.step_ticks(period + 5)
    assert person(sim)["trip"]["id"] == "resident-1:outbound:0"
    assert person(sim)["position"] == [1, 1.5, 0]
    sim.step_ticks(999_999 * period)
    assert person(sim)["trip"]["id"] == "resident-1:outbound:999999"
    assert person(sim)["position"] == [1, 1.5, 0]
    assert person(sim)["trip"]["arrival_tick"] == 1_000_000 * period + 10
    assert sim.snapshot()["event_count"] == 4 * 999_999 + 1


def test_large_day_jump_has_bounded_transition_work_memory_and_exact_event_tail(monkeypatch):
    seed = daily_scenario()
    sim = CivicSimulation(seed)
    calls = 0
    original_event = sim._event

    def counted_event(*args, **kwargs):
        nonlocal calls
        calls += 1
        original_event(*args, **kwargs)

    monkeypatch.setattr(sim, "_event", counted_event)
    period = 86_400 * sim.tick_hz
    sim.step_ticks(1_000_000 * period + 50)
    assert calls < 400
    state = sim.snapshot()
    assert state["event_count"] == 4_000_002
    assert len(state["events"]) == 256
    assert [e["sequence"] for e in state["events"]] == list(range(4_000_002 - 255, 4_000_003))
    assert state["events"][-1]["trip_id"] == "resident-1:outbound:1000000"
    assert state["events"][-1]["tick"] == 1_000_000 * period + 40
    assert len(sim._queue) <= 1
    assert len(sim._active_trips) <= 1
    assert len(sim.graph._cache) <= 2
    assert occupancy(sim) == {"home": 0, "office": 1}


def test_daily_fast_forward_and_varied_tick_batches_have_identical_journals():
    seed = daily_scenario()
    seed["residents"] += [dict(seed["residents"][0], id="resident-2", departure_tick=15)]
    single, batched = CivicSimulation(seed), CivicSimulation(seed)
    period = 86_400 * single.tick_hz
    target = 500 * period + 120
    single.step_ticks(target)
    for count in (20, period - 5, 7 * period + 13, 64 * period, 11, 200 * period + 17):
        batched.step_ticks(count)
    batched.step_ticks(target - batched.tick)
    assert batched.snapshot() == single.snapshot()
    assert batched.next_event_tick() == single.next_event_tick()


def test_daily_cycle_skipping_matches_individual_events_with_mixed_blockages():
    seed = daily_scenario()
    seed["nodes"] += [{"id": "isolated", "position": [100, 0, 0]}]
    seed["buildings"] += [{"id": "remote-home", "entrance_node_id": "isolated"}]
    seed["residents"] += [
        dict(seed["residents"][0], id="resident-2", departure_tick=15),
        dict(seed["residents"][0], id="blocked-resident", home_id="remote-home"),
    ]
    fast, individual = CivicSimulation(seed), CivicSimulation(seed)
    target = 200 * 86_400 * fast.tick_hz + 115
    fast.step_ticks(target)
    individual._process_events_to(target)
    assert fast.snapshot() == individual.snapshot()
    assert fast.next_event_tick() == individual.next_event_tick()


def test_daily_zero_duration_shared_building_trips_remain_finite_at_period_boundary():
    seed = daily_scenario()
    seed["residents"][0].update(work_id="home", departure_tick=0, return_tick=0)
    sim = CivicSimulation(seed)
    assert sim.snapshot()["event_count"] == 4
    sim.step_ticks(1_000_000 * 86_400 * sim.tick_hz)
    assert sim.snapshot()["event_count"] == 4_000_004
    assert person(sim)["activity"] == "home"
    assert occupancy(sim) == {"home": 1, "office": 0}
    assert len(sim.snapshot()["events"]) == 256
    assert sim.snapshot()["events"][-1]["trip_id"] == "resident-1:return:1000000"


def test_active_daily_trip_definitions_are_rekeyed_after_cycle_skip():
    sim = CivicSimulation(daily_scenario())
    sim.step_ticks(20)
    initial_id = person(sim)["trip"]["id"]
    initial_geometry = sim.trip_geometries([initial_id])[0]
    sim.step_ticks(100_000 * 86_400 * sim.tick_hz)
    new_id = person(sim)["trip"]["id"]
    with pytest.raises(ValueError, match="inactive"):
        sim.trip_geometries([initial_id])
    new_geometry = sim.trip_geometries([new_id])[0]
    assert dict(new_geometry, id=initial_id) == initial_geometry
    assert len(sim._active_trips) == 1
    new_geometry["points"][0][0] = 900
    assert sim.trip_geometries([new_id])[0]["points"][0][0] == 0


def test_private_worker_transfer_preserves_nested_templates_and_daily_continuation():
    seed = daily_scenario()
    seed["edges"][0]["points"] = [[0, 0, 0], [.5, 0, .5], [1, 0, 0]]
    seed["buildings"][0]["footprint"] = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    seed["residents"][0]["provenance"] = {"synthetic": ["home", "work"]}
    original = CivicSimulation(seed)
    original.step_ticks(20)
    # Pickle is used only for data from the owned worker child process; public
    # saves and protocol inputs continue to use the strict JSON formats.
    received = pickle.loads(pickle.dumps(original, protocol=pickle.HIGHEST_PROTOCOL))
    assert received.snapshot() == original.snapshot()
    snapshot = received.snapshot()
    snapshot["buildings"][0]["footprint"][0][0] = 100
    snapshot["residents"][0]["provenance"]["synthetic"].clear()
    assert received.snapshot() == original.snapshot()
    ticks = 100_000 * 86_400 * original.tick_hz + 100
    original.step_ticks(ticks)
    received.step_ticks(ticks)
    assert received.snapshot() == original.snapshot()


def test_daily_blocked_residents_are_retained_without_unbounded_retries():
    seed = daily_scenario()
    seed["edges"] = []
    sim = CivicSimulation(seed)
    sim.step_ticks(1_000_000 * 86_400 * sim.tick_hz)
    assert person(sim)["activity"] == "blocked"
    assert occupancy(sim) == {"home": 1, "office": 0}
    assert sim.snapshot()["event_count"] == 1
    assert len(sim.snapshot()["events"]) == 1
    assert sim.next_event_tick() is None


def test_daily_return_disconnection_blocks_at_work_before_period_skips():
    seed = daily_scenario()
    for edge in seed["edges"]:
        edge["bidirectional"] = False
    sim = CivicSimulation(seed)
    sim.step_ticks(10_000 * 86_400 * sim.tick_hz)
    assert person(sim)["activity"] == "blocked"
    assert occupancy(sim) == {"home": 0, "office": 1}
    assert sim.snapshot()["event_count"] == 3
    assert sim.next_event_tick() is None


@pytest.mark.parametrize("schedule", [None, True, {}, {"mode": "daily-v2"}, {"mode": "daily-v1", "period": 1}])
def test_unsupported_repeat_schedule_is_rejected(schedule):
    seed = scenario()
    seed["schedule"] = schedule
    with pytest.raises(ValueError, match="schedule"):
        CivicSimulation(seed)


def test_overlapping_daily_trips_and_unsafe_jump_are_rejected_before_advancement():
    seed = daily_scenario()
    seed["residents"][0]["speed_mps"] = .00001
    with pytest.raises(ValueError, match="overlaps"):
        CivicSimulation(seed)
    sim = CivicSimulation(daily_scenario())
    before = sim.snapshot()
    with pytest.raises(ValueError, match="JSON-safe"):
        sim.step_ticks(1 << 53)
    assert sim.snapshot() == before


def test_persistent_resident_completes_day_with_exactly_one_arrival_per_trip():
    sim = CivicSimulation(scenario())
    assert person(sim)["activity"] == "home"
    assert occupancy(sim) == {"home": 1, "office": 0}
    assert sim.next_event_tick() == 10
    sim.advance_ticks(10)
    resident = person(sim)
    assert resident["id"] == "resident-1"
    assert resident["activity"] == "walking_to_work"
    assert resident["trip"]["points"] == [[0, 0, 0], [1, 0, 0], [1, 2, 0]]
    assert resident["trip"]["arrival_tick"] == 40
    assert resident["trip"]["departure_tick"] == 10
    assert resident["position"] == [0, 0, 0]
    assert resident["visible"] and resident["moving"]
    assert occupancy(sim) == {"home": 0, "office": 0}
    sim.advance_ticks(10)
    assert person(sim)["position"] == [1, 0, 0]
    assert person(sim)["heading"] == math.pi / 2
    assert person(sim)["trip"]["segment_progress"] == 0
    sim.advance_ticks(20)
    assert person(sim)["activity"] == "at_work"
    assert person(sim)["position"] == [1, 2, 0]
    assert person(sim)["trip"] is None
    assert not person(sim)["visible"]
    assert occupancy(sim) == {"home": 0, "office": 1}
    sim.advance_ticks(60)
    assert person(sim)["activity"] == "walking_home"
    assert occupancy(sim) == {"home": 0, "office": 0}
    sim.advance_ticks(30)
    assert person(sim)["activity"] == "home"
    assert person(sim)["id"] == "resident-1"
    assert occupancy(sim) == {"home": 1, "office": 0}
    assert sim.next_event_tick() is None
    sim.advance_ticks(100_000)
    events = sim.snapshot()["events"]
    assert [event["type"] for event in events] == ["departure", "arrival", "departure", "arrival"]
    assert [event["tick"] for event in events] == [10, 40, 100, 130]
    assert len({e["trip_id"] for e in events if e["type"] == "arrival"}) == 2
    assert len(sim.snapshot()["residents"]) == 1


def test_equal_tick_batches_and_speed_produce_identical_state_and_event_order():
    seed = scenario()
    seed["residents"] += [dict(seed["residents"][0], id="resident-2", departure_tick=15)]
    single, batched = CivicSimulation(seed), CivicSimulation(seed)
    single.advance_ticks(135)
    for count in [1, 14, 3, 22, 41, 54]:
        batched.advance_ticks(count)
    assert single.snapshot() == batched.snapshot()
    fast = CivicSimulation(seed)
    fast.set_speed(4)
    fast.advance_ticks(135)
    fast_state = fast.snapshot()
    fast_state["speed"] = 1.0
    assert fast_state == single.snapshot()


def test_pause_forced_step_reset_and_detached_snapshots():
    seed = scenario()
    sim = CivicSimulation(seed)
    initial = sim.snapshot()
    seed["residents"][0]["label"] = "External change"
    sim.advance_ticks(15)
    sim.set_paused(True)
    paused = sim.snapshot()
    assert person(sim)["visible"] and person(sim)["moving"]
    assert sim.advance_ticks(400) == 15
    assert sim.snapshot() == paused
    assert sim.step_ticks(1) == 16
    assert sim.paused
    sim.set_speed(8)
    sim.reset()
    assert sim.snapshot() == initial
    modified = sim.snapshot()
    modified["residents"][0]["color"][0] = 99
    modified["buildings"][0]["resident_ids"].clear()
    assert sim.snapshot() == initial
    json.dumps(sim.snapshot(), allow_nan=False)


def test_unreachable_destination_preserves_resident_and_origin_occupancy():
    seed = scenario()
    seed["edges"] = []
    sim = CivicSimulation(seed)
    sim.advance_ticks(1_000)
    resident = person(sim)
    assert resident["activity"] == "blocked"
    assert resident["id"] == "resident-1"
    assert resident["building_id"] == "home"
    assert resident["position"] == [0, 0, 0]
    assert not resident["visible"]
    assert resident["blocked_reason"] == "No walking route from home to office"
    assert occupancy(sim) == {"home": 1, "office": 0}
    assert sim.snapshot()["event_count"] == 1


def test_unreachable_return_preserves_resident_at_work():
    seed = scenario()
    for edge in seed["edges"]:
        edge["bidirectional"] = False
    sim = CivicSimulation(seed)
    sim.advance_ticks(1_000)
    assert person(sim)["activity"] == "blocked"
    assert person(sim)["building_id"] == "office"
    assert occupancy(sim) == {"home": 0, "office": 1}
    assert [e["type"] for e in sim.snapshot()["events"]] == ["departure", "arrival", "blocked"]


def test_many_short_edges_cross_in_one_tick_without_overshooting_endpoint():
    seed = scenario()
    for node, x in zip(seed["nodes"], [0.0, 0.01, 0.02]):
        node["position"] = [x, 0, 0]
    sim = CivicSimulation(seed)
    sim.advance_ticks(10)
    assert person(sim)["trip"]["arrival_tick"] == 11
    sim.advance_ticks(1)
    assert person(sim)["position"] == [0.02, 0, 0]
    assert person(sim)["activity"] == "at_work"


def test_arrival_uses_ceiling_tick_for_non_integral_duration():
    seed = scenario()
    seed["residents"][0]["speed_mps"] = 4
    sim = CivicSimulation(seed)
    sim.advance_ticks(10)
    assert person(sim)["trip"]["arrival_tick"] == 18
    sim.advance_ticks(7)
    assert person(sim)["activity"] == "walking_to_work"
    assert person(sim)["position"] == pytest.approx([1, 1.8, 0])
    sim.advance_ticks(1)
    assert person(sim)["activity"] == "at_work"


def test_return_scheduled_before_work_arrival_starts_when_work_is_reached():
    seed = scenario()
    seed["residents"][0]["return_tick"] = 20
    sim = CivicSimulation(seed)
    sim.advance_ticks(40)
    assert person(sim)["activity"] == "walking_home"
    events = sim.snapshot()["events"]
    assert [e["tick"] for e in events] == [10, 40, 40]
    assert occupancy(sim) == {"home": 0, "office": 0}


def test_same_entrance_and_tick_zero_transitions_do_not_loop():
    seed = scenario()
    seed["buildings"][1]["entrance_node_id"] = "front-door"
    seed["residents"][0].update(departure_tick=0, return_tick=0)
    sim = CivicSimulation(seed)
    assert sim.tick == 0
    assert person(sim)["activity"] == "home"
    assert sim.snapshot()["event_count"] == 4
    assert occupancy(sim) == {"home": 1, "office": 0}


def test_snapshot_journal_is_bounded_but_total_counts_all_arrivals():
    seed = scenario()
    seed["residents"] = [dict(seed["residents"][0], id=f"resident-{i:04d}") for i in range(100)]
    sim = CivicSimulation(seed)
    sim.advance_ticks(200)
    state = sim.snapshot()
    assert len(state["events"]) == 256
    assert state["event_count"] == 400
    assert state["events"][0]["sequence"] == 145
    assert occupancy(sim) == {"home": 100, "office": 0}


@pytest.mark.parametrize("count", [-1, 1.5, True, "10"])
def test_invalid_advancement_rejected_even_while_paused(count):
    sim = CivicSimulation(scenario())
    sim.set_paused(True)
    with pytest.raises(ValueError):
        sim.advance_ticks(count)


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), True])
def test_invalid_speed_rejected(speed):
    sim = CivicSimulation(scenario())
    with pytest.raises(ValueError):
        sim.set_speed(speed)


def test_invalid_identity_assignment_and_schedule_rejected():
    seed = scenario()
    seed["residents"] *= 2
    with pytest.raises(ValueError, match="duplicate resident"):
        CivicSimulation(seed)
    seed = scenario()
    seed["residents"][0]["home_id"] = "missing"
    with pytest.raises(ValueError, match="unknown home_id"):
        CivicSimulation(seed)
    seed = scenario()
    seed["residents"][0]["return_tick"] = 0
    with pytest.raises(ValueError, match="returns before departure"):
        CivicSimulation(seed)


def test_snapshots_detach_nested_metadata_routes_occupancy_and_event_records():
    seed = scenario()
    seed["residents"][0]["metadata"] = {
        "preferences": ["walking", {"tags": ["early-shift"]}],
        "notes": {"source": "synthetic"},
    }
    seed["buildings"][0]["metadata"] = {"floors": [{"name": "ground"}]}
    sim = CivicSimulation(seed)
    sim.advance_ticks(15)
    before = sim.snapshot()
    changed = sim.snapshot()
    changed["residents"][0]["metadata"]["preferences"][1]["tags"].append("changed")
    changed["residents"][0]["metadata"]["notes"]["source"] = "changed"
    changed["residents"][0]["color"].clear()
    changed["residents"][0]["trip"]["points"][0][0] = 999
    changed["residents"][0]["trip"]["node_ids"].clear()
    changed["buildings"][0]["metadata"]["floors"][0]["name"] = "changed"
    changed["buildings"][0]["resident_ids"].append("fake-person")
    changed["events"][0]["type"] = "changed"
    assert sim.snapshot() == before
    assert seed["residents"][0]["metadata"]["preferences"][1]["tags"] == ["early-shift"]
    sim.reset()
    assert sim.snapshot()["residents"][0]["metadata"]["notes"]["source"] == "synthetic"


def test_repeated_snapshots_update_corner_progress_and_do_not_mutate_old_frames():
    sim = CivicSimulation(scenario())
    sim.advance_ticks(15)
    first = sim.snapshot()
    assert first["residents"][0]["position"] == [.5, 0, 0]
    assert first["residents"][0]["trip"]["segment_progress"] == .5
    sim.advance_ticks(10)
    later = sim.snapshot()
    assert later["residents"][0]["position"] == [1, .5, 0]
    assert later["residents"][0]["trip"]["segment_index"] == 1
    assert later["residents"][0]["trip"]["segment_progress"] == .25
    assert later["residents"][0]["heading"] == math.pi / 2
    assert first["tick"] == 15
    assert first["residents"][0]["position"] == [.5, 0, 0]
    sim.advance_ticks(15)
    arrived = sim.snapshot()
    assert arrived["residents"][0]["trip"] is None
    assert arrived["residents"][0]["activity"] == "at_work"
    assert len(arrived["events"]) == 2
    assert len(first["events"]) == 1
    assert len(later["events"]) == 1


def test_snapshot_ids_remain_sorted_with_reordered_scenario_records():
    seed = scenario()
    seed["residents"] = [dict(seed["residents"][0], id=identity) for identity in ("person-z", "person-a", "person-m")]
    seed["buildings"].reverse()
    sim = CivicSimulation(seed)
    for tick in (0, 20, 200):
        sim.step_ticks(tick - sim.tick)
        state = sim.snapshot()
        assert [record["id"] for record in state["residents"]] == ["person-a", "person-m", "person-z"]
        assert [record["id"] for record in state["buildings"]] == ["home", "office"]


@pytest.mark.parametrize("tick", [0, 15, 40, 110, 200])
def test_dynamic_snapshot_merged_over_static_scenario_equals_complete_snapshot(tick):
    seed = scenario()
    seed["residents"][0]["notes"] = {"nested": ["metadata"]}
    seed["buildings"][0]["footprint"] = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    sim = CivicSimulation(seed)
    sim.step_ticks(tick)
    complete = sim.snapshot()
    dynamic = sim.snapshot(include_static=False)
    assert "color" not in dynamic["residents"][0]
    assert "home_id" not in dynamic["residents"][0]
    assert "footprint" not in dynamic["buildings"][0]
    merged = deepcopy(dynamic)
    for field in ("residents", "buildings"):
        sources = {record["id"]: record for record in seed[field]}
        merged[field] = [dict(deepcopy(sources[record["id"]]), **record) for record in dynamic[field]]
    assert merged == complete
    assert json.dumps(merged, separators=(",", ":")) == json.dumps(complete, separators=(",", ":"))
    if dynamic["residents"][0]["trip"] is not None:
        dynamic["residents"][0]["trip"]["points"][0][0] = 99
    dynamic["buildings"][0]["resident_ids"].append("changed")
    if dynamic["events"]:
        dynamic["events"][0]["type"] = "changed"
    assert sim.snapshot() == complete


def test_polyline_hill_controls_travel_duration_and_batch_independent_pose():
    seed = scenario()
    seed["nodes"][1]["position"] = [6, 0, 0]
    seed["nodes"][2]["position"] = [7, 0, 0]
    seed["edges"][0]["points"] = [[0, 0, 0], [3, 0, 4], [6, 0, 0]]
    seed["residents"][0]["return_tick"] = 300
    direct, batched = CivicSimulation(seed), CivicSimulation(seed)
    direct.step_ticks(35)
    for count in (4, 6, 10, 15):
        batched.step_ticks(count)
    assert direct.snapshot() == batched.snapshot()
    person = direct.snapshot()["residents"][0]
    assert person["position"] == [1.5, 0, 2]
    assert person["trip"]["arrival_tick"] == 120
    assert person["trip"]["node_ids"] == ["front-door", "corner", "work-door"]
    assert len(person["trip"]["points"]) == 4


def test_compact_trip_references_merge_with_definitions_to_complete_trip():
    seed = scenario()
    seed["residents"].append(dict(seed["residents"][0], id="resident-2"))
    sim = CivicSimulation(seed)
    sim.step_ticks(25)
    complete = sim.snapshot()
    compact = sim.snapshot(include_static=False, include_trip_geometry=False)
    ids = [record["trip"]["id"] for record in compact["residents"]]
    definitions = sim.trip_geometries([ids[1], ids[0], ids[1]])
    assert [definition["id"] for definition in definitions] == [ids[1], ids[0]]
    by_id = {definition["id"]: definition for definition in definitions}
    for expected, reference in zip(complete["residents"], compact["residents"]):
        assert "points" not in reference["trip"]
        assert "node_ids" not in reference["trip"]
        assert "length_m" not in reference["trip"]
        assert dict(by_id[reference["trip"]["id"]], **reference["trip"]) == expected["trip"]
    definitions[0]["points"][0][0] = 999
    definitions[0]["node_ids"].clear()
    assert sim.snapshot() == complete
    assert sim.trip_geometries([]) == []


def test_trip_definition_lookup_rejects_unknown_arrived_and_reset_ids():
    sim = CivicSimulation(scenario())
    with pytest.raises(ValueError, match="inactive"):
        sim.trip_geometries(["resident-1:outbound:0"])
    sim.step_ticks(20)
    identity = person(sim)["trip"]["id"]
    with pytest.raises(ValueError, match="inactive"):
        sim.trip_geometries([identity, "missing"])
    with pytest.raises(ValueError, match="iterable"):
        sim.trip_geometries(identity)
    with pytest.raises(ValueError, match="nonempty"):
        sim.trip_geometries([True])
    sim.step_ticks(20)
    with pytest.raises(ValueError, match="inactive"):
        sim.trip_geometries([identity])
    sim.step_ticks(60)
    returning = person(sim)["trip"]["id"]
    assert sim.trip_geometries([returning])
    sim.reset()
    with pytest.raises(ValueError, match="inactive"):
        sim.trip_geometries([returning])


def test_immutable_geometry_capture_survives_arrival_reset_and_private_transfer():
    sim = CivicSimulation(daily_scenario())
    sim.step_ticks(25)
    identities = sim.active_trip_ids()
    assert type(identities) is tuple
    captured = sim.capture_trip_geometries(identities)
    expected_json = json.dumps(sim.trip_geometries(identities), separators=(",", ":"))
    assert json.dumps(captured, separators=(",", ":")) == expected_json
    assert captured[0]["points"] is sim._active_trips[identities[0]].route.points
    assert captured[0]["node_ids"] is sim._active_trips[identities[0]].route.node_ids
    with pytest.raises(TypeError):
        captured[0]["points"][0][0] = 999
    sim.step_ticks(1000)
    sim.reset()
    assert sim.active_trip_ids() == ()
    assert json.dumps(captured, separators=(",", ":")) == expected_json
    transferred = pickle.loads(pickle.dumps(captured))
    assert json.dumps(transferred, separators=(",", ":")) == expected_json
    captured[0]["id"] = "changed detached envelope"
    assert json.dumps(transferred, separators=(",", ":")) == expected_json
