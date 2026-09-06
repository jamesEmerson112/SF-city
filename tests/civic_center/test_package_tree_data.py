"""Portable city data keeps optional tree provenance and rejects mixed sources."""

import json

import pytest

from civic_center.geography import canonical_bytes, content_hash
from civic_center.package_verify import file_hash
from scripts.package_civic_windows import copy_city_data


def prepare(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    geography = {"complete": True, "files": {}}
    geography["sha256"] = content_hash(geography)
    path = source / "sf-geography.json"
    path.write_bytes(canonical_bytes(geography))
    tile = source / "tree-tiles/0_0.json"
    tile.parent.mkdir()
    tile.write_bytes(
        canonical_bytes({"schema_version": 1, "tile_id": "0_0", "trees": []})
    )
    index = {
        "schema_version": 1,
        "geography_sha256": geography["sha256"],
        "geography_file_sha256": file_hash(path),
        "source": {"id": "uzd4-f6yf"},
        "tiles": [
            {"id": "0_0", "path": "tree-tiles/0_0.json", "sha256": file_hash(tile)}
        ],
    }
    index["sha256"] = content_hash(index)
    (source / "tree-index.json").write_bytes(canonical_bytes(index))
    return path, index, tile


def test_tree_sidecar_is_portable_and_recorded_in_source_manifest(tmp_path):
    path, index, tile = prepare(tmp_path)
    output = tmp_path / "Application With Spaces"
    result = copy_city_data(output, path, None)
    target = output / ".local/civic/geography"
    assert result["trees_sha256"] == index["sha256"]
    assert (target / "tree-tiles/0_0.json").read_bytes() == tile.read_bytes()
    assert json.loads((target / "tree-index.json").read_bytes()) == index


@pytest.mark.parametrize(
    "damage", ["geography", "index_hash", "old_inventory", "tile_bytes", "traversal"]
)
def test_bad_tree_data_is_rejected_by_packaging(tmp_path, damage):
    path, index, tile = prepare(tmp_path)
    if damage == "geography":
        index["geography_sha256"] = "0" * 64
    elif damage == "index_hash":
        index["sha256"] = "0" * 64
    elif damage == "old_inventory":
        index["source"]["id"] = "tkzw-k3nq"
    elif damage == "tile_bytes":
        tile.write_text("altered source")
    else:
        index["tiles"][0]["path"] = "../outside.json"
    if damage != "index_hash":
        index["sha256"] = content_hash(
            {k: v for k, v in index.items() if k != "sha256"}
        )
    (path.parent / "tree-index.json").write_bytes(canonical_bytes(index))
    with pytest.raises(ValueError):
        copy_city_data(tmp_path / "output", path, None)
