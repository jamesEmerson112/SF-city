"""Every launcher attempt keeps a useful diagnostic record after cleanup."""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pytest

from civic_center import launch

TOKEN = "run-log-test-private-connection-token"


def _fake_hardware_monitor(monkeypatch):
    """All launcher unit tests use deterministic telemetry, never real drivers."""

    class Monitor:
        instances = []

        def __init__(self, log, root_pid, data_path, *, interval_seconds=1.0):
            self.log = log
            self.root_pid = root_pid
            self.data_path = data_path
            self.interval_seconds = interval_seconds
            self.started = False
            self.stopped = False
            self.registrations = []
            self.instances.append(self)

        def start(self):
            self.started = True
            self.log.hardware_inventory({"cpu": {"model": "fake CPU"}})
            self.log.hardware_sample({"cpu": {"percent": 12.5}})

        def register_process(self, pid, role):
            self.registrations.append((pid, role))

        def stop(self, timeout=2.0):
            record = json.loads(self.log.path.read_text(encoding="utf-8"))
            assert record["ended_at"] is None, "Stop telemetry before sealing the log"
            self.stopped = True
            self.log.hardware_sample({"cpu": {"percent": 25.0}})
            self.log.hardware_status("stopped")

    monkeypatch.setattr(launch, "HardwareMonitor", Monitor)
    return Monitor


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    _fake_hardware_monitor(monkeypatch)
    viewer = tmp_path / "viewer"
    (viewer / "assets").mkdir(parents=True)
    (viewer / "project.godot").touch()
    (viewer / "assets/civic-center.glb").touch()
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    monkeypatch.setattr(launch, "VIEWER", viewer)
    monkeypatch.setattr(launch, "find_godot", lambda: "test-godot")
    monkeypatch.setattr(launch.secrets, "token_urlsafe", lambda _: TOKEN)
    return tmp_path


def _read_logs(root: Path, directory: Path | None = None) -> list[dict]:
    directory = directory or root / ".local/civic/logs"
    files = list(directory.glob("*.json"))
    assert files, "The launcher must leave a JSON record even after early failure"
    records = []
    for path in files:
        serialized = path.read_text(encoding="utf-8")
        assert TOKEN not in serialized
        record = json.loads(serialized)
        assert record["schema_version"] == 1
        assert record["duration_seconds"] >= 0
        started = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(record["ended_at"].replace("Z", "+00:00"))
        assert started.utcoffset() is not None
        assert ended.utcoffset() is not None
        assert ended >= started
        records.append(record)
    return records


def _install_processes(
    monkeypatch,
    *,
    output: str = "",
    exit_code: int = 0,
    close_during_loading: bool = False,
):
    """Model the real loading handoff without launching a window or worker."""
    commands = []
    handoffs = []

    class Worker:
        returncode = 0
        pid = 10002

        def __init__(self):
            self.stdout = io.StringIO(
                json.dumps({"type": "ready", "port": 12345}) + "\n"
            )

        def poll(self):
            return self.returncode

    class Viewer:
        pid = 10001

        def __init__(self, command):
            self.stdout = io.StringIO(output)
            self.returncode = None
            self.path = (
                Path(command[command.index("--startup-file") + 1])
                if "--startup-file" in command
                else None
            )

        def poll(self):
            if self.returncode is not None:
                return self.returncode
            if self.path is None or close_during_loading:
                self.returncode = exit_code
            else:
                status = json.loads(self.path.read_text(encoding="utf-8"))
                if status["status"] in ("ready", "error"):
                    handoffs.append(status)
                    self.returncode = exit_code
            return self.returncode

    def start(command, **kwargs):
        commands.append(command)
        return Viewer(command) if command[0] == "test-godot" else Worker()

    monkeypatch.setattr(launch.subprocess, "Popen", start)
    return commands, handoffs


def test_missing_godot_leaves_a_failed_run_record(launcher, monkeypatch):
    def missing_godot():
        raise RuntimeError("Godot 4 was not found")

    def unexpected_process(*args, **kwargs):
        pytest.fail("Missing Godot must fail before creating any child process")

    monkeypatch.setattr(launch, "find_godot", missing_godot)
    monkeypatch.setattr(launch.subprocess, "Popen", unexpected_process)
    assert launch.main(["--world", "pilot", "--no-geography"]) == 1
    records = _read_logs(launcher)
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert records[0]["exit_code"] == 1
    assert "Godot 4 was not found" in json.dumps(records[0])


def test_invalid_geography_log_survives_error_handoff_cleanup(launcher, monkeypatch):
    commands, handoffs = _install_processes(monkeypatch)
    missing = launcher / "missing-geography.json"
    assert launch.main(["--geography", str(missing)]) == 1
    assert len(commands) == 1
    assert handoffs[-1]["status"] == "error"
    assert not list((launcher / ".cache").glob("startup-*.json"))
    records = _read_logs(launcher)
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert records[0]["exit_code"] == 1
    assert "Geography manifest not found" in json.dumps(records[0])


