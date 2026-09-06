"""Build an offline Windows folder containing Python, Godot and prepared city data.

Uses the official embeddable Python package and the already tested Godot binary.
No installer, registry changes, globally installed packages or export templates.
Each build uses a new directory and records a checksum for every shipped file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.geography import canonical_bytes, content_hash
from civic_center.launch import find_godot
from civic_center.package_verify import file_hash, inside, verify
from scripts.package_monitoring import (
    CACHE_MANIFEST,
    install_monitoring,
    monitoring_archives,
)

PYTHON_VERSION = "3.13.15"
PYTHON_URL = (
    "https://www.python.org/ftp/python/3.13.15/python-3.13.15-embeddable-amd64.zip"
)
PYTHON_SHA256 = "791ada5e20aba24524f8d939cdeb069976d632a699fe5cb65274b23f4545e68a"
PYTHON_RELEASE = "https://www.python.org/ftp/python/3.13.15/windows-3.13.15.json"
CACHE = ROOT / ".cache/civic-package"
SCENERY_CACHE_HEADER = struct.Struct("<8sIQ32s32s")
SCENERY_CACHE_MAX_BYTES = 128 * 1024 * 1024
CROWD_SOURCE_FILES = {
    "Cargo.toml",
    "Cargo.lock",
    "src/lib.rs",
    "civic_godot.gdextension",
    "build.py",
}
MPL_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"


def python_archive(allow_download: bool) -> Path:
    target = CACHE / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    if not target.is_file():
        if not allow_download:
            raise ValueError(
                "Portable Python is not cached; run again with --download-runtime"
            )
        CACHE.mkdir(parents=True, exist_ok=True)
        with urlopen(PYTHON_URL, timeout=60) as response:
            payload = response.read(32 * 1024 * 1024 + 1)
        if (
            len(payload) > 32 * 1024 * 1024
            or hashlib.sha256(payload).hexdigest() != PYTHON_SHA256
        ):
            raise ValueError(
                "Portable Python does not match the official release SHA256"
            )
        target.write_bytes(payload)
    if file_hash(target) != PYTHON_SHA256:
        raise ValueError("Cached portable Python checksum mismatch")
    return target


def copy_verified(source: Path, destination: Path, expected: str | None = None) -> None:
    if not source.is_file():
        raise ValueError(f"Missing build input: {source}")
    digest = file_hash(source)
    if expected and digest != expected:
        raise ValueError(f"Source checksum mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if file_hash(destination) != digest:
        raise ValueError(f"Copy verification failed: {destination}")


def copy_render_cache(directory: Path | None, output: Path) -> dict | None:
    """Ship only explicitly selected, complete prepared scenery entries."""
    if directory is None:
        return None
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError(f"Prepared scenery cache directory is missing: {directory}")
    target = inside(output, ".local/civic/render-cache")
    if (
        directory == target
        or directory.is_relative_to(target)
        or target.is_relative_to(directory)
    ):
        raise ValueError("Prepared scenery source and packaged cache must not overlap")
    prepared: list[tuple[Path, Path, str, int]] = []
    for candidate in sorted(directory.rglob("*.sfmesh")):
        relative = candidate.relative_to(directory)
        key = candidate.stem
        if (
            len(relative.parts) != 2
            or len(key) != 64
            or any(character not in "0123456789abcdef" for character in key)
            or relative.parts[0] != key[:2]
        ):
            raise ValueError(f"Invalid prepared scenery key path: {relative}")
        source = inside(directory, relative.as_posix())
        if candidate.is_symlink() or not source.is_file():
            raise ValueError(
                f"Prepared scenery must be a regular cache file: {relative}"
            )
        digest, size = _validate_render_cache_entry(source, key)
        prepared.append((source, inside(target, relative.as_posix()), digest, size))
    # Validate the whole selection before copying any entries. Ignore temporary
    # writes, reports and unrelated files rather than shipping runtime state.
    for source, destination, digest, _ in prepared:
        copy_verified(source, destination, digest)
    return {
        "format": "SFSCN001",
        "directory": ".local/civic/render-cache",
        "files": len(prepared),
        "bytes": sum(size for _, _, _, size in prepared),
    }


def _validate_render_cache_entry(path: Path, key: str) -> tuple[str, int]:
    """Check the bounded non-object cache envelope without decoding Variants."""
    size = path.stat().st_size
    if (
        not SCENERY_CACHE_HEADER.size
        < size
        <= SCENERY_CACHE_HEADER.size + SCENERY_CACHE_MAX_BYTES
    ):
        raise ValueError(f"Invalid prepared scenery size: {path}")
    with path.open("rb") as source:
        header = source.read(SCENERY_CACHE_HEADER.size)
        if len(header) != SCENERY_CACHE_HEADER.size:
            raise ValueError(f"Truncated prepared scenery header: {path}")
        magic, version, payload_size, identity, expected = SCENERY_CACHE_HEADER.unpack(
            header
        )
        if (
            magic != b"SFSCN001"
            or version != 1
            or payload_size != size - SCENERY_CACHE_HEADER.size
            or identity.hex() != key
        ):
            raise ValueError(f"Invalid prepared scenery header or key: {path}")
        payload_hash = hashlib.sha256()
        file_digest = hashlib.sha256(header)
        remaining = payload_size
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError(f"Truncated prepared scenery payload: {path}")
            payload_hash.update(chunk)
            file_digest.update(chunk)
            remaining -= len(chunk)
        if source.read(1) or payload_hash.digest() != expected:
            raise ValueError(f"Prepared scenery checksum mismatch: {path}")
    return file_digest.hexdigest(), size


def copy_application_sources(output: Path) -> dict[str, str]:
    inputs = {}
    for folder, extensions in (
        ("civic_center", {".py", ".json"}),
        (
            "viewer",
            {
                ".gd",
                ".gdshader",
                ".tscn",
                ".godot",
                ".glb",
                ".json",
                ".png",
                ".svg",
                ".ttf",
                ".tres",
                ".uid",
            },
        ),
    ):
        for source in sorted((ROOT / folder).rglob("*")):
            relative = source.relative_to(ROOT)
            if (
                source.is_file()
                and source.suffix in extensions
                and relative.parts[:3] != ("viewer", "native", "bin")
                and relative.as_posix() != "viewer/native/civic_godot.gdextension.uid"
                and not any(
                    part.startswith(".") or part == "__pycache__"
                    for part in relative.parts
                )
            ):
                _copy_input(source, output / relative, inputs)
    return inputs


def _copy_input(
    source: Path, destination: Path, inputs: dict, expected: str | None = None
) -> None:
    digest = expected or file_hash(source)
    copy_verified(source, destination, digest)
    inputs[source.relative_to(ROOT).as_posix()] = digest


def copy_native_components(
    output: Path, inputs: dict, *, enabled: bool
) -> tuple[dict | None, dict | None]:
    if not enabled:
        return None, None
    from civic_center.native_routing import find_library

    routing = None
    binary = find_library()
    if binary is not None:
        stamp = binary.with_name("native-routing.json")
        if not stamp.is_file():
            raise ValueError(
                "Build native provenance first with scripts/build_civic_native.py"
            )
        routing = json.loads(stamp.read_bytes())
        for name, expected in routing["source_files"].items():
            source = inside(ROOT / "native/civic-routing", name)
            if file_hash(source) != expected:
                raise ValueError(
                    "Rust sources changed; run scripts/build_civic_native.py before packaging"
                )
            inputs[source.relative_to(ROOT).as_posix()] = expected
        _copy_input(
            binary, output / "runtime/native" / binary.name, inputs, routing["sha256"]
        )
        _copy_input(stamp, output / "runtime/native/native-routing.json", inputs)
    return routing, copy_crowd_native(output, inputs)


def copy_crowd_native(output: Path, inputs: dict) -> dict | None:
    """Package a current Windows helper with exact locked source archives/notices."""
    output = output.resolve()
    crate = ROOT / "native/civic-godot"
    staged = ROOT / "viewer/native"
    binary = staged / "bin/civic_godot.dll"
    descriptor = staged / "civic_godot.gdextension"
    stamp = staged / "bin/native-crowd.json"
    if not any(path.exists() for path in (binary, descriptor, stamp)):
        return None
    if not all(path.is_file() for path in (binary, descriptor, stamp)):
        raise ValueError(
            "Incomplete native crowd build; run native/civic-godot/build.py"
        )
    metadata = json.loads(stamp.read_bytes())
    if (
        metadata.get("schema_version") != 1
        or metadata.get("crate") != "civic-godot"
        or metadata.get("helper_protocol_version") != 1
        or metadata.get("binary") != "civic_godot.dll"
        or metadata.get("godot_bindings") != "0.4.5"
        or metadata.get("godot_api") != "4.5"
        or set(metadata.get("source_files", {})) != CROWD_SOURCE_FILES
        or metadata.get("bytes") != binary.stat().st_size
    ):
        raise ValueError("Invalid native crowd build provenance")
    for name, expected in metadata["source_files"].items():
        if file_hash(inside(crate, name)) != expected:
            raise ValueError(
                "Native crowd sources changed; run native/civic-godot/build.py"
            )
    if file_hash(descriptor) != metadata["source_files"]["civic_godot.gdextension"]:
        raise ValueError("Native crowd descriptor differs from its built source")
    if file_hash(binary) != metadata.get("sha256"):
        raise ValueError("Native crowd binary checksum differs from its build stamp")
    locked = {
        (package["name"], package["version"]): package["checksum"]
        for package in tomllib.loads(
            (crate / "Cargo.lock").read_text(encoding="utf-8")
        )["package"]
        if "checksum" in package
    }
    dependencies = metadata.get("dependencies", [])
    if not isinstance(dependencies, list) or len(dependencies) != len(locked):
        raise ValueError("Native crowd dependency inventory differs from Cargo.lock")
    seen = set()
    prepared = []
    for dependency in dependencies:
        identity = (dependency["name"], dependency["version"])
        archive_name = f"{identity[0]}-{identity[1]}.crate"
        expected_url = f"https://static.crates.io/crates/{identity[0]}/{archive_name}"
        if (
            identity in seen
            or identity not in locked
            or dependency.get("sha256") != locked[identity]
            or dependency.get("source_archive") != expected_url
        ):
            raise ValueError(
                "Native crowd dependency provenance differs from Cargo.lock"
            )
        seen.add(identity)
        matches = list(
            (ROOT / ".cache/cargo-godot/registry/cache").glob(f"*/{archive_name}")
        )
        if len(matches) != 1 or file_hash(matches[0]) != locked[identity]:
            raise ValueError(
                f"Missing or altered locked crowd source archive: {archive_name}"
            )
        archive = matches[0]
        notices = _crate_notices(archive, identity, dependency.get("license"))
        prepared.append((dependency, archive, notices))
    mpl = crate / "licenses/MPL-2.0.txt"
    if file_hash(mpl) != MPL_SHA256:
        raise ValueError("Cached official MPL-2.0 license checksum differs")
    # Verify every optional build input before copying this component.
    for source in (binary, descriptor, stamp):
        _copy_input(source, output / source.relative_to(ROOT), inputs)
    for name in sorted(
        CROWD_SOURCE_FILES
        | {"README.md", "licenses/sources.json", "licenses/MPL-2.0.txt"}
    ):
        _copy_input(crate / name, output / "native/civic-godot" / name, inputs)
    _copy_input(mpl, output / "licenses/native-crowd/MPL-2.0.txt", inputs, MPL_SHA256)
    source_records = []
    for dependency, archive, notices in prepared:
        relative = Path("sources/native-crowd") / archive.name
        _copy_input(archive, output / relative, inputs, dependency["sha256"])
        label = f"{dependency['name']}-{dependency['version']}"
        license_paths = []
        for name, data in notices:
            target = inside(output / "licenses/native-crowd" / label, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            license_paths.append(target.relative_to(output).as_posix())
        source_records.append(
            {
                **dependency,
                "packaged_source": relative.as_posix(),
                "notices": license_paths,
            }
        )
    notice = {
        "schema_version": 1,
        "helper_source": "native/civic-godot",
        "mpl_text": "licenses/native-crowd/MPL-2.0.txt",
        "mpl_source": "https://www.mozilla.org/media/MPL/2.0/index.txt",
        "dependencies": source_records,
    }
    notice_path = output / "licenses/native-crowd/SOURCES.json"
    notice_path.write_bytes(canonical_bytes(notice))
    (notice_path.parent / "README.txt").write_text(
        "The optional CivicCrowdBuffers helper uses the pinned dependencies in SOURCES.json.\n"
        "Their complete, unchanged source archives are included under sources/native-crowd.\n"
        "SOURCES.json records each archive's registry URL, SHA256 and declared license.\n"
        "Original license/copyright notices are copied here and retained inside those archives.\n"
        "The godot-rust and gdextension-api sources are covered by MPL-2.0; its text is included.\n"
        "The helper's own source, Cargo.lock and rebuild instructions are in native/civic-godot.\n",
        encoding="utf-8",
    )
    return {
        **metadata,
        "packaged_source_bytes": sum(path.stat().st_size for _, path, _ in prepared),
        "source_inventory": "licenses/native-crowd/SOURCES.json",
    }


def _crate_notices(
    archive: Path, identity: tuple[str, str], declared_license: str | None
) -> list[tuple[str, bytes]]:
    """Read bounded files from a checksum-verified archive without extracting it."""
    prefix = f"{identity[0]}-{identity[1]}/"
    notices = []
    with tarfile.open(archive, "r:gz") as source:
        manifest = source.extractfile(prefix + "Cargo.toml")
        if manifest is None:
            raise ValueError("Locked dependency archive has no Cargo manifest")
        package = tomllib.loads(manifest.read(1024 * 1024).decode("utf-8"))["package"]
        if package.get("license") != declared_license:
            raise ValueError(
                "Dependency license inventory differs from its source archive"
            )
        for member in source.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            name = member.name[len(prefix) :]
            leaf = Path(name).name.lower()
            if not leaf.startswith(
                ("license", "licence", "copying", "copyright", "notice", "unlicense")
            ):
                continue
            # Validate even names we only read; never permit traversal on copy.
            inside(Path("notice-root").resolve(), name)
            if member.size > 1024 * 1024:
                raise ValueError("Dependency notice exceeds its 1 MiB bound")
            stream = source.extractfile(member)
            if stream is not None:
                notices.append((name, stream.read()))
    if not notices and declared_license != "MPL-2.0":
        # This derive subcrate omits the workspace license from its archive.
        # Its paired nanoserde crate includes it at the exact same Git revision.
        if identity != ("nanoserde-derive", "0.2.1"):
            raise ValueError(
                f"No original license notices found for dependency {identity[0]}"
            )
        sibling = archive.with_name("nanoserde-0.2.1.crate")
        if (
            file_hash(sibling)
            != "a36fb3a748a4c9736ed7aeb5f2dfc99665247f1ce306abbddb2bf0ba2ac530a4"
        ):
            raise ValueError("Nanoserde workspace license archive checksum differs")
        with (
            tarfile.open(archive, "r:gz") as original,
            tarfile.open(sibling, "r:gz") as workspace,
        ):
            original_vcs = json.load(
                original.extractfile(prefix + ".cargo_vcs_info.json")
            )
            workspace_vcs = json.load(
                workspace.extractfile("nanoserde-0.2.1/.cargo_vcs_info.json")
            )
            if (
                original_vcs["git"]["sha1"] != workspace_vcs["git"]["sha1"]
                or original_vcs.get("path_in_vcs") != "derive"
            ):
                raise ValueError(
                    "Nanoserde derive license has a different source revision"
                )
            notices.append(
                (
                    "LICENSE-MIT",
                    workspace.extractfile("nanoserde-0.2.1/LICENSE-MIT").read(),
                )
            )
            notices.append(
                (
                    "LICENSE-SOURCE.txt",
                    (
                        "The derive crate omits its workspace license. This unchanged MIT notice\n"
                        "comes from nanoserde-0.2.1.crate at the same Git revision recorded in\n"
                        "both source archives: " + original_vcs["git"]["sha1"] + "\n"
                        "https://github.com/not-fl3/nanoserde/tree/"
                        + original_vcs["git"]["sha1"]
                        + "\n"
                    ).encode("utf-8"),
                )
            )
    return notices


def copy_city_data(output: Path, geography: Path, terrain: Path | None) -> dict:
    raw = geography.read_bytes()
    manifest = json.loads(raw)
    if not manifest.get("complete") or content_hash(
        {k: v for k, v in manifest.items() if k != "sha256"}
    ) != manifest.get("sha256"):
        raise ValueError(
            "City geography is incomplete or its manifest checksum differs"
        )
    target = output / ".local/civic/geography"
    copy_verified(geography, target / "sf-geography.json")
    for relative, expected in manifest["files"].items():
        copy_verified(
            inside(geography.parent, relative), inside(target, relative), expected
        )
    visual_path = geography.parent / "visual-index.json"
    if visual_path.is_file():
        visual = json.loads(visual_path.read_bytes())
        if (
            visual.get("geography_sha256") != manifest["sha256"]
            or visual.get("geography_file_sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise ValueError("Visual index is from a different geographic source")
        copy_verified(visual_path, target / "visual-index.json")
        for tile in visual["tiles"]:
            copy_verified(
                inside(geography.parent, tile["path"]),
                inside(target, tile["path"]),
                tile["sha256"],
            )
    result = {
        "geography_sha256": manifest["sha256"],
        "geography_file_sha256": hashlib.sha256(raw).hexdigest(),
    }
    places_path = geography.parent / "places-index.json"
    if places_path.is_file():
        places = json.loads(places_path.read_bytes())
        if (
            places.get("geography_sha256") != manifest["sha256"]
            or places.get("geography_file_sha256") != hashlib.sha256(raw).hexdigest()
            or content_hash({k: v for k, v in places.items() if k != "sha256"})
            != places.get("sha256")
        ):
            raise ValueError(
                "Named places index is invalid or from a different geographic source"
            )
        copy_verified(places_path, target / "places-index.json")
        copy_verified(
            inside(geography.parent, places["areas_path"]),
            inside(target, places["areas_path"]),
            places["areas_sha256"],
        )
        result["places_sha256"] = places["sha256"]
    trees_path = geography.parent / "tree-index.json"
    if trees_path.is_file():
        trees = json.loads(trees_path.read_bytes())
        if (
            trees.get("geography_sha256") != manifest["sha256"]
            or trees.get("geography_file_sha256") != hashlib.sha256(raw).hexdigest()
            or content_hash({k: v for k, v in trees.items() if k != "sha256"})
            != trees.get("sha256")
            or trees.get("source", {}).get("id") != "uzd4-f6yf"
        ):
            raise ValueError(
                "Tree index is invalid or from a different geographic source"
            )
        copy_verified(trees_path, target / "tree-index.json")
        for tile in trees["tiles"]:
            copy_verified(
                inside(geography.parent, tile["path"]),
                inside(target, tile["path"]),
                tile["sha256"],
            )
        result["trees_sha256"] = trees["sha256"]
    use_path = geography.parent / "use-index.json"
    if use_path.is_file():
        use_index = json.loads(use_path.read_bytes())
        if (
            use_index.get("geography_sha256") != manifest["sha256"]
            or use_index.get("geography_file_sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise ValueError("Use overlay is from a different geographic source")
        copy_verified(use_path, target / "use-index.json")
        for tile in use_index["tiles"]:
            for path_key, hash_key in (
                ("path", "sha256"),
                ("color_path", "color_sha256"),
            ):
                if tile.get(path_key):
                    copy_verified(
                        inside(geography.parent, tile[path_key]),
                        inside(target, tile[path_key]),
                        tile[hash_key],
                    )
        result["use_overlay_landuse_sha256"] = use_index["landuse_sha256"]
    if terrain is not None:
        from civic_center.terrain import TerrainGrid

        grid = TerrainGrid(json.loads(terrain.read_bytes()))
        target = output / ".local/civic/terrain"
        copy_verified(terrain, target / "terrain.json")
        for key in ("catalog", "service_metadata"):
            relative = grid.data.get("source", {}).get(key)
            if relative:
                copy_verified(
                    inside(terrain.parent, relative), inside(target, relative)
                )
        result["terrain_file_sha256"] = file_hash(terrain)
    return result


def write_launchers(output: Path) -> None:
    launch = "\n".join(
        [
            "@echo off",
            "setlocal",
            'pushd "%~dp0"',
            '"%~dp0runtime\\python\\python.exe" -u -m civic_center %*',
            'set "civic_result=%errorlevel%"',
            'if not "%civic_result%"=="0" pause',
            "popd",
            "exit /b %civic_result%",
            "",
        ]
    )
    (output / "Start San Francisco.cmd").write_text(
        launch, encoding="utf-8", newline="\r\n"
    )
    verify_command = "\n".join(
        [
            "@echo off",
            "setlocal",
            'pushd "%~dp0"',
            '"%~dp0runtime\\python\\python.exe" -m civic_center.package_verify',
            'set "civic_result=%errorlevel%"',
            "pause",
            "popd",
            "exit /b %civic_result%",
            "",
        ]
    )
    (output / "Verify files.cmd").write_text(
        verify_command, encoding="utf-8", newline="\r\n"
    )
    (output / "START HERE.txt").write_text(
        "OpenGlassBox - San Francisco\n\n"
        "Double-click Start San Francisco.cmd. Keep this folder together in a writable location.\n"
        "Python and Godot are included; no separate installation is required.\n"
        "A loading window shows progress while the resident cohort and scenery prepare.\n\n"
        "H = City Hall, G = city overview, WASD = move, Q/E = rotate, wheel = zoom.\n"
        "1/2/3/4 = overhead/walk/follow/2D map. Click to inspect; Tab shows panels.\n"
        "Space = pause, N = next activity, F5/F9 = save/load.\n\n"
        "Search places and landmarks by name. U shows observed parcel uses.\n"
        "The view options control daylight, illustrative facades and street trees.\n\n"
        "The geography covers San Francisco. Homes, jobs, residents and schedules\n"
        "are generated examples, not a measured or calibrated city population.\n"
        "Data observation dates and approximations are documented in docs/SF_GEOGRAPHY.md.\n\n"
        "Saved days and runtime caches stay under .local/civic inside this folder.\n"
        "Verify files.cmd checks shipped file integrity; new saves/caches are allowed.\n"
        "This is a local development build using the full Godot executable.\n"
        "See licenses for Python, Godot, third-party components and data notices.\n",
        encoding="utf-8",
    )


def collect_godot_licenses(output: Path, godot: Path) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    script = CACHE / "godot-licenses.gd"
    script.write_text(
        "extends SceneTree\nfunc _initialize() -> void:\n"
        "\tvar directory: String = OS.get_cmdline_user_args()[0]\n"
        '\tvar license_file := FileAccess.open(directory.path_join("Godot-LICENSE.txt"),FileAccess.WRITE)\n'
        "\tlicense_file.store_string(Engine.get_license_text())\n"
        '\tvar info := {"engine":Engine.get_version_info(),"copyright":Engine.get_copyright_info(),"licenses":Engine.get_license_info()}\n'
        '\tvar info_file := FileAccess.open(directory.path_join("Godot-third-party.json"),FileAccess.WRITE)\n'
        '\tinfo_file.store_string(JSON.stringify(info,"  "))\n'
        "\tquit()\n",
        encoding="utf-8",
    )
    license_dir = output / "licenses"
    license_dir.mkdir(exist_ok=True)
    environment = os.environ.copy()
    for key, leaf in (("APPDATA", "roaming"), ("LOCALAPPDATA", "local")):
        path = CACHE / leaf
        path.mkdir(exist_ok=True)
        environment[key] = str(path)
    result = subprocess.run(
        [
            str(godot),
            "--headless",
            "--path",
            str(output / "viewer"),
            "--script",
            str(script),
            "--",
            str(license_dir),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    if result.returncode or not (license_dir / "Godot-third-party.json").is_file():
        raise ValueError(
            "Godot license extraction failed: "
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pilot-only", action="store_true")
    parser.add_argument(
        "--geography",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-geography.json",
    )
    parser.add_argument(
        "--terrain", type=Path, default=ROOT / ".local/civic/terrain/terrain.json"
    )
    parser.add_argument(
        "--render-cache",
        type=Path,
        help="Optionally ship validated .sfmesh entries from this prepared scenery directory",
    )
    parser.add_argument(
        "--download-runtime",
        action="store_true",
        help="Allow first download of pinned Python and monitoring wheels",
    )
    parser.add_argument(
        "--without-native",
        action="store_true",
        help="Omit native routing and crowd helpers; use Python/GDScript fallbacks",
    )
    parser.add_argument(
        "--landuse", type=Path, default=ROOT / ".local/civic/landuse/landuse.json"
    )
    parser.add_argument("--zip", action="store_true", help="Also create a ZIP archive")
    args = parser.parse_args()
    if args.render_cache is not None and args.pilot_only:
        parser.error("--render-cache requires a city build with its source geography")
    output = (
        args.output
        or ROOT
        / "dist"
        / ("san-francisco-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    ).resolve()
    if not output.is_relative_to(ROOT / "dist") or output == ROOT / "dist":
        parser.error(
            "Choose a new output directory inside this workspace's dist folder"
        )
    if output.exists():
        parser.error("Output already exists; choose a new build directory")
    archive = python_archive(args.download_runtime)
    hardware_archives = monitoring_archives(CACHE, args.download_runtime)
    godot = Path(find_godot()).resolve()
    if not godot.name.endswith("_console.exe"):
        parser.error("A Windows Godot console executable is required for this builder")
    engine = godot.with_name(godot.name.replace("_console.exe", ".exe"))
    if not engine.is_file():
        parser.error("The console executable's companion Godot binary is missing")
    output.mkdir(parents=True)
    print(f"Building {output}", flush=True)
    inputs = copy_application_sources(output)
    inputs["scripts/package_civic_windows.py"] = file_hash(Path(__file__).resolve())
    inputs["scripts/package_monitoring.py"] = file_hash(
        ROOT / "scripts/package_monitoring.py"
    )
    for hardware_input in [*hardware_archives, CACHE / CACHE_MANIFEST]:
        inputs[hardware_input.relative_to(ROOT).as_posix()] = file_hash(hardware_input)
    runtime = output / "runtime/python"
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = inside(runtime, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(member))
    monitoring = install_monitoring(output, hardware_archives)
    (runtime / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n..\\..\n", encoding="utf-8"
    )
    runtime_check = subprocess.run(
        [
            str(runtime / "python.exe"),
            "-c",
            "import civic_center,sys,psutil,pynvml; from pathlib import Path; "
            "base=Path(sys.executable).parent.resolve(); "
            "assert all(Path(m.__file__).resolve().is_relative_to(base) "
            "for m in (psutil,pynvml)); "
            "print(civic_center.__file__); print(sys.executable); print(psutil.__version__)",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=output,
    )
    if (
        runtime_check.returncode
        or str(output / "civic_center") not in runtime_check.stdout
    ):
        raise ValueError(
            "Bundled Python cannot import the packaged application and monitoring: "
            + runtime_check.stderr
        )
    for executable in (godot, engine):
        copy_verified(executable, output / "runtime/godot" / executable.name)
    native_metadata, crowd_metadata = copy_native_components(
        output, inputs, enabled=not args.without_native
    )
    sources = (
        {}
        if args.pilot_only
        else copy_city_data(
            output,
            args.geography.resolve(),
            args.terrain.resolve() if args.terrain.is_file() else None,
        )
    )
    if not args.pilot_only and args.landuse.is_file():
        from civic_center.landuse import LandUseIndex

        landuse = LandUseIndex.load(args.landuse)
        copy_verified(args.landuse, output / ".local/civic/landuse/landuse.json")
        sources["landuse_sha256"] = landuse.data["sha256"]
        sources["landuse_file_sha256"] = file_hash(args.landuse)
        if (
            sources.get("use_overlay_landuse_sha256", landuse.data["sha256"])
            != landuse.data["sha256"]
        ):
            raise ValueError(
                "Packaged use colors and resident allocation refer to different land-use sources"
            )
    render_cache = copy_render_cache(args.render_cache, output)
    for name in (
        "SF_GEOGRAPHY.md",
        "GODOT_NEXT_STEPS.md",
        "WINDOWS_BUILD.md",
        "OVERNIGHT_PROGRESS.md",
    ):
        copy_verified(ROOT / "docs" / name, output / "docs" / name)
    copy_verified(ROOT / "civic_center/README.md", output / "civic_center/README.md")
    for name in ("CIVIC_PROTOCOL.md", "one-resident-replay.json"):
        copy_verified(ROOT / "contracts" / name, output / "contracts" / name)
    copy_verified(ROOT / "LICENSE", output / "licenses/OpenGlassBox-LICENSE.txt")
    copy_verified(ROOT / "docs/SF_GEOGRAPHY.md", output / "licenses/DATA-NOTICES.md")
    copy_verified(runtime / "LICENSE.txt", output / "licenses/Python-LICENSE.txt")
    collect_godot_licenses(output, godot)
    write_launchers(output)
    for relative, digest in inputs.items():
        if file_hash(ROOT / relative) != digest:
            raise ValueError(
                f"Build input changed during packaging; repeat in a new directory: {relative}"
            )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": "Windows x86_64",
        "world": "pilot" if args.pilot_only else "San Francisco",
        "python": {
            "version": PYTHON_VERSION,
            "url": PYTHON_URL,
            "release_manifest": PYTHON_RELEASE,
            "sha256": PYTHON_SHA256,
        },
        "godot": {"binary": engine.name, "sha256": file_hash(engine)},
        "monitoring": monitoring,
        "native_routing": native_metadata,
        "native_crowd": crowd_metadata,
        "render_cache": render_cache,
        "build_inputs": inputs,
        "sources": sources,
        "files": {},
    }
    for path in sorted(output.rglob("*")):
        if path.is_file() and "__pycache__" not in path.relative_to(output).parts:
            manifest["files"][path.relative_to(output).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": file_hash(path),
            }
    (output / "package-manifest.json").write_bytes(canonical_bytes(manifest))
    result = verify(output)
    if not result["valid"]:
        raise ValueError("Package verification failed: " + json.dumps(result))
    if args.zip:
        zip_path = output.with_suffix(".zip")
        if zip_path.exists():
            raise ValueError("ZIP path already exists")
        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as target:
            for relative in [*manifest["files"], "package-manifest.json"]:
                source = inside(output, relative)
                target.write(source, source.relative_to(output.parent).as_posix())
        result["zip"] = {
            "path": str(zip_path),
            "bytes": zip_path.stat().st_size,
            "sha256": file_hash(zip_path),
        }
    print(json.dumps({"output": str(output), **result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
