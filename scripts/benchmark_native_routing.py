"""Compare cold Python/Rust searches using identical costs and full route output."""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.native_routing import NativeRoutes
from civic_center.routing import WalkingGraph
from civic_center.scenario import load_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-city-day-1000.json",
    )
    parser.add_argument("--pairs", type=int, default=400)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/native-routing-benchmark.json"
    )
    args = parser.parse_args()
    scenario = load_scenario(args.scenario)
    started = time.perf_counter()
    graph = WalkingGraph(scenario["nodes"], scenario["edges"])
    python_build = time.perf_counter() - started
    started = time.perf_counter()
    native = NativeRoutes(graph)
    native_build = time.perf_counter() - started
    buildings = {building["id"]: building for building in scenario["buildings"]}
    candidates = []
    for resident in scenario["residents"]:
        origin = buildings[resident["home_id"]]["entrance_node_id"]
        destination = buildings[resident["work_id"]]["entrance_node_id"]
        candidates.extend([(origin, destination), (destination, origin)])
    pairs = list(dict.fromkeys(candidates))[: args.pairs]
    timings = {"python": [], "rust": []}
    total_points = 0
    for origin, destination in pairs:
        graph._cache.clear()
        started = time.perf_counter()
        reference = graph.route(origin, destination)
        timings["python"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        result = native.route(origin, destination)
        timings["rust"].append((time.perf_counter() - started) * 1000)
        if result != reference:
            raise AssertionError(f"Native route differs: {origin} -> {destination}")
        total_points += len(result.points) if result else 0
    native.close()
    report = {
        "scenario": str(args.scenario.resolve()),
        "scenario_sha256": scenario["sha256"],
        "pairs": len(pairs),
        "matched_dense_points": total_points,
        "python_graph_build_seconds": python_build,
        "native_adjacency_copy_seconds": native_build,
        "timings_ms": {
            key: {
                "median": statistics.median(values),
                "total": sum(values),
                "p95": sorted(values)[max(0, int(len(values) * 0.95) - 1)],
            }
            for key, values in timings.items()
        },
        "note": "Cold search plus complete Python geometry reconstruction in both backends; no route cache hits; graph validation/preparation measured separately.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
