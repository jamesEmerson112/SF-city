"""Optional Rust shortest-path adapter with exact Python route reconstruction.

The native library owns only an immutable copy of CSR adjacency and edge costs.
Stable IDs, dense route geometry, cumulative distance, residents and time remain
in Python. WalkingGraph selects this adapter explicitly or through its auto policy.
"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import sys
import threading
import weakref

ROOT = Path(__file__).resolve().parents[1]


def find_library() -> Path | None:
    name = "civic_routing.dll" if sys.platform == "win32" else ("libcivic_routing.dylib" if sys.platform == "darwin" else "libcivic_routing.so")
    configured = os.environ.get("CIVIC_ROUTING_DLL")
    # An explicit override selects that file only, so an outdated fallback DLL
    # cannot silently replace a configured path that no longer exists.
    candidates = [Path(configured)] if configured else [
        ROOT / "runtime/native" / name,
        ROOT / ".cache/civic-native/release" / name,
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


class NativeRoutes:
    """Own one immutable native graph for a validated WalkingGraph instance."""

    def __init__(self, graph, library_path: Path | None = None):
        path = library_path or find_library()
        if path is None:
            raise RuntimeError("Rust routing library is unavailable; build native/civic-routing first")
        library = ctypes.CDLL(str(path))
        u32_pointer = ctypes.POINTER(ctypes.c_uint32)
        double_pointer = ctypes.POINTER(ctypes.c_double)
        library.civic_routing_abi_version.argtypes = []
        library.civic_routing_abi_version.restype = ctypes.c_uint32
        if library.civic_routing_abi_version() != 1:
            raise RuntimeError("Unsupported native routing ABI")
        library.civic_graph_new.argtypes = [ctypes.c_uint32, ctypes.c_uint32, u32_pointer, u32_pointer, double_pointer]
        library.civic_graph_new.restype = ctypes.c_void_p
        library.civic_graph_free.argtypes = [ctypes.c_void_p]
        library.civic_graph_free.restype = None
        library.civic_graph_route.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, u32_pointer, ctypes.c_uint32, u32_pointer, double_pointer]
        library.civic_graph_route.restype = ctypes.c_int32
        self.node_ids = tuple(sorted(graph.positions))
        self.node_indexes = {identity: index for index, identity in enumerate(self.node_ids)}
        self.steps = []
        self._origins = []
        offsets, targets, lengths = [0], [], []
        for origin in self.node_ids:
            for target, length, edge_id, reverse in graph._adjacency[origin]:
                targets.append(self.node_indexes[target])
                lengths.append(length)
                self.steps.append((target, edge_id, reverse))
                self._origins.append(origin)
            offsets.append(len(targets))
        if len(self.node_ids) > 2_000_000 or len(targets) > 8_000_000:
            raise ValueError("Native graph exceeds its declared ABI bounds")
        offset_buffer = (ctypes.c_uint32 * len(offsets))(*offsets)
        target_buffer = (ctypes.c_uint32 * max(1, len(targets)))(*targets)
        length_buffer = (ctypes.c_double * max(1, len(lengths)))(*lengths)
        self._handle = library.civic_graph_new(len(self.node_ids), len(targets), offset_buffer, target_buffer, length_buffer)
        if not self._handle:
            raise ValueError("Native graph rejected validated adjacency")
        self._library = library
        self._lengths = lengths
        self._graph = graph
        self._lock = threading.RLock()
        self._finalizer = weakref.finalize(self, library.civic_graph_free, self._handle)

    def close(self) -> None:
        with self._lock:
            self._finalizer()
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def route(self, origin: str, destination: str):
        from .routing import WalkingRoute

        if origin not in self.node_indexes or destination not in self.node_indexes:
            raise ValueError("route origin and destination must be walking node ids")
        with self._lock:
            if not self._handle:
                raise RuntimeError("Native routing graph is closed")
            output = (ctypes.c_uint32 * max(1, len(self.node_ids)))()
            count, cost = ctypes.c_uint32(), ctypes.c_double()
            status = self._library.civic_graph_route(
                self._handle, self.node_indexes[origin], self.node_indexes[destination],
                output, len(output), ctypes.byref(count), ctypes.byref(cost),
            )
            if status == 1:
                return None
            if status != 0 or count.value > len(output):
                raise RuntimeError(f"Native route failed with status {status}")
            if not math.isfinite(cost.value) or cost.value < 0:
                raise RuntimeError("Native route returned an invalid path cost")
            ids = [origin]
            sampled_points = [self._graph.positions[origin]]
            path_cost = 0.0
            for arc in output[:count.value]:
                if arc >= len(self.steps) or self._origins[arc] != ids[-1]:
                    raise RuntimeError("Native route returned an invalid arc sequence")
                target, edge_id, reverse = self.steps[arc]
                path_cost += self._lengths[arc]
                ids.append(target)
                geometry = self._graph._edge_points[edge_id]
                sampled_points.extend(reversed(geometry[:-1]) if reverse else geometry[1:])
            if ids[-1] != destination or path_cost != cost.value:
                raise RuntimeError("Native route returned inconsistent endpoints or cost")
            points = tuple(sampled_points)
            cumulative = [0.0]
            for start, end in zip(points, points[1:]):
                cumulative.append(cumulative[-1] + math.dist(start, end))
            return WalkingRoute(tuple(ids), points, tuple(cumulative))
