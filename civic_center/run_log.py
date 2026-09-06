"""Bounded, token-free JSON diagnostics for one application launch."""

from __future__ import annotations

import json
import math
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from .geography import atomic_write

MAX_EVENTS = 128
MAX_ERRORS = 32
MAX_CONSOLE_LINES = 80
MAX_TEXT = 2048
MAX_ITEMS = 64
MAX_LINE = 256 * 1024
MAX_HARDWARE_SAMPLES = 360
MAX_HARDWARE_SUMMARIES = 512
HARDWARE_PERSIST_SECONDS = 5.0
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PRIVATE_KEYS = {
    "arguments",
    "argv",
    "auth",
    "authorization",
    "command",
    "command_line",
    "env",
    "environ",
    "environment",
    "password",
    "raw_arguments",
    "raw_args",
    "secret",
    "secrets",
    "token",
}
_SUMMARY_KEYS = {
    "ready",
    "session_id",
    "sequence",
    "tick",
    "simulation_time",
    "paused",
    "speed",
    "resident_count",
    "outdoor_count",
    "visible_count",
    "animated_count",
    "asset_loaded",
    "asset_mesh_count",
    "building_count",
    "crowd_batches",
    "crowd_backend",
    "crowd_backend_error",
    "rendering_3d",
    "mode",
    "error",
}
_PROFILE_KEYS = {
    "samples",
    "loading",
    "startup",
    "streaming",
    "scenery_cache",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "max_ms",
    "duration_seconds",
    "cpu_phases",
    "decoder",
    "mode",
    "rendering_3d",
    "draw_calls",
    "primitives",
    "crowd_backend",
    "resident_count",
    "outdoor_count",
    "paused",
    "speed",
    "measurement",
}
_RESERVED = {
    "schema_version",
    "run_id",
    "started_at",
    "updated_at",
    "ended_at",
    "duration_seconds",
    "events",
    "diagnostics",
    "metrics",
    "hardware",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RunLog:
    """Write one recoverable JSON document while a run is starting and running.

    Logging is best effort: an unwritable directory disables disk persistence,
    while diagnostics and failure detection remain available in memory.
    """

    def __init__(
        self, directory: Path, settings: dict, secrets: tuple[str, ...] = ()
    ) -> None:
        self._lock = threading.RLock()
        self._secrets = tuple(sorted(filter(None, secrets), key=len, reverse=True))
        self._started = time.monotonic()
        self._last_persisted = 0.0
        self._threads: list[threading.Thread] = []
        self._has_errors = False
        self._startup_complete = False
        self._finished = False
        self.disabled = False
        run_id = uuid.uuid4().hex
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = Path(directory) / f"run-{timestamp}-{run_id[:12]}.json"
        self._data: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": _utc_now(),
            "updated_at": _utc_now(),
            "ended_at": None,
            "duration_seconds": 0.0,
            "status": "starting",
            "settings": self._clean(settings),
            "events": [],
            "diagnostics": {
                "errors": [],
                "console_tail": [],
                "event_count": 0,
                "error_count": 0,
                "console_line_count": 0,
                "malformed_marker_count": 0,
                "truncated_line_count": 0,
            },
            "metrics": {},
        }
        with self._lock:
            self._persist()

    @property
    def has_errors(self) -> bool:
        with self._lock:
            return self._has_errors

    @property
    def startup_complete(self) -> bool:
        with self._lock:
            return self._startup_complete

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        return text

    def _clean(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[depth limit]"
        if isinstance(value, dict):
            result = {}
            for key, item in list(value.items())[:MAX_ITEMS]:
                normalized = str(key).lower().replace("-", "_").replace(" ", "_")
                if normalized in _PRIVATE_KEYS or normalized.endswith("_token"):
                    continue
                result[self._redact(str(key))[:MAX_TEXT]] = self._clean(item, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [self._clean(item, depth + 1) for item in value[:MAX_ITEMS]]
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        return self._redact(str(value))[:MAX_TEXT]

    def _persist(self) -> None:
        if self._finished:
            return
        self._data["updated_at"] = _utc_now()
        if self._data["ended_at"] is None:
            self._data["duration_seconds"] = round(time.monotonic() - self._started, 3)
        if self.disabled:
            return
        try:
            payload = json.dumps(
                self._data, ensure_ascii=False, allow_nan=False, indent=2
            ).encode("utf-8")
            # Windows readers and virus scanners can briefly prevent replacement.
            for attempt in range(6):
                try:
                    atomic_write(self.path, payload + b"\n")
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * 2**attempt)
            self._last_persisted = time.monotonic()
        except (OSError, ValueError, TypeError) as error:
            self.disabled = True
            try:
                print(
                    f"San Francisco: run logging unavailable: {self._redact(str(error))}",
                    file=sys.stderr,
                )
            except (OSError, ValueError, AttributeError):
                pass

    def _event(self, name: str, fields: dict) -> None:
        events = self._data["events"]
        events.append(
            {"at": _utc_now(), "name": self._clean(name), **self._clean(fields)}
        )
        del events[:-MAX_EVENTS]
        self._data["diagnostics"]["event_count"] += 1

    def event(self, name: str, **fields: Any) -> None:
        with self._lock:
            if self._finished:
                return
            self._event(name, fields)
            self._persist()

    def update(self, **fields: Any) -> None:
        with self._lock:
            if self._finished:
                return
            self._data.update(
                self._clean(
                    {
                        key: value
                        for key, value in fields.items()
                        if key not in _RESERVED
                    }
                )
            )
            self._persist()

    def configure_hardware(
        self,
        enabled: bool,
        interval_seconds: float = 1.0,
        history_limit: int = MAX_HARDWARE_SAMPLES,
    ) -> None:
        """Configure an additive, bounded hardware report within this run."""
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Hardware interval must be finite and positive")
        if not 1 <= history_limit <= MAX_HARDWARE_SAMPLES:
            raise ValueError("Hardware history must contain 1 to 360 samples")
        with self._lock:
            if self._finished:
                return
            self._data["hardware"] = {
                "schema_version": 1,
                "enabled": enabled,
                "status": "starting" if enabled else "disabled",
                "interval_seconds": interval_seconds,
                "history_limit": history_limit,
                "inventory": {},
                "samples": [],
                "samples_recorded": 0,
                "samples_dropped": 0,
                "summary": {},
                "errors": [],
                "error_count": 0,
                "summary_limit": MAX_HARDWARE_SUMMARIES,
                "summary_truncated": False,
                "measurement": (
                    "Timestamped hardware observations; CPU and I/O rates cover the "
                    "preceding sample interval. Means are arithmetic sample means. "
                    "GPU usage is adapter-wide. Viewer context may be older than a sample."
                ),
            }
            self._persist()

    def hardware_inventory(self, inventory: dict) -> None:
        with self._lock:
            hardware = self._data.get("hardware")
            if (
                self._finished
                or not hardware
                or not hardware["enabled"]
                or hardware["status"] not in {"starting", "running"}
            ):
                return
            hardware["inventory"] = self._clean(inventory)
            hardware["status"] = "running"
            self._persist()

    def hardware_status(self, status: str, reason: str | None = None) -> None:
        with self._lock:
            hardware = self._data.get("hardware")
            if (
                self._finished
                or not hardware
                or not hardware["enabled"]
                or hardware["status"] in {"stopped", "timed_out", "unavailable"}
            ):
                return
            hardware["status"] = self._clean(status)
            if reason is not None:
                hardware["reason"] = self._clean(reason)
            self._persist()

    def hardware_warning(self, message: str) -> None:
        """Sensor failures are diagnostics, not application failures."""
        with self._lock:
            hardware = self._data.get("hardware")
            if (
                self._finished
                or not hardware
                or not hardware["enabled"]
                or hardware["status"] not in {"starting", "running"}
            ):
                return
            hardware["errors"].append(
                {"at": _utc_now(), "message": self._clean(message)}
            )
            del hardware["errors"][:-8]
            hardware["error_count"] += 1
            self._persist()

    @staticmethod
    def _hardware_numbers(value: Any, path: str = ""):
        # Summarize measurements, never PIDs, versions, timestamps or status codes.
        suffixes = (
            "_percent",
            "_bytes",
            "_bytes_per_second",
            "_ms",
            "_celsius",
            "_watts",
            "_mhz",
            "_rpm",
            "_c",
        )
        if isinstance(value, dict):
            if path == "processes.totals" and value.get("complete") is False:
                return
            for key, child in value.items():
                key_path = f"{path}.{key}" if path else key
                if isinstance(child, (dict, list)):
                    yield from RunLog._hardware_numbers(child, key_path)
                elif (
                    (key.endswith(suffixes) or key in {"percent", "rpm"})
                    and type(child) in (int, float)
                    and math.isfinite(child)
                ):
                    yield key_path, child
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, dict):
                    # Distinguish PID reuse and independent sensor groups.
                    identity = child.get("pid", child.get("index", index))
                    if "pid" in child and "created_at_unix" in child:
                        identity = f"{child['pid']}@{child['created_at_unix']}"
                    elif "group" in child:
                        identity = f"{child['group']}:{child.get('index', index)}"
                    yield from RunLog._hardware_numbers(child, f"{path}[{identity}]")
                elif (
                    path.endswith(suffixes)
                    and type(child) in (int, float)
                    and math.isfinite(child)
                ):
                    yield f"{path}[{index}]", child

    def hardware_sample(self, sample: dict) -> None:
        with self._lock:
            hardware = self._data.get("hardware")
            if (
                self._finished
                or not hardware
                or not hardware["enabled"]
                or hardware["status"] not in {"starting", "running"}
            ):
                return

            def section(value: Any) -> dict:
                return value if isinstance(value, dict) else {}

            runtime = section(self._data["metrics"].get("runtime"))
            performance = section(runtime.get("performance"))
            presentation = section(runtime.get("presentation"))
            simulation = section(runtime.get("simulation"))
            startup = section(runtime.get("startup"))
            context = {
                "run_status": self._data["status"],
                "viewer_metrics_at": self._data["metrics"].get("runtime_at"),
                "viewer_elapsed_ms": runtime.get("elapsed_ms"),
                "startup_stage": startup.get("stage"),
                "startup_complete": startup.get("complete"),
                "mode": presentation.get("mode"),
                "rendering_3d": presentation.get("rendering_3d"),
                "resident_count": simulation.get("resident_count"),
                "paused": simulation.get("paused"),
                "frame_p95_ms": performance.get("p95_ms"),
                "frame_samples": performance.get("samples"),
            }
            cleaned = self._clean(sample)
            entry = {
                **cleaned,
                "at": _utc_now(),
                "elapsed_seconds": round(time.monotonic() - self._started, 3),
                "context": self._clean(context),
            }
            hardware["samples"].append(entry)
            hardware["samples_recorded"] += 1
            overflow = len(hardware["samples"]) - hardware["history_limit"]
            if overflow > 0:
                del hardware["samples"][:overflow]
                hardware["samples_dropped"] += overflow
            summary = hardware["summary"]
            for key, value in self._hardware_numbers(cleaned):
                if key not in summary:
                    if len(summary) >= MAX_HARDWARE_SUMMARIES:
                        hardware["summary_truncated"] = True
                        continue
                    summary[key] = {
                        "count": 0,
                        "min": value,
                        "max": value,
                        "mean": 0.0,
                        "last": value,
                    }
                item = summary[key]
                item["count"] += 1
                item["min"] = min(item["min"], value)
                item["max"] = max(item["max"], value)
                item["mean"] += (value - item["mean"]) / item["count"]
                item["last"] = value
            # Keep one-second samples in memory, flush every five seconds and at
            # normal finish. Other log events also flush the current history.
            if hardware["samples_recorded"] == 1 or (
                time.monotonic() - self._last_persisted >= HARDWARE_PERSIST_SECONDS
            ):
                self._persist()

    def _error(self, message: str, source: str, fatal: bool = True) -> None:
        self._has_errors = self._has_errors or fatal
        errors = self._data["diagnostics"]["errors"]
        errors.append(
            {
                "at": _utc_now(),
                "source": self._clean(source),
                "message": self._clean(message),
                "severity": "error" if fatal else "warning",
            }
        )
        del errors[:-MAX_ERRORS]
        self._data["diagnostics"]["error_count"] += 1

    def error(self, message: str, source: str = "launcher") -> None:
        with self._lock:
            if self._finished:
                return
            self._error(message, source)
            self._persist()

    def _profile(self, payload: dict) -> dict:
        return self._clean(
            {key: value for key, value in payload.items() if key in _PROFILE_KEYS}
        )

    def _consume(self, line: str, truncated: bool = False) -> None:
        line = _ANSI.sub("", line).strip()
        if not line:
            return
        with self._lock:
            if self._finished:
                return
            diagnostics = self._data["diagnostics"]
            if truncated:
                diagnostics["truncated_line_count"] += 1
            marker, _, text = line.partition(" ")
            if marker.startswith("GODOT_APPLICATION_"):
                name = marker.removeprefix("GODOT_APPLICATION_")
                if name == "FAIL":
                    self._error(text, "viewer")
                    self._event("viewer_failed", {"message": text})
                elif name == "SCREENSHOT":
                    self._event("screenshot", {"path": text})
                elif name in {
                    "LOADING_VISIBLE",
                    "STARTUP_COMPLETE",
                    "FRAME_PROFILE",
                    "RUN_METRICS",
                    "READY",
                    "SMOKE_OK",
                }:
                    try:
                        payload = json.loads(text) if not truncated else None
                    except (ValueError, RecursionError):
                        payload = None
                    if not isinstance(payload, dict):
                        diagnostics["malformed_marker_count"] += 1
                    else:
                        metrics = self._data["metrics"]
                        if name in {"READY", "SMOKE_OK"}:
                            summary = {
                                key: value
                                for key, value in payload.items()
                                if key in _SUMMARY_KEYS
                                and not isinstance(value, (dict, list))
                            }
                            metrics["viewer"] = self._clean(summary)
                            if isinstance(payload.get("frame_profile"), dict):
                                metrics["frame_profile"] = self._profile(
                                    payload["frame_profile"]
                                )
                            self._event(
                                "viewer_ready" if name == "READY" else "smoke_ok", {}
                            )
                        elif name == "FRAME_PROFILE":
                            metrics["frame_profile"] = self._profile(payload)
                        elif name == "RUN_METRICS":
                            metrics["runtime"] = self._clean(payload)
                            metrics["runtime_at"] = _utc_now()
                            if (
                                isinstance(payload.get("error"), str)
                                and payload["error"]
                            ):
                                self._error(payload["error"], "viewer")
                            if payload.get("startup_complete") is True:
                                self._startup_complete = True
                            startup = payload.get("startup")
                            if (
                                isinstance(startup, dict)
                                and startup.get("complete") is True
                            ):
                                self._startup_complete = True
                        elif name == "STARTUP_COMPLETE":
                            metrics["startup"] = self._clean(payload)
                            self._startup_complete = True
                            self._event("startup_complete", {})
                        else:
                            metrics["loading_visible"] = self._clean(payload)
                            self._event("loading_visible", {})
                # Unknown marker bodies can contain simulation data. Do not retain them.
                self._persist()
                return
            diagnostics["console_line_count"] += 1
            if line.startswith("Godot Engine "):
                diagnostics["engine"] = self._clean(line)
            elif line.startswith(
                ("OpenGL ", "Vulkan ", "Direct3D ", "D3D12 ", "Metal ")
            ):
                diagnostics["renderer"] = self._clean(line)
            diagnostics["console_tail"].append(self._clean(line))
            del diagnostics["console_tail"][:-MAX_CONSOLE_LINES]
            fatal = line.startswith("SCRIPT ERROR:") or "Parse Error:" in line
            is_error = fatal or line.startswith("ERROR:")
            if is_error:
                self._error(line, "godot", fatal=fatal)
            if is_error or time.monotonic() - self._last_persisted >= 1.0:
                self._persist()

    def capture(self, stream: TextIO) -> threading.Thread:
        """Drain and tee viewer output without blocking the launcher monitor."""
        console = sys.stdout

        def read() -> None:
            continuation = False
            silent = False
            try:
                while True:
                    chunk = stream.readline(MAX_LINE)
                    if not chunk:
                        break
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode("utf-8", errors="replace")
                    if not continuation:
                        silent = chunk.startswith("GODOT_APPLICATION_RUN_METRICS ")
                    if not silent and console is not None:
                        try:
                            console.write(self._redact(chunk))
                            console.flush()
                        except (OSError, ValueError, AttributeError):
                            pass
                    truncated = len(chunk) >= MAX_LINE and not chunk.endswith("\n")
                    if not continuation:
                        self._consume(chunk, truncated=truncated)
                    continuation = truncated
            except (OSError, ValueError) as error:
                self.event("viewer_output_unavailable", message=str(error))
            finally:
                with self._lock:
                    self._persist()

        thread = threading.Thread(target=read, name="civic-run-log", daemon=True)
        with self._lock:
            self._threads.append(thread)
        thread.start()
        return thread

    def close_capture(self, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            threads = tuple(self._threads)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def finish(self, status: str, exit_code: int | None, **fields: Any) -> None:
        with self._lock:
            if self._finished:
                return
            self._data.update(
                self._clean(
                    {
                        key: value
                        for key, value in fields.items()
                        if key not in _RESERVED
                    }
                )
            )
            self._data.update(
                status=self._clean(status),
                exit_code=exit_code,
                ended_at=_utc_now(),
                duration_seconds=round(time.monotonic() - self._started, 3),
            )
            self._event("run_finished", {"status": status, "exit_code": exit_code})
            self._persist()
            self._finished = True
