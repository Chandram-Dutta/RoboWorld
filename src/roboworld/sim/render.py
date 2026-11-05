"""Offscreen snapshots (works headless on macOS) for MCP image results and reports."""

from __future__ import annotations

import io
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image

from roboworld.lang.manifest import Manifest
from roboworld.sim.scene import FLOOR_NAME, subtree_bodies


def robot_extent(model: mujoco.MjModel, data: mujoco.MjData) -> tuple[np.ndarray, float]:
    """Centre and size of the robot's bounding box (excluding the floor)."""
    floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, FLOOR_NAME)
    pts = []
    for g in range(model.ngeom):
        if g == floor or model.geom_bodyid[g] == 0:
            continue
        c, h = model.geom_aabb[g, :3], model.geom_aabb[g, 3:]
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    pts.append(data.geom_xpos[g] + data.geom_xmat[g].reshape(3, 3) @ (c + h * [sx, sy, sz]))
    pts = np.array(pts)
    lo, hi = pts.min(0), pts.max(0)
    return (lo + hi) / 2, float(np.linalg.norm(hi - lo))


class Camera:
    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData, manifest: Manifest,
                 width: int = 640, height: int = 480):
        self.model = model
        self.renderer = mujoco.Renderer(model, height, width)
        self.cam = mujoco.MjvCamera()
        center, size = robot_extent(model, data)
        self.distance = max(size * 1.6, 0.4)
        base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, manifest.base_body)
        if manifest.floating_base:
            self.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            self.cam.trackbodyid = base
        else:
            self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
            self.cam.lookat[:] = center
        self.cam.distance = self.distance
        self.cam.azimuth = 135
        self.cam.elevation = -18
        self.bodies = subtree_bodies(model, base)

    def render(self, data: mujoco.MjData, azimuth: float | None = None, elevation: float | None = None) -> np.ndarray:
        if azimuth is not None:
            self.cam.azimuth = azimuth
        if elevation is not None:
            self.cam.elevation = elevation
        self.renderer.update_scene(data, self.cam)
        return self.renderer.render().copy()

    def close(self) -> None:
        self.renderer.close()


def save_png(img: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path)
    return path


def png_bytes(img: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(img: np.ndarray, quality: int = 70) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def contact_sheet(images: list[np.ndarray], labels: list[str] | None = None) -> np.ndarray:
    """Tile snapshots horizontally into one image (cheaper for an LLM to look at)."""
    from PIL import ImageDraw

    h = min(i.shape[0] for i in images)
    tiles = [Image.fromarray(i[:h]) for i in images]
    sheet = Image.new("RGB", (sum(t.width for t in tiles), h), "white")
    x = 0
    draw = ImageDraw.Draw(sheet)
    for k, tile in enumerate(tiles):
        sheet.paste(tile, (x, 0))
        if labels:
            draw.rectangle([x + 6, 6, x + 6 + 7 * len(labels[k]) + 8, 26], fill=(255, 255, 255))
            draw.text((x + 10, 10), labels[k], fill=(20, 20, 20))
        x += tile.width
    return np.asarray(sheet)
