"""Structured launch diagnostics remain bounded, readable, and credential-free."""

import io
import json
import threading
import time
from pathlib import Path

import pytest

from civic_center import run_log
from civic_center.run_log import RunLog


def _read(log: RunLog) -> dict:
    return json.loads(log.path.read_text(encoding="utf-8"))


def test_each_run_gets_its_own_finished_document(tmp_path):
    first = RunLog(tmp_path, {"mode": "map", "scenario": Path("city.json")})
    second = RunLog(tmp_path, {})
    first.event("worker_ready", population=200)
    first.update(status="running", resolved={"scenario": Path("city.json")})
    first.finish("completed", 0)
    record = _read(first)
    assert first.path != second.path
    assert record["run_id"] != _read(second)["run_id"]
    assert record["schema_version"] == 1
    assert record["status"] == "completed"
    assert record["exit_code"] == 0
    assert record["started_at"] <= record["updated_at"]
    assert record["ended_at"] is not None
    assert record["duration_seconds"] >= 0
    assert record["settings"]["scenario"] == "city.json"
    assert record["events"][0]["name"] == "worker_ready"
    assert list(tmp_path.glob("*.tmp")) == []


def test_credentials_are_redacted_recursively_and_private_fields_dropped(tmp_path):
    secret = "very-secret-token"
    log = RunLog(
        tmp_path,
        {
            "mode": "map",
            "token": secret,
            "nested": {
                "access_token": "unknown",
                "environment": {"PASSWORD": "unknown"},
                "arguments": ["--token", "unknown"],
                "authorization": "unknown",
                "label": f"path/{secret}",
            },
        },
        secrets=(secret,),
    )
    log.event("loaded", message=f"Loaded {secret}", raw_arguments=["unknown"])
    log.error(f"Failed {secret}")
    log.finish("failed", 1, worker={"token": secret, "pid": 123})
    encoded = log.path.read_text(encoding="utf-8")
    assert secret not in encoded
    assert "unknown" not in encoded
    assert "[redacted]" in encoded
    assert _read(log)["worker"] == {"pid": 123}


def test_capture_retains_safe_summaries_and_latest_periodic_metrics(tmp_path, capsys):
    log = RunLog(tmp_path, {})
    lines = [
        "Godot Engine v4.test",
        "OpenGL API - GPU: test device",
        'GODOT_APPLICATION_LOADING_VISIBLE {"elapsed_ms": 20}',
        'GODOT_APPLICATION_STARTUP_COMPLETE {"complete": true, "usable_ms": 321}',
        'GODOT_APPLICATION_READY {"resident_count": 200, "sample_resident": {"id": "private-agent", "route": [1, 2]}, "buildings": [{"id":"private-building"}], "frame_profile": {"samples": 2}}',
        'GODOT_APPLICATION_SMOKE_OK {"mode":"map","resident_count":200}',
        'GODOT_APPLICATION_FRAME_PROFILE {"samples": 8, "scenery_cache": {"geography": {"hits": 20}}}',
        'GODOT_APPLICATION_RUN_METRICS {"startup":{"complete":true},"simulation":{"resident_count":200},"performance":{"samples":10}}',
        'GODOT_APPLICATION_RUN_METRICS {"startup":{"complete":true},"simulation":{"resident_count":300},"performance":{"samples":20},"final":true}',
        "GODOT_APPLICATION_SCREENSHOT city.png",
    ]
    reader = log.capture(io.StringIO("\n".join(lines) + "\n"))
    log.close_capture()
    assert not reader.is_alive()
    log.finish("completed", 0)
    record = _read(log)
    assert log.startup_complete
    assert not log.has_errors
    assert record["metrics"]["startup"]["usable_ms"] == 321
    assert record["metrics"]["viewer"] == {"mode": "map", "resident_count": 200}
    assert (
        record["metrics"]["frame_profile"]["scenery_cache"]["geography"]["hits"] == 20
    )
    assert record["metrics"]["runtime"]["simulation"]["resident_count"] == 300
    assert len(record["diagnostics"]["console_tail"]) == 2
    assert record["diagnostics"]["engine"] == "Godot Engine v4.test"
    assert record["diagnostics"]["renderer"] == "OpenGL API - GPU: test device"
    encoded = log.path.read_text(encoding="utf-8")
    assert "private-agent" not in encoded
    assert "private-building" not in encoded
    console = capsys.readouterr().out
    assert "OpenGL API - GPU: test device" in console
    assert "GODOT_APPLICATION_RUN_METRICS" not in console


