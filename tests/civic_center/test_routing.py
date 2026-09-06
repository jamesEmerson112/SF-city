"""Behavioral fixtures for explicit destination-based pedestrian routing."""

import math

import pytest

from civic_center.routing import WalkingGraph


def nodes(**positions):
    return [{"id": name, "position": position} for name, position in positions.items()]


def edges(*pairs, bidirectional=True):
    return [
        {"id": f"edge-{index}", "from": a, "to": b, "bidirectional": bidirectional}
        for index, (a, b) in enumerate(pairs)
    ]


def test_explicit_destination_shortest_route_not_first_branch():
    graph = WalkingGraph(
        nodes(a=[0, 0, 0], b=[0, 10, 0], c=[1, 0, 0], d=[2, 0, 0]),
        edges(("a", "b"), ("b", "d"), ("a", "c"), ("c", "d")),
    )
    route = graph.route("a", "d")
    assert route.node_ids == ("a", "c", "d")
    assert route.length == 2.0
    assert graph.route("a", "d") is route
    assert graph.route("d", "a").node_ids == ("d", "c", "a")


def test_direction_and_unreachable_have_no_random_fallback():
    graph = WalkingGraph(
        nodes(a=[0, 0, 0], b=[1, 0, 0], disconnected=[4, 0, 0]),
        edges(("a", "b"), bidirectional=False),
    )
    assert graph.route("a", "b") is not None
    assert graph.route("b", "a") is None
    assert graph.route("a", "disconnected") is None
    with pytest.raises(ValueError, match="node ids"):
        graph.route("a", "unknown")


def test_equal_length_routes_are_independent_of_input_order():
    positions = nodes(a=[0, 0, 0], b=[1, 1, 0], c=[1, -1, 0], d=[2, 0, 0])
    connections = edges(("a", "c"), ("c", "d"), ("a", "b"), ("b", "d"))
    left = WalkingGraph(positions, connections).route("a", "d")
    right = WalkingGraph(reversed(positions), reversed(connections)).route("a", "d")
    assert left == right
    assert left.node_ids == ("a", "b", "d")


def test_clamped_endpoints_corner_heading_and_multi_segment_sampling():
    graph = WalkingGraph(
        nodes(a=[0, 0, 0], b=[0.01, 0, 0], c=[0.01, 0.01, 0], d=[0.02, 0.01, 0]),
        edges(("a", "b"), ("b", "c"), ("c", "d")),
    )
    route = graph.route("a", "d")
    assert route.sample(-2).position == (0.0, 0.0, 0.0)
    corner = route.sample(0.01)
    assert corner.position == (0.01, 0.0, 0.0)
    assert corner.segment_index == 1
    assert corner.segment_progress == 0
    assert corner.heading == math.pi / 2
    crossed = route.sample(0.025)
    assert crossed.position == pytest.approx((0.015, 0.01, 0))
    assert crossed.segment_index == 2
    assert crossed.segment_progress == pytest.approx(0.5)
    end = route.sample(100)
    assert end.position == (0.02, 0.01, 0.0)
    assert end.segment_progress == 1
    assert end.heading == 0


def test_route_to_same_node_is_stationary():
    graph = WalkingGraph(nodes(a=[1, 2, 3]), [])
    route = graph.route("a", "a")
    assert route.length == 0
    assert route.sample(7).position == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("bad", [0, float("nan"), float("inf")])
def test_invalid_edges_rejected(bad):
    with pytest.raises(ValueError):
        WalkingGraph(nodes(a=[0, 0, 0], b=[bad, 0, 0]), edges(("a", "b")))


def test_height_counts_as_route_distance():
    graph = WalkingGraph(nodes(a=[0, 0, 0], b=[3, 0, 4]), edges(("a", "b")))
    route = graph.route("a", "b")
    assert route.length == 5
    assert route.sample(2.5).position == (1.5, 0.0, 2.0)


def test_duplicate_ids_and_unknown_edge_nodes_rejected():
    with pytest.raises(ValueError, match="duplicate walking node"):
        WalkingGraph([{"id": "a", "position": [0, 0, 0]}] * 2, [])
    with pytest.raises(ValueError, match="unknown walking node"):
        WalkingGraph(nodes(a=[0, 0, 0]), edges(("a", "missing")))


def test_edge_terrain_polyline_preserves_hill_and_reverse_sampling():
    graph = WalkingGraph(
        nodes(a=[0, 0, 0], b=[6, 0, 0]),
        [{"id": "hill", "from": "a", "to": "b", "bidirectional": True,
          "points": [[0, 0, 0], [3, 0, 4], [6, 0, 0]]}],
    )
    route = graph.route("a", "b")
    assert route.node_ids == ("a", "b")
    assert len(route.points) == 3
    assert route.length == 10
    assert route.sample(2.5).position == (1.5, 0.0, 2.0)
    assert route.sample(5).position == (3.0, 0.0, 4.0)
    assert route.sample(7.5).position == (4.5, 0.0, 2.0)
    reverse = graph.route("b", "a")
    assert reverse.points == tuple(reversed(route.points))
    assert reverse.length == 10
    assert reverse.sample(2.5).position == (4.5, 0.0, 2.0)
    assert reverse.sample(2.5).heading == math.pi


def test_shortest_path_cost_includes_grade_instead_of_endpoint_chord():
    graph = WalkingGraph(
        nodes(a=[0, 0, 0], b=[6, 0, 0], flat_detour=[3, 2, 0]),
        [{"id": "hill", "from": "a", "to": "b", "points": [[0, 0, 0], [3, 0, 4], [6, 0, 0]]},
         *edges(("a", "flat_detour"), ("flat_detour", "b"))],
    )
    route = graph.route("a", "b")
    assert route.node_ids == ("a", "flat_detour", "b")
    assert route.length == pytest.approx(2 * math.sqrt(13))


@pytest.mark.parametrize("points", [
    [[0, 0, 0]],
    [[1, 0, 0], [2, 0, 0]],
    [[0, 0, 0], [3, 0, 0]],
    [[0, 0, 0], [0, 0, 0], [2, 0, 0]],
    [[0, 0, 0], [1, 0, float("nan")], [2, 0, 0]],
])
def test_invalid_edge_polyline_is_rejected(points):
    with pytest.raises(ValueError):
        WalkingGraph(nodes(a=[0, 0, 0], b=[2, 0, 0]), [{"id": "road", "from": "a", "to": "b", "points": points}])
