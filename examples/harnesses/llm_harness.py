"""Example: a harness that asks an LLM what to do next.

RoboWorld doesn't ship LLM harnesses. This file shows one way to write your own.
`ask()` is the only model-specific part; it uses the Codex CLI (your Codex login,
no API key). Swap it for any model API you like.

    uv run rw harness check examples/harnesses/llm_harness.yaml --task avoid_red_zone
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path

from roboworld.harness import Harness, Robot, TaskInfo, objects_text


async def ask(prompt: str, image: bytes | None = None) -> str:
    """Send a prompt (and the robot's camera image) to a model; return its text reply."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "reply.txt"
        args = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-o", str(out)]
        if image:
            (Path(tmp) / "eye.png").write_bytes(image)
            args.append(f"--image={Path(tmp) / 'eye.png'}")
        proc = await asyncio.create_subprocess_exec(*args, prompt, cwd=tmp, stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        return out.read_text() if out.exists() else ""


class LLMHarness(Harness):
    name = "example:llm"

    def __init__(self, max_steps: int = 12):
        super().__init__()
        self.max_steps = max_steps
        self.stats = {"llm_calls": 0}

    async def run(self, robot: Robot, task: TaskInfo) -> None:
        skills = (await robot.skills())["skills"]
        menu = "\n".join(f"- {s['name']}({', '.join(s['args'])}): {s['description']}" for s in skills)
        history: list[str] = []
        for _ in range(self.max_steps):
            image, _ = await robot.look()
            seen = await robot.seen()
            prompt = (f"You control a robot. Task: {task.instruction}\n\nSkills:\n{menu}\n\n"
                      f"Seen so far (world metres):\n{objects_text(seen)}\n\n"
                      f"What you did so far:\n" + ("\n".join(history[-8:]) or "- nothing yet") + "\n\n"
                      'Reply with JSON only: {"skill": "<name>", "args": {...}} for the next step, or '
                      '{"done": true, "success": true|false, "answer": null} to stop. Do not run commands.')
            self.stats["llm_calls"] += 1
            reply = await ask(prompt, image)
            match = re.search(r"\{.*\}", reply, re.DOTALL)
            step = json.loads(match.group(0)) if match else {"done": True, "success": False}
            if step.get("done"):
                await robot.finish("llm harness done", success=step.get("success"), answer=step.get("answer"))
                return
            result = await robot.do(step.get("skill", ""), **(step.get("args") or {}))
            history.append(f"- {step.get('skill')}({step.get('args')}) -> "
                           f"{'ok' if result.get('ok') else 'FAILED'}: {result.get('message') or result.get('error')}")
            if robot.over:
                break
        if not robot.finished:
            await robot.finish("llm harness stopped", success=True if robot.ended_by == "success" else None)
