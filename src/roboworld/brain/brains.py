"""Brains: MCP clients that drive a robot episode.

Nothing here is tied to one vendor:

- ``ScriptedBrain`` replays fixed tool calls (tests, baselines).
- Your own harnesses plug in through ``roboworld.harness`` (see brain/registry.py).
- External agents (Claude Code, Codex, Gemini CLI...) connect to the robot MCP
  server directly; see ``runner.run_command_brain``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import yaml
from mcp import ClientSession


@dataclass
class ToolOutcome:
    text: str
    images: list[tuple[str, str]]  # (mime, base64)
    is_error: bool
    episode_over: bool


async def call_tool(session: ClientSession, name: str, args: dict[str, Any]) -> ToolOutcome:
    res = await session.call_tool(name, args)
    texts, images = [], []
    for c in res.content:
        if c.type == "text":
            texts.append(c.text)
        elif c.type == "image":
            images.append((c.mime_type, c.data))
    text = "\n".join(texts)
    over = False
    try:
        over = bool(json.loads(texts[0]).get("episode", {}).get("over")) if texts else False
    except (json.JSONDecodeError, AttributeError):
        pass
    return ToolOutcome(text, images, bool(res.is_error), over)


@dataclass
class Brain:
    name: str = "brain"
    stats: dict[str, Any] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    async def run(self, session: ClientSession, instructions: str, prompt: str, tools: list, max_turns: int) -> None:
        raise NotImplementedError


@dataclass
class ScriptedBrain(Brain):
    """Calls tools from a list like ``[{do: {skill: look_around}}, {finish: {summary: ok}}]``."""

    steps: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str) -> ScriptedBrain:
        with open(path) as f:
            return cls(name=f"scripted:{os.path.basename(path)}", steps=yaml.safe_load(f))

    async def run(self, session, instructions, prompt, tools, max_turns) -> None:
        finished = False
        for step in self.steps[:max_turns]:
            (tool, args), = step.items()
            if finished:
                break
            out = await call_tool(session, tool, args or {})
            self.log.append({"tool": tool, "args": args, "result": out.text[:500]})
            finished = tool == "finish"
            if out.episode_over and not finished:
                await call_tool(session, "finish", {"summary": "episode over"})
                finished = True
        if not finished:
            await call_tool(session, "finish", {"summary": "script ended"})
