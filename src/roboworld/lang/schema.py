"""RoboLang: a small, typed language LLMs use to make robots move.

A program is a list of steps. Each step is a dict with exactly one *verb* key:

    pose      move joints to a named pose or explicit angles
    clip      play keyframes (a dance, a nod, a wave)
    gait      walk / trot with a velocity command until a condition holds
    reach     move an end-effector to a point (inverse kinematics)
    wait      hold still for a while (or until a condition)
    repeat    run a block of steps N times
    parallel  run blocks at the same time on different limbs
    do        a plain block of steps (useful inside parallel)
    skill     run a named, closed-loop skill (walk_to, turn, push, ...) with args

Any step can carry ``until:`` (stop early when a condition becomes true) and
``label:`` (shows up in the run's event log). Programs are plain YAML/JSON so
LLMs can write them through tool calls, and the Pydantic models below double
as the JSON schema.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

Ease = Literal["linear", "cubic", "min_jerk"]
Stabilizer = Literal["none", "imu_feedback", "lipm_zmp", "policy"]
JointMap = dict[str, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ conditions
class Condition(_Strict):
    """A predicate checked every control tick, measured from the step's start.

    Set exactly one field. Combine with ``any`` / ``all``.
    """

    timeout: float | None = Field(None, gt=0, description="seconds since the step started")
    distance_traveled: float | None = Field(None, gt=0, description="metres of ground path covered")
    displacement: float | None = Field(None, gt=0, description="straight-line metres from the start point")
    turned: float | None = Field(None, gt=0, description="absolute heading change in degrees")
    fallen: bool | None = Field(None, description="true once the robot has tipped over")
    reached: list[float] | None = Field(
        None, min_length=2, max_length=3, description="[x, y] or [x, y, tolerance] in world metres"
    )
    any: list[Condition] | None = None
    all: list[Condition] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Condition:
        set_fields = [k for k, v in self if v is not None]
        if len(set_fields) != 1:
            raise ValueError(
                f"a condition needs exactly one of {list(type(self).model_fields)}, got {set_fields or 'none'}"
            )
        return self


# ---------------------------------------------------------------------- steps
class _Step(_Strict):
    label: str | None = Field(None, description="name shown in the event log")
    until: Condition | None = Field(None, description="end this step early when the condition holds")


class PoseStep(_Step):
    pose: str | JointMap = Field(
        description="named pose (see describe_robot) or {joint_or_alias: radians}"
    )
    duration: float = Field(0.6, gt=0, description="seconds to get there")
    ease: Ease = "min_jerk"
    relative: bool = Field(False, description="treat angles as offsets from the current targets")
    hold: float = Field(0.0, ge=0, description="seconds to hold after arriving")


class Key(_Strict):
    """One keyframe: ``t`` seconds to reach it from the previous key, plus joint angles."""

    model_config = ConfigDict(extra="forbid")
    t: float = Field(gt=0)
    pose: str | None = Field(None, description="start from a named pose, then apply joints")
    ease: Ease | None = None
    joints: JointMap = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_joints(cls, data: Any) -> Any:
        # Allow the compact form {t: 0.3, head.pitch: 0.2} as well as {t: 0.3, joints: {...}}.
        if isinstance(data, dict):
            known = {"t", "pose", "ease", "joints"}
            joints = dict(data.get("joints") or {})
            extra = {k: v for k, v in data.items() if k not in known}
            for k, v in extra.items():
                if not isinstance(v, (int, float)):
                    raise ValueError(f"keyframe field '{k}' must be a joint angle in radians, got {v!r}")
                joints[k] = float(v)
            data = {k: v for k, v in data.items() if k in known}
            data["joints"] = joints
        return data

    @model_validator(mode="after")
    def _not_empty(self) -> Key:
        if not self.joints and not self.pose:
            raise ValueError("a keyframe needs a pose and/or joint angles")
        return self


class Clip(_Strict):
    keys: list[Key] = Field(min_length=1)
    repeat: int = Field(1, ge=1, le=100)
    ease: Ease = "min_jerk"
    relative: bool = Field(False, description="angles are offsets from the targets when the clip starts")


class ClipStep(_Step):
    clip: Clip


class Velocity(_Strict):
    vx: float = Field(0.0, description="forward m/s (base frame)")
    vy: float = Field(0.0, description="left m/s (base frame)")
    wz: float = Field(0.0, description="turn rate rad/s, positive = counter-clockwise")


class Gait(_Strict):
    type: str = Field(description="gait name, e.g. biped_walk, quadruped_trot (see describe_robot)")
    velocity: Velocity = Field(default_factory=Velocity)
    period: float | None = Field(None, gt=0.1, lt=5.0, description="seconds per full gait cycle")
    step_height: float | None = Field(None, ge=0.0, lt=0.5, description="metres of foot lift")
    duty_factor: float | None = Field(None, gt=0.2, lt=0.95, description="fraction of the cycle a foot is down")
    double_support: float | None = Field(None, ge=0.0, lt=0.9, description="biped: fraction of a step on both feet")
    body_height: float | None = Field(None, gt=-0.3, lt=0.3, description="metres to raise(+)/lower(-) the body")
    stabilizer: Stabilizer | None = None
    params: dict[str, float] = Field(default_factory=dict, description="gait-specific tuning knobs")


class GaitStep(_Step):
    gait: Gait
    duration: float | None = Field(None, gt=0, description="seconds to run (or use until)")


class Reach(_Strict):
    effector: str = Field(description="end-effector name (see describe_robot)")
    pos: list[float] = Field(min_length=3, max_length=3, description="[x, y, z] metres")
    frame: Literal["base", "world"] = "base"
    relative: bool = Field(False, description="pos is an offset from the effector's current position")
    duration: float = Field(0.8, gt=0)
    ease: Ease = "min_jerk"


class ReachStep(_Step):
    reach: Reach


class WaitStep(_Step):
    wait: float | None = Field(description="seconds to hold (null = only stop on until)")

    @field_validator("wait")
    @classmethod
    def _positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("wait must be > 0 seconds")
        return v


class Repeat(_Strict):
    times: int = Field(ge=1, le=1000)
    do: list[Step] = Field(min_length=1)


class RepeatStep(_Step):
    repeat: Repeat


class ParallelStep(_Step):
    parallel: list[Step] = Field(min_length=2, description="blocks that run at once on disjoint joints")
    race: bool = Field(False, description="finish when the first block finishes (default: when all do)")


class BlockStep(_Step):
    do: list[Step] = Field(min_length=1)


class SkillStep(_Step):
    skill: str = Field(description="skill name (see the robot's skill list), e.g. walk_to, turn, push")
    args: dict[str, Any] = Field(default_factory=dict)


VERBS = ("pose", "clip", "gait", "reach", "wait", "repeat", "parallel", "do", "skill")


def _verb(value: Any) -> str | None:
    if isinstance(value, dict):
        present = [v for v in VERBS if v in value]
        return present[0] if len(present) == 1 else None
    for verb in VERBS:
        if hasattr(value, verb) and type(value).__name__.lower().startswith({"do": "block"}.get(verb, verb)):
            return verb
    return None


Step = Annotated[
    Union[
        Annotated[PoseStep, Tag("pose")],
        Annotated[ClipStep, Tag("clip")],
        Annotated[GaitStep, Tag("gait")],
        Annotated[ReachStep, Tag("reach")],
        Annotated[WaitStep, Tag("wait")],
        Annotated[RepeatStep, Tag("repeat")],
        Annotated[ParallelStep, Tag("parallel")],
        Annotated[BlockStep, Tag("do")],
        Annotated[SkillStep, Tag("skill")],
    ],
    Discriminator(
        _verb,
        custom_error_type="step_verb",
        custom_error_message="each step needs exactly one verb: " + ", ".join(VERBS),
    ),
]


class Program(_Strict):
    """A RoboLang program."""

    robot: str | None = Field(None, description="robot this was written for (checked if given)")
    name: str | None = None
    description: str | None = None
    on_fall: Literal["stop", "continue"] = Field("stop", description="what to do if the robot tips over")
    do: list[Step] = Field(min_length=1)


for _model in (Condition, Repeat, RepeatStep, ParallelStep, BlockStep, Program):
    _model.model_rebuild()


def parse_program(source: str | dict[str, Any] | list[Any]) -> Program:
    """Parse YAML/JSON text, a dict, or a bare list of steps into a Program."""
    import yaml

    data = yaml.safe_load(source) if isinstance(source, str) else source
    if isinstance(data, list):
        data = {"do": data}
    if not isinstance(data, dict):
        raise ValueError("a program must be a mapping with a 'do' list (or a list of steps)")
    return Program.model_validate(data)


def program_json_schema() -> dict[str, Any]:
    return Program.model_json_schema()
