"""City cohort integration on small source-shaped geographic fixtures."""

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math

import pytest

from civic_center.city_scenario import build_city_scenario, write_city_scenario
from civic_center.model import CivicSimulation
from civic_center.routing import WalkingGraph
from civic_center.scenario import load_scenario, scenario_hash


def geography_fixture(root, centers=None, graph=None):
    if graph is None:
        graph = {
            "schema_version": 1,
            "routing_assumption": "test fixture street-centerline walking proxy",
            "nodes": [
                {"id": f"street:{component}:{index}", "position": [x, y, 0]}
                for component, y in (("south", 0), ("north", 4000))
                for index, x in enumerate((-2000, 0, 2000))
            ] + [
                {"id": "island:west", "position": [5900, 6000, 0]},
                {"id": "island:east", "position": [6100, 6000, 0]},
            ],
            "edges": [
                {"id": f"edge:{component}:{index}", "from": f"street:{component}:{index}",
                 "to": f"street:{component}:{index + 1}", "bidirectional": True,
                 "source_street_id": f"official-{component}", "street_name": "Fixture street"}
                for component in ("south", "north") for index in range(2)
            ] + [{"id": "edge:island", "from": "island:west", "to": "island:east", "bidirectional": True}],
        }
    if centers is None:
        centers = [(x, y + 25) for y in (0, 4000) for x in (-1800, -1200, -200, 600, 1600)] + [(6000, 6025)]
    buildings = []
    for index, (x, y) in enumerate(centers):
        footprint = [[x - 5, y - 5, 0], [x + 5, y - 5, 0], [x + 5, y + 5, 0], [x - 5, y + 5, 0]]
        buildings.append({
            "id": f"sf-building:{index}", "source_id": str(index), "centroid": [x, y, 0],
            "bounds": {"min": [x - 5, y - 5], "max": [x + 5, y + 5]},
            "height_m": 12.5, "height_source": "fixture source field", "ground_elevation_navd88_m": 30,
            "mblr": "fixture-parcel", "name": None, "tile_id": "fixture-tile",
            "footprint": footprint, "rings": [footprint],
        })
    index = {
        "schema_version": 1,
        "buildings": [{key: value for key, value in record.items() if key not in ("footprint", "rings")} for record in buildings],
    }
    payloads = {
        "fixture/street-graph.json": graph,
        "fixture/buildings-index.json": index,
        "fixture/tile.json": {"schema_version": 1, "buildings": buildings},
    }
    files = {}
    for relative, payload in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        path.write_bytes(encoded)
        files[relative] = hashlib.sha256(encoded).hexdigest()
    manifest = {
        "schema_version": 1, "origin": {"longitude": -122.4193, "latitude": 37.7793},
        "coordinate_system": "local east, north, up; meters",
        "graph_path": "fixture/street-graph.json", "building_index_path": "fixture/buildings-index.json",
        "tiles": [{"id": "fixture-tile", "path": "fixture/tile.json"}], "files": files,
    }
    manifest["sha256"] = scenario_hash(manifest)
    path = root / "sf-geography.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, graph, buildings


def test_authentic_geometry_ids_and_source_values_survive_inferred_connectors(tmp_path):
    manifest, graph, sources = geography_fixture(tmp_path)
    scenario = build_city_scenario(manifest, 20)
    originals = {source["id"]: source for source in sources}
    source_nodes = {node["id"]: node["position"] for node in graph["nodes"]}
    actual_nodes = {node["id"]: node["position"] for node in scenario["nodes"]}
    for identity, position in source_nodes.items():
        assert actual_nodes[identity] == position
    for building in scenario["buildings"]:
        source = originals[building["id"]]
        for field in ("source_id", "centroid", "bounds", "height_m", "height_source", "tile_id", "footprint", "rings"):
            assert building[field] == source[field]
        assert building["position"] == source["centroid"]
        assert building["entrance_position"][1] == source["bounds"]["min"][1]
        assert building["connector_distance_m"] == 20
        assert "generated" in building["use_source"]
        assert "inferred" in building["entrance_source"]
    road_edges = [edge for edge in scenario["edges"] if not edge["id"].startswith("connector:")]
    original_length = sum(math.dist(source_nodes[edge["from"]], source_nodes[edge["to"]]) for edge in graph["edges"])
    split_length = sum(math.dist(actual_nodes[edge["from"]], actual_nodes[edge["to"]]) for edge in road_edges)
    assert split_length == pytest.approx(original_length)
    assert scenario["geography_manifest"] == str(manifest.resolve())
    assert scenario["sha256"] == scenario_hash(scenario)


