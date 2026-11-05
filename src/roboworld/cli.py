"""``rw``: the RoboWorld command line."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="RoboWorld: build robots, move them with RoboLang, test them in simulation.",
                  no_args_is_help=True, add_completion=False)


def _print(data) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


@app.command()
def robots() -> None:
    """List robots."""
    from roboworld import api

    for r in api.robots():
        mark = "✓" if r["available"] else "↓ (rw fetch)"
        typer.echo(f"{r['name']:<22} {r['kind']:<11} {mark}")


@app.command()
def fetch(robot: str, force: bool = False) -> None:
    """Download a robot's model files (pinned commit, sparse clone)."""
    from roboworld.robots import fetch as do_fetch

    typer.echo(do_fetch(robot, force=force))


@app.command()
def describe(robot: str) -> None:
    """Show a robot's manifest: joints, aliases, limbs, poses, gaits."""
    from roboworld import api

    _print(api.describe(robot))


@app.command()
def lang() -> None:
    """Print the RoboLang reference."""
    from roboworld import api

    typer.echo(api.language_reference())


@app.command()
def check(robot: str, program: Path) -> None:
    """Validate a RoboLang program file against a robot."""
    from roboworld import api

    report = api.validate(robot, program.read_text())
    _print(report)
    raise typer.Exit(0 if report["ok"] else 1)


@app.command()
def run(
    robot: str,
    program: Optional[Path] = typer.Argument(None, help="RoboLang YAML/JSON file"),
    idle: bool = typer.Option(False, help="just stand for a few seconds"),
    seconds: float = typer.Option(30.0, help="max simulated seconds"),
    view: bool = typer.Option(False, help="open the Rerun viewer afterwards"),
    snapshots: int = typer.Option(4, help="number of snapshot images"),
) -> None:
    """Simulate a program (or --idle) and record the run."""
    from roboworld import api

    if program is None and not idle:
        raise typer.BadParameter("give a program file or --idle")
    source = "do: [{wait: 3}]" if idle else program.read_text()
    result = api.simulate(robot, source, max_seconds=seconds, snapshots=snapshots)
    _print(result)
    if view and result.get("run_id"):
        _open_viewer(Path(result["recording"]))
    raise typer.Exit(0 if result.get("status") == "completed" else 1)


def _open_viewer(rrd: Path) -> None:
    exe = shutil.which("rerun") or str(Path(sys.executable).parent / "rerun")
    subprocess.Popen([exe, str(rrd)])


@app.command()
def view(run_id: str = typer.Argument("latest"), web: bool = typer.Option(False, help="open in the browser")) -> None:
    """Replay a recorded run in Rerun (3D, joint plots, events)."""
    from roboworld import store

    rrd = store.run_dir(run_id) / "recording.rrd"
    if web:
        exe = shutil.which("rerun") or str(Path(sys.executable).parent / "rerun")
        subprocess.run([exe, "--web-viewer", str(rrd)])
    else:
        _open_viewer(rrd)


@app.command()
def runs(limit: int = 15) -> None:
    """List recent runs."""
    from roboworld import api

    for r in api.runs(limit):
        typer.echo(f"{r['run_id']:<45} {r['status']:<10} forward={r['forward_m']} fell={r['fell']}")


@app.command()
def snapshot(robot: str, pose: Optional[str] = None, out: Path = Path("snapshot.png"),
             azimuth: float = 135.0) -> None:
    """Render a robot in a named pose to a PNG."""
    from roboworld import api
    from roboworld.sim.render import save_png

    typer.echo(save_png(api.snapshot(robot, pose, azimuth=azimuth), out))


@app.command()
def tasks() -> None:
    """List tasks (world + instruction) that robots can be dropped into."""
    from roboworld.world.spec import list_tasks

    for t in list_tasks():
        world = t.world if isinstance(t.world, str) else t.world.name
        typer.echo(f"{t.name:<22} world={world:<16} {t.instruction}")


@app.command("serve-robot")
def serve_robot(
    robot: str = typer.Option(..., help="robot name"),
    task: str = typer.Option(..., help="task name (rw tasks)"),
    mode: str = typer.Option("paused", help="paused | realtime"),
    seed: int = typer.Option(0),
    run_id: Optional[str] = typer.Option(None, help="results go to runs/<run_id>"),
    brain: Optional[str] = typer.Option(None, help="label for the brain, recorded in results"),
    http: Optional[int] = typer.Option(None, help="serve over streamable HTTP on this port instead of stdio"),
    record: bool = typer.Option(True, help="write a Rerun recording of the episode"),
) -> None:
    """Run a robot episode as an MCP server: any MCP client can be the brain."""
    from roboworld.mcp.robot_server import create_robot_server

    server = create_robot_server(robot, task, mode=mode, seed=seed, run_id=run_id, brain=brain, record=record)
    if http:
        server.run("streamable-http", host="127.0.0.1", port=http)
    else:
        server.run("stdio")


