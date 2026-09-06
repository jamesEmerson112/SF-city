"""Prepare observed City Hall footprint plus sources for an original Blender model."""

import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import content_hash
from civic_center.mesh_prepare import triangulate_rings
from civic_center.package_verify import inside


def main():
    directory = ROOT / ".local/civic/geography"
    manifest = json.loads((directory / "sf-geography.json").read_text(encoding="utf-8"))
    tile = json.loads(
        (directory / "sf-geography/tiles/0_-1.json").read_text(encoding="utf-8")
    )
    building = next(
        record
        for record in tile["buildings"]
        if record["id"] == "sf-building:201006.0000041"
    )
    graph_raw = inside(directory, manifest["graph_path"]).read_bytes()
    if (
        hashlib.sha256(graph_raw).hexdigest()
        != manifest["files"][manifest["graph_path"]]
    ):
        raise ValueError("Source walking graph checksum mismatch")
    graph = json.loads(graph_raw)
    connected = {edge[key] for edge in graph["edges"] for key in ("from", "to")}
    nearest = min(
        (node for node in graph["nodes"] if node["id"] in connected),
        key=lambda node: (
            math.dist(node["position"][:2], building["centroid"][:2]),
            node["id"],
        ),
    )
    data = {
        "schema_version": 1,
        "building": building,
        "roof": triangulate_rings(building.get("rings", [building["footprint"]])),
        "origin": manifest["origin"],
        "geography_sha256": manifest["sha256"],
        "walk_position": nearest["position"],
        "walk_node_id": nearest["id"],
        "walk_target_distance_m": round(
            math.dist(nearest["position"][:2], building["centroid"][:2]), 3
        ),
        "building_reference": {
            "url": "https://data.sfgov.org/d/ynuv-fyni",
            "title": "San Francisco building footprints",
            "source_id": building["source_id"],
            "license": "Open Data Commons Public Domain Dedication and License 1.0",
            "license_url": "https://opendatacommons.org/licenses/pddl/1-0/",
            "observation_note": "2010 Pictometry-origin geometry refined in 2017; source refresh dates are not new surveys.",
        },
        "architectural_height_m": 307.5 * 0.3048,
        "height_reference": {
            "url": "https://www.sf.gov/sites/default/files/2021-12/12746-DocentPresentation.pdf",
            "title": "San Francisco City Hall docent presentation",
            "reported_height_feet": 307.5,
        },
        "source_note": "Observed DataSF outer footprint and median roof height; original procedural facade, columns and dome. Total landmark height follows the City's docent reference. LiDAR peak-ground statistic is retained separately and differs from architectural height. This is an approximate exterior, not a surveyed facade or interior.",
    }
    data["sha256"] = content_hash(data)
    output = ROOT / "assets/source/city-hall-geometry.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "footprint_vertices": len(data["roof"]["roof_vertices"]),
                "roof_triangles": len(data["roof"]["roof_triangles"]) // 3,
                "architectural_height_m": data["architectural_height_m"],
            }
        )
    )


if __name__ == "__main__":
    main()
