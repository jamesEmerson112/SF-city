"""Deterministic pedestrian routes in local east/north/up metres.

This router is independent of the legacy resource-carrier search: its target is
an explicit node, and an unreachable target never becomes a random fallback.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import heapq
import math
import os
from typing import Any, Iterable

Position = tuple[float, float, float]


def _identifier(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description} must be a nonempty string")
    return value


def _position(value: Any, description: str) -> Position:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{description} must contain three finite coordinates")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in value):
        raise ValueError(f"{description} must contain three finite coordinates")
    result = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{description} must contain three finite coordinates")
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class RouteSample:
    position: Position
    heading: float
    segment_index: int
    segment_progress: float


@dataclass(frozen=True)
class WalkingRoute:
    node_ids: tuple[str, ...]
    points: tuple[Position, ...]
    cumulative_lengths: tuple[float, ...]

    @property
    def length(self) -> float:
        return self.cumulative_lengths[-1]

    def sample(self, distance: float) -> RouteSample:
        """Clamp to endpoints and cross any number of short segments exactly.

        At an internal corner the heading belongs to the outgoing segment. At
        the final endpoint it belongs to the final incoming segment. A route to
        the same node is stationary and has heading zero.
        """
        if not math.isfinite(distance):
            raise ValueError("route sample distance must be finite")
        if len(self.points) == 1:
            return RouteSample(self.points[0], 0.0, 0, 1.0)
        distance = min(max(distance, 0.0), self.length)
        segment = min(
            bisect_right(self.cumulative_lengths, distance) - 1,
            len(self.points) - 2,
        )
        start, end = self.points[segment : segment + 2]
        segment_length = (
            self.cumulative_lengths[segment + 1] - self.cumulative_lengths[segment]
        )
        progress = (distance - self.cumulative_lengths[segment]) / segment_length
        if distance == self.length:
            position = self.points[-1]
            progress = 1.0
        elif progress == 0.0:
            position = start
        else:
            position = tuple(
                a + (b - a) * progress for a, b in zip(start, end)
            )
        heading = math.atan2(end[1] - start[1], end[0] - start[0])
        return RouteSample(position, heading, segment, progress)


class WalkingGraph:
    """Validated graph with cached, deterministic geometric Dijkstra routes.

    ``backend`` accepts auto/python/rust, or reads CIVIC_ROUTING_BACKEND when
    omitted (default auto). Auto uses a discovered native library and uses Python
    when none exists. Library/ABI/search failures propagate; they never cause a
    runtime switch to a different algorithm. Backend choice is execution state,
    never scenario data or part of a route's identity.
    """

    def __init__(
        self, nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]],
        *, backend: str | None = None,
    ) -> None:
        requested = os.environ.get("CIVIC_ROUTING_BACKEND", "auto") if backend is None else backend
        if requested not in ("auto", "python", "rust"):
            raise ValueError("routing backend must be auto, python or rust")
        self._backend_requested = requested
        self._selected_backend: str | None = None
        self._native_library = None
        self._native_routes = None
        self.positions: dict[str, Position] = {}
        self._adjacency: dict[str, list[tuple[str, float, str, bool]]] = {}
        self._edge_points: dict[str, tuple[Position, ...]] = {}
        self._cache: dict[tuple[str, str], WalkingRoute | None] = {}
        for node in nodes:
            node_id = _identifier(node.get("id"), "node id")
            if node_id in self.positions:
                raise ValueError(f"duplicate walking node id: {node_id}")
            self.positions[node_id] = _position(
                node.get("position"), f"node {node_id} position"
            )
            self._adjacency[node_id] = []
        if not self.positions:
            raise ValueError("walking graph must contain at least one node")
        edge_ids: set[str] = set()
        for edge in edges:
            edge_id = _identifier(edge.get("id"), "edge id")
            if edge_id in edge_ids:
                raise ValueError(f"duplicate walking edge id: {edge_id}")
            edge_ids.add(edge_id)
            source, target = edge.get("from"), edge.get("to")
            if source not in self.positions or target not in self.positions:
                raise ValueError(f"edge {edge_id} references an unknown walking node")
            bidirectional = edge.get("bidirectional", True)
            if not isinstance(bidirectional, bool):
                raise ValueError(f"edge {edge_id} bidirectional must be a boolean")
            if "points" in edge:
                raw_points = edge["points"]
                if not isinstance(raw_points, (list, tuple)) or len(raw_points) < 2:
                    raise ValueError(f"edge {edge_id} points must contain at least two positions")
                points = tuple(_position(point, f"edge {edge_id} point") for point in raw_points)
                if points[0] != self.positions[source] or points[-1] != self.positions[target]:
                    raise ValueError(f"edge {edge_id} polyline endpoints must match its graph nodes")
            else:
                points = self.positions[source], self.positions[target]
            lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
            if any(not math.isfinite(length) or length <= 0 for length in lengths):
                raise ValueError(f"edge {edge_id} must have finite positive polyline segment lengths")
            length = sum(lengths)
            if not math.isfinite(length) or length <= 0.0:
                raise ValueError(f"edge {edge_id} must have a finite positive length")
            self._edge_points[edge_id] = points
            self._adjacency[source].append((target, length, edge_id, False))
            if bidirectional:
                self._adjacency[target].append((source, length, edge_id, True))
        for neighbors in self._adjacency.values():
            neighbors.sort()

    @property
    def backend(self) -> str:
        """Resolve backend availability without constructing native adjacency."""
        if self._selected_backend is None:
            if self._backend_requested == "python":
                self._selected_backend = "python"
            else:
                from .native_routing import find_library
                self._native_library = find_library()
                if self._native_library is None and self._backend_requested == "rust":
                    raise RuntimeError("Rust routing library is unavailable; build native/civic-routing or select python")
                self._selected_backend = "rust" if self._native_library is not None else "python"
        return self._selected_backend

    def __getstate__(self):
        """Transfer validated Python graph/cache data over private worker IPC."""
        state = self.__dict__.copy()
        for field in ("_native_routes", "_native_library", "_selected_backend"):
            state.pop(field, None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._backend_requested = state.get("_backend_requested", "auto")
        self._native_routes = None
        self._native_library = None
        self._selected_backend = None

    def route(self, origin: str, destination: str) -> WalkingRoute | None:
        """Return a complete immutable shortest route, or None if disconnected."""
        if origin not in self.positions or destination not in self.positions:
            raise ValueError("route origin and destination must be walking node ids")
        key = origin, destination
        if key in self._cache:
            return self._cache[key]
        if self.backend == "rust":
            from .native_routing import NativeRoutes
            if self._native_routes is None:
                self._native_routes = NativeRoutes(self, self._native_library)
            result = self._native_routes.route(origin, destination)
            self._cache[key] = result
            return result
        queue = [(0.0, origin)]
        costs = {origin: 0.0}
        previous: dict[str, tuple[str, str, bool]] = {}
        while queue:
            cost, current = heapq.heappop(queue)
            if cost != costs[current]:
                continue
            if current == destination:
                ids = [destination]
                edge_steps = []
                while ids[-1] != origin:
                    predecessor, edge_id, reverse = previous[ids[-1]]
                    ids.append(predecessor)
                    edge_steps.append((edge_id, reverse))
                ids.reverse()
                edge_steps.reverse()
                sampled_points = [self.positions[origin]]
                for edge_id, reverse in edge_steps:
                    geometry = self._edge_points[edge_id]
                    sampled_points.extend(reversed(geometry[:-1]) if reverse else geometry[1:])
                points = tuple(sampled_points)
                cumulative = [0.0]
                for a, b in zip(points, points[1:]):
                    cumulative.append(cumulative[-1] + math.dist(a, b))
                result = WalkingRoute(tuple(ids), points, tuple(cumulative))
                self._cache[key] = result
                return result
            for neighbor, length, edge_id, reverse in self._adjacency[current]:
                candidate = cost + length
                if candidate < costs.get(neighbor, math.inf):
                    costs[neighbor] = candidate
                    previous[neighbor] = current, edge_id, reverse
                    heapq.heappush(queue, (candidate, neighbor))
        self._cache[key] = None
        return None
