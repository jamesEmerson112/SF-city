"""The loading window stays closable before the simulation is available."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from civic_center import launch


def _launcher_fixture(tmp_path, monkeypatch):
    viewer = tmp_path / "viewer"
    (viewer / "assets").mkdir(parents=True)
    (viewer / "project.godot").touch()
    (viewer / "assets/civic-center.glb").touch()
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    monkeypatch.setattr(launch, "VIEWER", viewer)
    monkeypatch.setattr(launch, "find_godot", lambda: "test-godot")


def test_closing_loading_window_does_not_start_a_worker(tmp_path, monkeypatch):
    _launcher_fixture(tmp_path, monkeypatch)
    commands = []

    class ClosedViewer:
        returncode = 0

        def poll(self):
            return 0

    def start(command, **kwargs):
        commands.append(command)
        return ClosedViewer()

    monkeypatch.setattr(launch.subprocess, "Popen", start)
    assert (
        launch.main(["--world", "pilot", "--no-geography", "--no-hardware-monitor"])
        == 0
    )
    assert len(commands) == 1
    assert commands[0][0] == "test-godot"
    assert not list((tmp_path / ".cache").glob("startup-*.json"))


def test_startup_error_reaches_loading_window(tmp_path, monkeypatch):
    _launcher_fixture(tmp_path, monkeypatch)
    received = []

    class LoadingViewer:
        returncode = 0

        def __init__(self, command):
            self.path = Path(command[command.index("--startup-file") + 1])

        def poll(self):
            status = json.loads(self.path.read_text())
            if status["status"] == "error":
                received.append(status)
                return 0
            return None

    monkeypatch.setattr(
        launch.subprocess, "Popen", lambda command, **kwargs: LoadingViewer(command)
    )
    missing = tmp_path / "missing-geography.json"
    assert launch.main(["--geography", str(missing), "--no-hardware-monitor"]) == 1
    assert received[0]["schema_version"] == 1
    assert "Geography manifest not found" in received[0]["message"]
    assert "arguments" not in received[0]


def test_worker_readiness_can_be_cancelled_before_timeout():
    worker = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        started = time.monotonic()
        with pytest.raises(launch._LaunchCancelled):
            launch._read_ready(worker, 20, cancelled=lambda: True)
        assert time.monotonic() - started < 2
    finally:
        launch._terminate_tree(worker)
        worker.stdout.close()


def test_closing_loading_window_terminates_preparation_child(tmp_path, monkeypatch):
    actual_start = subprocess.Popen
    children = []

    def start(command, **kwargs):
        child = actual_start(
            [sys.executable, "-u", "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(child)
        return child

    class ClosedViewer:
        def poll(self):
            return 0

    monkeypatch.setattr(launch.subprocess, "Popen", start)
    started = time.monotonic()
    with pytest.raises(launch._LaunchCancelled):
        launch._prepare_with_viewer(
            ClosedViewer(),
            tmp_path / "startup.json",
            tmp_path / "geography.json",
            None,
            200,
            7,
            None,
            20,
        )
    assert time.monotonic() - started < 5
    assert children and children[0].poll() is not None
    assert not (tmp_path / "startup.request.json").exists()
    assert not (tmp_path / "startup.result.json").exists()
