"""An episode: one robot, one task, one brain, driven one tool call at a time.

The episode owns the simulation, perception, task scoring and recording. The
brain (any MCP client) only gets what a real robot would have: its senses,
its skills, and a clock. Success is judged here from ground truth, never by the
brain's own claim.

Timing modes:
    paused    the world waits while the brain thinks (tests pure reasoning)
    realtime  thinking time passes in the world: before each tool call the sim
              catches up by the wall-clock time since the previous call ended,
              with the robot holding still. Slow brains lose time, rolling
              balls keep rolling.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import mujoco
import numpy as np
import rerun as rr

from roboworld import store
from roboworld.lang.schema import Program, SkillStep
from roboworld.lang.skills import available_skills, check_skill, list_motions
from roboworld.lang.validate import check_source
from roboworld.sim.metrics import Metrics
from roboworld.sim.perception import Perception
from roboworld.sim.recorder import Recorder
from roboworld.sim.render import jpeg_bytes, png_bytes, save_png
from roboworld.sim.runner import Simulation
from roboworld.sim.scene import CAMERA_NAME
from roboworld.sim.state import RobotState
from roboworld.world.spec import Predicate, TaskSpec, load_task


class Episode:
    def __init__(self, robot: str, task: TaskSpec | str, mode: str = "paused", seed: int = 0,
                 run_id: str | None = None, brain: str | None = None, record: bool = True):
        if mode not in ("paused", "realtime"):
            raise ValueError("mode must be 'paused' or 'realtime'")
        self.task = load_task(task) if isinstance(task, str) else task
        self.world = self.task.resolved_world().resolved(seed)  # random placements for this seed
        self.robot = robot
        self.mode = mode
        self.seed = seed
        self.brain = brain or "unknown"
        self.sim = Simulation(robot, self.world)
        self.manifest = self.sim.manifest
        self.sim.reset()
        self.perception = Perception(self.sim.model, self.world, self.manifest, seed=seed)
        self.metrics = Metrics(self.manifest, self.sim.servo.force_limit)
        if run_id:
            self.run_id, self.run_dir = run_id, store.RUNS_DIR_for(run_id)
        else:
            self.run_id, self.run_dir = store.new_run_dir(f"{robot}-{self.task.name}")
        self.recorder = Recorder(self.sim.model, self.manifest, self.run_dir / "recording.rrd", self.run_id) \
            if record else None
        if self.recorder:
            self.recorder.text("task", f"**{self.task.name}** ({self.mode})\n\n{self.task.instruction}")
        cam = self.manifest.camera
        self.eye = mujoco.Renderer(self.sim.model, cam.height, cam.width) if cam else None
        self.transcript: list[dict[str, Any]] = []
        self.success_t: float | None = None
        self.ended_by: str | None = None
        self.brain_summary: str | None = None
        self.invalid_calls = 0
        self.think_time = 0.0
        self.last_call_end: float | None = None
        self.wall_start = time.time()
        self._tick = 0
        self._last_eye_t = -1e9
        self.last_result: dict[str, Any] | None = None
        self.perception.update(self.sim.data, self.sim.state().t)
        self.answer: str | None = None
        self.claimed_success: bool | None = None
        self._seq: dict[int, int] = {}
        self._d0: dict[int, float] = {}
        self._progress(self.task.success)  # record starting distances
        self._write_result()

    # ------------------------------------------------------------- scoring
    def _obj(self, name: str) -> np.ndarray:
        return self.perception.true_position(self.sim.data, name)

    def _in_region(self, p: np.ndarray, region: str) -> float:
        """Distance (m) from p to the region rectangle; 0 when inside."""
        obj = self.world.object(region)
        c = self._obj(region)[:2]
        yaw = np.radians(obj.yaw)
        rel = np.array([[np.cos(yaw), np.sin(yaw)], [-np.sin(yaw), np.cos(yaw)]]) @ (p[:2] - c)
        outside = np.maximum(np.abs(rel) - np.asarray(obj.size[:2]), 0.0)
        return float(np.linalg.norm(outside))

    def _distance(self, pred: Predicate) -> float:
        """How far (m) the world is from satisfying the predicate (0 = satisfied)."""
        st_pos = self.sim.data.xpos[self.sim.reader.base][:2]
        if pred.object_in_region is not None:
            return self._in_region(self._obj(pred.object_in_region["object"]), pred.object_in_region["region"])
        if pred.robot_in_region is not None:
            return self._in_region(st_pos, pred.robot_in_region)
        if pred.robot_near is not None:
            d = float(np.linalg.norm(self._obj(pred.robot_near["object"])[:2] - st_pos))
            return max(0.0, d - float(pred.robot_near.get("distance", 0.5)))
        if pred.answer is not None:
            return 0.0 if self._answer_ok(pred.answer) else np.inf
        if pred.all is not None:
            return max(self._distance(p) for p in pred.all)
        if pred.any is not None:
            return min(self._distance(p) for p in pred.any)
        if pred.sequence is not None:
            # Steps latch: once step k has happened, only steps after it matter.
            k = self._seq.get(id(pred), 0)
            while k < len(pred.sequence) and self._distance(pred.sequence[k]) <= 0.0:
                k += 1
            self._seq[id(pred)] = k
            return 0.0 if k == len(pred.sequence) else self._distance(pred.sequence[k]) + 1e-3
        return np.inf

    @staticmethod
    def _norm_answer(text: str) -> str:
        words = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                 "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}
        t = text.strip().lower().strip(".!?\"' ")
        return words.get(t, t)

    def _answer_ok(self, expected: str | list[str]) -> bool:
        if self.answer is None:
            return False
        options = [expected] if isinstance(expected, str) else expected
        return self._norm_answer(self.answer) in {self._norm_answer(o) for o in options}

    def _progress(self, pred: Predicate) -> float:
        """0..1: how much of the predicate is done (used for partial credit)."""
        if pred.all is not None:
            return float(np.mean([self._progress(p) for p in pred.all]))
        if pred.any is not None:
            return max(self._progress(p) for p in pred.any)
        if pred.sequence is not None:
            self._distance(pred)
            k = self._seq.get(id(pred), 0)
            n = len(pred.sequence)
            return 1.0 if k >= n else (k + self._progress(pred.sequence[k])) / n
        if pred.answer is not None:
            return 1.0 if self._answer_ok(pred.answer) else 0.0
        d = self._distance(pred)
        d0 = self._d0.setdefault(id(pred), max(d, 1e-6))
        return float(np.clip(1.0 - d / d0, 0.0, 1.0))

    @property
    def success(self) -> bool:
        return self.success_t is not None

    @property
    def over(self) -> bool:
        return self.ended_by is not None

    def progress(self) -> float:
        return 1.0 if self.success else self._progress(self.task.success)

    # ---------------------------------------------------------- sim hooks
    EYE_HZ = 5.0  # camera frames recorded for replay (what the robot saw, not only what the brain asked for)

    def _record_eye(self, st: RobotState) -> None:
        if not (self.recorder and self.eye is not None):
            return
        if st.t - self._last_eye_t < 1.0 / self.EYE_HZ - 1e-6:
            return
        self._last_eye_t = st.t
        self.eye.update_scene(self.sim.data, camera=CAMERA_NAME)
        jpg = jpeg_bytes(self.eye.render())
        self.recorder.rec.set_time("sim", duration=st.t)
        self.recorder.rec.log("robot/eye", rr.EncodedImage(contents=jpg, media_type="image/jpeg"))

    def _on_tick(self, st: RobotState) -> str | None:
        self._tick += 1
        if self._tick % 5 == 0:
            self.perception.update(self.sim.data, st.t)
        self._record_eye(st)
        if self.task.fail_if is not None and self._distance(self.task.fail_if) <= 0.0:
            self.ended_by = "failed"
            if self.recorder:
                self.recorder.event(st.t, "TASK FAILED (constraint broken)", "WARN")
            return "task failed: a rule of the task was broken"
        if self.success_t is None and self._distance(self.task.success) <= 0.0:
            self.success_t = st.t
            self.ended_by = "success"
            if self.recorder:
                self.recorder.event(st.t, "TASK COMPLETE", "INFO")
            return "task complete"
        if st.t >= self.task.time_limit_s:
            self.ended_by = self.ended_by or "time_limit"
            return "time limit reached"
        if self.sim.is_fallen(st):
            self.ended_by = self.ended_by or "fell"
            return "the robot fell over"
        return None

    def _catch_up(self) -> None:
        """Realtime mode: the world kept going while the brain was thinking."""
        now = time.time()
        if self.last_call_end is not None:
            gap = now - self.last_call_end
            self.think_time += gap
            if self.mode == "realtime" and not self.over and gap > 0:
                self.sim.hold(gap, on_tick=self._on_tick, metrics=self.metrics, recorder=self.recorder)

    def _begin(self, tool: str, args: dict[str, Any]) -> float:
        self._catch_up()
        t = self.sim.state().t
        if self.recorder:
            self.recorder.event(t, f"brain → {tool}({json.dumps(args, default=str)[:300]})", "INFO")
        return t

    def _end(self, tool: str, args: dict[str, Any], t0: float, result: dict[str, Any], ok: bool = True) -> dict:
        st = self.sim.state()
        result = {**result, "episode": self.status_brief(st)}
        self.transcript.append({"i": len(self.transcript), "tool": tool, "args": args, "ok": ok,
                                "sim_t0": round(t0, 2), "sim_t1": round(st.t, 2),
                                "wall": round(time.time() - self.wall_start, 2), "result": result})
        if not ok:
            self.invalid_calls += 1
        self.last_call_end = time.time()
        self._write_result()
        return result

    # --------------------------------------------------------------- views
    def robot_state(self, st: RobotState) -> dict[str, Any]:
        tilt = float(np.degrees(np.arccos(np.clip(st.up_z, -1, 1))))
        return {"x": round(float(st.base_pos[0]), 2), "y": round(float(st.base_pos[1]), 2),
                "heading_deg": round(float(np.degrees(st.yaw))), "tilt_deg": round(tilt, 1),
                "fallen": self.sim.is_fallen(st)}

    def status_brief(self, st: RobotState | None = None) -> dict[str, Any]:
        st = st or self.sim.state()
        return {"time_s": round(st.t, 1), "time_left_s": round(max(0.0, self.task.time_limit_s - st.t), 1),
                "over": self.over, "ended_by": self.ended_by}

    # --------------------------------------------------------------- tools
    def observe(self) -> dict[str, Any]:
        t0 = self._begin("observe", {})
        st = self.sim.state()
        self.perception.update(self.sim.data, st.t)
        out = {
            "task": self.task.instruction,
            "robot": self.robot_state(st),
            "objects_seen": self.perception.known_objects(st),
            "last_action": self.last_result,
            "frame": "world metres; x was forward at the start, y to the left; heading in degrees, counter-clockwise",
        }
        return self._end("observe", {}, t0, out)

    def look(self) -> tuple[bytes | None, dict[str, Any]]:
        t0 = self._begin("look", {})
        st = self.sim.state()
        if self.eye is None:
            return None, self._end("look", {}, t0, {"error": "this robot has no camera"}, ok=False)
        self.eye.update_scene(self.sim.data, camera=CAMERA_NAME)
        img = self.eye.render().copy()
        seen = self.perception.update(self.sim.data, st.t)
        if self.recorder:
            # What the brain actually looked at, kept apart from the continuous robot/eye stream.
            self.recorder.rec.set_time("sim", duration=st.t)
            self.recorder.rec.log("brain/look", rr.EncodedImage(contents=jpeg_bytes(img), media_type="image/jpeg"))
        save_png(img, self.run_dir / "eye" / f"t{st.t:06.2f}.png")
        visible = [d.describe(st, True) for d in seen]
        return png_bytes(img), self._end("look", {}, t0, {"visible_objects": visible,
                                                          "robot": self.robot_state(st)})

    def skills(self) -> dict[str, Any]:
        t0 = self._begin("skills", {})
        out = {"skills": available_skills(self.manifest), "saved_motions": list_motions(self.robot),
               "tip": "Skills report ok/failed with a message. Objects must be seen before you can walk_to/push them."}
        return self._end("skills", {}, t0, out)

    def _execute(self, program: Program, tool: str, args: dict[str, Any], t0: float) -> dict[str, Any]:
        if self.over:
            return self._end(tool, args, t0, {"ok": False, "message": f"episode is over ({self.ended_by})"}, ok=False)
        remaining = self.task.time_limit_s - self.sim.state().t + 0.05
        out = self.sim.execute(program, max_seconds=remaining, sense=self.perception, on_tick=self._on_tick,
                               metrics=self.metrics, recorder=self.recorder)
        if out.status == "fell":
            self.ended_by = self.ended_by or "fell"  # a fallen robot can't carry on (no get-up skill yet)
        st = self.sim.state()
        self.perception.update(self.sim.data, st.t)
        results = out.results
        if out.status == "stopped" and self.ended_by == "success":
            message = "task complete!"
        elif out.reason:
            message = out.reason
        elif results:
            message = results[-1]["message"]
        else:
            message = out.status
        ok = (results[-1]["ok"] if results else out.status == "completed") and out.status != "fell"
        result = {"ok": bool(ok or self.success), "message": message, "robot": self.robot_state(st)}
        if len(results) == 1:
            result.update({k: v for k, v in results[0].items() if k not in ("ok", "message", "robot")})
        elif results:
            result["skill_results"] = results
        warnings = [e["text"] for e in out.events
                    if e["kind"] == "warning" or (e["kind"] == "abort" and e["text"] != "task complete")]
        if warnings:
            result["warnings"] = warnings
        self.last_result = {"tool": tool, "args": args, "ok": result["ok"], "message": message}
        return self._end(tool, args, t0, result)

    def do(self, skill: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        t0 = self._begin("do", {"skill": skill, "args": args})
        try:
            check_skill(skill, args, self.manifest)
        except ValueError as e:
            return self._end("do", {"skill": skill, "args": args}, t0, {"ok": False, "error": str(e)}, ok=False)
        program = Program(do=[SkillStep(skill=skill, args=args)])
        return self._execute(program, "do", {"skill": skill, "args": args}, t0)

    def run(self, program: str) -> dict[str, Any]:
        t0 = self._begin("run", {"program": program[:2000]})
        parsed, report = check_source(program, self.manifest)
        if parsed is None or not report.ok:
            return self._end("run", {"program": program[:2000]}, t0,
                             {"ok": False, "errors": report.errors, "warnings": report.warnings}, ok=False)
        return self._execute(parsed, "run", {"program": program[:2000]}, t0)

    def status(self) -> dict[str, Any]:
        t0 = self._begin("status", {})
        return self._end("status", {}, t0, {"task": self.task.instruction, "robot": self.robot, "mode": self.mode,
                                            "time_limit_s": self.task.time_limit_s, "success": self.success,
                                            "tool_calls_so_far": len(self.transcript)})

    def finish(self, summary: str = "", success: bool | None = None, answer: str | None = None) -> dict[str, Any]:
        args = {"summary": summary, "success": success, "answer": answer}
        t0 = self._begin("finish", args)
        self.brain_summary = summary
        self.claimed_success = success
        if answer is not None:
            self.answer = str(answer)
            if self.success_t is None and not self.over and self._distance(self.task.success) <= 0.0:
                self.success_t = self.sim.state().t
                self.ended_by = "success"
        if not self.over:
            self.ended_by = "brain_finished"
        out = self._end("finish", args, t0, {"success": self.success,
                                             "message": "episode closed; results recorded"})
        self.close()
        return out

    # -------------------------------------------------------------- results
    def result(self) -> dict[str, Any]:
        st = self.sim.state()
        skills_used: dict[str, int] = {}
        for c in self.transcript:
            if c["tool"] == "do":
                name = c["args"].get("skill", "?")
                skills_used[name] = skills_used.get(name, 0) + 1
        calls = len(self.transcript)
        return {
            "run_id": self.run_id,
            "kind": "episode",
            "robot": self.robot,
            "task": self.task.name,
            "instruction": self.task.instruction,
            "mode": self.mode,
            "seed": self.seed,
            "brain": self.brain,
            "status": "success" if self.success else (self.ended_by or "in_progress"),
            "success": self.success,
            "success_time_s": None if self.success_t is None else round(self.success_t, 2),
            "ended_by": self.ended_by or "in_progress",
            "progress": round(self.progress(), 3),
            "sim_time_s": round(st.t, 2),
            "wall_time_s": round(time.time() - self.wall_start, 2),
            "brain_stats": {"tool_calls": calls, "invalid_calls": self.invalid_calls, "skills_used": skills_used,
                            "think_time_s": round(self.think_time, 2),
                            "mean_think_s": round(self.think_time / max(calls - 1, 1), 2),
                            "summary": self.brain_summary,
                            "claimed_success": self.claimed_success,
                            "overclaimed": bool(self.claimed_success) and not self.success,
                            "answer": self.answer},
            "metrics": self.metrics.result(),
            "recording": str(self.run_dir / "recording.rrd"),
            "view_with": f"rw view {self.run_id}",
        }

    def _write_result(self) -> None:
        (self.run_dir / "result.json").write_text(json.dumps(self.result(), indent=2, default=str))
        with (self.run_dir / "transcript.jsonl").open("w") as f:
            for row in self.transcript:
                f.write(json.dumps(row, default=str) + "\n")
        if self.recorder:
            self.recorder.rec.flush()

    def close(self) -> dict[str, Any]:
        if getattr(self, "_closed", False):
            return self.result()
        self._closed = True
        if not self.over:
            self.ended_by = "disconnected"
        self._write_result()
        if self.recorder:
            self.recorder.close()
        if self.eye is not None:
            self.eye.close()
        return self.result()


def episode_dir(run_id: str) -> Path:
    return store.RUNS_DIR_for(run_id)
