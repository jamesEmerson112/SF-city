"""Independent Python polygon/count oracle for the actual city daylight replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import _RingMask, canonical_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay", type=Path, default=ROOT / ".cache/sf-daylight-replay.json"
    )
    parser.add_argument(
        "--areas", type=Path, default=ROOT / ".local/civic/geography/places-areas.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/area-activity-oracle.json"
    )
    args = parser.parse_args()
    replay = json.loads(args.replay.read_bytes())
    areas = json.loads(args.areas.read_bytes())["areas"]
    scenario = replay["scene"]["scenario"]
    cases = []
    for area in areas:
        if not area["id"].startswith("sf-neighborhood:"):
            continue
        parts = [
            [_RingMask(ring) for ring in part["rings"]] for part in area["polygons"]
        ]

        def contains(point):
            return any(
                rings[0].contains(point)
                and not any(hole.contains(point) for hole in rings[1:])
                for rings in parts
            )

        inside = {
            building["id"]
            for building in scenario["buildings"]
            if contains(building["centroid"])
        }
        base = {
            "cohort_size": len(scenario["residents"]),
            "assigned_buildings": len(inside),
            "home_assignments": sum(
                resident["home_id"] in inside for resident in scenario["residents"]
            ),
            "work_assignments": sum(
                resident["work_id"] in inside for resident in scenario["residents"]
            ),
            "buildings_without_centroids": 0,
            "people_without_location": 0,
        }
        expected = []
        for snapshot in replay["snapshots"]:
            value = {
                **base,
                "people_here": 0,
                "indoors_here": 0,
                "walking_here": 0,
                "incoming_trips": 0,
                "outgoing_trips": 0,
                "internal_trips": 0,
            }
            for resident in snapshot["residents"]:
                if resident["building_id"] is not None:
                    value["indoors_here"] += resident["building_id"] in inside
                else:
                    value["walking_here"] += contains(resident["position"])
                trip = resident["trip"]
                if trip is not None:
                    origin, destination = (
                        trip["origin_id"] in inside,
                        trip["destination_id"] in inside,
                    )
                    if origin and destination:
                        value["internal_trips"] += 1
                    elif origin:
                        value["outgoing_trips"] += 1
                    elif destination:
                        value["incoming_trips"] += 1
            value["people_here"] = value["indoors_here"] + value["walking_here"]
            expected.append(value)
        cases.append({"id": area["id"], "expected": expected})
    result = {
        "replay": str(args.replay.resolve()),
        "areas": str(args.areas.resolve()),
        "cases": cases,
        "snapshot_count": len(replay["snapshots"]),
        "cohort_size": len(scenario["residents"]),
    }
    result["people_here_sums"] = [
        sum(case["expected"][index]["people_here"] for case in cases)
        for index in range(len(replay["snapshots"]))
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(result))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "areas": len(cases),
                "snapshots": result["snapshot_count"],
                "people_here_sums": result["people_here_sums"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
