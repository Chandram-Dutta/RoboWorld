"""Record a run to a Rerun ``.rrd`` file: 3D replay, joint plots and events."""

from __future__ import annotations

from pathlib import Path

import mujoco
import numpy as np
import rerun as rr

from roboworld.lang.manifest import Manifest
from roboworld.sim.scene import FLOOR_NAME
from roboworld.sim.state import RobotState


def _rgba(model: mujoco.MjModel, g: int) -> list[int]:
    mat = model.geom_matid[g]
    rgba = model.mat_rgba[mat] if mat >= 0 else model.geom_rgba[g]
    return [int(255 * c) for c in rgba]


def _mesh(model: mujoco.MjModel, mesh_id: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    va, vn = model.mesh_vertadr[mesh_id], model.mesh_vertnum[mesh_id]
    fa, fn = model.mesh_faceadr[mesh_id], model.mesh_facenum[mesh_id]
    verts = model.mesh_vert[va : va + vn].astype(np.float32)
    faces = model.mesh_face[fa : fa + fn].astype(np.uint32)
    tri = verts[faces]
    face_n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals = np.zeros_like(verts)
    for k in range(3):
        np.add.at(normals, faces[:, k], face_n)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    return verts, faces, normals


class Recorder:
    """Buffers a run and writes it as one Rerun recording."""

    def __init__(self, model: mujoco.MjModel, manifest: Manifest, path: Path, run_id: str):
        self.model = model
        self.manifest = manifest
        self.path = path
        self.rec = rr.RecordingStream("roboworld", recording_id=run_id)
        self.rec.save(str(path))
        self.rec.send_recording_name(f"{manifest.robot} · {run_id}")
        self.geoms = self._visual_geoms()
        self._log_static()
        self.times: list[float] = []
        self.q: list[np.ndarray] = []
        self.targets: list[np.ndarray] = []
        self.torque: list[np.ndarray] = []
        self.base: list[np.ndarray] = []
        self.rpy: list[tuple[float, float, float]] = []

    def _visual_geoms(self) -> list[int]:
        m = self.model
        floor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, FLOOR_NAME)
        robot = [g for g in range(m.ngeom) if g != floor and m.geom_bodyid[g] != 0]
        visual = [g for g in robot if m.geom_group[g] <= 2 and m.geom_rgba[g][3] > 0]
        return visual or robot

    def _log_static(self) -> None:
        m, rec = self.model, self.rec
        rec.log("world", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)
        rec.log(
            "world/floor",
            rr.Boxes3D(half_sizes=[[3, 3, 0.002]], centers=[[0, 0, -0.002]], colors=[[200, 204, 210, 255]],
                       fill_mode="solid"),
            static=True,
        )
        floor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, FLOOR_NAME)
        static = [g for g in range(m.ngeom) if m.geom_bodyid[g] == 0 and g != floor]
        data = mujoco.MjData(m)
        mujoco.mj_forward(m, data)
        for g in static:  # walls, painted areas, fixed obstacles
            arch = self._geom_archetype(g)
            if arch is not None:
                rec.log(f"world/static/geom_{g}", arch, static=True)
                rec.log(f"world/static/geom_{g}", rr.Transform3D(translation=data.geom_xpos[g],
                                                                  mat3x3=data.geom_xmat[g].reshape(3, 3)), static=True)
        for g in self.geoms:
            arch = self._geom_archetype(g)
            if arch is not None:
                rec.log(f"world/robot/geom_{g}", arch, static=True)

    def _geom_archetype(self, g: int) -> object | None:
        m = self.model
        t, size, color = m.geom_type[g], m.geom_size[g], _rgba(m, g)
        if t == mujoco.mjtGeom.mjGEOM_MESH:
            verts, faces, normals = _mesh(m, int(m.geom_dataid[g]))
            arch = rr.Mesh3D(vertex_positions=verts, triangle_indices=faces, vertex_normals=normals,
                             albedo_factor=color)
        elif t == mujoco.mjtGeom.mjGEOM_BOX:
            arch = rr.Boxes3D(half_sizes=[size], colors=[color], fill_mode="solid")
        elif t == mujoco.mjtGeom.mjGEOM_SPHERE:
            arch = rr.Ellipsoids3D(half_sizes=[[size[0]] * 3], colors=[color], fill_mode="solid")
        elif t == mujoco.mjtGeom.mjGEOM_ELLIPSOID:
            arch = rr.Ellipsoids3D(half_sizes=[size], colors=[color], fill_mode="solid")
        elif t == mujoco.mjtGeom.mjGEOM_CAPSULE:
            arch = rr.Capsules3D(lengths=[2 * size[1]], radii=[size[0]], translations=[[0, 0, -size[1]]],
                                 colors=[color], fill_mode="solid")
        elif t == mujoco.mjtGeom.mjGEOM_CYLINDER:
            arch = rr.Cylinders3D(lengths=[2 * size[1]], radii=[size[0]], colors=[color], fill_mode="solid")
        else:
            return None
        return arch

    def frame(self, data: mujoco.MjData, state: RobotState, targets: np.ndarray) -> None:
        rec = self.rec
        rec.set_time("sim", duration=state.t)
        for g in self.geoms:
            rec.log(
                f"world/robot/geom_{g}",
                rr.Transform3D(translation=data.geom_xpos[g], mat3x3=data.geom_xmat[g].reshape(3, 3)),
            )
        self.times.append(state.t)
        self.q.append(state.q)
        self.targets.append(targets.copy())
        self.torque.append(state.torque)
        self.base.append(state.base_pos)
        self.rpy.append((state.roll, state.pitch, state.yaw))

    def event(self, t: float, text: str, level: str = "INFO") -> None:
        self.rec.set_time("sim", duration=t)
        self.rec.log("events", rr.TextLog(text, level=level))

    def text(self, path: str, body: str) -> None:
        self.rec.log(path, rr.TextDocument(body, media_type="text/markdown"), static=True)

    def close(self) -> None:
        rec = self.rec
        if self.times:
            times = rr.TimeColumn("sim", duration=np.asarray(self.times))
            q, tgt, tau = (np.asarray(a) for a in (self.q, self.targets, self.torque))
            for i, name in enumerate(self.manifest.joints):
                rec.send_columns(f"plots/joints/{name}/q", indexes=[times], columns=rr.Scalars.columns(scalars=q[:, i]))
                rec.send_columns(f"plots/joints/{name}/target", indexes=[times],
                                 columns=rr.Scalars.columns(scalars=tgt[:, i]))
                rec.send_columns(f"plots/torque/{name}", indexes=[times],
                                 columns=rr.Scalars.columns(scalars=tau[:, i]))
            base = np.asarray(self.base)
            rpy = np.degrees(np.asarray(self.rpy))
            rec.send_columns("plots/base/height", indexes=[times], columns=rr.Scalars.columns(scalars=base[:, 2]))
            for k, axis in enumerate(("roll", "pitch", "yaw")):
                rec.send_columns(f"plots/base/{axis}_deg", indexes=[times],
                                 columns=rr.Scalars.columns(scalars=rpy[:, k]))
            rec.log("world/trail", rr.LineStrips3D([base * [1, 1, 0] + [0, 0, 0.003]], colors=[[230, 120, 40, 255]],
                                                   radii=[0.004]), static=True)
        rec.flush()
        rec.disconnect()
