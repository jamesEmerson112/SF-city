"""An optional native search must preserve full route identity and geometry."""

import random

import pytest

from civic_center.native_routing import NativeRoutes, find_library
from civic_center.routing import WalkingGraph
from civic_center.scenario import make_scenario

pytestmark = pytest.mark.skipif(find_library() is None, reason="Optional Rust routing library has not been built")


def test_native_paths_match_all_pilot_building_pairs_and_dense_geometry():
    scenario = make_scenario(20, 7)
    graph = WalkingGraph(scenario["nodes"], scenario["edges"], backend="python")
    entrances = [building["entrance_node_id"] for building in scenario["buildings"]]
    with NativeRoutes(graph) as native:
        for origin in entrances:
            for destination in entrances:
                assert native.route(origin, destination) == graph.route(origin, destination)


def test_equal_cost_parallel_edges_keep_python_discovery_order():
    nodes = [{"id": "a", "position": [0, 0, 0]}, {"id": "b", "position": [1, 1, 0]},
             {"id": "c", "position": [1, -1, 0]}, {"id": "d", "position": [2, 0, 0]}]
    edges = [{"id": "z-ab", "from": "a", "to": "b", "bidirectional": False},
             {"id": "a-ab", "from": "a", "to": "b", "bidirectional": False,
              "points": [[0, 0, 0], [0.5, 0.5, 0], [1, 1, 0]]},
             {"id": "ac", "from": "a", "to": "c"}, {"id": "bd", "from": "b", "to": "d"},
             {"id": "cd", "from": "c", "to": "d"}]
    graph = WalkingGraph(nodes, edges, backend="python")
    with NativeRoutes(graph) as native:
        assert native.route("a", "d") == graph.route("a", "d")
        assert native.route("a", "d").node_ids == ("a", "b", "d")


def test_seeded_directed_graphs_include_disconnected_and_same_node_routes():
    rng = random.Random(14)
    for graph_number in range(8):
        nodes = [{"id": f"node-{index:02d}", "position": [rng.random()*10, rng.random()*10, rng.random()*3]} for index in range(12)]
        edges = [{"id": f"edge-{a}-{b}", "from": nodes[a]["id"], "to": nodes[b]["id"], "bidirectional": False}
                 for a in range(12) for b in range(12) if a != b and rng.random() < 0.12]
        graph = WalkingGraph(nodes, edges, backend="python")
        with NativeRoutes(graph) as native:
            for origin in nodes:
                for destination in nodes:
                    assert native.route(origin["id"], destination["id"]) == graph.route(origin["id"], destination["id"]), graph_number


def test_closed_graph_and_unknown_endpoints_fail_cleanly():
    graph = WalkingGraph([{"id": "only", "position": [0, 0, 0]}], [], backend="python")
    native = NativeRoutes(graph)
    assert native.route("only", "only") == graph.route("only", "only")
    with pytest.raises(ValueError):
        native.route("missing", "only")
    native.close()
    native.close()
    with pytest.raises(RuntimeError, match="closed"):
        native.route("only", "only")
