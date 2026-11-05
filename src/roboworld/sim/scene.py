"""Assemble a simulation scene (robot + camera + ground + world objects) with MjSpec."""

from __future__ import annotations

import mujoco
import numpy as np

from roboworld.lang.manifest import Manifest
from roboworld.robots import load_manifest, load_robot_spec
from roboworld.world.spec import WALL_NAMES, WorldObject, WorldSpec

FLOOR_NAME = "rw_floor"
CAMERA_NAME = "robot_cam"
OBJECT_PREFIX = "w_"

# Collision bits. Robot body stand-ins (PROXY) touch world things but not the floor or each other.
WORLD_CONTYPE, WORLD_CONAFFINITY = 1 | 8, 1 | 4
PROXY_CONTYPE, PROXY_CONAFFINITY = 4, 8


def add_body_proxies(spec: mujoco.MjSpec) -> int:
    """Let visual meshes of bodies with no collision geometry (e.g. the duck's legs and trunk)
    collide with world objects, so robots can't walk through balls and boxes. Returns how many."""
    colliding_bodies = {id(g.parent) for g in spec.geoms if g.contype or g.conaffinity}
    count = 0
    for g in spec.geoms:
        body = g.parent
        if body is spec.worldbody or id(body) in colliding_bodies or g.contype or g.conaffinity:
            continue
        if g.group != 2 or g.type != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        g.contype, g.conaffinity = PROXY_CONTYPE, PROXY_CONAFFINITY
        count += 1
    return count


def _camera_frame(spec: mujoco.MjSpec, manifest: Manifest) -> tuple[str, np.ndarray, np.ndarray] | None:
    """Body, local position and local quaternion for the robot's camera."""
    cam = manifest.camera
    if cam is None:
        return None
    model = spec.compile()
    data = mujoco.MjData(model)
    pose = manifest.pose(manifest.default_pose)
    for j, v in pose.items():
        data.qpos[model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)]] = v
    mujoco.mj_kinematics(model, data)
    base_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, manifest.base_body)
    r_base = data.xmat[base_id].reshape(3, 3)
    if cam.site:
        sid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, cam.site)
        body_id = int(model.site_bodyid[sid])
        anchor = data.site_xpos[sid]
    else:
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, cam.body)
        anchor = data.xpos[body_id]
    r_body = data.xmat[body_id].reshape(3, 3)
    # cam.pos is an offset in the base frame (at the default pose), e.g. "10 cm forward".
    world_pos = anchor + r_base @ np.asarray(cam.pos, dtype=float)
    local_pos = r_body.T @ (world_pos - data.xpos[body_id])
    f = r_base @ (np.asarray(cam.look, dtype=float) / np.linalg.norm(cam.look))
    right = np.cross(f, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, f)
    r_cam = np.column_stack([right, up, -f])  # MuJoCo cameras look along -z with +y up
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, (r_body.T @ r_cam).flatten())
    name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id)
    return name, local_pos, quat


