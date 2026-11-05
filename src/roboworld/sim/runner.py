"""Run RoboLang programs in MuJoCo and record everything about the run.

``Simulation.execute`` runs one program from the robot's *current* state, so an
episode can chain many programs/skills (one per brain tool call).
``Simulation.run`` is the one-shot version: reset, execute, save a run folder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import mujoco
import numpy as np
import yaml

from roboworld import store
from roboworld.lang.ik import Kinematics
from roboworld.lang.interpreter import Interpreter
from roboworld.lang.schema import Program, parse_program
from roboworld.robots import ensure_available, load_manifest
from roboworld.sim.metrics import Metrics
from roboworld.sim.recorder import Recorder
from roboworld.sim.render import Camera, contact_sheet, save_png
from roboworld.sim.scene import build_scene, place_on_ground, set_joint_positions
from roboworld.sim.servo import ServoLayer
from roboworld.sim.state import RobotState, StateReader
from roboworld.world.spec import WorldSpec

TickHook = Callable[[RobotState], "str | None"]


@dataclass
class RunResult:
    run_id: str
    robot: str
    status: str  # completed | fell | timeout
    metrics: dict[str, Any]
    events: list[dict[str, Any]]
    run_dir: Path
    snapshots: list[Path] = field(default_factory=list)
    contact_sheet: Path | None = None
    program_name: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "robot": self.robot,
            "status": self.status,
            "program_name": self.program_name,
            "metrics": self.metrics,
            "events": self.events,
            "recording": str(self.run_dir / "recording.rrd"),
            "view_with": f"rw view {self.run_id}",
        }


@dataclass
class ExecResult:
    status: str  # completed | fell | timeout | stopped
    reason: str | None
    t_start: float
    t_end: float
    events: list[dict[str, Any]]
    results: list[dict[str, Any]]  # skill outcomes, in order


class Simulation:
    """One robot (optionally in a world), driven at ``control_hz`` by the RoboLang interpreter."""

    def __init__(self, robot: str, world: WorldSpec | None = None, control_hz: float = 50.0):
        ensure_available(robot)
        self.robot = robot
        self.world = world
        self.manifest = load_manifest(robot)
        self.model = build_scene(robot, world)
        self.data = mujoco.MjData(self.model)
        self.servo = ServoLayer(self.model, self.manifest)
        self.reader = StateReader(self.model, self.manifest, self.servo)
        self.kin = Kinematics(robot, self.manifest)
        self.substeps = max(1, int(round(1.0 / (control_hz * self.model.opt.timestep))))
        self.dt = self.substeps * self.model.opt.timestep
        self.targets = self.default_targets()
        self.t_origin = 0.0
        self.start_height = 0.0

    def default_targets(self) -> np.ndarray:
        pose = self.manifest.pose(self.manifest.default_pose)
        return np.array([pose.get(j, 0.0) for j in self.manifest.joints])

    def reset(self, settle: float = 0.6) -> RobotState:
        mujoco.mj_resetData(self.model, self.data)
        self.targets = self.default_targets()
        set_joint_positions(self.model, self.data, self.manifest,
                            dict(zip(self.manifest.joints, self.targets, strict=True)))
        start = self.world.robot_start if self.world else None
        xy = tuple(start.pos) if start else (0.0, 0.0)
        yaw = np.radians(start.yaw_deg) if start else 0.0
        place_on_ground(self.model, self.data, self.manifest, xy=xy, yaw=yaw)
        for _ in range(int(settle / self.dt)):
            self.step(self.targets)
        self.t_origin = float(self.data.time)
        st = self.state()
        self.start_height = float(st.base_pos[2])
        return st

    def step(self, targets: np.ndarray) -> None:
        for _ in range(self.substeps):
            self.servo.apply(self.data, targets)
            mujoco.mj_step(self.model, self.data)

    def state(self) -> RobotState:
        st = self.reader.read(self.data)
        st.t -= self.t_origin
        return st

    def is_fallen(self, st: RobotState) -> bool:
        if not self.manifest.floating_base:
            return False
        return bool(st.up_z < 0.5 or st.base_pos[2] < 0.45 * self.start_height)

    # -------------------------------------------------------------- execute
    def execute(
        self,
        program: Program,
        *,
        max_seconds: float,
        sense: Any = None,
        on_tick: TickHook | None = None,
        metrics: Metrics | None = None,
        recorder: Recorder | None = None,
        realtime: Callable[[float], None] | None = None,
    ) -> ExecResult:
        """Run ``program`` from the current state until it ends, the robot falls,
        ``max_seconds`` pass, or ``on_tick`` returns a stop reason."""
        interp = Interpreter(self.manifest, self.kin, program, self.dt)
        interp.ctx.sense = sense
        st = self.state()
        t0 = st.t
        interp.start(st, self.targets)
        status, reason = "timeout", None
        logged = 0
        while st.t - t0 < max_seconds:
            self.targets = interp.tick(st.t, st)
            self.step(self.targets)
            st = self.state()
            if metrics:
                metrics.update(st, self.targets, self.dt)
            if recorder:
                recorder.frame(self.data, st, self.targets)
                for ev in interp.events[logged:]:
                    recorder.event(ev.t, f"[{ev.kind}] {ev.text}", "WARN" if ev.kind in ("abort", "warning") else "INFO")
                logged = len(interp.events)
            if realtime:
                realtime(st.t)
            if self.is_fallen(st):
                if metrics:
                    metrics.mark_fall(st.t)
                interp.ctx.t = st.t
                interp.ctx.event("fall", f"robot fell (tilt {np.degrees(np.arccos(np.clip(st.up_z, -1, 1))):.0f}°)")
                if program.on_fall == "stop":
                    interp.abort("fell")
                    status, reason = "fell", "the robot fell over"
                    break
            stop = on_tick(st) if on_tick else None
            if stop:
                interp.abort(stop)
                status, reason = "stopped", stop
                break
            if interp.done:
                status = "completed"
                break
        if recorder:
            for ev in interp.events[logged:]:
                recorder.event(ev.t, f"[{ev.kind}] {ev.text}", "WARN" if ev.kind in ("abort", "warning") else "INFO")
        return ExecResult(status, reason, t0, st.t, [e.as_dict() for e in interp.events], interp.ctx.results)

    def hold(self, seconds: float, on_tick: TickHook | None = None, metrics: Metrics | None = None,
             recorder: Recorder | None = None, realtime: Callable[[float], None] | None = None) -> str | None:
        """Stand still (keep current targets) for ``seconds``; returns a stop reason if one fired."""
        st = self.state()
        t_end = st.t + seconds
        while st.t < t_end:
            self.step(self.targets)
            st = self.state()
            if metrics:
                metrics.update(st, self.targets, self.dt)
            if recorder:
                recorder.frame(self.data, st, self.targets)
            if realtime:
                realtime(st.t)
            stop = on_tick(st) if on_tick else None
            if stop:
                return stop
        return None

    # ------------------------------------------------------------------ run
    def run(
        self,
        program: Program | str | dict,
        max_seconds: float = 60.0,
        record: bool = True,
        snapshots: int = 4,
        save: bool = True,
    ) -> RunResult:
        """Reset, run a program and save a run folder. ``save=False`` keeps nothing on disk."""
        if not isinstance(program, Program):
            program = parse_program(program)
        tmp = None
        if save:
            run_id, run_dir = store.new_run_dir(self.robot)
        else:
            import tempfile

            tmp = tempfile.TemporaryDirectory()
            run_id, run_dir = "unsaved", Path(tmp.name)
            record, snapshots = False, 0
        program_yaml = yaml.safe_dump(program.model_dump(exclude_none=True), sort_keys=False)
        (run_dir / "program.yaml").write_text(program_yaml)
        self.reset()
        metrics = Metrics(self.manifest, self.servo.force_limit)
        recorder = Recorder(self.model, self.manifest, run_dir / "recording.rrd", run_id) if record else None
        if recorder:
            recorder.text("program", f"```yaml\n{program_yaml}```")
        camera = Camera(self.model, self.data, self.manifest) if snapshots else None
        frames: list[tuple[float, np.ndarray]] = []
        traj_t: list[float] = []
        traj_q: list[np.ndarray] = []

        def on_tick(st: RobotState) -> None:
            traj_t.append(st.t)
            traj_q.append(self.data.qpos.copy())
            if camera and (not frames or st.t - frames[-1][0] >= 0.5):
                frames.append((st.t, camera.render(self.data)))

        out = self.execute(program, max_seconds=max_seconds, on_tick=on_tick, metrics=metrics, recorder=recorder)
        status = out.status
        # A short tail so recordings show the robot settling (or finishing its fall).
        self.hold(1.0 if status == "fell" else 0.5, on_tick=on_tick, metrics=metrics, recorder=recorder)
        if status == "completed" and metrics.fell_at is not None:
            status = "fell"

        result = RunResult(run_id, self.robot, status, metrics.result(), out.events, run_dir,
                           program_name=program.name)
        if camera:
            picks = self._pick_frames(frames, snapshots)
            for t, img in picks:
                result.snapshots.append(save_png(img, run_dir / "snapshots" / f"t{t:06.2f}.png"))
            if picks:
                sheet = contact_sheet([img for _, img in picks], [f"t={t:.1f}s" for t, _ in picks])
                result.contact_sheet = save_png(sheet, run_dir / "contact_sheet.png")
            camera.close()
        if recorder:
            recorder.close()
        if tmp is not None:
            tmp.cleanup()
            return result
        np.savez_compressed(run_dir / "trajectory.npz", t=np.array(traj_t), qpos=np.array(traj_q),
                            joint_names=np.array(list(self.manifest.joints)))
        (run_dir / "result.json").write_text(json.dumps(result.summary(), indent=2))
        return result

    @staticmethod
    def _pick_frames(frames: list[tuple[float, np.ndarray]], n: int) -> list[tuple[float, np.ndarray]]:
        if len(frames) <= n:
            return frames
        idx = np.linspace(0, len(frames) - 1, n).round().astype(int)
        return [frames[i] for i in idx]


def run_program(robot: str, program: Program | str | dict, **kwargs: Any) -> RunResult:
    return Simulation(robot).run(program, **kwargs)
