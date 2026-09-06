"""Exercise owned-process shutdown, including Windows venv launcher children."""

import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import pytest

from civic_center.launch import (
    _read_ready,
    _shutdown_worker,
    _terminate_tree,
    _relocate_cached_sources,
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
        _shutdown_worker(process, ready["port"], token)
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
        _terminate_tree(process)
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
