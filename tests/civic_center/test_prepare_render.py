"""Keep offline scenery preparation completion and cancellation trustworthy."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import scripts.prepare_sf_render as prepare_render


class _InterruptedOutput(io.StringIO):
    def __next__(self) -> str:
        raise KeyboardInterrupt


class _Process:
    def __init__(
        self, output: str, exit_code: int = 0, interrupt: str | None = None
    ) -> None:
        self.stdout = (
            _InterruptedOutput(output) if interrupt == "read" else io.StringIO(output)
        )
        self.returncode: int | None = None
        self.exit_code = exit_code
        self.interrupt = interrupt

    def wait(self) -> int:
        if self.interrupt == "wait":
            raise KeyboardInterrupt
        self.returncode = self.exit_code
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


@pytest.fixture
def prepared_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "prepared city"
    for relative in (
        ".local/civic/geography/sf-geography.json",
        ".local/civic/terrain/terrain.json",
    ):
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(prepare_render, "ROOT", workspace)
    monkeypatch.setattr(prepare_render, "find_godot", lambda: "test-godot-console.exe")
    return workspace


def _mock_process(
    monkeypatch: pytest.MonkeyPatch, process: _Process
) -> tuple[Mock, Mock]:
    spawn = Mock(return_value=process)

    def terminate(owned: _Process) -> None:
        assert owned is process
        assert not owned.stdout.closed
        owned.returncode = 1

    terminate_tree = Mock(side_effect=terminate)
    monkeypatch.setattr(
        prepare_render,
        "subprocess",
        SimpleNamespace(Popen=spawn, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT),
    )
    monkeypatch.setattr(prepare_render, "_terminate_tree", terminate_tree)
    return spawn, terminate_tree


def test_success_streams_output_and_forwards_absolute_input_paths(
    prepared_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = 'SCENERY_PREPARE_PROGRESS {"done":1}\nSCENERY_PREPARE_OK {}\n'
    process = _Process(output)
    spawn, terminate = _mock_process(monkeypatch, process)

    assert prepare_render.main(["--scope", "city", "--radius", "900"]) == 0
    command = spawn.call_args.args[0]
    assert command[:6] == [
        "test-godot-console.exe",
        "--headless",
        "--path",
        str(prepared_workspace / "viewer"),
        "--script",
        "res://prepare_scenery.gd",
    ]
    forwarded = dict(zip(command[7::2], command[8::2], strict=True))
    assert forwarded == {
        "--geography": str(
            (prepared_workspace / ".local/civic/geography/sf-geography.json").resolve()
        ),
        "--terrain": str(
            (prepared_workspace / ".local/civic/terrain/terrain.json").resolve()
        ),
        "--render-cache": str(
            (prepared_workspace / ".local/civic/render-cache").resolve()
        ),
        "--scope": "city",
        "--radius": "900.0",
        "--report": str((prepared_workspace / ".cache/scenery-prepare.json").resolve()),
    }
    assert spawn.call_args.kwargs["cwd"] == prepared_workspace
    assert spawn.call_args.kwargs["stderr"] == subprocess.STDOUT
    assert (prepared_workspace / ".local/civic/render-cache").is_dir()
    assert (prepared_workspace / ".cache").is_dir()
    assert capsys.readouterr().out == output
    assert process.stdout.closed
    terminate.assert_not_called()


@pytest.mark.parametrize(
    ("output", "exit_code", "expected"),
    [
        ("SCENERY_PREPARE_OK {}\n", 7, 7),
        ("SCENERY_PREPARE_PROGRESS {}\n", 0, 1),
        ("SCENERY_PREPARE_OKAY {}\n", 0, 1),
        ("SCRIPT ERROR: Invalid assignment\nSCENERY_PREPARE_OK {}\n", 0, 1),
        ("Parse Error: Invalid script\nSCENERY_PREPARE_OK {}\n", 0, 1),
        (
            "ERROR: Failed to read the root certificate store.\nSCENERY_PREPARE_OK {}\n",
            0,
            0,
        ),
    ],
)
def test_completion_requires_marker_clean_script_and_successful_engine_exit(
    prepared_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: str,
    exit_code: int,
    expected: int,
) -> None:
    process = _Process(output, exit_code)
    _, terminate = _mock_process(monkeypatch, process)

    assert prepare_render.main([]) == expected
    assert process.stdout.closed
    terminate.assert_not_called()


@pytest.mark.parametrize("interrupt", ["read", "wait"])
def test_cancel_terminates_owned_godot_tree_before_closing_output(
    prepared_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: str,
) -> None:
    process = _Process("SCENERY_PREPARE_OK {}\n", interrupt=interrupt)
    spawn, terminate = _mock_process(monkeypatch, process)

    assert prepare_render.main([]) == 130
    spawn.assert_called_once()
    # This boundary must clean up the complete tree: the Windows console
    # executable is a wrapper whose engine child survives parent-only kill().
    terminate.assert_called_once_with(process)
    assert process.poll() is not None
    assert process.stdout.closed


@pytest.mark.parametrize("radius", ["0", "-1", "nan", "inf", "-inf"])
def test_invalid_radius_is_rejected_before_starting_godot_or_creating_cache(
    prepared_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    radius: str,
) -> None:
    spawn, terminate = _mock_process(monkeypatch, _Process(""))

    with pytest.raises(SystemExit) as failure:
        prepare_render.main([f"--radius={radius}"])
    assert failure.value.code == 2
    assert "Radius must be finite and positive" in capsys.readouterr().err
    assert not (prepared_workspace / ".local/civic/render-cache").exists()
    spawn.assert_not_called()
    terminate.assert_not_called()


@pytest.mark.parametrize(
    "missing",
    [
        ".local/civic/geography/sf-geography.json",
        ".local/civic/terrain/terrain.json",
    ],
)
def test_missing_input_is_rejected_before_starting_godot_or_creating_cache(
    prepared_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    (prepared_workspace / missing).unlink()
    spawn, terminate = _mock_process(monkeypatch, _Process(""))

    with pytest.raises(SystemExit) as failure:
        prepare_render.main([])
    assert failure.value.code == 2
    assert "Install geography and terrain first" in capsys.readouterr().err
    assert not (prepared_workspace / ".local/civic/render-cache").exists()
    spawn.assert_not_called()
    terminate.assert_not_called()
