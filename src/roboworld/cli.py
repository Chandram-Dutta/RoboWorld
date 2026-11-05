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
    brain: str = typer.Option(..., help="scripted | openai | codex | claude-code | cmd"),
    script: Optional[Path] = typer.Option(None, help="scripted: YAML list of tool calls"),
    base_url: str = typer.Option("http://localhost:11434/v1", help="openai: any OpenAI-compatible endpoint"),
    model: str = typer.Option("qwen3:4b", help="openai: model name"),
    api_key_env: Optional[str] = typer.Option(None, help="openai: env var holding the API key"),
    vision: bool = typer.Option(True, help="openai: send camera images to the model"),
    cmd: Optional[str] = typer.Option(None, help="cmd: agent command with {prompt} and {mcp_config} placeholders"),
    mode: str = typer.Option("paused", help="paused | realtime"),
    seed: int = 0,
    max_turns: int = 40,
) -> None:
    """Drop a robot into a task and let a brain (any MCP client) drive it."""
    import os

    from roboworld.brain import brains, runner

    if brain == "scripted":
        if not script:
            raise typer.BadParameter("--script is required for the scripted brain")
        result = runner.run_episode(robot, task, brains.ScriptedBrain.from_file(str(script)), mode=mode, seed=seed,
                                    max_turns=max_turns)
    elif brain == "openai":
        key = os.environ.get(api_key_env) if api_key_env else None
        b = brains.OpenAICompatBrain(base_url=base_url, model=model, api_key=key, vision=vision)
        result = runner.run_episode(robot, task, b, mode=mode, seed=seed, max_turns=max_turns)
    elif brain in runner.PRESETS or brain == "cmd":
        command = brain if brain in runner.PRESETS else cmd
        if not command:
            raise typer.BadParameter("--cmd is required for the cmd brain")
        result = runner.run_command_brain(robot, task, command, mode=mode, seed=seed)
    else:
        raise typer.BadParameter(f"unknown brain '{brain}'")
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
