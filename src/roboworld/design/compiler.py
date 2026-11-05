"""Compile a RoboSpec into a MuJoCo model (built with MjSpec) and a RoboWorld manifest.

Conventions so every designed robot plugs straight into gaits, skills and tasks:
- base body ``base`` with a free joint and an ``imu`` site
- joints ``<leg>_<part>``; each leg is a limb; feet are sites ``<leg>_foot``
- head joints ``neck_pitch`` / ``head_yaw`` (aliases ``head.pitch`` / ``head.yaw``), camera at site ``head_cam``
- every joint has a position servo from the catalog (kp, torque limit, damping...)
- robot geoms collide with the floor and world objects but not with each other
"""

from __future__ import annotations

import math
from typing import Any

import mujoco
import numpy as np

from roboworld.design.spec import LegSpec, RoboSpec, servo_catalog
from roboworld.world.spec import COLORS

ROBOT_CONTYPE, ROBOT_CONAFFINITY = 2, 1  # touches floor + world objects, never itself
GAIT_FOR = {"biped": "biped_walk", "quadruped": "quadruped_trot", "hexapod": "hexapod_tripod"}


def _rgba(color: str) -> list[float]:
    return list(COLORS.get(color, COLORS["gray"]))


def _geom(body: Any, **kw: Any) -> Any:
    g = body.add_geom(**kw)
    g.contype, g.conaffinity = ROBOT_CONTYPE, ROBOT_CONAFFINITY
    return g


def leg_angles(leg: LegSpec, stance: float | None = None) -> tuple[float, float]:
    """(hip pitch, knee) that put the foot straight below the hip at ``stance`` x leg length."""
    l1, l2 = leg.thigh, leg.shin
    h = (stance or leg.stance) * (l1 + l2)
    knee_inner = math.acos(np.clip((l1 * l1 + l2 * l2 - h * h) / (2 * l1 * l2), -1, 1))
    beta = math.pi - knee_inner  # how much the knee is bent
    a = math.acos(np.clip((l1 * l1 + h * h - l2 * l2) / (2 * l1 * h), -1, 1))  # thigh angle from vertical
    if leg.knee == "forward":
        return -a, beta  # thigh swings forward, shin back: knee points forward
    return a, -beta  # thigh back, shin forward: knee points backward


