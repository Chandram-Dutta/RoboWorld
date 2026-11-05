"""Skills: named, closed-loop behaviours built on RoboLang gaits and poses.

A skill is what an LLM brain asks for ("walk_to red_ball", "turn 90"). Each one
runs as an interpreter Action at the control rate, uses perception (only what
the robot has seen) and reports an outcome: ok, a message and data. Skills are
also usable inside RoboLang programs: ``- skill: walk_to`` with ``args: {...}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from roboworld import paths
from roboworld.lang import schema
from roboworld.lang.gaits import available_gaits, make_gait
from roboworld.lang.interpreter import Action, Ctx, Interpolate, Sequence, build
from roboworld.lang.manifest import Manifest

if TYPE_CHECKING:
    from roboworld.sim.perception import Perception

Target = str | list[float]


def wrap(a: float) -> float:
    return float((a + np.pi) % (2 * np.pi) - np.pi)


# ---------------------------------------------------------------- registry
@dataclass
class SkillDef:
    name: str
    description: str
    params: type[BaseModel]
    applies: Callable[[Manifest], bool]
    cls: type


SKILLS: dict[str, SkillDef] = {}


def skill(name: str, description: str, params: type[BaseModel], applies: Callable[[Manifest], bool]):
    def register(cls: type) -> type:
        SKILLS[name] = SkillDef(name, description, params, applies, cls)
        return cls

    return register


def default_gait(m: Manifest) -> str | None:
    gaits = available_gaits(m)
    if m.default_gait in gaits:
        return m.default_gait
    return gaits[0] if gaits else None


def can_move(m: Manifest) -> bool:
    return default_gait(m) is not None


def head_joint(m: Manifest, axis: str) -> str | None:
    try:
        return m.resolve_joint(f"head.{axis}")
    except KeyError:
        return None


def has_camera(m: Manifest) -> bool:
    return m.camera is not None


def available_skills(m: Manifest) -> list[dict[str, Any]]:
    out = []
    for sd in SKILLS.values():
        if sd.applies(m):
            schema_ = sd.params.model_json_schema()
            out.append({"name": sd.name, "description": sd.description,
                        "args": schema_.get("properties", {}), "required": schema_.get("required", [])})
    return out


def check_skill(name: str, args: dict[str, Any], m: Manifest) -> BaseModel:
    """Validate a skill call; raises ValueError with a readable message."""
    sd = SKILLS.get(name)
    usable = sorted(s.name for s in SKILLS.values() if s.applies(m))
    if sd is None:
        raise ValueError(f"unknown skill '{name}'. Available: {usable}")
    if not sd.applies(m):
        raise ValueError(f"skill '{name}' isn't available on {m.robot}. Available: {usable}")
    try:
        return sd.params.model_validate(args or {})
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'args'}: {err['msg']}" for err in e.errors())
        raise ValueError(f"bad args for {name}: {problems}") from None


def make_skill(step: schema.SkillStep, ctx: Ctx) -> Action:
    args = check_skill(step.skill, step.args, ctx.manifest)
    return SKILLS[step.skill].cls(ctx, args, step.label)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------- base
class Skill(Action):
    name = "skill"

    def __init__(self, ctx: Ctx, args: BaseModel, label: str | None = None):
        super().__init__(None)
        self.args = args
        self.label_text = label
        self.claims = set()
        self.ok: bool | None = None

    def begin(self, ctx: Ctx) -> None:
        ctx.event("skill_start", f"{self.name}({self.args.model_dump(exclude_none=True)})")
        super().begin(ctx)

    def report(self, ctx: Ctx, ok: bool, message: str, **data: Any) -> None:
        if self.ok is not None:
            return
        self.ok = ok
        st = ctx.state
        result = {"skill": self.name, "ok": ok, "message": message,
                  "duration_s": round(ctx.t - self.t0, 2)}
        if st is not None:
            result["robot"] = {"x": round(float(st.base_pos[0]), 2), "y": round(float(st.base_pos[1]), 2),
                               "heading_deg": round(float(np.degrees(st.yaw)))}
        result.update(data)
        ctx.results.append(result)
        ctx.event("skill_end", f"{self.name}: {'ok' if ok else 'FAILED'} - {message}")

    def sense(self, ctx: Ctx) -> Perception:
        if ctx.sense is None:
            raise LookupError("this skill needs perception (run it inside a world/episode)")
        return ctx.sense

    def locate(self, ctx: Ctx, target: Target) -> tuple[np.ndarray, Any]:
        """World xy of a target: [x, y] coordinates or a remembered object."""
        if isinstance(target, list):
            if len(target) != 2:
                raise LookupError("coordinates must be [x, y]")
            return np.asarray(target, dtype=float), None
        det = self.sense(ctx).resolve(target)
        return np.asarray(det.position, dtype=float), det


class Mover:
    """Drives the robot's default gait with live velocity / heading commands."""

    def __init__(self, ctx: Ctx, speed: float | None):
        m = ctx.manifest
        self.gait_name = default_gait(m)
        self.gait = make_gait(ctx, schema.Gait(type=self.gait_name))
        limits = m.gaits.get(self.gait_name, {}).get("limits", {})
        self.vmax = float(limits.get("vx", [-0.3, 0.3])[1]) * 0.85
        self.vback = float(abs(limits.get("vx", [-0.3, 0.3])[0])) * 0.85
        self.vlat = float(abs(limits.get("vy", [-0.1, 0.1])[1])) * 0.85
        self.turn_rate = float(limits.get("wz", [-0.6, 0.6])[1]) * 0.85
        self.speed = min(speed, self.vmax) if speed else self.vmax
        self.gait.settings.params["turn_rate"] = self.turn_rate
        self.started = False

    @property
    def claims(self) -> set[int]:
        return set(self.gait.claims)

    def drive(self, ctx: Ctx, vx: float = 0.0, vy: float = 0.0, heading: float | None = None) -> None:
        if not self.started:
            self.gait.start(ctx)
            self.started = True
        self.gait.set_command(vx=float(np.clip(vx, -self.vback, self.vmax)),
                              vy=float(np.clip(vy, -self.vlat, self.vlat)), wz=0.0)
        self.gait.heading_target = heading
        self.gait.tick(ctx)

    def stop(self, ctx: Ctx) -> bool:
        """Request a graceful stop and keep ticking; True once fully stopped."""
        if not self.started:
            return True
        self.gait.heading_target = None
        self.gait.set_command(0.0, 0.0, 0.0)
        self.gait.request_stop()
        if not self.gait.done:
            self.gait.tick(ctx)
        return self.gait.done