@pytest.mark.parametrize(
    "line",
    [
        "GODOT_APPLICATION_FAIL Cannot connect",
        "SCRIPT ERROR: Invalid property",
        "Parse Error: Invalid syntax",
        'GODOT_APPLICATION_RUN_METRICS {"error": "Cannot load assets"}',
    ],
)
def test_fatal_viewer_diagnostics_are_reported_even_before_nonzero_exit(tmp_path, line):
    log = RunLog(tmp_path, {})
    log.capture(io.StringIO(line + "\n"))
    log.close_capture()
    assert log.has_errors
    assert _read(log)["diagnostics"]["errors"]


def test_native_godot_warning_is_recorded_without_failing_run(tmp_path):
    log = RunLog(tmp_path, {})
    log.capture(io.StringIO("ERROR: Native certificate store is unavailable\n"))
    log.close_capture()
    assert not log.has_errors
    diagnostic = _read(log)["diagnostics"]["errors"][0]
    assert diagnostic["severity"] == "warning"


def test_events_errors_and_console_lines_remain_bounded(tmp_path, monkeypatch):
    writes = []
    monkeypatch.setattr(
        run_log, "atomic_write", lambda path, payload: writes.append(payload)
    )
    log = RunLog(tmp_path, {})
    for index in range(run_log.MAX_EVENTS + 10):
        log.event("tick", tick=index)
    for index in range(run_log.MAX_ERRORS + 10):
        log.error(f"error {index}")
    log.capture(
        io.StringIO(
            "\n".join(f"line {i}" for i in range(run_log.MAX_CONSOLE_LINES + 10))
        )
    )
    log.close_capture()
    log.finish("failed", 1)
    record = json.loads(writes[-1])
    assert len(record["events"]) == run_log.MAX_EVENTS
    assert len(record["diagnostics"]["errors"]) == run_log.MAX_ERRORS
    assert len(record["diagnostics"]["console_tail"]) == run_log.MAX_CONSOLE_LINES
    assert record["diagnostics"]["event_count"] == run_log.MAX_EVENTS + 11
    assert record["diagnostics"]["error_count"] == run_log.MAX_ERRORS + 10


def test_write_failure_warns_once_and_does_not_disable_error_detection(
    tmp_path, monkeypatch, capsys
):
    calls = []

    def unavailable(path, payload):
        calls.append(path)
        raise OSError("read-only output")

    monkeypatch.setattr(run_log, "atomic_write", unavailable)
    log = RunLog(tmp_path, {})
    log.event("starting")
    log.error("worker failure")
    log.update(status="failed")
    log.finish("failed", 1)
    assert log.disabled
    assert log.has_errors
    assert len(calls) == 1
    assert capsys.readouterr().err.count("run logging unavailable") == 1


def test_malformed_or_oversized_marker_does_not_keep_raw_state(tmp_path, monkeypatch):
    monkeypatch.setattr(run_log, "MAX_LINE", 512)
    log = RunLog(tmp_path, {})
    log.capture(
        io.StringIO(
            "GODOT_APPLICATION_READY {broken\n"
            + 'GODOT_APPLICATION_READY {"residents": "'
            + "private-agent" * 100
            + '"}\n'
            + 'GODOT_APPLICATION_STARTUP_COMPLETE {"complete":true}\n'
        )
    )
    log.close_capture()
    record = _read(log)
    assert log.startup_complete
    assert record["diagnostics"]["malformed_marker_count"] == 2
    assert record["diagnostics"]["truncated_line_count"] == 1
    assert "private-agent" not in log.path.read_text(encoding="utf-8")