@app.command()
def episode(
    robot: str = typer.Option(...),
    task: str = typer.Option(...),
    brain: str = typer.Option(..., help="your harness spec .yaml, baseline, codex, claude-code, scripted or cmd"),
    script: Optional[Path] = typer.Option(None, help="scripted: YAML list of tool calls"),
    cmd: Optional[str] = typer.Option(None, help="cmd: agent command with {prompt} and {mcp_config} placeholders"),
    mode: str = typer.Option("paused", help="paused | realtime"),
    seed: int = 0,
    max_turns: int = 40,
) -> None:
    """Drop a robot into a task and let a brain (your harness, or any MCP agent) drive it."""
    from roboworld.brain import brains, registry, runner

    if brain == "scripted":
        if not script:
            raise typer.BadParameter("--script is required for the scripted brain")
        resolved = brains.ScriptedBrain.from_file(str(script))
    elif brain == "cmd":
        if not cmd:
            raise typer.BadParameter("--cmd is required for the cmd brain")
        resolved = registry.CommandBrain(name="cmd", command=cmd)
    else:
        resolved = registry.resolve(brain)
    if isinstance(resolved, registry.CommandBrain):
        result = runner.run_command_brain(robot, task, resolved.command, mode=mode, seed=seed)
    else:
        result = runner.run_episode(robot, task, resolved, mode=mode, seed=seed, max_turns=max_turns)
    _print(runner.episode_summary(result))


@app.command()
def bench(
    robots: str = typer.Option("go2,open_duck_mini_v2", help="comma-separated robots"),
    tasks: str = typer.Option("all", help="comma-separated tasks, or all"),
    brains: str = typer.Option("baseline", help="comma-separated brains: baseline, codex, claude-code, a spec .yaml…"),
    seeds: int = typer.Option(2, help="random placements per task"),
    mode: str = typer.Option("paused", help="paused | realtime"),
    jobs: int = typer.Option(3, help="episodes in parallel (in-process brains; agent CLIs run one at a time)"),
    max_turns: int = 40,
    record: bool = typer.Option(False, help="keep Rerun recordings (≈5-15 MB per episode)"),
    name: str = typer.Option("", help="label for the bench folder"),
) -> None:
    """Run robots × brains × tasks × seeds and write a comparison report."""
    from roboworld.bench import run_bench

    done = {"n": 0}

    def tick(row: dict) -> None:
        done["n"] += 1
        mark = "✓" if row["success"] else ("!" if row["error"] else "·")
        typer.echo(f"  {mark} {row['brain']:<24} {row['robot']:<18} {row['task']:<28} s{row['seed']} "
                   f"{row['status']}" + (f"  ({row['error']})" if row["error"] else ""))

    out = run_bench([r.strip() for r in robots.split(",")], [t.strip() for t in tasks.split(",")],
                    [b.strip() for b in brains.split(",")], seeds, mode=mode, parallel=jobs, max_turns=max_turns,
                    record=record, name=name, progress_cb=tick)
    typer.echo("")
    for b in out["leaderboard"]:
        a = out["by_brain"][b]
        typer.echo(f"{b:<28} success {a['successes']}/{a['episodes']} ({100 * a['success_rate']:.0f}%)  "
                   f"progress {100 * a['mean_progress']:.0f}%  overclaim {a['overclaim_rate']}")
    typer.echo(f"\nreport: {out['report']}")


@app.command()
def brains() -> None:
    """List brains you can use with `rw bench` / `rw episode`."""
    from roboworld.brain.registry import list_brains

    for b in list_brains():
        typer.echo(f"{b['name']:<18} {b['type']:<10} {b['about']}")


harness_app = typer.Typer(help="Build and check your own harness (the brain's control loop).",
                          no_args_is_help=True)
app.add_typer(harness_app, name="harness")

