"""Launch the City Hall application with ``python -m civic_center``."""

from pathlib import Path
import subprocess
import sys

# The Windows PATH on this checkout still points at Python 3.9. Prefer the
# project's environment so the documented command starts the tested runtime.
root = Path(__file__).resolve().parents[1]
local_python = root / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if local_python.is_file() and Path(sys.executable).resolve() != local_python.resolve():
    raise SystemExit(subprocess.call([str(local_python), "-m", "civic_center", *sys.argv[1:]], cwd=root))
if sys.version_info < (3, 10):
    raise SystemExit("City Hall requires Python 3.10 or later; create the workspace virtual environment first.")

from .launch import main

raise SystemExit(main())
