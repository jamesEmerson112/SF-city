"""GPU telemetry remains usable without a particular driver or optional sensor."""

import json
from types import SimpleNamespace

import pytest

from civic_center import gpu_hardware
from civic_center.gpu_hardware import NvidiaCollector


class NVMLError_NotSupported(Exception):
    pass


class NVMLError_DriverNotLoaded(Exception):
    pass


class NVMLError_GpuIsLost(Exception):
    pass


class FakeNvml:
    NVML_TEMPERATURE_GPU = 0
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 2

    def __init__(self, count=1):
        self.count = count
        self.init_calls = 0
        self.shutdown_calls = 0
        self.handle_calls = []
        self.lost = set()

    def nvmlInit(self):
        self.init_calls += 1

    def nvmlShutdown(self):
        self.shutdown_calls += 1

    def nvmlDeviceGetCount(self):
        return self.count

    def nvmlDeviceGetHandleByIndex(self, index):
        self.handle_calls.append(index)
        if index in self.lost:
            raise NVMLError_GpuIsLost("private details must not be recorded")
        return index

    def nvmlDeviceGetName(self, handle):
        return b"NVIDIA Test Adapter"

    def nvmlSystemGetDriverVersion(self):
        return b"582.66"

    def nvmlDeviceGetMemoryInfo(self, handle):
        return SimpleNamespace(total=8 * 1024**3, used=2 * 1024**3, free=6 * 1024**3)

    def nvmlDeviceGetUtilizationRates(self, handle):
        return SimpleNamespace(gpu=42, memory=17)

    def nvmlDeviceGetTemperature(self, handle, sensor):
        assert sensor == self.NVML_TEMPERATURE_GPU
        return 61

    def nvmlDeviceGetPowerUsage(self, handle):
        return 125500

    def nvmlDeviceGetClockInfo(self, handle, domain):
        return {self.NVML_CLOCK_GRAPHICS: 1500, self.NVML_CLOCK_MEM: 4000}[domain]

    def nvmlDeviceGetFanSpeed(self, handle):
        return 30


@pytest.fixture
def nvml(monkeypatch):
    module = FakeNvml()
    monkeypatch.setattr(gpu_hardware.importlib, "import_module", lambda name: module)
    return module


def test_constructor_and_unused_close_do_not_touch_optional_driver(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gpu_hardware.importlib, "import_module", lambda name: calls.append(name)
    )
    collector = NvidiaCollector()
    assert calls == []
    collector.close()
    collector.close()
    assert collector.sample()["status"] == "closed"
    assert calls == []


def test_inventory_and_samples_have_safe_identity_and_correct_units(nvml):
    collector = NvidiaCollector()
    inventory = collector.inventory()
    adapter = inventory["adapters"][0]
    assert inventory["status"] == "ok"
    assert adapter["model"] == "NVIDIA Test Adapter"
    assert adapter["driver_version"] == "582.66"
    assert adapter["vram_total_bytes"] == 8 * 1024**3
    adapter["model"] = "caller mutation"
    assert collector.inventory()["adapters"][0]["model"] == "NVIDIA Test Adapter"

    sample = collector.sample()
    adapter = sample["adapters"][0]
    assert sample["scope"] == "adapter"
    assert adapter["gpu_utilization_percent"] == 42
    assert adapter["memory_utilization_percent"] == 17
    assert adapter["vram_used_bytes"] == 2 * 1024**3
    assert adapter["vram_free_bytes"] == 6 * 1024**3
    assert adapter["temperature_c"] == 61
    assert adapter["power_watts"] == 125.5
    assert adapter["graphics_clock_mhz"] == 1500
    assert adapter["memory_clock_mhz"] == 4000
    assert adapter["fan_speed_percent"] == 30
    assert all(item["status"] == "ok" for item in adapter["metrics_status"].values())
    assert nvml.init_calls == 1
    encoded = json.dumps({"inventory": inventory, "sample": sample}, allow_nan=False)
    assert "uuid" not in encoded and "serial" not in encoded
    collector.close()
    collector.close()
    assert nvml.shutdown_calls == 1
    assert collector.inventory()["status"] == "closed"


