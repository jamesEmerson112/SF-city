"""Hardware reports preserve real deltas and isolate missing or denied providers."""

import json
from collections import namedtuple
from types import SimpleNamespace

import pytest

from civic_center import hardware
from civic_center.hardware import HardwareCollector

CpuTimes = namedtuple("CpuTimes", "user system idle iowait guest guest_nice")


class NoSuchProcess(Exception):
    pass


class AccessDenied(Exception):
    pass


class FakeProcess:
    def __init__(self, pid, created=10.0):
        self.pid = pid
        self.created = created
        self.running = True
        self.seconds = 1.0
        self.read_bytes = 1000
        self.write_bytes = 2000
        self.child_processes = []
        self.parent_process = None
        self.denied_memory = False
        self.read_calls = 0

    def create_time(self):
        return self.created

    def is_running(self):
        return self.running

    def children(self, recursive):
        assert recursive is True
        return self.child_processes

    def parent(self):
        return self.parent_process

    def cpu_times(self):
        self.read_calls += 1
        return SimpleNamespace(user=self.seconds, system=0)

    def memory_info(self):
        if self.denied_memory:
            raise AccessDenied("private-user-name/secret-path")
        return SimpleNamespace(rss=10000, vms=20000, private=8000)

    def io_counters(self):
        return SimpleNamespace(
            read_bytes=self.read_bytes,
            write_bytes=self.write_bytes,
            read_count=10,
            write_count=20,
        )


class FakePsutil:
    __version__ = "test"

    def __init__(self):
        self.processes = {100: FakeProcess(100), 101: FakeProcess(101)}
        self.processes[100].child_processes = [self.processes[101]]
        self.processes[101].parent_process = self.processes[100]
        self.times = [CpuTimes(10, 5, 80, 5, 2, 0), CpuTimes(10, 5, 80, 5, 2, 0)]
        self.disk = SimpleNamespace(
            read_bytes=1000, write_bytes=2000, read_count=10, write_count=20
        )

    def cpu_count(self, logical=True):
        return 2 if logical else 1

    def cpu_times(self, percpu):
        assert percpu is True
        return self.times

    def cpu_freq(self):
        return SimpleNamespace(current=3000, min=0, max=3500)

    def virtual_memory(self):
        return SimpleNamespace(total=100000, used=40000, available=60000, percent=40)

    def swap_memory(self):
        return SimpleNamespace(total=10000, used=1000, free=9000, percent=10)

    def disk_io_counters(self, nowrap):
        assert nowrap is False
        return self.disk

    def sensors_battery(self):
        return None

    def Process(self, pid):
        if pid not in self.processes:
            raise NoSuchProcess("user-secret")
        return self.processes[pid]


class FakeGpu:
    def __init__(self):
        self.closed = 0

    def inventory(self):
        return {"status": "ok", "adapters": [{"index": 0, "model": "Test GPU"}]}

    def sample(self):
        return {
            "status": "ok",
            "adapters": [{"index": 0, "gpu_utilization_percent": 20}],
        }

    def close(self):
        self.closed += 1


@pytest.fixture
def rig(monkeypatch, tmp_path):
    provider = FakePsutil()
    monkeypatch.setattr(hardware.importlib, "import_module", lambda name: provider)
    monkeypatch.setattr(hardware, "NvidiaCollector", FakeGpu)
    monkeypatch.setattr(
        hardware, "_cpu_identity", lambda: {"model": "Test CPU", "vendor": "Test"}
    )
    clock = [100.0]
    monkeypatch.setattr(hardware.time, "monotonic", lambda: clock[0])
    collector = HardwareCollector(100, tmp_path / "not-created" / "data")
    return collector, provider, clock


def test_inventory_has_machine_specs_and_safe_provider_capabilities(rig):
    collector, _, _ = rig
    result = collector.inventory()
    assert result["cpu"] == {
        "model": "Test CPU",
        "vendor": "Test",
        "logical_cores": 2,
        "physical_cores": 1,
    }
    assert result["memory_total_bytes"] == 100000
    assert result["data_volume"]["total_bytes"] > 0
    assert result["providers"]["psutil"] == {
        "status": "ok",
        "reason": None,
        "version": "test",
    }
    assert (
        result["providers"]["capabilities"]["temperatures"]["status"] == "unavailable"
    )
    assert result["gpu"]["adapters"][0]["model"] == "Test GPU"
    encoded = json.dumps(result, allow_nan=False)
    for forbidden in ("hostname", "serial", "cmdline", "username", "not-created"):
        assert forbidden not in encoded


