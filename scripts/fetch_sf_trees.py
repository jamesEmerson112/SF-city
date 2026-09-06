"""Fetch the replacement SF street-tree inventory and prepare verified visual tiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import fetch_source
from civic_center.trees import SOURCE, build_trees


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".cache/sf-trees")
    parser.add_argument(
        "--geography",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-geography.json",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        index = fetch_source(
            SOURCE,
            args.cache_dir,
            page_size=5000,
            offline=args.offline,
            refresh=args.refresh,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        result = build_trees(index, args.geography)
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as error:
        print(f"SF tree import failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