def test_missing_optional_binding_is_recorded_and_not_retried(monkeypatch):
    calls = []

    def missing(name):
        calls.append(name)
        raise ModuleNotFoundError("sensitive local dependency path")

    monkeypatch.setattr(gpu_hardware.importlib, "import_module", missing)
    collector = NvidiaCollector()
    assert collector.inventory()["reason"] == "ModuleNotFoundError"
    assert collector.sample()["status"] == "unavailable"
    assert calls == ["pynvml"]
    collector.close()


def test_absent_driver_is_not_an_application_error(nvml, monkeypatch):
    def absent():
        raise NVMLError_DriverNotLoaded()

    monkeypatch.setattr(nvml, "nvmlInit", absent)
    collector = NvidiaCollector()
    assert collector.sample()["reason"] == "NVMLError_DriverNotLoaded"
    assert collector.inventory()["adapters"] == []
    collector.close()
    assert nvml.shutdown_calls == 0


def test_unsupported_metric_does_not_drop_other_measurements(nvml, monkeypatch):
    def unsupported(handle):
        raise NVMLError_NotSupported()

    monkeypatch.setattr(nvml, "nvmlDeviceGetPowerUsage", unsupported)
    collector = NvidiaCollector()
    sample = collector.sample()
    adapter = sample["adapters"][0]
    assert sample["status"] == "partial"
    assert adapter["power_watts"] is None
    assert adapter["metrics_status"]["power_watts"] == {
        "status": "unsupported",
        "reason": "NVMLError_NotSupported",
    }
    assert adapter["temperature_c"] == 61
    assert adapter["fan_speed_percent"] == 30
    collector.close()


def test_disappearing_adapter_does_not_abort_other_adapters(nvml):
    nvml.count = 2
    collector = NvidiaCollector()
    assert len(collector.inventory()["adapters"]) == 2
    nvml.lost.add(0)
    report = collector.sample()
    first, second = report["adapters"]
    assert report["status"] == "partial"
    assert first["gpu_utilization_percent"] is None
    assert first["status"] == "unavailable"
    assert first["metrics_status"]["temperature_c"]["reason"] == "NVMLError_GpuIsLost"
    assert second["gpu_utilization_percent"] == 42
    assert "private details" not in json.dumps(report)
    nvml.lost.clear()
    assert collector.sample()["status"] == "ok"
    collector.close()


def test_failed_enumeration_still_releases_initialized_nvml(nvml, monkeypatch):
    def failed_count():
        raise RuntimeError("failed")

    monkeypatch.setattr(nvml, "nvmlDeviceGetCount", failed_count)
    collector = NvidiaCollector()
    assert collector.inventory()["status"] == "unavailable"
    collector.close()
    collector.close()
    assert nvml.shutdown_calls == 1


def test_no_nvidia_adapters_is_explicit(nvml):
    nvml.count = 0
    collector = NvidiaCollector()
    assert collector.inventory()["reason"] == "no_nvidia_adapters"
    assert collector.sample()["adapters"] == []
    collector.close()


def test_many_adapters_are_bounded(nvml):
    nvml.count = 1000
    collector = NvidiaCollector()
    inventory = collector.inventory()
    assert inventory["reason"] == "adapter_limit"
    assert inventory["detected_adapter_count"] == 1000
    assert len(inventory["adapters"]) == gpu_hardware.MAX_ADAPTERS
    assert max(nvml.handle_calls) == gpu_hardware.MAX_ADAPTERS - 1
    collector.close()


@pytest.mark.parametrize("reading", [float("nan"), float("inf"), -1, 2**64 - 1])
def test_invalid_readings_are_null_json_values(nvml, monkeypatch, reading):
    monkeypatch.setattr(nvml, "nvmlDeviceGetPowerUsage", lambda handle: reading)
    collector = NvidiaCollector()
    report = collector.sample()
    adapter = report["adapters"][0]
    assert adapter["power_watts"] is None
    assert adapter["metrics_status"]["power_watts"]["reason"] == "invalid_reading"
    assert adapter["gpu_utilization_percent"] == 42
    json.dumps(report, allow_nan=False)
    collector.close()


def test_shutdown_failure_is_best_effort(nvml, monkeypatch):
    def failed_shutdown():
        nvml.shutdown_calls += 1
        raise RuntimeError("driver already gone")

    monkeypatch.setattr(nvml, "nvmlShutdown", failed_shutdown)
    collector = NvidiaCollector()
    collector.sample()
    collector.close()
    collector.close()
    assert nvml.shutdown_calls == 1
