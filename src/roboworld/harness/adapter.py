"""Run a ``Harness`` wherever a brain is expected (``rw episode``, ``rw bench``),
or connect one straight to a robot server you started yourself."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from roboworld.brain.brains import Brain
from roboworld.harness.core import Harness, Robot, TaskInfo


async def task_info(robot: Robot, instructions: str, prompt: str) -> TaskInfo:
    st = await robot.status()
    ep = st.get("episode", {})
    return TaskInfo(robot=st.get("robot", ""), instruction=st.get("task") or prompt, prompt=prompt,
                    briefing=instructions, time_limit_s=st.get("time_limit_s") or ep.get("time_left_s"),
                    mode=st.get("mode", "paused"))


async def drive(harness: Harness, session: Any, tools: list[Any], instructions: str, prompt: str) -> Robot:
    """Run a harness on an open robot MCP session; always leaves the episode finished."""
    robot = Robot(session, tools)
    task = await task_info(robot, instructions, prompt)
    try:
        await harness.run(robot, task)
    finally:
        if not robot.finished:
            await robot.finish(summary=f"{harness.name} stopped without calling finish")
    return robot


@dataclass
class HarnessBrain(Brain):
    harness: Harness | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.harness is not None and self.name == "brain":
            self.name = self.harness.name

    async def run(self, session, instructions, prompt, tools, max_turns) -> None:
        robot = await drive(self.harness, session, tools, instructions, prompt)
        self.stats = {"harness": self.harness.name, **self.harness.stats, "robot_calls": robot.calls,
                      "failed_robot_calls": robot.failed_calls}
        self.log = robot.log


async def connect_and_run(harness: Harness, url: str | None = None, command: list[str] | None = None) -> Robot:
    """Drive a robot server you started yourself: ``url`` for ``rw serve-robot --http PORT``
    (e.g. http://127.0.0.1:8765/mcp) or ``command`` to launch one over stdio."""
    from mcp import ClientSession

    if url:
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                init = await session.initialize()
                tools = (await session.list_tools()).tools
                return await drive(harness, session, tools, init.instructions or "", init.instructions or "")
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=command[0], args=command[1:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            return await drive(harness, session, tools, init.instructions or "", init.instructions or "")
