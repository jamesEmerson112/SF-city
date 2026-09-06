"""Best-effort local hardware counters, restricted to SF-city's process tree.

Counter deltas belong to this collector rather than psutil's thread-local CPU
baselines. Unsupported readings stay null and every provider reports its status.
No process command lines, network identities, or machine serials are collected.
"""

from __future__ import annotations

import importlib
import math
import os
import platform
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .gpu_hardware import NvidiaCollector

MAX_PROCESSES = 64
MAX_CORES = 64
MAX_SENSORS = 64
_IO_FIELDS = ("read_bytes", "write_bytes", "read_count", "write_count")


def _status(status: str, reason: str | None = None, **values: Any) -> dict:
    return {"status": status, "reason": reason, **values}


def _error(error: Exception) -> dict:
    # Exception messages can contain filenames, user names, or command lines.
    name = type(error).__name__
    status = (
        "unsupported"
        if isinstance(error, (AttributeError, NotImplementedError))
        else "unavailable"
    )
    return _status(status, name)


def _number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if math.isfinite(value) and value >= 0 else None
    return None


def _fields(value: Any, fields: dict[str, str]) -> dict:
    return {
        target: _number(getattr(value, source, None))
        for source, target in fields.items()
    }


def _read(call: Callable[[], Any], fields: dict[str, str]) -> dict:
    try:
        value = call()
        if value is None:
            return _status(
                "unavailable", "No data reported", **dict.fromkeys(fields.values())
            )
        values = _fields(value, fields)
        if all(value is None for value in values.values()):
            return _status("unavailable", "No supported numeric fields", **values)
        return _status("ok", **values)
    except Exception as error:
        return {**_error(error), **dict.fromkeys(fields.values())}


def _cpu_identity() -> dict:
    identity = {"model": platform.processor().strip() or None, "vendor": None}
    try:
        if platform.system() == "Windows":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                for target, name in (
                    ("model", "ProcessorNameString"),
                    ("vendor", "VendorIdentifier"),
                ):
                    try:
                        identity[target] = (
                            str(winreg.QueryValueEx(key, name)[0]).strip() or None
                        )
                    except OSError:
                        pass
        elif platform.system() == "Linux":
            # Read only model/vendor values; no other hardware identifiers persist.
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                name, separator, value = line.partition(":")
                target = {"model name": "model", "vendor_id": "vendor"}.get(
                    name.strip()
                )
                if separator and target:
                    identity[target] = value.strip() or None
                if all(identity.values()):
                    break
    except (OSError, ImportError):
        pass
    return identity


def _cpu_counts(value: Any) -> tuple[float, float, tuple[float, ...]]:
    fields = value._asdict()
    excluded = {"guest", "guest_nice"}
    if "dpc" in fields:
        # Windows system time already includes interrupt and DPC time.
        excluded.update(("interrupt", "irq", "dpc"))
    total = sum(float(v) for k, v in fields.items() if k not in excluded)
    idle = float(fields.get("idle", 0)) + float(fields.get("iowait", 0))
    return total, idle, tuple(float(v) for k, v in fields.items() if k not in excluded)


def _cpu_percent(previous: tuple, current: tuple) -> float | None:
    if len(current) > 2 and len(previous) > 2:
        if len(current[2]) != len(previous[2]) or any(
            new < old for old, new in zip(previous[2], current[2])
        ):
            return None
    total = current[0] - previous[0]
    idle = current[1] - previous[1]
    if (
        not math.isfinite(total)
        or not math.isfinite(idle)
        or total <= 0
        or idle < 0
        or idle > total
    ):
        return None
    return round((total - idle) / total * 100, 3)


@dataclass
class _TrackedProcess:
    process: Any
    created: float
    role: str
    cpu_before: tuple[float, float] | None = None
    io_before: tuple[float, dict] | None = None