def test_closing_loading_window_records_cancellation(launcher, monkeypatch):
    commands, _ = _install_processes(monkeypatch, close_during_loading=True)
    assert launch.main(["--world", "pilot", "--no-geography"]) == 0
    assert len(commands) == 1, "Closing the loading window must not start a worker"
    records = _read_logs(launcher)
    assert len(records) == 1
    assert records[0]["status"] == "cancelled"
    assert records[0]["exit_code"] == 0
    assert not list((launcher / ".cache").glob("startup-*.json"))


@pytest.mark.parametrize("replay", [False, True])
def test_successful_live_and_replay_runs_capture_settings_and_loading(
    launcher, monkeypatch, replay
):
    startup = {"complete": True, "usable_ms": 321.5}
    metrics = {
        "schema_version": 1,
        "final": True,
        "startup": startup,
        "performance": {
            "samples": 12,
            "p95_ms": 18.25,
            "scenery_cache": {
                "geography": {"hits": 7, "misses": 0},
                "terrain": {"hits": 11, "misses": 1},
            },
        },
        "simulation": {"ready": True, "resident_count": 1, "tick": 42},
        "presentation": {"mode": "map", "rendering_3d": False},
        "error": "",
    }
    output = (
        "GODOT_APPLICATION_STARTUP_COMPLETE "
        + json.dumps(startup)
        + "\nGODOT_APPLICATION_RUN_METRICS "
        + json.dumps(metrics)
        + "\n"
    )
    _install_processes(monkeypatch, output=output)
    args = [
        "--world",
        "pilot",
        "--no-geography",
        "--population",
        "1",
        "--mode",
        "map",
        "--headless",
    ]
    if replay:
        recording = launcher / "recording.json"
        recording.write_text("{}", encoding="utf-8")
        args.extend(["--replay", str(recording)])
    assert launch.main(args) == 0
    records = _read_logs(launcher)
    assert len(records) == 1
    record = records[0]
    assert record["status"] == "completed"
    assert record["exit_code"] == 0
    assert record["settings"]["world"] == "pilot"
    assert record["settings"]["mode"] == "map"
    assert record["settings"]["population"] == 1
    assert record["settings"]["headless"] is True
    assert record["metrics"]["startup"]["usable_ms"] == 321.5
    runtime = record["metrics"]["runtime"]
    assert runtime["final"] is True, "Drain the final viewer report before finishing"
    assert runtime["performance"]["scenery_cache"]["geography"]["hits"] == 7
    assert runtime["performance"]["scenery_cache"]["terrain"]["misses"] == 1
    assert runtime["simulation"]["tick"] == 42


def test_nonzero_viewer_exit_is_failed_even_without_an_error_marker(
    launcher, monkeypatch
):
    _install_processes(
        monkeypatch,
        output='GODOT_APPLICATION_STARTUP_COMPLETE {"complete":true}\n',
        exit_code=17,
    )
    assert launch.main(["--world", "pilot", "--no-geography"]) == 17
    record = _read_logs(launcher)[0]
    assert record["status"] == "failed"
    assert record["exit_code"] == 17


def test_keyboard_interrupt_records_interrupted_exit(launcher, monkeypatch):
    def interrupted_godot_lookup():
        raise KeyboardInterrupt

    monkeypatch.setattr(launch, "find_godot", interrupted_godot_lookup)
    assert launch.main(["--world", "pilot", "--no-geography"]) == 130
    record = _read_logs(launcher)[0]
    assert record["status"] == "interrupted"
    assert record["exit_code"] == 130


def test_custom_log_directory_keeps_a_separate_json_for_each_launch(
    launcher, monkeypatch
):
    directory = launcher / "session diagnostics"
    _install_processes(monkeypatch, close_during_loading=True)
    args = ["--world", "pilot", "--no-geography", "--log-dir", str(directory)]
    assert launch.main(args) == 0
    assert launch.main(args) == 0
    records = _read_logs(launcher, directory)
    assert len(records) == 2
    assert all(record["status"] == "cancelled" for record in records)
    assert not list((launcher / ".local/civic/logs").glob("*.json"))


def test_launcher_exception_redacts_connection_token(launcher, monkeypatch):
    def failing_lookup():
        raise RuntimeError(f"Could not launch using token {TOKEN}")

    monkeypatch.setattr(launch, "find_godot", failing_lookup)
    assert launch.main(["--world", "pilot", "--no-geography"]) == 1
    record = _read_logs(launcher)[0]
    assert record["status"] == "failed"
    assert "Could not launch" in json.dumps(record)