def _add_object(spec: mujoco.MjSpec, obj: WorldObject) -> None:
    rgba = list(obj.rgba)
    x, y = obj.pos[:2]
    z = obj.pos[2] if len(obj.pos) == 3 else obj.half_height + 0.001
    quat = [np.cos(np.radians(obj.yaw) / 2), 0, 0, np.sin(np.radians(obj.yaw) / 2)]
    gtype = {"sphere": mujoco.mjtGeom.mjGEOM_SPHERE, "box": mujoco.mjtGeom.mjGEOM_BOX,
             "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER, "region": mujoco.mjtGeom.mjGEOM_BOX}[obj.shape]
    size = list(obj.size) + [0.0] * (3 - len(obj.size))
    name = OBJECT_PREFIX + obj.name
    if obj.shape == "region":
        spec.worldbody.add_geom(name=name, type=gtype, size=[obj.size[0], obj.size[1], 0.0005],
                                pos=[x, y, 0.0006], quat=quat, rgba=rgba, contype=0, conaffinity=0, group=0)
        return
    kwargs: dict = {"name": name, "type": gtype, "size": size, "rgba": rgba, "group": 0,
                    "contype": WORLD_CONTYPE, "conaffinity": WORLD_CONAFFINITY}
    if obj.shape == "sphere":
        # Rolling resistance (like a ball on carpet) so a nudged ball doesn't roll away.
        kwargs.update(condim=6, friction=[obj.friction or 0.8, 0.02, 0.015])
    else:
        kwargs.update(condim=3, friction=[obj.friction or 0.8, 0.02, 0.01])
    if obj.movable:
        body = spec.worldbody.add_body(name=name, pos=[x, y, z], quat=quat)
        body.add_freejoint(name=name + "_free")
        body.add_geom(mass=obj.mass, **kwargs)
    else:
        spec.worldbody.add_geom(pos=[x, y, z], quat=quat, **kwargs)


def _add_walls(spec: mujoco.MjSpec, world: WorldSpec) -> None:
    w = world.walls
    if w is None:
        return
    hx, hy = w.half_size
    t, h = w.thickness / 2, w.height / 2
    rgba = list(WorldObject(name="_", shape="box", size=[1, 1, 1], pos=[0, 0], color=w.color).rgba)
    for name, (pos, size) in zip(WALL_NAMES, [
        ([hx + t, 0, h], [t, hy + 2 * t, h]), ([-hx - t, 0, h], [t, hy + 2 * t, h]),
        ([0, hy + t, h], [hx, t, h]), ([0, -hy - t, h], [hx, t, h]),
    ], strict=True):
        spec.worldbody.add_geom(name=OBJECT_PREFIX + name, type=mujoco.mjtGeom.mjGEOM_BOX, pos=pos, size=size,
                                rgba=rgba, group=0, contype=WORLD_CONTYPE, conaffinity=WORLD_CONAFFINITY)


def _add_bumps(spec: mujoco.MjSpec, world: WorldSpec) -> None:
    rng = np.random.default_rng((world.seed or 0) + 7919)
    for i, patch in enumerate(world.bumps):
        (x0, x1), (y0, y1) = patch.area
        rgba = list(WorldObject(name="_", shape="box", size=[1, 1, 1], pos=[0, 0], color=patch.color).rgba)
        for k in range(patch.count):
            hz = rng.uniform(*patch.height) / 2
            hx, hy = rng.uniform(*patch.size, 2) / 2
            yaw = rng.uniform(0, np.pi)
            spec.worldbody.add_geom(
                name=f"{OBJECT_PREFIX}bump{i}_{k}", type=mujoco.mjtGeom.mjGEOM_BOX, size=[hx, hy, hz],
                pos=[rng.uniform(x0, x1), rng.uniform(y0, y1), hz], quat=[np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)],
                rgba=rgba, group=1, condim=3, friction=[0.9, 0.02, 0.01])


def build_scene(robot: str, world: WorldSpec | None = None) -> mujoco.MjModel:
    spec = load_robot_spec(robot)
    manifest = load_manifest(robot)
    if world is not None:
        add_body_proxies(spec)
    mount = _camera_frame(spec, manifest)
    if mount is not None:
        body, pos, quat = mount
        spec.body(body).add_camera(name=CAMERA_NAME, pos=list(pos), quat=list(quat), fovy=manifest.camera.fovy)
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
    if world is not None:
        _add_walls(spec, world)
        _add_bumps(spec, world)
        for obj in world.objects:
            _add_object(spec, obj)
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


def place_on_ground(model: mujoco.MjModel, data: mujoco.MjData, manifest: Manifest, clearance: float = 0.002,
                    xy: tuple[float, float] = (0.0, 0.0), yaw: float = 0.0) -> None:
    """Put a floating-base robot at (x, y, yaw) with its lowest point resting on the floor."""
    if not manifest.floating_base:
        mujoco.mj_forward(model, data)
        return
    base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, manifest.base_body)
    free = int(model.body_jntadr[base])
    adr = int(model.jnt_qposadr[free])
    data.qpos[adr : adr + 2] = xy
    data.qpos[adr + 3 : adr + 7] = [np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)]
    mujoco.mj_forward(model, data)
    z = lowest_point(model, data, subtree_bodies(model, base))
    data.qpos[adr + 2] += clearance - z
    mujoco.mj_forward(model, data)
