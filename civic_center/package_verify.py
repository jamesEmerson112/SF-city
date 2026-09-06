"""Verify the shipped files in a portable application folder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def inside(directory: Path, relative: str) -> Path:
    """Resolve a manifest member without accepting absolute or escaping paths."""
    directory = directory.resolve()
    member = Path(relative)
    resolved = (directory / member).resolve()
    if (
        member.is_absolute()
        or member.drive
        or resolved == directory
        or not resolved.is_relative_to(directory)
    ):
        raise ValueError(f"Manifest path escapes the package: {relative}")
    return resolved


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = json.loads(
        (directory / "package-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("files"), dict
    ):
        raise ValueError("Unsupported package manifest")
    failures = []
    total = 0
    for relative, descriptor in manifest["files"].items():
        path = inside(directory, relative)
        if not path.is_file():
            failures.append({"path": relative, "reason": "missing"})
        elif (
            path.stat().st_size != descriptor["bytes"]
            or file_hash(path) != descriptor["sha256"]
        ):
            failures.append({"path": relative, "reason": "content differs"})
        total += descriptor["bytes"]
    return {
        "valid": not failures,
        "files": len(manifest["files"]),
        "bytes": total,
        "failures": failures,
    }


def main() -> int:
    try:
        result = verify(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Package verification failed: {error}")
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
