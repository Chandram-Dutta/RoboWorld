"""Assemble a simulation scene (robot + ground + lights) with MjSpec."""

from __future__ import annotations

import mujoco
import numpy as np

from roboworld.lang.manifest import Manifest
from roboworld.robots import load_robot_spec

FLOOR_NAME = "rw_floor"


def build_scene(robot: str) -> mujoco.MjModel:
    spec = load_robot_spec(robot)
    spec.visual.headlight.ambient = [0.35, 0.35, 0.35]
    spec.visual.headlight.diffuse = [0.6, 0.6, 0.6]
    spec.visual.headlight.specular = [0.0, 0.0, 0.0]
    spec.visual.global_.offwidth = 1280
    spec.visual.global_.offheight = 960

    spec.add_texture(
        name="rw_sky",
        type=mujoco.mjtTexture.mjTEXTURE_SKYBOX,
        builtin=mujoco.mjtBuiltin.mjBUILTIN_GRADIENT,
        rgb1=[0.55, 0.7, 0.85],
        rgb2=[0.95, 0.97, 1.0],
        width=512,
        height=512,
    )
    spec.add_texture(
        name="rw_grid",
        type=mujoco.mjtTexture.mjTEXTURE_2D,
        builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER,
        rgb1=[0.82, 0.84, 0.86],
        rgb2=[0.74, 0.76, 0.79],
        mark=mujoco.mjtMark.mjMARK_EDGE,
        markrgb=[0.6, 0.62, 0.65],
        width=300,
        height=300,
    )
    mat = spec.add_material(name="rw_floor_mat", texrepeat=[4, 4], texuniform=True, reflectance=0.05)
    mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "rw_grid"

    spec.worldbody.add_geom(
        name=FLOOR_NAME,
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[0, 0, 0.05],
        material="rw_floor_mat",
        condim=3,
        friction=[0.8, 0.02, 0.01],
    )
    spec.worldbody.add_light(
        name="rw_sun", pos=[0, 0, 4], dir=[0.3, 0.2, -1], type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL,
        diffuse=[0.6, 0.6, 0.6], specular=[0.1, 0.1, 0.1], castshadow=1,
    )
    return spec.compile()


def set_joint_positions(model: mujoco.MjModel, data: mujoco.MjData, manifest: Manifest, q: dict[str, float]) -> None:
    for name, value in q.items():
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        data.qpos[model.jnt_qposadr[jid]] = value


def lowest_point(model: mujoco.MjModel, data: mujoco.MjData, body_ids: set[int]) -> float:
    """Lowest world z over the collision geoms of the given bodies (oriented AABBs)."""
    z_min = np.inf
    for g in range(model.ngeom):
        if model.geom_bodyid[g] not in body_ids:
            continue
        if model.geom_contype[g] == 0 and model.geom_conaffinity[g] == 0:
            continue
        center, half = model.geom_aabb[g, :3], model.geom_aabb[g, 3:]
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * half + center
        world = data.geom_xpos[g] + corners @ data.geom_xmat[g].reshape(3, 3).T
        z_min = min(z_min, float(world[:, 2].min()))
    return z_min


def subtree_bodies(model: mujoco.MjModel, root: int) -> set[int]:
    ids = {root}
    for b in range(model.nbody):
        p = b
        while p > 0:
            if p == root:
                ids.add(b)
                break
            p = int(model.body_parentid[p])
    return ids


def place_on_ground(model: mujoco.MjModel, data: mujoco.MjData, manifest: Manifest, clearance: float = 0.002) -> None:
    """Shift a floating-base robot vertically so its lowest point rests on the floor."""
    if not manifest.floating_base:
        mujoco.mj_forward(model, data)
        return
    base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, manifest.base_body)
    free = int(model.body_jntadr[base])
    adr = int(model.jnt_qposadr[free])
    mujoco.mj_forward(model, data)
    z = lowest_point(model, data, subtree_bodies(model, base))
    data.qpos[adr + 2] += clearance - z
    mujoco.mj_forward(model, data)
