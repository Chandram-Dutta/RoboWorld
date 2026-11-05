"""Filesystem locations used by RoboWorld.

Everything lives under the project root by default. Set ``ROBOWORLD_HOME`` to
point the data directories somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def _default_home() -> Path:
    # src/roboworld/paths.py -> project root (editable install / checkout).
    candidate = PACKAGE_DIR.parents[1]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


HOME = Path(os.environ.get("ROBOWORLD_HOME", _default_home())).resolve()
ASSETS_DIR = HOME / "assets"
ROBOT_ASSETS_DIR = ASSETS_DIR / "robots"
RUNS_DIR = HOME / "runs"
LIBRARY_DIR = HOME / "library"
CACHE_DIR = HOME / ".cache"
MANIFEST_DIR = PACKAGE_DIR / "robots" / "manifests"