def test_output_sink_failure_still_drains_viewer(tmp_path, monkeypatch):
    class BrokenConsole:
        def write(self, value):
            raise OSError("closed console")

    monkeypatch.setattr(run_log.sys, "stdout", BrokenConsole())
    log = RunLog(tmp_path, {})
    reader = log.capture(
        io.StringIO('GODOT_APPLICATION_STARTUP_COMPLETE {"complete":true}\n')
    )
    log.close_capture()
    assert not reader.is_alive()
    assert log.startup_complete


def test_finished_document_is_not_rewritten_by_late_capture(tmp_path):
    log = RunLog(tmp_path, {})
    log.finish("cancelled", 0)
    before = log.path.read_bytes()
    log.capture(io.StringIO("GODOT_APPLICATION_FAIL late buffered error\n"))
    log.close_capture()
    log.update(status="running")
    log.event("late_event")
    assert log.path.read_bytes() == before


def test_atomic_updates_can_be_read_during_background_capture(tmp_path):
    log = RunLog(tmp_path, {})
    failure = []

    def write_events():
        for index in range(25):
            log.event("stage", index=index)

    writer = threading.Thread(target=write_events)
    writer.start()
    while writer.is_alive():
        try:
            record = _read(log)
            assert record["run_id"]
            time.sleep(0.001)
        except PermissionError:
            # Windows replacement can also briefly deny a concurrent open.
            time.sleep(0.001)
        except (OSError, ValueError, AssertionError) as error:
            failure.append(error)
            break
    writer.join()
    assert not failure
    assert len(_read(log)["events"]) == 25


def test_transient_windows_replace_denial_is_retried(tmp_path, monkeypatch):
    original = run_log.atomic_write
    denied = []

    def shared_reader(path, payload):
        if not denied:
            denied.append(True)
            raise PermissionError("temporary file sharing conflict")
        return original(path, payload)

    monkeypatch.setattr(run_log, "atomic_write", shared_reader)
    log = RunLog(tmp_path, {})
    assert not log.disabled
    assert _read(log)["status"] == "starting"


def test_hardware_history_keeps_peaks_after_old_samples_are_evicted(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True, interval_seconds=1.0, history_limit=3)
    log.hardware_inventory({"cpu": {"logical_count": 8}})
    for value in (100.0, 10.0, 20.0, 30.0, 40.0):
        log.hardware_sample({"cpu": {"percent": value}, "collection_ms": 1.5})
    log.finish("completed", 0)
    hardware = _read(log)["hardware"]
    assert hardware["samples_recorded"] == 5
    assert hardware["samples_dropped"] == 2
    assert len(hardware["samples"]) == 3
    assert [sample["cpu"]["percent"] for sample in hardware["samples"]] == [
        20.0,
        30.0,
        40.0,
    ]
    assert hardware["summary"]["cpu.percent"] == {
        "count": 5,
        "min": 10.0,
        "max": 100.0,
        "mean": 40.0,
        "last": 40.0,
    }


