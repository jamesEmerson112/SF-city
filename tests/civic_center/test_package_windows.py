"""Portable native components keep source provenance, notices and real fallbacks."""

import io
import json
from pathlib import Path
import tarfile

import pytest

from civic_center.geography import canonical_bytes, content_hash
from civic_center.package_verify import file_hash
import scripts.package_civic_windows as package


MPL = (package.ROOT / "native/civic-godot/licenses/MPL-2.0.txt").read_bytes()


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def archive(path: Path, *, notice_name="LICENSE-MIT", license_name="MIT") -> Path:
    with tarfile.open(path, "w:gz") as target:
        records = {
            "Cargo.toml": f'[package]\nname="fixture"\nversion="1.0.0"\nlicense="{license_name}"\n'
        }
        if notice_name:
            records[notice_name] = "Original fixture copyright and license notice."
        for name, value in records.items():
            data = value.encode()
            member = tarfile.TarInfo("fixture-1.0.0/" + name)
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
    return path


@pytest.fixture
def built_crowd(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setattr(package, "ROOT", root)
    crate = root / "native/civic-godot"
    cached = (
        root / ".cache/cargo-godot/registry/cache/fixture-index/fixture-1.0.0.crate"
    )
    cached.parent.mkdir(parents=True)
    archive(cached)
    for name in package.CROWD_SOURCE_FILES - {"Cargo.lock"}:
        write(crate / name, "source " + name)
    write(
        crate / "Cargo.lock",
        'version = 4\n[[package]]\nname="fixture"\nversion="1.0.0"\nchecksum="'
        + file_hash(cached)
        + '"\n',
    )
    write(crate / "README.md", "Fixture source instructions")
    write(crate / "licenses/MPL-2.0.txt", MPL)
    write(crate / "licenses/sources.json", "{}")
    binary = write(root / "viewer/native/bin/civic_godot.dll", b"compiled fixture")
    descriptor = write(
        root / "viewer/native/civic_godot.gdextension",
        (crate / "civic_godot.gdextension").read_bytes(),
    )
    metadata = {
        "schema_version": 1,
        "crate": "civic-godot",
        "helper_protocol_version": 1,
        "binary": binary.name,
        "bytes": binary.stat().st_size,
        "sha256": file_hash(binary),
        "godot_bindings": "0.4.5",
        "godot_api": "4.5",
        "source_files": {
            name: file_hash(crate / name) for name in package.CROWD_SOURCE_FILES
        },
        "dependencies": [
            {
                "name": "fixture",
                "version": "1.0.0",
                "license": "MIT",
                "sha256": file_hash(cached),
                "source_archive": "https://static.crates.io/crates/fixture/fixture-1.0.0.crate",
            }
        ],
    }
    stamp = write(binary.with_name("native-crowd.json"), json.dumps(metadata))
    return {
        "root": root,
        "crate": crate,
        "cached": cached,
        "binary": binary,
        "descriptor": descriptor,
        "stamp": stamp,
        "metadata": metadata,
    }


def test_native_package_carries_verified_sources_and_original_notices(
    built_crowd, tmp_path
):
    output = tmp_path / "output"
    inputs = {}
    result = package.copy_crowd_native(output, inputs)
    assert result["sha256"] == file_hash(output / "viewer/native/bin/civic_godot.dll")
    assert (
        file_hash(output / "viewer/native/civic_godot.gdextension")
        == result["source_files"]["civic_godot.gdextension"]
    )
    assert result["packaged_source_bytes"] == built_crowd["cached"].stat().st_size
    assert (
        output / "sources/native-crowd/fixture-1.0.0.crate"
    ).read_bytes() == built_crowd["cached"].read_bytes()
    assert (
        output / "licenses/native-crowd/fixture-1.0.0/LICENSE-MIT"
    ).read_text() == "Original fixture copyright and license notice."
    assert file_hash(output / "licenses/native-crowd/MPL-2.0.txt") == package.MPL_SHA256
    sources = json.loads((output / result["source_inventory"]).read_bytes())
    assert (
        sources["dependencies"][0]["packaged_source"]
        == "sources/native-crowd/fixture-1.0.0.crate"
    )
    assert "native/civic-godot/src/lib.rs" in inputs
    assert (
        ".cache/cargo-godot/registry/cache/fixture-index/fixture-1.0.0.crate" in inputs
    )
    assert all(
        file_hash(built_crowd["root"] / name) == digest
        for name, digest in inputs.items()
    )


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "binary",
        "descriptor",
        "source_stamp",
        "archive",
        "archive_missing",
        "dependency_hash",
        "dependency_url",
        "dependency_license",
        "dependency_duplicate",
        "mpl",
    ],
)
def test_native_package_rejects_stale_or_altered_inputs_before_copy(
    built_crowd, tmp_path, change
):
    data = built_crowd
    metadata = data["metadata"]
    if change == "source":
        write(data["crate"] / "src/lib.rs", "changed source")
    elif change in {"binary", "descriptor", "archive"}:
        write(data["cached" if change == "archive" else change], "altered bytes")
    elif change == "archive_missing":
        data["cached"].unlink()
    elif change == "source_stamp":
        metadata["source_files"].pop("src/lib.rs")
    elif change == "dependency_hash":
        metadata["dependencies"][0]["sha256"] = "0" * 64
    elif change == "dependency_url":
        metadata["dependencies"][0][
            "source_archive"
        ] = "https://example.invalid/unrelated.crate"
    elif change == "dependency_license":
        metadata["dependencies"][0]["license"] = "different-license"
    elif change == "dependency_duplicate":
        metadata["dependencies"].append(metadata["dependencies"][0])
    elif change == "mpl":
        write(data["crate"] / "licenses/MPL-2.0.txt", "altered license")
    write(data["stamp"], json.dumps(metadata))
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        package.copy_crowd_native(output, {})
    assert not output.exists()


