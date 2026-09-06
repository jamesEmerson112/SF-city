"""Prepare reusable Godot scenery before launching the resident simulation."""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.launch import _terminate_tree, find_godot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geography",
        type=Path,
        default=ROOT / ".local/civic/geography/sf-geography.json",
    )
    parser.add_argument(
        "--terrain", type=Path, default=ROOT / ".local/civic/terrain/terrain.json"
    )
    parser.add_argument(
        "--render-cache", type=Path, default=ROOT / ".local/civic/render-cache"
    )
    parser.add_argument("--scope", choices=("city-hall", "city"), default="city-hall")
    parser.add_argument(
        "--radius",
        type=float,
        default=750.0,
        help="Half-width of the City Hall area in meters",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / ".cache/scenery-prepare.json"
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.radius) or args.radius <= 0:
        parser.error("Radius must be finite and positive")
    if not args.geography.is_file() or not args.terrain.is_file():
        parser.error(
            "Install geography and terrain first, or provide their manifest paths"
        )
    args.render_cache.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    if sys.platform == "win32":
        for key, leaf in (("APPDATA", "roaming"), ("LOCALAPPDATA", "local")):
            path = ROOT / ".local/civic/runtime" / leaf
            path.mkdir(parents=True, exist_ok=True)
            environment[key] = str(path)
    command = [
        find_godot(),
        "--headless",
        "--path",
        str(ROOT / "viewer"),
        "--script",
        "res://prepare_scenery.gd",
        "--",
        "--geography",
        str(args.geography.resolve()),
        "--terrain",
        str(args.terrain.resolve()),
        "--render-cache",
        str(args.render_cache.resolve()),
        "--scope",
        args.scope,
        "--radius",
        str(args.radius),
        "--report",
        str(args.report.resolve()),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    completed = False
    script_error = False
    try:
        for line in process.stdout:
            print(line, end="", flush=True)
            completed = completed or line.startswith("SCENERY_PREPARE_OK ")
            script_error = (
                script_error or "SCRIPT ERROR" in line or "Parse Error" in line
            )
        code = process.wait()
        return code if code else (0 if completed and not script_error else 1)
    except KeyboardInterrupt:
        return 130
    finally:
        if process.poll() is None:
            _terminate_tree(process)
        process.stdout.close()


if __name__ == "__main__":
    raise SystemExit(main())