def test_first_sample_warms_up_instead_of_claiming_idle_hardware(rig):
    collector, _, _ = rig
    sample = collector.sample()
    assert sample["cpu"]["status"] == "warming_up"
    assert sample["cpu"]["percent"] is None
    assert sample["cpu"]["per_core_percent"] == [None, None]
    assert sample["cpu"]["frequency"]["min_mhz"] is None
    assert sample["disk"]["rates"]["read_bytes_per_second"] is None
    assert sample["processes"]["totals"]["cpu_percent"] is None
    assert sample["memory"]["used_bytes"] == 40000
    assert sample["sensors"]["temperatures"]["items"] is None
    assert sample["sensors"]["battery"]["percent"] is None
    assert sample["gpu"]["adapters"][0]["gpu_utilization_percent"] == 20
    json.dumps(sample, allow_nan=False)


def test_rates_and_cpu_normalization_use_elapsed_time_and_exclude_guest(rig):
    collector, provider, clock = rig
    collector.register_process(101, "viewer")
    collector.sample()
    clock[0] += 2
    provider.times = [CpuTimes(11, 5, 81, 5, 3, 0), CpuTimes(10, 5, 82, 5, 2, 0)]
    provider.disk = SimpleNamespace(
        read_bytes=5000, write_bytes=3000, read_count=14, write_count=22
    )
    provider.processes[100].seconds += 1
    provider.processes[101].seconds += 3
    provider.processes[101].read_bytes += 800
    sample = collector.sample()
    assert sample["cpu"]["per_core_percent"] == [50, 0]
    assert sample["cpu"]["percent"] == 25
    assert sample["disk"]["rates"]["read_bytes_per_second"] == 2000
    assert sample["disk"]["rates"]["write_bytes_per_second"] == 500
    rows = {row["role"]: row for row in sample["processes"]["items"]}
    assert rows["viewer"]["cpu"]["percent"] == 150
    assert rows["viewer"]["io"]["rates"]["read_bytes_per_second"] == 400
    assert sample["processes"]["totals"] == {
        "sampled_processes": 2,
        "cpu_percent": 200,
        "machine_cpu_percent": 100,
        "rss_bytes": 20000,
        "private_bytes": 16000,
        "complete": True,
    }


def test_counter_resets_and_process_restarts_never_produce_negative_rates(rig):
    collector, provider, clock = rig
    collector.sample()
    clock[0] += 1
    provider.times = [CpuTimes(1, 0, 1, 0, 0, 0)] * 2
    provider.disk.read_bytes = 0
    provider.processes[100].seconds = 0
    provider.processes[100].write_bytes = 0
    sample = collector.sample()
    assert sample["cpu"]["percent"] is None
    assert sample["disk"]["rates"]["status"] == "warming_up"
    assert sample["disk"]["rates"]["write_bytes_per_second"] is None
    assert sample["processes"]["items"][0]["cpu"]["percent"] is None
    assert (
        sample["processes"]["items"][0]["io"]["rates"]["write_bytes_per_second"] is None
    )
    clock[0] += 1
    provider.times = [CpuTimes(1.5, 0, 1.5, 0, 0, 0)] * 2
    provider.disk.read_bytes += 100
    provider.processes[100].seconds += 0.5
    recovered = collector.sample()
    assert recovered["cpu"]["percent"] == 50
    assert recovered["disk"]["rates"]["read_bytes_per_second"] == 100
    assert recovered["processes"]["items"][0]["cpu"]["percent"] == 50


def test_pid_reuse_drops_old_identity_without_reading_replacement(rig):
    collector, provider, clock = rig
    collector.register_process(101, "worker")
    collector.sample()
    old = provider.processes[101]
    replacement = FakeProcess(101, created=99.0)
    provider.processes[101] = replacement
    provider.processes[100].child_processes = []
    clock[0] += 1
    sample = collector.sample()
    rows = {row["pid"]: row for row in sample["processes"]["items"]}
    assert rows[101]["status"] == "exited"
    assert old.read_calls == 1
    assert replacement.read_calls == 0
    assert 101 not in collector._processes
    assert all(row["pid"] != 101 for row in collector.sample()["processes"]["items"])


