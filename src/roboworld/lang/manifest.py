"""Robot manifest: the semantic layer of RoboLang.

A manifest gives an LLM (and the interpreter) meaningful names for a robot's
parts: limb groups, joint aliases like ``head.pitch``, end-effectors, named
poses and gait defaults. RoboLang programs only ever refer to these names, which
is what lets one language drive a duck, a dog or an arm.

Manifests are generated automatically from a compiled ``MjModel`` and then
merged with a hand-written (or LLM-proposed) override file.
"""

from __future__ import annotations

import difflib
import os
from typing import Any, Literal

import mujoco
import numpy as np
from pydantic import BaseModel, Field

RobotKind = Literal["biped", "quadruped", "hexapod", "arm", "wheeled", "mobile_manipulator", "other"]


class Joint(BaseModel):
    name: str
    range: tuple[float, float]
    actuator: str
    control: Literal["position", "torque"]
    force_limit: float | None = None
    # PD gains used by the servo layer when the actuator is torque-controlled.
    kp: float | None = None
    kd: float | None = None


class EndEffector(BaseModel):
    """A point the language can target: exactly one of site / geom / body."""

    site: str | None = None
    geom: str | None = None
    body: str | None = None
    limb: str | None = None

    @property
    def frame(self) -> tuple[str, str]:
        """(mink frame type, name)."""
        for kind in ("site", "geom", "body"):
            name = getattr(self, kind)
            if name:
                return kind, name
        raise ValueError("end effector has no site, geom or body")


class CameraMount(BaseModel):
    """The robot's eye: mounted on a body (or at a site), looking along ``look``
    (a direction in the base frame, at the default pose)."""

    body: str | None = None
    site: str | None = None
    pos: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    look: list[float] = Field(default_factory=lambda: [1.0, 0.0, -0.3])
    fovy: float = 60.0
    width: int = 320
    height: int = 240
    max_range: float = 5.0


class Manifest(BaseModel):
    robot: str
    kind: RobotKind = "other"
    description: str = ""
    floating_base: bool
    base_body: str
    imu_site: str | None = None
    mass: float
    joints: dict[str, Joint]
    limbs: dict[str, list[str]] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    end_effectors: dict[str, EndEffector] = Field(default_factory=dict)
    feet: list[str] = Field(default_factory=list)
    poses: dict[str, dict[str, float]] = Field(default_factory=dict)
    default_pose: str = "zero"
    max_joint_speed: float = 6.0  # rad/s, used to rate-limit targets
    gaits: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default_gait: str | None = None
    camera: CameraMount | None = None

    # ------------------------------------------------------------------ lookup
    def resolve_joint(self, ref: str) -> str:
        """Map a joint reference (name, alias or ``limb.suffix``) to a joint name."""
        if ref in self.joints:
            return ref
        if ref in self.aliases:
            return self.aliases[ref]
        lowered = {k.lower(): k for k in [*self.joints, *self.aliases]}
        if ref.lower() in lowered:
            return self.resolve_joint(lowered[ref.lower()])
        if "." in ref:
            limb, _, suffix = ref.partition(".")
            if limb in self.limbs:
                hits = [j for j in self.limbs[limb] if j.endswith(suffix) or suffix in j]
                if len(hits) == 1:
                    return hits[0]
        options = [*self.joints, *self.aliases]
        close = difflib.get_close_matches(ref, options, n=4, cutoff=0.4)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise KeyError(f"Unknown joint '{ref}' on {self.robot}.{hint}")

    def limb_joints(self, limb: str) -> list[str]:
        if limb not in self.limbs:
            close = difflib.get_close_matches(limb, list(self.limbs), n=3, cutoff=0.4)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise KeyError(f"Unknown limb '{limb}' on {self.robot}.{hint}")
        return self.limbs[limb]

    def pose(self, name: str) -> dict[str, float]:
        if name not in self.poses:
            close = difflib.get_close_matches(name, list(self.poses), n=3, cutoff=0.4)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise KeyError(f"Unknown pose '{name}' on {self.robot}. Known: {sorted(self.poses)}.{hint}")
        return self.poses[name]

    def clamp(self, joint: str, value: float, margin: float = 0.0) -> float:
        lo, hi = self.joints[joint].range
        return float(np.clip(value, lo + margin, hi - margin))

    # ----------------------------------------------------------------- display
    def summary(self) -> dict[str, Any]:
        """Compact description for an LLM: what can this robot do and how is it named."""
        return {
            "robot": self.robot,
            "kind": self.kind,
            "description": self.description,
            "mass_kg": round(self.mass, 3),
            "floating_base": self.floating_base,
            "limbs": self.limbs,
            "joints": {
                name: {"range_rad": [round(j.range[0], 3), round(j.range[1], 3)], "control": j.control}
                for name, j in self.joints.items()
            },
            "aliases": self.aliases,
            "end_effectors": {k: v.model_dump(exclude_none=True) for k, v in self.end_effectors.items()},
            "feet": self.feet,
            "poses": sorted(self.poses),
            "default_pose": self.default_pose,
            "gaits": self.gaits,
        }


# ---------------------------------------------------------------- generation
def _common_prefix(names: list[str]) -> str:
    prefix = os.path.commonprefix(names)
    # Only strip whole tokens: "left_hip_yaw"/"left_knee" -> "left_"
    cut = max(prefix.rfind("_"), prefix.rfind("."))
    return prefix[: cut + 1] if cut >= 0 else ""