class MovingSkill(Skill):
    """Skill that walks: subclasses implement ``control`` returning (vx, vy, heading) or a final outcome."""

    timeout = 60.0

    def __init__(self, ctx: Ctx, args: BaseModel, label: str | None = None):
        super().__init__(ctx, args, label)
        self.mover = Mover(ctx, getattr(args, "speed", None))
        self.claims = self.mover.claims
        self.final: tuple[bool, str, dict] | None = None
        self.interrupted = False

    def start(self, ctx: Ctx) -> None:
        st = ctx.state
        self.p0 = st.base_pos[:2].copy()
        self.yaw0 = st.yaw
        self.best = np.inf
        self.best_t = ctx.t
        try:
            self.setup(ctx)
        except LookupError as e:
            self.final = (False, str(e), {})

    def setup(self, ctx: Ctx) -> None:
        pass

    def control(self, ctx: Ctx) -> tuple[float, float, float | None] | tuple[bool, str, dict]:
        raise NotImplementedError

    def tick(self, ctx: Ctx) -> None:
        if self.final is None and not self.interrupted:
            if ctx.t - self.t0 > self.timeout:
                self.final = (False, f"gave up after {self.timeout:.0f} s", {})
            else:
                try:
                    out = self.control(ctx)
                except LookupError as e:
                    out = (False, str(e), {})
                if isinstance(out[0], bool):
                    self.final = out  # type: ignore[assignment]
                else:
                    vx, vy, heading = out  # type: ignore[misc]
                    self.mover.drive(ctx, vx, vy, heading)
                    return
        if self.mover.stop(ctx):
            if self.interrupted and self.final is None:
                self.final = (False, "interrupted", {})
            ok, msg, data = self.final  # type: ignore[misc]
            self.report(ctx, ok, msg, **data)
            self.finish(ctx)

    def request_stop(self, ctx: Ctx) -> None:
        self.interrupted = True

    def stuck(self, ctx: Ctx, distance: float, window: float = 4.0) -> bool:
        """True if ``distance`` (to go) hasn't improved by 3 cm in ``window`` seconds.
        Time spent turning on the spot (see ``nav``) doesn't count."""
        if getattr(self, "_turning", False):
            self.best_t = ctx.t
            self.best = min(self.best, distance)
            return False
        if distance < self.best - 0.03:
            self.best = distance
            self.best_t = ctx.t
        return ctx.t - self.best_t > window

    def nav(self, ctx: Ctx, goal: np.ndarray, speed: float) -> tuple[float, float, float, float]:
        """(vx, vy, heading, distance) to walk toward ``goal``; turns on the spot when facing away."""
        st = ctx.state
        d = goal - st.base_pos[:2]
        dist = float(np.linalg.norm(d))
        heading = float(np.arctan2(d[1], d[0]))
        err = wrap(heading - st.yaw)
        self._turning = abs(err) > np.radians(35)
        vx = 0.0 if self._turning else speed * float(np.clip(dist / 0.4, 0.35, 1.0)) * np.cos(err)
        return vx, 0.0, heading, dist


