"""Source-backed destinations in the existing San Francisco coordinate frame.

Analysis neighborhoods are reporting areas, not legal neighborhood boundaries.
Recreation and Parks properties are department holdings, not a land-cover map.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable
import json

from .geography import (
    LandMask,
    LocalProjection,
    Source,
    _polygon_centroid,
    _project_points,
    _RingMask,
    atomic_write,
    bounds_of,
    cached_features,
    canonical_bytes,
    content_hash,
)
from .package_verify import inside

SOURCES = (
    Source(
        "neighborhoods",
        "j2bu-swwd",
        "Analysis Neighborhoods",
        "the_geom",
        "the_geom,nhood",
        "nhood",
        observation_note="41 analysis areas aggregated from Census tracts. These are not official or legal neighborhood boundaries. The source describes a static reporting geography, last revised on the portal in 2023.",
    ),
    Source(
        "parks",
        "gtr9-ntp6",
        "Recreation and Parks Properties",
        "shape",
        "shape,objectid,property_id,property_name,propertytype,city,acres,ownership,data_as_of,last_edited_date",
        "objectid",
        observation_note="Land owned or maintained by SF Recreation and Parks, including plazas, facilities, gardens and non-park properties. This is not complete park or vegetation coverage. Source observation dates are preserved independently of portal refresh dates.",
    ),
)


def _within(point: list, bounds: dict) -> bool:
    return all(
        bounds["min"][axis] <= point[axis] <= bounds["max"][axis] for axis in range(2)
    )


def _contains(point: list, masks: list[_RingMask]) -> bool:
    return masks[0].contains(point) and not any(
        mask.contains(point) for mask in masks[1:]
    )


def _anchor(rings: list, land: LandMask, bounds: dict) -> list | None:
    """Find a deterministic interior point on known land, including concave areas.

    The centroid is only a candidate: it may sit in a hole or outside a concave
    polygon. Horizontal scan intervals supply actual interior alternatives.
    """
    masks = [_RingMask(ring) for ring in rings]
    _, centroid = _polygon_centroid(rings)

    def accepted(point: list) -> bool:
        return (
            _within(point, bounds)
            and _contains(point, masks)
            and land.polygon_at(point) is not None
        )

    if accepted(centroid):
        return centroid
    local_bounds = bounds_of(rings[0])
    bottom = max(local_bounds["min"][1], bounds["min"][1])
    top = min(local_bounds["max"][1], bounds["max"][1])
    if top <= bottom:
        return None
    levels = [(bottom + top) / 2]
    levels += [bottom + (top - bottom) * (index + 0.5) / 32 for index in range(32)]
    candidates = []
    for north in levels:
        crossings = []
        for ring in rings:
            for first, second in zip(ring, ring[1:] + ring[:1]):
                if (first[1] > north) != (second[1] > north):
                    crossings.append(
                        first[0]
                        + (north - first[1])
                        * (second[0] - first[0])
                        / (second[1] - first[1])
                    )
        crossings.sort()
        for left, right in zip(crossings[::2], crossings[1::2]):
            left = max(left, bounds["min"][0])
            right = min(right, bounds["max"][0])
            if right <= left:
                continue
            point = [round((left + right) / 2, 3), round(north, 3), 0.0]
            if accepted(point):
                candidates.append((math.dist(point[:2], centroid[:2]), point))
    return min(candidates)[1] if candidates else None


def normalize_places(
    features: dict[str, Iterable[dict]], geography: dict, graph: dict
) -> tuple[list[dict], list[dict], dict]:
    """Normalize names/areas and choose camera targets without inventing places."""
    projection = LocalProjection()
    land = LandMask(geography["land"])
    bounds = geography["bounds"]
    used_nodes = {edge[key] for edge in graph["edges"] for key in ("from", "to")}
    nodes = [
        node
        for node in graph["nodes"]
        if node["id"] in used_nodes
        and _within(node["position"], bounds)
        and land.polygon_at(node["position"]) is not None
    ]
    nodes.sort(key=lambda node: node["id"])
    places, areas = [], []
    seen: set[str] = set()
    statistics: Counter = Counter()
    for source in SOURCES:
        for feature in features[source.key]:
            statistics[source.key + "_source_records"] += 1
            properties = feature.get("properties") or {}
            name = properties.get(
                "nhood" if source.key == "neighborhoods" else "property_name"
            )
            source_id = properties.get(
                "nhood" if source.key == "neighborhoods" else "property_id"
            )
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(source_id, str)
                or not source_id.strip()
            ):
                raise ValueError("Place source requires a name and stable identifier")
            name, source_id = name.strip(), source_id.strip()
            kind = "neighborhood" if source.key == "neighborhoods" else "park"
            identity = f"sf-{kind}:{source_id}"
            if identity in seen:
                raise ValueError(f"Duplicate place source identifier: {identity}")
            seen.add(identity)
            if kind == "park" and properties.get("city") != "San Francisco":
                statistics["outside_sf_city_records"] += 1
                continue
            geometry = feature.get("geometry") or {}
            if geometry.get("type") == "MultiPolygon":
                polygons = geometry.get("coordinates", [])
            elif geometry.get("type") == "Polygon":
                polygons = [geometry.get("coordinates", [])]
            else:
                raise ValueError(f"Place requires Polygon or MultiPolygon: {identity}")
            valid_parts = []
            for part, polygon in enumerate(polygons):
                rings = [
                    _project_points(ring, projection, ring=True) for ring in polygon
                ]
                if not rings:
                    raise ValueError(f"Place polygon has no rings: {identity}")
                area, _ = _polygon_centroid(rings)
                anchor = _anchor(rings, land, bounds)
                if anchor is None:
                    statistics["parts_without_known_land_anchor"] += 1
                    continue
                valid_parts.append(
                    {"part": part, "rings": rings, "area_m2": area, "anchor": anchor}
                )
            if not valid_parts:
                statistics["records_without_known_land_anchor"] += 1
                continue
            primary = min(
                valid_parts, key=lambda item: (-item["area_m2"], item["part"])
            )
            target = primary["anchor"]
            place_bounds = bounds_of(
                point for item in valid_parts for point in item["rings"][0]
            )
            span = max(
                place_bounds["max"][axis] - place_bounds["min"][axis]
                for axis in range(2)
            )
            # A nearby source street node is a navigation aid, not an entrance or
            # an assertion that the park has an accessible path at that location.
            nearest = (
                min(
                    nodes,
                    key=lambda node: (
                        math.dist(node["position"][:2], target[:2]),
                        node["id"],
                    ),
                )
                if nodes
                else None
            )
            entry: dict[str, Any] = {
                "id": identity,
                "name": name,
                "kind": kind,
                "source_key": source.key,
                "source_id": source_id,
                "bounds": place_bounds,
                "target": target,
                "view_distance_m": round(max(200.0, min(16000.0, span * 1.55)), 3),
                "polygon_parts": len(valid_parts),
                "area_m2": round(sum(item["area_m2"] for item in valid_parts), 3),
            }
            if nearest:
                entry["walk_position"] = nearest["position"]
                entry["walk_node_id"] = nearest["id"]
                entry["walk_target_distance_m"] = round(
                    math.dist(nearest["position"][:2], target[:2]), 3
                )
            if kind == "park":
                entry.update(
                    {
                        "property_type": properties.get("propertytype"),
                        "data_as_of": properties.get("data_as_of"),
                        "ownership": properties.get("ownership"),
                    }
                )
            places.append(entry)
            areas.append(
                {
                    "id": identity,
                    "polygons": [
                        {
                            "part": item["part"],
                            "rings": item["rings"],
                            "area_m2": item["area_m2"],
                        }
                        for item in valid_parts
                    ],
                }
            )
            statistics[source.key + "_destinations"] += 1
    places.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    areas.sort(key=lambda item: item["id"])
    return places, areas, dict(statistics)


def build_places(indexes: dict[str, dict], geography_path: str | Path) -> dict:
    path = Path(geography_path).resolve()
    raw = path.read_bytes()
    geography = json.loads(raw)
    if content_hash(
        {key: value for key, value in geography.items() if key != "sha256"}
    ) != geography.get("sha256"):
        raise ValueError("Geography manifest checksum mismatch")
    graph_raw = inside(path.parent, geography["graph_path"]).read_bytes()
    if (
        hashlib.sha256(graph_raw).hexdigest()
        != geography["files"][geography["graph_path"]]
    ):
        raise ValueError("Street graph checksum mismatch")
    places, areas, statistics = normalize_places(
        {key: cached_features(index) for key, index in indexes.items()},
        geography,
        json.loads(graph_raw),
    )
    areas_raw = canonical_bytes({"schema_version": 1, "areas": areas})
    atomic_write(path.parent / "places-areas.json", areas_raw)
    sources = {}
    for source in SOURCES:
        index = indexes[source.key]
        sources[source.key] = {
            key: index[key]
            for key in (
                "id",
                "title",
                "url",
                "license",
                "metadata_sha256",
                "source_rows_updated_at",
                "retrieved_at",
                "pages",
            )
        }
        sources[source.key]["observation_note"] = source.observation_note
    result = {
        "schema_version": 1,
        "geography_sha256": geography["sha256"],
        "geography_file_sha256": hashlib.sha256(raw).hexdigest(),
        "sources": sources,
        "places": places,
        "areas_path": "places-areas.json",
        "areas_sha256": hashlib.sha256(areas_raw).hexdigest(),
        "statistics": statistics,
        "note": "Named navigation uses analysis neighborhoods and SF Recreation and Parks properties. It is not an official neighborhood boundary, complete park coverage, vegetation classification, entrance survey or accessibility assessment. Targets lie on known source land; walk targets use nearby source street nodes.",
    }
    result["sha256"] = content_hash(result)
    atomic_write(path.parent / "places-index.json", canonical_bytes(result))
    return {
        "output": str(path.parent / "places-index.json"),
        "sha256": result["sha256"],
        "statistics": statistics,
        "index_bytes": len(canonical_bytes(result)),
        "areas_bytes": len(areas_raw),
    }
