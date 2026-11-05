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


@app.command("serve-mcp")
def serve_mcp() -> None:
    """Run the MCP server on stdio (for Claude Code / Claude Desktop)."""
    from roboworld.mcp.server import main

    main()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
