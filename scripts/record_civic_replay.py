"""Record deterministic one-person departure/arrival checkpoints for Godot checks."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.model import CivicSimulation
from civic_center.scenario import make_scenario


def record() -> dict:
    scenario = make_scenario(1)
    model = CivicSimulation(scenario)
    session = "one-resident-replay-v1"
    frames = []

    def capture() -> None:
        frames.append({"type": "snapshot", "protocol_version": 1,
                       "session_id": session, "sequence": len(frames) + 1,
                       **model.snapshot()})

    capture()
    model.step_ticks(model.next_event_tick() - model.tick)
    capture()
    arrival = model.snapshot()["residents"][0]["trip"]["arrival_tick"]
    model.step_ticks((arrival - model.tick) // 2)
    capture()
    model.step_ticks(arrival - model.tick)
    capture()
    model.step_ticks(model.next_event_tick() - model.tick)
    capture()
    arrival = model.snapshot()["residents"][0]["trip"]["arrival_tick"]
    model.step_ticks((arrival - model.tick) // 2)
    capture()
    model.step_ticks(arrival - model.tick)
    capture()
    return {"scene": {"type": "scene", "protocol_version": 1,
                      "session_id": session, "scenario": scenario,
                      "visual_asset": "res://assets/civic-center.glb"},
            "snapshots": frames}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "contracts/one-resident-replay.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = record()
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(payload['snapshots'])} checkpoints to {args.output}")


if __name__ == "__main__":
    main()
