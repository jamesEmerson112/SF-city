"""Hardware telemetry remains optional and cannot hold application shutdown."""

from __future__ import annotations

import json
import threading
import time

import pytest

from civic_center.hardware_monitor import HardwareMonitor
from civic_center.run_log import RunLog


def _read(log):
    return json.loads(log.path.read_text(encoding="utf-8"))


def _sample_event(log, monkeypatch):
    published = threading.Event()
    original = log.hardware_sample

    def receive(sample):
        original(sample)
        published.set()

    monkeypatch.setattr(log, "hardware_sample", receive)
    return published


class Collector:
    def __init__(self):
        self.registrations = []
        self.worker_registered = threading.Event()
        self.closed = threading.Event()

    def inventory(self):
        return {"cpu": {"logical_count": 8}, "gpu": {"status": "unavailable"}}

    def sample(self):
        return {"cpu": {"percent": 12.5}, "gpu": {"status": "unavailable"}}

    def register_process(self, pid, role):
        self.registrations.append((pid, role))
        if role == "worker":
            self.worker_registered.set()

    def close(self):
        self.closed.set()


def test_sensor_collection_runs_off_launcher_thread_and_tracks_registered_processes(
    tmp_path, monkeypatch
):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.update(status="loading")
    published = _sample_event(log, monkeypatch)
    collector = Collector()
    calls = []

    def factory(root_pid, data_path):
        calls.append((threading.get_ident(), root_pid, data_path))
        return collector

    monitor = HardwareMonitor(
        log, 123, tmp_path, interval_seconds=0.05, collector_factory=factory
    )
    assert (
        calls == []
    ), "Construction must not initialize drivers on the launcher thread"
    for invalid in (None, 0, -1, True):
        monitor.register_process(invalid, "invalid")
    monitor.register_process(101, "viewer")
    monitor.start()
    try:
        assert published.wait(2), "A loading run should receive hardware samples"
        monitor.register_process(202, "worker")
        assert collector.worker_registered.wait(2)
    finally:
        monitor.stop()
    log.finish("completed", 0)
    assert calls == [(calls[0][0], 123, tmp_path)]
    assert calls[0][0] != threading.get_ident()
    assert collector.registrations == [(101, "viewer"), (202, "worker")]
    assert collector.closed.is_set()
    hardware = _read(log)["hardware"]
    assert hardware["status"] == "stopped"
    assert hardware["samples_recorded"] >= 1
    assert hardware["samples"][0]["context"]["run_status"] == "loading"
    first = hardware["samples"][0]
    assert first["collection_ms"] >= 0
    assert (
        first["collected_monotonic_seconds"]
        >= first["collection_started_monotonic_seconds"]
    )
    assert first["collected_at_unix"] > 0
    assert first["collection_delivery_ms"] >= 0
    assert first["context"]["phase_mixed"] is True
    assert hardware["inventory"]["gpu"]["status"] == "unavailable"
    assert not log.has_errors


def test_missing_collector_dependency_is_nonfatal(tmp_path, monkeypatch):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    unavailable = threading.Event()
    original = log.hardware_status

    def status(value, reason=None):
        original(value, reason)
        if value == "unavailable":
            unavailable.set()

    monkeypatch.setattr(log, "hardware_status", status)

    def factory(root_pid, data_path):
        raise ImportError("optional sensor module is not installed")

    monitor = HardwareMonitor(log, 123, tmp_path, collector_factory=factory)
    monitor.start()
    try:
        assert unavailable.wait(2)
    finally:
        monitor.stop()
    log.finish("completed", 0)
    record = _read(log)
    assert record["status"] == "completed"
    assert record["hardware"]["status"] == "unavailable"
    assert "not installed" in record["hardware"]["reason"]
    assert record["hardware"]["samples_recorded"] == 0
    assert not log.has_errors


def test_transient_sensor_error_does_not_prevent_later_samples(tmp_path, monkeypatch):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    published = _sample_event(log, monkeypatch)

    class IntermittentCollector(Collector):
        attempts = 0

        def sample(self):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("sensor temporarily unavailable")
            return super().sample()

    collector = IntermittentCollector()
    monitor = HardwareMonitor(
        log,
        123,
        tmp_path,
        interval_seconds=0.05,
        collector_factory=lambda *args: collector,
    )
    monitor.start()
    try:
        assert published.wait(2)
    finally:
        monitor.stop()
    log.finish("completed", 0)
    hardware = _read(log)["hardware"]
    assert hardware["samples_recorded"] >= 1
    assert hardware["error_count"] == 1
    assert "temporarily unavailable" in hardware["errors"][0]["message"]
    assert not log.has_errors


def test_persistent_sensor_failure_stops_monitor_without_failing_run(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)

    class FailedCollector(Collector):
        def sample(self):
            raise OSError("sensor is unavailable")

    collector = FailedCollector()
    monitor = HardwareMonitor(
        log,
        123,
        tmp_path,
        interval_seconds=0.05,
        collector_factory=lambda *args: collector,
    )
    monitor.start()
    try:
        assert collector.closed.wait(2)
    finally:
        monitor.stop()
    log.finish("completed", 0)
    hardware = _read(log)["hardware"]
    assert hardware["status"] == "unavailable"
    assert hardware["error_count"] == 3
    assert hardware["samples_recorded"] == 0
    assert not log.has_errors


@pytest.mark.parametrize("blocked_stage", ["factory", "inventory", "sample"])
def test_blocking_sensor_does_not_hold_shutdown_or_publish_late_results(
    tmp_path, blocked_stage
):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    entered = threading.Event()
    release = threading.Event()

    def block():
        entered.set()
        assert release.wait(3)

    class BlockedCollector(Collector):
        def inventory(self):
            if blocked_stage == "inventory":
                block()
            return super().inventory()

        def sample(self):
            if blocked_stage == "sample":
                block()
            return super().sample()

    collector = BlockedCollector()

    def factory(root_pid, data_path):
        if blocked_stage == "factory":
            block()
        return collector

    monitor = HardwareMonitor(log, 123, tmp_path, collector_factory=factory)
    monitor.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        monitor.stop(timeout=0.05)
        assert time.monotonic() - started < 0.5
        assert _read(log)["hardware"]["status"] == "timed_out"
        before = log.path.read_bytes()
        release.set()
        assert collector.closed.wait(2)
        assert log.path.read_bytes() == before, "A stopped monitor published late data"
        log.finish("cancelled", 0)
        assert _read(log)["hardware"]["samples_recorded"] == 0
    finally:
        release.set()
        monitor.stop(timeout=1)


def test_stop_before_start_never_initializes_sensors(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)

    def factory(*args):
        pytest.fail("Stopping before start must prevent sensor initialization")

    monitor = HardwareMonitor(log, 123, tmp_path, collector_factory=factory)
    monitor.stop()
    monitor.start()
    assert _read(log)["hardware"]["samples_recorded"] == 0