def test_city_generator_repeats_explicitly_and_can_reproduce_finite_schedule(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    repeated = build_city_scenario(manifest, 20)
    finite = build_city_scenario(manifest, 20, repeat_days=False)
    assert repeated["generation"]["generator_version"] == 4
    assert repeated["schedule"] == {"mode": "daily-v1"}
    assert "no weekday" in repeated["schedule_note"]
    assert "schedule" not in finite
    without_repeat = deepcopy(repeated)
    del without_repeat["schedule"]
    del without_repeat["schedule_note"]
    without_repeat["sha256"] = scenario_hash(without_repeat)
    assert without_repeat == finite
    with pytest.raises(ValueError, match="repeat_days"):
        build_city_scenario(manifest, 20, repeat_days=1)


@pytest.mark.parametrize("population", [200, 1000])
def test_city_cohort_repeated_days_conserve_identity_occupancy_and_bounded_history(tmp_path, population):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    scenario = build_city_scenario(manifest, population)
    model = CivicSimulation(scenario)
    model.step_ticks((500 * 86_400 + 12 * 3600) * model.tick_hz)
    state = model.snapshot()
    assert len(state["residents"]) == population
    assert {r["id"] for r in state["residents"]} == {r["id"] for r in scenario["residents"]}
    assert all(r["activity"] == "home" for r in state["residents"])
    assert sum(b["occupancy"] for b in state["buildings"]) == population
    assert state["event_count"] == 501 * 4 * population
    assert len(state["events"]) == 256
    assert model.next_event_tick() > model.tick


def test_split_junctions_form_valid_nonzero_connected_walking_routes(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path, centers=[(-500, 25), (500, 25)])
    scenario = build_city_scenario(manifest, 1)
    graph = WalkingGraph(scenario["nodes"], scenario["edges"])
    resident = scenario["residents"][0]
    buildings = {b["id"]: b for b in scenario["buildings"]}
    route = graph.route(buildings[resident["home_id"]]["entrance_node_id"], buildings[resident["work_id"]]["entrance_node_id"])
    assert route.length == pytest.approx(1040)
    assert resident["commute_distance_m"] == route.length
    assert len([n for n in scenario["nodes"] if n["id"].startswith("sf-attach:")]) == 2


def test_buildings_projected_to_same_street_point_share_junction_without_zero_edge(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path, centers=[(-500, 25), (-500, -25), (500, 25)])
    scenario = build_city_scenario(manifest, 20)
    WalkingGraph(scenario["nodes"], scenario["edges"])
    projected = [node for node in scenario["nodes"] if node["id"].startswith("sf-attach:") and node["position"] == [-500, 0, 0]]
    assert len(projected) == 1


def test_disconnected_components_keep_home_work_together_and_skip_isolated_building(tmp_path):
    manifest, _graph, sources = geography_fixture(tmp_path)
    scenario = build_city_scenario(manifest, 200)
    by_id = {building["id"]: building for building in sources}
    used_y = set()
    for resident in scenario["residents"]:
        home_y = by_id[resident["home_id"]]["centroid"][1]
        work_y = by_id[resident["work_id"]]["centroid"][1]
        assert home_y == work_y
        assert home_y != 6025
        used_y.add(home_y)
        assert 150 <= resident["commute_distance_m"] <= 3000
    assert used_y == {25, 4025}
    assert scenario["generation"]["route_searches"] <= 16 * scenario["generation"]["connected_candidate_buildings"]


def test_seeded_prefixes_and_spatial_assignments_repeat_for_larger_cohort(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    small = build_city_scenario(manifest, 200, seed=19)
    large = build_city_scenario(manifest, 1000, seed=19)
    assert large["residents"][:200] == small["residents"]
    assert build_city_scenario(manifest, 200, seed=19) == small
    assert [r["id"] for r in small["residents"]] == [f"sf-resident-{i:06d}" for i in range(200)]


@pytest.mark.parametrize("population", [200, 1000])
def test_city_cohort_finishes_same_persistent_day_and_conserves_occupancy(tmp_path, population):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    scenario = build_city_scenario(manifest, population)
    simulation = CivicSimulation(scenario)
    simulation.advance_ticks(2 * 3600 * simulation.tick_hz)
    state = simulation.snapshot()
    assert all(person["activity"] == "at_work" for person in state["residents"])
    work_counts = Counter(person["work_id"] for person in scenario["residents"])
    assert {b["id"]: b["occupancy"] for b in state["buildings"] if b["occupancy"]} == work_counts
    simulation.advance_ticks(11 * 3600 * simulation.tick_hz)
    state = simulation.snapshot()
    assert all(person["activity"] == "home" for person in state["residents"])
    assert state["event_count"] == population * 4
    assert sum(building["occupancy"] for building in state["buildings"]) == population
    assert len({person["id"] for person in state["residents"]}) == population


def test_no_cross_component_fallback_when_no_reachable_pair_exists(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path, centers=[(-500, 25), (-500, 4025)])
    with pytest.raises(ValueError, match="No connected home/work pair"):
        build_city_scenario(manifest, 1)


def test_route_distance_limit_rejects_nearby_buildings_separated_by_long_detour(tmp_path):
    graph = {
        "schema_version": 1,
        "nodes": [{"id": str(i), "position": point} for i, point in enumerate([[-20, 0, 0], [-20, 5000, 0], [20, 5000, 0], [20, 0, 0]])],
        "edges": [{"id": str(i), "from": str(i), "to": str(i + 1), "bidirectional": True} for i in range(3)],
    }
    manifest, _graph, _sources = geography_fixture(tmp_path, centers=[(-30, 0), (30, 0)], graph=graph)
    with pytest.raises(ValueError, match="No connected home/work pair"):
        build_city_scenario(manifest, 1, minimum_walk_m=10, maximum_walk_m=1000)


def test_geography_file_integrity_is_checked_before_generation(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    graph_path = tmp_path / "fixture/street-graph.json"
    graph_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_city_scenario(manifest, 1)


def test_manifest_artifact_paths_cannot_escape_dataset_root(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["graph_path"] = "../outside.json"
    payload["sha256"] = scenario_hash(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        build_city_scenario(manifest, 1)


def test_writer_creates_separate_scenario_compatible_with_standard_loader(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    output = tmp_path / "generated/sf-city-day.json"
    assert write_city_scenario(manifest, output, population=20) == output
    scenario = load_scenario(output)
    assert scenario["population"] == 20
    assert scenario["id"] == "san-francisco-street-walking-day-v1"
    assert scenario["geography_manifest_sha256"] == json.loads(manifest.read_text(encoding="utf-8"))["sha256"]


@pytest.mark.parametrize("population", [True, 0, 5000, -1, 1.0])
def test_city_population_does_not_silently_expand_past_current_cohort_scope(tmp_path, population):
    with pytest.raises(ValueError, match="City population"):
        build_city_scenario(tmp_path / "not-needed.json", population)


def terrain_fixture(path):
    # East-west slope: z=0 at x=-7000, z=140 at x=7000 after origin subtraction.
    data = {
        "schema_version": 1, "origin": {"longitude": -122.4193, "latitude": 37.7793},
        "width": 2, "height": 2, "bounds": {"min": [-7000, -7000], "max": [7000, 7000]},
        "origin_elevation_m": 10, "elevations_m": [10, 150, 10, 150],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_optional_terrain_grounds_route_vertices_entrances_and_flat_building_bases(tmp_path):
    manifest, original_graph, _sources = geography_fixture(tmp_path / "geography", centers=[(-500, 25), (500, 25)])
    terrain_path = terrain_fixture(tmp_path / "custom-terrain.json")
    scenario = build_city_scenario(manifest, 1, terrain_path=terrain_path)
    node_positions = {node["id"]: node["position"] for node in scenario["nodes"]}
    for position in node_positions.values():
        assert position[2] == pytest.approx(70 + position[0] * .01 + .08)
    for building in scenario["buildings"]:
        assert building["position"][2] == pytest.approx(70 + building["position"][0] * .01)
        assert building["base_elevation_m"] == building["position"][2]
        assert building["entrance_position"][2] == pytest.approx(70 + building["entrance_position"][0] * .01 + .08)
        assert all(point[2] == 0 for point in building["footprint"])
        assert building["ground_elevation_navd88_m"] == 30
    assert scenario["residents"][0]["commute_distance_m"] > 1040
    assert scenario["terrain_manifest"] == str(terrain_path.resolve())
    assert scenario["terrain_manifest_sha256"] == hashlib.sha256(terrain_path.read_bytes()).hexdigest()
    assert scenario["terrain"]["missing_street_node_samples"] == 0
    simulation = CivicSimulation(scenario)
    simulation.advance_ticks(2 * 3600 * simulation.tick_hz)
    assert simulation.snapshot()["residents"][0]["activity"] == "at_work"


def test_sibling_terrain_autodetection_and_explicit_missing_sample_fallback(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path / "geography", centers=[(-500, 25), (500, 25)])
    path = terrain_fixture(tmp_path / "terrain/terrain.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["elevations_m"] = [None] * 4
    path.write_text(json.dumps(data), encoding="utf-8")
    scenario = build_city_scenario(manifest, 1)
    assert scenario["terrain_manifest"] == str(path.resolve())
    assert scenario["terrain"]["missing_street_node_samples"] > 0
    assert all(node["position"][2] == .08 for node in scenario["nodes"])
    assert all(building["base_elevation_m"] == 0 for building in scenario["buildings"])
    assert "fallback" in scenario["buildings"][0]["base_elevation_source"]


def test_terrain_with_different_coordinate_origin_is_rejected(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path / "geography")
    path = terrain_fixture(tmp_path / "terrain/terrain.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["origin"]["longitude"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="same local origin"):
        build_city_scenario(manifest, 1)


def test_city_walk_spawn_uses_source_street_node_instead_of_building_entrance(tmp_path):
    manifest, graph, _sources = geography_fixture(tmp_path)
    scenario = build_city_scenario(manifest, 20)
    source = next(node for node in graph["nodes"] if node["id"] == scenario["view"]["walk_source_node_id"])
    assert source["position"] == [0, 0, 0]
    assert scenario["view"]["walk_position"] == [0, 0, 1.8]
    assert scenario["view"]["target"] == [0, 0, 15]
    assert not scenario["view"]["walk_source_node_id"].startswith("entrance:")


def test_street_projection_inside_building_is_not_used_as_generated_access(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path, centers=[(-500, 0), (500, 25)])
    with pytest.raises(ValueError, match="No connected home/work pair"):
        build_city_scenario(manifest, 1)


def test_off_source_land_buildings_are_excluded_from_assignment_and_counted(tmp_path):
    manifest, _graph, _sources = geography_fixture(tmp_path)
    index_path = tmp_path / "fixture/buildings-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["buildings"][0]["centroid_on_source_land"] = False
    excluded_id = index["buildings"][0]["id"]
    encoded = json.dumps(index).encode("utf-8")
    index_path.write_bytes(encoded)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"]["fixture/buildings-index.json"] = hashlib.sha256(encoded).hexdigest()
    payload["sha256"] = scenario_hash(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    scenario = build_city_scenario(manifest, 20)
    assert scenario["generation"]["excluded_off_source_land"] == 1
    assert all(excluded_id not in (resident["home_id"], resident["work_id"]) for resident in scenario["residents"])
    assert "not a legal-jurisdiction claim" in scenario["generation"]["land_filter_note"]


def test_terrain_polylines_follow_hill_triangles_without_extra_graph_nodes(tmp_path):
    from civic_center.terrain import TerrainGrid

    manifest, original_graph, _sources = geography_fixture(tmp_path / "geography", centers=[(-500, 25), (500, 25)])
    flat = build_city_scenario(manifest, 1)
    path = tmp_path / "terrain.json"
    data = {
        "schema_version": 1, "origin": {"longitude": -122.4193, "latitude": 37.7793},
        "width": 3, "height": 3, "bounds": {"min": [-7000, -7000], "max": [7000, 7000]},
        "origin_elevation_m": 0, "elevations_m": [0, 0, 0, 0, 500, 0, 0, 0, 0],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    scenario = build_city_scenario(manifest, 1, terrain_path=path)
    assert len(scenario["nodes"]) == len(flat["nodes"])
    assert len(scenario["edges"]) == len(flat["edges"])
    assert scenario["terrain"]["polyline_edges"] > 0
    terrain = TerrainGrid(data)
    for edge in scenario["edges"]:
        if "points" not in edge:
            continue
        for first, second in zip(edge["points"], edge["points"][1:]):
            assert math.dist(first, second) <= 20 + 1e-7
            for fraction in (.25, .5, .75):
                east, north, height = [first[i] + (second[i] - first[i]) * fraction for i in range(3)]
                assert height == pytest.approx(terrain.triangle_height_at(east, north) + .08, abs=1e-7)
    graph = WalkingGraph(scenario["nodes"], scenario["edges"])
    buildings = {building["id"]: building for building in scenario["buildings"]}
    resident = scenario["residents"][0]
    route = graph.route(buildings[resident["home_id"]]["entrance_node_id"], buildings[resident["work_id"]]["entrance_node_id"])
    assert route.length == resident["commute_distance_m"]
    assert len(route.points) > len(route.node_ids)