def test_hardware_samples_exclude_missing_nonfinite_and_boolean_gauges(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_sample(
        {
            "cpu": {"percent": None},
            "memory": {"used_bytes": 128},
            "temperature_celsius": float("nan"),
            "power_watts": float("inf"),
            "available_percent": False,
            "process_id": 123,
        }
    )
    log.hardware_sample({"cpu": {"percent": 12.5}, "memory": {"used_bytes": None}})
    log.finish("completed", 0)
    hardware = _read(log)["hardware"]
    summary = hardware["summary"]
    assert summary["cpu.percent"]["count"] == 1
    assert summary["cpu.percent"]["mean"] == 12.5
    assert summary["memory.used_bytes"]["count"] == 1
    assert summary["memory.used_bytes"]["last"] == 128
    assert "temperature_celsius" not in summary
    assert "power_watts" not in summary
    assert "available_percent" not in summary
    assert "process_id" not in summary
    assert hardware["samples"][0]["temperature_celsius"] is None


def test_hardware_inventory_and_samples_redact_secrets(tmp_path):
    secret = "hardware-test-private-token"
    log = RunLog(tmp_path, {}, secrets=(secret,))
    log.configure_hardware(True)
    log.hardware_inventory(
        {
            "cpu": {"model": f"device {secret}"},
            "token": "unlisted-private-token",
            "environment": {"PRIVATE_VALUE": "unlisted-private-environment"},
        }
    )
    log.hardware_sample(
        {
            "label": f"sample {secret}",
            "authorization": "unlisted-private-authorization",
            "cpu": {"percent": 5.0},
        }
    )
    log.hardware_warning(f"Sensor unavailable: {secret}")
    encoded = log.path.read_text(encoding="utf-8")
    assert secret not in encoded
    assert "unlisted-private" not in encoded
    assert "[redacted]" in encoded
    assert not log.has_errors


def test_hardware_history_retains_default_capacity_above_generic_list_limit(
    tmp_path, monkeypatch
):
    writes = []
    monkeypatch.setattr(
        run_log, "atomic_write", lambda path, payload: writes.append(payload)
    )
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    for index in range(361):
        log.hardware_sample({"memory": {"used_bytes": index}})
    log.finish("completed", 0)
    record = json.loads(writes[-1])
    hardware = record["hardware"]
    assert hardware["history_limit"] == 360
    assert len(hardware["samples"]) == 360
    assert hardware["samples_recorded"] == 361
    assert hardware["samples_dropped"] == 1
    assert hardware["samples"][0]["memory"]["used_bytes"] == 1
    assert hardware["summary"]["memory.used_bytes"]["count"] == 361
    assert hardware["summary"]["memory.used_bytes"]["min"] == 0
    assert hardware["summary"]["memory.used_bytes"]["max"] == 360


def test_hardware_sampling_during_loading_preserves_collection_timestamps(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.update(status="loading")
    log.hardware_inventory({"cpu": {"logical_count": 8}})
    log.hardware_sample({"cpu": {"percent": 15.0}, "collection_ms": 2.5})
    sample = _read(log)["hardware"]["samples"][0]
    assert sample["at"]
    assert sample["elapsed_seconds"] >= 0
    assert sample["collection_ms"] == 2.5
    assert sample["context"]["run_status"] == "loading"
    log.finish("cancelled", 0)
    assert _read(log)["hardware"]["samples_recorded"] == 1


def test_finished_run_ignores_all_late_hardware_callbacks(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_sample({"cpu": {"percent": 10.0}})
    log.finish("completed", 0)
    before = log.path.read_bytes()
    log.hardware_inventory({"cpu": {"logical_count": 999}})
    log.hardware_sample({"cpu": {"percent": 99.0}})
    log.hardware_status("unavailable", "late sensor exception")
    log.hardware_warning("late warning")
    log.configure_hardware(False)
    assert log.path.read_bytes() == before
    assert not log.has_errors


def test_unwritable_log_does_not_make_hardware_sampling_fatal(tmp_path, monkeypatch):
    def unavailable(path, payload):
        raise OSError("read-only log directory")

    monkeypatch.setattr(run_log, "atomic_write", unavailable)
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_inventory({"cpu": {"logical_count": 8}})
    log.hardware_sample({"cpu": {"percent": 10.0}})
    log.hardware_warning("optional sensor unavailable")
    log.hardware_status("unavailable", "sensors unavailable")
    log.finish("completed", 0)
    assert log.disabled
    assert not log.has_errors


def test_hardware_summary_preserves_process_identity_when_order_changes(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_sample(
        {
            "processes": {
                "items": [
                    {"pid": 101, "cpu": {"percent": 10.0}},
                    {"pid": 202, "cpu": {"percent": 80.0}},
                ]
            }
        }
    )
    log.hardware_sample(
        {
            "processes": {
                "items": [
                    {"pid": 202, "cpu": {"percent": 60.0}},
                    {"pid": 101, "cpu": {"percent": 20.0}},
                ]
            }
        }
    )
    log.finish("completed", 0)
    summary = _read(log)["hardware"]["summary"]
    assert summary["processes.items[101].cpu.percent"]["max"] == 20.0
    assert summary["processes.items[101].cpu.percent"]["mean"] == 15.0
    assert summary["processes.items[202].cpu.percent"]["min"] == 60.0
    assert summary["processes.items[202].cpu.percent"]["mean"] == 70.0


def test_hardware_samples_are_buffered_until_flush_or_finish(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(run_log.time, "monotonic", lambda: now[0])
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_sample({"cpu": {"percent": 10.0}})
    assert _read(log)["hardware"]["samples_recorded"] == 1
    now[0] += 1.0
    log.hardware_sample({"cpu": {"percent": 20.0}})
    assert _read(log)["hardware"]["samples_recorded"] == 1
    now[0] += 5.0
    log.hardware_sample({"cpu": {"percent": 30.0}})
    assert _read(log)["hardware"]["samples_recorded"] == 3
    now[0] += 1.0
    log.hardware_sample({"cpu": {"percent": 40.0}})
    assert _read(log)["hardware"]["samples_recorded"] == 3
    log.finish("completed", 0)
    assert _read(log)["hardware"]["samples_recorded"] == 4


def test_disabled_hardware_log_does_not_accept_sensor_callbacks(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(False)
    log.hardware_inventory({"cpu": {"model": "unexpected device"}})
    log.hardware_sample({"cpu": {"percent": 99.0}})
    log.hardware_warning("unexpected warning")
    log.hardware_status("running")
    log.finish("completed", 0)
    hardware = _read(log)["hardware"]
    assert hardware["enabled"] is False
    assert hardware["status"] == "disabled"
    assert hardware["samples"] == []
    assert hardware["inventory"] == {}
    assert hardware["errors"] == []


def test_hardware_summary_tracks_each_core_without_collapsing_missing_values(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_sample(
        {
            "cpu": {
                "per_core_percent": [None, 50.0, True, float("nan"), 90.0],
                "logical_ids": [0, 1, 2, 3, 4],
            }
        }
    )
    log.hardware_sample(
        {
            "cpu": {
                "per_core_percent": [20.0, 30.0, False, 10.0, None],
                "logical_ids": [0, 1, 2, 3, 4],
            }
        }
    )
    log.finish("completed", 0)
    summary = _read(log)["hardware"]["summary"]
    assert summary["cpu.per_core_percent[0]"]["count"] == 1
    assert summary["cpu.per_core_percent[0]"]["mean"] == 20.0
    assert summary["cpu.per_core_percent[1]"] == {
        "count": 2,
        "min": 30.0,
        "max": 50.0,
        "mean": 40.0,
        "last": 30.0,
    }
    assert "cpu.per_core_percent[2]" not in summary
    assert summary["cpu.per_core_percent[3]"]["count"] == 1
    assert summary["cpu.per_core_percent[3]"]["mean"] == 10.0
    assert summary["cpu.per_core_percent[4]"]["count"] == 1
    assert summary["cpu.per_core_percent[4]"]["max"] == 90.0
    assert not any(key.startswith("cpu.logical_ids") for key in summary)


def test_hardware_temperature_groups_with_same_index_keep_separate_summaries(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    log.hardware_sample(
        {
            "sensors": {
                "temperatures": {
                    "items": [
                        {"group": "chipA", "index": 0, "current_c": 45.0},
                        {"group": "chipB", "index": 0, "current_c": 80.0},
                    ]
                }
            }
        }
    )
    log.hardware_sample(
        {
            "sensors": {
                "temperatures": {
                    "items": [
                        {"group": "chipB", "index": 0, "current_c": 70.0},
                        {"group": "chipA", "index": 0, "current_c": 55.0},
                    ]
                }
            }
        }
    )
    log.finish("completed", 0)
    summary = _read(log)["hardware"]["summary"]
    assert summary["sensors.temperatures.items[chipA:0].current_c"] == {
        "count": 2,
        "min": 45.0,
        "max": 55.0,
        "mean": 50.0,
        "last": 55.0,
    }
    assert summary["sensors.temperatures.items[chipB:0].current_c"] == {
        "count": 2,
        "min": 70.0,
        "max": 80.0,
        "mean": 75.0,
        "last": 70.0,
    }
    assert "sensors.temperatures.items[0].current_c" not in summary


def test_hardware_fan_rpm_is_summarized_with_its_sensor_identity(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    for rpm in (1200.0, 1400.0, None):
        log.hardware_sample(
            {
                "sensors": {
                    "fans": {
                        "items": [
                            {"group": "chassis", "index": 0, "rpm": rpm},
                        ]
                    }
                }
            }
        )
    log.finish("completed", 0)
    summary = _read(log)["hardware"]["summary"]
    assert summary["sensors.fans.items[chassis:0].rpm"] == {
        "count": 2,
        "min": 1200.0,
        "max": 1400.0,
        "mean": 1300.0,
        "last": 1400.0,
    }


def test_hardware_summary_separates_reused_process_ids_by_creation_time(tmp_path):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    for created, percent in ((1.0, 90.0), (2.0, 10.0), (2.0, 30.0)):
        log.hardware_sample(
            {
                "processes": {
                    "items": [
                        {
                            "pid": 123,
                            "created_at_unix": created,
                            "cpu": {"percent": percent},
                        },
                    ]
                }
            }
        )
    log.finish("completed", 0)
    summary = _read(log)["hardware"]["summary"]
    assert summary["processes.items[123@1.0].cpu.percent"] == {
        "count": 1,
        "min": 90.0,
        "max": 90.0,
        "mean": 90.0,
        "last": 90.0,
    }
    assert summary["processes.items[123@2.0].cpu.percent"] == {
        "count": 2,
        "min": 10.0,
        "max": 30.0,
        "mean": 20.0,
        "last": 30.0,
    }
    assert "processes.items[123].cpu.percent" not in summary


def test_incomplete_process_totals_do_not_pollute_available_measurement_summaries(
    tmp_path,
):
    log = RunLog(tmp_path, {})
    log.configure_hardware(True)
    for complete, total_cpu, rss, process_cpu in (
        (False, 80.0, 900, 4.0),
        (True, 10.0, 1000, 10.0),
        (False, 99.0, 9900, 12.0),
    ):
        log.hardware_sample(
            {
                "processes": {
                    "items": [
                        {
                            "pid": 123,
                            "created_at_unix": 1.0,
                            "cpu": {"percent": process_cpu},
                        }
                    ],
                    "totals": {
                        "complete": complete,
                        "cpu_percent": total_cpu,
                        "rss_bytes": rss,
                    },
                }
            }
        )
    log.finish("completed", 0)
    summary = _read(log)["hardware"]["summary"]
    assert summary["processes.totals.cpu_percent"] == {
        "count": 1,
        "min": 10.0,
        "max": 10.0,
        "mean": 10.0,
        "last": 10.0,
    }
    assert summary["processes.totals.rss_bytes"] == {
        "count": 1,
        "min": 1000,
        "max": 1000,
        "mean": 1000.0,
        "last": 1000,
    }
    process = summary["processes.items[123@1.0].cpu.percent"]
    assert process["count"] == 3
    assert process["min"] == 4.0
    assert process["max"] == 12.0
    assert process["mean"] == pytest.approx(26.0 / 3)


def test_live_feed_payloads_are_redacted_and_finished_log_rejects_late_writes(tmp_path):
    class Feed:
        def __init__(self):
            self.rows = []

        def publish(self, kind, payload, source):
            self.rows.append((kind, payload, source))

    feed = Feed()
    log = RunLog(tmp_path, {}, secrets=("private-key",))
    log.configure_hardware(True)
    log.attach_telemetry(feed)
    log.hardware_inventory({"model": "private-key", "auth": "hidden"})
    log.hardware_sample({"cpu": {"percent": 12}, "token": "hidden"})
    log.capture(io.StringIO("WARNING: private-key\n"), source="worker", echo=False)
    log.close_capture()
    log.capture(io.StringIO('GODOT_APPLICATION_COMPARISON_POINT {"mode":"map"}\n'))
    log.close_capture()
    log.finish("completed", 0)
    before = len(feed.rows)
    content = log.path.read_bytes()
    log.hardware_sample({"cpu": {"percent": 99}})
    log.phase({"reason": "late"})
    log.comparison_point({"reason": "late"})
    log.error("late")
    assert len(feed.rows) == before
    assert log.path.read_bytes() == content
    encoded = json.dumps(feed.rows)
    assert "private-key" not in encoded and "hidden" not in encoded
    assert "[redacted]" in encoded
    assert any(kind == "log" and source == "worker" for kind, _, source in feed.rows)
    assert len(_read(log)["experiments"]["comparison_points"]) == 1


def test_failed_live_publisher_does_not_break_archival_logging(tmp_path):
    class FailedFeed:
        def publish(self, *args):
            raise OSError("feed unavailable")

    log = RunLog(tmp_path, {})
    log.attach_telemetry(FailedFeed())
    log.event("still-running")
    log.finish("completed", 0)
    assert _read(log)["status"] == "completed"


def test_matched_command_rejection_is_one_safe_warning_without_error_state(
    tmp_path, capsys
):
    class Feed:
        def __init__(self):
            self.rows = []

        def publish(self, kind, payload, source):
            self.rows.append((kind, payload, source))

    feed = Feed()
    log = RunLog(tmp_path, {}, secrets=("fixture-secret",))
    log.attach_telemetry(feed)
    rejection = {
        "schema_version": 1,
        "request_id": "viewer-4",
        "action": "set_population",
        "code": "invalid_command",
        "message": "Budget exceeded fixture-secret",
        "session_id": "fixture-session",
        "at_unix": 1234.5,
        "token": "not-retained",
        "residents": [{"id": "not-retained"}],
        "environment": {"key": "not-retained"},
    }
    lines = ["GODOT_APPLICATION_COMMAND_REJECTED " + json.dumps(rejection)]
    lines += [
        'GODOT_APPLICATION_RUN_METRICS {"error":"","startup":{"complete":true}}'
    ] * 3
    log.capture(io.StringIO("\n".join(lines) + "\n"))
    log.close_capture()
    assert not log.has_errors
    log.finish("completed", 0)
    record = _read(log)
    assert record["diagnostics"]["error_count"] == 0
    assert record["diagnostics"]["command_rejection_count"] == 1
    events = [
        event for event in record["events"] if event["name"] == "command_rejected"
    ]
    assert len(events) == 1
    assert events[0]["severity"] == "warning"
    assert events[0]["action"] == "set_population"
    assert events[0]["code"] == "invalid_command"
    assert events[0]["message"] == "Budget exceeded [redacted]"
    warnings = [
        payload
        for kind, payload, source in feed.rows
        if kind == "log" and source == "worker"
    ]
    assert len(warnings) == 1 and warnings[0]["severity"] == "warning"
    encoded = json.dumps(record) + json.dumps(feed.rows)
    assert "fixture-secret" not in encoded and "not-retained" not in encoded
    assert "GODOT_APPLICATION_COMMAND_REJECTED" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "fatal",
    [
        "GODOT_APPLICATION_FAIL Budget exceeded",
        "SCRIPT ERROR: Budget exceeded",
        'GODOT_APPLICATION_RUN_METRICS {"error":"Budget exceeded"}',
    ],
)
def test_rejection_warning_never_suppresses_a_real_error_with_the_same_text(
    tmp_path, fatal
):
    log = RunLog(tmp_path, {})
    rejection = {
        "schema_version": 1,
        "request_id": "viewer-4",
        "action": "set_population",
        "code": "invalid_command",
        "message": "Budget exceeded",
    }
    log.capture(
        io.StringIO(
            "GODOT_APPLICATION_COMMAND_REJECTED "
            + json.dumps(rejection)
            + "\n"
            + fatal
            + "\n"
        )
    )
    log.close_capture()
    assert log.has_errors
    assert _read(log)["diagnostics"]["error_count"] > 0


def test_malformed_command_rejection_marker_does_not_persist_arbitrary_payload(
    tmp_path,
):
    log = RunLog(tmp_path, {})
    log.capture(
        io.StringIO(
            'GODOT_APPLICATION_COMMAND_REJECTED {"residents":["private-row"]}\n'
        )
    )
    log.close_capture()
    log.finish("completed", 0)
    record = _read(log)
    assert record["diagnostics"]["malformed_marker_count"] == 1
    assert record["diagnostics"]["command_rejection_count"] == 0
    assert "private-row" not in json.dumps(record)
