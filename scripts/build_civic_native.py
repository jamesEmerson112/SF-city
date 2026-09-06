"""Build the optional Rust router offline and record source/runtime provenance."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import atomic_write, canonical_bytes, content_hash
from civic_center.package_verify import file_hash


def main() -> int:
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo.exe")
    rustc = shutil.which("rustc") or str(Path(cargo).with_name("rustc.exe"))
    crate = ROOT / "native/civic-routing"
    target = ROOT / ".cache/civic-native"
    subprocess.run(
        [
            cargo,
            "build",
            "--release",
            "--offline",
            "--locked",
            "--manifest-path",
            str(crate / "Cargo.toml"),
            "--target-dir",
            str(target),
        ],
        check=True,
    )
    binary = (
        target
        / "release"
        / (
            "civic_routing.dll"
            if sys.platform == "win32"
            else (
                "libcivic_routing.dylib"
                if sys.platform == "darwin"
                else "libcivic_routing.so"
            )
        )
    )
    sources = {
        name: file_hash(crate / name)
        for name in ("Cargo.toml", "Cargo.lock", "src/lib.rs")
    }
    result = {
        "schema_version": 1,
        "abi_version": 1,
        "crate": "civic-routing",
        "version": "0.1.0",
        "source_files": sources,
        "source_sha256": content_hash(sources),
        "binary": binary.name,
        "sha256": file_hash(binary),
        "bytes": binary.stat().st_size,
        "compiler": subprocess.check_output([rustc, "--version"], text=True).strip(),
        "cargo": subprocess.check_output([cargo, "--version"], text=True).strip(),
        "profile": "release",
        "external_dependencies": [],
        "license": "MIT",
    }
    atomic_write(binary.with_name("native-routing.json"), canonical_bytes(result))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
