"""Optional read-only NVIDIA adapter diagnostics through NVIDIA's NVML bindings.

Importing this module and constructing a collector never loads the GPU driver.
Values are adapter-wide, including activity from applications other than SF-city.
NVML memory reporting under Windows WDDM is not per-process memory accounting.

API units: https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html
"""

from __future__ import annotations

import copy
import importlib
import math
from typing import Any, Callable

MAX_ADAPTERS = 16
_SAMPLE_FIELDS = (
    "gpu_utilization_percent",
    "memory_utilization_percent",
    "vram_total_bytes",
    "vram_used_bytes",
    "vram_free_bytes",
    "temperature_c",
    "power_watts",
    "graphics_clock_mhz",
    "memory_clock_mhz",
    "fan_speed_percent",
)
_INVENTORY_FIELDS = ("model", "driver_version", "vram_total_bytes")


def _number(value: Any, maximum: float | None = None) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("non_numeric_reading")
    if not math.isfinite(value) or value < 0 or value in (2**32 - 1, 2**64 - 1):
        raise ValueError("invalid_reading")
    if maximum is not None and value > maximum:
        raise ValueError("out_of_range_reading")
    return value


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty_reading")
    return " ".join(value.split())[:160]


class NvidiaCollector:
    """Lazy, best-effort provider; call from one monitoring thread, then close."""

    def __init__(self) -> None:
        self._nvml: Any = None
        self._attempted = False
        self._initialized = False
        self._closed = False
        self._count = 0
        self._reason: str | None = None
        self._inventory: dict | None = None

    def _failure(self, error: Exception) -> dict:
        # Stable codes only: exception messages can contain local paths.
        name = type(error).__name__
        if isinstance(error, (ImportError, OSError)):
            status = "unavailable"
        elif isinstance(error, AttributeError) or name in (
            "NVMLError_NotSupported",
            "NVMLError_FunctionNotFound",
        ):
            status = "unsupported"
        elif name in (
            "NVMLError_GpuIsLost",
            "NVMLError_DriverNotLoaded",
            "NVMLError_LibraryNotFound",
            "NVMLError_NoPermission",
            "NVMLError_Uninitialized",
            "NVMLError_NotFound",
        ):
            status = "unavailable"
        elif isinstance(error, ValueError):
            return {"status": "unavailable", "reason": "invalid_reading"}
        else:
            status = "error"
        return {"status": status, "reason": name[:80]}

    def _start(self) -> None:
        if self._attempted or self._closed:
            return
        self._attempted = True
        try:
            self._nvml = importlib.import_module("pynvml")
            self._nvml.nvmlInit()
            self._initialized = True
            self._count = int(_number(self._nvml.nvmlDeviceGetCount()))
            if not self._count:
                self._reason = "no_nvidia_adapters"
        except Exception as error:
            self._reason = self._failure(error)["reason"]

    def _report(self, adapters: list[dict]) -> dict:
        status, reason = "ok", None
        if self._closed:
            status, reason = "closed", "collector_closed"
        elif self._reason:
            status, reason = "unavailable", self._reason
        elif self._count > MAX_ADAPTERS:
            status, reason = "partial", "adapter_limit"
        elif any(item["status"] != "ok" for item in adapters):
            status, reason = "partial", "some_metrics_unavailable"
        return {
            "provider": "nvidia_nvml",
            "status": status,
            "reason": reason,
            "scope": "adapter",
            "detected_adapter_count": self._count,
            "adapter_limit": MAX_ADAPTERS,
            "adapters": adapters,
        }

    @staticmethod
    def _empty(index: int, fields: tuple[str, ...]) -> dict:
        return {
            "index": index,
            "status": "ok",
            **dict.fromkeys(fields),
            "metrics_status": {},
        }

    @staticmethod
    def _finish_adapter(record: dict) -> dict:
        statuses = [item["status"] for item in record["metrics_status"].values()]
        if statuses and not any(item == "ok" for item in statuses):
            record["status"] = "unavailable"
        elif any(item != "ok" for item in statuses):
            record["status"] = "partial"
        return record

    def _query(
        self,
        record: dict,
        fields: dict[str, Callable[[Any], Any]],
        function: str,
        *arguments: Any,
    ) -> None:
        try:
            result = getattr(self._nvml, function)(*arguments)
        except Exception as error:
            failure = self._failure(error)
            for field in fields:
                record[field] = None
                record["metrics_status"][field] = failure.copy()
            return
        for field, transform in fields.items():
            try:
                record[field] = transform(result)
                record["metrics_status"][field] = {"status": "ok", "reason": None}
            except Exception as error:
                record[field] = None
                record["metrics_status"][field] = self._failure(error)

    def _handle(self, record: dict, fields: tuple[str, ...]) -> Any:
        try:
            return self._nvml.nvmlDeviceGetHandleByIndex(record["index"])
        except Exception as error:
            failure = self._failure(error)
            for field in fields:
                record["metrics_status"][field] = failure.copy()
            return None

    def inventory(self) -> dict:
        """Return safe hardware identity and per-field availability, never serials."""
        self._start()
        if self._closed or self._reason:
            return self._report([])
        if self._inventory is not None:
            return copy.deepcopy(self._inventory)
        adapters = []
        for index in range(min(self._count, MAX_ADAPTERS)):
            record = self._empty(index, _INVENTORY_FIELDS)
            handle = self._handle(record, _INVENTORY_FIELDS)
            if handle is not None:
                self._query(record, {"model": _text}, "nvmlDeviceGetName", handle)
                self._query(
                    record, {"driver_version": _text}, "nvmlSystemGetDriverVersion"
                )
                self._query(
                    record,
                    {"vram_total_bytes": lambda value: _number(value.total)},
                    "nvmlDeviceGetMemoryInfo",
                    handle,
                )
            adapters.append(self._finish_adapter(record))
        self._inventory = self._report(adapters)
        self._inventory["sample_fields"] = list(_SAMPLE_FIELDS)
        return copy.deepcopy(self._inventory)

    def sample(self) -> dict:
        """Read current adapter telemetry; unavailable readings stay null."""
        self._start()
        if self._closed or self._reason:
            return self._report([])
        adapters = []
        for index in range(min(self._count, MAX_ADAPTERS)):
            record = self._empty(index, _SAMPLE_FIELDS)
            handle = self._handle(record, _SAMPLE_FIELDS)
            if handle is not None:
                self._query(
                    record,
                    {
                        "gpu_utilization_percent": lambda value: _number(
                            value.gpu, 100
                        ),
                        "memory_utilization_percent": lambda value: _number(
                            value.memory, 100
                        ),
                    },
                    "nvmlDeviceGetUtilizationRates",
                    handle,
                )
                self._query(
                    record,
                    {
                        "vram_total_bytes": lambda value: _number(value.total),
                        "vram_used_bytes": lambda value: _number(value.used),
                        "vram_free_bytes": lambda value: _number(value.free),
                    },
                    "nvmlDeviceGetMemoryInfo",
                    handle,
                )
                self._query(
                    record,
                    {"temperature_c": _number},
                    "nvmlDeviceGetTemperature",
                    handle,
                    getattr(self._nvml, "NVML_TEMPERATURE_GPU", 0),
                )
                self._query(
                    record,
                    {"power_watts": lambda value: _number(value) / 1000.0},
                    "nvmlDeviceGetPowerUsage",
                    handle,
                )
                self._query(
                    record,
                    {"graphics_clock_mhz": _number},
                    "nvmlDeviceGetClockInfo",
                    handle,
                    getattr(self._nvml, "NVML_CLOCK_GRAPHICS", 0),
                )
                self._query(
                    record,
                    {"memory_clock_mhz": _number},
                    "nvmlDeviceGetClockInfo",
                    handle,
                    getattr(self._nvml, "NVML_CLOCK_MEM", 2),
                )
                self._query(
                    record,
                    {"fan_speed_percent": _number},
                    "nvmlDeviceGetFanSpeed",
                    handle,
                )
            adapters.append(self._finish_adapter(record))
        return self._report(adapters)

    def close(self) -> None:
        """Release only this collector's NVML reference, at most once."""
        if self._closed:
            return
        self._closed = True
        if self._initialized:
            self._initialized = False
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
