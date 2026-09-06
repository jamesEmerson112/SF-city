"""Prepare observed footprint references for three original skyline exteriors."""

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

LANDMARKS = (
    {
        "key": "transamerica-pyramid",
        "label": "Transamerica Pyramid",
        "tile": "2_3",
        "id": "sf-building:201006.0000687",
        "height_m": round(853 * 0.3048, 4),
        "height_reference": {
            "url": "https://www.strongmotioncenter.org/NCESMD/photos/NSMP/bldlayouts/bld1239.pdf",
            "title": "USGS National Strong Motion Project station 1239 building layout, revision 2025-01-21",
            "reported_height_feet": 853,
            "reported_base_width_m": 53,
            "reported_structural_reference_degrees": 350,
        },
        "model_parameters": {"base_width_m": 53.0, "yaw_degrees": 10.0},
        "source_note": "Original approximate exterior using the observed DataSF footprint location and USGS-reported overall height, base width and structural orientation. Taper, wing geometry, colonnade and facade details are illustrative. The source footprint's median height is a different statistic from the pyramid's architectural top.",
    },
    {
        "key": "coit-tower",
        "label": "Coit Tower",
        "tile": "2_5",
        "id": "sf-building:201006.0006230",
        "height_m": round(212 * 0.3048, 4),
        "height_reference": {
            "url": "https://sfrecpark.org/DocumentCenter/View/7387/CoitTowerBrochure_V5",
            "title": "San Francisco Recreation and Parks Coit Tower brochure",
            "reported_height_feet": 212,
            "note": "The department brochure reports 212 feet; other references report 210. This model explicitly follows the brochure rather than silently mixing height references.",
        },
        "model_parameters": {
            "shaft_radius_m": 6.4,
            "shaft_center_offset_m": [1.3, -5.0],
            "yaw_degrees": 14.0,
        },
        "source_note": "Original approximate fluted tower and observation arcade above its observed DataSF base footprint. Overall height follows the Recreation and Parks brochure. Shaft radius, tower center within the footprint, arch details and facade proportions are illustrative, not a surveyed architectural model.",
    },
    {
        "key": "sutro-tower",
        "label": "Sutro Tower",
        "tile": "-6_-6",
        "id": "sf-building:201006.0009087",
        "replaces_building_ids": [
            "sf-building:201006.0009087",
            "sf-building:201006.0062170",
            "sf-building:201006.0168289",
        ],
        "height_m": 977 * 0.3048,
        "height_reference": {
            "url": "https://www.sutrotower.com/about",
            "title": "Sutro Tower operator: About the Tower",
            "reported_height_feet": 977,
            "shape_url": "https://explore.sutrotower.com/tour/design/a-unique-shape",
        },
        "model_parameters": {
            "main_structure_height_m": 228.6,
            "base_radius_m": 26.4,
            "waist_radius_m": 10.5,
            "top_radius_m": 17.6,
            "waist_height_m": 150.0,
            "yaw_degrees": 60.0,
        },
        "source_note": "Original illustrative three-legged open-truss structure aligned to the observed DataSF tower footprint group. Overall height follows the tower operator. Leg widths, taper, bracing, platforms, antennas and red/white pattern are approximations, not current antenna inventories or structural engineering data. Three identified overlapping source tower parts are replaced visually; nearby service buildings remain.",
    },
)


def main() -> None:
    directory = ROOT / ".local/civic/geography"
    raw = (directory / "sf-geography.json").read_bytes()
    geography = json.loads(raw)
    if content_hash(
        {key: value for key, value in geography.items() if key != "sha256"}
    ) != geography.get("sha256"):
        raise ValueError("Geographic source checksum mismatch")
    graph_raw = inside(directory, geography["graph_path"]).read_bytes()
    if (
        hashlib.sha256(graph_raw).hexdigest()
        != geography["files"][geography["graph_path"]]
    ):
        raise ValueError("Source walking graph checksum mismatch")
    graph = json.loads(graph_raw)
    connected = {edge[key] for edge in graph["edges"] for key in ("from", "to")}
    walking_nodes = [node for node in graph["nodes"] if node["id"] in connected]
    records = []
    for specification in LANDMARKS:
        relative = "sf-geography/tiles/" + specification["tile"] + ".json"
        tile_raw = inside(directory, relative).read_bytes()
        if hashlib.sha256(tile_raw).hexdigest() != geography["files"][relative]:
            raise ValueError("Geographic tile checksum mismatch")
        by_id = {
            building["id"]: building for building in json.loads(tile_raw)["buildings"]
        }
        building = by_id[specification["id"]]
        record = dict(specification)
        record["building"] = building
        record["roof"] = triangulate_rings(building["rings"])
        record["replaces_building_ids"] = specification.get(
            "replaces_building_ids", [specification["id"]]
        )
        record["replaced_building_references"] = [
            by_id[identity] for identity in record["replaces_building_ids"]
        ]
        nearest = min(
            walking_nodes,
            key=lambda node: (
                math.dist(node["position"][:2], building["centroid"][:2]),
                node["id"],
            ),
        )
        record["walk_position"] = nearest["position"]
        record["walk_node_id"] = nearest["id"]
        record["walk_target_distance_m"] = round(
            math.dist(nearest["position"][:2], building["centroid"][:2]), 3
        )
        record["building_reference"] = {
            "url": "https://data.sfgov.org/d/ynuv-fyni",
            "title": "San Francisco building footprints",
            "source_id": building["source_id"],
            "license": "Open Data Commons Public Domain Dedication and License 1.0",
            "license_url": "https://opendatacommons.org/licenses/pddl/1-0/",
            "observation_note": "2010 Pictometry-origin geometry refined in 2017; source refresh dates are not new surveys.",
        }
        record["sha256"] = content_hash(record)
        records.append(record)
    result = {
        "schema_version": 1,
        "origin": geography["origin"],
        "geography_sha256": geography["sha256"],
        "geography_file_sha256": hashlib.sha256(raw).hexdigest(),
        "landmarks": records,
    }
    result["sha256"] = content_hash(result)
    output = ROOT / "assets/source/skyline-geometry.json"
    output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "landmarks": [
                    {
                        "key": record["key"],
                        "height_m": record["height_m"],
                        "replaced_parts": len(record["replaces_building_ids"]),
                    }
                    for record in records
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
