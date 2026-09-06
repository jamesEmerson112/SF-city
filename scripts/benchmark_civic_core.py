"""Record core snapshot/JSON costs with optional same-process baseline comparison.

Example (PowerShell, after retaining a pre-change model.py in .cache):
    python scripts/benchmark_civic_core.py --baseline .cache/civic-model-before-snapshot.py --output .cache/civic-core-benchmark.json

This measures Python simulation work, not rendering, network transport or FPS.
Baseline and current models receive identical scenarios/ticks in interleaved
order, and their snapshots and encoded bytes must agree on every measurement.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.model import CivicSimulation
from civic_center.scenario import make_scenario


def _baseline_class(path: Path) -> type:
    name = "civic_center._benchmark_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load baseline model: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.CivicSimulation


def _encode(state: dict[str, Any]) -> bytes:
    # Matches worker.encode_frame's current JSON options, excluding its small
    # transport envelope because this benchmark deliberately owns only the core.
    return json.dumps(state, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _summary(samples: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(samples) * 1000, 3),
        "min_ms": round(min(samples) * 1000, 3),
        "max_ms": round(max(samples) * 1000, 3),
    }


def benchmark(
    populations: list[int], simulation_seconds: float, iterations: int,
    warmups: int, baseline_path: Path | None = None,
) -> dict[str, Any]:
    constructors = {"current": CivicSimulation}
    if baseline_path is not None:
        constructors = {"baseline": _baseline_class(baseline_path), **constructors}
    report: dict[str, Any] = {
        "description": "Python core costs only; no rendering or FPS measurement",
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "iterations": iterations,
        "warmups": warmups,
        "simulation_seconds_start": simulation_seconds,
        "tick_increment_per_sample": 20,
        "baseline_path": str(baseline_path) if baseline_path else None,
        "json_options": {"separators": [",", ":"], "allow_nan": False, "ensure_ascii": True},
        "workloads": [],
    }
    for population in populations:
        scenario = make_scenario(population)
        models = {}
        timings = {}
        for name, constructor in constructors.items():
            started = perf_counter()
            model = constructor(scenario)
            initialized = perf_counter()
            model.advance_ticks(round(simulation_seconds * model.tick_hz))
            advanced = perf_counter()
            models[name] = model
            timings[name] = {
                "initialize_ms": round((initialized - started) * 1000, 3),
                "initial_advance_ms": round((advanced - initialized) * 1000, 3),
                "snapshot": [], "json_encoding": [], "snapshot_plus_encoding": [],
            }
            for _ in range(warmups):
                _encode(model.snapshot())
        last_snapshot = None
        last_encoded = b""
        for iteration in range(iterations):
            order = list(models)
            if iteration % 2:
                order.reverse()
            iteration_states = []
            iteration_bytes = []
            for name in order:
                model = models[name]
                model.step_ticks(20)
                started = perf_counter()
                state = model.snapshot()
                snapshotted = perf_counter()
                encoded = _encode(state)
                finished = perf_counter()
                timings[name]["snapshot"].append(snapshotted - started)
                timings[name]["json_encoding"].append(finished - snapshotted)
                timings[name]["snapshot_plus_encoding"].append(finished - started)
                iteration_states.append(state)
                iteration_bytes.append(encoded)
                last_snapshot, last_encoded = state, encoded
            assert all(state == iteration_states[0] for state in iteration_states)
            assert all(encoded == iteration_bytes[0] for encoded in iteration_bytes)
        assert last_snapshot is not None
        workload = {
            "population": population,
            "completed_tick": last_snapshot["tick"],
            "walking_residents": sum(person["moving"] for person in last_snapshot["residents"]),
            "snapshot_json_bytes": len(last_encoded),
            "event_journal_records": len(last_snapshot["events"]),
            "models": {},
        }
        for name, measurements in timings.items():
            workload["models"][name] = {
                key: _summary(value) if isinstance(value, list) else value
                for key, value in measurements.items()
            }
        if baseline_path is not None:
            workload["baseline_and_current_states_identical"] = True
            workload["snapshot_median_speedup"] = round(
                statistics.median(timings["baseline"]["snapshot"])
                / statistics.median(timings["current"]["snapshot"]), 3,
            )
        report["workloads"].append(workload)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--populations", type=int, nargs="+", default=[200, 1000, 5000])
    parser.add_argument("--simulation-seconds", type=float, default=600)
    parser.add_argument("--iterations", type=int, default=9)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 1 or args.warmups < 0 or args.simulation_seconds < 0:
        parser.error("iterations must be positive; warmups and simulation seconds nonnegative")
    report = benchmark(
        args.populations, args.simulation_seconds, args.iterations,
        args.warmups, args.baseline,
    )
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
