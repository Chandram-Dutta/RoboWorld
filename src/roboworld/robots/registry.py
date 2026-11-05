"""Robot registry: where robot models come from and how to load them.

Each robot is described by a YAML file containing a ``source`` (where to get
the MJCF), optional ``sim`` option overrides, and ``manifest`` overrides that
name its parts for RoboLang.

Built-in robots live in ``src/roboworld/robots/manifests/``. Robots users bring
themselves live in ``library/robots/<name>.yaml`` with ``source.type: path``.
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import mujoco
import yaml
from pydantic import BaseModel, Field

from roboworld import paths
from roboworld.lang.manifest import Manifest, build_manifest


class Source(BaseModel):
    type: Literal["git", "path"]
    model: str
    # git sources
    repo: str | None = None
    commit: str | None = None
    subdir: str = ""
    include: list[str] = Field(default_factory=list)
    # path sources (user robots); relative paths resolve against the YAML file
    path: str | None = None


class RobotEntry(BaseModel):
    name: str
    source: Source
    sim: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    config_file: Path | None = None

    @property
    def model_path(self) -> Path:
        if self.source.type == "path":
            base = self.config_file.parent if self.config_file else paths.HOME
            return (base / (self.source.path or ".") / self.source.model).resolve()
        return paths.ROBOT_ASSETS_DIR / self.name / self.source.model

    @property
    def available(self) -> bool:
        return self.model_path.exists()

    @property
    def kind(self) -> str:
        return self.manifest.get("kind", "other")


def _config_files() -> list[Path]:
    files = sorted(paths.MANIFEST_DIR.glob("*.yaml"))
    user_dir = paths.LIBRARY_DIR / "robots"
    if user_dir.exists():
        files += sorted(user_dir.glob("*.yaml"))
    return files


@lru_cache(maxsize=None)
def _entries() -> dict[str, RobotEntry]:
    entries: dict[str, RobotEntry] = {}
    for f in _config_files():
        data = yaml.safe_load(f.read_text())
        entry = RobotEntry(**data, config_file=f)
        entries[entry.name] = entry
    return entries


def reload() -> None:
    _entries.cache_clear()
    load_manifest.cache_clear()


def list_robots() -> list[RobotEntry]:
    return list(_entries().values())


def get_robot(name: str) -> RobotEntry:
    entries = _entries()
    if name not in entries:
        close = difflib.get_close_matches(name, list(entries), n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise KeyError(f"Unknown robot '{name}'. Known robots: {sorted(entries)}.{hint}")
    return entries[name]


def fetch(name: str, force: bool = False) -> Path:
    """Download a git-sourced robot into ``assets/robots/<name>`` (sparse, pinned)."""
    entry = get_robot(name)
    if entry.source.type != "git":
        return entry.model_path
    if entry.available and not force:
        return entry.model_path
    src = entry.source
    dest = paths.ROBOT_ASSETS_DIR / name
    with tempfile.TemporaryDirectory(dir=paths.CACHE_DIR if paths.CACHE_DIR.exists() else None) as tmp:
        repo_dir = Path(tmp) / "repo"

        def git(*args: str, cwd: Path | None = None) -> None:
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

        git("clone", "--filter=blob:none", "--no-checkout", "--sparse", src.repo or "", str(repo_dir))
        git("sparse-checkout", "set", src.subdir or ".", cwd=repo_dir)
        git("checkout", src.commit or "HEAD", cwd=repo_dir)
        root = repo_dir / src.subdir
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for item in src.include or [p.name for p in root.iterdir()]:
            path = root / item
            if path.is_dir():
                shutil.copytree(path, dest / item)
            elif path.exists():
                shutil.copy2(path, dest / item)
    return entry.model_path


def ensure_available(name: str) -> RobotEntry:
    entry = get_robot(name)
    if not entry.available:
        if entry.source.type == "git":
            fetch(name)
        else:
            raise FileNotFoundError(f"Model for robot '{name}' not found at {entry.model_path}")
    return entry


def load_robot_spec(name: str) -> mujoco.MjSpec:
    """The robot's MJCF as an editable MjSpec, with RoboWorld sim overrides applied."""
    entry = ensure_available(name)
    spec = mujoco.MjSpec.from_file(str(entry.model_path))
    for key, value in entry.sim.items():
        setattr(spec.option, key, value)
    return spec


@lru_cache(maxsize=None)
def load_manifest(name: str) -> Manifest:
    entry = ensure_available(name)
    model = load_robot_spec(name).compile()
    return build_manifest(name, model, dict(entry.manifest))
