"""RoboWorld MCP server: lets an LLM (Claude Code / Desktop) design and test robot motions.

Run with ``rw serve-mcp`` (stdio). Register in Claude Code with:

    claude mcp add roboworld -- uv --directory /path/to/RoboWorld run rw serve-mcp
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from roboworld import api
from roboworld.sim.render import png_bytes

INSTRUCTIONS = """\
RoboWorld simulates robots (MuJoCo) and moves them with RoboLang, a small YAML language.
Workflow:
1. list_robots, then describe_robot (joint names, poses, gaits).
2. language_reference.
3. Write a program, validate_program, simulate.
4. Read the metrics and snapshots, refine, simulate again.
Runs are recorded; the user can replay them with `rw view <run_id>`."""

server = MCPServer("roboworld", instructions=INSTRUCTIONS)


def _json(data: Any) -> str:
    return json.dumps(data, indent=1, default=str)


@server.tool()
def list_robots() -> str:
    """List robots available in RoboWorld (name, kind, description)."""
    return _json(api.robots())


@server.tool()
def describe_robot(robot: str) -> str:
    """Joints (with ranges), aliases like head.pitch, limbs, end-effectors, named poses and
    available gaits (with tuned defaults) for one robot. Read this before writing a program."""
    return _json(api.describe(robot))


@server.tool()
def language_reference() -> str:
    """The RoboLang reference: verbs (pose, clip, gait, reach, wait, repeat, parallel, do),
    until-conditions, safety rules and examples."""
    return api.language_reference()


@server.tool()
def validate_program(robot: str, program: str) -> str:
    """Check a RoboLang program (YAML or JSON text) against a robot without running it.
    Returns errors (must fix), warnings (will be auto-corrected) and estimated duration."""
    return _json(api.validate(robot, program))


@server.tool(structured_output=False)
def simulate(robot: str, program: str, max_seconds: float = 30.0, look: bool = True) -> list[Any]:
    """Run a RoboLang program (YAML or JSON text) on a robot in simulation.

    Returns status (completed | fell | timeout | invalid), metrics (forward_m,
    lateral_drift_m, heading_change_deg, fell, max_tilt_deg, peak_torque_ratio,
    energy, ...), the event log, the run_id, and (if look) a contact sheet of
    snapshots over time so you can see what happened."""
    result = api.simulate(robot, program, max_seconds=max_seconds, snapshots=4 if look else 0)
    sheet = result.pop("contact_sheet", None)
    out: list[Any] = [_json(result)]
    if look and sheet:
        out.append(Image(path=sheet))
    return out


@server.tool(structured_output=False)
def render_snapshot(robot: str, pose: str | None = None, joints: dict[str, float] | None = None,
                    azimuth: float = 135.0) -> Image:
    """Picture of the robot standing in a named pose, optionally with joint overrides
    ({joint_or_alias: radians}). Use it to check what a pose looks like before animating it.
    azimuth rotates the camera around the robot (degrees)."""
    return Image(data=png_bytes(api.snapshot(robot, pose, joints, azimuth)), format="png")


@server.tool()
def save_motion(robot: str, name: str, program: str, description: str = "") -> str:
    """Save a RoboLang program as a named motion (e.g. 'wave', 'happy_dance') in the robot's library.
    Robot brains can then run it with the `play` skill. Simulate it first to make sure it works."""
    return _json(api.save_motion(robot, name, program, description))


@server.tool()
def list_motions(robot: str) -> str:
    """Saved motions for a robot (playable by its brain via the `play` skill)."""
    return _json(api.motions(robot))


@server.tool()
def list_tasks() -> str:
    """Tasks (world + instruction) that robots can be dropped into with `rw episode` / `rw serve-robot`."""
    from roboworld.world.spec import list_tasks as _tasks

    return _json([{"name": t.name, "instruction": t.instruction,
                   "world": t.world if isinstance(t.world, str) else t.world.name} for t in _tasks()])


# ------------------------------------------------------------------ design tools
@server.tool()
def design_templates() -> str:
    """Robot templates to start a design from (duck biped, mini dog, hexapod), and the servo catalog."""
    from roboworld.design import api as design

    return _json({"templates": design.templates(), "servos": design.servos()})


def _design_result(out: dict[str, Any]) -> list[Any]:
    result: list[Any] = [_json(out)]
    try:
        result.append(Image(data=png_bytes(api.snapshot(out["name"])), format="png"))
    except Exception:  # noqa: BLE001 - the picture is a bonus
        pass
    return result


@server.tool(structured_output=False)
def design_robot(name: str, template: str, changes: str = "", note: str = "") -> list[Any]:
    """Create a new robot from a template plus changes (YAML), compile it and run its checks.

    Changes can use dotted keys and per-leg edits, e.g.
    {"body.mass": 1.4, "all_legs": {"thigh": 0.1, "dof": "biped6"}, "legs": {"left_leg": {"foot": [0.12, 0.06]}}}.
    The robot then works with every gait, skill, task and the benchmark."""
    from roboworld.design import api as design

    return _design_result(design.new(name, template, changes, note=note))


@server.tool(structured_output=False)
def derive_robot(parent: str, name: str, changes: str, note: str = "") -> list[Any]:
    """Make a child design of an existing design with some changes (history keeps the link), and check it."""
    from roboworld.design import api as design

    return _design_result(design.derive(parent, name, changes, note=note))


@server.tool()
def check_design(name: str) -> str:
    """Physical and walking checks for a robot: mass, joint ranges, overlapping parts, standing torque and sag,
    walking, straightness, turning. Each check says pass/warn/fail and why."""
    from roboworld.design import api as design

    return _json(design.check(name))


@server.tool()
def list_designs() -> str:
    """All robot designs with their parent, last check result and note."""
    from roboworld.design import api as design

    return _json(design.designs())


@server.tool()
def design_history(name: str) -> str:
    """A design and its ancestors, newest first."""
    from roboworld.design import api as design

    return _json(design.history(name))


@server.tool()
def tune_design(name: str, course: str = "flat", trials: int = 24) -> str:
    """Search the design's gait settings on a course ('flat' or 'bumpy') and save the best as a child design."""
    from roboworld.design import api as design

    return _json(design.tune(name, course=course, trials=trials))


@server.tool()
def compare_designs(robots: list[str], tasks: str = "all", seeds: int = 2, brain: str = "baseline") -> str:
    """Run the same brain on several robots across tasks and seeds; differences come from the bodies."""
    from roboworld.design import api as design

    return _json(design.compare(robots, tasks, seeds=seeds, brain=brain))


@server.tool()
def list_runs(limit: int = 10) -> str:
    """Most recent simulation runs."""
    return _json(api.runs(limit))


@server.tool()
def get_run(run_id: str) -> str:
    """Full result of a past run (metrics, events, program path, recording path)."""
    return _json(api.get_run(run_id))


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
