"""RoboSpec: a robot described in a few numbers, so a person or an LLM can design
and tweak it ("make the legs 2 cm longer", "add ankle roll", "wider feet").

A RoboSpec compiles (see compiler.py) into a MuJoCo model plus a manifest, so a
designed robot works with every gait, skill, task and benchmark in RoboWorld.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from roboworld import paths

TEMPLATE_DIR = paths.PACKAGE_DIR / "design" / "templates"
LegDof = Literal["biped5", "biped6", "quad3"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


@lru_cache(maxsize=1)
def servo_catalog() -> dict[str, dict[str, Any]]:
    return yaml.safe_load((paths.PACKAGE_DIR / "design" / "servos.yaml").read_text())


class BodySpec(_Strict):
    size: list[float] = Field(min_length=3, max_length=3, description="torso [length x, width y, height z] in m")
    mass: float = Field(gt=0, le=50, description="torso mass incl. battery and electronics, kg")
    color: str = "white"


class LegSpec(_Strict):
    name: str = Field(description="leg name, e.g. left_leg, right_leg, FL, FR, RL, RR")
    mount: list[float] = Field(min_length=3, max_length=3, description="hip position relative to torso centre, m")
    dof: LegDof = Field(description="biped5: yaw/roll/pitch/knee/ankle; biped6: + ankle roll; quad3: abduct/hip/knee")
    thigh: float = Field(0.08, gt=0.01, lt=0.6, description="hip-to-knee length, m")
    shin: float = Field(0.08, gt=0.01, lt=0.6, description="knee-to-ankle length, m")
    foot: list[float] = Field(default_factory=lambda: [0.10, 0.05],
                              description="biped: [length, width] of the flat foot; quad: [radius] of the ball foot")
    knee: Literal["forward", "backward"] = "forward"
    stance: float = Field(0.85, gt=0.4, lt=0.98, description="standing hip height as a fraction of thigh+shin")
    servo: str = "sts3215"
    segment_mass: float = Field(0.07, gt=0, lt=5, description="mass of each leg segment (servo + bracket), kg")
    color: str = "gray"

    @model_validator(mode="after")
    def _check(self) -> LegSpec:
        if self.servo not in servo_catalog():
            raise ValueError(f"unknown servo '{self.servo}'; catalog: {sorted(servo_catalog())}")
        need = 1 if self.dof == "quad3" else 2
        if len(self.foot) != need:
            raise ValueError(f"leg '{self.name}' ({self.dof}) needs foot with {need} value(s)")
        return self


class HeadSpec(_Strict):
    size: list[float] = Field(default_factory=lambda: [0.08, 0.08, 0.06], min_length=3, max_length=3)
    mount: list[float] = Field(min_length=3, max_length=3, description="neck base relative to torso centre, m")
    neck: float = Field(0.05, ge=0.0, lt=0.4, description="neck length, m")
    dof: Literal["pitch_yaw", "fixed"] = "pitch_yaw"
    servo: str = "sts3215"
    camera_look: list[float] = Field(default_factory=lambda: [1.0, 0.0, -0.7], min_length=3, max_length=3)
    camera_fovy: float = 80.0
    color: str = "white"


class RoboSpec(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    kind: Literal["biped", "quadruped", "hexapod"]
    description: str = ""
    template: str | None = None
    body: BodySpec
    legs: list[LegSpec] = Field(min_length=2)
    head: HeadSpec | None = None
    gait: dict[str, Any] = Field(default_factory=dict, description="overrides for the default gait's settings")

    @model_validator(mode="after")
    def _check(self) -> RoboSpec:
        names = [leg.name for leg in self.legs]
        if len(set(names)) != len(names):
            raise ValueError("leg names must be unique")
        expected = {"biped": 2, "quadruped": 4, "hexapod": 6}[self.kind]
        if len(self.legs) != expected:
            raise ValueError(f"a {self.kind} needs {expected} legs, got {len(self.legs)}")
        if self.kind == "biped" and any(leg.dof == "quad3" for leg in self.legs):
            raise ValueError("biped legs must be biped5 or biped6")
        if self.kind != "biped" and any(leg.dof != "quad3" for leg in self.legs):
            raise ValueError(f"{self.kind} legs must be quad3")
        return self

    def digest(self) -> str:
        """Content hash of the design (name excluded), for history and de-duplication."""
        data = self.model_dump(exclude={"name", "description", "template"})
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


# ------------------------------------------------------------------ templates
def list_templates() -> dict[str, str]:
    out = {}
    for f in sorted(TEMPLATE_DIR.glob("*.yaml")):
        out[f.stem] = (yaml.safe_load(f.read_text()) or {}).get("description", "")
    return out


def load_template(name: str) -> dict[str, Any]:
    f = TEMPLATE_DIR / f"{name}.yaml"
    if not f.exists():
        raise KeyError(f"unknown template '{name}'. Templates: {sorted(list_templates())}")
    data = yaml.safe_load(f.read_text())
    data["template"] = name
    return data


# -------------------------------------------------------------------- changes
def apply_changes(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``changes`` into a spec dict.

    Extras that make LLM-written edits easy:
    - ``legs: {left_leg: {thigh: 0.1}}`` edits legs by name (a list replaces all legs)
    - ``all_legs: {...}`` applies to every leg
    - dotted keys: ``{"body.mass": 1.5, "head.neck": 0.08}``
    """
    out = copy.deepcopy(base)
    changes = copy.deepcopy(changes or {})
    for key in [k for k in changes if "." in k]:
        value = changes.pop(key)
        node = changes
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    all_legs = changes.pop("all_legs", None)
    legs = changes.pop("legs", None)

    def merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v

    merge(out, changes)
    if isinstance(legs, list):
        out["legs"] = legs
    elif isinstance(legs, dict):
        by_name = {leg["name"]: leg for leg in out.get("legs", [])}
        for name, patch in legs.items():
            if name not in by_name:
                raise KeyError(f"no leg named '{name}'; legs: {sorted(by_name)}")
            merge(by_name[name], patch)
    if all_legs:
        for leg in out.get("legs", []):
            merge(leg, all_legs)
    return out
