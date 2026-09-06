"""Prepare compact, optional display data without modifying observed geography."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import atomic_write, canonical_bytes, content_hash
from civic_center.mesh_prepare import triangulate_rings


def silhouette(record: dict) -> list:
    """An explicitly coarse oriented bounding box, never a new footprint."""
    points = record["footprint"]
    longest = max(
        zip(points, points[1:] + points[:1]),
        key=lambda pair: (pair[1][0] - pair[0][0]) ** 2
        + (pair[1][1] - pair[0][1]) ** 2,
    )
    angle = math.atan2(longest[1][1] - longest[0][1], longest[1][0] - longest[0][0])
    cosine, sine = math.cos(angle), math.sin(angle)
    along = [point[0] * cosine + point[1] * sine for point in points]
    across = [-point[0] * sine + point[1] * cosine for point in points]
    minimum_x, maximum_x = min(along), max(along)
    minimum_y, maximum_y = min(across), max(across)
    center_x, center_y = (minimum_x + maximum_x) / 2, (minimum_y + maximum_y) / 2
    values = [
        center_x * cosine - center_y * sine,
        center_x * sine + center_y * cosine,
        maximum_x - minimum_x,
        maximum_y - minimum_y,
        record["height_m"],
        angle,
    ]
    return [record["id"], *[round(value, 4) for value in values]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geography",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-geography.json",
    )
    args = parser.parse_args()
    path = args.geography.resolve()
    directory = path.parent
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not manifest.get("complete"):
        parser.error("Geography preparation must be complete first")
    unsigned = {key: value for key, value in manifest.items() if key != "sha256"}
    if content_hash(unsigned) != manifest.get("sha256"):
        raise ValueError("Geography manifest checksum mismatch")
    started = time.perf_counter()
    descriptors = []
    counts = {
        "buildings": 0,
        "courtyard_roofs": 0,
        "roof_triangles": 0,
        "rejected_roofs": 0,
    }
    failures = []
    byte_count = 0
    for tile in manifest["tiles"]:
        source = (directory / tile["path"]).resolve()
        if not source.is_relative_to(directory):
            raise ValueError("Source tile path escapes the geography directory")
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"].get(tile["path"]):
            raise ValueError(f"Geography tile checksum mismatch: {tile['id']}")
        data = json.loads(raw)
        rows = []
        roofs = []
        for building in data["buildings"]:
            rows.append(silhouette(building))
            rings = building.get("rings", [building["footprint"]])
            if len(rings) > 1:
                try:
                    roof = triangulate_rings(rings)
                    roofs.append({"id": building["id"], **roof})
                    counts["courtyard_roofs"] += 1
                    counts["roof_triangles"] += len(roof["roof_triangles"]) // 3
                except ValueError as error:
                    counts["rejected_roofs"] += 1
                    if len(failures) < 20:
                        failures.append({"id": building["id"], "reason": str(error)})
        counts["buildings"] += len(rows)
        relative = f"visual/tiles/{tile['id']}.json"
        payload = canonical_bytes(
            {"schema_version": 1, "id": tile["id"], "silhouettes": rows, "roofs": roofs}
        )
        atomic_write(directory / relative, payload)
        byte_count += len(payload)
        descriptors.append(
            {
                "id": tile["id"],
                "path": relative,
                "bounds": tile["bounds"],
                "building_count": len(rows),
                "roof_count": len(roofs),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    index = {
        "schema_version": 1,
        "geography_sha256": manifest["sha256"],
        "geography_file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "origin": manifest["origin"],
        "tiles": descriptors,
        "silhouette_columns": [
            "id",
            "east",
            "north",
            "width_m",
            "depth_m",
            "height_m",
            "yaw_radians",
        ],
        "silhouette_note": "Coarse oriented bounding boxes aligned to each outer footprint's longest edge. These are display substitutes at a distance; original footprints, courtyards and heights remain in source geography.",
        "roof_note": "Mapbox Earcut triangulations preserve courtyard rings; every accepted roof is checked for polygon area conservation. Rejected roofs remain open in the existing viewer fallback.",
        "statistics": {**counts, "tile_data_bytes": byte_count},
        "rejected_examples": failures,
        "dependencies": {"mapbox-earcut": "2.0.0", "numpy": "2.5.2"},
    }
    atomic_write(directory / "visual-index.json", canonical_bytes(index))
    print(
        json.dumps(
            {
                "output": str(directory / "visual-index.json"),
                **index["statistics"],
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
