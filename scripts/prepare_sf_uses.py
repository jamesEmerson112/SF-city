"""Prepare optional parcel-use colors and group-aware inspection for city tiles."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import atomic_write, canonical_bytes, content_hash
from civic_center.landuse import LandUseIndex, SOURCE_URL, LICENSE_URL
from civic_center.package_verify import inside

CATEGORIES = {
    "residential": "Positive ordinary residential units; no commercial floor area recorded",
    "mixed": "Both ordinary residential units and commercial floor area recorded",
    "institutional": "Cultural, institutional or educational area is the largest commercial component",
    "medical": "Medical area is the largest commercial component",
    "office": "Office area is the largest commercial component",
    "retail": "Retail or entertainment area is the largest commercial component",
    "industrial": "Production, distribution or repair area is the largest commercial component",
    "visitor": "Visitor accommodation area is the largest commercial component",
    "commercial": "Commercial components tie for the largest area, or no dominant component is available",
    "parking": "Source flags parking or garage, without ordinary residential units or commercial area",
    "open_space": "Source flags open space, without ordinary residential units or commercial area",
    "other": "Uniquely matched source with no use classified by these rules",
    "unknown": "No unique exact parcel join to the source",
}
COMMERCIAL = {
    "cie": "institutional",
    "med": "medical",
    "mips": "office",
    "retail": "retail",
    "pdr": "industrial",
    "visitor": "visitor",
}


def category(record: dict) -> str:
    home = (record.get("residential_units") or 0) > 0
    work = (record.get("commercial_area_sqft") or 0) > 0
    if home:
        return "mixed" if work else "residential"
    if work:
        values = record["commercial_by_use_sqft"]
        largest = max(value or 0 for value in values.values())
        winners = [key for key, value in values.items() if value == largest]
        return (
            COMMERCIAL[winners[0]]
            if largest > 0 and len(winners) == 1
            else "commercial"
        )
    if record.get("parking_lot") is True or record.get("garage") is True:
        return "parking"
    if record.get("open_space") is True:
        return "open_space"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geography",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-geography.json",
    )
    parser.add_argument(
        "--landuse", type=Path, default=ROOT / ".local/civic/landuse/landuse.json"
    )
    args = parser.parse_args()
    started = time.perf_counter()
    directory = args.geography.resolve().parent
    raw = args.geography.read_bytes()
    manifest = json.loads(raw)
    if content_hash(
        {k: v for k, v in manifest.items() if k != "sha256"}
    ) != manifest.get("sha256"):
        raise ValueError("Geography manifest checksum mismatch")
    relative = manifest["building_index_path"]
    building_bytes = inside(directory, relative).read_bytes()
    if hashlib.sha256(building_bytes).hexdigest() != manifest["files"][relative]:
        raise ValueError("Building index checksum mismatch")
    buildings = json.loads(building_bytes)["buildings"]
    del building_bytes
    index = LandUseIndex.load(args.landuse)
    matched, join_statistics = index.match_buildings(buildings)
    tiles = defaultdict(list)
    for building in buildings:
        use = matched.get(building["id"])
        if use is not None:
            tiles[building["tile_id"]].append((building["id"], use))
    descriptors = []
    statistics = Counter()
    keys = (
        "record_id",
        "data_as_of",
        "geography_type",
        "group_footprint_count",
        "residential_units_in_source_group",
        "special_units_or_beds_in_source_group",
        "commercial_area_sqft_in_source_group",
        "commercial_by_use_sqft_in_source_group",
    )
    for tile in manifest["tiles"]:
        rows, groups = [], {}
        for identity, use in tiles[tile["id"]]:
            source_record = index.records[use["record_id"]]
            kind = category(source_record)
            rows.append([identity, kind, use["record_id"]])
            groups[use["record_id"]] = {key: use[key] for key in keys}
            statistics[kind] += 1
        rows.sort(key=lambda row: row[0])
        relative = "use-tiles/" + tile["id"] + ".json"
        payload = canonical_bytes(
            {"schema_version": 1, "id": tile["id"], "buildings": rows, "groups": groups}
        )
        atomic_write(inside(directory, relative), payload)
        color_path = "use-colors/" + tile["id"] + ".json"
        color_payload = canonical_bytes(
            {"schema_version": 1, "id": tile["id"], "buildings": rows}
        )
        atomic_write(inside(directory, color_path), color_payload)
        descriptors.append(
            {
                "id": tile["id"],
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "color_path": color_path,
                "color_sha256": hashlib.sha256(color_payload).hexdigest(),
                "building_count": len(rows),
                "group_count": len(groups),
            }
        )
    result = {
        "schema_version": 1,
        "geography_sha256": manifest["sha256"],
        "geography_file_sha256": hashlib.sha256(raw).hexdigest(),
        "landuse_sha256": index.data["sha256"],
        "landuse_file_sha256": hashlib.sha256(args.landuse.read_bytes()).hexdigest(),
        "source": {
            "title": "San Francisco Land Use",
            "url": SOURCE_URL,
            "license_url": LICENSE_URL,
            "observation_dates": index.data["statistics"]["observation_dates"],
        },
        "columns": ["id", "category", "group_id"],
        "categories": CATEGORIES,
        "note": "Use colors classify source parcel/group attributes. They do not locate uses within individual footprints or imply observed residents, employers or occupancy. Group totals are shared source facts, never per-building totals.",
        "tiles": descriptors,
        "tile_count": len(descriptors),
        "statistics": {
            "matched_buildings": len(matched),
            "categories": dict(statistics),
            "join": join_statistics,
        },
    }
    atomic_write(directory / "use-index.json", canonical_bytes(result))
    print(
        json.dumps(
            {
                "output": str(directory / "use-index.json"),
                "tiles": len(descriptors),
                "statistics": result["statistics"],
                "tile_bytes": sum(
                    inside(directory, tile["path"]).stat().st_size
                    for tile in descriptors
                ),
                "color_bytes": sum(
                    inside(directory, tile["color_path"]).stat().st_size
                    for tile in descriptors
                ),
                "seconds": round(time.perf_counter() - started, 2),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
