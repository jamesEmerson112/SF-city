"""Exercise owned-process shutdown, including Windows venv launcher children."""

import json
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from civic_center.launch import (
    _read_ready,
    _relocate_cached_sources,
    _shutdown_worker,
    _terminate_tree,
)
from civic_center.scenario import scenario_hash

ROOT = Path(__file__).resolve().parents[2]


def test_moved_city_cache_rebases_sources_without_changing_resident_geometry(tmp_path):
    scenario = {
        "geography_manifest": "C:/former/location/geography.json",
        "terrain_manifest": "C:/former/location/terrain.json",
        "terrain": {"path": "C:/former/location/terrain.json", "sample_count": 42},
        "residents": [{"id": "resident-1", "home_id": "home"}],
        "nodes": [{"id": "home", "position": [1, 2, 3]}],
    }
    scenario["sha256"] = scenario_hash(scenario)
    old_hash = scenario["sha256"]
    geography, terrain = tmp_path / "geography.json", tmp_path / "terrain.json"
    assert _relocate_cached_sources(scenario, geography, terrain)
    assert scenario["geography_manifest"] == str(geography.resolve())
    assert (
        scenario["terrain_manifest"]
        == scenario["terrain"]["path"]
        == str(terrain.resolve())
    )
    assert scenario["sha256"] == scenario_hash(scenario) != old_hash
    assert scenario["nodes"] == [{"id": "home", "position": [1, 2, 3]}]
    assert not _relocate_cached_sources(scenario, geography, terrain)


def _closed(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return False
    except OSError:
        return True


def test_graceful_worker_shutdown_closes_actual_interpreter_socket():
    token = secrets.token_urlsafe(12)
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "civic_center.worker",
            "--port",
            "0",
            "--token",
            token,
            "--population",
            "1",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ready = None
    try:
        ready = _read_ready(process, 10)
        assert not _closed(ready["port"])
        outcome = _shutdown_worker(process, ready["port"], token)
        assert outcome["status"] == "graceful"
        assert outcome["acknowledged"] is True
        assert outcome["forced"] is False
        assert outcome["exit_code"] == 0
        assert process.poll() is not None
        assert _closed(ready["port"])
    finally:
        if process.poll() is None:
            _terminate_tree(process)
        process.stdout.close()
        process.stderr.close()


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows venv launcher process tree"
)
def test_forced_cleanup_terminates_worker_descendants():
    child = "\n".join(
        [
            "import json,os,socket,time",
            "sock=socket.socket()",
            "sock.bind(('127.0.0.1',0)); sock.listen()",
            "print(json.dumps({'type':'ready','port':sock.getsockname()[1],'pid':os.getpid()}),flush=True)",
            "time.sleep(30)",
        ]
    )
    parent = "\n".join(
        [
            "import subprocess,sys",
            f"child=subprocess.Popen([sys.executable,'-u','-c',{child!r}],stdout=subprocess.PIPE,text=True)",
            "print(child.stdout.readline(),end='',flush=True)",
            "child.wait()",
        ]
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", parent],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        ready = _read_ready(process, 10)
        assert not _closed(ready["port"])
        outcome = _terminate_tree(process)
        assert outcome["status"] == "forced"
        assert outcome["forced"] is True
        deadline = time.monotonic() + 2
        while not _closed(ready["port"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert process.poll() is not None
        assert _closed(ready["port"]), "The descendant interpreter remained alive"
    finally:
        if process.poll() is None:
            _terminate_tree(process)
        process.stdout.close()
        process.stderr.close()


def test_readiness_failure_has_clear_error_and_owned_process_can_exit():
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", "print('invalid readiness')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with pytest.raises(RuntimeError, match="startup failed"):
            _read_ready(process, 10)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            _terminate_tree(process)
        process.stdout.close()
        process.stderr.close()


@pytest.mark.parametrize(
    "ready",
    [
        [],
        True,
        {"type": "ready", "port": True},
        {"type": "ready", "port": 0},
        {"type": "ready", "port": 65536},
    ],
)
def test_malformed_ready_record_is_a_clear_startup_error(ready):
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", f"print({json.dumps(ready)!r})"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with pytest.raises(RuntimeError, match="invalid readiness"):
            _read_ready(process, 5)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            _terminate_tree(process)
        process.stdout.close()
        process.stderr.close()


class _ExitedProcess:
    def __init__(self, exit_code=0):
        self.returncode = exit_code

    def poll(self):
        return self.returncode


def test_shutdown_reports_already_exited_without_connecting(monkeypatch):
    from civic_center import launch

    def unexpected(*args, **kwargs):
        pytest.fail("An exited owned process does not need a socket or termination")

    monkeypatch.setattr(launch.socket, "create_connection", unexpected)
    result = _shutdown_worker(_ExitedProcess(17), 12345, "secret")
    assert result["status"] == "already_exited"
    assert result["exit_code"] == 17
    assert result["acknowledged"] is False


def test_shutdown_discards_large_frames_and_matches_only_its_ack(monkeypatch):
    from civic_center import launch

    process = _ExitedProcess(None)
    process.wait = lambda timeout: setattr(process, "returncode", 0)
    valid = json.dumps(
        {"type": "ack", "action": "shutdown", "request_id": "launcher-shutdown"}
    ).encode()
    wrong = json.dumps(
        {"type": "ack", "action": "save", "request_id": "launcher-shutdown"}
    ).encode()
    chunks = iter(
        [
            b'{"scene":"' + b"x" * 65000,
            b"y" * 65000,
            b'"}\n' + wrong + b"\n",
            valid[:17],
            valid[17:] + b"\n",
            b"",
        ]
    )

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, data):
            commands = [json.loads(line) for line in data.splitlines()]
            assert commands[-1]["action"] == "shutdown"

        def settimeout(self, timeout):
            assert 0 < timeout <= 0.5

        def recv(self, count):
            assert count == 65536
            return next(chunks)

    monkeypatch.setattr(
        launch.socket, "create_connection", lambda *a, **k: Connection()
    )
    result = _shutdown_worker(process, 12345, "private")
    assert result["status"] == "graceful"
    assert result["acknowledged"] is True
    assert result["forced"] is False


def test_failed_graceful_connection_reports_forced_fallback(monkeypatch):
    from civic_center import launch

    process = _ExitedProcess(None)

    def unavailable(*args, **kwargs):
        raise OSError("socket unavailable")

    def forced(owned):
        assert owned is process
        owned.returncode = 1
        return {"status": "forced", "exit_code": 1, "forced": True}

    monkeypatch.setattr(launch.socket, "create_connection", unavailable)
    monkeypatch.setattr(launch, "_terminate_tree", forced)
    result = _shutdown_worker(process, 12345, "private")
    assert result["status"] == "forced"
    assert result["acknowledged"] is False
    assert result["reason"] == "worker_connection_failed"


def test_failed_owned_termination_is_reported(monkeypatch):
    from civic_center import launch

    class Process(_ExitedProcess):
        def terminate(self):
            raise OSError("owned process termination failed")

    monkeypatch.setattr(launch.sys, "platform", "linux")
    result = _terminate_tree(Process(None))
    assert result["status"] == "failed"
    assert result["forced"] is True
    assert result["exit_code"] is None
    assert "owned process termination failed" in result["reason"]
