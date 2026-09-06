"""Tree source locations, omissions, artistic dimensions and reproducibility."""

from copy import deepcopy
import hashlib
import json

import pytest

from civic_center.geography import LocalProjection, canonical_bytes, content_hash
from civic_center.trees import SOURCE, build_trees, display_dimensions, normalize_trees


def geography_fixture():
    return {
        "bounds": {"min": [-1000, -1000], "max": [1000, 1000]},
        "land": [
            {
                "id": "land",
                "rings": [
                    [[-800, -800, 0], [800, -800, 0], [800, 800, 0], [-800, 800, 0]]
                ],
                "area_m2": 2560000,
            }
        ],
    }


def feature(identity=1, point=(0, 0), **properties):
    return {
        "type": "Feature",
        "properties": {
            "treeid": str(identity),
            "species": "Magnolia grandiflora :: Southern Magnolia",
            "planttype": "Tree",
            "mapdbh": "12",
            "data_as_of": "2026-07-01",
            "data_loaded_at": "2026-09-05",
            **properties,
        },
        "geometry": {
            "type": "Point",
            "coordinates": LocalProjection().to_lonlat(*point),
        },
    }


def test_source_positions_and_observation_dates_remain_distinct():
    source = feature(point=(121.25, -83.75))
    records, counts = normalize_trees([source], geography_fixture())
    tree = records[0]
    assert tree["position"] == [121.25, -83.75, 0.0]
    assert tree["data_as_of"] == "2026-07-01"
    assert tree["data_loaded_at"] == "2026-09-05"
    assert tree["dbh_source_value"] == 12.0
    assert tree["dbh_source_units"] == "not stated in source metadata"
    assert tree["display"]["source"] == "illustrative-v1"
    assert counts["renderable_records"] == 1
    source["geometry"]["coordinates"][0] = 0
    assert tree["position"] == [121.25, -83.75, 0.0]


def test_display_variation_is_not_an_invented_dbh_height_measurement():
    small = normalize_trees([feature(mapdbh="1")], geography_fixture())[0][0]
    large = normalize_trees([feature(mapdbh="120")], geography_fixture())[0][0]
    assert small["display"] == large["display"]
    assert (
        display_dimensions(
            "sf-tree:1", "Phoenix canariensis :: Canary Island Date Palm"
        )["shape"]
        == "palm"
    )
    assert (
        display_dimensions("sf-tree:1", "Pinus radiata :: Monterey Pine")["shape"]
        == "conifer"
    )
    assert display_dimensions("sf-tree:1", None)["shape"] == "broadleaf"


def test_missing_coordinates_sites_and_explicit_stumps_do_not_become_trees():
    missing = feature(1)
    missing["geometry"] = None
    records, counts = normalize_trees(
        [
            missing,
            feature(2, species="Stump"),
            feature(3, planttype="Landscaping"),
            feature(4, species="Empty Basin :: Planting Site"),
            feature(5),
        ],
        geography_fixture(),
    )
    assert [tree["id"] for tree in records] == ["sf-tree:5"]
    assert counts["missing_coordinates"] == 1
    assert counts["excluded_nonliving_site_label"] == 2
    assert counts["excluded_non_tree_or_unspecified_type"] == 1


@pytest.mark.parametrize(
    "coordinates", [[float("nan"), 1], [181, 1], [0, 91], [False, 1], [1], [0, 0, 0, 0]]
)
def test_invalid_coordinates_are_counted_and_omitted(coordinates):
    current = feature()
    current["geometry"]["coordinates"] = coordinates
    records, counts = normalize_trees([current], geography_fixture())
    assert records == []
    assert counts["invalid_coordinates"] == 1


def test_outside_extent_and_unknown_land_are_separate_omissions():
    records, counts = normalize_trees(
        [feature(1, (2000, 0)), feature(2, (900, 0))], geography_fixture()
    )
    assert records == []
    assert counts["outside_urban_bounds"] == 1
    assert counts["outside_known_source_land"] == 1


def test_coincident_coordinates_retain_ids_without_random_relocation():
    records, counts = normalize_trees([feature(2), feature(1)], geography_fixture())
    assert [tree["id"] for tree in records] == ["sf-tree:1", "sf-tree:2"]
    assert records[0]["position"] == records[1]["position"] == [0, 0, 0]
    assert counts["records_at_coincident_positions"] == 2
    assert counts["coincident_position_groups"] == 1
    assert counts["unique_source_positions"] == 1


@pytest.mark.parametrize(
    "identity", [None, 0, -1, "1.5", "NaN", "Infinity", "1e1000000", True]
)
def test_bad_identity_is_rejected_before_any_ambiguous_source_records(identity):
    with pytest.raises(ValueError, match="treeid"):
        normalize_trees([feature(identity)], geography_fixture())


def test_duplicate_ids_are_rejected_even_when_one_has_missing_coordinates():
    missing = feature()
    missing["geometry"] = None
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_trees([missing, feature()], geography_fixture())


def test_invalid_dbh_does_not_drop_a_valid_tree_or_set_its_visual_height():
    records, counts = normalize_trees([feature(mapdbh="unknown")], geography_fixture())
    assert records[0]["dbh_source_value"] is None
    assert counts["invalid_dbh_attribute"] == 1
    assert records[0]["display"] == display_dimensions(
        "sf-tree:1", records[0]["species"]
    )


def test_complete_preparation_checks_identity_tiles_and_cached_source_bytes(tmp_path):
    geography = geography_fixture()
    geography["sha256"] = content_hash(geography)
    path = tmp_path / "sf-geography.json"
    path.write_bytes(canonical_bytes(geography))
    raw = canonical_bytes(
        {
            "type": "FeatureCollection",
            "features": [feature(1, (600, 1)), feature(2, (-600, 1))],
        }
    )
    page_path = tmp_path / "page.geojson"
    page_path.write_bytes(raw)
    source_index = {
        "id": SOURCE.dataset_id,
        "cache_folder": str(tmp_path),
        "title": SOURCE.title,
        "url": SOURCE.url,
        "license": {"name": "PDDL"},
        "metadata_sha256": "1" * 64,
        "source_rows_updated_at": 123,
        "retrieved_at": "2026-09-06",
        "pages": [{"file": page_path.name, "sha256": hashlib.sha256(raw).hexdigest()}],
    }
    report = build_trees(source_index, path)
    manifest = json.loads((tmp_path / "tree-index.json").read_bytes())
    assert report["tile_count"] == 2
    assert manifest["sha256"] == content_hash(
        {k: v for k, v in manifest.items() if k != "sha256"}
    )
    assert (
        manifest["geography_file_sha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert {tile["id"] for tile in manifest["tiles"]} == {"1_0", "-2_0"}
    for tile in manifest["tiles"]:
        assert (
            hashlib.sha256((tmp_path / tile["path"]).read_bytes()).hexdigest()
            == tile["sha256"]
        )
    assert build_trees(source_index, path) == report
    prior = (tmp_path / "tree-index.json").read_bytes()
    page_path.write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        build_trees(source_index, path)
    assert (tmp_path / "tree-index.json").read_bytes() == prior
    altered = deepcopy(source_index)
    altered["id"] = "tkzw-k3nq"
    with pytest.raises(ValueError, match="replacement"):
        build_trees(altered, path)
