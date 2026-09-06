"""Offline destination geometry and provenance checks."""

from copy import deepcopy
import hashlib
import json

import pytest

from civic_center.geography import LocalProjection, canonical_bytes, content_hash
from civic_center.places import _anchor, build_places, normalize_places


def feature(name="Test area", rings=None, *, park=False, city="San Francisco"):
    rings = rings or [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]
    projection = LocalProjection()
    properties = (
        {
            "property_id": name,
            "property_name": name,
            "city": city,
            "propertytype": "Mini Park",
            "data_as_of": "2025-12-18",
        }
        if park
        else {"nhood": name}
    )
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [projection.to_lonlat(*point) for point in ring] for ring in rings
            ],
        },
    }


def fixture():
    rings = [[[-100, -100, 0], [100, -100, 0], [100, 100, 0], [-100, 100, 0]]]
    geography = {
        "bounds": {"min": [-100, -100], "max": [100, 100]},
        "land": [{"id": "land", "rings": rings, "area_m2": 40000}],
    }
    graph = {
        "nodes": [
            {"id": "west", "position": [-20, 0, 0]},
            {"id": "east", "position": [20, 0, 0]},
            {"id": "unused", "position": [10, 10, 0]},
        ],
        "edges": [{"from": "west", "to": "east"}],
    }
    return geography, graph


def test_source_names_deterministic_targets_and_nearby_street():
    geography, graph = fixture()
    sources = {
        "neighborhoods": [feature("Zulu"), feature("Alpha")],
        "parks": [feature("Garden", park=True)],
    }
    places, areas, counts = normalize_places(sources, geography, graph)
    assert [place["name"] for place in places] == ["Alpha", "Garden", "Zulu"]
    assert places[0]["target"] == [10, 10, 0]
    assert places[0]["walk_position"] == [20, 0, 0]
    assert places[0]["walk_node_id"] == "east"
    assert places[1]["data_as_of"] == "2025-12-18"
    assert counts["neighborhoods_destinations"] == 2
    assert len(areas) == 3
    assert normalize_places(
        {"neighborhoods": sources["neighborhoods"][::-1], "parks": sources["parks"]},
        geography,
        graph,
    ) == (places, areas, counts)


def test_centroid_in_hole_gets_an_actual_interior_target():
    geography, graph = fixture()
    outer = [[-30, -30], [30, -30], [30, 30], [-30, 30], [-30, -30]]
    hole = [[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]]
    places, areas, _ = normalize_places(
        {"neighborhoods": [feature(rings=[outer, hole])], "parks": []}, geography, graph
    )
    target = places[0]["target"]
    assert not (-10 <= target[0] <= 10 and -10 <= target[1] <= 10)
    assert -30 < target[0] < 30 and -30 < target[1] < 30
    assert len(areas[0]["polygons"][0]["rings"]) == 2
    assert places[0]["area_m2"] == 3200


def test_concave_area_target_stays_inside():
    geography, graph = fixture()
    ring = [[0, 0], [40, 0], [40, 10], [10, 10], [10, 40], [0, 40], [0, 0]]
    places, _, _ = normalize_places(
        {"neighborhoods": [feature(rings=[ring])], "parks": []}, geography, graph
    )
    x, y, _ = places[0]["target"]
    assert (0 <= x <= 40 and 0 <= y <= 10) or (0 <= x <= 10 and 0 <= y <= 40)


def test_outside_department_properties_and_unknown_land_are_counted():
    geography, graph = fixture()
    outside = [[200, 200], [210, 200], [210, 210], [200, 210], [200, 200]]
    places, _, counts = normalize_places(
        {
            "neighborhoods": [feature("Beyond land", [outside])],
            "parks": [feature("Camp", park=True, city="Groveland")],
        },
        geography,
        graph,
    )
    assert places == []
    assert counts["outside_sf_city_records"] == 1
    assert counts["records_without_known_land_anchor"] == 1


def test_missing_nearby_network_does_not_invent_a_walk_target():
    geography, _ = fixture()
    places, _, _ = normalize_places(
        {"neighborhoods": [feature()], "parks": []},
        geography,
        {"nodes": [], "edges": []},
    )
    assert "walk_position" not in places[0]


@pytest.mark.parametrize(
    "bad", ["duplicate", "missing_name", "bad_geometry", "nonfinite"]
)
def test_source_corruption_is_rejected(bad):
    geography, graph = fixture()
    current = feature()
    records = [current]
    if bad == "duplicate":
        records.append(deepcopy(current))
    elif bad == "missing_name":
        current["properties"].pop("nhood")
    elif bad == "bad_geometry":
        current["geometry"]["type"] = "Point"
    else:
        current["geometry"]["coordinates"][0][0][0] = float("nan")
    with pytest.raises(ValueError):
        normalize_places({"neighborhoods": records, "parks": []}, geography, graph)


def test_build_checks_source_integrity_before_writing(tmp_path):
    geography, graph = fixture()
    graph_raw = canonical_bytes(graph)
    (tmp_path / "graph.json").write_bytes(graph_raw)
    geography.update(
        {
            "graph_path": "graph.json",
            "files": {"graph.json": hashlib.sha256(graph_raw).hexdigest()},
        }
    )
    geography["sha256"] = content_hash(geography)
    path = tmp_path / "geography.json"
    path.write_bytes(canonical_bytes(geography))
    (tmp_path / "graph.json").write_text("{}")
    with pytest.raises(ValueError, match="Street graph checksum"):
        build_places({}, path)
    assert not (tmp_path / "places-index.json").exists()
    geography["sha256"] = "0" * 64
    path.write_bytes(canonical_bytes(geography))
    with pytest.raises(ValueError, match="Geography manifest checksum"):
        build_places({}, path)
