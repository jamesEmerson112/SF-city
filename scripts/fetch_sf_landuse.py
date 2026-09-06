"""Prepare official SF parcel uses and report exact joins to observed footprints."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import atomic_write, canonical_bytes, content_hash
from civic_center.landuse import LandUseIndex, fetch_landuse, normalize_rows
from civic_center.package_verify import inside


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/sf-landuse")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".local/civic/landuse/landuse.json"
    )
    parser.add_argument(
        "--geography",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-geography.json",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    index, rows = fetch_landuse(
        args.cache,
        offline=args.offline,
        refresh=args.refresh,
        progress=lambda value: print(value, flush=True),
    )
    data = normalize_rows(rows, index)
    del rows
    geography = json.loads(args.geography.read_bytes())
    if content_hash(
        {k: v for k, v in geography.items() if k != "sha256"}
    ) != geography.get("sha256"):
        raise ValueError("Geography checksum differs")
    relative = geography["building_index_path"]
    raw = inside(args.geography.parent, relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() != geography["files"][relative]:
        raise ValueError("Building index checksum differs")
    buildings = json.loads(raw)["buildings"]
    uses, statistics = LandUseIndex(data).match_buildings(buildings)
    del buildings
    report = {
        "schema_version": 1,
        "geography_sha256": geography["sha256"],
        "landuse_sha256": data["sha256"],
        "statistics": statistics,
        "landuse_statistics": data["statistics"],
        "matched_building_examples": [
            uses[key] | {"id": key} for key in sorted(uses)[:5]
        ],
    }
    atomic_write(args.output, canonical_bytes(data))
    atomic_write(args.output.with_name("join-report.json"), canonical_bytes(report))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "bytes": args.output.stat().st_size,
                "sha256": data["sha256"],
                "statistics": statistics,
                "seconds": round(time.perf_counter() - started, 2),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
