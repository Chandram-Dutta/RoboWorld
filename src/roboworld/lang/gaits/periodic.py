"""Periodic multi-leg gaits (trot, pace, bound, tripod) from foot trajectories + IK.

Each foot follows a phase-shifted cycle in the base frame: during stance it
slides backwards at the commanded body velocity, during swing it lifts and
returns forwards. No training needed; works open-loop for statically and
dynamically stable multi-legged robots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from roboworld.lang.gaits.base import GaitController, min_jerk
from roboworld.lang.ik import Frame

if TYPE_CHECKING:
    from roboworld.lang.interpreter import Ctx

# Phase offsets by foot name suffix/prefix. Unknown layouts fall back to alternating pairs.
PATTERNS = {
    "quadruped_trot": {"FL": 0.0, "RR": 0.0, "FR": 0.5, "RL": 0.5},
    "quadruped_pace": {"FL": 0.0, "RL": 0.0, "FR": 0.5, "RR": 0.5},
    "quadruped_bound": {"FL": 0.0, "FR": 0.0, "RL": 0.5, "RR": 0.5},
    "quadruped_walk": {"FL": 0.0, "RR": 0.25, "FR": 0.5, "RL": 0.75},
    "hexapod_tripod": {"L1": 0.0, "R2": 0.0, "L3": 0.0, "R1": 0.5, "L2": 0.5, "R3": 0.5},
}
PATTERN_KINDS = {"hexapod_tripod": ("hexapod",)}


class PeriodicGait(GaitController):
    kinds = ("quadruped", "hexapod")
    fallback = {
        "period": 0.4,
        "step_height": 0.06,
        "duty_factor": 0.6,
        "double_support": 0.0,
        "body_height": 0.0,
        "stabilizer": "imu_feedback",
        "params": {"ramp": 0.6, "tilt_gain": 0.8},
    }

    def __init__(self, ctx: Ctx, spec, name: str):
        self.name = name
        super().__init__(ctx, spec)
        pattern = PATTERNS.get(name, {})
        self.offsets = []
        for i, foot in enumerate(self.feet):
            key = next((k for k in pattern if foot.startswith(k) or foot.endswith(k)), None)
            self.offsets.append(pattern[key] if key else 0.5 * (i % 2))
        if name == "quadruped_walk":
            self.settings.duty_factor = max(self.settings.duty_factor, 0.75)

    def start(self, ctx: Ctx) -> None:
        self.t0 = ctx.t
        self.q_stance = self.stance_q(ctx)
        frames = ctx.kin.fk(self.q_stance, self.feet)
        # Raising the body by h means the feet sit h lower in the base frame.
        self.p0 = {f: frames[f].pos - np.array([0.0, 0.0, self.settings.body_height]) for f in self.feet}
        self.q_last = self.q_stance.copy()
        self.speed_scale = 0.0
        self.stop_t: float | None = None
        self.init_heading(ctx)

    def _foot(self, foot: str, phase: float, v: np.ndarray, wz: float, h: float) -> np.ndarray:
        s = self.settings
        p0 = self.p0[foot]
        stance_time = s.duty_factor * s.period
        # Foot velocity in the base frame during stance is -(v + w x p).
        d = (v + np.array([-wz * p0[1], wz * p0[0]])) * stance_time
        pos = p0.copy()
        if phase < s.duty_factor:
            u = phase / s.duty_factor
            pos[:2] += d * (0.5 - u)
        else:
            u = (phase - s.duty_factor) / (1 - s.duty_factor)
            pos[:2] += d * (-0.5 + min_jerk(u))
            pos[2] += h * np.sin(np.pi * u)
        return pos

    def tick(self, ctx: Ctx) -> None:
        s = self.settings
        t = ctx.t - self.t0
        ramp = s.params.get("ramp", 0.6)
        if self.stop_requested and self.stop_t is None:
            self.stop_t = t
        if self.stop_t is None:
            self.speed_scale = min(1.0, t / ramp) if ramp > 0 else 1.0
        else:
            self.speed_scale = max(0.0, self.speed_scale - ctx.dt / max(ramp * 0.5, 1e-3))
        scale = min_jerk(self.speed_scale)
        v = np.array([s.vx, s.vy]) * scale
        wz = s.wz * scale
        wz += self.heading_correction(ctx, wz) * (1.0 if self.stop_t is None else 0.0)
        h = s.step_height * min(1.0, t / 0.25)
        if self.stop_t is not None and self.speed_scale == 0.0:
            # Let the last swings land, then finish on a full-stance phase boundary.
            h *= max(0.0, 1.0 - (t - self.stop_t) / s.period)
            if t - self.stop_t > s.period:
                self.done = True
        phase_g = t / s.period
        # Attitude feedback: shorten the legs on the high side to level the body.
        gain = s.params.get("tilt_gain", 0.8) if s.stabilizer != "none" else 0.0
        correction = self.tilt_correction(ctx, -gain)
        targets = {}
        for foot, off in zip(self.feet, self.offsets, strict=True):
            pos = self._foot(foot, (phase_g + off) % 1.0, v, wz, h)
            targets[foot] = Frame(correction @ pos, np.eye(3))
        q, _ = ctx.kin.solve(self.q_last, targets, q_posture=self.q_stance, iters=6)
        self.q_last = q
        ctx.targets[self.claims] = q[self.claims]
