"""What the robot can know about the world: a simulated object detector + memory.

The detector only reports objects that are inside the head camera's field of
view, within range and not hidden behind something (ray cast). Estimates carry
distance-proportional noise. Everything the brain learns about the world comes
through here, so it can't use positions of things it has never seen.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import mujoco
import numpy as np

from roboworld.lang.manifest import Manifest
from roboworld.sim.scene import CAMERA_NAME, OBJECT_PREFIX
from roboworld.sim.state import RobotState
from roboworld.world.spec import WorldObject, WorldSpec


@dataclass
class Detection:
    name: str
    kind: str
    color: str
    position: list[float]  # estimated world [x, y]
    size_m: float  # rough diameter
    t: float  # sim time when seen
    half_extent: list[float] | None = None  # [hx, hy] for areas and boxes
    segment: list[list[float]] | None = None  # walls: inner face [[x0, y0], [x1, y1]]
    flat: bool = False  # painted on the floor: you can walk onto it

    def nearest(self, xy: np.ndarray) -> np.ndarray:
        """Closest point of this object (its segment, for walls) to xy."""
        if self.segment is None:
            return np.asarray(self.position, dtype=float)
        a, b = (np.asarray(p, dtype=float) for p in self.segment)
        u = np.clip(float((xy - a) @ (b - a)) / max(float((b - a) @ (b - a)), 1e-9), 0.0, 1.0)
        return a + (b - a) * u

    def relative(self, st: RobotState) -> tuple[float, float]:
        """(distance m, bearing deg, + = to the robot's left) from the robot's current pose."""
        d = self.nearest(st.base_pos[:2]) - st.base_pos[:2]
        bearing = np.degrees((np.arctan2(d[1], d[0]) - st.yaw + np.pi) % (2 * np.pi) - np.pi)
        return float(np.linalg.norm(d)), float(bearing)

    def describe(self, st: RobotState, visible: bool) -> dict:
        dist, bearing = self.relative(st)
        out = asdict(self)
        out["position"] = [round(v, 2) for v in self.position]
        out["size_m"] = round(self.size_m, 2)
        out.pop("t")
        if self.half_extent is None:
            out.pop("half_extent")
        if not self.flat:
            out.pop("flat")
        if self.segment is None:
            out.pop("segment")
        else:
            out["segment"] = [[round(v, 2) for v in p] for p in self.segment]
        out.update(distance_m=round(dist, 2), bearing_deg=round(bearing), visible_now=visible,
                   last_seen_s_ago=round(st.t - self.t, 1))
        return out


class Perception:
    def __init__(self, model: mujoco.MjModel, world: WorldSpec | None, manifest: Manifest, seed: int = 0,
                 noise: float = 0.02):
        self.model = model
        self.world = world
        self.manifest = manifest
        self.rng = np.random.default_rng(seed)
        self.noise = noise
        self.cam = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, CAMERA_NAME)
        self.cam_body = int(model.cam_bodyid[self.cam]) if self.cam >= 0 else -1
        cam_cfg = manifest.camera
        self.max_range = cam_cfg.max_range if cam_cfg else 0.0
        if self.cam >= 0:
            fovy = np.radians(model.cam_fovy[self.cam])
            aspect = cam_cfg.width / cam_cfg.height
            self.half_v = fovy / 2
            self.half_h = np.arctan(np.tan(fovy / 2) * aspect)
        self.objects: dict[str, tuple[WorldObject, int]] = {}
        for obj in (world.objects if world else []):
            gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, OBJECT_PREFIX + obj.name)
            self.objects[obj.name] = (obj, gid)
        self.walls: dict[str, tuple[int, tuple]] = {}
        if world is not None and world.walls is not None:
            for name, seg in world.walls.segments().items():
                gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, OBJECT_PREFIX + name)
                self.walls[name] = (gid, seg)
            self.wall_height = world.walls.height
        self.memory: dict[str, Detection] = {}
        self.visible: set[str] = set()
        self._geomid = np.zeros(1, dtype=np.int32)
        self._groups = np.array([1, 1, 0, 0, 0, 0], dtype=np.uint8)  # world geoms only (robot is group 2/3)

    @property
    def has_camera(self) -> bool:
        return self.cam >= 0

    def true_position(self, data: mujoco.MjData, name: str) -> np.ndarray:
        return data.geom_xpos[self.objects[name][1]].copy()

    def _visible(self, data: mujoco.MjData, target: np.ndarray, gid: int) -> float | None:
        """Distance to target if it is in view and not hidden behind something, else None."""
        cam_pos = data.cam_xpos[self.cam]
        cam_rot = data.cam_xmat[self.cam].reshape(3, 3)
        v = target - cam_pos
        dist = float(np.linalg.norm(v))
        if dist > self.max_range or dist < 1e-6:
            return None
        c = cam_rot.T @ v
        forward = -c[2]
        if forward <= 0:
            return None
        if abs(np.arctan2(c[0], forward)) > self.half_h or abs(np.arctan2(c[1], forward)) > self.half_v:
            return None
        hit = mujoco.mj_ray(self.model, data, cam_pos, v / dist, self._groups, 1, -1, self._geomid)
        if hit < 0 or int(self._geomid[0]) != gid:
            return None
        return dist

    @staticmethod
    def _sample_points(data: mujoco.MjData, obj: WorldObject, gid: int) -> list[np.ndarray]:
        """Centre first, then points spread over the object (corners of areas, tops of solids)."""
        c = data.geom_xpos[gid].copy()
        pts = [c]
        if obj.shape in ("region", "box"):
            rot = data.geom_xmat[gid].reshape(3, 3)
            hx, hy = obj.size[0], obj.size[1]
            hz = obj.size[2] if obj.shape == "box" else 0.0
            for sx, sy in ((0.7, 0.7), (0.7, -0.7), (-0.7, 0.7), (-0.7, -0.7)):
                pts.append(c + rot @ np.array([sx * hx, sy * hy, 0.8 * hz]))
        else:
            pts.append(c + np.array([0.0, 0.0, 0.8 * obj.half_height]))
        return pts

    def detect(self, data: mujoco.MjData, t: float) -> list[Detection]:
        if not self.has_camera:
            return []
        seen = []
        for name, (gid, seg) in self.walls.items():
            a, b = np.asarray(seg[0]), np.asarray(seg[1])
            pts = [np.array([*(a + (b - a) * u), self.wall_height / 2]) for u in np.linspace(0.05, 0.95, 9)]
            if any(self._visible(data, p, gid) is not None for p in pts):
                seen.append(Detection(name=name, kind="wall", color="white", position=[float(v) for v in (a + b) / 2],
                                      size_m=float(np.linalg.norm(b - a)), t=t,
                                      segment=[[float(v) for v in a], [float(v) for v in b]]))
        for name, (obj, gid) in self.objects.items():
            target = data.geom_xpos[gid]
            dist = None
            for p in self._sample_points(data, obj, gid):  # partly hidden things are still seen
                dist = self._visible(data, p, gid)
                if dist is not None:
                    break
            if dist is None:
                continue
            est = target[:2] + self.rng.normal(0.0, self.noise * dist, 2)
            extent = [float(obj.size[0]), float(obj.size[1])] if obj.shape in ("region", "box") else None
            size = 2 * max(obj.size[:2]) if extent else 2 * obj.radius_xy
            seen.append(Detection(name=name, kind=obj.label, color=obj.color_name,
                                  position=[float(est[0]), float(est[1])], size_m=size, t=t, half_extent=extent,
                                  flat=obj.shape == "region"))
        return seen

    def update(self, data: mujoco.MjData, t: float) -> list[Detection]:
        seen = self.detect(data, t)
        self.visible = {d.name for d in seen}
        for d in seen:
            self.memory[d.name] = d
        return seen

    def resolve(self, query: str) -> Detection:
        """Find a remembered object by name or description ("red ball", "goal")."""
        q = query.strip().lower().replace("_", " ")
        if query in self.memory:
            return self.memory[query]
        tokens = q.split()
        matches = [d for d in self.memory.values()
                   if all(tok in f"{d.name.replace('_', ' ')} {d.kind} {d.color}".lower() for tok in tokens)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(sorted(m.name for m in matches))
            raise LookupError(f"'{query}' is ambiguous; I have seen: {names}. Use the exact name.")
        known = ", ".join(sorted(self.memory)) or "nothing yet"
        raise LookupError(f"I haven't seen anything matching '{query}'. Seen so far: {known}. "
                          "Try look_around or turn to search.")

    def known_objects(self, st: RobotState) -> list[dict]:
        return [d.describe(st, d.name in self.visible) for d in
                sorted(self.memory.values(), key=lambda d: d.relative(st)[0])]
