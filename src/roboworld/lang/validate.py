"""Static checks of a RoboLang program against a specific robot, before running it.

Errors stop a program from running. Warnings are things the safety layer will
quietly fix (clamping, slowing down) that the author probably wants to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from roboworld.lang import schema
from roboworld.lang.gaits import available_gaits
from roboworld.lang.manifest import Manifest


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    estimated_duration_s: float | None = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings,
                "estimated_duration_s": None if self.estimated_duration_s is None
                else round(self.estimated_duration_s, 2)}


def format_validation_error(err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        parts: list[str] = []
        loc = list(e["loc"])
        for i, x in enumerate(loc):
            if i + 1 < len(loc) and loc[i + 1] == x:
                continue  # union tags repeat the verb: ('clip', 'clip') -> 'clip'
            if isinstance(x, int):
                parts[-1:] = [f"{parts[-1]}[{x}]"] if parts else [f"[{x}]"]
            else:
                parts.append(str(x))
        out.append(f"{'.'.join(parts) or 'program'}: {e['msg']}")
    return out


class _Checker:
    def __init__(self, manifest: Manifest, report: Report):
        self.m = manifest
        self.r = report
        self.gaits = available_gaits(manifest)

    def joints_of_pose(self, pose: str | dict[str, float], where: str) -> dict[str, float]:
        try:
            if isinstance(pose, str):
                return dict(self.m.pose(pose))
            return {self.m.resolve_joint(k): v for k, v in pose.items()}
        except KeyError as e:
            self.r.errors.append(f"{where}: {e.args[0]}")
            return {}

    def check_values(self, values: dict[str, float], where: str, relative: bool) -> None:
        if relative:
            return
        for j, v in values.items():
            lo, hi = self.m.joints[j].range
            if not lo - 1e-6 <= v <= hi + 1e-6:
                self.r.warnings.append(f"{where}: {j}={v:.3f} is outside its range [{lo:.3f}, {hi:.3f}] and will be clamped")

    def check_speed(self, before: dict[str, float], after: dict[str, float], t: float, where: str) -> None:
        for j, v in after.items():
            if j in before and t > 0:
                speed = abs(v - before[j]) / t
                if speed > self.m.max_joint_speed * 1.5:
                    self.r.warnings.append(
                        f"{where}: {j} would need {speed:.1f} rad/s (servo max ~{self.m.max_joint_speed}); "
                        "it will move slower than written"
                    )

    def steps(self, steps: list[Any], path: str) -> tuple[set[str], float | None]:
        claims: set[str] = set()
        total: float | None = 0.0
        for i, step in enumerate(steps):
            c, d = self.step(step, f"{path}[{i}]")
            claims |= c
            total = None if total is None or d is None else total + d
        return claims, total

    def step(self, step: Any, where: str) -> tuple[set[str], float | None]:
        if step.label:
            where = f"{where}({step.label})"
        duration: float | None
        if isinstance(step, schema.PoseStep):
            values = self.joints_of_pose(step.pose, where)
            self.check_values(values, where, step.relative)
            claims, duration = set(values), step.duration + step.hold
            current = self.m.pose(self.m.default_pose)
            self.check_speed(current, values, step.duration, where)
        elif isinstance(step, schema.ClipStep):
            claims, duration = set(), 0.0
            prev = dict(self.m.pose(self.m.default_pose))
            for k, key in enumerate(step.clip.keys):
                values = self.joints_of_pose(key.pose, f"{where}.keys[{k}]") if key.pose else {}
                values.update(self.joints_of_pose(key.joints, f"{where}.keys[{k}]"))
                self.check_values(values, f"{where}.keys[{k}]", step.clip.relative)
                if not step.clip.relative:
                    self.check_speed(prev, values, key.t, f"{where}.keys[{k}]")
                    prev.update(values)
                claims |= set(values)
                duration += key.t
            duration *= step.clip.repeat
        elif isinstance(step, schema.GaitStep):
            g = step.gait
            claims = set()
            duration = step.duration
            if g.type not in self.gaits:
                self.r.errors.append(f"{where}: gait '{g.type}' is not available for this {self.m.kind}; "
                                     f"use one of {self.gaits}")
            else:
                for f in self.m.feet:
                    limb = self.m.end_effectors[f].limb
                    claims |= set(self.m.limbs.get(limb or "", []))
                limits = self.m.gaits.get(g.type, {}).get("limits", {})
                for axis, (lo, hi) in limits.items():
                    v = getattr(g.velocity, axis)
                    if not lo <= v <= hi:
                        self.r.warnings.append(f"{where}: {axis}={v} is outside the tested range [{lo}, {hi}] "
                                               "for this robot; it may fall")
            if step.duration is None and step.until is None:
                self.r.errors.append(f"{where}: a gait never stops on its own; add 'duration' or 'until'")
        elif isinstance(step, schema.ReachStep):
            claims, duration = set(), step.reach.duration
            ee = self.m.end_effectors.get(step.reach.effector)
            if ee is None:
                self.r.errors.append(f"{where}: unknown end effector '{step.reach.effector}'; "
                                     f"known: {sorted(self.m.end_effectors)}")
            else:
                claims = set(self.m.limbs.get(ee.limb or "", self.m.joints))
        elif isinstance(step, schema.WaitStep):
            claims, duration = set(), step.wait
            if step.wait is None and step.until is None:
                self.r.errors.append(f"{where}: 'wait: null' needs an 'until' condition")
        elif isinstance(step, schema.RepeatStep):
            claims, d = self.steps(step.repeat.do, f"{where}.repeat.do")
            duration = None if d is None else d * step.repeat.times
        elif isinstance(step, schema.BlockStep):
            claims, duration = self.steps(step.do, f"{where}.do")
        elif isinstance(step, schema.ParallelStep):
            claims, durations = set(), []
            for b, branch in enumerate(step.parallel):
                c, d = self.step(branch, f"{where}.parallel[{b}]")
                overlap = claims & c
                if overlap:
                    self.r.errors.append(
                        f"{where}.parallel[{b}]: joints {sorted(overlap)} are already driven by another "
                        "parallel branch; give each branch different limbs"
                    )
                claims |= c
                durations.append(d)
            known = [d for d in durations if d is not None]
            if step.race:
                duration = min(known) if known else None
            else:
                duration = None if None in durations else max(durations)
        elif isinstance(step, schema.SkillStep):
            from roboworld.lang.skills import check_skill, default_gait

            claims, duration = set(), None  # skills end on their own; duration depends on the world
            try:
                check_skill(step.skill, step.args, self.m)
            except ValueError as e:
                self.r.errors.append(f"{where}: {e}")
            gait = default_gait(self.m)
            if gait and step.skill not in ("look_at", "stand", "play"):
                for f in self.m.feet:
                    claims |= set(self.m.limbs.get(self.m.end_effectors[f].limb or "", []))
        else:  # pragma: no cover
            raise TypeError(type(step))
        if step.until is not None:
            timeout = step.until.timeout
            duration = timeout if duration is None else (min(duration, timeout) if timeout else duration)
            if duration is None and timeout is None:
                duration = None
        return claims, duration


def validate(program: schema.Program, manifest: Manifest) -> Report:
    report = Report()
    if program.robot and program.robot != manifest.robot:
        report.errors.append(f"program was written for '{program.robot}' but is being run on '{manifest.robot}'")
    _, duration = _Checker(manifest, report).steps(program.do, "do")
    report.estimated_duration_s = duration
    return report


def check_source(source: str | dict | list, manifest: Manifest) -> tuple[schema.Program | None, Report]:
    """Parse + validate, turning schema errors into readable report errors."""
    try:
        program = schema.parse_program(source)
    except ValidationError as e:
        return None, Report(errors=format_validation_error(e), estimated_duration_s=None)
    except Exception as e:  # YAML syntax errors etc.
        return None, Report(errors=[f"could not parse program: {e}"], estimated_duration_s=None)
    return program, validate(program, manifest)
