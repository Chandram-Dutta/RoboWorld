"""Servo layer: turn joint position targets into actuator commands.

RoboLang always speaks in joint *position* targets (how hobby servos like the
STS3215 are driven). Position actuators get the target directly; torque motors
get a PD loop closed here on every physics step.
"""

from __future__ import annotations

import mujoco
import numpy as np

from roboworld.lang.manifest import Manifest


class ServoLayer:
    def __init__(self, model: mujoco.MjModel, manifest: Manifest):
        self.names = list(manifest.joints)
        n = len(self.names)
        self.act = np.zeros(n, dtype=int)
        self.qadr = np.zeros(n, dtype=int)
        self.vadr = np.zeros(n, dtype=int)
        self.is_pos = np.zeros(n, dtype=bool)
        self.kp = np.zeros(n)
        self.kd = np.zeros(n)
        self.lo = np.zeros(n)
        self.hi = np.zeros(n)
        self.force_limit = np.full(n, np.inf)
        for i, name in enumerate(self.names):
            j = manifest.joints[name]
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            self.act[i] = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, j.actuator)
            self.qadr[i] = model.jnt_qposadr[jid]
            self.vadr[i] = model.jnt_dofadr[jid]
            self.is_pos[i] = j.control == "position"
            self.kp[i] = j.kp or 0.0
            self.kd[i] = j.kd or 0.0
            self.lo[i], self.hi[i] = j.range
            if j.force_limit:
                self.force_limit[i] = j.force_limit
        self.ctrl_lo = model.actuator_ctrlrange[self.act, 0]
        self.ctrl_hi = model.actuator_ctrlrange[self.act, 1]
        self.ctrl_limited = model.actuator_ctrllimited[self.act].astype(bool)

    def q(self, data: mujoco.MjData) -> np.ndarray:
        return data.qpos[self.qadr].copy()

    def qd(self, data: mujoco.MjData) -> np.ndarray:
        return data.qvel[self.vadr].copy()

    def torque(self, data: mujoco.MjData) -> np.ndarray:
        return data.actuator_force[self.act].copy()

    def apply(self, data: mujoco.MjData, targets: np.ndarray) -> None:
        targets = np.clip(targets, self.lo, self.hi)
        ctrl = np.where(
            self.is_pos,
            targets,
            self.kp * (targets - data.qpos[self.qadr]) - self.kd * data.qvel[self.vadr],
        )
        ctrl = np.where(self.ctrl_limited, np.clip(ctrl, self.ctrl_lo, self.ctrl_hi), ctrl)
        data.ctrl[self.act] = ctrl