class _Builder:
    def __init__(self, spec: RoboSpec):
        self.spec = spec
        self.s = mujoco.MjSpec()
        self.s.modelname = spec.name
        self.s.compiler.degree = False
        self.s.option.timestep = 0.002
        self.s.option.iterations = 20
        self.s.option.ls_iterations = 10
        self.joints: list[str] = []
        self.limbs: dict[str, list[str]] = {}
        self.effectors: dict[str, dict[str, str]] = {}
        self.feet: list[str] = []
        self.home: dict[str, float] = {}
        self.crouch: dict[str, float] = {}

    def joint(self, body: Any, name: str, axis: list[float], rng: tuple[float, float], servo: str,
              limb: str) -> None:
        sv = servo_catalog()[servo]
        j = body.add_joint(name=name, type=mujoco.mjtJoint.mjJNT_HINGE, axis=axis, range=list(rng))
        j.limited = mujoco.mjtLimited.mjLIMITED_TRUE
        j.damping = [sv["damping"], 0.0, 0.0]  # MuJoCo 3.17: damping is a 3-vector (first entry = linear)
        j.armature, j.frictionloss = sv["armature"], sv["frictionloss"]
        act = self.s.add_actuator(name=name, target=name, trntype=mujoco.mjtTrn.mjTRN_JOINT)
        act.set_to_position(kp=sv["kp"])
        act.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
        act.forcerange = [-sv["torque_nm"], sv["torque_nm"]]
        act.ctrllimited = mujoco.mjtLimited.mjLIMITED_TRUE
        act.ctrlrange = list(rng)
        self.joints.append(name)
        self.limbs.setdefault(limb, []).append(name)

    def build(self) -> mujoco.MjSpec:
        spec = self.spec
        bx, by, bz = spec.body.size
        base = self.s.worldbody.add_body(name="base", pos=[0, 0, 0.6])
        base.add_freejoint(name="root")
        _geom(base, name="torso", type=mujoco.mjtGeom.mjGEOM_BOX, size=[bx / 2, by / 2, bz / 2],
              mass=spec.body.mass, rgba=_rgba(spec.body.color))
        base.add_site(name="imu", pos=[0, 0, 0])
        for leg in spec.legs:
            (self.biped_leg if leg.dof.startswith("biped") else self.quad_leg)(base, leg)
        if spec.head is not None:
            self.head(base)
        return self.s

    def biped_leg(self, base: Any, leg: LegSpec) -> None:
        n, seg, col = leg.name, leg.segment_mass, _rgba(leg.color)
        sph = mujoco.mjtGeom.mjGEOM_SPHERE
        cap = mujoco.mjtGeom.mjGEOM_CAPSULE
        yaw = base.add_body(name=f"{n}_hip_yaw", pos=list(leg.mount))
        self.joint(yaw, f"{n}_hip_yaw", [0, 0, 1], (-0.5, 0.5), leg.servo, n)
        _geom(yaw, type=sph, size=[0.018, 0, 0], mass=seg * 0.5, rgba=col)
        roll = yaw.add_body(name=f"{n}_hip_roll")
        self.joint(roll, f"{n}_hip_roll", [1, 0, 0], (-0.45, 0.45), leg.servo, n)
        _geom(roll, type=sph, size=[0.016, 0, 0], mass=seg * 0.3, rgba=col)
        thigh = roll.add_body(name=f"{n}_thigh")
        fwd = leg.knee == "forward"
        self.joint(thigh, f"{n}_hip_pitch", [0, 1, 0], (-1.7, 1.0) if fwd else (-1.0, 1.7), leg.servo, n)
        _geom(thigh, type=cap, fromto=[0, 0, 0, 0, 0, -leg.thigh], size=[0.015, 0, 0], mass=seg, rgba=col)
        shin = thigh.add_body(name=f"{n}_shin", pos=[0, 0, -leg.thigh])
        self.joint(shin, f"{n}_knee", [0, 1, 0], (-0.05, 2.6) if fwd else (-2.6, 0.05), leg.servo, n)
        _geom(shin, type=cap, fromto=[0, 0, 0, 0, 0, -leg.shin], size=[0.013, 0, 0], mass=seg, rgba=col)
        ankle = shin.add_body(name=f"{n}_ankle", pos=[0, 0, -leg.shin])
        self.joint(ankle, f"{n}_ankle", [0, 1, 0], (-1.6, 1.6), leg.servo, n)
        _geom(ankle, type=sph, size=[0.014, 0, 0], mass=seg * 0.4, rgba=col)
        foot_body = ankle
        if leg.dof == "biped6":
            foot_body = ankle.add_body(name=f"{n}_ankle_roll")
            self.joint(foot_body, f"{n}_ankle_roll", [1, 0, 0], (-0.5, 0.5), leg.servo, n)
            _geom(foot_body, type=sph, size=[0.012, 0, 0], mass=seg * 0.3, rgba=col)
        fl, fw = leg.foot
        sole = -0.026
        _geom(foot_body, name=f"{n}_sole", type=mujoco.mjtGeom.mjGEOM_BOX, size=[fl / 2, fw / 2, 0.006],
              pos=[fl * 0.15, 0, sole + 0.006], mass=0.03, rgba=_rgba("orange"), condim=3,
              friction=[1.0, 0.02, 0.01])
        foot_body.add_site(name=f"{n}_foot", pos=[fl * 0.15, 0, sole])
        self.effectors[f"{n}_foot"] = {"site": f"{n}_foot", "limb": n}
        self.feet.append(f"{n}_foot")
        for pose, stance in ((self.home, None), (self.crouch, leg.stance * 0.82)):
            hip, knee = leg_angles(leg, stance)
            pose.update({f"{n}_hip_yaw": 0.0, f"{n}_hip_roll": 0.0, f"{n}_hip_pitch": hip, f"{n}_knee": knee,
                         f"{n}_ankle": -(hip + knee)})
            if leg.dof == "biped6":
                pose[f"{n}_ankle_roll"] = 0.0

    def quad_leg(self, base: Any, leg: LegSpec) -> None:
        n, seg, col = leg.name, leg.segment_mass, _rgba(leg.color)
        cap = mujoco.mjtGeom.mjGEOM_CAPSULE
        abd = base.add_body(name=f"{n}_abduct", pos=list(leg.mount))
        self.joint(abd, f"{n}_abduct", [1, 0, 0], (-0.7, 0.7), leg.servo, n)
        _geom(abd, type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.02, 0, 0], mass=seg, rgba=col)
        thigh = abd.add_body(name=f"{n}_thigh")
        fwd = leg.knee == "forward"
        self.joint(thigh, f"{n}_hip", [0, 1, 0], (-2.0, 1.2) if fwd else (-1.2, 2.0), leg.servo, n)
        _geom(thigh, type=cap, fromto=[0, 0, 0, 0, 0, -leg.thigh], size=[0.014, 0, 0], mass=seg, rgba=col)
        shin = thigh.add_body(name=f"{n}_shin", pos=[0, 0, -leg.thigh])
        self.joint(shin, f"{n}_knee", [0, 1, 0], (-0.1, 2.7) if fwd else (-2.7, 0.1), leg.servo, n)
        _geom(shin, type=cap, fromto=[0, 0, 0, 0, 0, -leg.shin], size=[0.011, 0, 0], mass=seg * 0.6, rgba=col)
        r = leg.foot[0]
        _geom(shin, name=f"{n}_toe", type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[r, 0, 0], pos=[0, 0, -leg.shin],
              mass=0.01, rgba=_rgba("black"), condim=3, friction=[1.0, 0.02, 0.01])
        shin.add_site(name=f"{n}_foot", pos=[0, 0, -leg.shin])
        self.effectors[f"{n}_foot"] = {"site": f"{n}_foot", "limb": n}
        self.feet.append(f"{n}_foot")
        for pose, stance in ((self.home, None), (self.crouch, leg.stance * 0.8)):
            hip, knee = leg_angles(leg, stance)
            pose.update({f"{n}_abduct": 0.0, f"{n}_hip": hip, f"{n}_knee": knee})

    def head(self, base: Any) -> None:
        h = self.spec.head
        hx, hy, hz = h.size
        parent = base.add_body(name="neck_base", pos=list(h.mount))
        if h.dof == "pitch_yaw":
            pitch = parent
            self.joint(pitch, "neck_pitch", [0, 1, 0], (-0.6, 0.9), h.servo, "head")
            _geom(pitch, type=mujoco.mjtGeom.mjGEOM_CAPSULE, fromto=[0, 0, 0, 0, 0, max(h.neck, 0.01)],
                  size=[0.012, 0, 0], mass=0.05, rgba=_rgba("gray"))
            parent = pitch.add_body(name="head", pos=[0, 0, h.neck])
            self.joint(parent, "head_yaw", [0, 0, 1], (-1.4, 1.4), h.servo, "head")
            for pose in (self.home, self.crouch):
                pose.update({"neck_pitch": 0.0, "head_yaw": 0.0})
        else:
            # A fixed head still needs some mass on its own body.
            _geom(parent, type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.005, 0, 0], mass=0.005)
        _geom(parent, name="head_shell", type=mujoco.mjtGeom.mjGEOM_BOX, size=[hx / 2, hy / 2, hz / 2],
              pos=[hx * 0.2, 0, hz / 2], mass=0.12, rgba=_rgba(h.color))
        parent.add_site(name="head_cam", pos=[hx * 0.7 + 0.005, 0, hz / 2])
        self.effectors["head"] = {"site": "head_cam", "limb": "head"} if h.dof == "pitch_yaw" else {"site": "head_cam"}


