"""Official parcel uses, with explicit groups and conservative footprint joins.

The source describes properties, not observed residents or employers. A parcel
group's residential units and commercial area are counted once. Relative weights
among its matched footprints are an allocation assumption, never building counts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Callable, Iterable
from urllib.parse import urlencode

from .geography import _request_json, atomic_write, canonical_bytes, content_hash
from .package_verify import inside

SOURCE_ID = "c5ge-t6pj"
SOURCE_URL = "https://data.sfgov.org/d/c5ge-t6pj"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
FIELDS = (
    "ludb_id",
    "mapblklot",
    "resunits",
    "resunits_s",
    "cie",
    "med",
    "mips",
    "retail",
    "pdr",
    "visitor",
    "total_comm",
    "residentia",
    "geography_type",
    "parking_lo",
    "garage",
    "open_space",
    "major_mult",
    "special_jurisdiction",
    "data_as_of",
    "data_loaded_at",
)
COMMERCIAL_FIELDS = ("cie", "med", "mips", "retail", "pdr", "visitor")


def parcel_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().strip("'\"").upper()
    if value.startswith("SF"):
        value = value[2:]
    return value if re.fullmatch(r"[0-9]{4}[A-Z0-9]{3,8}", value) else None


def parcel_keys(value: object) -> tuple[str, ...]:
    """Accept known single/group syntax; never guess partially malformed groups."""
    if not isinstance(value, str) or not value.strip():
        return ()
    tokens = value.strip().strip("[]").split(",")
    keys = [parcel_key(token) for token in tokens]
    return tuple(sorted(set(keys))) if all(keys) else ()


def _nonnegative(value: object, integer: bool = False) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or (integer and not number.is_integer()):
        return None
    return int(number) if integer else number


def normalize_rows(rows: Iterable[dict], source: dict) -> dict:
    records = []
    seen = set()
    statistics = Counter()
    dates = Counter()
    types = Counter()
    for raw in rows:
        identity = raw.get("ludb_id")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Land-use source has a missing or duplicate record ID")
        seen.add(identity)
        parcels = parcel_keys(raw.get("mapblklot"))
        units = _nonnegative(raw.get("resunits"), integer=True)
        special = _nonnegative(raw.get("resunits_s"), integer=True)
        commercial = _nonnegative(raw.get("total_comm"))
        areas = {key: _nonnegative(raw.get(key)) for key in COMMERCIAL_FIELDS}
        statistics["records"] += 1
        statistics["records_without_joinable_parcels"] += not bool(parcels)
        statistics["multiple_parcel_records"] += len(parcels) > 1
        statistics["unknown_residential_units"] += units is None
        statistics["unknown_special_units"] += special is None
        statistics["unknown_commercial_area"] += commercial is None
        if commercial is not None and all(
            value is not None for value in areas.values()
        ):
            statistics["commercial_component_mismatches"] += (
                abs(sum(areas.values()) - commercial) > 1.0
            )
        statistics["residential_units"] += units or 0
        statistics["special_units_or_beds"] += special or 0
        statistics["commercial_area_sqft"] += commercial or 0
        dates[str(raw.get("data_as_of", "unknown"))] += 1
        types[str(raw.get("geography_type", "unknown"))] += 1
        records.append(
            {
                "id": identity,
                "parcels": list(parcels),
                "parcel_expression": raw.get("mapblklot"),
                "geography_type": raw.get("geography_type"),
                "residential_units": units,
                "special_units_or_beds": special,
                "commercial_area_sqft": commercial,
                "commercial_by_use_sqft": areas,
                "residential_type": raw.get("residentia"),
                "parking_lot": raw.get("parking_lo"),
                "garage": raw.get("garage"),
                "open_space": raw.get("open_space"),
                "major_multiphase_project": raw.get("major_mult"),
                "special_jurisdiction": raw.get("special_jurisdiction"),
                "data_as_of": raw.get("data_as_of"),
            }
        )
    records.sort(key=lambda row: row["id"])
    result = {
        "schema_version": 1,
        "id": "san-francisco-parcel-land-use",
        "source": source,
        "records": records,
        "statistics": {
            **statistics,
            "observation_dates": dict(dates),
            "geography_types": dict(types),
        },
        "limitations": [
            "Source counts belong to a parcel or parcel group, not every footprint joined to it.",
            "Exact historical parcel IDs are used; unmatched, analytical and ambiguous joins remain explicit.",
            "Residential units are not residents; commercial square feet are not observed jobs.",
            "Special residential units can represent beds and are kept separate from ordinary dwelling units.",
            "Footprint allocation weights use relative area among matched buildings, not surveyed internal uses.",
        ],
    }
    result["sha256"] = content_hash(result)
    return result


class LandUseIndex:
    def __init__(self, data: dict):
        if data.get("schema_version") != 1 or not isinstance(data.get("records"), list):
            raise ValueError("Unsupported land-use schema")
        if content_hash(
            {key: value for key, value in data.items() if key != "sha256"}
        ) != data.get("sha256"):
            raise ValueError("Land-use checksum mismatch")
        self.data = data
        self.records = {}
        self.by_parcel = defaultdict(list)
        for record in data["records"]:
            if record["id"] in self.records:
                raise ValueError("Duplicate normalized land-use record")
            self.records[record["id"]] = record
            for key in record["parcels"]:
                if parcel_key(key) != key:
                    raise ValueError("Invalid normalized parcel key")
                self.by_parcel[key].append(record)

    @classmethod
    def load(cls, path: str | Path) -> "LandUseIndex":
        return cls(json.loads(Path(path).read_bytes()))

    def lookup(self, footprint_parcel: object) -> dict | None:
        matches = self.by_parcel.get(parcel_key(footprint_parcel), [])
        return matches[0] if len(matches) == 1 else None

    def match_buildings(self, buildings: Iterable[dict]) -> tuple[dict, dict]:
        """Return one assignment per uniquely joined footprint and aggregate QA."""
        grouped = defaultdict(list)
        statistics = Counter()
        identities = set()
        for building in buildings:
            identity = building["id"]
            if identity in identities:
                raise ValueError("Duplicate footprint ID in land-use join")
            identities.add(identity)
            statistics["footprints"] += 1
            key = parcel_key(building.get("mblr"))
            matches = self.by_parcel.get(key, [])
            if not key:
                statistics["invalid_footprint_parcel"] += 1
            elif not matches:
                statistics["unmatched_footprints"] += 1
            elif len(matches) != 1:
                statistics["ambiguous_footprints"] += 1
            else:
                grouped[matches[0]["id"]].append(building)
        result = {}
        for identity, group in grouped.items():
            record = self.records[identity]
            areas = [_nonnegative(building.get("area_m2")) or 0.0 for building in group]
            total = sum(areas)
            home_weight = record["residential_units"] or 0
            work_weight = record["commercial_area_sqft"] or 0
            statistics["matched_source_records"] += 1
            statistics["matched_residential_units_counted_once"] += home_weight
            statistics["matched_commercial_area_sqft_counted_once"] += work_weight
            for building, area in zip(group, areas):
                share = area / total if total else 1.0 / len(group)
                result[building["id"]] = {
                    "record_id": identity,
                    "parcel_key": parcel_key(building.get("mblr")),
                    "data_as_of": record["data_as_of"],
                    "home_eligible": home_weight > 0,
                    "work_eligible": work_weight > 0,
                    "home_weight": home_weight * share,
                    "work_weight": work_weight * share,
                    "footprint_share": share,
                    "group_footprint_count": len(group),
                    "residential_units_in_source_group": record["residential_units"],
                    "special_units_or_beds_in_source_group": record[
                        "special_units_or_beds"
                    ],
                    "commercial_area_sqft_in_source_group": record[
                        "commercial_area_sqft"
                    ],
                    "commercial_by_use_sqft_in_source_group": record[
                        "commercial_by_use_sqft"
                    ],
                    "geography_type": record["geography_type"],
                    "source_url": SOURCE_URL,
                    "allocation_note": "Relative footprint area shares a source parcel/group count across matched buildings; generated allocation, not measured building occupancy or jobs.",
                }
                statistics["matched_footprints"] += 1
                statistics["home_eligible_footprints"] += home_weight > 0
                statistics["work_eligible_footprints"] += work_weight > 0
        statistics["unmatched_source_records"] = len(self.records) - len(grouped)
        return result, dict(statistics)


def fetch_landuse(
    cache: Path,
    *,
    offline=False,
    refresh=False,
    page_size=5000,
    request: Callable = _request_json,
    progress: Callable = print,
) -> tuple[dict, list[dict]]:
    if not 1 <= page_size <= 20000:
        raise ValueError("Land-use page size must be between 1 and 20000")
    cache = cache.resolve()
    query = {"$select": ",".join(FIELDS), "$order": "ludb_id", "$limit": str(page_size)}
    directory = cache / SOURCE_ID / content_hash(query)[:16]
    index_path = directory / "index.json"
    if index_path.is_file() and not refresh:
        index = json.loads(index_path.read_bytes())
        if index.get("complete"):
            rows = []
            for descriptor in [index["metadata"], *index["pages"]]:
                raw = inside(directory, descriptor["file"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
                    raise ValueError("Cached land-use checksum mismatch; use --refresh")
                if descriptor is not index["metadata"]:
                    rows.extend(json.loads(raw))
            if len(rows) != index["row_count"]:
                raise ValueError("Cached land-use row count differs")
            return index, rows
    if offline:
        raise ValueError("A complete verified land-use cache is unavailable")
    metadata_url = f"https://data.sfgov.org/api/views/{SOURCE_ID}.json"
    metadata, metadata_raw = request(metadata_url)
    if metadata.get("licenseId") != "CC0_10":
        raise ValueError("Land-use license changed; review source before importing")
    available = {column.get("fieldName") for column in metadata.get("columns", [])}
    if not set(FIELDS).issubset(available):
        raise ValueError("Land-use source fields changed")
    base = f"https://data.sfgov.org/resource/{SOURCE_ID}.json?"
    count, _ = request(base + urlencode({"$select": "count(*) as count"}))
    expected = int(count[0]["count"])
    if not 0 < expected <= 1000000:
        raise ValueError("Unexpected land-use source size")
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(directory / "metadata.json", metadata_raw)
    index = {
        "schema_version": 1,
        "complete": False,
        "source_url": SOURCE_URL,
        "dataset_id": SOURCE_ID,
        "title": metadata.get("name"),
        "license_id": "CC0_10",
        "license_url": LICENSE_URL,
        "rows_updated_at": metadata.get("rowsUpdatedAt"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "file": "metadata.json",
            "url": metadata_url,
            "sha256": hashlib.sha256(metadata_raw).hexdigest(),
        },
        "query": query,
        "pages": [],
        "row_count": expected,
    }
    atomic_write(index_path, canonical_bytes(index))
    rows = []
    for offset in range(0, expected, page_size):
        url = base + urlencode({**query, "$offset": str(offset)})
        data, raw = request(url)
        if not isinstance(data, list) or len(data) != min(page_size, expected - offset):
            raise ValueError("Land-use source page count changed during download")
        name = f"page-{offset:07d}.json"
        atomic_write(directory / name, raw)
        rows.extend(data)
        index["pages"].append(
            {
                "file": name,
                "url": url,
                "rows": len(data),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        progress(f"Land use: {len(rows):,}/{expected:,} records cached")
    latest, _ = request(metadata_url)
    if latest.get("rowsUpdatedAt") != metadata.get("rowsUpdatedAt"):
        raise ValueError("Land-use source updated during download; refresh required")
    if len({row.get("ludb_id") for row in rows}) != expected:
        raise ValueError("Land-use download contains duplicate or missing source IDs")
    index["complete"] = True
    atomic_write(index_path, canonical_bytes(index))
    return index, rows
