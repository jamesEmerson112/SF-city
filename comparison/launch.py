"""Launch a native demo or a web renderer in its own desktop window."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ENGINES = ("godot", "panda3d", "three", "babylon", "deck", "cesium")


def command_for(engine, smoke, population=200, mode="overhead"):
    if engine == "godot":
        configured = os.environ.get("GODOT_BIN") or shutil.which("godot") or shutil.which("godot4")
        local = sorted((ROOT / ".tools" / "godot").glob("Godot*console.exe"))
        executable = configured or (str(local[0]) if local else None)
        if not executable:
            raise RuntimeError("Install Godot 4 and set GODOT_BIN to its executable. See comparison/README.md.")
        return [executable, "--path", str(ROOT / "godot"), "--", "--population", str(population), "--mode", mode, *(["--smoke-test"] if smoke else [])]
    if engine == "panda3d":
        candidates = [ROOT.parent / name / sub for name in ("venv", ".venv") for sub in ("Scripts/python.exe", "bin/python")]
        python = next((str(path) for path in candidates if path.is_file()), sys.executable)
        return [python, str(ROOT / "panda3d" / "main.py"), "--population", str(population), "--mode", mode, *(["--smoke-test"] if smoke else [])]
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Install Node.js 22.12+ and run npm ci in comparison/web first.")
    if not (ROOT / "web" / "node_modules").is_dir():
        raise RuntimeError("Run npm ci in comparison/web first.")
    return [node, str(ROOT / "web" / "scripts" / "desktop.mjs"), engine, "--population", str(population), "--mode", "orbit" if mode == "overhead" else mode, *(["--smoke-test"] if smoke else [])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", nargs="?", choices=ENGINES)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--population", type=int, choices=(200, 1000, 5000), default=200)
    parser.add_argument("--mode", choices=("overhead", "walk", "follow"), default="overhead")
    args = parser.parse_args()
    engine = args.engine
    if not engine:
        print("City Hall renderer comparison\n")
        for i, name in enumerate(ENGINES, 1):
            print("  {}. {}".format(i, name))
        answer = input("\nChoose engine (1-6, or name): ").strip().lower()
        engine = ENGINES[int(answer) - 1] if answer in tuple(str(i) for i in range(1, 7)) else answer
        if engine not in ENGINES:
            parser.error("Choose one of: " + ", ".join(ENGINES))
    try:
        return subprocess.call(command_for(engine, args.smoke_test, args.population, args.mode), cwd=ROOT.parent)
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
