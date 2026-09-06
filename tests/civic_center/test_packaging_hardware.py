"""Portable monitoring uses pinned wheels, safe extraction and offline caches."""

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from scripts import package_monitoring as monitoring


def wheel_bytes(files: dict[str, bytes], *, symlink=False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            member = zipfile.ZipInfo(name)
            # Keep deliberately unsafe raw names; ZipInfo normalizes Windows separators.
            member.filename = name
            if symlink:
                member.create_system = 3
                member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, payload)
    return output.getvalue()


@pytest.fixture
def wheel(tmp_path, monkeypatch):
    files = {
        "fixture/__init__.py": b"value = 1\n",
        "fixture/_native.pyd": b"fixture native bytes",
        "fixture-1.0.dist-info/METADATA": b"Name: fixture\nVersion: 1.0\n",
        "fixture-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        "fixture-1.0.dist-info/RECORD": b"fixture record",
        "fixture-1.0.dist-info/licenses/LICENSE": b"Original license notice",
    }
    payload = wheel_bytes(files)
    specification = {
        "name": "fixture",
        "version": "1.0",
        "filename": "fixture-1.0-py3-none-any.whl",
        "url": "https://example.invalid/fixture.whl",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "metadata_url": "https://example.invalid/fixture/json",
    }
    monkeypatch.setattr(monitoring, "WHEELS", (specification,))
    cache = tmp_path / "cache"
    cache.mkdir()
    target = cache / specification["filename"]
    target.write_bytes(payload)
    return specification, target, files, payload


def test_cached_wheels_never_access_network_and_record_pinned_inventory(
    wheel, monkeypatch
):
    specification, target, _, _ = wheel

    def unexpected(*args, **kwargs):
        pytest.fail("Cached build attempted network access")

    monkeypatch.setattr(monitoring, "urlopen", unexpected)
    assert monitoring.monitoring_archives(target.parent, False) == [target]
    manifest = json.loads((target.parent / monitoring.CACHE_MANIFEST).read_bytes())
    assert manifest == {"schema_version": 1, "wheels": [specification]}


def test_uncached_wheel_requires_download_flag(wheel, tmp_path, monkeypatch):
    _, target, _, _ = wheel
    calls = []
    monkeypatch.setattr(monitoring, "urlopen", lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError, match="--download-runtime"):
        monitoring.monitoring_archives(tmp_path / "empty", False)
    assert calls == []
    assert target.is_file()


def test_first_download_is_verified_before_becoming_a_cache_entry(
    wheel, tmp_path, monkeypatch
):
    specification, _, _, payload = wheel
    calls = []

    def download(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(payload)

    monkeypatch.setattr(monitoring, "urlopen", download)
    result = monitoring.monitoring_archives(tmp_path / "fresh-cache", True)
    assert result[0].read_bytes() == payload
    assert calls == [(specification["url"], 30)]


def test_bad_download_never_enters_cache(wheel, tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring, "urlopen", lambda *a, **kw: io.BytesIO(b"wrong"))
    cache = tmp_path / "fresh-cache"
    with pytest.raises(ValueError, match="SHA256"):
        monitoring.monitoring_archives(cache, True)
    assert not cache.exists()


def test_altered_cached_wheel_is_rejected_without_refetch(wheel, monkeypatch):
    _, target, _, _ = wheel
    target.write_bytes(b"altered")
    calls = []
    monkeypatch.setattr(monitoring, "urlopen", lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError, match="checksum"):
        monitoring.monitoring_archives(target.parent, True)
    assert calls == []


def test_extraction_preserves_native_binary_metadata_and_license(wheel, tmp_path):
    specification, archive, files, _ = wheel
    output = tmp_path / "output"
    result = monitoring.install_monitoring(output, [archive])
    destination = output / monitoring.SITE_PACKAGES
    assert all(
        (destination / name).read_bytes() == payload for name, payload in files.items()
    )
    dependency = result["dependencies"][0]
    assert dependency["sha256"] == specification["sha256"]
    assert dependency["files"] == len(files)
    assert dependency["notices"] == [
        monitoring.SITE_PACKAGES + "/fixture-1.0.dist-info/licenses/LICENSE"
    ]


@pytest.mark.parametrize(
    "name",
    [
        "../escape.py",
        "/rooted.py",
        "C:/absolute.py",
        "x:stream",
        "a/../../escape.py",
        "a\\escape.py",
        "NUL",
        "fixture.data/scripts/entry.py",
    ],
)
def test_archive_paths_are_checked_before_any_files_are_written(wheel, tmp_path, name):
    specification, archive, _, _ = wheel
    payload = wheel_bytes({"fixture/valid.py": b"valid", name: b"unsafe"})
    archive.write_bytes(payload)
    specification["sha256"] = hashlib.sha256(payload).hexdigest()
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="path"):
        monitoring.install_monitoring(output, [archive])
    assert not output.exists()


def test_archive_symlinks_are_rejected(wheel, tmp_path):
    specification, archive, _, _ = wheel
    payload = wheel_bytes({"fixture/link": b"../../escape"}, symlink=True)
    archive.write_bytes(payload)
    specification["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match="path"):
        monitoring.install_monitoring(tmp_path / "output", [archive])


def test_duplicate_windows_paths_are_rejected_before_extraction(wheel, tmp_path):
    specification, archive, _, _ = wheel
    payload = wheel_bytes({"fixture/Model.py": b"first", "fixture/model.py": b"second"})
    archive.write_bytes(payload)
    specification["sha256"] = hashlib.sha256(payload).hexdigest()
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Duplicate"):
        monitoring.install_monitoring(output, [archive])
    assert not output.exists()


def test_extract_size_is_bounded_before_writing(wheel, tmp_path, monkeypatch):
    _, archive, _, _ = wheel
    monkeypatch.setattr(monitoring, "MAX_EXTRACTED_BYTES", 4)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="extraction limit"):
        monitoring.install_monitoring(output, [archive])
    assert not output.exists()


def test_extraction_rechecks_archive_checksum(wheel, tmp_path):
    _, archive, _, _ = wheel
    archive.write_bytes(b"changed after cache verification")
    with pytest.raises(ValueError, match="SHA256"):
        monitoring.install_monitoring(tmp_path / "output", [archive])


def test_existing_file_is_not_overwritten(wheel, tmp_path):
    _, archive, _, _ = wheel
    output = tmp_path / "output"
    existing = output / monitoring.SITE_PACKAGES / "fixture/__init__.py"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="Duplicate"):
        monitoring.install_monitoring(output, [archive])
    assert existing.read_bytes() == b"preserve"


def test_embedded_notice_path_is_recorded_without_changing_source(wheel, tmp_path):
    specification, archive, files, _ = wheel
    specification["embedded_notices"] = ["fixture/__init__.py"]
    output = tmp_path / "output"
    result = monitoring.install_monitoring(output, [archive])
    notice = monitoring.SITE_PACKAGES + "/fixture/__init__.py"
    assert notice in result["dependencies"][0]["notices"]
    assert (output / notice).read_bytes() == files["fixture/__init__.py"]