HARNESS_TEMPLATE = '''"""{name}: a RoboWorld harness. Edit run(); see "Building a harness" in the docs.

Run it:   uv run rw harness check {spec}
Bench it: uv run rw bench --brains baseline,{spec}
"""

from roboworld.harness import Harness, Robot, TaskInfo


class {cls}(Harness):
    name = "{name}"

    def __init__(self, model: str | None = None, max_steps: int = 20):
        super().__init__()
        self.model = model  # from the spec's params: use it to call whatever LLM you like
        self.max_steps = max_steps

    async def run(self, robot: Robot, task: TaskInfo) -> None:
        # 1. Perceive: scan the room, then read back everything seen so far.
        await robot.do("look_around")
        seen = await robot.seen()

        # 2. Decide. Replace this rule with your own logic or a call to your model
        #    (see examples/harnesses/llm_harness.py for one way to do that).
        words = task.instruction.lower()
        target = next((o["name"] for o in seen
                       if o.get("kind") != "wall" and o["name"].split("_")[0] in words), None)

        # 3. Act with skills (see `await robot.skills()`), and read each result.
        ok = False
        if target:
            result = await robot.do("walk_to", target=target)
            ok = bool(result.get("ok"))

        # 4. Finish. Only claim success you have checked.
        #    Anything you put in self.stats (model calls, tokens, cost_usd...) shows up in the results.
        await robot.finish(f"{name}: went to {{target}}", success=ok)
'''

SPEC_TEMPLATE = """name: {name}
type: harness
harness: {path}:{cls}
# params are passed to your class's constructor, e.g. which model your harness should call:
# params: {{max_steps: 20, model: your-model-name}}
"""


@harness_app.command("new")
def harness_new(name: str, folder: Path = typer.Option(Path("harnesses"), "--dir", help="where to write it")) -> None:
    """Scaffold a harness: NAME.py (the class) and NAME.yaml (the spec that plugs it in)."""
    import re

    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "my_harness"
    cls = "".join(part.capitalize() for part in slug.split("_")) + "Harness"
    folder.mkdir(parents=True, exist_ok=True)
    py, spec = folder / f"{slug}.py", folder / f"{slug}.yaml"
    for f in (py, spec):
        if f.exists():
            raise typer.BadParameter(f"{f} already exists")
    py.write_text(HARNESS_TEMPLATE.format(name=slug, cls=cls, spec=spec))
    spec.write_text(SPEC_TEMPLATE.format(name=slug, cls=cls, path=py))
    typer.echo(f"wrote {py}\nwrote {spec}\n\nnext: uv run rw harness check {spec}")


@harness_app.command("check")
def harness_check(
    spec: str = typer.Argument(..., help="brain spec .yaml (or a brain name)"),
    robot: str = "go2",
    task: str = "find_red_ball",
    seed: int = 0,
    max_turns: int = 40,
) -> None:
    """Run one quick episode with a harness and report whether it behaves."""
    from roboworld.brain import registry, runner

    brain = registry.resolve(spec)
    if isinstance(brain, registry.CommandBrain):
        result = runner.run_command_brain(robot, task, brain.command, seed=seed, record=False)
    else:
        result = runner.run_episode(robot, task, brain, seed=seed, max_turns=max_turns, record=False)
    stats = result.get("brain_stats", {})
    problems = []
    if result.get("ended_by") in ("disconnected", "in_progress"):
        problems.append("the episode wasn't finished cleanly")
    if (result.get("ended_by") == "brain_finished" and stats.get("summary")
            and "stopped without calling finish" in stats["summary"]):
        problems.append("run() returned without calling robot.finish(...) while the episode was still open")
    if stats.get("invalid_calls"):
        problems.append(f"{stats['invalid_calls']} invalid tool call(s)")
    if stats.get("overclaimed"):
        problems.append("claimed success but the simulator disagrees")
    _print(runner.episode_summary(result))
    typer.echo("\n" + ("OK: harness ran cleanly" if not problems else "issues:\n- " + "\n- ".join(problems)))
    raise typer.Exit(0 if not problems or problems == ["claimed success but the simulator disagrees"] else 1)


design_app = typer.Typer(help="Design robots: templates, changes, checks, history, tuning, comparisons.",
                         no_args_is_help=True)
app.add_typer(design_app, name="design")


