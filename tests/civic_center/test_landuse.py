"""Parcel groups, uncertain joins and source snapshots keep their real meaning."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from civic_center.landuse import (
    FIELDS,
    LandUseIndex,
    fetch_landuse,
    normalize_rows,
    parcel_keys,
)


def row(
    identity="group-a", parcels="'0787001', '0787002'", units="4", commercial="1000"
):
    return {
        "ludb_id": identity,
        "mapblklot": parcels,
        "resunits": units,
        "resunits_s": "7",
        "total_comm": commercial,
        "cie": commercial,
        "mips": "0",
        "retail": "0",
        "med": "0",
        "pdr": "0",
        "visitor": "0",
        "geography_type": "multiple_parcels",
        "data_as_of": "2026-08-17T00:00:00.000",
    }


def test_groups_count_units_once_and_preserve_distinct_special_beds():
    data = normalize_rows([row()], {"license_id": "CC0_10"})
    index = LandUseIndex(data)
    buildings = [
        {"id": "a", "mblr": "SF0787001", "area_m2": 20},
        {"id": "b", "mblr": "SF0787001", "area_m2": 30},
        {"id": "c", "mblr": "SF0787002", "area_m2": 50},
    ]
    matches, stats = index.match_buildings(buildings)
    assert stats["matched_residential_units_counted_once"] == 4
    assert stats["matched_commercial_area_sqft_counted_once"] == 1000
    assert sum(value["home_weight"] for value in matches.values()) == pytest.approx(4)
    assert sum(value["work_weight"] for value in matches.values()) == pytest.approx(
        1000
    )
    assert matches["c"]["footprint_share"] == 0.5
    assert matches["c"]["special_units_or_beds_in_source_group"] == 7
    assert data["statistics"]["residential_units"] == 4
    assert data["statistics"]["special_units_or_beds"] == 7


def test_ambiguous_and_unknown_parcels_do_not_become_arbitrary_homes():
    data = normalize_rows([row("a", "0787001"), row("b", "0787001")], {})
    index = LandUseIndex(data)
    matches, stats = index.match_buildings(
        [
            {"id": "ambiguous", "mblr": "SF0787001"},
            {"id": "unknown", "mblr": "SF9999001"},
            {"id": "invalid", "mblr": None},
        ]
    )
    assert matches == {}
    assert (
        stats["ambiguous_footprints"]
        == stats["unmatched_footprints"]
        == stats["invalid_footprint_parcel"]
        == 1
    )
    assert index.lookup("SF0787001") is None


@pytest.mark.parametrize(
    "units,commercial", [("NaN", "-1"), ("1.5", "Infinity"), (None, None)]
)
def test_unknown_counts_are_not_eligible_or_silently_zero_observations(
    units, commercial
):
    data = normalize_rows([row(units=units, commercial=commercial)], {})
    assert data["records"][0]["residential_units"] is None
    assert data["records"][0]["commercial_area_sqft"] is None
    matches, _ = LandUseIndex(data).match_buildings([{"id": "a", "mblr": "SF0787001"}])
    assert not matches["a"]["home_eligible"] and not matches["a"]["work_eligible"]


def test_parcel_normalization_accepts_known_group_syntax_only():
    assert parcel_keys("'0787002', '0787001', '0787001'") == ("0787001", "0787002")
    assert parcel_keys("SF3490A037") == ("3490A037",)
    assert parcel_keys("0787001, unknown") == ()
    assert parcel_keys("Analytical geometry") == ()
    assert parcel_keys(None) == ()


def test_duplicate_records_and_changed_normalized_content_fail():
    with pytest.raises(ValueError, match="duplicate"):
        normalize_rows([row(), row()], {})
    data = normalize_rows([row()], {})
    data["records"][0]["residential_units"] = 999
    with pytest.raises(ValueError, match="checksum"):
        LandUseIndex(data)


def fake_source(*, update_during_fetch=False, license_id="CC0_10"):
    requests = []
    rows = [row("a", "0787001"), row("b", "0787002"), row("c", "0787003")]

    def request(url):
        requests.append(url)
        if "/api/views/" in url:
            metadata_calls = sum("/api/views/" in value for value in requests)
            value = {
                "name": "Land Use",
                "licenseId": license_id,
                "rowsUpdatedAt": 2 if update_during_fetch and metadata_calls > 1 else 1,
                "columns": [{"fieldName": field} for field in FIELDS],
            }
        else:
            query = parse_qs(urlparse(url).query)
            if "count(*)" in query["$select"][0]:
                value = [{"count": "3"}]
            else:
                offset, limit = int(query["$offset"][0]), int(query["$limit"][0])
                value = rows[offset : offset + limit]
        return value, json.dumps(value).encode()

    return request, requests


def test_paginated_source_reuses_verified_offline_cache_and_detects_corruption(
    tmp_path,
):
    request, calls = fake_source()
    index, rows = fetch_landuse(
        tmp_path, page_size=2, request=request, progress=lambda _: None
    )
    assert len(rows) == index["row_count"] == 3 and index["complete"]
    assert len(index["pages"]) == 2
    number = len(calls)
    cached, cached_rows = fetch_landuse(
        tmp_path, page_size=2, offline=True, request=request
    )
    assert cached == index and cached_rows == rows and len(calls) == number
    page = next(tmp_path.rglob("page-0000000.json"))
    page.write_text("[]")
    with pytest.raises(ValueError, match="checksum"):
        fetch_landuse(tmp_path, page_size=2, offline=True, request=request)


def test_mid_download_source_update_does_not_publish_complete_cache(tmp_path):
    request, _ = fake_source(update_during_fetch=True)
    with pytest.raises(ValueError, match="updated during"):
        fetch_landuse(tmp_path, page_size=2, request=request, progress=lambda _: None)
    assert not json.loads(next(tmp_path.rglob("index.json")).read_bytes())["complete"]


def test_source_license_change_fails_before_any_page_download(tmp_path):
    request, calls = fake_source(license_id="changed")
    with pytest.raises(ValueError, match="license changed"):
        fetch_landuse(tmp_path, request=request)
    assert len(calls) == 1
