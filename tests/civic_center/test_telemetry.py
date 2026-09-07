"""Live diagnostics stay useful under authentication errors and backpressure."""

import json
import socket
import threading

import pytest

from civic_center.telemetry import MAX_LOGS, TelemetryHub


@pytest.fixture
def hub():
    server = TelemetryHub("test-run", "test-credential")
    server.start()
    try:
        yield server
    finally:
        server.stop()
    assert not server._thread.is_alive()


def _connect(hub, token="test-credential"):
    connection = socket.create_connection(("127.0.0.1", hub.port), timeout=2)
    connection.sendall(
        (
            json.dumps({"type": "hello", "schema_version": 1, "token": token}) + "\n"
        ).encode()
    )
    return connection


def _read(stream):
    return json.loads(stream.readline())


def test_authenticated_snapshot_then_hardware_and_log_updates(hub):
    hub.publish("inventory", {"cpu": {"model": "fixture"}})
    hub.publish("hardware", {"cpu": {"percent": 12.0}})
    with _connect(hub) as connection, connection.makefile("rb") as stream:
        initial = _read(stream)
        assert initial["kind"] == "snapshot"
        assert initial["payload"]["inventory"]["cpu"]["model"] == "fixture"
        assert initial["payload"]["hardware"]["cpu"]["percent"] == 12.0
        assert initial["payload"]["clock"]["launcher_monotonic_seconds"] > 0
        hub.publish("hardware", {"cpu": {"percent": 34.0}}, "hardware")
        hub.publish(
            "log",
            {
                "id": 1,
                "source": "worker",
                "severity": "warning",
                "message": "fixture warning",
            },
            "worker",
        )
        records = [_read(stream), _read(stream)]
        assert [row["kind"] for row in records] == ["hardware", "log"]
        assert records[0]["payload"]["cpu"]["percent"] == 34.0
        assert records[1]["source"] == "worker"
        assert all(row["sequence"] > initial["sequence"] for row in records)
        assert "test-credential" not in json.dumps([initial, *records])


@pytest.mark.parametrize(
    "hello",
    [
        b'{"type":"hello","schema_version":1,"token":"wrong"}\n',
        b"not-json\n",
        b"x" * 4097,
    ],
)
def test_bad_or_oversized_handshakes_never_receive_diagnostics(hub, hello):
    hub.publish("hardware", {"private_fixture": "authenticated only"})
    with socket.create_connection(("127.0.0.1", hub.port), timeout=2) as connection:
        connection.sendall(hello)
        try:
            assert connection.recv(1024) == b""
        except ConnectionResetError:
            pass


def test_log_flood_is_bounded_and_slow_subscriber_does_not_block_publish(hub):
    slow = _connect(hub)
    done = threading.Event()

    def flood():
        for index in range(5000):
            hub.publish("log", {"id": index, "message": "x" * 2000})
            hub.publish("hardware", {"cpu": {"percent": index}})
        done.set()

    writer = threading.Thread(target=flood, daemon=True)
    writer.start()
    try:
        assert done.wait(5), "Socket backpressure must never block producer callbacks"
        with _connect(hub) as connection, connection.makefile("rb") as stream:
            snapshot = _read(stream)
            assert snapshot["kind"] == "snapshot"
            assert snapshot["payload"]["hardware"]["cpu"]["percent"] == 4999
            assert len(snapshot["payload"]["logs"]) <= MAX_LOGS
            assert snapshot["dropped_events"] >= 5000 - MAX_LOGS
            assert len(json.dumps(snapshot).encode()) < 128 * 1024
    finally:
        slow.close()
        writer.join(2)


def test_idle_feed_heartbeat_and_stop_ignore_late_callbacks(hub):
    with _connect(hub) as connection, connection.makefile("rb") as stream:
        initial = _read(stream)
        heartbeat = _read(stream)
        assert heartbeat["kind"] == "heartbeat"
        assert heartbeat["sequence"] == initial["sequence"]
    hub.stop()
    before = hub._records(None)
    hub.publish("hardware", {"cpu": {"percent": 99}})
    assert hub._records(None)[0] == before[0]