def _sets(pairs: list[str] | None, changes: str | None) -> dict:
    import yaml

    out = yaml.safe_load(changes) if changes else {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        if not key or not _:
            raise typer.BadParameter(f"--set expects key=value, got '{pair}'")
        out[key.strip()] = yaml.safe_load(value)
    return out


def _check_lines(report: dict) -> None:
    typer.echo(f"\ncheck: {report['summary']}")
    for c in report["checks"]:
        typer.echo(f"  {c['status']:<4} {c['check']:<18} {c['detail']}")


@design_app.command("templates")
def design_templates() -> None:
    """Starting points for new robots."""
    from roboworld.design import api

    for name, about in api.templates().items():
        typer.echo(f"{name:<10} {' '.join(about.split())}")


@design_app.command("servos")
def design_servos() -> None:
    """The servo catalog."""
    from roboworld.design import api

    for name, s in api.servos().items():
        typer.echo(f"{name:<8} {s['torque_nm']:>4} N·m  {s['speed_rad_s']:>4} rad/s  {s['mass_kg'] * 1000:>3.0f} g  {s['note']}")


@design_app.command("new")
def design_new(name: str, template: str = typer.Option(..., help="see `rw design templates`"),
               set_: Optional[list[str]] = typer.Option(None, "--set", help="change, e.g. all_legs.thigh=0.1"),
               changes: Optional[str] = typer.Option(None, help="YAML mapping of changes"),
               note: str = "", check: bool = True) -> None:
    """Create a robot from a template (plus optional changes), compile it and check it."""
    from roboworld.design import api

    out = api.new(name, template, _sets(set_, changes), note=note, check=check)
    typer.echo(f"created {out['name']} (digest {out['digest']})")
    if check:
        _check_lines(out["check"])


@design_app.command("derive")
def design_derive(parent: str, name: str,
                  set_: Optional[list[str]] = typer.Option(None, "--set", help="change, e.g. body.mass=1.4"),
                  changes: Optional[str] = typer.Option(None, help="YAML mapping of changes"),
                  note: str = "", check: bool = True) -> None:
    """Make a child design with some changes; history keeps the link to its parent."""
    from roboworld.design import api

    out = api.derive(parent, name, _sets(set_, changes), note=note, check=check)
    typer.echo(f"created {out['name']} from {parent}")
    if check:
        _check_lines(out["check"])


@design_app.command("check")
def design_check(name: str) -> None:
    """Re-run the physical and walking checks on a design (or any robot)."""
    from roboworld.design import api

    _check_lines(api.check(name))


@design_app.command("show")
def design_show(name: str) -> None:
    """Print a design's spec and history info."""
    from roboworld.design import api

    _print(api.show(name))


@design_app.command("list")
def design_list() -> None:
    """All designs."""
    from roboworld.design import api

    for d in api.designs():
        typer.echo(f"{d['name']:<22} parent={d['parent'] or '-':<18} {d['check'] or 'unchecked':<12} {d['note'] or ''}")


@design_app.command("history")
def design_history(name: str) -> None:
    """A design and its ancestors."""
    from roboworld.design import api

    for h in api.history(name):
        typer.echo(f"{h['name']:<22} {h['created']}  {h['check'] or 'unchecked':<12} {h['note'] or ''}")


@design_app.command("tune")
def design_tune(name: str, course: str = typer.Option("flat", help="flat | bumpy"), trials: int = 24,
                as_: Optional[str] = typer.Option(None, "--as", help="name for the tuned child design")) -> None:
    """Search the design's gait settings on a course; save the best as a child design."""
    from roboworld.design import api

    out = api.tune(name, course=course, trials=trials, new_name=as_)
    typer.echo(f"{course}: {out['baseline_score_m']} m -> {out['best_score_m']} m over {out['trials']} trials")
    typer.echo(f"best: {out['best']}")
    typer.echo(f"saved as: {out.get('saved_as') or '(no improvement, nothing saved)'}")


@design_app.command("compare")
def design_compare(robots: list[str], tasks: str = typer.Option("all", help="comma-separated tasks or all"),
                   seeds: int = 2, brain: str = typer.Option("baseline", help="the same brain drives every robot"),
                   jobs: int = 3) -> None:
    """Run the same brain on several robots across tasks: differences come from the bodies."""
    from roboworld.design import api

    out = api.compare(list(robots), tasks, seeds=seeds, brain=brain, parallel=jobs)
    for robot, r in sorted(out["robots"].items(), key=lambda kv: -kv[1]["success_rate"]):
        typer.echo(f"{robot:<22} {r['successes']}/{r['episodes']} ({100 * r['success_rate']:.0f}%)  {r['tasks']}")
    typer.echo(f"\nreport: {out['report']}")


@app.command("robot-config")
def robot_config(robot: str = typer.Option(...), task: str = typer.Option(...), mode: str = "paused",
                 seed: int = 0, brain: str = "external") -> None:
    """Print an MCP config that lets any MCP client (Claude Code, Codex, Cursor...) be the robot's brain."""
    from roboworld.brain import runner

    run_id = runner.new_episode_id(robot, task)
    _print(runner.mcp_config(robot, task, mode, seed, run_id, brain))


@app.command("serve-mcp")
def serve_mcp() -> None:
    """Run the MCP server on stdio (for Claude Code / Claude Desktop)."""
    from roboworld.mcp.server import main

    main()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