def _actuated_joints(model: mujoco.MjModel) -> dict[str, Joint]:
    joints: dict[str, Joint] = {}
    for a in range(model.nu):
        if model.actuator_trntype[a] != mujoco.mjtTrn.mjTRN_JOINT:
            continue
        jid = int(model.actuator_trnid[a, 0])
        jname = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, jid)
        aname = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, a) or jname
        if model.jnt_limited[jid]:
            lo, hi = (float(x) for x in model.jnt_range[jid])
        else:
            lo, hi = -np.pi, np.pi
        is_position = (
            model.actuator_biastype[a] == mujoco.mjtBias.mjBIAS_AFFINE
            and model.actuator_biasprm[a, 1] < 0
        )
        force_limit = None
        if model.actuator_forcelimited[a]:
            force_limit = float(np.max(np.abs(model.actuator_forcerange[a])))
        elif not is_position and model.actuator_ctrllimited[a]:
            force_limit = float(np.max(np.abs(model.actuator_ctrlrange[a])))
        joints[jname] = Joint(
            name=jname,
            range=(lo, hi),
            actuator=aname,
            control="position" if is_position else "torque",
            force_limit=force_limit,
        )
    return joints


def _auto_limbs(model: mujoco.MjModel, joints: dict[str, Joint], base_body: int) -> dict[str, list[str]]:
    """Group joints by the branch of the kinematic tree they hang from."""
    groups: dict[int, list[str]] = {}
    for jname in joints:
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jname)
        body = int(model.jnt_bodyid[jid])
        # Walk up until the parent is the base (or world).
        while model.body_parentid[body] not in (base_body, 0) and body != base_body:
            body = int(model.body_parentid[body])
        groups.setdefault(body, []).append(jname)
    limbs: dict[str, list[str]] = {}
    for body, names in groups.items():
        prefix = _common_prefix(names).rstrip("_.")
        label = prefix or (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body) or f"limb{body}")
        while label in limbs:
            label += "_"
        limbs[label] = names
    return limbs


def _auto_aliases(limbs: dict[str, list[str]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for limb, names in limbs.items():
        prefix = _common_prefix(names) if len(names) > 1 else ""
        for name in names:
            suffix = name[len(prefix):]
            for tail in ("_joint", "_jnt"):
                suffix = suffix.removesuffix(tail)
            key = f"{limb}.{suffix}"
            if key != name:
                aliases[key] = name
    return aliases


def build_manifest(name: str, model: mujoco.MjModel, overrides: dict[str, Any] | None = None) -> Manifest:
    overrides = dict(overrides or {})
    joints = _actuated_joints(model)

    free = [j for j in range(model.njnt) if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE]
    floating = bool(free)
    base_id = int(model.jnt_bodyid[free[0]]) if floating else 1 if model.nbody > 1 else 0
    base_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, base_id) or "world"

    imu = None
    for candidate in ("imu", "IMU", "imu_site"):
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, candidate) >= 0:
            imu = candidate
            break

    limbs = overrides.pop("limbs", None) or _auto_limbs(model, joints, base_id)
    aliases = _auto_aliases(limbs)
    aliases.update(overrides.pop("aliases", {}) or {})

    poses: dict[str, dict[str, float]] = {
        "zero": {j: float(np.clip(0.0, *joints[j].range)) for j in joints}
    }
    for k in range(model.nkey):
        kname = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_KEY, k)
        if not kname:
            continue
        qpos = model.key_qpos[k]
        poses[kname] = {
            j: float(qpos[model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)]])
            for j in joints
        }
    for pname, values in (overrides.pop("poses", {}) or {}).items():
        base = dict(poses.get(pname, poses["zero"]))
        base.update(values)
        poses[pname] = base

    # Default PD gains for torque-controlled joints (the servo layer closes the loop).
    gains = overrides.pop("joint_gains", None) or {}
    for jname, joint in joints.items():
        if joint.control == "torque":
            limit = joint.force_limit or 10.0
            joints[jname] = joint.model_copy(
                update={"kp": gains.get("kp", limit * 2.0), "kd": gains.get("kd", limit * 0.1)}
            )
    joint_overrides = overrides.pop("joint_overrides", {}) or {}
    for jname, fields in joint_overrides.items():
        joints[jname] = joints[jname].model_copy(update=fields)

    effectors = {
        k: EndEffector(**v) for k, v in (overrides.pop("end_effectors", {}) or {}).items()
    }
    if not effectors:
        for s in range(model.nsite):
            sname = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, s) or ""
            if any(tag in sname.lower() for tag in ("foot", "hand", "gripper", "tool", "ee")):
                effectors[sname] = EndEffector(site=sname)

    manifest = Manifest(
        robot=name,
        floating_base=floating,
        base_body=base_name,
        imu_site=imu,
        mass=float(model.body_subtreemass[base_id if floating else 0]),
        joints=joints,
        limbs=limbs,
        aliases=aliases,
        end_effectors=effectors,
        poses=poses,
        **overrides,
    )
    # Validate cross references early so bad override files fail loudly.
    for limb, names in manifest.limbs.items():
        for j in names:
            if j not in manifest.joints:
                raise ValueError(f"Limb '{limb}' references unknown joint '{j}'")
    for alias, j in manifest.aliases.items():
        if j not in manifest.joints:
            raise ValueError(f"Alias '{alias}' points at unknown joint '{j}'")
    if manifest.default_pose not in manifest.poses:
        raise ValueError(f"default_pose '{manifest.default_pose}' is not a known pose")
    return manifest
