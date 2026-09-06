"""Local launcher handoff and cancelable scenario preparation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def write_status(path: Path, status: str, message: str, **fields: object) -> None:
    """Publish a complete local startup record; readers never see partial JSON."""
    from .geography import atomic_write

    atomic_write(
        path,
        json.dumps(
            {"schema_version": 1, "status": status, "message": message, **fields},
            allow_nan=False,
        ).encode("utf-8"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    from .launch import _prepared_city_scenario

    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        result = _prepared_city_scenario(
            Path(request["geography"]),
            Path(request["terrain"]) if request.get("terrain") else None,
            request["population"],
            request["seed"],
            Path(request["landuse"]) if request.get("landuse") else None,
        )
        write_status(args.result, "ready", "Residents prepared", scenario=str(result))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        write_status(args.result, "error", str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
