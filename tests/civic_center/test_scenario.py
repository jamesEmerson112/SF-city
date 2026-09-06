"""Integration acceptance for seeded residents on the original City Hall block."""

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
from time import perf_counter

import pytest

from civic_center.model import CivicSimulation
from civic_center.scenario import make_scenario, scenario_hash, load_scenario, write_scenario

ROOT = Path(__file__).resolve().parents[2]


def test_repeating_schedule_is_explicit_and_default_pilot_data_remains_identical():
    original = make_scenario(20, 7)
    repeated = make_scenario(20, 7, repeat_days=True)
    assert "schedule" not in original
    assert repeated["schedule"] == {"mode": "daily-v1"}
    repeated_without_flag = deepcopy(repeated)
    del repeated_without_flag["schedule"]
    repeated_without_flag["sha256"] = scenario_hash(repeated_without_flag)
    assert repeated_without_flag == original
    sim = CivicSimulation(repeated)
    sim.step_ticks(3 * 86_400 * sim.tick_hz + 12 * 3600 * sim.tick_hz)
    assert sim.snapshot()["event_count"] == 20 * 4 * 4
    assert all(r["activity"] == "home" for r in sim.snapshot()["residents"])


def test_default_one_resident_replay_stays_exact():
    replay = json.loads((ROOT / "contracts" / "one-resident-replay.json").read_text())
    simulation = CivicSimulation(replay["scene"]["scenario"])
    for expected in replay["snapshots"]:
        state = {key: value for key, value in expected.items()
                 if key not in {"type", "protocol_version", "session_id", "sequence"}}
        simulation.step_ticks(state["tick"] - simulation.tick)
        assert simulation.snapshot() == state


@pytest.fixture(scope="module")
def visual_scene():
    path = ROOT / "comparison" / "shared" / "scene.json"
    return json.loads(path.read_text(encoding="utf-8"))


def enters_rectangle(first, second, minimum, maximum):
    """Segment intersects the strict 2D interior, including between endpoints."""
    low, high = 0.0, 1.0
    for axis in range(2):
        start, delta = first[axis], second[axis] - first[axis]
        minimum_axis, maximum_axis = minimum[axis] + 1e-7, maximum[axis] - 1e-7
        if delta == 0:
            if not minimum_axis <= start <= maximum_axis:
                return False
        else:
            entering, leaving = sorted(((minimum_axis - start) / delta, (maximum_axis - start) / delta))
            low, high = max(low, entering), min(high, leaving)
            if low > high:
                return False
    return low <= high


def test_seeded_population_prefixes_keep_assignments_and_appearance():
    small, larger = make_scenario(200, 31), make_scenario(1000, 31)
    assert larger["residents"][:200] == small["residents"]
    assert make_scenario(200, 31) == small
    different = make_scenario(200, 32)
    assert [r["id"] for r in different["residents"]] == [r["id"] for r in small["residents"]]
    assert different["residents"] != small["residents"]
    assert small["sha256"] == scenario_hash(small)
    assert small["sha256"] != larger["sha256"]


def test_scenario_generation_does_not_share_mutable_palette_state():
    expected = make_scenario(20)
    changed = make_scenario(20)
    changed["residents"][0]["color"][0] = 999
    changed["residents"][0]["skin_color"][0] = 999
    assert make_scenario(20) == expected
    assert changed["residents"][3]["color"] != changed["residents"][0]["color"]


def test_actual_one_resident_walks_to_city_hall_door_then_returns_home():
    seed = make_scenario(1)
    sim = CivicSimulation(seed)
    first = sim.snapshot()["residents"][0]
    assert first["position"] == [-113, 0, .08]
    assert sim.snapshot()["clock_seconds"] == 7 * 3600 + 59 * 60 + 50
    sim.advance_ticks(sim.next_event_tick())
    walking = sim.snapshot()["residents"][0]
    assert walking["id"] == first["id"]
    assert walking["activity"] == "walking_to_work"
    assert sim.snapshot()["clock_seconds"] == 8 * 3600
    assert walking["trip"]["points"][0] == first["position"]
    assert walking["trip"]["points"][-1] == [0, 7, 2.4]
    assert walking["trip"]["destination_id"] == "city-hall"
    length = sum(math.dist(a, b) for a, b in zip(walking["trip"]["points"], walking["trip"]["points"][1:]))
    arrival = walking["trip"]["arrival_tick"]
    assert arrival - sim.tick == math.ceil(length / walking["speed_mps"] * seed["tick_hz"])
    sim.advance_ticks(arrival - sim.tick)
    arrived = sim.snapshot()["residents"][0]
    assert arrived["activity"] == "at_work"
    assert arrived["position"] == [0, 7, 2.4]
    assert not arrived["visible"]
    assert sum(b["occupancy"] for b in sim.snapshot()["buildings"] if b["id"] == "city-hall") == 1
    sim.advance_ticks(sim.next_event_tick() - sim.tick)
    assert sim.snapshot()["clock_seconds"] == 17 * 3600
    assert sim.snapshot()["residents"][0]["activity"] == "walking_home"
    sim.advance_ticks(sim.next_event_tick() - sim.tick)
    assert sim.snapshot()["residents"][0]["position"] == first["position"]
    assert sim.snapshot()["residents"][0]["activity"] == "home"
    assert sim.snapshot()["event_count"] == 4


