"""Record actual later-day city states for daylight and camera inspection."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import atomic_write, canonical_bytes
from civic_center.model import CivicSimulation
from civic_center.scenario import load_scenario
from civic_center.worker import scene_message, snapshot_message

TIMES = (
    (6, 30, "dawn"),
    (7, 0, "sunrise"),
    (8, 20, "morning commute"),
    (13, 0, "midday"),
    (17, 20, "evening commute"),
    (19, 20, "sunset"),
    (22, 0, "night"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-city-day.json",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/sf-daylight-replay.json"
    )
    args = parser.parse_args()
    started = time.perf_counter()
    scenario = load_scenario(args.scenario)
    if scenario.get("schedule", {}).get("mode") != "daily-v1":
        raise ValueError(
            "Daylight replay requires an authoritative repeating-day scenario"
        )
    model = CivicSimulation(scenario)
    model.set_paused(True)
    session = "sf-daylight-replay-v1"
    frames, labels, report = [], [], []
    for hour, minute, label in TIMES:
        clock_seconds = 86400 + hour * 3600 + minute * 60
        target = round((clock_seconds - model.start_time_seconds) * model.tick_hz)
        model.step_ticks(target - model.tick)
        frame = snapshot_message(model, session, len(frames) + 1)
        assert frame["clock_seconds"] == clock_seconds
        activities = Counter(resident["activity"] for resident in frame["residents"])
        walking = sum(resident["visible"] for resident in frame["residents"])
        assert walking + sum(
            building["occupancy"] for building in frame["buildings"]
        ) == len(frame["residents"])
        frames.append(frame)
        labels.append(label)
        report.append(
            {
                "index": len(frames) - 1,
                "label": label,
                "clock_seconds": clock_seconds,
                "activities": dict(activities),
            }
        )
    document = {
        "scene": scene_message(scenario, session),
        "snapshots": frames,
        "frame_labels": labels,
        "note": "Each state is produced by advancing the authoritative repeating simulation to day2. Lighting consumes its clock; no visual-only time override is used.",
    }
    payload = canonical_bytes(document)
    if len(payload) > 32 * 1024 * 1024:
        raise ValueError(
            "Daylight replay exceeds its bounded32MiB inspection size; use a smaller cohort"
        )
    atomic_write(args.output, payload)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "bytes": len(payload),
                "seconds": round(time.perf_counter() - started, 3),
                "frames": report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
