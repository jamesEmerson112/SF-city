"""Exact, bounded shared route coordinates for negotiated sessions.

Negotiate ``route_geometry_encoding: city-points-v1`` independently of
the snapshot encoding and acknowledge it in the scene before using these frames.
Reliable ``route_coordinate_pool`` frames append exact triples at ``start_index``;
``trip_geometry_indices`` frames then define paths through those point indices.
The existing ``forget_trip_geometries`` message releases inactive path references.
The codec itself has no worker or viewer dependencies.

A pool belongs to one session. Coordinates never move or change identity within
that session; resetting requires a different, fresh session ID. Production uses
``commuter-v1`` identity validation: ``resident:outbound|return:cycle`` pins one
exact route fingerprint per resident/direction and remembers only the highest
cycle. Forgotten older cycles cannot be reintroduced, while exact reactivation
of the current cycle is safe. This supports unlimited repeating days with bounded
identity memory on the current immutable-assignment model. Changed assignments,
routes or point positions require a new session. The generic ``opaque-v1`` test
mode retains its finite per-ID ledger instead. All limits fail explicitly; no
referenced point or identity is silently reused. Integrations must stage reliable
bootstrap frames within their outgoing queue, separately from this cache budget.

Python expansion preserves JSON numeric types and float bits, including signed
zero. Receivers whose JSON parser normalizes numeric types may accept numerically
equal triples at distinct fresh indices; immutable index identity, bounded counts
and route fingerprints still prevent coordinates from being reinterpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import struct
from typing import Any, Callable

ROUTE_GEOMETRY_ENCODING = "city-points-v1"
PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_POINTS = 400_000  # Current complete city has fewer than 300,000 terrain vertices.
MAX_POINT_REFERENCES = 2_000_000  # Measured 5,000-resident peak has 1.33 million.
MAX_NODE_REFERENCES = 500_000
MAX_TRIP_IDENTITIES = 20_000
MAX_ROUTE_ITEMS = 50_000
MAX_ID_BYTES = 512
MAX_SESSION_BYTES = 128
MAX_SAFE_INTEGER = (1 << 53) - 1
WIRE_ENVELOPE_RESERVE = 4096
MAX_POOL_MESSAGE_POINTS = 1024


class GeometryEncodingCancelled(RuntimeError):
    """Cooperative cancellation occurred before the encoder state committed."""


def _check_cancel(should_cancel):
    if should_cancel is not None and should_cancel():
        raise GeometryEncodingCancelled("Shared geometry encoding cancelled")


@dataclass(frozen=True)
class GeometryLimits:
    """Tests or consumers may lower hard limits; they cannot raise them."""

    points: int = MAX_POINTS
    point_references: int = MAX_POINT_REFERENCES
    node_references: int = MAX_NODE_REFERENCES
    identities: int = MAX_TRIP_IDENTITIES
    cache_bytes: int = MAX_CACHE_BYTES
    frame_bytes: int = MAX_FRAME_BYTES

    def __post_init__(self):
        for field, maximum in (
            ("points", MAX_POINTS), ("point_references", MAX_POINT_REFERENCES),
            ("node_references", MAX_NODE_REFERENCES), ("identities", MAX_TRIP_IDENTITIES),
            ("cache_bytes", MAX_CACHE_BYTES), ("frame_bytes", MAX_FRAME_BYTES),
        ):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"Shared geometry {field} limit must be from 1 to {maximum}")


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError(f"Invalid shared geometry JSON: {error}") from error


def _identifier(value: Any, *, session=False) -> str:
    maximum = MAX_SESSION_BYTES if session else MAX_ID_BYTES
    if type(value) is not str or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Shared geometry IDs must be nonempty strings without control characters")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("Shared geometry IDs must be valid Unicode") from error
    if len(encoded) > maximum:
        raise ValueError(f"Shared geometry ID exceeds {maximum} bytes")
    return value


def _number(value: Any, *, nonnegative=False):
    if type(value) not in (int, float):
        raise ValueError("Shared geometry numbers must be finite JSON numbers")
    if type(value) is int and abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("Shared geometry integer exceeds the JSON-safe range")
    if type(value) is float and not math.isfinite(value):
        raise ValueError("Shared geometry numbers must be finite JSON numbers")
    if nonnegative and value < 0:
        raise ValueError("Shared geometry length must be nonnegative")
    return value


def _point(value: Any):
    if type(value) not in (list, tuple) or len(value) != 3:
        raise ValueError("Shared geometry points require three coordinates")
    return tuple(_number(number) for number in value)


def _point_key(point) -> bytes:
    # Preserve float bits (including negative zero), and distinguish an integer
    # coordinate from a float. Ordinary tuple equality would collapse both.
    return b"".join(
        b"f" + struct.pack("!d", number) if type(number) is float
        else b"i" + number.to_bytes(8, "big", signed=True)
        for number in point
    )


def _sequence(value: Any, description: str, maximum: int, *, nonempty=True):
    if type(value) not in (list, tuple) or len(value) > maximum or (nonempty and not value):
        raise ValueError(f"Shared geometry {description} must contain {'1' if nonempty else '0'} to {maximum} items")
    return value


@dataclass(frozen=True)
class _Path:
    identity: str
    indices: tuple[int, ...]
    node_ids: tuple[str, ...]
    length: int | float

    def record(self):
        return {"id": self.identity, "point_indices": list(self.indices),
                "node_ids": list(self.node_ids), "length_m": self.length}


@dataclass(frozen=True)
class _Identity:
    digest: bytes
    cycle: int | None


class _Store:
    def __init__(self, session_id: str, *, identity_mode="commuter-v1", limits: GeometryLimits | None = None):
        self.limits = limits or GeometryLimits()
        if type(self.limits) is not GeometryLimits:
            raise TypeError("Shared geometry limits require GeometryLimits")
        if identity_mode not in ("commuter-v1", "opaque-v1"):
            raise ValueError("Unsupported shared geometry identity mode")
        self.identity_mode = identity_mode
        self.session_id = _identifier(session_id, session=True)
        self._clear()

    def _clear(self):
        self._points = []
        self._point_indices = {}
        self._paths = {}
        self._identities = {}
        self._point_bytes = 0
        self._pool_wire_bytes = 0
        self._path_bytes = 0
        self._path_frame_overhead = len(_json({**self._base("trip_geometry_indices"), "geometries": []}))
        self._point_references = 0
        self._node_references = 0

    def reset(self, session_id: str):
        """Reset after an explicitly new scene/session; old frames are rejected."""
        session_id = _identifier(session_id, session=True)
        if session_id == self.session_id:
            raise ValueError("Shared geometry reset requires a new session ID")
        self.session_id = session_id
        self._clear()

    def stats(self):
        return {
            "points": len(self._points), "active_trips": len(self._paths),
            "identity_mode": self.identity_mode, "identity_records": len(self._identities),
            # Kept for readers of the original prototype statistics. In commuter
            # mode these are resident/direction records, not lifetime trip IDs.
            "seen_trip_identities": len(self._identities),
            "point_references": self._point_references,
            "node_references": self._node_references,
            "pool_json_bytes": self._point_bytes,
            "active_path_json_bytes": self._path_bytes,
            "pool_wire_bytes": self._pool_wire_bytes,
            "active_path_wire_bytes": self._path_bytes + len(self._paths) * self._path_frame_overhead,
            "accounted_wire_bytes": self._pool_wire_bytes + self._path_bytes + len(self._paths) * self._path_frame_overhead + WIRE_ENVELOPE_RESERVE,
        }

    @property
    def point_count(self):
        return len(self._points)

    @property
    def active_trip_ids(self):
        """Detached ID set; query on the same owner thread that mutates the codec."""
        return frozenset(self._paths)

    def _identity_key(self, identity):
        if self.identity_mode == "opaque-v1":
            return identity, None
        parts = identity.rsplit(":", 2)
        if len(parts) != 3 or parts[1] not in ("outbound", "return"):
            raise ValueError("Shared geometry commuter ID requires resident:outbound|return:cycle")
        resident, direction, cycle_text = parts
        _identifier(resident)
        if not cycle_text or any(c < "0" or c > "9" for c in cycle_text) or len(cycle_text) > 16:
            raise ValueError("Shared geometry commuter cycle must be a canonical JSON-safe integer")
        cycle = int(cycle_text)
        if cycle > MAX_SAFE_INTEGER or str(cycle) != cycle_text:
            raise ValueError("Shared geometry commuter cycle must be a canonical JSON-safe integer")
        return (resident, direction), cycle

    def _identity_total(self, updates):
        return len(self._identities) + sum(key not in self._identities for key in updates)

    def _budget(self, points, point_bytes, path_bytes, point_refs, node_refs, identities,
                *, pool_wire_bytes=None, active_paths=None):
        if points > self.limits.points:
            raise ValueError("Shared geometry point limit reached; start a new session")
        if point_refs > self.limits.point_references:
            raise ValueError("Shared geometry point-reference limit exceeded")
        if node_refs > self.limits.node_references:
            raise ValueError("Shared geometry node-reference limit exceeded")
        if identities > self.limits.identities:
            raise ValueError("Shared geometry identity lifetime limit reached; start a new session")
        pool_wire_bytes = self._pool_wire_bytes if pool_wire_bytes is None else pool_wire_bytes
        active_paths = len(self._paths) if active_paths is None else active_paths
        if pool_wire_bytes + path_bytes + active_paths * self._path_frame_overhead + WIRE_ENVELOPE_RESERVE > self.limits.cache_bytes:
            raise ValueError("Shared geometry wire cache budget exceeded")

    def _stage_paths(self, paths, retire_ids=(), should_cancel=None):
        staged, digests = {}, {}
        path_bytes, point_refs, node_refs = self._path_bytes, self._point_references, self._node_references
        for identity in retire_ids:
            _check_cancel(should_cancel)
            retired = self._paths[identity]
            path_bytes -= len(_json(retired.record())) + 1
            point_refs -= len(retired.indices)
            node_refs -= len(retired.node_ids)
        for path in paths:
            _check_cancel(should_cancel)
            if path.identity in staged:
                raise ValueError("Shared geometry message contains duplicate trip IDs")
            record = path.record()
            encoded = _json(record)
            key, cycle = self._identity_key(path.identity)
            if self.identity_mode == "commuter-v1":
                del record["id"]
            digest = hashlib.sha256(_json(record) if cycle is not None else encoded).digest()
            prior = digests.get(key, self._identities.get(key))
            if prior is not None and prior.digest != digest:
                raise ValueError("Shared geometry trip identity cannot change within a session")
            if prior is not None and cycle is not None and cycle < prior.cycle:
                raise ValueError("Shared geometry stale commuter cycle cannot be reintroduced")
            staged[path.identity] = path
            if path.identity not in self._paths:
                path_bytes += len(encoded) + 1
                point_refs += len(path.indices)
                node_refs += len(path.node_ids)
            if prior is None or prior.cycle != cycle:
                digests[key] = _Identity(digest, cycle)
        return staged, digests, path_bytes, point_refs, node_refs

    def _commit_paths(self, stage, retire_ids=()):
        paths, digests, self._path_bytes, self._point_references, self._node_references = stage
        for identity in retire_ids:
            del self._paths[identity]
        self._paths.update(paths)
        self._identities.update(digests)

    def _retire_ids(self, ids, *, nonempty=True):
        ids = _sequence(ids, "forgotten IDs", self.limits.identities, nonempty=nonempty)
        checked = [_identifier(identity) for identity in ids]
        if len(set(checked)) != len(checked) or any(identity not in self._paths for identity in checked):
            raise ValueError("Shared geometry forget requires unique active trip IDs")
        return checked

    def _forget(self, ids):
        checked = self._retire_ids(ids)
        for identity in checked:
            path = self._paths.pop(identity)
            self._path_bytes -= len(_json(path.record())) + 1
            self._point_references -= len(path.indices)
            self._node_references -= len(path.node_ids)

    def expand(self, ids: list[str] | tuple[str, ...] | None = None):
        """Return detached exact geometries in unique requested-ID order."""
        identities = list(self._paths) if ids is None else _sequence(ids, "expansion IDs", self.limits.identities, nonempty=False)
        ordered, seen = [], set()
        for identity in identities:
            identity = _identifier(identity)
            if identity not in self._paths:
                raise ValueError(f"Unknown active shared geometry trip ID: {identity}")
            if identity not in seen:
                ordered.append(identity)
                seen.add(identity)
        result = []
        for identity in ordered:
            path = self._paths[identity]
            result.append({"id": identity, "points": [list(self._points[i]) for i in path.indices],
                           "node_ids": list(path.node_ids), "length_m": path.length})
        return result

    def _base(self, kind):
        return {"type": kind, "protocol_version": PROTOCOL_VERSION, "session_id": self.session_id}

    def _frames(self, kind, field, records, *, start_index=None, record_limit=None, should_cancel=None):
        """Split arrays into finite messages; individual paths cannot be split."""
        messages, batch = [], []
        start = start_index

        def message(items):
            result = self._base(kind)
            if start is not None:
                result["start_index"] = start
            result[field] = items
            return result

        size = len(_json(message([])))
        for index, record in enumerate(records):
            if index % 256 == 0:
                _check_cancel(should_cancel)
            record_size = len(_json(record))
            if size + record_size + bool(batch) > self.limits.frame_bytes or (record_limit is not None and len(batch) >= record_limit):
                if not batch:
                    raise ValueError("One shared geometry record exceeds the frame limit")
                messages.append(message(batch))
                if start is not None:
                    start += len(batch)
                batch = []
                size = len(_json(message([])))
            if size + record_size > self.limits.frame_bytes:
                raise ValueError("One shared geometry record exceeds the frame limit")
            size += record_size + bool(batch)
            batch.append(record)
        if batch:
            messages.append(message(batch))
        return messages


class SharedGeometryEncoder(_Store):
    def encode(self, definitions: list[dict[str, Any]], *, retire_ids: list[str] | tuple[str, ...] = (),
               should_cancel: Callable[[], bool] | None = None):
        """Atomically prepare forgets, pool appends and indexed definitions.

        A single background owner can filter immutable model captures against
        active_trip_ids and submit only new routes plus expired IDs. Unchanged
        routes then require no coordinate validation or serialization per tick.
        Retirements and additions share one budget check and commit; any failure
        leaves the pool, identities, active paths and counters unchanged.
        """
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("Shared geometry cancellation check must be callable")
        _check_cancel(should_cancel)
        definitions = _sequence(definitions, "definitions", self.limits.identities, nonempty=False)
        retire_ids = self._retire_ids(retire_ids, nonempty=False)
        if not definitions and not retire_ids:
            return []
        retired_set = set(retire_ids)
        points, indices, paths = [], {}, []
        point_bytes = self._point_bytes
        requested_ids = set()
        prospective_refs, prospective_nodes = self._point_references, self._node_references
        for identity in retire_ids:
            prospective_refs -= len(self._paths[identity].indices)
            prospective_nodes -= len(self._paths[identity].node_ids)
        message_refs = message_nodes = 0
        for definition in definitions:
            _check_cancel(should_cancel)
            if type(definition) is not dict or set(definition) != {"id", "points", "node_ids", "length_m"}:
                raise ValueError("Shared geometry definition has missing or unsupported fields")
            identity = _identifier(definition["id"])
            self._identity_key(identity)
            if identity in retired_set:
                raise ValueError("Shared geometry cannot retire and redefine the same trip in one update")
            if identity in requested_ids:
                raise ValueError("Shared geometry message contains duplicate trip IDs")
            requested_ids.add(identity)
            values = _sequence(definition["points"], "route points", MAX_ROUTE_ITEMS)
            node_values = _sequence(definition["node_ids"], "route node IDs", MAX_ROUTE_ITEMS)
            message_refs += len(values)
            message_nodes += len(node_values)
            if message_refs > self.limits.point_references or message_nodes > self.limits.node_references:
                raise ValueError("Shared geometry message exceeds decoded point-reference or node-reference limits")
            if identity not in self._paths:
                prospective_refs += len(values)
                prospective_nodes += len(node_values)
                if prospective_refs > self.limits.point_references:
                    raise ValueError("Shared geometry point-reference limit exceeded")
                if prospective_nodes > self.limits.node_references:
                    raise ValueError("Shared geometry node-reference limit exceeded")
            references = []
            for position_index, value in enumerate(values):
                if position_index % 256 == 0:
                    _check_cancel(should_cancel)
                point = _point(value)
                key = _point_key(point)
                index = self._point_indices.get(key)
                if index is None:
                    index = indices.get(key)
                if index is None:
                    index = len(self._points) + len(points)
                    if index >= self.limits.points:
                        raise ValueError("Shared geometry point limit reached; start a new session")
                    indices[key] = index
                    points.append(point)
                    point_bytes += len(_json(point)) + 1
                references.append(index)
            nodes = tuple(_identifier(node) for node in node_values)
            paths.append(_Path(identity, tuple(references), nodes, _number(definition["length_m"], nonnegative=True)))
        stage = self._stage_paths(paths, retire_ids, should_cancel)
        messages = self._frames("forget_trip_geometries", "ids", retire_ids, should_cancel=should_cancel)
        pool_messages = self._frames("route_coordinate_pool", "points", (list(p) for p in points),
                                     start_index=len(self._points), record_limit=MAX_POOL_MESSAGE_POINTS,
                                     should_cancel=should_cancel)
        pool_wire_bytes = self._pool_wire_bytes + sum(len(_json(message)) + 1 for message in pool_messages)
        messages += pool_messages
        messages += self._frames("trip_geometry_indices", "geometries", (p.record() for p in paths if p.identity not in self._paths),
                                 record_limit=1, should_cancel=should_cancel)
        active_paths = len(self._paths) - len(retire_ids) + sum(identity not in self._paths for identity in stage[0])
        self._budget(len(self._points) + len(points), point_bytes, *stage[2:], self._identity_total(stage[1]),
                     pool_wire_bytes=pool_wire_bytes, active_paths=active_paths)
        _check_cancel(should_cancel)
        self._points.extend(points)
        self._point_indices.update(indices)
        self._point_bytes = point_bytes
        self._pool_wire_bytes = pool_wire_bytes
        self._commit_paths(stage, retire_ids)
        return messages

    def messages_since(self, point_cursor: int, trip_ids: list[str] | tuple[str, ...]):
        """Non-mutating reliable delivery for an independent client cursor.

        Call on the codec owner thread. Returned lists are detached and can be
        serialized/queued after later updates. Existing full coordinates are not
        copied or serialized when the client cursor already reaches this pool.
        """
        if type(point_cursor) is not int or not 0 <= point_cursor <= len(self._points):
            raise ValueError("Shared geometry client point cursor is out of range")
        ids = _sequence(trip_ids, "delivery IDs", self.limits.identities, nonempty=False)
        checked = []
        seen = set()
        for identity in ids:
            identity = _identifier(identity)
            if identity not in self._paths:
                raise ValueError(f"Unknown active shared geometry trip ID: {identity}")
            if identity not in seen:
                checked.append(identity)
                seen.add(identity)
        if point_cursor == len(self._points) and not checked:
            return []
        messages = self._frames("route_coordinate_pool", "points", (list(p) for p in self._points[point_cursor:]),
                                start_index=point_cursor, record_limit=MAX_POOL_MESSAGE_POINTS)
        messages += self._frames("trip_geometry_indices", "geometries", (self._paths[identity].record() for identity in checked), record_limit=1)
        return messages

    def forget(self, ids: list[str]):
        message = {**self._base("forget_trip_geometries"), "ids": list(ids)}
        if len(_json(message)) > self.limits.frame_bytes:
            raise ValueError("Shared geometry forget frame exceeds the frame limit")
        self._forget(ids)
        return message


class SharedGeometryDecoder(_Store):
    def apply_json(self, encoded: bytes):
        """Bound serialized input before parsing; duplicate JSON keys are invalid."""
        if type(encoded) is not bytes or len(encoded) > self.limits.frame_bytes:
            raise ValueError("Shared geometry JSON frame exceeds the limit or is not bytes")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Shared geometry JSON contains duplicate keys")
                result[key] = value
            return result

        try:
            message = json.loads(encoded.decode("utf-8"), object_pairs_hook=unique)
        except (UnicodeError, ValueError, RecursionError) as error:
            raise ValueError(f"Invalid shared geometry JSON: {error}") from error
        self.apply(message)

    def apply(self, message: dict[str, Any]):
        """Validate and atomically apply one already bounded, parsed JSON frame."""
        if type(message) is not dict:
            raise ValueError("Shared geometry frame must be an object")
        if type(message.get("protocol_version")) is not int or message["protocol_version"] != PROTOCOL_VERSION:
            raise ValueError("Unsupported shared geometry protocol version")
        if message.get("session_id") != self.session_id:
            raise ValueError("Shared geometry frame belongs to a different session")
        if len(_json(message)) > self.limits.frame_bytes:
            raise ValueError("Shared geometry frame exceeds the frame limit")
        kind = message.get("type")
        base = {"type", "protocol_version", "session_id"}
        if kind == "forget_trip_geometries":
            if set(message) != base | {"ids"}:
                raise ValueError("Shared geometry forget frame has unsupported fields")
            self._forget(message["ids"])
        elif kind == "route_coordinate_pool":
            if set(message) != base | {"start_index", "points"}:
                raise ValueError("Shared geometry pool frame has unsupported fields")
            start = message["start_index"]
            if type(start) is not int or start != len(self._points):
                raise ValueError("Shared geometry point appends require the exact next index")
            points, indices, point_bytes = [], {}, self._point_bytes
            values = _sequence(message["points"], "pool points", min(self.limits.points, MAX_POOL_MESSAGE_POINTS))
            if len(self._points) + len(values) > self.limits.points:
                raise ValueError("Shared geometry point limit reached; start a new session")
            for value in values:
                point = _point(value)
                key = _point_key(point)
                if key in self._point_indices or key in indices:
                    raise ValueError("Shared geometry pool contains a duplicate coordinate identity")
                indices[key] = len(self._points) + len(points)
                points.append(point)
                point_bytes += len(_json(point)) + 1
            self._budget(len(self._points) + len(points), point_bytes, self._path_bytes,
                         self._point_references, self._node_references, len(self._identities),
                         pool_wire_bytes=self._pool_wire_bytes + len(_json(message)) + 1)
            self._points.extend(points)
            self._point_indices.update(indices)
            self._point_bytes = point_bytes
            self._pool_wire_bytes += len(_json(message)) + 1
        elif kind == "trip_geometry_indices":
            if set(message) != base | {"geometries"}:
                raise ValueError("Shared geometry path frame has unsupported fields")
            paths = []
            message_refs = message_nodes = 0
            for record in _sequence(message["geometries"], "indexed paths", self.limits.identities):
                if type(record) is not dict or set(record) != {"id", "point_indices", "node_ids", "length_m"}:
                    raise ValueError("Shared geometry indexed path has unsupported fields")
                indices = _sequence(record["point_indices"], "point references", MAX_ROUTE_ITEMS)
                nodes = _sequence(record["node_ids"], "route node IDs", MAX_ROUTE_ITEMS)
                message_refs += len(indices)
                message_nodes += len(nodes)
                if message_refs > self.limits.point_references or message_nodes > self.limits.node_references:
                    raise ValueError("Shared geometry message exceeds decoded point-reference or node-reference limits")
                if any(type(i) is not int or not 0 <= i < len(self._points) for i in indices):
                    raise ValueError("Shared geometry point reference is invalid or out of range")
                paths.append(_Path(_identifier(record["id"]), tuple(indices),
                                   tuple(_identifier(n) for n in nodes),
                                   _number(record["length_m"], nonnegative=True)))
            stage = self._stage_paths(paths)
            self._budget(len(self._points), self._point_bytes, *stage[2:], self._identity_total(stage[1]),
                         active_paths=len(self._paths) + sum(identity not in self._paths for identity in stage[0]))
            self._commit_paths(stage)
        else:
            raise ValueError("Unsupported shared geometry frame type")
