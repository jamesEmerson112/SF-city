"""Portable scenery copies are optional, bounded and verified before shipping."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest
from civic_center.package_verify import file_hash
from scripts.package_civic_windows import copy_render_cache


def make_entry(directory: Path, key: str = "a1" * 32) -> Path:
    payload = b"opaque Godot array payload fixture"
    header = struct.pack(
        "<8sIQ32s32s",
        b"SFSCN001",
        1,
        len(payload),
        bytes.fromhex(key),
        hashlib.sha256(payload).digest(),
    )
    path = directory / key[:2] / f"{key}.sfmesh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + payload)
    return path


def test_prepared_cache_is_opt_in(tmp_path: Path) -> None:
    output = tmp_path / "portable"
    result = copy_render_cache(None, output)
    assert result is None
    assert not output.exists()


def test_only_validated_entries_are_copied_with_original_bytes(tmp_path: Path) -> None:
    source = tmp_path / "cache with spaces"
    first = make_entry(source)
    second = make_entry(source, "b2" * 32)
    (first.parent / f"{first.name}.tmp-123").write_text("partial")
    (source / "preparation-report.json").write_text("{}")
    output = tmp_path / "portable with spaces"

    result = copy_render_cache(source, output)

    destination = output / ".local/civic/render-cache"
    assert result == {
        "format": "SFSCN001",
        "directory": ".local/civic/render-cache",
        "files": 2,
        "bytes": first.stat().st_size + second.stat().st_size,
    }
    assert len(list(destination.rglob("*.sfmesh"))) == 2
    for path in (first, second):
        packaged = destination / path.relative_to(source)
        assert packaged.read_bytes() == path.read_bytes()
        assert file_hash(packaged) == file_hash(path)
    assert not (destination / "preparation-report.json").exists()
    assert not list(destination.rglob("*.tmp-*"))


@pytest.mark.parametrize(
    "damage",
    ["magic", "version", "length", "key", "payload", "truncated", "oversized"],
)
def test_bad_entries_reject_selection_before_any_copy(
    tmp_path: Path, damage: str
) -> None:
    source = tmp_path / "cache"
    make_entry(source)
    invalid = make_entry(source, "b2" * 32)
    data = bytearray(invalid.read_bytes())
    if damage == "magic":
        data[0] ^= 255
    elif damage == "version":
        struct.pack_into("<I", data, 8, 2)
    elif damage == "length":
        struct.pack_into("<Q", data, 12, len(data))
    elif damage == "key":
        data[20] ^= 255
    elif damage == "payload":
        data[-1] ^= 255
    elif damage == "truncated":
        data = data[:40]
    else:
        struct.pack_into("<Q", data, 12, 129 * 1024 * 1024)
    invalid.write_bytes(data)
    output = tmp_path / "portable"

    with pytest.raises(ValueError, match="scenery"):
        copy_render_cache(source, output)

    assert not output.exists()


@pytest.mark.parametrize(
    "relative",
    [
        "bad.sfmesh",
        "wrong/" + "a1" * 32 + ".sfmesh",
        "a1/nested/" + "a1" * 32 + ".sfmesh",
        "a1/" + "zz" * 32 + ".sfmesh",
    ],
)
def test_invalid_content_key_paths_are_rejected(tmp_path: Path, relative: str) -> None:
    source = tmp_path / "cache"
    path = source / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"invalid")

    with pytest.raises(ValueError, match="key path"):
        copy_render_cache(source, tmp_path / "portable")


def test_cache_directory_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory is missing"):
        copy_render_cache(tmp_path / "missing", tmp_path / "portable")


def test_source_cannot_overlap_package_cache(tmp_path: Path) -> None:
    output = tmp_path / "portable"
    source = output / ".local/civic/render-cache"
    make_entry(source)
    with pytest.raises(ValueError, match="must not overlap"):
        copy_render_cache(source, output)


def test_symlink_cannot_copy_a_cache_entry_outside_source(tmp_path: Path) -> None:
    source = tmp_path / "cache"
    outside = make_entry(tmp_path / "outside")
    link = source / outside.parent.name / outside.name
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("This Windows account cannot create filesystem symlinks.")

    with pytest.raises(ValueError, match="escapes|regular"):
        copy_render_cache(source, tmp_path / "portable")