# ---------------------------------------------------------------- skills
class StandArgs(_Args):
    pass


@skill("stand", "Stop and return to the default standing pose.", StandArgs, lambda m: True)
class Stand(Skill):
    name = "stand"

    def start(self, ctx: Ctx) -> None:
        pose = ctx.manifest.pose(ctx.manifest.default_pose)
        self.inner = Interpolate(None, [(0.6, pose, "min_jerk")])
        self.inner.bind(ctx)
        self.claims = self.inner.claims
        self.inner.begin(ctx)

    def tick(self, ctx: Ctx) -> None:
        self.inner.tick(ctx)
        if self.inner.done:
            self.report(ctx, True, "standing")
            self.finish(ctx)


class WalkArgs(_Args):
    distance: float = Field(description="metres; negative walks backward", ge=-5, le=5)
    speed: float | None = Field(None, gt=0, description="m/s (default: robot's comfortable speed)")


@skill("walk", "Walk straight forward (or backward with a negative distance), holding the current heading.",
       WalkArgs, can_move)
class Walk(MovingSkill):
    name = "walk"

    def setup(self, ctx: Ctx) -> None:
        a = self.args
        sp = self.mover.speed if a.distance >= 0 else min(self.mover.speed, self.mover.vback)
        self.timeout = abs(a.distance) / max(sp, 1e-3) * 2.5 + 5
        self.dir = np.array([np.cos(self.yaw0), np.sin(self.yaw0)])

    def control(self, ctx: Ctx):
        a = self.args
        progress = float((ctx.state.base_pos[:2] - self.p0) @ self.dir)
        remaining = a.distance - progress
        if abs(remaining) < 0.03 or np.sign(remaining) != np.sign(a.distance):
            return True, f"walked {progress:.2f} m", {"walked_m": round(progress, 2)}
        if self.stuck(ctx, abs(remaining)):
            return False, f"blocked after {progress:.2f} m", {"walked_m": round(progress, 2)}
        speed = self.mover.speed * float(np.clip(abs(remaining) / 0.3, 0.4, 1.0))
        return float(np.sign(remaining)) * speed, 0.0, self.yaw0


class StrafeArgs(_Args):
    distance: float = Field(description="metres; positive = to the robot's left", ge=-3, le=3)


