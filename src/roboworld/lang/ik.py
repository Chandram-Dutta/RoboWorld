"""Kinematics in the robot's base frame (mink-based IK + forward kinematics).

We compile a copy of the robot with its floating base removed, so the base
body is fixed and "base frame" positions are well defined. Gaits and ``reach``
steps express end-effector targets in that frame; IK turns them into joint
position targets for the servo layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import mink
import mujoco
import numpy as np

from roboworld.lang.manifest import Manifest
from roboworld.robots import load_robot_spec


@dataclass
class Frame:
    pos: np.ndarray  # base frame
    rot: np.ndarray  # 3x3, base frame


class Kinematics:
    def __init__(self, robot: str, manifest: Manifest):
        spec = load_robot_spec(robot)
        for joint in list(spec.joints):
            if joint.type == mujoco.mjtJoint.mjJNT_FREE:
                spec.delete(joint)
        for key in list(spec.keys):  # keyframes include the free joint's 7 qpos
            spec.delete(key)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        self.manifest = manifest
        self.names = list(manifest.joints)
        self.qadr = np.array([
            self.model.jnt_qposadr[mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, n)]
            for n in self.names
        ])
        self.base = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, manifest.base_body)
        mujoco.mj_forward(self.model, self.data)
        self.base_pos = self.data.xpos[self.base].copy()
        self.base_rot = self.data.xmat[self.base].reshape(3, 3).copy()
        self.configuration = mink.Configuration(self.model)
        self.limits = [mink.ConfigurationLimit(self.model)]
        self.posture = mink.PostureTask(self.model, cost=1e-3)
        self._tasks: dict[str, mink.FrameTask] = {}

    # ------------------------------------------------------------- helpers
    def to_base(self, pos_w: np.ndarray, rot_w: np.ndarray | None = None) -> Frame:
        pos = self.base_rot.T @ (pos_w - self.base_pos)
        rot = self.base_rot.T @ rot_w if rot_w is not None else np.eye(3)
        return Frame(pos, rot)

    def to_world(self, frame: Frame) -> tuple[np.ndarray, np.ndarray]:
        return self.base_pos + self.base_rot @ frame.pos, self.base_rot @ frame.rot

    def _full_q(self, q: np.ndarray) -> np.ndarray:
        full = self.model.qpos0.copy()
        full[self.qadr] = q
        return full

    def _frame_world(self, data: mujoco.MjData, effector: str) -> tuple[np.ndarray, np.ndarray]:
        kind, name = self.manifest.end_effectors[effector].frame
        obj = {"site": mujoco.mjtObj.mjOBJ_SITE, "geom": mujoco.mjtObj.mjOBJ_GEOM,
               "body": mujoco.mjtObj.mjOBJ_BODY}[kind]
        idx = mujoco.mj_name2id(self.model, obj, name)
        if kind == "site":
            return data.site_xpos[idx].copy(), data.site_xmat[idx].reshape(3, 3).copy()
        if kind == "geom":
            return data.geom_xpos[idx].copy(), data.geom_xmat[idx].reshape(3, 3).copy()
        return data.xpos[idx].copy(), data.xmat[idx].reshape(3, 3).copy()

    # ----------------------------------------------------------------- API
    def fk(self, q: np.ndarray, effectors: list[str] | None = None) -> dict[str, Frame]:
        self.data.qpos[:] = self._full_q(q)
        mujoco.mj_kinematics(self.model, self.data)
        names = effectors if effectors is not None else list(self.manifest.end_effectors)
        return {e: self.to_base(*self._frame_world(self.data, e)) for e in names}

    def com(self, q: np.ndarray) -> np.ndarray:
        """Whole-body centre of mass in the base frame."""
        self.data.qpos[:] = self._full_q(q)
        mujoco.mj_kinematics(self.model, self.data)
        mujoco.mj_comPos(self.model, self.data)
        return self.to_base(self.data.subtree_com[self.base].copy()).pos

    def front_reach(self) -> float:
        """How far the robot's collision geometry extends in front of the base (default pose), metres."""
        return self._extent()[1]

    def back_reach(self) -> float:
        """How far the body extends behind the base (bumper height, default pose), metres."""
        return max(0.0, -self._extent()[0])

    def half_width(self) -> float:
        """Half the robot's width (collision geometry, default pose), metres."""
        ymin, ymax = self._extent()[2:]
        return max(abs(ymin), abs(ymax))

    def _extent(self) -> tuple[float, float, float, float]:
        """(xmin, xmax, ymin, ymax) of the robot's body below 'bumper height' (0.25 m above its
        lowest point) in the base frame at the default pose: what bumps into things on the floor."""
        if not hasattr(self, "_ext"):
            q = np.array([self.manifest.poses[self.manifest.default_pose].get(j, 0.0) for j in self.names])
            self.data.qpos[:] = self._full_q(q)
            mujoco.mj_kinematics(self.model, self.data)
            pts = []
            for g in range(self.model.ngeom):
                solid = self.model.geom_contype[g] or self.model.geom_conaffinity[g]
                if not solid and self.model.geom_group[g] != 2:
                    continue
                c, h = self.model.geom_aabb[g, :3], self.model.geom_aabb[g, 3:]
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        for sz in (-1, 1):
                            pw = self.data.geom_xpos[g] + self.data.geom_xmat[g].reshape(3, 3) @ (c + h * [sx, sy, sz])
                            pts.append(self.to_base(pw).pos)
            p3 = np.array(pts) if pts else np.zeros((1, 3))
            low = p3[:, 2] < p3[:, 2].min() + 0.25
            a = p3[low][:, :2] if low.any() else p3[:, :2]
            self._ext = (float(a[:, 0].min()), float(max(a[:, 0].max(), 0.0)), float(a[:, 1].min()),
                         float(a[:, 1].max()))
        return self._ext

    def _task(self, effector: str) -> mink.FrameTask:
        if effector not in self._tasks:
            kind, name = self.manifest.end_effectors[effector].frame
            self._tasks[effector] = mink.FrameTask(name, kind, position_cost=1.0, orientation_cost=0.0)
        return self._tasks[effector]

    def solve(
        self,
        q_init: np.ndarray,
        targets: dict[str, Frame],
        orientation_cost: float | np.ndarray = 0.0,
        q_posture: np.ndarray | None = None,
        iters: int = 12,
        tol: float = 1e-4,
    ) -> tuple[np.ndarray, float]:
        """Joint targets that put each effector at its base-frame target. Returns (q, max_error_m)."""
        cfg = self.configuration
        cfg.update(self._full_q(q_init))
        self.posture.set_target(self._full_q(q_posture if q_posture is not None else q_init))
        tasks: list = [self.posture]
        for effector, frame in targets.items():
            task = self._task(effector)
            task.set_orientation_cost(orientation_cost)
            pos_w, rot_w = self.to_world(frame)
            task.set_target(mink.SE3.from_rotation_and_translation(mink.SO3.from_matrix(rot_w), pos_w))
            tasks.append(task)
        err = np.inf
        for _ in range(iters):
            vel = mink.solve_ik(cfg, tasks, 0.1, "daqp", damping=1e-4, limits=self.limits)
            cfg.integrate_inplace(vel, 0.1)
            err = max(
                (float(np.linalg.norm(self._task(e).compute_error(cfg)[:3])) for e in targets), default=0.0
            )
            if err < tol:
                break
        return cfg.q[self.qadr].copy(), err
