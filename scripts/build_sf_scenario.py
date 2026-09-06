"""Create a persistent walking cohort from downloaded normalized SF geography."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.city_scenario import CITY_POPULATIONS, OFFLINE_CITY_POPULATIONS, write_city_scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geography", type=Path, default=ROOT / ".local/civic/geography/sf-geography.json")
    parser.add_argument("--output", type=Path, help="Scenario path; offline larger cohorts default to their own distinct-population file")
    parser.add_argument("--population", type=int, choices=CITY_POPULATIONS + OFFLINE_CITY_POPULATIONS, default=200)
    parser.add_argument("--distinct-allocations", action="store_true", help="Require unique home/work building pairs; required for offline 2,000/5,000 scale cohorts. Does not expand viewer presets.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--minimum-walk-m", type=float, default=150)
    parser.add_argument("--maximum-walk-m", type=float, default=3000)
    parser.add_argument("--maximum-connector-m", type=float, default=120)
    parser.add_argument("--candidate-limit", type=int, default=4000)
    parser.add_argument("--terrain", type=Path, help="Elevation grid; defaults to sibling ../terrain/terrain.json when present")
    parser.add_argument("--one-day", action="store_true", help="Generate the original finite schedule instead of repeating every 24 hours")
    parser.add_argument("--landuse", type=Path, help="Verified parcel land-use sidecar to constrain eligible homes and workplaces")
    args = parser.parse_args()
    if args.output is None:
        args.output = (
            ROOT / f".local/civic/scenarios/sf-city-distinct-{args.population}.json"
            if args.population in OFFLINE_CITY_POPULATIONS
            else ROOT / ".local/civic/geography/sf-city-day.json"
        )
    if not args.geography.is_file():
        parser.error("Geography manifest is missing; run scripts/fetch_sf_geography.py first or provide --geography PATH")
    try:
        path = write_city_scenario(
            args.geography, args.output, population=args.population, seed=args.seed,
            minimum_walk_m=args.minimum_walk_m, maximum_walk_m=args.maximum_walk_m,
            maximum_connector_m=args.maximum_connector_m, candidate_limit=args.candidate_limit,
            terrain_path=args.terrain, repeat_days=not args.one_day, landuse_path=args.landuse,
            distinct_allocations=args.distinct_allocations,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    scenario = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({"output": str(path), "population": scenario["population"], **scenario["generation"]}, indent=2))


if __name__ == "__main__":
    main()