class HardwareCollector:
    """Collect one snapshot at a time; scheduling and persistence live elsewhere."""

    def __init__(self, root_pid: int, data_path: Path) -> None:
        self._lock = threading.RLock()
        self._root_pid = root_pid
        self._root_created: float | None = None
        self._closed = False
        self._processes: dict[int, _TrackedProcess] = {}
        self._registration_errors: dict[int, dict] = {}
        self._cpu_before: list[tuple] | None = None
        self._disk_before: tuple[float, dict] | None = None
        self._data_path = Path(data_path)
        while (
            not self._data_path.exists() and self._data_path != self._data_path.parent
        ):
            self._data_path = self._data_path.parent
        try:
            self._psutil = importlib.import_module("psutil")
            self._provider = _status(
                "ok", version=getattr(self._psutil, "__version__", None)
            )
        except Exception as error:
            self._psutil = None
            self._provider = _status("unavailable", f"psutil: {type(error).__name__}")
        self._gpu = NvidiaCollector()
        self.register_process(root_pid, "launcher")

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if self._psutil is None:
            raise ModuleNotFoundError("psutil")
        return getattr(self._psutil, name)(*args, **kwargs)

    def _belongs_to_launcher(self, process: Any) -> bool:
        root = self._processes.get(self._root_pid)
        if root is None or not root.process.is_running():
            return False
        ancestor = process
        seen = set()
        for _ in range(MAX_PROCESSES):
            if ancestor is None or ancestor.pid in seen:
                return False
            seen.add(ancestor.pid)
            if ancestor.pid == self._root_pid:
                return ancestor.create_time() == self._root_created
            ancestor = ancestor.parent()
        return False

    def register_process(self, pid: int, role: str) -> None:
        """Capture identity now so a later recycled PID cannot join the report."""
        with self._lock:
            if self._closed or self._psutil is None or pid <= 0:
                return
            try:
                process = self._psutil.Process(pid)
                created = process.create_time()
                if pid == self._root_pid:
                    allowed = (
                        self._root_created is None or created == self._root_created
                    )
                    if allowed:
                        self._root_created = created
                else:
                    allowed = self._belongs_to_launcher(process)
                if not allowed:
                    if len(self._registration_errors) < MAX_PROCESSES:
                        self._registration_errors[pid] = {
                            "pid": pid,
                            "role": role[:48],
                            **_status("unavailable", "Launcher ancestry not verified"),
                        }
                    return
                existing = self._processes.get(pid)
                if existing is not None and existing.created == created:
                    existing.role = role[:48]
                elif len(self._processes) < MAX_PROCESSES:
                    self._processes[pid] = _TrackedProcess(process, created, role[:48])
                self._registration_errors.pop(pid, None)
            except Exception as error:
                if len(self._registration_errors) < MAX_PROCESSES:
                    self._registration_errors[pid] = {
                        "pid": pid,
                        "role": role[:48],
                        **_error(error),
                    }

    def _disk_capacity(self) -> dict:
        return _read(
            lambda: shutil.disk_usage(self._data_path),
            {"total": "total_bytes", "used": "used_bytes", "free": "free_bytes"},
        )

    def inventory(self) -> dict:
        memory = self._memory()
        cpu = _cpu_identity()
        for logical, label in ((True, "logical_cores"), (False, "physical_cores")):
            try:
                cpu[label] = self._call("cpu_count", logical=logical)
            except Exception:
                cpu[label] = os.cpu_count() if logical else None
        capabilities = {}
        for label, api in (
            ("cpu", "cpu_times"),
            ("memory", "virtual_memory"),
            ("swap", "swap_memory"),
            ("disk_io", "disk_io_counters"),
            ("processes", "Process"),
            ("cpu_frequency", "cpu_freq"),
            ("temperatures", "sensors_temperatures"),
            ("fans", "sensors_fans"),
            ("battery", "sensors_battery"),
        ):
            supported = self._psutil is not None and callable(
                getattr(self._psutil, api, None)
            )
            capabilities[label] = _status(
                "available" if supported else "unavailable",
                (
                    "Platform API present; readings may be unavailable"
                    if supported
                    else "psutil missing or platform API unsupported"
                ),
            )
        try:
            gpu = self._gpu.inventory()
        except Exception as error:
            gpu = _error(error)
        return {
            "schema_version": 1,
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "architecture": platform.machine(),
            },
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
            },
            "cpu": cpu,
            "memory_total_bytes": memory["total_bytes"],
            "memory_status": memory["status"],
            "data_volume": self._disk_capacity(),
            "providers": {"psutil": dict(self._provider), "capabilities": capabilities},
            "gpu": gpu,
            "measurement": {
                "system_cpu_percent": "0-100 across all logical cores",
                "process_cpu_percent": "100 is one fully busy logical core; may exceed 100",
                "process_memory": "RSS sum can double-count shared pages; private bytes when available",
                "disk_io": "System-wide counters; device aggregation may include logical devices",
                "cpu_frequency": "MHz; generally nominal rather than dynamic outside Linux",
                "sensors": "Platform dependent; missing readings are null, not zero",
            },
        }

    def _cpu(self) -> dict:
        frequency = _read(
            lambda: self._call("cpu_freq"),
            {"current": "current_mhz", "min": "min_mhz", "max": "max_mhz"},
        )
        for name in ("current_mhz", "min_mhz", "max_mhz"):
            if frequency[name] == 0:
                frequency[name] = None
        try:
            current = [
                _cpu_counts(item) for item in self._call("cpu_times", percpu=True)
            ]
            previous, self._cpu_before = self._cpu_before, current
            coverage = {
                "logical_cores_observed": len(current),
                "per_core_limit": MAX_CORES,
                "per_core_omitted": max(0, len(current) - MAX_CORES),
            }
            if not current:
                return _status(
                    "unavailable",
                    "No CPU counters",
                    percent=None,
                    per_core_percent=None,
                    frequency=frequency,
                )
            if previous is None or len(previous) != len(current):
                return _status(
                    "warming_up",
                    "Counter baseline",
                    percent=None,
                    per_core_percent=[None] * min(len(current), MAX_CORES),
                    **coverage,
                    frequency=frequency,
                )
            values = [
                _cpu_percent(before, after) for before, after in zip(previous, current)
            ]
            # Any reset invalidates aggregate comparison, then the next sample resumes.
            percent = (
                None
                if None in values
                else _cpu_percent(
                    (sum(v[0] for v in previous), sum(v[1] for v in previous)),
                    (sum(v[0] for v in current), sum(v[1] for v in current)),
                )
            )
            return _status(
                "ok" if percent is not None else "warming_up",
                None if percent is not None else "Counter reset or no elapsed CPU time",
                percent=percent,
                per_core_percent=values[:MAX_CORES],
                **coverage,
                frequency=frequency,
            )
        except Exception as error:
            self._cpu_before = None
            return {
                **_error(error),
                "percent": None,
                "per_core_percent": None,
                "frequency": frequency,
            }

    def _memory(self) -> dict:
        return _read(
            lambda: self._call("virtual_memory"),
            {
                "total": "total_bytes",
                "available": "available_bytes",
                "used": "used_bytes",
                "percent": "percent",
            },
        )

    @staticmethod
    def _io_rates(current: dict, before: tuple | None, now: float) -> dict:
        rates = dict.fromkeys(f"{name}_per_second" for name in _IO_FIELDS)
        if before is None or now <= before[0]:
            return _status("warming_up", "Counter baseline", **rates)
        elapsed = now - before[0]
        reset = False
        for name in _IO_FIELDS:
            old, new = before[1].get(name), current.get(name)
            if old is not None and new is not None:
                if new < old:
                    reset = True
                else:
                    rates[f"{name}_per_second"] = round((new - old) / elapsed, 3)
        if reset:
            return _status("warming_up", "Counter reset", **dict.fromkeys(rates))
        return _status(
            "ok" if any(v is not None for v in rates.values()) else "unavailable",
            **rates,
        )

    def _disk(self, now: float) -> dict:
        counters = _read(
            lambda: self._call("disk_io_counters", nowrap=False),
            {name: name for name in _IO_FIELDS},
        )
        if counters["status"] == "ok":
            rates = self._io_rates(counters, self._disk_before, now)
            self._disk_before = (now, counters)
        else:
            rates = {
                **counters,
                **dict.fromkeys(f"{name}_per_second" for name in _IO_FIELDS),
            }
            self._disk_before = None
        return {
            "scope": "system",
            "counters": counters,
            "rates": rates,
            "data_volume": self._disk_capacity(),
        }

    def _discover(self) -> dict:
        root = self._processes.get(self._root_pid)
        if root is None:
            return _status("unavailable", "Launcher process unavailable")
        try:
            if not root.process.is_running():
                return _status("unavailable", "Launcher exited or PID reused")
            children = root.process.children(recursive=True)
            truncated = len(children) + 1 > MAX_PROCESSES
            for process in children[: MAX_PROCESSES - 1]:
                if process.pid not in self._processes:
                    self.register_process(process.pid, "child")
            return _status(
                "partial" if truncated else "ok",
                "Process limit reached" if truncated else None,
            )
        except Exception as error:
            return _error(error)

    def _process_sample(self, item: _TrackedProcess, now: float) -> dict:
        process = item.process
        row = {"pid": process.pid, "role": item.role, "created_at_unix": item.created}
        try:
            if not process.is_running():
                return {**row, **_status("exited", "Process exited or PID reused")}
            # psutil checks identity in is_running(); retain a fresh identity check
            # before reading counters because create_time on a Process is cached.
            if self._call("Process", process.pid).create_time() != item.created:
                return {**row, **_status("exited", "PID reused")}
        except Exception as error:
            return {**row, **_error(error)}
        try:
            times = process.cpu_times()
            cpu_seconds = times.user + times.system
            cpu_percent = None
            reason = "Counter baseline"
            if item.cpu_before is not None and now > item.cpu_before[0]:
                delta = cpu_seconds - item.cpu_before[1]
                if delta >= 0:
                    cpu_percent = round(delta / (now - item.cpu_before[0]) * 100, 3)
                    reason = None
                else:
                    reason = "Counter reset"
            item.cpu_before = (now, cpu_seconds)
            row["cpu"] = _status(
                "ok" if cpu_percent is not None else "warming_up",
                reason,
                percent=cpu_percent,
            )
        except Exception as error:
            item.cpu_before = None
            row["cpu"] = {**_error(error), "percent": None}
        row["memory"] = _read(
            lambda: process.memory_info(),
            {"rss": "rss_bytes", "vms": "virtual_bytes", "private": "private_bytes"},
        )
        row["memory"]["private_status"] = (
            "ok"
            if row["memory"]["private_bytes"] is not None
            else "unsupported_or_unavailable"
        )
        counters = _read(
            lambda: process.io_counters(), {name: name for name in _IO_FIELDS}
        )
        if counters["status"] == "ok":
            rates = self._io_rates(counters, item.io_before, now)
            item.io_before = (now, counters)
        else:
            rates = {
                "status": counters["status"],
                "reason": counters["reason"],
                **dict.fromkeys(f"{name}_per_second" for name in _IO_FIELDS),
            }
            item.io_before = None
        row["io"] = {"counters": counters, "rates": rates}
        row["status"] = (
            "ok"
            if all(row[key]["status"] == "ok" for key in ("cpu", "memory"))
            else "partial"
        )
        return row

    def _process_snapshot(self, now: float) -> dict:
        if self._psutil is None:
            return {**self._provider, "items": [], "totals": None}
        with self._lock:
            discovery = self._discover()
            items = []
            for pid, item in list(self._processes.items()):
                row = self._process_sample(item, now)
                items.append(row)
                if row["status"] == "exited" or row.get("reason") in (
                    "NoSuchProcess",
                    "ZombieProcess",
                ):
                    self._processes.pop(pid, None)
            items.extend(self._registration_errors.values())
            self._registration_errors.clear()
        active = [row for row in items if "memory" in row]

        def total(section: str, key: str) -> float | int | None:
            values = [row[section][key] for row in active]
            return (
                sum(values) if values and all(v is not None for v in values) else None
            )

        cpu = total("cpu", "percent")
        try:
            cores = self._call("cpu_count", logical=True)
        except Exception:
            cores = None
        omitted = max(0, len(items) - MAX_PROCESSES)
        incomplete = bool(omitted) or any(
            row["status"] not in ("ok", "exited") for row in items
        )
        return {
            "status": "partial" if incomplete or discovery["status"] != "ok" else "ok",
            "discovery": discovery,
            "items": items[:MAX_PROCESSES],
            "items_omitted": omitted,
            "process_limit": MAX_PROCESSES,
            "totals": {
                "sampled_processes": len(active),
                "cpu_percent": cpu,
                "machine_cpu_percent": (
                    round(cpu / cores, 3) if cpu is not None and cores else None
                ),
                "rss_bytes": total("memory", "rss_bytes"),
                "private_bytes": total("memory", "private_bytes"),
                "complete": not incomplete and discovery["status"] == "ok",
            },
        }

    def _sensor(self, api: str, fields: dict[str, str]) -> dict:
        try:
            groups = self._call(api)
            if not groups:
                return _status("unavailable", "No sensors reported", items=None)
            items = []
            total = sum(len(values) for values in groups.values())
            for group, values in groups.items():
                for index, value in enumerate(values):
                    if len(items) >= MAX_SENSORS:
                        break
                    # Avoid vendor-provided labels; group + index identifies series.
                    items.append(
                        {
                            "group": str(group)[:48],
                            "index": index,
                            **_fields(value, fields),
                        }
                    )
            return _status("ok", items=items, omitted=max(0, total - len(items)))
        except Exception as error:
            return {**_error(error), "items": None}

    def _battery(self) -> dict:
        try:
            value = self._call("sensors_battery")
            if value is None:
                return _status(
                    "unavailable",
                    "No battery reported",
                    percent=None,
                    seconds_left=None,
                    power_plugged=None,
                )
            return _status(
                "ok",
                percent=_number(value.percent),
                seconds_left=_number(value.secsleft),
                power_plugged=value.power_plugged,
            )
        except Exception as error:
            return {
                **_error(error),
                "percent": None,
                "seconds_left": None,
                "power_plugged": None,
            }

    def sample(self) -> dict:
        if self._closed:
            return _status("closed", "Collector closed")
        now = time.monotonic()
        try:
            gpu = self._gpu.sample()
        except Exception as error:
            gpu = _error(error)
        return {
            "cpu": self._cpu(),
            "memory": self._memory(),
            "swap": _read(
                lambda: self._call("swap_memory"),
                {
                    "total": "total_bytes",
                    "used": "used_bytes",
                    "free": "free_bytes",
                    "percent": "percent",
                },
            ),
            "disk": self._disk(now),
            "processes": self._process_snapshot(now),
            "sensors": {
                "temperatures": self._sensor(
                    "sensors_temperatures",
                    {
                        "current": "current_c",
                        "high": "high_c",
                        "critical": "critical_c",
                    },
                ),
                "fans": self._sensor("sensors_fans", {"current": "rpm"}),
                "battery": self._battery(),
            },
            "gpu": gpu,
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._processes.clear()
            self._registration_errors.clear()
        try:
            self._gpu.close()
        except Exception:
            pass
