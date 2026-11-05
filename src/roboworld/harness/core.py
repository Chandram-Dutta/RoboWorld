"""The Harness SDK core: ``Robot`` (what a harness can do), ``TaskInfo`` (what it's
asked to do) and ``Harness`` (the class you subclass).

A harness never touches the simulator. It drives the robot's MCP server, the
same one Codex or Claude Code would use, through ``Robot``'s typed methods.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any



@dataclass
class TaskInfo:
    robot: str
    instruction: str  # the task, in words
    prompt: str  # a ready-made opening prompt for an LLM
    briefing: str  # the robot server's instructions: robot, tools, coordinates, timing mode
    time_limit_s: float | None = None
    mode: str = "paused"


@dataclass
class ToolResult:
    text: str
    data: dict[str, Any] | None
    images: list[bytes]
    is_error: bool

    @property
    def ok(self) -> bool:
        return not self.is_error and bool((self.data or {}).get("ok", True)) and "error" not in (self.data or {})


class Robot:
    """The robot as a harness sees it: its MCP tools, with typed helpers.

    Every call goes over MCP to the robot server, so a harness works the same
    against a local episode, a remote ``rw serve-robot --http`` or a benchmark.
    """

    def __init__(self, session: Any, tools: list[Any]):
        self.session = session
        self.tools = tools  # raw MCP tool definitions (name, description, input_schema)
        self.over = False
        self.ended_by: str | None = None  # success | failed | fell | time_limit | brain_finished ...
        self.finished = False
        self.calls = 0
        self.failed_calls = 0
        self.log: list[dict[str, Any]] = []

    async def call(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        """Call any robot tool by name (what an LLM's tool call maps to)."""
        res = await self.session.call_tool(name, args or {})
        texts, images = [], []
        for c in res.content:
            if c.type == "text":
                texts.append(c.text)
            elif c.type == "image":
                images.append(base64.b64decode(c.data))
        text = "\n".join(texts)
        data = None
        try:
            parsed = json.loads(texts[0]) if texts else None
            data = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        result = ToolResult(text, data, images, bool(res.is_error))
        self.calls += 1
        if not result.ok:
            self.failed_calls += 1
        if data and data.get("episode", {}).get("over"):
            self.over = True
            self.ended_by = data["episode"].get("ended_by") or self.ended_by
        if name == "finish":
            self.finished = self.over = True
        self.log.append({"tool": name, "args": args or {}, "ok": result.ok, "result": text[:300]})
        return result

    # ----------------------------------------------------- typed helpers
    async def observe(self) -> dict[str, Any]:
        return (await self.call("observe")).data or {}

    async def look(self) -> tuple[bytes | None, dict[str, Any]]:
        r = await self.call("look")
        return (r.images[0] if r.images else None), (r.data or {})

    async def skills(self) -> dict[str, Any]:
        return (await self.call("skills")).data or {}

    async def do(self, skill: str, **args: Any) -> dict[str, Any]:
        return (await self.call("do", {"skill": skill, "args": args})).data or {}

    async def run(self, program: str) -> dict[str, Any]:
        return (await self.call("run", {"program": program})).data or {}

    async def status(self) -> dict[str, Any]:
        return (await self.call("status")).data or {}

    async def finish(self, summary: str = "", success: bool | None = None, answer: str | None = None) -> dict:
        args: dict[str, Any] = {"summary": summary}
        if success is not None:
            args["success"] = success
        if answer is not None:
            args["answer"] = str(answer)
        return (await self.call("finish", args)).data or {}

    async def seen(self) -> list[dict[str, Any]]:
        """Objects (and walls) the robot has seen so far."""
        return (await self.observe()).get("objects_seen", [])


class Harness:
    """Subclass this and implement ``run``. ``stats`` ends up in the episode results.

    Lifecycle: the runner connects to the robot, builds ``TaskInfo`` and calls
    ``await harness.run(robot, task)``. If ``run`` returns without calling
    ``robot.finish``, the runner finishes the episode for you.
    """

    name: str = "harness"

    def __init__(self) -> None:
        self.stats: dict[str, Any] = {}

    async def run(self, robot: Robot, task: TaskInfo) -> None:  # pragma: no cover - interface
        raise NotImplementedError


def objects_text(seen: list[dict[str, Any]]) -> str:
    """Compact one-line-per-object description of what's been seen."""
    lines = []
    for o in seen:
        if o.get("kind") == "wall":
            continue
        extra = " (painted on the floor)" if o.get("flat") else ""
        lines.append(f"- {o['name']}: {o.get('color', '')} {o.get('kind', '')}{extra} at "
                     f"({o['position'][0]:.2f}, {o['position'][1]:.2f}), {o.get('distance_m')} m away, "
                     f"bearing {o.get('bearing_deg')}°" + (" (visible now)" if o.get("visible_now") else ""))
    walls = [o["name"] for o in seen if o.get("kind") == "wall"]
    if walls:
        lines.append(f"- walls seen: {', '.join(walls)}")
    return "\n".join(lines) or "- nothing yet"
