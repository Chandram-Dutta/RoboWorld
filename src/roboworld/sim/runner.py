"""Run RoboLang programs in MuJoCo and record everything about the run."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


class Simulation:
    """One robot on a flat floor, driven at ``control_hz`` by the RoboLang interpreter."""

    def __init__(self, robot: str, control_hz: float = 50.0):
        ensure_available(robot)
        self.robot = robot
        self.manifest = load_manifest(robot)
        self.model = build_scene(robot)
        self.data = mujoco.MjData(self.model)
        self.servo = ServoLayer(self.model, self.manifest)
        self.reader = StateReader(self.model, self.manifest, self.servo)
        self.kin = Kinematics(robot, self.manifest)
        self.substeps = max(1, int(round(1.0 / (control_hz * self.model.opt.timestep))))
        self.dt = self.substeps * self.model.opt.timestep

    def default_targets(self) -> np.ndarray:
        pose = self.manifest.pose(self.manifest.default_pose)
        return np.array([pose.get(j, 0.0) for j in self.manifest.joints])

    def reset(self, settle: float = 0.6) -> RobotState:
        mujoco.mj_resetData(self.model, self.data)
        targets = self.default_targets()
        set_joint_positions(self.model, self.data, self.manifest, dict(zip(self.manifest.joints, targets, strict=True)))
        place_on_ground(self.model, self.data, self.manifest)
        for _ in range(int(settle / self.dt)):
            self.step(targets)
        self.t_origin = float(self.data.time)
        return self.state()

    def step(self, targets: np.ndarray) -> None:
        for _ in range(self.substeps):
            self.servo.apply(self.data, targets)
            mujoco.mj_step(self.model, self.data)

    def state(self) -> RobotState:
        st = self.reader.read(self.data)
        st.t -= getattr(self, "t_origin", 0.0)
        return st

    def is_fallen(self, st: RobotState, start: RobotState) -> bool:
        if not self.manifest.floating_base:
            return False
        return st.up_z < 0.5 or st.base_pos[2] < 0.45 * start.base_pos[2]

    # ------------------------------------------------------------------ run
    def run(
        self,
        program: Program | str | dict,
        max_seconds: float = 60.0,
        record: bool = True,
        snapshots: int = 4,
        save: bool = True,
    ) -> RunResult:
        """Run a program. ``save=False`` keeps nothing on disk (for sweeps/optimisers)."""
        if not isinstance(program, Program):
            program = parse_program(program)
        if save:
            run_id, run_dir = store.new_run_dir(self.robot)
        else:
            import tempfile

            self._tmp = tempfile.TemporaryDirectory()
            run_id, run_dir = "unsaved", Path(self._tmp.name)
            record, snapshots = False, 0
        (run_dir / "program.yaml").write_text(
            yaml.safe_dump(program.model_dump(exclude_none=True, exclude_defaults=False), sort_keys=False)
        )
        start = self.reset()
        targets = self.default_targets()
        interp = Interpreter(self.manifest, self.kin, program, self.dt)
        metrics = Metrics(self.manifest, self.servo.force_limit)
        recorder = Recorder(self.model, self.manifest, run_dir / "recording.rrd", run_id) if record else None
        if recorder:
            recorder.text("program", f"```yaml\n{(run_dir / 'program.yaml').read_text()}```")
        camera = Camera(self.model, self.data, self.manifest) if snapshots else None
        frames: list[tuple[float, np.ndarray]] = []

        interp.start(start, targets)
        st = start
        status = "timeout"
        tail_until: float | None = None
        traj_t, traj_qpos = [], []
        logged = 0
        while st.t < max_seconds:
            targets = interp.tick(st.t, st)
            self.step(targets)
            st = self.state()
            metrics.update(st, targets, self.dt)
            traj_t.append(st.t)
            traj_qpos.append(self.data.qpos.copy())
            if recorder:
                recorder.frame(self.data, st, targets)
                for ev in interp.events[logged:]:
                    recorder.event(ev.t, f"[{ev.kind}] {ev.text}", "WARN" if ev.kind in ("abort", "warning") else "INFO")
                logged = len(interp.events)
            if camera and (not frames or st.t - frames[-1][0] >= 0.5):
                frames.append((st.t, camera.render(self.data)))
            if tail_until is None:
                if self.is_fallen(st, start):
                    metrics.mark_fall(st.t)
                    interp.ctx.t = st.t
                    interp.ctx.event("fall", f"robot fell (tilt {np.degrees(np.arccos(np.clip(st.up_z, -1, 1))):.0f}°)")
                    if program.on_fall == "stop":
                        interp.abort("fell")
                        status = "fell"
                        tail_until = st.t + 1.0
                elif interp.done:
                    status = "completed" if interp.aborted is None else status
                    tail_until = st.t + 0.5
            elif st.t >= tail_until:
                break
        if status == "completed" and metrics.fell_at is not None:
            status = "fell"

        events = [e.as_dict() for e in interp.events]
        result = RunResult(run_id, self.robot, status, metrics.result(), events, run_dir,
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
        if not save:
            self._tmp.cleanup()
            return result
        np.savez_compressed(run_dir / "trajectory.npz", t=np.array(traj_t), qpos=np.array(traj_qpos),
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
