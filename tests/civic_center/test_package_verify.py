"""An extracted portable build must detect absent or altered shipped files."""

import hashlib
import json

import pytest

from civic_center.package_verify import inside, verify


def test_package_verification_allows_saves_but_detects_changed_runtime(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    binary = runtime / "python.exe"
    binary.write_bytes(b"runtime-fixture")
    manifest = {
        "schema_version": 1,
        "files": {
            "runtime/python.exe": {
                "bytes": len(b"runtime-fixture"),
                "sha256": hashlib.sha256(b"runtime-fixture").hexdigest(),
            }
        },
    }
    (tmp_path / "package-manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "new-save.json").write_text("{}")
    assert verify(tmp_path)["valid"]
    binary.write_bytes(b"altered-fixture")
    assert verify(tmp_path)["failures"] == [
        {"path": "runtime/python.exe", "reason": "content differs"}
    ]
    binary.unlink()
    assert verify(tmp_path)["failures"] == [
        {"path": "runtime/python.exe", "reason": "missing"}
    ]


@pytest.mark.parametrize("relative", ["../outside", "nested/../../outside", "."])
def test_package_paths_stay_inside_distribution(tmp_path, relative):
    with pytest.raises(ValueError, match="escapes"):
        inside(tmp_path, relative)
