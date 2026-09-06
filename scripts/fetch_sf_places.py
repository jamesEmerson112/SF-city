"""Fetch verified public neighborhood/park sources and prepare named navigation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import fetch_source
from civic_center.places import SOURCES, build_places


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".cache/sf-places")
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
        indexes = {
            source.key: fetch_source(
                source,
                args.cache_dir,
                page_size=1000,
                offline=args.offline,
                refresh=args.refresh,
                progress=lambda text: print(text, file=sys.stderr, flush=True),
            )
            for source in SOURCES
        }
        result = build_places(indexes, args.geography)
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as error:
        print(f"SF places import failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