@skill("strafe", "Step sideways (positive = left) without turning.", StrafeArgs, can_move)
class Strafe(MovingSkill):
    name = "strafe"

    def setup(self, ctx: Ctx) -> None:
        self.timeout = abs(self.args.distance) / max(self.mover.vlat, 1e-3) * 2.5 + 5
        self.dir = np.array([-np.sin(self.yaw0), np.cos(self.yaw0)])

    def control(self, ctx: Ctx):
        d = self.args.distance
        progress = float((ctx.state.base_pos[:2] - self.p0) @ self.dir)
        remaining = d - progress
        if abs(remaining) < 0.03 or np.sign(remaining) != np.sign(d):
            return True, f"moved {progress:.2f} m sideways", {}
        if self.stuck(ctx, abs(remaining)):
            return False, f"blocked after {progress:.2f} m", {}
        return 0.0, float(np.sign(remaining)) * self.mover.vlat, self.yaw0


class TurnArgs(_Args):
    degrees: float = Field(description="positive = turn left (counter-clockwise)", ge=-720, le=720)


@skill("turn", "Turn on the spot by a number of degrees (positive = left).", TurnArgs, can_move)
class Turn(MovingSkill):
    name = "turn"

    def setup(self, ctx: Ctx) -> None:
        self.goal = self.yaw0 + np.radians(self.args.degrees)
        self.timeout = abs(np.radians(self.args.degrees)) / max(self.mover.turn_rate, 1e-3) * 2.5 + 5
        self.turned = 0.0
        self.last = self.yaw0

    def control(self, ctx: Ctx):
        yaw = ctx.state.yaw
        self.turned += wrap(yaw - self.last)
        self.last = yaw
        remaining = np.radians(self.args.degrees) - self.turned
        if abs(remaining) < np.radians(4):
            return True, f"turned {np.degrees(self.turned):.0f}°", {}
        if self.stuck(ctx, abs(remaining)):
            return False, f"could not turn further (turned {np.degrees(self.turned):.0f}°)", {}
        # Steer to an intermediate heading so large turns keep their direction.
        step = float(np.clip(remaining, -np.radians(60), np.radians(60)))
        return 0.0, 0.0, yaw + step


class TargetArgs(_Args):
    target: Target = Field(description="an object you have seen (name like 'red_ball' or 'red ball') or [x, y]")


@skill("face", "Turn on the spot to face a seen object or a point.", TargetArgs, can_move)
class Face(MovingSkill):
    name = "face"

    def setup(self, ctx: Ctx) -> None:
        self.timeout = 20.0

    def control(self, ctx: Ctx):
        goal, _ = self.locate(ctx, self.args.target)
        d = goal - ctx.state.base_pos[:2]
        heading = float(np.arctan2(d[1], d[0]))
        err = wrap(heading - ctx.state.yaw)
        if abs(err) < np.radians(5):
            return True, f"facing {self.args.target}", {}
        if self.stuck(ctx, abs(err)):
            return False, "could not turn to face it", {}
        return 0.0, 0.0, heading


class WalkToArgs(_Args):
    target: Target = Field(description="an object you have seen or [x, y] in metres")
    stop_distance: float | None = Field(None, gt=0, description="stop this far from the target's centre (m)")
    speed: float | None = Field(None, gt=0)


@skill("walk_to", "Walk to a seen object or a point, steering as it goes (no obstacle avoidance: "
       "if something is in the way it reports 'blocked').", WalkToArgs, can_move)
