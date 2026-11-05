"""Read a compact robot state from MuJoCo data (what controllers and predicates see)."""

from __future__ import annotations

from dataclasses import dataclass, field

import mujoco
import numpy as np

from roboworld.lang.manifest import Manifest
from roboworld.sim.scene import FLOOR_NAME
from roboworld.sim.servo import ServoLayer


@dataclass
class RobotState:
    t: float
    q: np.ndarray
    qd: np.ndarray
    torque: np.ndarray
    base_pos: np.ndarray
    base_rot: np.ndarray  # 3x3, base frame -> world
    base_linvel: np.ndarray  # world frame
    gyro: np.ndarray  # base frame angular velocity
    roll: float
    pitch: float
    yaw: float
    effectors: dict[str, np.ndarray] = field(default_factory=dict)  # world positions
    contacts: dict[str, bool] = field(default_factory=dict)  # feet touching the floor

    @property
    def up_z(self) -> float:
        """z component of the base's up axis: 1 upright, 0 on its side."""
        return float(self.base_rot[2, 2])


def rpy_from_rot(r: np.ndarray) -> tuple[float, float, float]:
    roll = float(np.arctan2(r[2, 1], r[2, 2]))
    pitch = float(np.arcsin(np.clip(-r[2, 0], -1.0, 1.0)))
    yaw = float(np.arctan2(r[1, 0], r[0, 0]))
    return roll, pitch, yaw


class StateReader:
    def __init__(self, model: mujoco.MjModel, manifest: Manifest, servo: ServoLayer):
        self.model = model
        self.manifest = manifest
        self.servo = servo
        self.base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, manifest.base_body)
        self.floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR_NAME)
        self.effector_ids: dict[str, tuple[int, int]] = {}
        self.foot_geoms: dict[str, set[int]] = {}
        for name, ee in manifest.end_effectors.items():
            kind, ref = ee.frame
            obj = {"site": mujoco.mjtObj.mjOBJ_SITE, "geom": mujoco.mjtObj.mjOBJ_GEOM,
                   "body": mujoco.mjtObj.mjOBJ_BODY}[kind]
            idx = mujoco.mj_name2id(model, obj, ref)
            if idx < 0:
                raise ValueError(f"End effector '{name}' refers to missing {kind} '{ref}'")
            self.effector_ids[name] = (int(obj), idx)
            if name in manifest.feet:
                body = {"site": model.site_bodyid, "geom": model.geom_bodyid}.get(kind)
                body_id = int(body[idx]) if body is not None else idx
                geoms = {g for g in range(model.ngeom) if model.geom_bodyid[g] == body_id
                         and (model.geom_contype[g] or model.geom_conaffinity[g])}
                if kind == "geom":
                    geoms = {idx}
                self.foot_geoms[name] = geoms
        self._vel = np.zeros(6)

    def effector_pos(self, data: mujoco.MjData, name: str) -> np.ndarray:
        obj, idx = self.effector_ids[name]
        if obj == mujoco.mjtObj.mjOBJ_SITE:
            return data.site_xpos[idx].copy()
        if obj == mujoco.mjtObj.mjOBJ_GEOM:
            return data.geom_xpos[idx].copy()
        return data.xpos[idx].copy()

    def read(self, data: mujoco.MjData) -> RobotState:
        m = self.model
        rot = data.xmat[self.base].reshape(3, 3).copy()
        mujoco.mj_objectVelocity(m, data, mujoco.mjtObj.mjOBJ_BODY, self.base, self._vel, 0)
        linvel = self._vel[3:].copy()
        gyro = rot.T @ self._vel[:3]
        roll, pitch, yaw = rpy_from_rot(rot)
        contacts = {foot: False for foot in self.foot_geoms}
        for i in range(data.ncon):
            c = data.contact[i]
            pair = (int(c.geom1), int(c.geom2))
            if self.floor not in pair:
                continue
            other = pair[1] if pair[0] == self.floor else pair[0]
            for foot, geoms in self.foot_geoms.items():
                if other in geoms:
                    contacts[foot] = True
        return RobotState(
            t=float(data.time),
            q=self.servo.q(data),
            qd=self.servo.qd(data),
            torque=self.servo.torque(data),
            base_pos=data.xpos[self.base].copy(),
            base_rot=rot,
            base_linvel=linvel,
            gyro=gyro,
            roll=roll,
            pitch=pitch,
            yaw=yaw,
            effectors={n: self.effector_pos(data, n) for n in self.effector_ids},
            contacts=contacts,
        )
