"""RoboLang interpreter: runs a Program at the control rate and emits joint targets.

Every step compiles into an ``Action`` that claims a set of joints and writes
their targets each tick. Unclaimed joints keep their last target. After all
actions run, a safety layer clamps targets to joint limits and rate-limits them
to what the servos can physically do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from roboworld.lang import schema
from roboworld.lang.gaits import make_gait
from roboworld.lang.gaits.base import GaitController, min_jerk
from roboworld.lang.ik import Frame, Kinematics
from roboworld.lang.manifest import Manifest
from roboworld.sim.state import RobotState

EASE = {
    "linear": lambda s: float(np.clip(s, 0, 1)),
    "cubic": lambda s: (lambda c: c * c * (3 - 2 * c))(float(np.clip(s, 0, 1))),
    "min_jerk": min_jerk,
}


@dataclass
class Event:
    t: float
    kind: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"t": round(self.t, 3), "kind": self.kind, "text": self.text, **self.data}


@dataclass
class Ctx:
    manifest: Manifest
    kin: Kinematics
    dt: float
    targets: np.ndarray
    index: dict[str, int]
    t: float = 0.0
    state: RobotState | None = None
    events: list[Event] = field(default_factory=list)

    def event(self, kind: str, text: str, **data: Any) -> None:
        self.events.append(Event(self.t, kind, text, data))


# ===================================================================== actions
class Action:
    claims: set[int] = set()

    def __init__(self, label: str | None = None):
        self.label = label
        self.done = False
        self.started = False

    def begin(self, ctx: Ctx) -> None:
        self.started = True
        self.t0 = ctx.t
        if self.label:
            ctx.event("step_start", self.label)
        self.start(ctx)

    def finish(self, ctx: Ctx) -> None:
        if not self.done:
            self.done = True
            if self.label:
                ctx.event("step_end", self.label)

    def start(self, ctx: Ctx) -> None:
        pass

    def tick(self, ctx: Ctx) -> None:
        pass

    def request_stop(self, ctx: Ctx) -> None:
        self.finish(ctx)


def resolve_joint_map(manifest: Manifest, mapping: dict[str, float]) -> dict[str, float]:
    return {manifest.resolve_joint(k): float(v) for k, v in mapping.items()}


def resolve_pose(manifest: Manifest, pose: str | dict[str, float]) -> dict[str, float]:
    return dict(manifest.pose(pose)) if isinstance(pose, str) else resolve_joint_map(manifest, pose)


class Interpolate(Action):
    """Shared by pose / clip / reach: move claimed joints through keyframes."""

    def __init__(self, label: str | None, keys: list[tuple[float, dict[str, float], str]], repeat: int = 1,
                 relative: bool = False, hold: float = 0.0):
        super().__init__(label)
        self.keys = keys  # (duration, joint->value, ease)
        self.repeat = repeat
        self.relative = relative
        self.hold = hold
        self._names = sorted({j for _, values, _ in keys for j in values})

    def bind(self, ctx: Ctx) -> None:
        self.claims = {ctx.index[j] for j in self._names}

    def start(self, ctx: Ctx) -> None:
        self.idx = np.array([ctx.index[j] for j in self._names], dtype=int)
        start = ctx.targets[self.idx].copy()
        frames, prev = [start], start
        for _, values, _ in self.keys:
            nxt = prev.copy()
            for i, j in enumerate(self._names):
                if j in values:
                    nxt[i] = start[i] + values[j] if self.relative else values[j]
            frames.append(nxt)
            prev = nxt
        self.frames = frames
        self.durations = [d for d, _, _ in self.keys]
        self.eases = [EASE[e] for _, _, e in self.keys]
        self.cycle = sum(self.durations)

    def tick(self, ctx: Ctx) -> None:
        el = ctx.t - self.t0
        total = self.cycle * self.repeat
        if el >= total:
            ctx.targets[self.idx] = self.frames[-1]
            if el >= total + self.hold:
                self.finish(ctx)
            return
        rep, local = divmod(el, self.cycle)
        for k, d in enumerate(self.durations):
            if local < d or k == len(self.durations) - 1:
                a = self.frames[k] if (k > 0 or rep == 0) else self.frames[-1]
                b = self.frames[k + 1]
                ctx.targets[self.idx] = a + (b - a) * self.eases[k](local / d)
                return
            local -= d


class PoseAction(Interpolate):
    def __init__(self, step: schema.PoseStep, manifest: Manifest):
        values = resolve_pose(manifest, step.pose)
        super().__init__(step.label, [(step.duration, values, step.ease)], relative=step.relative, hold=step.hold)


class ClipAction(Interpolate):
    def __init__(self, step: schema.ClipStep, manifest: Manifest):
        keys = []
        for key in step.clip.keys:
            values = dict(manifest.pose(key.pose)) if key.pose else {}
            values.update(resolve_joint_map(manifest, key.joints))
            keys.append((key.t, values, key.ease or step.clip.ease))
        super().__init__(step.label, keys, repeat=step.clip.repeat, relative=step.clip.relative)


class ReachAction(Interpolate):
    def __init__(self, step: schema.ReachStep, manifest: Manifest):
        self.spec = step.reach
        ee = manifest.end_effectors.get(self.spec.effector)
        if ee is None:
            raise KeyError(f"Unknown end effector '{self.spec.effector}'. Known: {sorted(manifest.end_effectors)}")
        limb = manifest.limbs.get(ee.limb or "", list(manifest.joints))
        super().__init__(step.label, [(self.spec.duration, {j: 0.0 for j in limb}, self.spec.ease)])

    def start(self, ctx: Ctx) -> None:
        r = self.spec
        current = ctx.kin.fk(ctx.targets, [r.effector])[r.effector]
        pos = np.asarray(r.pos, dtype=float)
        st = ctx.state
        if r.frame == "world" and st is not None:
            # Frames are expressed in the base body's local frame.
            pos = st.base_rot.T @ pos if r.relative else st.base_rot.T @ (pos - st.base_pos)
        target = current.pos + pos if r.relative else pos
        q, err = ctx.kin.solve(ctx.targets, {r.effector: Frame(target, current.rot)}, iters=60)
        if err > 0.01:
            ctx.event("warning", f"reach target for {r.effector} is {err * 100:.1f} cm out of reach; going as close as possible")
        self.keys = [(r.duration, {j: float(q[ctx.index[j]]) for j in self._names}, r.ease)]
        super().start(ctx)


class WaitAction(Action):
    def __init__(self, step: schema.WaitStep):
        super().__init__(step.label)
        self.duration = step.wait

    def tick(self, ctx: Ctx) -> None:
        if self.duration is not None and ctx.t - self.t0 >= self.duration:
            self.finish(ctx)


class GaitAction(Action):
    def __init__(self, step: schema.GaitStep, ctx: Ctx):
        super().__init__(step.label)
        self.spec = step.gait
        self.duration = step.duration
        self.gait: GaitController = make_gait(ctx, step.gait)
        self.claims = set(self.gait.claims)

    def start(self, ctx: Ctx) -> None:
        self.gait.start(ctx)
        s = self.gait.settings
        ctx.event("gait_start", f"{self.spec.type} vx={s.vx} vy={s.vy} wz={s.wz} period={s.period}")

    def tick(self, ctx: Ctx) -> None:
        if self.duration is not None and ctx.t - self.t0 >= self.duration:
            self.gait.request_stop()
        self.gait.tick(ctx)
        if self.gait.done:
            self.finish(ctx)

    def request_stop(self, ctx: Ctx) -> None:
        self.gait.request_stop()  # graceful: finish the step, settle, then done


class Sequence(Action):
    def __init__(self, label: str | None, factories: list, times: int = 1):
        super().__init__(label)
        self.factories = factories
        self.times = times
        self.claims = set()

    def start(self, ctx: Ctx) -> None:
        self.i = 0
        self.rep = 0
        self.child: Action | None = None
        self.stopping = False

    def tick(self, ctx: Ctx) -> None:
        while not self.done:
            if self.child is None:
                if self.stopping or self.rep >= self.times:
                    self.finish(ctx)
                    return
                self.child = self.factories[self.i]()
                self.child.begin(ctx)
            self.child.tick(ctx)
            if not self.child.done:
                return
            self.child = None
            self.i += 1
            if self.i >= len(self.factories):
                self.i = 0
                self.rep += 1
            # Zero-duration children fall through to the next one in the same tick.

    def request_stop(self, ctx: Ctx) -> None:
        self.stopping = True
        if self.child is not None:
            self.child.request_stop(ctx)
        else:
            self.finish(ctx)


class Parallel(Action):
    def __init__(self, label: str | None, factories: list, race: bool):
        super().__init__(label)
        self.factories = factories
        self.race = race

    def start(self, ctx: Ctx) -> None:
        self.children = [f() for f in self.factories]
        for c in self.children:
            c.begin(ctx)
        self.stopping = False

    def tick(self, ctx: Ctx) -> None:
        for c in self.children:
            if not c.done:
                c.tick(ctx)
        if self.race and not self.stopping and any(c.done for c in self.children):
            self.request_stop(ctx)
        if all(c.done for c in self.children):
            self.finish(ctx)

    def request_stop(self, ctx: Ctx) -> None:
        self.stopping = True
        for c in self.children:
            if not c.done:
                c.request_stop(ctx)


PATH_SMOOTHING_S = 0.4  # low-pass the base position so gait sway doesn't count as distance


class Monitor:
    """Tracks odometry since a step started, for ``until`` conditions."""

    def __init__(self, ctx: Ctx):
        st = ctx.state
        self.t0 = ctx.t
        self.dt = ctx.dt
        self.start = st.base_pos[:2].copy() if st else np.zeros(2)
        self.last = self.start.copy()
        self.smooth = self.start.copy()
        self.path = 0.0
        self.yaw = st.yaw if st else 0.0
        self.turned = 0.0

    def update(self, ctx: Ctx) -> None:
        st = ctx.state
        if st is None:
            return
        alpha = min(1.0, self.dt / PATH_SMOOTHING_S)
        smooth = self.smooth + alpha * (st.base_pos[:2] - self.smooth)
        self.path += float(np.linalg.norm(smooth - self.smooth))
        self.smooth = smooth
        self.last = st.base_pos[:2].copy()
        self.turned += float((st.yaw - self.yaw + np.pi) % (2 * np.pi) - np.pi)
        self.yaw = st.yaw

    def check(self, c: schema.Condition, ctx: Ctx) -> bool:
        st = ctx.state
        if c.timeout is not None:
            return ctx.t - self.t0 >= c.timeout
        if c.distance_traveled is not None:
            return self.path >= c.distance_traveled
        if c.displacement is not None:
            return float(np.linalg.norm(self.last - self.start)) >= c.displacement
        if c.turned is not None:
            return abs(np.degrees(self.turned)) >= c.turned
        if c.fallen is not None:
            return (st is not None and st.up_z < 0.5) == c.fallen
        if c.reached is not None:
            tol = c.reached[2] if len(c.reached) > 2 else 0.1
            return float(np.linalg.norm(self.last - np.asarray(c.reached[:2]))) <= tol
        if c.any is not None:
            return any(self.check(x, ctx) for x in c.any)
        if c.all is not None:
            return all(self.check(x, ctx) for x in c.all)
        return False


class Until(Action):
    def __init__(self, inner: Action, cond: schema.Condition):
        super().__init__(None)
        self.inner = inner
        self.cond = cond
        self.claims = inner.claims

    def start(self, ctx: Ctx) -> None:
        self.monitor = Monitor(ctx)
        self.inner.begin(ctx)
        self.stop_t: float | None = None

    def tick(self, ctx: Ctx) -> None:
        self.monitor.update(ctx)
        if self.stop_t is None and self.monitor.check(self.cond, ctx):
            self.stop_t = ctx.t
            ctx.event("until", f"condition met: {self.cond.model_dump(exclude_none=True)}")
            self.inner.request_stop(ctx)
        if not self.inner.done:
            self.inner.tick(ctx)
        if self.inner.done or (self.stop_t is not None and ctx.t - self.stop_t > 3.0):
            self.finish(ctx)

    def request_stop(self, ctx: Ctx) -> None:
        self.inner.request_stop(ctx)
        if self.inner.done:
            self.finish(ctx)


# ===================================================================== builder
def build(step: Any, ctx: Ctx) -> Action:
    m = ctx.manifest
    if isinstance(step, schema.PoseStep):
        action: Action = PoseAction(step, m)
        action.bind(ctx)
    elif isinstance(step, schema.ClipStep):
        action = ClipAction(step, m)
        action.bind(ctx)
    elif isinstance(step, schema.ReachStep):
        action = ReachAction(step, m)
        action.bind(ctx)
    elif isinstance(step, schema.GaitStep):
        action = GaitAction(step, ctx)
    elif isinstance(step, schema.WaitStep):
        action = WaitAction(step)
    elif isinstance(step, schema.RepeatStep):
        action = Sequence(step.label, [lambda s=s: build(s, ctx) for s in step.repeat.do], step.repeat.times)
    elif isinstance(step, schema.BlockStep):
        action = Sequence(step.label, [lambda s=s: build(s, ctx) for s in step.do])
    elif isinstance(step, schema.ParallelStep):
        action = Parallel(step.label, [lambda s=s: build(s, ctx) for s in step.parallel], step.race)
    else:  # pragma: no cover
        raise TypeError(f"unknown step {type(step).__name__}")
    if getattr(step, "until", None) is not None:
        return Until(action, step.until)
    return action


class Interpreter:
    def __init__(self, manifest: Manifest, kin: Kinematics, program: schema.Program, dt: float):
        self.manifest = manifest
        self.program = program
        names = list(manifest.joints)
        index = {n: i for i, n in enumerate(names)}
        self.ctx = Ctx(manifest=manifest, kin=kin, dt=dt, targets=np.zeros(len(names)), index=index)
        self.lo = np.array([manifest.joints[n].range[0] for n in names])
        self.hi = np.array([manifest.joints[n].range[1] for n in names])
        self.vmax = manifest.max_joint_speed
        self.root: Action = Sequence(None, [lambda s=s: build(s, self.ctx) for s in program.do])
        self.out = np.zeros(len(names))
        self.aborted: str | None = None

    @property
    def done(self) -> bool:
        return self.root.done or self.aborted is not None

    @property
    def events(self) -> list[Event]:
        return self.ctx.events

    def start(self, state: RobotState, initial_targets: np.ndarray) -> None:
        self.ctx.t = 0.0
        self.ctx.state = state
        self.ctx.targets = initial_targets.copy()
        self.out = initial_targets.copy()
        self.root.begin(self.ctx)

    def tick(self, t: float, state: RobotState) -> np.ndarray:
        ctx = self.ctx
        ctx.t = t
        ctx.state = state
        if not self.done:
            self.root.tick(ctx)
        desired = np.clip(ctx.targets, self.lo, self.hi)
        step = self.vmax * ctx.dt
        self.out = self.out + np.clip(desired - self.out, -step, step)
        return self.out.copy()

    def abort(self, reason: str) -> None:
        if self.aborted is None:
            self.aborted = reason
            self.ctx.event("abort", reason)