def test_explicit_registration_of_new_process_resets_old_pid_baselines(rig):
    collector, provider, clock = rig
    collector.register_process(101, "worker")
    collector.sample()
    provider.processes[101] = FakeProcess(101, created=99.0)
    provider.processes[101].parent_process = provider.processes[100]
    collector.register_process(101, "preparation")
    clock[0] += 1
    sample = collector.sample()
    row = next(row for row in sample["processes"]["items"] if row["pid"] == 101)
    assert row["role"] == "preparation"
    assert row["created_at_unix"] == 99
    assert row["cpu"]["percent"] is None
    assert row["io"]["rates"]["read_bytes_per_second"] is None


def test_exited_launcher_does_not_adopt_unrelated_recycled_tree(rig):
    collector, provider, _ = rig
    original = provider.processes[100]
    original.running = False
    unrelated = FakeProcess(900)
    provider.processes[100] = FakeProcess(100, created=999)
    provider.processes[100].child_processes = [unrelated]
    sample = collector.sample()
    assert sample["processes"]["items"][0]["status"] == "exited"
    assert unrelated.read_calls == 0
    assert sample["processes"]["discovery"]["status"] == "unavailable"


def test_access_denied_to_one_process_keeps_other_providers_and_redacts_errors(rig):
    collector, provider, clock = rig
    collector.sample()
    provider.processes[101].denied_memory = True
    clock[0] += 1
    sample = collector.sample()
    assert sample["processes"]["status"] == "partial"
    assert sample["processes"]["totals"]["rss_bytes"] is None
    assert sample["memory"]["status"] == "ok"
    assert sample["gpu"]["status"] == "ok"
    assert "AccessDenied" in json.dumps(sample)
    assert "private-user-name" not in json.dumps(sample)
    assert "secret-path" not in json.dumps(sample)


