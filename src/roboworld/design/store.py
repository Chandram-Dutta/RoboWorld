"""Designs on disk, with history.

    library/designs/<name>/spec.yaml   the RoboSpec
    library/designs/<name>/robot.xml   compiled MuJoCo model
    library/designs/<name>/meta.json   digest, parent, note, created, last check report
    library/robots/<name>.yaml         registry entry: makes it a normal RoboWorld robot
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from roboworld import paths
from roboworld.design.compiler import compile_spec
from roboworld.design.spec import RoboSpec
from roboworld.robots import registry


def design_dir(name: str) -> Path:
    return paths.LIBRARY_DIR / "designs" / name


def robot_entry(name: str) -> Path:
    return paths.LIBRARY_DIR / "robots" / f"{name}.yaml"


@dataclass
class Design:
    spec: RoboSpec
    meta: dict[str, Any]

    @property
    def name(self) -> str:
        return self.spec.name


def save(spec: RoboSpec, parent: str | None = None, note: str = "", overwrite: bool = False) -> Design:
    builtin = {e.name for e in registry.list_robots() if e.config_file and paths.MANIFEST_DIR in e.config_file.parents}
    if spec.name in builtin:
        raise ValueError(f"'{spec.name}' is a built-in robot; pick another name")
    folder = design_dir(spec.name)
    if folder.exists() and not overwrite:
        raise FileExistsError(f"design '{spec.name}' already exists; derive a new one or pass overwrite")
    if parent is not None and not design_dir(parent).exists():
        raise KeyError(f"no design named '{parent}'")
    xml, manifest = compile_spec(spec)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spec.yaml").write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False))
    (folder / "robot.xml").write_text(xml)
    meta = {"name": spec.name, "digest": spec.digest(), "parent": parent, "note": note, "template": spec.template,
            "created": datetime.now().isoformat(timespec="seconds"), "check": None}
    (folder / "meta.json").write_text(json.dumps(meta, indent=2))
    entry = {"name": spec.name, "source": {"type": "path", "path": f"../designs/{spec.name}", "model": "robot.xml"},
             "manifest": manifest}
    robot_entry(spec.name).parent.mkdir(parents=True, exist_ok=True)
    robot_entry(spec.name).write_text(yaml.safe_dump(entry, sort_keys=False))
    registry.reload()
    return Design(spec, meta)


def load(name: str) -> Design:
    folder = design_dir(name)
    if not folder.exists():
        known = ", ".join(d["name"] for d in list_designs()) or "none yet"
        raise KeyError(f"no design named '{name}'. Designs: {known}")
    spec = RoboSpec(**yaml.safe_load((folder / "spec.yaml").read_text()))
    return Design(spec, json.loads((folder / "meta.json").read_text()))


def update_meta(name: str, **fields: Any) -> None:
    f = design_dir(name) / "meta.json"
    meta = json.loads(f.read_text())
    meta.update(fields)
    f.write_text(json.dumps(meta, indent=2, default=str))


def history(name: str) -> list[dict[str, Any]]:
    """The design and its ancestors, newest first."""
    chain, seen = [], set()
    while name and name not in seen:
        seen.add(name)
        d = load(name)
        check = d.meta.get("check") or {}
        chain.append({"name": name, "parent": d.meta.get("parent"), "note": d.meta.get("note"),
                      "created": d.meta.get("created"), "digest": d.meta.get("digest"),
                      "check": check.get("summary")})
        name = d.meta.get("parent")
    return chain


def list_designs() -> list[dict[str, Any]]:
    root = paths.LIBRARY_DIR / "designs"
    out = []
    for folder in sorted(root.iterdir()) if root.exists() else []:
        f = folder / "meta.json"
        if f.exists():
            meta = json.loads(f.read_text())
            out.append({k: meta.get(k) for k in ("name", "parent", "note", "template", "created")}
                       | {"check": (meta.get("check") or {}).get("summary")})
    return out


def delete(name: str) -> None:
    shutil.rmtree(design_dir(name), ignore_errors=True)
    robot_entry(name).unlink(missing_ok=True)
    registry.reload()
