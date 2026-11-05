"""The robot as an MCP server: any MCP client can be its brain.

One server process = one episode (robot + task + timing mode). The brain gets
only the robot's senses and skills. It can't see hidden world state or reset
the world. Results are written to ``runs/<run_id>/`` as the episode goes and
finalised when the client disconnects or calls ``finish``.

    rw serve-robot --robot open_duck_mini_v2 --task push_ball_to_goal
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from mcp.server.mcpserver import Image, MCPServer

from roboworld.episode import Episode
from roboworld.robots import load_manifest
from roboworld.world.spec import load_task


def task_prompt(robot: str, task: str, mode: str) -> str:
    t = load_task(task)
    return (f"You are controlling the robot '{robot}' through the robot MCP tools. Task: {t.instruction} "
            f"You have {t.time_limit_s:.0f} s of robot time ({mode} mode). Start with skills and look, "
            "then act. Call finish when you think the task is done.")


def instructions(robot: str, task: str, mode: str) -> str:
    m = load_manifest(robot)
    t = load_task(task)
    timing = ("PAUSED mode: the world waits while you think." if mode == "paused" else
              "REALTIME mode: the world keeps going while you think. Thinking time uses up robot time.")
    return f"""\
You are the brain of a robot: {robot} ({m.kind}). {" ".join(m.description.split())}

TASK: {t.instruction}
Time limit: {t.time_limit_s:.0f} s of robot time. {timing}

Tools:
- observe(): where you are, what you have seen so far, the result of your last action.
- look(): an image from the robot's camera plus the objects visible right now.
- skills(): what the robot can do, with argument formats.
- do(skill, args): run a skill, e.g. do("look_around") or do("walk_to", {{"target": "red_ball"}}).
  It returns when the skill finishes, with ok and a message. Skills can fail: read the message and adapt.
- run(program): run a custom RoboLang motion program (YAML) for anything the skills don't cover.
- finish(summary): end the episode when you think the task is done, or that it's impossible.

Coordinates are world metres. At the start x pointed forward and y to the left. Headings are degrees,
counter-clockwise. You only know about objects you have seen. Success is judged by the simulator,
not by you."""


def create_robot_server(robot: str, task: str, mode: str = "paused", seed: int = 0, run_id: str | None = None,
                        brain: str | None = None) -> MCPServer:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="episode")  # MuJoCo + GL on one thread
    holder: dict[str, Episode] = {}

    def episode() -> Episode:
        if "ep" not in holder:
            holder["ep"] = Episode(robot, task, mode=mode, seed=seed, run_id=run_id, brain=brain)
        return holder["ep"]

    async def call(fn: Callable[[Episode], Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, lambda: fn(episode()))

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[dict]:
        await call(lambda ep: None)  # build the world before the first tool call
        try:
            yield {}
        finally:
            await call(lambda ep: ep.close())
            executor.shutdown(wait=True)

    server = MCPServer("robot", instructions=instructions(robot, task, mode), lifespan=lifespan)

    def dump(data: Any) -> str:
        return json.dumps(data, indent=1, default=str)

    @server.tool()
    async def observe() -> str:
        """Robot pose, everything seen so far (with distance/bearing from where you are now), last action result."""
        return dump(await call(lambda ep: ep.observe()))

    @server.tool(structured_output=False)
    async def look() -> list[Any]:
        """See through the robot's camera: returns the image and the objects visible right now."""
        png, info = await call(lambda ep: ep.look())
        out: list[Any] = [dump(info)]
        if png:
            out.append(Image(data=png, format="png"))
        return out

    @server.tool()
    async def skills() -> str:
        """The robot's skills (name, description, args) and saved motions."""
        return dump(await call(lambda ep: ep.skills()))

    @server.tool()
    async def do(skill: str, args: dict[str, Any] | str | None = None) -> str:
        """Run one skill and wait for it to finish. args is an object, e.g. {"target": "red_ball"}.
        Returns ok, a message (why it failed, if it did), the robot's pose and the episode clock."""
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                return dump({"ok": False, "error": "args must be a JSON object"})
        return dump(await call(lambda ep: ep.do(skill, args or {})))

    @server.tool()
    async def run(program: str) -> str:
        """Run a RoboLang program (YAML text) for custom motions. Steps can also call skills:
        `- skill: walk_to` with `args: {target: red_ball}`."""
        return dump(await call(lambda ep: ep.run(program)))

    @server.tool()
    async def status() -> str:
        """Task, clock and whether the episode is over."""
        return dump(await call(lambda ep: ep.status()))

    @server.tool()
    async def finish(summary: str = "") -> str:
        """End the episode. Say briefly what you did and whether you think the task is done."""
        return dump(await call(lambda ep: ep.finish(summary)))

    @server.prompt()
    def start() -> str:
        """The task prompt for this episode."""
        return task_prompt(robot, task, mode)

    return server
