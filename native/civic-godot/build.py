"""Build the optional Godot helper from pinned cached crates and stage it locally."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


CRATE = Path(__file__).resolve().parent
ROOT = CRATE.parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch", action="store_true", help="Download locked crates first"
    )
    args = parser.parse_args()
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo.exe")
    rustc = str(Path(cargo).with_name("rustc.exe" if os.name == "nt" else "rustc"))
    env = dict(os.environ, CARGO_HOME=str(ROOT / ".cache/cargo-godot"))
    manifest = ["--locked", "--manifest-path", str(CRATE / "Cargo.toml")]
    if args.fetch:
        subprocess.run([cargo, "fetch", *manifest], env=env, check=True)
    target = ROOT / ".cache/civic-godot"
    subprocess.run(
        [
            cargo,
            "build",
            "--release",
            "--offline",
            *manifest,
            "--target-dir",
            str(target),
        ],
        env=env,
        check=True,
    )
    filename = (
        "civic_godot.dll"
        if os.name == "nt"
        else "libcivic_godot.dylib" if sys.platform == "darwin" else "libcivic_godot.so"
    )
    source = target / "release" / filename
    destination = ROOT / "viewer/native/bin"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination / filename)
    shutil.copy2(
        CRATE / "civic_godot.gdextension",
        destination.parent / "civic_godot.gdextension",
    )
    packages = json.loads(
        subprocess.check_output(
            [cargo, "metadata", "--offline", "--format-version", "1", *manifest],
            env=env,
            text=True,
        )
    )["packages"]
    checksums = {
        (package["name"], package["version"]): package.get("checksum")
        for package in tomllib.loads(
            (CRATE / "Cargo.lock").read_text(encoding="utf-8")
        )["package"]
    }
    dependencies = [
        {
            "name": package["name"],
            "version": package["version"],
            "license": package["license"],
            "sha256": checksums[(package["name"], package["version"])],
            "source_archive": f"https://static.crates.io/crates/{package['name']}/{package['name']}-{package['version']}.crate",
        }
        for package in sorted(packages, key=lambda value: value["name"])
        if package["name"] != "civic-godot"
    ]
    metadata = {
        "schema_version": 1,
        "crate": "civic-godot",
        "version": "0.1.0",
        "helper_protocol_version": 1,
        "godot_bindings": "0.4.5",
        "godot_api": "4.5",
        "compiler": subprocess.check_output([rustc, "--version"], text=True).strip(),
        "binary": filename,
        "bytes": source.stat().st_size,
        "sha256": digest(source),
        "source_files": {
            name: digest(CRATE / name)
            for name in (
                "Cargo.toml",
                "Cargo.lock",
                "src/lib.rs",
                "civic_godot.gdextension",
                "build.py",
            )
        },
        "dependencies": dependencies,
        "dependency_license_note": "godot-rust crates are MPL-2.0; see Cargo.lock and README.md",
    }
    (destination / "native-crowd.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
