"""Fetch/cache official whole-city San Francisco geometry and build local tiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from civic_center.geography import DEFAULT_CACHE, DEFAULT_OUTPUT, SOURCES, fetch_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--tile-size", type=float, default=500)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use verified complete cache only; never access the network",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="fetch current source snapshots again"
    )
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args(argv)
    start = time.monotonic()
    try:
        indexes = {}
        for source in SOURCES:
            indexes[source.key] = fetch_source(
                source,
                args.cache_dir,
                page_size=args.page_size,
                offline=args.offline,
                refresh=args.refresh,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        if args.download_only:
            result = {
                "sources": {
                    key: value["feature_count"] for key, value in indexes.items()
                }
            }
        else:
            from civic_center.geography import build_geography

            result = build_geography(
                indexes, args.output_dir, tile_size_m=args.tile_size
            )
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        print(json.dumps(result, sort_keys=True), flush=True)
    except (OSError, ValueError) as error:
        print(f"SF geography import failed: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