class WalkTo(MovingSkill):
    name = "walk_to"

    def setup(self, ctx: Ctx) -> None:
        goal, det = self.locate(ctx, self.args.target)
        front = ctx.kin.front_reach()
        default_stop = front + (det.size_m / 2 if det else 0.0) + 0.08
        self.stop = self.args.stop_distance or default_stop
        dist = float(np.linalg.norm(goal - ctx.state.base_pos[:2]))
        self.timeout = dist / max(self.mover.speed, 1e-3) * 3 + 10

    def control(self, ctx: Ctx):
        goal, _ = self.locate(ctx, self.args.target)
        vx, vy, heading, dist = self.nav(ctx, goal, self.mover.speed)
        if dist <= self.stop:
            return True, f"arrived {dist:.2f} m from {self.args.target}", {"distance_m": round(dist, 2)}
        if self.stuck(ctx, dist):
            return False, f"blocked {dist:.2f} m from {self.args.target}", {"distance_m": round(dist, 2)}
        return vx, vy, heading


class LookAroundArgs(_Args):
    pass


@skill("look_around", "Scan the surroundings (head sweep and/or turning on the spot) and report everything "
       "seen. Use this to search for things.", LookAroundArgs, lambda m: has_camera(m))
class LookAround(Skill):
    name = "look_around"

    def start(self, ctx: Ctx) -> None:
        m = ctx.manifest
        self.yaw_joint = head_joint(m, "yaw")
        self.mover = Mover(ctx, None) if can_move(m) else None
        self.claims = set(self.mover.claims) if self.mover else set()
        self.plan: list[tuple[str, float]] = []
        if self.yaw_joint:
            lo, hi = m.joints[self.yaw_joint].range
            amp = float(min(1.4, hi * 0.9, -lo * 0.9))
            self.claims |= {ctx.index[self.yaw_joint]}
            self.plan += [("head", amp), ("head", -amp), ("head", 0.0)]
            if self.mover:
                self.plan += [("turn", np.pi), ("head", amp), ("head", -amp), ("head", 0.0), ("turn", np.pi)]
        elif self.mover:
            self.plan += [("turn", np.pi / 2)] * 4
        self.seen_before = set(self.sense(ctx).memory)
        self._next(ctx)

    def _next(self, ctx: Ctx) -> None:
        if not self.plan:
            self.phase = None
            return
        self.phase, value = self.plan.pop(0)
        self.t_phase = ctx.t
        if self.phase == "head":
            self.head_from = float(ctx.targets[ctx.index[self.yaw_joint]])
            self.head_to = value
        else:
            self.heading = ctx.state.yaw + value

    def tick(self, ctx: Ctx) -> None:
        if self.phase == "head":
            u = (ctx.t - self.t_phase) / 1.2
            i = ctx.index[self.yaw_joint]
            ctx.targets[i] = self.head_from + (self.head_to - self.head_from) * min(1.0, u * u * (3 - 2 * u))
            if u >= 1.0:
                self._next(ctx)
        elif self.phase == "turn":
            err = wrap(self.heading - ctx.state.yaw)
            if abs(err) < np.radians(6) or ctx.t - self.t_phase > 12:
                if self.mover.stop(ctx):
                    self.mover = Mover(ctx, None)
                    self._next(ctx)
            else:
                self.mover.drive(ctx, 0.0, 0.0, self.heading)
        else:
            if self.mover is None or self.mover.stop(ctx):
                sense = self.sense(ctx)
                objects = sense.known_objects(ctx.state)
                new = sorted(set(sense.memory) - self.seen_before)
                msg = f"saw {len(objects)} object(s)" + (f", new: {', '.join(new)}" if new else "")
                self.report(ctx, True, msg, objects=objects)
                self.finish(ctx)

    def request_stop(self, ctx: Ctx) -> None:
        self.plan = []
        self.phase = None


class LookAtArgs(_Args):
    target: Target = Field(description="an object you have seen or [x, y]")


@skill("look_at", "Point the head (or the whole body, if there is no head) at a seen object or point.",
       LookAtArgs, lambda m: has_camera(m) and (head_joint(m, "yaw") is not None or can_move(m)))
