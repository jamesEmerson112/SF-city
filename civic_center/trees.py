"""Public street-tree locations with explicitly illustrative display dimensions.

The replacement inventory excludes removed trees and planting sites. It does not
cover every park tree, guarantee current field conditions or measure canopy size.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

from .geography import (
    LandMask,
    LocalProjection,
    Source,
    atomic_write,
    bounds_of,
    cached_features,
    canonical_bytes,
    content_hash,
)

SOURCE = Source(
    "street_trees",
    "uzd4-f6yf",
    "San Francisco Street Tree Inventory",
    "point",
    "point,treeid,species,planttype,mapdbh,planteddate,siteinfo,data_as_of,data_loaded_at",
    "treeid",
    observation_note=(
        "Replacement Public Works CMMS street-tree inventory. The department excludes "
        "removed trees, empty basins and planting sites. Coordinates may be missing "
        "or imprecise and records can lag field conditions. It is not complete park "
        "tree coverage. Source dates are distinct from portal refresh dates."
    ),
)
TILE_SIZE_M = 500
MAX_TREES = 500000
DISPLAY_NOTE = (
    "Tree locations and species text come from the source. Height, canopy width, "
    "trunk thickness, color and shape are illustrative; they are not measured "
    "dimensions, inferred ages or condition assessments. DBH is preserved as a "
    "source attribute; its metadata does not state units and it does not set height."
)


def _text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(f"Tree {label} must be bounded text")
    return value.strip() or None


def display_dimensions(identity: str, species: str | None) -> dict:
    """Stable artistic variation independent of source DBH or observation date."""
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    scientific = (species or "").split("::", 1)[0].strip().casefold()
    genus = scientific.split(" ", 1)[0]
    if genus in {
        "phoenix",
        "washingtonia",
        "trachycarpus",
        "butia",
        "brahea",
        "chamaerops",
    }:
        shape = "palm"
        height = 9.0 + digest[0] / 255.0 * 4.0
        canopy = 4.0 + digest[1] / 255.0 * 1.0
    elif genus in {
        "pinus",
        "sequoia",
        "sequoiadendron",
        "cedrus",
        "picea",
        "abies",
        "cupressus",
        "cupressocyparis",
        "hesperocyparis",
    }:
        shape = "conifer"
        height = 8.0 + digest[0] / 255.0 * 4.0
        canopy = 4.0 + digest[1] / 255.0 * 2.0
    else:
        shape = "broadleaf"
        height = 6.0 + digest[0] / 255.0 * 3.0
        canopy = 4.0 + digest[1] / 255.0 * 2.0
    return {
        "shape": shape,
        "height_m": round(height, 3),
        "canopy_width_m": round(canopy, 3),
        "rotation_degrees": round(digest[2] / 255.0 * 360.0, 3),
        "tint_variant": digest[3] % 4,
        "source": "illustrative-v1",
    }


def _tree_identity(value: object) -> str:
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or not 0 < number <= 2**53
            or number != number.to_integral_value()
        ):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(
            "Tree source requires a positive stable numeric treeid"
        ) from None
    return "sf-tree:" + str(int(number))


def normalize_trees(
    features: Iterable[dict], geography: dict
) -> tuple[list[dict], dict]:
    projection = LocalProjection()
    land = LandMask(geography["land"])
    bounds = geography["bounds"]
    seen: set[str] = set()
    positions: Counter = Counter()
    statistics: Counter = Counter()
    dates: Counter = Counter()
    records = []
    for feature in features:
        statistics["source_records"] += 1
        if statistics["source_records"] > MAX_TREES:
            raise ValueError("Tree inventory exceeds its bounded record limit")
        if not isinstance(feature, dict) or not isinstance(
            feature.get("properties"), dict
        ):
            raise ValueError("Tree feature requires a properties object")
        properties = feature["properties"]
        identity = _tree_identity(properties.get("treeid"))
        if identity in seen:
            raise ValueError(f"Duplicate tree source identifier: {identity}")
        seen.add(identity)
        plant_type = _text(properties.get("planttype"), "planttype")
        if plant_type is None or plant_type.casefold() != "tree":
            statistics["excluded_non_tree_or_unspecified_type"] += 1
            continue
        species = _text(properties.get("species"), "species")
        # Explicit stump/empty-site labels remain exclusions even if a future
        # upstream row is mistakenly classified as a Tree.
        if species and any(
            label in species.casefold()
            for label in (
                "stump",
                "empty basin",
                "planting site",
                "vacant site",
                "removed tree",
            )
        ):
            statistics["excluded_nonliving_site_label"] += 1
            continue
        geometry = feature.get("geometry")
        if geometry is None:
            statistics["missing_coordinates"] += 1
            continue
        coordinates = (
            geometry.get("coordinates") if isinstance(geometry, dict) else None
        )
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) not in (2, 3)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in coordinates
            )
            or not -180 <= coordinates[0] <= 180
            or not -90 <= coordinates[1] <= 90
        ):
            statistics["invalid_coordinates"] += 1
            continue
        # Only the source horizontal position is used; the shared terrain owns Z.
        point = [
            round(value, 3) for value in projection.to_local(*coordinates[:2])[:2]
        ] + [0.0]
        if not all(bounds["min"][i] <= point[i] <= bounds["max"][i] for i in range(2)):
            statistics["outside_urban_bounds"] += 1
            continue
        if land.polygon_at(point) is None:
            statistics["outside_known_source_land"] += 1
            continue
        dbh_raw = properties.get("mapdbh")
        dbh = None
        if dbh_raw is not None:
            try:
                dbh = float(dbh_raw)
            except (ValueError, TypeError):
                pass
            if (
                isinstance(dbh_raw, bool)
                or dbh is None
                or not math.isfinite(dbh)
                or dbh < 0.0
            ):
                statistics["invalid_dbh_attribute"] += 1
                dbh = None
        date = _text(properties.get("data_as_of"), "data_as_of")
        dates[date or "unspecified"] += 1
        record = {
            "id": identity,
            "position": point,
            "species": species,
            "planttype": plant_type,
            "siteinfo": _text(properties.get("siteinfo"), "siteinfo"),
            "planteddate": _text(properties.get("planteddate"), "planteddate"),
            "data_as_of": date,
            "data_loaded_at": _text(properties.get("data_loaded_at"), "data_loaded_at"),
            "dbh_source_value": dbh,
            "dbh_source_units": "not stated in source metadata",
            "display": display_dimensions(identity, species),
        }
        positions[tuple(point[:2])] += 1
        statistics["shape_" + record["display"]["shape"]] += 1
        records.append(record)
    records.sort(key=lambda item: item["id"])
    statistics["renderable_records"] = len(records)
    statistics["coincident_position_groups"] = sum(
        count > 1 for count in positions.values()
    )
    statistics["records_at_coincident_positions"] = sum(
        count for count in positions.values() if count > 1
    )
    statistics["unique_source_positions"] = len(positions)
    return records, {
        **statistics,
        "source_data_as_of_counts": dict(sorted(dates.items())),
    }


def build_trees(source_index: dict, geography_path: str | Path) -> dict:
    if source_index.get("id") != SOURCE.dataset_id:
        raise ValueError("Tree source must be the replacement street-tree inventory")
    path = Path(geography_path).resolve()
    raw = path.read_bytes()
    geography = json.loads(raw)
    if content_hash(
        {key: value for key, value in geography.items() if key != "sha256"}
    ) != geography.get("sha256"):
        raise ValueError("Geography manifest checksum mismatch")
    records, statistics = normalize_trees(cached_features(source_index), geography)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        east, north = record["position"][:2]
        grouped[
            f"{math.floor(east / TILE_SIZE_M)}_{math.floor(north / TILE_SIZE_M)}"
        ].append(record)
    tiles = []
    byte_count = 0
    for identity, trees in sorted(grouped.items()):
        relative = f"tree-tiles/{identity}.json"
        contents = canonical_bytes(
            {"schema_version": 1, "tile_id": identity, "trees": trees}
        )
        atomic_write(path.parent / relative, contents)
        byte_count += len(contents)
        tiles.append(
            {
                "id": identity,
                "path": relative,
                "sha256": hashlib.sha256(contents).hexdigest(),
                "tree_count": len(trees),
                "bounds": bounds_of(item["position"] for item in trees),
            }
        )
    source = {
        key: source_index[key]
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
    source["observation_note"] = SOURCE.observation_note
    result = {
        "schema_version": 1,
        "geography_sha256": geography["sha256"],
        "geography_file_sha256": hashlib.sha256(raw).hexdigest(),
        "source": source,
        "tile_size_m": TILE_SIZE_M,
        "tiles": tiles,
        "statistics": statistics,
        "display_note": DISPLAY_NOTE,
        "position_note": "Horizontal source coordinates are retained in the common local frame. Terrain supplies display elevation. Coincident source points remain separate IDs; no random relocation or duplicate-count population claim is applied.",
    }
    result["sha256"] = content_hash(result)
    atomic_write(path.parent / "tree-index.json", canonical_bytes(result))
    return {
        "output": str(path.parent / "tree-index.json"),
        "sha256": result["sha256"],
        "statistics": statistics,
        "tile_count": len(tiles),
        "tile_bytes": byte_count,
    }
