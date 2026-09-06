"""
Centralized pytest configuration for OpenGlassBox tests.

Adds the project root to sys.path so that ``from openglassbox.X import ...``
works regardless of whether the package has been pip-installed.
"""

import os
import sys

# Ensure the project root is on sys.path for non-installed usage
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
