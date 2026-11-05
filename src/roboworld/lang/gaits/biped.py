"""Biped walking without training: footstep plan + LIPM/ZMP preview control + IK.

1. A footstep planner turns the velocity command into alternating footsteps.
2. The zero-moment point (ZMP) must stay inside the support foot, so we build a
   ZMP reference that sits on the stance foot and slides across during double
   support.
3. Kajita's preview controller on the linear inverted pendulum model (LIPM)
   produces a centre-of-mass trajectory that tracks that ZMP reference.
4. Swing feet follow smooth arcs; IK turns body + feet poses into joint targets.
5. A tilt correction (``tilt_gain``) keeps the feet level if the torso leans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.linalg import solve_discrete_are

from roboworld.lang.gaits.base import GaitController, min_jerk, rot_z
from roboworld.lang.ik import Frame

if TYPE_CHECKING:
    from roboworld.lang.interpreter import Ctx

G = 9.81


class LipmPreview:
    """Kajita preview controller for one horizontal axis (jerk input, ZMP output)."""

    def __init__(self, dt: float, zc: float, horizon: float = 1.6, q_e: float = 1.0, r: float = 1e-6):
        self.n = int(round(horizon / dt))
        a = np.array([[1, dt, dt * dt / 2], [0, 1, dt], [0, 0, 1]])
        b = np.array([[dt**3 / 6], [dt * dt / 2], [dt]])
        c = np.array([[1, 0, -zc / G]])
        at = np.block([[np.eye(1), c @ a], [np.zeros((3, 1)), a]])
        bt = np.vstack([c @ b, b])
        it = np.array([[1.0], [0], [0], [0]])
        ft = np.vstack([c @ a, a])
        q = np.diag([q_e, 0, 0, 0])
        p = solve_discrete_are(at, bt, q, np.array([[r]]))
        s = r + (bt.T @ p @ bt).item()
        self.gi = (bt.T @ p @ it).item() / s
        self.gx = (bt.T @ p @ ft / s).ravel()
        ac = at - bt @ (bt.T @ p @ at) / s
        x = -ac.T @ p @ it
        gd = [-self.gi]
        for _ in range(1, self.n):
            gd.append((bt.T @ x).item() / s)
            x = ac.T @ x
        self.gd = np.array(gd)
        self.a, self.b, self.c = a, b.ravel(), c.ravel()

    def step(self, x: np.ndarray, err: float, zmp_now: float, refs: np.ndarray) -> tuple[np.ndarray, float]:
        err += float(self.c @ x) - zmp_now
        u = -self.gi * err - float(self.gx @ x) - float(self.gd @ refs)
        return self.a @ x + self.b * u, err


@dataclass
class Phase:
    kind: str  # shift | step | final | hold
    t0: float
    t1: float
    ds: float  # seconds of double support at the start
    zmp_from: np.ndarray
    zmp_to: np.ndarray
    feet: dict[str, np.ndarray]  # foot poses (x, y, yaw) at phase start
    swing: str | None = None
    swing_to: np.ndarray | None = None
    closing: bool = False
    support: str | None = None
    extra: dict = field(default_factory=dict)

    def zmp(self, t: float) -> np.ndarray:
        if self.ds <= 0 or t >= self.t0 + self.ds:
            return self.zmp_to
        u = min_jerk((t - self.t0) / self.ds)
        return self.zmp_from + (self.zmp_to - self.zmp_from) * u

    def feet_after(self) -> dict[str, np.ndarray]:
        feet = {k: v.copy() for k, v in self.feet.items()}
        if self.swing and self.swing_to is not None:
            feet[self.swing] = self.swing_to.copy()
        return feet


class BipedWalk(GaitController):
    name = "biped_walk"
    kinds = ("biped",)
    fallback = {
        "period": 0.5,
        "step_height": 0.03,
        "duty_factor": 0.6,
        "double_support": 0.25,
        "body_height": 0.0,
        "stabilizer": "lipm_zmp",
        "params": {"tilt_gain": 0.5, "orientation_cost": 0.3, "foot_roll_cost": 0.0, "max_step": 0.08,
                   "zmp_offset_x": 0.0, "com_feedback": 0.0},
    }

    def start(self, ctx: Ctx) -> None:
        if len(self.feet) != 2:
            raise ValueError("biped_walk needs exactly two feet in the manifest")
        s = self.settings
        self.t0 = ctx.t
        self.dt = ctx.dt
        self.T = s.period / 2.0
        self.ds = s.double_support * self.T
        self.q_stance = self.stance_q(ctx)
        self.q_last = self.q_stance.copy()
        frames = ctx.kin.fk(self.q_stance, self.feet)
        com = ctx.kin.com(self.q_stance)
        self.com_offset = com  # CoM in base frame at stance
        self.left, self.right = self._sides(frames)
        self.foot_z = {f: frames[f].pos[2] - s.body_height for f in self.feet}
        self.foot_rot = {f: frames[f].rot for f in self.feet}
        zc = float(com[2] - np.mean([frames[f].pos[2] for f in self.feet]) + s.body_height)
        self.preview = LipmPreview(self.dt, zc)
        # Walk frame: origin at the initial CoM, x forward.
        feet = {f: np.array([frames[f].pos[0] - com[0], frames[f].pos[1] - com[1], 0.0]) for f in self.feet}
        self.width = abs(feet[self.left][1] - feet[self.right][1])
        self.x = np.zeros(3)
        self.y = np.zeros(3)
        self.ex = self.ey = 0.0
        self.stopping = False
        self.init_heading(ctx)
        self.wz_eff = s.wz
        first_support = self.right if (s.vy > 0 or s.wz > 0) else self.left
        mid = (feet[self.left][:2] + feet[self.right][:2]) / 2
        yaw0 = (feet[self.left][2] + feet[self.right][2]) / 2
        self.phases = [Phase("shift", 0.0, self.T * 1.5, self.T * 1.5, mid, self._zmp_point(feet[first_support]),
                             feet, support=first_support, extra={"center": np.array([mid[0], mid[1], yaw0])})]
        self.current = 0

    def _sides(self, frames: dict[str, Frame]) -> tuple[str, str]:
        a, b = self.feet
        return (a, b) if frames[a].pos[1] > frames[b].pos[1] else (b, a)

    def _zmp_point(self, foot_pose: np.ndarray) -> np.ndarray:
        off = self.settings.params.get("zmp_offset_x", 0.0)
        return foot_pose[:2] + rot_z(foot_pose[2])[:2, :2] @ np.array([off, 0.0])

    # ------------------------------------------------------------ planning
    def _landing(self, center: np.ndarray, swing: str, closing: bool) -> tuple[np.ndarray, np.ndarray]:
        """Advance the planned body centre by one step of the command, then place the swing
        foot beside it. Planning around the centre (not the support foot) keeps left and right
        turns symmetric and stops the body drifting while turning on the spot."""
        s = self.settings
        side = 1.0 if swing == self.left else -1.0
        if closing:
            new_center = center.copy()
        else:
            max_step = s.params.get("max_step", 0.08)
            dx = float(np.clip(s.vx * self.T, -max_step, max_step))
            dy = float(np.clip(s.vy * self.T, -max_step / 2, max_step / 2))
            dyaw = float(np.clip(self.wz_eff * self.T, -0.35, 0.35))
            xy = center[:2] + rot_z(center[2])[:2, :2] @ np.array([dx, dy])
            new_center = np.array([xy[0], xy[1], center[2] + dyaw])
        foot_xy = new_center[:2] + rot_z(new_center[2])[:2, :2] @ np.array([0.0, side * self.width / 2])
        return np.array([foot_xy[0], foot_xy[1], new_center[2]]), new_center

    def _extend(self, until: float) -> None:
        while self.phases[-1].t1 < until:
            prev = self.phases[-1]
            feet = prev.feet_after()
            t0 = prev.t1
            if prev.kind == "hold":
                prev.t1 = until + 1.0
                return
            center = prev.extra["center"]
            if prev.kind == "final":
                mid = prev.zmp_to
                self.phases.append(Phase("hold", t0, t0 + 0.6, 0.0, mid, mid, feet, extra={"center": center}))
                continue
            if self.stopping and (prev.kind == "shift" or prev.closing):
                mid = (feet[self.left][:2] + feet[self.right][:2]) / 2
                self.phases.append(Phase("final", t0, t0 + self.T * 1.5, self.T * 1.5,
                                         prev.zmp_to, mid, feet, extra={"center": center}))
                continue
            if prev.kind == "shift":
                support = prev.support
            else:
                support = prev.swing  # the foot that just landed
            swing = self.left if support == self.right else self.right
            closing = self.stopping
            landing, new_center = self._landing(center, swing, closing)
            zmp_from = prev.zmp_to
            zmp_to = self._zmp_point(feet[support])
            self.phases.append(Phase("step", t0, t0 + self.T, self.ds, zmp_from, zmp_to, feet,
                                     swing=swing, swing_to=landing, closing=closing, support=support,
                                     extra={"center": new_center}))

    def request_stop(self) -> None:
        if self.stopping:
            return
        self.stop_requested = True
        self.stopping = True
        # Re-plan everything after the phase in progress.
        self.phases = self.phases[: self.current + 1]

    def _phase_at(self, t: float) -> Phase:
        for ph in self.phases[self.current:]:
            if ph.t0 <= t < ph.t1:
                return ph
        return self.phases[-1]

    def _zmp_ref(self, t: float) -> np.ndarray:
        return self._phase_at(t).zmp(t)

    # ---------------------------------------------------------------- tick
    def _feet_now(self, ph: Phase, t: float) -> tuple[dict[str, np.ndarray], dict[str, float]]:
        feet = {k: v.copy() for k, v in ph.feet.items()}
        lift = {f: 0.0 for f in self.feet}
        if ph.kind == "step" and ph.swing and t >= ph.t0 + ph.ds:
            u = (t - ph.t0 - ph.ds) / max(ph.t1 - ph.t0 - ph.ds, 1e-6)
            a = min_jerk(u)
            start, end = ph.feet[ph.swing], ph.swing_to
            feet[ph.swing] = start + (end - start) * a
            h = self.settings.step_height * (0.3 if ph.closing else 1.0)
            lift[ph.swing] = h * 0.5 * (1 - np.cos(2 * np.pi * np.clip(u, 0, 1)))
        return feet, lift

    def tick(self, ctx: Ctx) -> None:
        s = self.settings
        t = ctx.t - self.t0
        n = self.preview.n
        if not self.stopping:
            # Heading hold: steer the footstep plan back toward the commanded heading.
            self.wz_eff = s.wz + self.heading_correction(ctx, s.wz)
        advanced = False
        while self.current < len(self.phases) - 1 and t >= self.phases[self.current].t1:
            self.current += 1
            advanced = True
        if advanced and not self.stopping:
            # Re-plan future footsteps with the latest command at every step boundary.
            self.phases = self.phases[: self.current + 1]
        self._extend(t + (n + 2) * self.dt)
        ph = self.phases[self.current]
        if ph.kind == "hold" and t >= ph.t0 + 0.5:
            self.done = True

        refs = np.array([self._zmp_ref(t + (j + 1) * self.dt) for j in range(n)])
        now = self._zmp_ref(t)
        self.x, self.ex = self.preview.step(self.x, self.ex, now[0], refs[:, 0])
        self.y, self.ey = self.preview.step(self.y, self.ey, now[1], refs[:, 1])

        feet, lift = self._feet_now(ph, t)
        yaw_b = float(np.mean([feet[f][2] for f in self.feet]))
        rz = rot_z(yaw_b)
        com_xy = np.array([self.x[0], self.y[0]])
        # Optional feedback (off by default): if the torso tips forward (pitch > 0),
        # move the body target back over the feet, and likewise sideways for roll.
        k = s.params.get("com_feedback", 0.0)
        if k:
            zc = -self.preview.c[2] * G  # pendulum height
            com_xy += rz[:2, :2] @ (k * zc * np.array([-ctx.state.pitch, ctx.state.roll]))
        base_xy = com_xy - rz[:2, :2] @ self.com_offset[:2]

        gain = s.params.get("tilt_gain", 0.5) if s.stabilizer != "none" else 0.0
        correction = self.tilt_correction(ctx, gain)
        targets = {}
        for f in self.feet:
            rel = rz[:2, :2].T @ (feet[f][:2] - base_xy)
            pos = np.array([rel[0], rel[1], self.foot_z[f] + lift[f]])
            rot = rot_z(feet[f][2] - yaw_b) @ self.foot_rot[f]
            targets[f] = Frame(correction @ pos, correction @ rot)
        # Feet without ankle roll can't stay flat while the hips shift sideways, so
        # by default only foot pitch/yaw are constrained and the foot may roll.
        c = s.params.get("orientation_cost", 0.3)
        cost = np.array([s.params.get("foot_roll_cost", 0.0), c, c])
        q, _ = ctx.kin.solve(self.q_last, targets, orientation_cost=cost, q_posture=self.q_stance, iters=8)
        self.q_last = q
        ctx.targets[self.claims] = q[self.claims]
        self.debug = {"zmp": now, "com": com_xy, "phase": ph.kind}
