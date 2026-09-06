"""Keep presentation mode selection separate from the simulation worker."""

import io
import json
from pathlib import Path

import pytest
from civic_center import launch


@pytest.mark.parametrize("mode", ["overhead", "walk", "follow", "map"])
@pytest.mark.parametrize("replay", [False, True])
def test_launch_forwards_view_mode_for_live_and_replay(
    tmp_path, monkeypatch, mode, replay
):
    viewer = tmp_path / "viewer"
    assets = viewer / "assets"
    assets.mkdir(parents=True)
    (viewer / "project.godot").touch()
    (assets / "civic-center.glb").touch()
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    monkeypatch.setattr(launch, "VIEWER", viewer)
    monkeypatch.setattr(launch, "find_godot", lambda: "test-godot")
    commands = []

    handoff = {}

    class CompletedProcess:
        returncode = 0

        def __init__(self):
            self.stdout = io.StringIO(
                json.dumps({"type": "ready", "port": 12345}) + "\n"
            )

        def poll(self):
            return self.returncode

    class ViewerProcess(CompletedProcess):
        def __init__(self, command):
            super().__init__()
            self.status_path = (
                Path(command[command.index("--startup-file") + 1])
                if "--startup-file" in command
                else None
            )

        def poll(self):
            if self.status_path is None:
                return 0
            status = json.loads(self.status_path.read_text())
            if status["status"] == "ready":
                handoff.update(status)
                return 0
            return None

    def start_process(command, **kwargs):
        commands.append(command)
        return (
            ViewerProcess(command) if command[0] == "test-godot" else CompletedProcess()
        )

    monkeypatch.setattr(launch.subprocess, "Popen", start_process)
    args = [
        "--world",
        "pilot",
        "--no-geography",
        "--mode",
        mode,
        "--no-hardware-monitor",
    ]
    if replay:
        recording = tmp_path / "recorded-day.json"
        recording.touch()
        args.extend(["--replay", str(recording)])

    assert launch.main(args) == 0
    assert len(commands) == (1 if replay else 2)
    viewer_command = next(command for command in commands if command[0] == "test-godot")
    options = viewer_command[viewer_command.index("--") + 1 :]
    assert options[options.index("--mode") + 1] == mode
    if replay:
        assert options[options.index("--replay") + 1] == str(recording.resolve())
    else:
        assert (
            commands[0][0] == "test-godot"
        ), "Loading window must precede worker startup"
        assert "--startup-file" in viewer_command
        assert not Path(
            viewer_command[viewer_command.index("--startup-file") + 1]
        ).exists()
        options = handoff["arguments"]
        worker_command = commands[1]
        assert "civic_center.worker" in worker_command
        assert "--mode" not in worker_command
        assert options[options.index("--port") + 1] == "12345"
