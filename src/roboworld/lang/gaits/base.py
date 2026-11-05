"""Shared machinery for gait controllers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from roboworld.lang import schema

if TYPE_CHECKING:
    from roboworld.lang.interpreter import Ctx


def rot_x(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def min_jerk(s: float) -> float:
    s = float(np.clip(s, 0.0, 1.0))
    return s * s * s * (10 - 15 * s + 6 * s * s)


@dataclass
class GaitSettings:
    """Gait parameters after merging program values over robot defaults."""

    vx: float
    vy: float
    wz: float
    period: float
    step_height: float
    duty_factor: float
    double_support: float
    body_height: float
    stabilizer: str
    params: dict[str, float] = field(default_factory=dict)

    @classmethod
    def merge(cls, spec: schema.Gait, defaults: dict[str, Any], fallback: dict[str, Any]) -> GaitSettings:
        def pick(name: str) -> Any:
            value = getattr(spec, name)
            if value is not None:
                return value
            return defaults.get(name, fallback[name])

        params = dict(fallback.get("params", {}))
        params.update(defaults.get("params", {}))
        params.update(spec.params)
        return cls(
            vx=spec.velocity.vx,
            vy=spec.velocity.vy,
            wz=spec.velocity.wz,
            period=pick("period"),
            step_height=pick("step_height"),
            duty_factor=pick("duty_factor"),
            double_support=pick("double_support"),
            body_height=pick("body_height"),
            stabilizer=pick("stabilizer"),
            params=params,
        )


class GaitController:
    """Base class. Subclasses fill ``self.claims`` (joint indices) and implement ``tick``."""

    name = "gait"
    kinds: tuple[str, ...] = ()
    fallback: dict[str, Any] = {}

    def __init__(self, ctx: Ctx, spec: schema.Gait):
        m = ctx.manifest
        self.settings = GaitSettings.merge(spec, m.gaits.get(spec.type, {}), self.fallback)
        self.feet = list(m.feet)
        limbs = [m.end_effectors[f].limb for f in self.feet]
        joints = [j for limb in limbs if limb for j in m.limbs[limb]]
        self.claims = [ctx.index[j] for j in joints]
        self.stop_requested = False
        self.done = False

    def start(self, ctx: Ctx) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def tick(self, ctx: Ctx) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def request_stop(self) -> None:
        self.stop_requested = True

    def init_heading(self, ctx: Ctx) -> None:
        self.yaw_ref = ctx.state.yaw if ctx.state is not None else 0.0

    def heading_correction(self, ctx: Ctx, wz_cmd: float) -> float:
        """Integrate the commanded turn rate and return a yaw-rate correction toward it."""
        self.yaw_ref += wz_cmd * ctx.dt
        gain = self.settings.params.get("heading_gain", 1.0)
        if gain <= 0 or ctx.state is None:
            return 0.0
        err = (self.yaw_ref - ctx.state.yaw + np.pi) % (2 * np.pi) - np.pi
        limit = self.settings.params.get("heading_max_rate", 0.3)
        return float(np.clip(gain * err, -limit, limit))

    # ------------------------------------------------------------ helpers
    def stance_q(self, ctx: Ctx) -> np.ndarray:
        """Joint vector of the robot's stance pose (gait param ``stance_pose`` or default pose)."""
        m = ctx.manifest
        pose = m.gaits.get(self.name, {}).get("stance_pose", m.default_pose)
        q = ctx.targets.copy()
        for j, v in m.pose(pose).items():
            q[ctx.index[j]] = v
        return q

    def tilt_correction(self, ctx: Ctx, gain: float) -> np.ndarray:
        """Rotation applied to base-frame foot targets to react to torso tilt.

        ``gain = 1`` maps level-frame targets into the tilted base frame: the legs
        stay vertical in the world, which is what a biped wants (feet under the
        hips). Negative gains do the opposite, shortening the legs on the high
        side, which is how a quadruped levels its body.
        """
        if gain == 0:
            return np.eye(3)
        st = ctx.state
        tilt = rot_y(gain * st.pitch) @ rot_x(gain * st.roll)
        return tilt.T
