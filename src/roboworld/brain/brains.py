"""Brains: MCP clients that drive a robot episode.

Nothing here is tied to one vendor:

- ``ScriptedBrain`` replays fixed tool calls (tests, baselines).
- ``OpenAICompatBrain`` talks to any OpenAI-compatible chat endpoint: Ollama,
  LM Studio, vLLM, OpenRouter, OpenAI, and other hosted providers that offer the
  same API.

External agents (Claude Code, Codex, Gemini CLI...) connect to the robot MCP
server directly; see ``runner.run_command_brain``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
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


@dataclass
class OpenAICompatBrain(Brain):
    """An LLM behind any OpenAI-compatible ``/chat/completions`` endpoint."""

    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3:4b"
    api_key: str | None = None
    vision: bool = True
    temperature: float = 0.2
    timeout: float = 300.0
    transport: httpx.AsyncBaseTransport | None = None  # tests inject a mock

    def __post_init__(self) -> None:
        if self.name == "brain":
            self.name = f"openai-compat:{self.model}"
        self.stats = {"model": self.model, "base_url": self.base_url, "llm_calls": 0, "prompt_tokens": 0,
                      "completion_tokens": 0, "llm_latency_s": 0.0, "nudges": 0}

    async def _complete(self, client: httpx.AsyncClient, messages: list, tools: list) -> dict[str, Any]:
        body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                "temperature": self.temperature}
        t0 = time.time()
        resp = await client.post("/chat/completions", json=body)
        self.stats["llm_latency_s"] = round(self.stats["llm_latency_s"] + time.time() - t0, 2)
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        self.stats["llm_calls"] += 1
        self.stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        return data["choices"][0]["message"]

    async def run(self, session, instructions, prompt, tools, max_turns) -> None:
        oa_tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                      "parameters": t.input_schema}} for t in tools]
        messages: list[dict[str, Any]] = [{"role": "system", "content": instructions},
                                          {"role": "user", "content": prompt}]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        finished = False
        async with httpx.AsyncClient(base_url=self.base_url.rstrip("/"), headers=headers, timeout=self.timeout,
                                     transport=self.transport) as client:
            for _ in range(max_turns):
                msg = await self._complete(client, messages, oa_tools)
                calls = msg.get("tool_calls") or []
                messages.append({"role": "assistant", "content": msg.get("content") or "", **(
                    {"tool_calls": calls} if calls else {})})
                if msg.get("content"):
                    self.log.append({"assistant": msg["content"][:1000]})
                if not calls:
                    if self.stats["nudges"] >= 2:
                        break
                    self.stats["nudges"] += 1
                    messages.append({"role": "user", "content": "Use the robot tools to continue, or call finish."})
                    continue
                images: list[tuple[str, str]] = []
                over = False
                for call in calls:
                    fn = call["function"]
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    out = await call_tool(session, fn["name"], args)
                    self.log.append({"tool": fn["name"], "args": args, "result": out.text[:500]})
                    content = out.text + ("\n[camera image attached below]" if out.images and self.vision else "")
                    messages.append({"role": "tool", "tool_call_id": call.get("id", fn["name"]), "content": content})
                    images += out.images
                    over = over or out.episode_over
                    finished = finished or fn["name"] == "finish"
                if images and self.vision:
                    parts: list[dict[str, Any]] = [{"type": "text", "text": "Camera image from look():"}]
                    parts += [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
                              for mime, data in images[-1:]]
                    messages.append({"role": "user", "content": parts})
                if finished:
                    return
                if over:
                    await call_tool(session, "finish", {"summary": "episode over"})
                    return
        if not finished:
            await call_tool(session, "finish", {"summary": "turn limit reached"})