class LookAt(Skill):
    name = "look_at"

    def start(self, ctx: Ctx) -> None:
        m = ctx.manifest
        self.yaw_joint = head_joint(m, "yaw")
        self.inner: Action | None = None
        try:
            goal, _ = self.locate(ctx, self.args.target)
        except LookupError as e:
            self.report(ctx, False, str(e))
            self.finish(ctx)
            return
        d = goal - ctx.state.base_pos[:2]
        bearing = wrap(float(np.arctan2(d[1], d[0])) - ctx.state.yaw)
        if self.yaw_joint:
            lo, hi = m.joints[self.yaw_joint].range
            if lo <= bearing <= hi:
                self.inner = Interpolate(None, [(0.5, {self.yaw_joint: bearing}, "min_jerk")])
                self.inner.bind(ctx)
        if self.inner is None:
            self.inner = Face(ctx, TargetArgs(target=self.args.target))
        self.claims = self.inner.claims
        self.inner.begin(ctx)

    def tick(self, ctx: Ctx) -> None:
        if self.done:
            return
        self.inner.tick(ctx)
        if self.inner.done:
            self.report(ctx, True, f"looking at {self.args.target}")
            self.finish(ctx)


class PushArgs(_Args):
    object: str = Field(description="name of a seen object to push")
    to: Target = Field(description="a seen area/object (e.g. 'green_goal') or [x, y]")
    speed: float | None = Field(None, gt=0)


@skill("push", "Push a seen object to a seen area or point: walks around behind it, lines up and shoves it "
       "along. Keeps track of the object even when it's too close to see.", PushArgs, can_move)
class Push(MovingSkill):
    name = "push"
    timeout = 150.0

    def setup(self, ctx: Ctx) -> None:
        self.state_name = "approach"
        self.waypoints: list[np.ndarray] = []
        self.attempts = 0
        self.front = ctx.kin.front_reach()
        self.backoff_from: np.ndarray | None = None
        self._plan_approach(ctx)

    def _object(self, ctx: Ctx) -> tuple[np.ndarray, float, bool]:
        sense = self.sense(ctx)
        det = sense.resolve(self.args.object)
        visible = det.name in sense.visible
        return np.asarray(det.position, dtype=float), det.size_m / 2, visible

    def _goal(self, ctx: Ctx) -> tuple[np.ndarray, float]:
        goal, det = self.locate(ctx, self.args.to)
        tol = 0.15
        if det is not None and det.half_extent:
            tol = max(0.08, min(det.half_extent) - 0.03)
        return goal, tol

    def _plan_approach(self, ctx: Ctx) -> None:
        p, r, _ = self._object(ctx)
        g, _ = self._goal(ctx)
        u = (g - p) / max(np.linalg.norm(g - p), 1e-6)
        stand = r + self.front + 0.07
        approach = p - u * stand
        robot = ctx.state.base_pos[:2]
        rel = robot - p
        self.waypoints = []
        if np.linalg.norm(rel) > 1e-6 and float((rel / np.linalg.norm(rel)) @ -u) < 0.6:
            side = np.sign(u[0] * rel[1] - u[1] * rel[0]) or 1.0
            normal = np.array([-u[1], u[0]]) * side
            clear = r + self.front + 0.2
            self.waypoints.append(p + normal * clear - u * clear * 0.5)
        self.waypoints.append(approach)
        self.state_name = "approach"
        self.t_state = ctx.t

    def control(self, ctx: Ctx):
        st = ctx.state
        robot = st.base_pos[:2]
        p, r, visible = self._object(ctx)
        g, tol = self._goal(ctx)
        if float(np.linalg.norm(p - g)) <= tol and self.state_name != "verify":
            self.state_name, self.backoff_from = "verify", robot.copy()
        if self.state_name == "approach":
            target = self.waypoints[0]
            vx, vy, heading, dist = self.nav(ctx, target, self.mover.speed)
            if dist < 0.06:
                self.waypoints.pop(0)
                self.best = np.inf
                if not self.waypoints:
                    self.state_name, self.t_state = "align", ctx.t
                return 0.0, 0.0, heading
            if self.stuck(ctx, dist, window=6.0):
                return False, f"couldn't get behind {self.args.object}", {}
            return vx, vy, heading
        line = float(np.arctan2(*(g - p)[::-1]))
        if self.state_name == "align":
            if abs(wrap(line - st.yaw)) < np.radians(8) or ctx.t - self.t_state > 10:
                self.state_name, self.t_state = "push", ctx.t
                self.best = np.inf
            return 0.0, 0.0, line
        if self.state_name == "push":
            fwd = np.array([np.cos(st.yaw), np.sin(st.yaw)])
            rel = p - robot
            ahead = float(rel @ fwd)
            lateral = float(rel @ np.array([-fwd[1], fwd[0]]))
            if not visible and ahead < self.front + r + 0.12:
                # Too close to see: assume the object rides in front of the robot.
                p = robot + fwd * (self.front + r)
                self.sense(ctx).memory[self.sense(ctx).resolve(self.args.object).name].position = p.tolist()
            elif abs(lateral) > r + 0.08 or ahead < 0:
                self.attempts += 1
                if self.attempts > 5:
                    return False, f"{self.args.object} keeps slipping away", {}
                self._plan_approach(ctx)
                return 0.0, 0.0, None
            u = (g - p) / max(np.linalg.norm(g - p), 1e-6)
            rp = robot - p
            offset = float(u[0] * rp[1] - u[1] * rp[0])  # robot's signed distance from the push line
            heading = line - float(np.clip(2.0 * offset, -0.5, 0.5))
            to_go = float(np.linalg.norm(p - g))
            if self.stuck(ctx, to_go, window=8.0):
                return False, f"pushing made no progress ({to_go:.2f} m to go)", {}
            # Dribble: push gently, and slower still near the goal so the object doesn't overshoot.
            return self.mover.speed * float(np.clip(to_go / 0.6, 0.3, 0.55)), 0.0, heading
        # verify: back off until the object is visible again, then check it really is in place
        backed = float(np.linalg.norm(robot - self.backoff_from))
        if not visible and backed < 0.7:
            return -self.mover.vback * 0.7, 0.0, st.yaw
        if visible and float(np.linalg.norm(p - g)) <= tol:
            return True, f"pushed {self.args.object} to {self.args.to}", {"error_m": round(float(np.linalg.norm(p - g)), 2)}
        if not visible:
            return False, f"lost sight of {self.args.object} (try look_around)", {}
        self.attempts += 1
        self._plan_approach(ctx)
        return 0.0, 0.0, None


