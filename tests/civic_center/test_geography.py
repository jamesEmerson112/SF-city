"""Small deterministic offline fixtures for municipal geometry normalization."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from civic_center import geography
from civic_center.geography import (
    LandMask,
    LocalProjection,
    Source,
    cached_features,
    canonical_bytes,
    content_hash,
    fetch_source,
    normalize_buildings,
    normalize_land,
    normalize_streets,
    simplify_line,
    write_geography,
)


@pytest.fixture
def projection():
    return LocalProjection()


def coordinates(points):
    projection = LocalProjection()
    return [projection.to_lonlat(*point[:2]) for point in points]


def street(cnn="1", points=((0, 0), (10, 0)), **properties):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates(points)},
        "properties": {
            "cnn": cnn,
            "active": True,
            "layer": "STREETS",
            "classcode": "5",
            "f_node_cnn": "10.0",
            "t_node_cnn": "20.0",
            "oneway": "F",
            "streetname": "FIXTURE STREET",
            **properties,
        },
    }


def building(
    identity="201006.0000001",
    outer=((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)),
    holes=(),
    **properties,
):
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [coordinates(outer)] + [coordinates(hole) for hole in holes],
        },
        "properties": {
            "sf16_bldgid": identity,
            "hgt_median_m": "12.25",
            "gnd_min_m": "100",
            "peak_1st_m": "117.5",
            "mblr": "FIXTURE-PARCEL",
            **properties,
        },
    }


def shoreline():
    return {
        "type": "Feature",
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    coordinates(
                        [
                            (-100, -100),
                            (100, -100),
                            (100, 100),
                            (-100, 100),
                            (-100, -100),
                        ]
                    )
                ],
                [
                    coordinates(
                        [
                            (1000, 1000),
                            (1010, 1000),
                            (1010, 1010),
                            (1000, 1010),
                            (1000, 1000),
                        ]
                    )
                ],
            ],
        },
        "properties": {"objectid": "1"},
    }


@pytest.mark.parametrize(
    "longitude,latitude",
    [
        (-122.4193, 37.7793),
        (-122.515, 37.708),
        (-122.35, 37.83),
        (-123.0, 37.7),
    ],
)
def test_projection_roundtrips_city_limits_and_outlying_islands(
    projection, longitude, latitude
):
    local = projection.to_local(longitude, latitude)
    assert projection.to_lonlat(*local[:2]) == pytest.approx(
        [longitude, latitude], abs=1e-10
    )
    assert local[2] == 0


def test_projection_origin_axis_scale_and_independent_vertical(projection):
    assert projection.to_local(-122.4193, 37.7793) == [0, 0, 0]
    assert projection.to_local(*projection.to_lonlat(1, 0), z=17.61) == pytest.approx(
        [1, 0, 17.61], abs=1e-6
    )
    assert projection.to_local(*projection.to_lonlat(0, 1)) == pytest.approx(
        [0, 1, 0], abs=1e-6
    )
    # WGS84 latitude and longitude arc lengths at the origin, independently
    # calculated from the meridional/prime-vertical radii of curvature.
    latitude = math.radians(projection.origin_latitude)
    eccentricity_squared = 6.6943799901413165e-3
    denominator = 1 - eccentricity_squared * math.sin(latitude) ** 2
    meridional = 6378137 * (1 - eccentricity_squared) / denominator**1.5
    prime_vertical = 6378137 / math.sqrt(denominator)
    north = projection.to_local(
        projection.origin_longitude, projection.origin_latitude + 1e-5
    )
    east = projection.to_local(
        projection.origin_longitude + 1e-5, projection.origin_latitude
    )
    assert north[1] == pytest.approx(meridional * math.radians(1e-5), abs=1e-7)
    assert east[0] == pytest.approx(
        prime_vertical * math.cos(latitude) * math.radians(1e-5), abs=1e-7
    )


@pytest.mark.parametrize(
    "coordinate", [(float("nan"), 0), (0, float("inf")), (181, 30), (-122, 91)]
)
def test_projection_rejects_invalid_coordinates(projection, coordinate):
    with pytest.raises(ValueError):
        projection.to_local(*coordinate)


def test_street_graph_uses_official_nodes_and_retains_bend_vertices():
    features = [
        street(points=[(0, 0), (5, 1), (10, 0)]),
        street("2", [(10, 0.02), (15, 5)], f_node_cnn="20", t_node_cnn="30"),
    ]
    streets, graph, statistics = normalize_streets(features)
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert len(streets) == 2
    assert len(nodes) == 4
    assert nodes["sf-node:20"]["position"] == [10, 0, 0]
    assert nodes["sf-bend:1:0:1"]["position"] == [5, 1, 0]
    assert len(graph["edges"]) == 3
    assert graph["maximum_endpoint_snap_m"] == 0.02
    assert all(edge["bidirectional"] for edge in graph["edges"])
    assert streets[0]["motor_oneway"] == "F"
    assert "inferred" in streets[0]["width_source"]
    assert statistics["graph_nodes"] == 4
    assert normalize_streets(list(reversed(features))) == (streets, graph, statistics)


def test_nonphysical_roads_are_excluded_and_freeway_private_not_walkable():
    features = [
        street("1"),
        street("2", active=False),
        street("3", layer="PAPER_WATER"),
        street("4", layer="PSEUDO"),
        street("5", layer="FREEWAYS", classcode="1"),
        street("6", layer="PRIVATE"),
        street("7", layer="STREETS", classcode="6"),
    ]
    streets, graph, statistics = normalize_streets(features)
    assert {record["source_id"] for record in streets} == {"1", "5", "6", "7"}
    assert {edge["source_street_id"] for edge in graph["edges"]} == {"1"}
    assert statistics["excluded_retired"] == 1
    assert statistics["excluded_paper_or_pseudo"] == 2
    assert statistics["excluded_from_walking_graph"] == 3


def test_geometric_crossing_does_not_invent_an_intersection():
    _, graph, _ = normalize_streets(
        [
            street("1", [(-10, 0), (10, 0)], f_node_cnn="1", t_node_cnn="2"),
            street("2", [(0, -10), (0, 10)], f_node_cnn="3", t_node_cnn="4"),
        ]
    )
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 2
    assert all(node["position"] != [0, 0, 0] for node in graph["nodes"])


def test_inconsistent_source_intersections_are_partitioned_with_bounded_snap():
    features = [
        street("1", [(0, 0), (10, 0)], f_node_cnn="1", t_node_cnn="2"),
        street("2", [(1000, 0), (1010, 0)], f_node_cnn="1", t_node_cnn="3"),
        street("3", [(1, 0), (0, 10)], f_node_cnn="1", t_node_cnn="4"),
    ]
    _, graph, statistics = normalize_streets(features)
    conflicting = [node for node in graph["nodes"] if node.get("source_node_id") == "1"]
    assert len(conflicting) == 2
    assert all(node["source_node_conflict"] for node in conflicting)
    assert graph["ambiguous_source_node_count"] == 1
    assert graph["source_endpoint_maximum_disagreement_m"] == 1000
    assert graph["maximum_endpoint_snap_m"] == 1
    assert graph["maximum_endpoint_snap_m"] <= graph["junction_tolerance_m"]
    assert statistics["ambiguous_source_nodes"] == 1
    assert normalize_streets(list(reversed(features)))[1] == graph
    from civic_center.routing import WalkingGraph

    WalkingGraph(graph["nodes"], graph["edges"])


def test_missing_and_sentinel_intersection_ids_do_not_connect_streets():
    _, graph, _ = normalize_streets(
        [
            street("1", [(0, 0), (10, 0)], f_node_cnn="0", t_node_cnn="-1"),
            street("2", [(100, 0), (110, 0)], f_node_cnn=None, t_node_cnn="0"),
        ]
    )
    assert len(graph["nodes"]) == 4
    assert all("source_node_id" not in node for node in graph["nodes"])


def test_duplicate_source_ids_raise_instead_of_silently_merging():
    with pytest.raises(ValueError, match="duplicate"):
        normalize_streets([street(), street()])
    with pytest.raises(ValueError, match="duplicate"):
        normalize_buildings([building(), building()])


def test_building_preserves_courtyard_ground_datum_and_measured_height():
    hole = [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]
    buildings, statistics = normalize_buildings([building(holes=[hole])])
    record = buildings[0]
    assert len(record["rings"]) == 2
    assert record["footprint"] == record["rings"][0]
    assert len(record["footprint"]) == 4
    assert record["area_m2"] == 96
    assert record["centroid"] == [5.125, 5.125, 0]
    assert record["height_m"] == 12.25
    assert record["ground_elevation_navd88_m"] == 100
    assert record["roof_peak_elevation_navd88_m"] == 117.5
    assert all(point[2] == 0 for ring in record["rings"] for point in ring)
    assert record["use"] is None
    assert statistics["parts_with_holes"] == 1


@pytest.mark.parametrize("height", [None, "0", "-1", "nan", "invalid"])
def test_missing_building_height_is_explicitly_estimated(height):
    buildings, statistics = normalize_buildings([building(hgt_median_m=height)])
    assert buildings[0]["height_m"] == 6
    assert "estimated" in buildings[0]["height_source"]
    assert statistics["estimated_height_parts"] == 1


def test_multipolygon_parts_keep_distinct_ids_and_shared_source_id():
    first, second = building(), building(
        outer=[(20, 0), (30, 0), (30, 10), (20, 10), (20, 0)]
    )
    first["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [
            first["geometry"]["coordinates"],
            second["geometry"]["coordinates"],
        ],
    }
    buildings, _ = normalize_buildings([first])
    assert [record["id"] for record in buildings] == [
        "sf-building:201006.0000001:part:0",
        "sf-building:201006.0000001:part:1",
    ]
    assert len({record["source_id"] for record in buildings}) == 1


def test_land_retains_mainland_and_separate_island():
    land = normalize_land([shoreline()])
    assert len(land) == 2
    assert land[0]["bounds"]["min"] == [-100, -100]
    assert land[1]["bounds"]["min"] == [1000, 1000]
    assert len(land[1]["points"]) == 4


def test_land_membership_respects_islands_holes_and_offshore_points():
    feature = shoreline()
    feature["geometry"]["coordinates"][0].append(
        coordinates([(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)])
    )
    land = normalize_land([feature])
    mask = LandMask(land)
    assert mask.polygon_at([50, 0, 0]) == land[0]["id"]
    assert mask.polygon_at([1005, 1005, 0]) == land[1]["id"]
    assert mask.polygon_at([0, 0, 0]) is None
    assert mask.polygon_at([500, 500, 0]) is None
    assert mask.polygon_at([-100, 0, 0]) == land[0]["id"]


def test_simplification_preserves_endpoints_and_real_bends():
    points = [[0, 0, 0], [2, 0.001, 0], [4, 0, 0], [5, 5, 0], [10, 5, 0]]
    assert simplify_line(points, 0.01) == [points[index] for index in (0, 2, 3, 4)]


def test_tiled_artifacts_are_deterministic_complete_and_checksummed(tmp_path):
    streets = [street(points=[(-10, 0), (510, 0)])]
    buildings = [building(outer=[(490, 0), (510, 0), (510, 10), (490, 10), (490, 0)])]
    result = write_geography(streets, buildings, [shoreline()], tmp_path)
    manifest_path = tmp_path / "sf-geography.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["sha256"] == content_hash(
        {key: value for key, value in manifest.items() if key != "sha256"}
    )
    assert manifest["origin"] == {"longitude": -122.4193, "latitude": 37.7793}
    for path, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / path).read_bytes()).hexdigest() == digest
    index = json.loads((tmp_path / manifest["building_index_path"]).read_bytes())[
        "buildings"
    ]
    tile_record = next(
        tile for tile in manifest["tiles"] if tile["id"] == index[0]["tile_id"]
    )
    tile = json.loads((tmp_path / tile_record["path"]).read_bytes())
    assert tile["buildings"][0]["id"] == index[0]["id"]
    assert tile_record["bounds"]["min"][0] <= 490
    assert manifest["statistics"]["building_count"] == 1
    assert manifest["land_bounds"]["max"] == [1010, 1010]
    assert manifest["bounds"]["max"][0] == 510
    assert result == write_geography(streets, buildings, [shoreline()], tmp_path)
    assert manifest_path.read_bytes() == manifest_raw


@pytest.fixture
def source_cache(monkeypatch, tmp_path):
    source = Source(
        "fixture", "abcd-1234", "Offline fixture", "line", "line,cnn", "cnn"
    )
    records = [street("1"), street("2"), street("3")]
    calls = []
    metadata = {
        "rowsUpdatedAt": 123,
        "licenseId": "PDDL",
        "license": {"name": "PDDL", "termsLink": geography.PDDL_URL},
        "columns": [{"fieldName": "line"}, {"fieldName": "cnn"}],
    }

    def request(url, **_kwargs):
        from urllib.parse import parse_qs, urlparse

        calls.append(url)
        query = parse_qs(urlparse(url).query)
        if "/api/views/" in url:
            result = deepcopy(metadata)
        elif urlparse(url).path.endswith(".json"):
            result = [{"count": "3"}]
        else:
            offset, limit = int(query["$offset"][0]), int(query["$limit"][0])
            result = {
                "type": "FeatureCollection",
                "features": records[offset : offset + limit],
                "crs": {"properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            }
        return result, canonical_bytes(result)

    monkeypatch.setattr(geography, "_request_json", request)
    return source, records, calls, metadata, tmp_path


def test_paginated_cache_retains_urls_counts_and_offline_checksums(
    source_cache, monkeypatch
):
    source, records, calls, _metadata, root = source_cache
    index = fetch_source(source, root, page_size=2)
    assert index["feature_count"] == 3
    assert [page["feature_count"] for page in index["pages"]] == [2, 1]
    assert list(cached_features(index)) == records
    assert len(calls) == 5
    monkeypatch.setattr(
        geography,
        "_request_json",
        lambda *_args, **_kwargs: pytest.fail("offline mode used network"),
    )
    assert fetch_source(source, root, page_size=2, offline=True) == index


def test_corrupt_cache_is_rejected_instead_of_used_offline(source_cache):
    source, _records, _calls, _metadata, root = source_cache
    index = fetch_source(source, root, page_size=2)
    page = (
        root
        / source.dataset_id
        / content_hash(index["source_query"])[:16]
        / index["pages"][0]["file"]
    )
    page.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        fetch_source(source, root, page_size=2, offline=True)


def test_corrupt_cached_metadata_is_rejected(source_cache):
    source, _records, _calls, _metadata, root = source_cache
    index = fetch_source(source, root, page_size=2)
    metadata_path = Path(index["cache_folder"]) / "metadata.json"
    metadata_path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata failed checksum"):
        fetch_source(source, root, page_size=2, offline=True)


@pytest.mark.parametrize(
    "retry_after,expected_delay",
    [
        ("3", 3.0),
        ("-5", 0.0),
        ("Thu, 01 Jan 2099 00:00:00 GMT", 20.0),
        ("not a valid delay", 1.0),
        ("nan", 1.0),
    ],
)
def test_transient_download_retry_handles_retry_after(
    monkeypatch, retry_after, expected_delay
):
    import io
    from urllib.error import HTTPError

    attempts = []
    sleeps = []

    def request(*_args, **_kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise HTTPError(
                "https://data.sfgov.org/example",
                429,
                "Too Many Requests",
                {"Retry-After": retry_after},
                None,
            )
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(geography, "urlopen", request)
    monkeypatch.setattr(geography.time, "sleep", sleeps.append)
    assert geography._request_json("https://data.sfgov.org/example")[0] == {"ok": True}
    assert sleeps == [expected_delay]
    assert len(attempts) == 2


def test_offline_missing_cache_never_accesses_network(source_cache, monkeypatch):
    source, _records, _calls, _metadata, root = source_cache
    monkeypatch.setattr(
        geography,
        "_request_json",
        lambda *_args, **_kwargs: pytest.fail("offline mode used network"),
    )
    with pytest.raises(FileNotFoundError):
        fetch_source(source, root, offline=True)


def test_unreviewed_license_or_changed_schema_blocks_import(source_cache):
    source, _records, _calls, metadata, root = source_cache
    metadata["licenseId"] = "different"
    with pytest.raises(ValueError, match="license"):
        fetch_source(source, root)
    metadata["licenseId"] = "PDDL"
    metadata["columns"] = [{"fieldName": "cnn"}]
    with pytest.raises(ValueError, match="schema"):
        fetch_source(source, root)