def test_walking_segments_avoid_building_interiors_except_own_entrance(visual_scene):
    seed = make_scenario(1)
    points = {n["id"]: n["position"] for n in seed["nodes"]}
    entrances = {b["id"]: b["entrance_node_id"] for b in seed["buildings"]}
    for edge in seed["edges"]:
        a, b = points[edge["from"]], points[edge["to"]]
        for box in visual_scene["collision_boxes"]:
            if not enters_rectangle(a, b, box["min"], box["max"]):
                continue
            # A dedicated entrance connector may terminate in its own building;
            # a through edge or a neighboring building cannot use that exception.
            assert entrances[box["id"]] in (edge["from"], edge["to"]), (edge["id"], box["id"])
            outside = b if edge["from"] == entrances[box["id"]] else a
            assert not enters_rectangle(outside, outside, box["min"], box["max"])


def test_plaza_paths_avoid_raised_lawns_and_fountain(visual_scene):
    seed = make_scenario(1)
    points = {n["id"]: n["position"] for n in seed["nodes"]}
    lawns = [p for p in visual_scene["primitives"] if p["id"].startswith("lawn-")]
    fountain = next(p for p in visual_scene["primitives"] if p["id"] == "fountain-base")
    for edge in seed["edges"]:
        a, b = points[edge["from"]], points[edge["to"]]
        for lawn in lawns:
            minimum = [lawn["position"][axis] - lawn["size"][axis] / 2 for axis in range(2)]
            maximum = [lawn["position"][axis] + lawn["size"][axis] / 2 for axis in range(2)]
            assert not enters_rectangle(a, b, minimum, maximum), (edge["id"], lawn["id"])
        delta = [b[axis] - a[axis] for axis in range(2)]
        length_squared = sum(v * v for v in delta)
        if length_squared:
            t = max(0, min(1, sum((fountain["position"][i] - a[i]) * delta[i] for i in range(2)) / length_squared))
            closest = [a[i] + delta[i] * t for i in range(2)]
            assert math.dist(closest, fountain["position"][:2]) > fountain["radius"] + .3


def test_routes_stay_above_block_and_plaza_surfaces(visual_scene):
    seed = make_scenario(1)
    points = {n["id"]: n["position"] for n in seed["nodes"]}
    floors = [p for p in visual_scene["primitives"] if p["id"] in ("civic-block", "plaza")]
    for edge in seed["edges"]:
        a, b = points[edge["from"]], points[edge["to"]]
        for fraction in [i / 20 for i in range(21)]:
            point = [a[i] + fraction * (b[i] - a[i]) for i in range(3)]
            for floor in floors:
                minimum = [floor["position"][i] - floor["size"][i] / 2 for i in range(2)]
                maximum = [floor["position"][i] + floor["size"][i] / 2 for i in range(2)]
                if enters_rectangle(point, point, minimum, maximum):
                    top = floor["position"][2] + floor["size"][2] / 2
                    assert point[2] >= top - 1e-7, (edge["id"], point, floor["id"])


@pytest.mark.parametrize("population", [200, 1000, 5000])
def test_complete_day_conserves_population_and_building_assignments(population, record_property):
    seed = make_scenario(population)
    started = perf_counter()
    sim = CivicSimulation(seed)
    initialized = perf_counter()
    sim.advance_ticks(3600 * seed["tick_hz"])
    morning = sim.snapshot()
    assert all(r["activity"] == "at_work" for r in morning["residents"])
    work_counts = Counter(r["work_id"] for r in seed["residents"])
    assert {b["id"]: b["occupancy"] for b in morning["buildings"] if b["occupancy"]} == dict(work_counts)
    sim.advance_ticks(10 * 3600 * seed["tick_hz"])
    finished = sim.snapshot()
    completed = perf_counter()
    assert all(r["activity"] == "home" for r in finished["residents"])
    home_counts = Counter(r["home_id"] for r in seed["residents"])
    assert {b["id"]: b["occupancy"] for b in finished["buildings"] if b["occupancy"]} == dict(home_counts)
    assert sorted(r["id"] for r in finished["residents"]) == sorted(r["id"] for r in seed["residents"])
    assert sum(b["occupancy"] for b in finished["buildings"]) == population
    assert finished["event_count"] == population * 4
    assert sim.next_event_tick() is None
    # Diagnostics only: no machine-specific timing threshold or engine ranking.
    record_property("population", population)
    record_property("initialize_ms", round(1000 * (initialized - started), 3))
    record_property("advance_day_and_two_snapshots_ms", round(1000 * (completed - initialized), 3))


def test_written_scenario_round_trips_and_detects_tampering(tmp_path):
    path = tmp_path / "day.json"
    write_scenario(path, 20, 123)
    assert load_scenario(path) == make_scenario(20, 123)
    altered = json.loads(path.read_text(encoding="utf-8"))
    altered["residents"][0]["speed_mps"] = 4
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_scenario(path)