class PlayArgs(_Args):
    motion: str = Field(description="name of a saved motion (see the motion list)")


def motion_dir(robot: str) -> Path:
    return paths.LIBRARY_DIR / "motions" / robot


def list_motions(robot: str) -> list[dict[str, str]]:
    d = motion_dir(robot)
    out = []
    for f in sorted(d.glob("*.yaml")) if d.exists() else []:
        data = yaml.safe_load(f.read_text()) or {}
        out.append({"name": f.stem, "description": data.get("description") or ""})
    return out


@skill("play", "Play a saved RoboLang motion (a dance, a wave, a nod...). See list_motions.", PlayArgs,
       lambda m: bool(list_motions(m.robot)))
class Play(Skill):
    name = "play"

    def start(self, ctx: Ctx) -> None:
        f = motion_dir(ctx.manifest.robot) / f"{self.args.motion}.yaml"
        if not f.exists():
            names = [x["name"] for x in list_motions(ctx.manifest.robot)]
            self.report(ctx, False, f"no saved motion '{self.args.motion}'. Saved: {names}")
            self.finish(ctx)
            return
        program = schema.parse_program(f.read_text())
        self.inner = Sequence(None, [lambda s=s: build(s, ctx) for s in program.do])
        self.inner.begin(ctx)

    def tick(self, ctx: Ctx) -> None:
        if self.done:
            return
        self.inner.tick(ctx)
        if self.inner.done:
            self.report(ctx, True, f"played {self.args.motion}")
            self.finish(ctx)

    def request_stop(self, ctx: Ctx) -> None:
        if not self.done:
            self.inner.request_stop(ctx)
