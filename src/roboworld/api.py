"""High-level operations shared by the CLI and the MCP server."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from roboworld import store
from roboworld.lang.gaits import available_gaits
from roboworld.lang.validate import check_source
from roboworld.robots import ensure_available, list_robots, load_manifest


def robots() -> list[dict[str, Any]]:
    return [
        {"name": e.name, "kind": e.kind, "available": e.available,
         "description": " ".join(str(e.manifest.get("description", "")).split())}
        for e in list_robots()
    ]


def describe(robot: str) -> dict[str, Any]:
    ensure_available(robot)
    m = load_manifest(robot)
    info = m.summary()
    info["gaits"] = {g: m.gaits.get(g, {}) for g in available_gaits(m)}
    info["safety"] = {"max_joint_speed_rad_s": m.max_joint_speed, "fall_tilt_deg": 60}
    return info


def language_reference() -> str:
    return resources.files("roboworld.lang").joinpath("reference.md").read_text()


def validate(robot: str, program: str | dict | list) -> dict[str, Any]:
    _, report = check_source(program, load_manifest(robot))
    return report.as_dict()


def simulate(robot: str, program: str | dict | list, max_seconds: float = 30.0, record: bool = True,
             snapshots: int = 4) -> dict[str, Any]:
    from roboworld.sim.runner import Simulation

    manifest = load_manifest(robot)
    parsed, report = check_source(program, manifest)
    if parsed is None or not report.ok:
        return {"status": "invalid", "validation": report.as_dict()}
    result = Simulation(robot).run(parsed, max_seconds=max_seconds, record=record, snapshots=snapshots)
    out = result.summary()
    out["validation"] = report.as_dict()
    out["contact_sheet"] = str(result.contact_sheet) if result.contact_sheet else None
    return out


def snapshot(robot: str, pose: str | None = None, joints: dict[str, float] | None = None,
             azimuth: float = 135.0, elevation: float = -18.0) -> np.ndarray:
    """Render the robot standing in a pose (no physics)."""
    from roboworld.sim.render import Camera
    from roboworld.sim.scene import build_scene, place_on_ground, set_joint_positions

    m = load_manifest(robot)
    model = build_scene(robot)
    data = mujoco.MjData(model)
    q = dict(m.pose(pose or m.default_pose))
    for k, v in (joints or {}).items():
        q[m.resolve_joint(k)] = m.clamp(m.resolve_joint(k), v)
    set_joint_positions(model, data, m, q)
    place_on_ground(model, data, m)
    cam = Camera(model, data, m)
    img = cam.render(data, azimuth=azimuth, elevation=elevation)
    cam.close()
    return img


def get_run(run_id: str) -> dict[str, Any]:
    return store.load_run(run_id)


def runs(limit: int = 20) -> list[dict[str, Any]]:
    return store.list_runs(limit)


def run_file(run_id: str, name: str) -> Path:
    return store.run_dir(run_id) / name
