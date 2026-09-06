"""Pinned monitoring wheels for the isolated Windows embeddable runtime."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PureWindowsPath
from urllib.request import urlopen

from civic_center.package_verify import file_hash, inside

# Selected from the official, version-specific PyPI JSON metadata on 2026-09-06.
# psutil's CPython stable ABI wheel supports the packaged CPython 3.13 x64.
WHEELS = (
    {
        "name": "psutil",
        "version": "7.2.2",
        "filename": "psutil-7.2.2-cp37-abi3-win_amd64.whl",
        "url": "https://files.pythonhosted.org/packages/b4/90/e2159492b5426be0c1fef7acba807a03511f97c5f86b3caeda6ad92351a7/psutil-7.2.2-cp37-abi3-win_amd64.whl",
        "sha256": "eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988",
        "metadata_url": "https://pypi.org/pypi/psutil/7.2.2/json",
    },
    {
        "name": "nvidia-ml-py",
        "version": "13.610.43",
        "filename": "nvidia_ml_py-13.610.43-py3-none-any.whl",
        "url": "https://files.pythonhosted.org/packages/23/45/caa600acfab94560807a20a64b5830d2cd3c3202b7f1328644d70b7d6bd8/nvidia_ml_py-13.610.43-py3-none-any.whl",
        "sha256": "f13c72698edef492f985cc225f14faafe68ae065a2e407f45bdf6f4b9b43fde8",
        "metadata_url": "https://pypi.org/pypi/nvidia-ml-py/13.610.43/json",
        # This wheel retains its complete BSD notice at the top of the source.
        "embedded_notices": ["pynvml.py"],
    },
)
CACHE_MANIFEST = "hardware-wheels.json"
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_FILES = 512
SITE_PACKAGES = "runtime/python/Lib/site-packages"


def monitoring_archives(cache: Path, allow_download: bool) -> list[Path]:
    """Use checksum-verified cached wheels; fetch only with explicit build flag."""
    archives = []
    for specification in WHEELS:
        target = cache / specification["filename"]
        if not target.is_file():
            if not allow_download:
                raise ValueError(
                    f"Monitoring wheel {target.name} is not cached; "
                    "run again with --download-runtime"
                )
            with urlopen(specification["url"], timeout=30) as response:
                payload = response.read(MAX_ARCHIVE_BYTES + 1)
            if (
                len(payload) > MAX_ARCHIVE_BYTES
                or hashlib.sha256(payload).hexdigest() != specification["sha256"]
            ):
                raise ValueError("Monitoring wheel differs from its pinned PyPI SHA256")
            cache.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        if (
            target.stat().st_size > MAX_ARCHIVE_BYTES
            or file_hash(target) != specification["sha256"]
        ):
            raise ValueError(
                f"Cached monitoring wheel checksum mismatch: {target.name}"
            )
        archives.append(target)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / CACHE_MANIFEST).write_text(
        json.dumps({"schema_version": 1, "wheels": WHEELS}, indent=2) + "\n",
        encoding="utf-8",
    )
    return archives


def install_monitoring(output: Path, archives: list[Path]) -> dict:
    """Extract whole verified wheels, preserving dist-info and original notices."""
    if len(archives) != len(WHEELS):
        raise ValueError("Monitoring wheel inventory differs from the pinned set")
    destination = inside(output, SITE_PACKAGES)
    pending: list[tuple[Path, bytes]] = []
    seen = set()
    dependencies = []
    total_bytes = 0
    for specification, archive in zip(WHEELS, archives):
        if (
            archive.name != specification["filename"]
            or archive.stat().st_size > MAX_ARCHIVE_BYTES
            or file_hash(archive) != specification["sha256"]
        ):
            raise ValueError("Monitoring wheel differs from its pinned PyPI SHA256")
        files = 0
        notices = []
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ValueError("Monitoring wheel exceeds its file-count limit")
            for member in members:
                name = member.orig_filename.rstrip("/")
                parts = name.split("/")
                if (
                    not name
                    or "\\" in name
                    or ":" in name
                    or any(
                        part in ("", ".", "..") or part.endswith((" ", "."))
                        for part in parts
                    )
                    or any(PureWindowsPath(part).is_reserved() for part in parts)
                    or stat.S_ISLNK(member.external_attr >> 16)
                    or parts[0].endswith(".data")
                ):
                    raise ValueError(
                        f"Unsafe or unsupported monitoring wheel path: {name}"
                    )
                target = inside(destination, name)
                if member.is_dir():
                    continue
                identity = name.casefold()
                if identity in seen or target.exists():
                    raise ValueError(f"Duplicate monitoring wheel target: {name}")
                seen.add(identity)
                total_bytes += member.file_size
                if total_bytes > MAX_EXTRACTED_BYTES:
                    raise ValueError("Monitoring wheels exceed their extraction limit")
                payload = source.read(member)
                pending.append((target, payload))
                files += 1
                if name in specification.get(
                    "embedded_notices", ()
                ) or target.name.lower().startswith(
                    ("license", "licence", "copying", "copyright", "notice")
                ):
                    notices.append(target.relative_to(output.resolve()).as_posix())
        dependencies.append({**specification, "files": files, "notices": notices})
    # Check all archive paths, sizes, checksums and CRCs before any extraction.
    for target, payload in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return {"site_packages": SITE_PACKAGES, "dependencies": dependencies}