@pytest.mark.parametrize("missing", ["binary", "descriptor", "stamp"])
def test_partly_staged_native_build_is_an_error(built_crowd, tmp_path, missing):
    built_crowd[missing].unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        package.copy_crowd_native(tmp_path / "output", {})


def test_missing_optional_helper_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(package, "ROOT", tmp_path)
    assert package.copy_crowd_native(tmp_path / "output", {}) is None


def test_without_native_never_discovers_or_copies_either_helper(
    built_crowd, tmp_path, monkeypatch
):
    import civic_center.native_routing as routing

    def unexpected(*args, **kwargs):
        pytest.fail("Native discovery/copy was invoked despite --without-native")

    monkeypatch.setattr(routing, "find_library", unexpected)
    monkeypatch.setattr(package, "copy_crowd_native", unexpected)
    output = tmp_path / "output"
    assert package.copy_native_components(output, {}, enabled=False) == (None, None)
    assert not output.exists()


def test_application_copy_omits_generated_native_files_but_keeps_fallback(
    built_crowd, tmp_path
):
    root = built_crowd["root"]
    write(root / "viewer/native/crowd_buffers.gd", "portable fallback")
    write(root / "viewer/native/crowd_buffer_factory.gd", "optional discovery")
    write(root / "viewer/native/civic_godot.gdextension.uid", "generated uid")
    output = tmp_path / "output"
    inputs = package.copy_application_sources(output)
    assert (output / "viewer/native/crowd_buffers.gd").is_file()
    assert (output / "viewer/native/crowd_buffer_factory.gd").is_file()
    assert not (output / "viewer/native/bin").exists()
    assert not (output / "viewer/native/civic_godot.gdextension").exists()
    assert not (output / "viewer/native/civic_godot.gdextension.uid").exists()
    assert set(inputs) == {
        "viewer/native/crowd_buffers.gd",
        "viewer/native/crowd_buffer_factory.gd",
    }


def test_archive_notice_paths_cannot_escape_package(tmp_path):
    source = archive(tmp_path / "fixture.crate", notice_name="../../LICENSE-MIT")
    with pytest.raises(ValueError, match="escapes"):
        package._crate_notices(source, ("fixture", "1.0.0"), "MIT")


@pytest.mark.parametrize("change", [None, "source", "checksum", "areas", "escape"])
def test_places_index_and_areas_remain_verified(tmp_path, change):
    geography = tmp_path / "geography/sf-geography.json"
    manifest = {"complete": True, "files": {}}
    manifest["sha256"] = content_hash(manifest)
    write(geography, canonical_bytes(manifest))
    areas = write(geography.parent / "areas.json", '{"polygons":[]}')
    places = {
        "geography_sha256": manifest["sha256"],
        "geography_file_sha256": file_hash(geography),
        "areas_path": "areas.json",
        "areas_sha256": file_hash(areas),
    }
    if change == "source":
        places["geography_sha256"] = "wrong"
    if change == "escape":
        places["areas_path"] = "../areas.json"
    places["sha256"] = content_hash(places)
    if change == "checksum":
        places["sha256"] = "wrong"
    write(geography.parent / "places-index.json", canonical_bytes(places))
    if change == "areas":
        write(areas, "changed")
    output = tmp_path / "output"
    if change:
        with pytest.raises(ValueError):
            package.copy_city_data(output, geography, None)
    else:
        result = package.copy_city_data(output, geography, None)
        assert result["places_sha256"] == places["sha256"]
        assert (
            output / ".local/civic/geography/areas.json"
        ).read_bytes() == areas.read_bytes()