def _gait_defaults(spec: RoboSpec) -> dict[str, Any]:
    leg_len = float(np.mean([leg.thigh + leg.shin for leg in spec.legs]))
    if spec.kind == "biped":
        biped6 = all(leg.dof == "biped6" for leg in spec.legs)
        g = {"period": 0.6, "step_height": round(0.2 * leg_len, 3), "double_support": 0.3, "stabilizer": "lipm_zmp",
             "params": {"tilt_gain": 0.5, "foot_roll_cost": 0.3 if biped6 else 0.0},
             "limits": {"vx": [round(-0.6 * leg_len, 3), round(1.1 * leg_len, 3)],
                        "vy": [round(-0.35 * leg_len, 3), round(0.35 * leg_len, 3)], "wz": [-0.6, 0.6]}}
    else:
        hexa = spec.kind == "hexapod"
        g = {"period": 0.7 if hexa else 0.35, "step_height": round(0.35 * leg_len, 3),
             "duty_factor": 0.55 if hexa else 0.6, "stabilizer": "imu_feedback",
             "limits": {"vx": [round(-1.2 * leg_len, 3), round((1.5 if hexa else 1.8) * leg_len, 3)],
                        "vy": [round(-0.8 * leg_len, 3), round(0.8 * leg_len, 3)], "wz": [-1.0, 1.0]}}
    custom = dict(spec.gait)
    for k, v in custom.items():
        if isinstance(v, dict) and isinstance(g.get(k), dict):
            g[k] = {**g[k], **v}
        else:
            g[k] = v
    return g


def compile_spec(spec: RoboSpec) -> tuple[str, dict[str, Any]]:
    """MJCF XML text and the manifest overrides for the registry entry."""
    b = _Builder(spec)
    mj = b.build()
    xml = mj.to_xml()
    mujoco.MjModel.from_xml_string(xml)  # fail early if it doesn't compile
    servos = {leg.servo for leg in spec.legs} | ({spec.head.servo} if spec.head and spec.head.dof != "fixed" else set())
    gait = GAIT_FOR[spec.kind]
    manifest: dict[str, Any] = {
        "kind": spec.kind,
        "description": spec.description or f"Designed {spec.kind} '{spec.name}'",
        "limbs": b.limbs,
        "end_effectors": b.effectors,
        "feet": b.feet,
        "default_pose": "home",
        "poses": {"home": b.home, "crouch": b.crouch},
        "max_joint_speed": min(servo_catalog()[s]["speed_rad_s"] for s in servos),
        "default_gait": gait,
        "gaits": {gait: _gait_defaults(spec)},
    }
    if spec.head is not None:
        manifest["aliases"] = {"head.pitch": "neck_pitch", "head.yaw": "head_yaw"} if spec.head.dof == "pitch_yaw" else {}
        manifest["camera"] = {"site": "head_cam", "pos": [0.0, 0.0, 0.0], "look": spec.head.camera_look,
                              "fovy": spec.head.camera_fovy}
    return xml, manifest
