"""Run an episode: start the robot MCP server and let a brain drive it.

In-process brains (scripted, OpenAI-compatible) connect over stdio from here.
External agents get an MCP config file and a prompt, and run as a subprocess.
Either way the robot side is identical, and results land in ``runs/<run_id>/``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from roboworld import paths
from roboworld.brain.brains import Brain
from roboworld.mcp.robot_server import task_prompt

PRESETS = {
    # Claude Code headless: allow every tool of the "robot" server, nothing else.
    "claude-code": "claude -p {prompt} --mcp-config {mcp_config} --strict-mcp-config --allowedTools mcp__robot",
    # Codex headless: read-only sandbox (it only needs the robot tools), session not saved to history.
    "codex": "codex exec --skip-git-repo-check --ephemeral -s read-only -o {run_dir}/brain_last_message.txt "
             "{codex_flags} {prompt}",
}


def new_episode_id(robot: str, task: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{robot}-{task}-{secrets.token_hex(2)}"


def server_args(robot: str, task: str, mode: str, seed: int, run_id: str, brain: str,
                record: bool = True) -> list[str]:
    return ["-m", "roboworld.cli", "serve-robot", "--robot", robot, "--task", task, "--mode", mode,
            "--seed", str(seed), "--run-id", run_id, "--brain", brain, "--record" if record else "--no-record"]


def _finalise(run_id: str, brain: Brain | None = None) -> dict[str, Any]:
    f = paths.RUNS_DIR / run_id / "result.json"
    result = json.loads(f.read_text())
    if brain is not None:
        result["brain_stats"]["llm"] = brain.stats or None
        (paths.RUNS_DIR / run_id / "brain_log.json").write_text(json.dumps(brain.log, indent=1, default=str))
        f.write_text(json.dumps(result, indent=2, default=str))
    return result


async def run_episode_async(robot: str, task: str, brain: Brain, mode: str = "paused", seed: int = 0,
                            max_turns: int = 40, run_id: str | None = None, record: bool = True) -> dict[str, Any]:
    run_id = run_id or new_episode_id(robot, task)
    params = StdioServerParameters(command=sys.executable,
                                   args=server_args(robot, task, mode, seed, run_id, brain.name, record),
                                   cwd=str(paths.HOME), env=server_env())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            await brain.run(session, init.instructions or "", task_prompt(robot, task, mode), tools, max_turns)
    return _finalise(run_id, brain)


def run_episode(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(run_episode_async(*args, **kwargs))


def server_env() -> dict[str, str]:
    """Environment for the robot server process (results go to this process's runs dir)."""
    return {**os.environ, "ROBOWORLD_RUNS_DIR": str(paths.RUNS_DIR), "ROBOWORLD_HOME": str(paths.HOME),
            "ROBOWORLD_LIBRARY_DIR": str(paths.LIBRARY_DIR)}


def mcp_config(robot: str, task: str, mode: str, seed: int, run_id: str, brain: str,
               record: bool = True) -> dict[str, Any]:
    """Config any MCP client can use to launch this episode's robot server."""
    return {"mcpServers": {"robot": {"command": sys.executable,
                                     "args": server_args(robot, task, mode, seed, run_id, brain, record),
                                     "cwd": str(paths.HOME),
                                     "env": {"ROBOWORLD_RUNS_DIR": str(paths.RUNS_DIR),
                                             "ROBOWORLD_HOME": str(paths.HOME),
                                             "ROBOWORLD_LIBRARY_DIR": str(paths.LIBRARY_DIR)}}}}


def codex_flags(cfg: dict[str, Any], name: str = "robot") -> str:
    """`codex exec -c ...` overrides that register the robot server for one run (TOML values)."""
    server = cfg["mcpServers"]["robot"]
    env = ", ".join(f"{k} = {json.dumps(v)}" for k, v in server["env"].items())
    overrides = {
        "command": json.dumps(server["command"]),
        "args": "[" + ", ".join(json.dumps(a) for a in server["args"]) + "]",
        "cwd": json.dumps(server["cwd"]),
        "env": "{ " + env + " }",
        "startup_timeout_sec": "60",
        "tool_timeout_sec": "900",  # long skills (a full push) can take minutes on a busy machine
        "default_tools_approval_mode": json.dumps("approve"),  # headless: nobody is there to approve
    }
    return " ".join(f"-c {shlex.quote(f'mcp_servers.{name}.{k}={v}')}" for k, v in overrides.items())


def run_command_brain(robot: str, task: str, command: str, mode: str = "paused", seed: int = 0,
                      run_id: str | None = None, timeout: float = 1800.0, record: bool = True) -> dict[str, Any]:
    """Run an external agent CLI as the brain. ``command`` may use {prompt}, {mcp_config},
    {codex_flags}, {run_dir} and {run_id}."""
    command = PRESETS.get(command, command)
    run_id = run_id or new_episode_id(robot, task)
    run_dir = paths.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    label = shlex.split(command)[0]
    cfg = mcp_config(robot, task, mode, seed, run_id, label, record)
    cfg_path = run_dir / "mcp_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    cmd = command.format(prompt=shlex.quote(task_prompt(robot, task, mode)), mcp_config=shlex.quote(str(cfg_path)),
                         codex_flags=codex_flags(cfg), run_dir=shlex.quote(str(run_dir)), run_id=run_id)
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(paths.HOME))
    (run_dir / "brain_stdout.txt").write_text(proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else ""))
    if not (run_dir / "result.json").exists():
        raise RuntimeError(f"the agent never started the robot server; see {run_dir / 'brain_stdout.txt'}")
    result = _finalise(run_id)
    result["brain_stats"]["command"] = command
    # Agent CLIs (Codex prints "model: ...") usually say which model they ran; keep it for comparisons.
    found = re.search(r"^model:\s*(\S+)", proc.stdout + "\n" + proc.stderr, re.MULTILINE)
    if found:
        result["brain_stats"]["model"] = found.group(1)
        result["brain"] = f"{label}:{found.group(1)}"
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def episode_summary(result: dict[str, Any]) -> dict[str, Any]:
    keys = ("run_id", "robot", "task", "mode", "brain", "status", "success", "success_time_s", "progress",
            "sim_time_s", "wall_time_s", "brain_stats", "view_with")
    return {k: result.get(k) for k in keys}


def results_dir(run_id: str) -> Path:
    return paths.RUNS_DIR / run_id
