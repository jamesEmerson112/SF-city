"""Compare city wire encodings and export untouched TCP frames for Godot parity.

Use a local checkpoint; the simulation remains paused except for explicit test
steps. This measures CPU and bytes, not rendering frame rate or WAN throughput.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import socket
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.checkpoint import load_checkpoint
from civic_center.worker import (
    CITY_ROUTES_ENCODING,
    CITY_ROWS_ENCODING,
    CivicWorker,
    encode_frame,
    snapshot_message,
)


def profile(checkpoint: Path, output: Path, samples: int) -> dict:
    simulation = load_checkpoint(checkpoint)
    if not simulation.scenario.get("geography_manifest"):
        raise ValueError("transport profiling requires a city checkpoint")
    simulation.set_paused(True)
    output.mkdir(parents=True, exist_ok=True)
    measured = {
        mode: {"snapshot_ms": [], "encode_ms": [], "total_ms": []}
        for mode in ("routes", "rows")
    }
    for iteration in range(samples + 3):
        for mode in ("routes", "rows") if iteration % 2 else ("rows", "routes"):
            started = time.perf_counter()
            message = snapshot_message(
                simulation,
                "benchmark",
                1,
                compact=True,
                trip_references=True,
                rows=mode == "rows",
            )
            captured = time.perf_counter()
            frame = encode_frame(message)
            finished = time.perf_counter()
            measured[mode]["bytes"] = len(frame)
            if iteration >= 3:
                measured[mode]["snapshot_ms"].append((captured - started) * 1000)
                measured[mode]["encode_ms"].append((finished - captured) * 1000)
                measured[mode]["total_ms"].append((finished - started) * 1000)
    report = {
        "python": sys.version,
        "samples": samples,
        "tick": simulation.tick,
        "population": len(simulation.scenario["residents"]),
        "scenario_sha256": simulation.scenario.get("sha256"),
        "walking": sum(
            person["moving"]
            for person in simulation.snapshot(
                include_static=False, include_trip_geometry=False
            )["residents"]
        ),
    }
    for mode, values in measured.items():
        report[mode] = {
            key: (
                round(statistics.median(value), 3) if isinstance(value, list) else value
            )
            for key, value in values.items()
        }

    token = secrets.token_hex(16)
    worker = CivicWorker(
        simulation.scenario,
        token,
        simulation=simulation,
        save_dir=output / "unused-saves",
        job_backend="thread",
    )
    failures = []

    def run():
        try:
            worker.run()
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        for mode, encoding in (
            ("routes", CITY_ROUTES_ENCODING),
            ("rows", CITY_ROWS_ENCODING),
        ):
            stream = bytearray()
            expected = []
            states = {str(simulation.tick): simulation.snapshot()}
            first_full = None
            last_tick = None
            with socket.create_connection(
                ("127.0.0.1", worker.port), timeout=15
            ) as client:
                client.settimeout(15)
                reader = client.makefile("rb")
                # Fragmented authentication exercises the real frame reader too.
                hello = encode_frame(
                    {
                        "type": "hello",
                        "protocol_version": 1,
                        "token": token,
                        "snapshot_encoding": encoding,
                    }
                )
                client.sendall(hello[:7])
                client.sendall(hello[7:])
                geometry_frames = []
                snapshots = 0
                while snapshots < 3:
                    line = reader.readline()
                    if not line:
                        raise RuntimeError("worker closed the profiling connection")
                    stream.extend(line)
                    message = json.loads(line)
                    if message["type"] == "error":
                        raise RuntimeError(message["message"])
                    if message["type"] == "scene":
                        assert message["snapshot_encoding"] == encoding
                        (output / f"{mode}-scene.json").write_bytes(line)
                        if mode == "routes":
                            (output / "scene.json").write_bytes(line)
                    elif message["type"] == "trip_geometries":
                        geometry_frames.append(line)
                    elif message["type"] == "ack":
                        assert simulation.tick == message["tick"]
                        states[str(simulation.tick)] = simulation.snapshot()
                    elif message["type"] == "snapshot":
                        envelope = {
                            "type": "snapshot",
                            "protocol_version": 1,
                            "tick": message["tick"],
                            "session_id": message["session_id"],
                            "sequence": message["sequence"],
                        }
                        assert str(message["tick"]) in states
                        expected.append(envelope)
                        if snapshots == 0:
                            report[mode]["tcp_snapshot_bytes"] = len(line)
                            (output / f"{mode}.json").write_bytes(line)
                            first_full = {**states[str(message["tick"])], **envelope}
                            (output / f"{mode}-definitions.ndjson").write_bytes(
                                b"".join(geometry_frames)
                            )
                        if last_tick == message["tick"]:
                            continue  # Retain periodic duplicates in the oracle.
                        last_tick = message["tick"]
                        snapshots += 1
                        if snapshots < 3:
                            client.sendall(
                                encode_frame(
                                    {
                                        "type": "command",
                                        "request_id": str(snapshots),
                                        "action": "step",
                                        "value": 20,
                                    }
                                )
                            )
                reader.close()
            (output / f"{mode}.ndjson").write_bytes(stream)
            # Full local oracles may exceed live frame limits. Reuse each tick's
            # state in the file, while retaining every actual TCP sequence.
            (output / f"{mode}-full.json").write_text(
                json.dumps(first_full, separators=(",", ":"), allow_nan=False),
                encoding="utf-8",
            )
            (output / f"{mode}-fulls.json").write_text(
                json.dumps(
                    {"states": states, "envelopes": expected},
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
        report["tcp_frames_exported"] = True
    finally:
        worker._stop.set()
        thread.join(5)
        if thread.is_alive():
            raise RuntimeError("profiling worker did not stop")
    if failures:
        raise failures[0]
    (output / "python.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/city-rows-profile"
    )
    parser.add_argument("--samples", type=int, default=21)
    options = parser.parse_args()
    if not 3 <= options.samples <= 1000:
        parser.error("samples must be between 3 and 1000")
    print(
        json.dumps(
            profile(options.checkpoint, options.output, options.samples), indent=2
        )
    )


if __name__ == "__main__":
    main()
