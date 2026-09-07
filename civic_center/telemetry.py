"""Authenticated, bounded, read-only live diagnostics over loopback TCP.

Producers replace immutable latest values or append short log records. Only the
server thread serializes and sends; slow or absent viewers never block producers.
"""

from __future__ import annotations

import hmac
import json
import selectors
import socket
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_LOGS = 128
MAX_FRAME_BYTES = 128 * 1024
MAX_PENDING_BYTES = 512 * 1024
MAX_CLIENTS = 4
AUTH_BYTES = 4096


class TelemetryHub:
    def __init__(self, run_id: str, token: str, *, started: float | None = None):
        self.run_id = run_id
        self.token = token
        self.started = time.monotonic() if started is None else started
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._listener = None
        self._sequence = 0
        self._latest: dict[str, dict] = {}
        self._logs: deque[dict] = deque(maxlen=MAX_LOGS)
        self._dropped = 0
        self.port = 0

    def publish(self, kind: str, payload: dict, source: str = "launcher") -> None:
        """Accept an already sanitized immutable payload; never perform I/O here."""
        if self._stop.is_set() or kind not in {
            "inventory",
            "hardware",
            "status",
            "phase",
            "log",
        }:
            return
        with self._lock:
            if self._stop.is_set():
                return
            self._sequence += 1
            record = {
                "schema_version": 1,
                "type": "telemetry",
                "run_id": self.run_id,
                "sequence": self._sequence,
                "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "kind": kind,
                "source": source,
                "payload": payload,
            }
            if kind == "log":
                if len(self._logs) == MAX_LOGS:
                    self._dropped += 1
                self._logs.append(record)
            else:
                self._latest[kind] = record

    def start(self) -> None:
        if self._thread is not None or self._stop.is_set():
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(MAX_CLIENTS)
            listener.setblocking(False)
        except OSError:
            listener.close()
            raise
        self._listener = listener
        self.port = listener.getsockname()[1]
        self._thread = threading.Thread(
            target=self._serve, name="civic-live-telemetry", daemon=True
        )
        try:
            self._thread.start()
        except RuntimeError:
            listener.close()
            self._thread = None
            self._listener = None
            raise

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(max(0.0, timeout))
        elif self._listener is not None:
            self._listener.close()

    def _records(self, cursor: int | None) -> tuple[int, list[dict]]:
        with self._lock:
            latest = dict(self._latest)
            logs = list(self._logs)
            sequence, dropped = self._sequence, self._dropped
        if cursor is None:
            record = {
                "schema_version": 1,
                "type": "telemetry",
                "run_id": self.run_id,
                "sequence": sequence,
                "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "kind": "snapshot",
                "source": "launcher",
                "dropped_events": dropped,
                "payload": {
                    key: latest.get(kind, {}).get("payload", {})
                    for key, kind in (
                        ("inventory", "inventory"),
                        ("hardware", "hardware"),
                        ("status", "status"),
                        ("phase", "phase"),
                    )
                },
            }
            record["payload"]["logs"] = [row["payload"] for row in logs]
            record["payload"]["clock"] = {
                "launcher_monotonic_seconds": time.monotonic(),
                "unix_seconds": time.time(),
                "launcher_elapsed_seconds": time.monotonic() - self.started,
            }
            return sequence, [record]
        records = sorted(
            [row for row in [*latest.values(), *logs] if row["sequence"] > cursor],
            key=lambda row: row["sequence"],
        )
        return sequence, [{**row, "dropped_events": dropped} for row in records]

    @staticmethod
    def _encode(record: dict) -> bytes:
        def encode(value):
            return (
                json.dumps(
                    value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                + "\n"
            ).encode("utf-8")

        data = encode(record)
        if len(data) <= MAX_FRAME_BYTES:
            return data
        # A connection snapshot can contain many individually bounded log rows.
        if record["kind"] == "snapshot":
            record = {**record, "payload": dict(record["payload"])}
            logs = list(record["payload"].get("logs", []))
            while logs and len(data) > MAX_FRAME_BYTES:
                logs = logs[len(logs) // 2 + 1 :]
                record["payload"]["logs"] = logs
                record["payload"]["snapshot_truncated"] = True
                data = encode(record)
        if len(data) > MAX_FRAME_BYTES:
            record = {
                **record,
                "kind": "status",
                "payload": {
                    "telemetry_warning": "Oversized diagnostic omitted",
                    "omitted_kind": record["kind"],
                },
            }
            data = encode(record)
        return data

    def _serve(self) -> None:
        clients: dict[socket.socket, dict[str, Any]] = {}
        selector = selectors.DefaultSelector()
        listener = self._listener
        selector.register(listener, selectors.EVENT_READ)

        def drop(connection):
            clients.pop(connection, None)
            try:
                selector.unregister(connection)
            except (KeyError, ValueError):
                pass
            connection.close()

        try:
            while not self._stop.is_set():
                for key, mask in selector.select(0.05):
                    connection = key.fileobj
                    if connection is listener:
                        try:
                            connection, _ = listener.accept()
                            connection.setblocking(False)
                            if len(clients) >= MAX_CLIENTS:
                                connection.close()
                                continue
                            clients[connection] = {
                                "authenticated": False,
                                "input": bytearray(),
                                "output": bytearray(),
                                "cursor": None,
                                "deadline": time.monotonic() + 3.0,
                                "last_sent": time.monotonic(),
                            }
                            selector.register(connection, selectors.EVENT_READ)
                        except OSError:
                            continue
                        continue
                    client = clients.get(connection)
                    if client is None:
                        continue
                    try:
                        if mask & selectors.EVENT_READ:
                            chunk = connection.recv(AUTH_BYTES + 1)
                            if not chunk or client["authenticated"]:
                                drop(connection)
                                continue
                            client["input"].extend(chunk)
                            if len(client["input"]) > AUTH_BYTES:
                                drop(connection)
                                continue
                            if b"\n" in client["input"]:
                                raw, _, trailing = client["input"].partition(b"\n")
                                hello = json.loads(raw)
                                valid = (
                                    isinstance(hello, dict)
                                    and hello.get("type") == "hello"
                                    and hello.get("schema_version") == 1
                                    and isinstance(hello.get("token"), str)
                                    and hmac.compare_digest(hello["token"], self.token)
                                    and not trailing.strip()
                                )
                                if not valid:
                                    drop(connection)
                                    continue
                                client["authenticated"] = True
                                client["input"].clear()
                        if mask & selectors.EVENT_WRITE and client["output"]:
                            sent = connection.send(client["output"][:65536])
                            del client["output"][:sent]
                    except BlockingIOError:
                        continue
                    except (OSError, ValueError, TypeError, RecursionError):
                        drop(connection)
                for connection, client in list(clients.items()):
                    if not client["authenticated"]:
                        if time.monotonic() > client["deadline"]:
                            drop(connection)
                        continue
                    # Wait for the previous batch to drain, then coalesce latest
                    # values and resume log history at its sequence cursor.
                    if not client["output"]:
                        cursor, records = self._records(client["cursor"])
                        client["cursor"] = cursor
                        if (
                            not records
                            and time.monotonic() - client["last_sent"] >= 1.0
                        ):
                            records = [
                                {
                                    "schema_version": 1,
                                    "type": "telemetry",
                                    "run_id": self.run_id,
                                    "sequence": cursor,
                                    "kind": "heartbeat",
                                    "source": "launcher",
                                    "at": datetime.now(timezone.utc).isoformat(
                                        timespec="milliseconds"
                                    ),
                                    "elapsed_seconds": round(
                                        time.monotonic() - self.started, 3
                                    ),
                                    "payload": {},
                                }
                            ]
                        if records:
                            client["last_sent"] = time.monotonic()
                        for record in records:
                            client["output"].extend(self._encode(record))
                            if len(client["output"]) > MAX_PENDING_BYTES:
                                drop(connection)
                                break
                    if connection in clients:
                        selector.modify(
                            connection,
                            selectors.EVENT_READ
                            | (selectors.EVENT_WRITE if client["output"] else 0),
                        )
        except (OSError, ValueError):
            # Diagnostics transport failure must never fail the application.
            pass
        finally:
            for connection in list(clients):
                drop(connection)
            selector.close()
            listener.close()