@pytest.mark.parametrize(
    ("diagnostic", "status"),
    [
        ("ERROR: Could not read the native root certificate store", "completed"),
        ("SCRIPT ERROR: Invalid call in the city renderer", "failed"),
        ("GODOT_APPLICATION_FAIL city renderer failed", "failed"),
    ],
)
def test_viewer_diagnostics_distinguish_script_failures_from_native_warnings(
    launcher, monkeypatch, diagnostic, status
):
    output = 'GODOT_APPLICATION_STARTUP_COMPLETE {"complete":true}\n' f"{diagnostic}\n"
    _install_processes(monkeypatch, output=output)
    launch.main(["--world", "pilot", "--no-geography"])
    record = _read_logs(launcher)[0]
    assert record["status"] == status
    assert diagnostic.removeprefix("GODOT_APPLICATION_FAIL ") in json.dumps(record)


@pytest.mark.parametrize("replay", [False, True])
def test_hardware_monitor_starts_before_lookup_and_stops_before_final_log(
    launcher, monkeypatch, replay
):
    monitor_class = launch.HardwareMonitor

    def lookup():
        assert len(monitor_class.instances) == 1
        assert monitor_class.instances[0].started
        return "test-godot"

    monkeypatch.setattr(launch, "find_godot", lookup)
    _install_processes(
        monkeypatch,
        output='GODOT_APPLICATION_STARTUP_COMPLETE {"complete":true}\n',
    )
    args = ["--world", "pilot", "--no-geography", "--hardware-interval", "0.5"]
    if replay:
        recording = launcher / "recording.json"
        recording.write_text("{}", encoding="utf-8")
        args.extend(["--replay", str(recording)])
    assert launch.main(args) == 0
    monitor = monitor_class.instances[0]
    assert monitor.stopped
    assert monitor.interval_seconds == 0.5
    assert monitor.root_pid > 0
    assert monitor.data_path == launcher
    assert (10001, "viewer") in monitor.registrations
    assert ((10002, "worker") in monitor.registrations) is not replay
    record = _read_logs(launcher)[0]
    assert record["status"] == "completed"
    assert record["hardware"]["enabled"] is True
    assert record["hardware"]["status"] == "stopped"
    assert record["hardware"]["samples_recorded"] == 2
    assert record["hardware"]["summary"]["cpu.percent"]["max"] == 25.0


def test_hardware_monitor_can_be_disabled_without_initializing_sensors(
    launcher, monkeypatch
):
    monitor_class = launch.HardwareMonitor
    _install_processes(monkeypatch, close_during_loading=True)
    assert (
        launch.main(["--world", "pilot", "--no-geography", "--no-hardware-monitor"])
        == 0
    )
    assert monitor_class.instances == []
    hardware = _read_logs(launcher)[0]["hardware"]
    assert hardware["enabled"] is False
    assert hardware["status"] == "disabled"
    assert hardware["samples_recorded"] == 0


@pytest.mark.parametrize(
    ("failure", "status", "exit_code"),
    [
        (RuntimeError("Godot is unavailable"), "failed", 1),
        (KeyboardInterrupt(), "interrupted", 130),
    ],
)
def test_hardware_monitor_stops_when_startup_lookup_fails(
    launcher, monkeypatch, failure, status, exit_code
):
    monitor_class = launch.HardwareMonitor

    def fail_lookup():
        assert monitor_class.instances[0].started
        raise failure

    monkeypatch.setattr(launch, "find_godot", fail_lookup)
    assert launch.main(["--world", "pilot", "--no-geography"]) == exit_code
    assert monitor_class.instances[0].stopped
    record = _read_logs(launcher)[0]
    assert record["status"] == status
    assert record["exit_code"] == exit_code
    assert record["hardware"]["status"] == "stopped"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "0.1", "61"])
def test_invalid_hardware_interval_fails_before_starting_a_run(launcher, value):
    monitor_class = launch.HardwareMonitor
    with pytest.raises(SystemExit) as error:
        launch.main(["--hardware-interval", value])
    assert error.value.code == 2
    assert monitor_class.instances == []
    assert not list((launcher / ".local/civic/logs").glob("*.json"))


def test_worker_token_starting_with_dash_remains_one_argument_and_is_redacted(
    launcher, monkeypatch
):
    token = "-leading-dash-test-connection-token"
    monkeypatch.setattr(launch.secrets, "token_urlsafe", lambda _: token)
    commands, _ = _install_processes(
        monkeypatch,
        output='GODOT_APPLICATION_STARTUP_COMPLETE {"complete":true}\n',
    )
    assert launch.main(["--world", "pilot", "--no-geography"]) == 0
    worker_command = next(
        command for command in commands if "civic_center.worker" in command
    )
    assert f"--token={token}" in worker_command
    assert "--token" not in worker_command
    assert token not in worker_command
    record = _read_logs(launcher)[0]
    assert record["status"] == "completed"
    assert record["exit_code"] == 0
    assert token not in json.dumps(record)
