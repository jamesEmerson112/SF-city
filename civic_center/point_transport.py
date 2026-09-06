"""One bounded background owner for the optional shared-coordinate wire cache.

Inputs contain detached dynamic state and immutable model geometry. The socket
loop never lends the encoder a live model, nor copies every route coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import queue
import threading
import time
from typing import Any

from civic_center.shared_geometry import GeometryEncodingCancelled, SharedGeometryEncoder


MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024
POOL_CHUNK_POINTS = 1024


def _frame(message: dict[str, Any]) -> bytes:
    value = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(value) > MAX_FRAME_BYTES:
        raise ValueError("shared route frame exceeds the 16 MiB limit")
    return value + b"\n"


@dataclass(frozen=True)
class PointRequest:
    session_id: str
    state: dict[str, Any]
    definitions: list[dict[str, Any]]
    active_ids: tuple[str, ...]
    known_ids: frozenset[str]
    point_cursor: int


@dataclass(frozen=True)
class PoolFrame:
    start: int
    count: int
    data: bytes


@dataclass(frozen=True)
class PointUpdate:
    session_id: str
    state: dict[str, Any]
    active_ids: tuple[str, ...]
    pool_frames: tuple[PoolFrame, ...]
    path_frames: dict[str, bytes]
    stats: dict[str, Any]
    elapsed_seconds: float
    error: str = ""
    cancelled: bool = False


class PointTransportService:
    """At most one request/result; cancellation leaves no owned thread behind."""

    def __init__(self) -> None:
        self._requests: queue.Queue[PointRequest | None] = queue.Queue(maxsize=1)
        self._results: queue.Queue[PointUpdate] = queue.Queue(maxsize=1)
        self._cancel = threading.Event()
        self._stopping = threading.Event()
        self._busy = False  # Owned by the socket loop, including completed work.
        self._thread = threading.Thread(target=self._run, name="civic-route-preparation")
        self._thread.start()

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, request: PointRequest) -> bool:
        if self._busy or self._stopping.is_set():
            return False
        self._cancel.clear()
        self._requests.put_nowait(request)
        self._busy = True
        return True

    def cancel(self) -> None:
        self._cancel.set()

    def poll(self) -> PointUpdate | None:
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            return None
        self._busy = False
        return result

    def close(self) -> None:
        self._stopping.set()
        self._cancel.set()
        try:
            self._requests.put_nowait(None)
        except queue.Full:
            pass
        # The codec checks cooperative cancellation inside bounded point loops.
        self._thread.join()

    def _check_cancelled(self) -> None:
        if self._cancel.is_set() or self._stopping.is_set():
            raise InterruptedError("shared route preparation was cancelled")

    def _prepare(self, encoder: SharedGeometryEncoder, request: PointRequest) -> PointUpdate:
        started = time.monotonic()
        self._check_cancelled()
        active = set(request.active_ids)
        prior = set(encoder.active_trip_ids)
        prior_cursor = encoder.point_count
        retired = sorted(prior - active)
        missing = [record for record in request.definitions if record["id"] not in prior]
        emitted = encoder.encode(missing, retire_ids=retired, should_cancel=self._cancel.is_set)
        self._check_cancelled()
        needed = [identity for identity in request.active_ids if identity not in request.known_ids]
        messages = (emitted if request.point_cursor == prior_cursor and request.known_ids == prior
                    else encoder.messages_since(request.point_cursor, needed))
        pools = []
        paths = {}
        for message in messages:
            self._check_cancelled()
            if message["type"] == "route_coordinate_pool":
                points = message["points"]
                for offset in range(0, len(points), POOL_CHUNK_POINTS):
                    self._check_cancelled()
                    chunk = points[offset:offset + POOL_CHUNK_POINTS]
                    start = message["start_index"] + offset
                    encoded = _frame({**message, "start_index":start, "points":chunk})
                    pools.append(PoolFrame(start, len(chunk), encoded))
            elif message["type"] == "trip_geometry_indices":
                for record in message["geometries"]:
                    self._check_cancelled()
                    paths[record["id"]] = _frame({**message, "geometries":[record]})
            elif message["type"] != "forget_trip_geometries":
                raise ValueError("unexpected shared route preparation message")
        self._check_cancelled()
        if sum(len(item.data) for item in pools) + sum(map(len, paths.values())) > MAX_CACHE_BYTES:
            raise ValueError("prepared shared route chunks exceed the 32 MiB cache limit")
        return PointUpdate(request.session_id, request.state, request.active_ids,
                           tuple(pools), paths, encoder.stats(), time.monotonic() - started)

    def _run(self) -> None:
        encoder = None
        while not self._stopping.is_set():
            request = self._requests.get()
            if request is None or self._stopping.is_set():
                break
            try:
                if encoder is None or encoder.session_id != request.session_id:
                    encoder = SharedGeometryEncoder(request.session_id)
                result = self._prepare(encoder, request)
            except Exception as exc:
                result = PointUpdate(request.session_id, request.state, request.active_ids,
                                     (), {}, {}, 0.0, str(exc), isinstance(exc, (InterruptedError, GeometryEncodingCancelled)))
            if self._stopping.is_set():
                break
            self._results.put(result)