def test_missing_psutil_keeps_static_inventory_gpu_and_explicit_missing_readings(
    monkeypatch, tmp_path
):
    def missing(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(hardware.importlib, "import_module", missing)
    monkeypatch.setattr(hardware, "NvidiaCollector", FakeGpu)
    collector = HardwareCollector(100, tmp_path)
    inventory = collector.inventory()
    assert inventory["cpu"]["logical_cores"]
    assert inventory["memory_total_bytes"] is None
    assert inventory["providers"]["psutil"]["status"] == "unavailable"
    sample = collector.sample()
    assert sample["cpu"]["percent"] is None
    assert sample["memory"]["total_bytes"] is None
    assert sample["processes"]["items"] == []
    assert sample["processes"]["totals"] is None
    assert sample["gpu"]["status"] == "ok"


def test_disk_provider_failure_resets_baseline_without_breaking_other_metrics(
    rig, monkeypatch
):
    collector, provider, clock = rig
    collector.sample()
    original = provider.disk_io_counters

    def denied(**kwargs):
        raise AccessDenied("private-volume-name")

    monkeypatch.setattr(provider, "disk_io_counters", denied)
    clock[0] += 1
    result = collector.sample()
    assert result["disk"]["counters"]["status"] == "unavailable"
    assert result["disk"]["rates"]["read_bytes_per_second"] is None
    assert result["memory"]["status"] == "ok"
    assert "private-volume-name" not in json.dumps(result)
    monkeypatch.setattr(provider, "disk_io_counters", original)
    clock[0] += 1
    assert collector.sample()["disk"]["rates"]["status"] == "warming_up"


def test_sensor_values_and_missing_private_memory_are_explicit(rig, monkeypatch):
    collector, provider, _ = rig
    monkeypatch.setattr(
        provider,
        "sensors_temperatures",
        lambda: {"cpu": [SimpleNamespace(current=50, high=90, critical=100)]},
        raising=False,
    )
    monkeypatch.setattr(
        provider,
        "sensors_fans",
        lambda: {"fan": [SimpleNamespace(current=1200)]},
        raising=False,
    )
    monkeypatch.setattr(
        provider,
        "sensors_battery",
        lambda: SimpleNamespace(percent=75, secsleft=-1, power_plugged=True),
    )
    monkeypatch.setattr(
        provider.processes[100],
        "memory_info",
        lambda: SimpleNamespace(rss=100, vms=200),
    )
    sample = collector.sample()
    assert sample["sensors"]["temperatures"]["items"][0]["current_c"] == 50
    assert sample["sensors"]["fans"]["items"][0]["rpm"] == 1200
    assert sample["sensors"]["battery"]["seconds_left"] is None
    assert sample["sensors"]["battery"]["power_plugged"] is True
    assert sample["processes"]["items"][0]["memory"]["private_bytes"] is None
    assert sample["processes"]["totals"]["private_bytes"] is None


def test_missing_and_failing_gpu_providers_do_not_disable_cpu_memory(rig, monkeypatch):
    collector, _, _ = rig

    def broken():
        raise RuntimeError("machine-secret")

    monkeypatch.setattr(collector._gpu, "inventory", broken)
    monkeypatch.setattr(collector._gpu, "sample", broken)
    assert collector.inventory()["gpu"]["reason"] == "RuntimeError"
    sample = collector.sample()
    assert sample["gpu"]["status"] == "unavailable"
    assert sample["memory"]["status"] == "ok"
    assert "machine-secret" not in json.dumps(sample)


def test_unavailable_registration_is_reported_once_without_scanning_process_list(rig):
    collector, _, _ = rig
    collector.register_process(500, "worker")
    sample = collector.sample()
    row = next(row for row in sample["processes"]["items"] if row["pid"] == 500)
    assert row["reason"] == "NoSuchProcess"
    assert "user-secret" not in json.dumps(sample)
    assert all(row["pid"] != 500 for row in collector.sample()["processes"]["items"])


def test_close_is_idempotent_and_disables_future_collection(rig):
    collector, _, _ = rig
    collector.close()
    collector.close()
    collector.register_process(101, "viewer")
    assert collector.sample()["status"] == "closed"
    assert collector._gpu.closed == 1
    assert not collector._processes


def test_windows_cpu_total_does_not_count_interrupt_or_dpc_twice():
    WindowsTimes = namedtuple("WindowsTimes", "user system idle interrupt dpc")
    before = hardware._cpu_counts(WindowsTimes(10, 10, 80, 3, 2))
    after = hardware._cpu_counts(WindowsTimes(10, 11, 81, 3.5, 2.5))
    assert hardware._cpu_percent(before, after) == 50


def test_more_than_64_cores_retains_full_aggregate_and_reports_omitted_detail(rig):
    collector, provider, _ = rig
    provider.times = [CpuTimes(0, 0, 0, 0, 0, 0)] * 128
    first = collector.sample()
    assert len(first["cpu"]["per_core_percent"]) == 64
    assert first["cpu"]["logical_cores_observed"] == 128
    assert first["cpu"]["per_core_omitted"] == 64
    provider.times = [CpuTimes(1, 0, 0, 0, 0, 0)] * 64 + [
        CpuTimes(0, 0, 1, 0, 0, 0)
    ] * 64
    result = collector.sample()
    assert result["cpu"]["percent"] == 50
    assert result["cpu"]["per_core_percent"] == [100] * 64


def test_delayed_registration_rejects_unrelated_recycled_pid(rig):
    collector, provider, _ = rig
    unrelated = FakeProcess(500, created=99)
    provider.processes[500] = unrelated
    collector.register_process(500, "viewer")
    result = collector.sample()
    row = next(row for row in result["processes"]["items"] if row["pid"] == 500)
    assert row["reason"] == "Launcher ancestry not verified"
    assert unrelated.read_calls == 0
    assert 500 not in collector._processes


def test_registration_rejects_descendant_of_recycled_root(rig):
    collector, provider, _ = rig
    recycled_root = FakeProcess(100, created=999)
    provider.processes[100] = recycled_root
    child = FakeProcess(500)
    child.parent_process = recycled_root
    provider.processes[500] = child
    collector.register_process(500, "viewer")
    collector.register_process(100, "launcher")
    assert 500 not in collector._processes
    assert collector._processes[100].created == 10


def test_individual_cpu_counter_reset_is_not_hidden_by_other_increases(rig):
    collector, provider, _ = rig
    collector.sample()
    provider.times = [CpuTimes(9, 7, 81, 5, 2, 0)] * 2
    result = collector.sample()
    assert result["cpu"]["percent"] is None
    assert result["cpu"]["status"] == "warming_up"


def test_process_detail_limit_accounts_for_failed_registrations(rig):
    collector, _, _ = rig
    for pid in range(200, 264):
        collector.register_process(pid, "worker")
    result = collector.sample()["processes"]
    assert len(result["items"]) == hardware.MAX_PROCESSES
    assert result["items_omitted"] == 2
    assert result["totals"]["complete"] is False
