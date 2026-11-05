"""Per-run metrics: how far, how straight, how stable, how hard the servos worked."""

from __future__ import annotations

import numpy as np

from roboworld.lang.manifest import Manifest
from roboworld.sim.state import RobotState


class Metrics:
    def __init__(self, manifest: Manifest, force_limit: np.ndarray):
        self.m = manifest
        self.limit = np.where(np.isfinite(force_limit), force_limit, np.nan)
        self.start: RobotState | None = None
        self.last: RobotState | None = None
        self.path = 0.0
        self.energy = 0.0
        self.ticks = 0
        self.sat = 0
        self.peak_ratio = 0.0
        self.track_sq = 0.0
        self.tilt_sum = 0.0
        self.max_tilt = 0.0
        self.min_height = np.inf
        self.fell_at: float | None = None
        self.limit_hits = 0
        lo = np.array([j.range[0] for j in manifest.joints.values()])
        hi = np.array([j.range[1] for j in manifest.joints.values()])
        self.lo, self.hi = lo + 1e-3, hi - 1e-3

    def update(self, st: RobotState, targets: np.ndarray, dt: float) -> None:
        if self.start is None:
            self.start = st
            self.last = st
            self.smooth = st.base_pos[:2].copy()
        # Path length on a low-passed position, so gait sway doesn't inflate it.
        smooth = self.smooth + min(1.0, dt / 0.4) * (st.base_pos[:2] - self.smooth)
        self.path += float(np.linalg.norm(smooth - self.smooth))
        self.smooth = smooth
        self.energy += float(np.sum(np.abs(st.torque * st.qd))) * dt
        ratio = np.abs(st.torque) / self.limit
        if np.any(np.isfinite(ratio)):
            self.peak_ratio = max(self.peak_ratio, float(np.nanmax(ratio)))
            self.sat += int(np.nansum(ratio >= 0.95))
        self.track_sq += float(np.mean((targets - st.q) ** 2))
        tilt = float(np.degrees(np.arccos(np.clip(st.up_z, -1, 1))))
        self.tilt_sum += tilt
        self.max_tilt = max(self.max_tilt, tilt)
        self.min_height = min(self.min_height, float(st.base_pos[2]))
        self.limit_hits += int(np.sum((st.q <= self.lo) | (st.q >= self.hi)))
        self.ticks += 1
        self.last = st

    def mark_fall(self, t: float) -> None:
        if self.fell_at is None:
            self.fell_at = t

    def result(self) -> dict[str, float | bool | list[float] | None]:
        if self.start is None or self.last is None:
            return {}
        s, e = self.start, self.last
        disp = e.base_pos[:2] - s.base_pos[:2]
        heading = np.array([np.cos(s.yaw), np.sin(s.yaw)])
        forward = float(disp @ heading)
        lateral = float(disp @ np.array([-heading[1], heading[0]]))
        duration = e.t - s.t
        displacement = float(np.linalg.norm(disp))
        dyaw = float(np.degrees((e.yaw - s.yaw + np.pi) % (2 * np.pi) - np.pi))
        n_joint_ticks = max(self.ticks * len(self.m.joints), 1)
        cot = self.energy / (self.m.mass * 9.81 * displacement) if displacement > 0.05 else None
        r = lambda x, k=3: None if x is None else round(float(x), k)  # noqa: E731
        return {
            "duration_s": r(duration, 2),
            "fell": self.fell_at is not None,
            "fall_time_s": r(self.fell_at, 2),
            "forward_m": r(forward),
            "lateral_drift_m": r(lateral),
            "displacement_m": r(displacement),
            "distance_traveled_m": r(self.path),
            "avg_speed_mps": r(displacement / duration if duration > 0 else 0.0),
            "heading_change_deg": r(dyaw, 1),
            "final_position": [r(e.base_pos[0]), r(e.base_pos[1])],
            "max_tilt_deg": r(self.max_tilt, 1),
            "mean_tilt_deg": r(self.tilt_sum / max(self.ticks, 1), 1),
            "min_base_height_m": r(self.min_height),
            "peak_torque_ratio": r(self.peak_ratio, 2),
            "torque_saturation_pct": r(100 * self.sat / n_joint_ticks, 1),
            "energy_j": r(self.energy, 2),
            "cost_of_transport": r(cot, 2),
            "tracking_rmse_rad": r(np.sqrt(self.track_sq / max(self.ticks, 1))),
            "joint_limit_hits": self.limit_hits,
        }
