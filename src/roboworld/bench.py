"""`rw bench`: robots × brains × tasks × seeds, run in parallel, with a comparison report.

Every episode goes through the same robot MCP server, whatever the brain is.
In-process harnesses run concurrently (``jobs`` at a time). External agent
commands run one at a time, since they use your account and rate limits.
Results land in ``runs/<bench_id>/``: ``results.csv``, ``summary.json``,
``report.html`` and one folder per episode under ``episodes/``.
"""

from __future__ import annotations

import asyncio
import csv
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from roboworld import paths
from roboworld.brain import registry, runner
from roboworld.lang.skills import can_move
from roboworld.robots import load_manifest
from roboworld.world.spec import list_tasks, load_task

FIELDS = ["robot", "task", "brain", "seed", "status", "success", "success_time_s", "progress", "sim_time_s",
          "wall_time_s", "tool_calls", "invalid_calls", "claimed_success", "overclaimed", "tokens", "cost_usd",
          "llm_calls", "model", "harness", "run_id", "error"]


@dataclass(frozen=True)
class Job:
    robot: str
    task: str
    brain: str
    seed: int


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", text).strip("-")[:40] or "x"


def compatible(robot: str, task: str) -> bool:
    t = load_task(task)
    if t.robots is not None:
        return robot in t.robots
    return can_move(load_manifest(robot))


def _row(job: Job, label: str, res: dict[str, Any] | None, error: str | None = None) -> dict[str, Any]:
    res = res or {}
    bs = res.get("brain_stats") or {}
    llm = bs.get("llm") or {}
    tokens = (llm.get("prompt_tokens") or 0) + (llm.get("completion_tokens") or 0) or None
    return {
        "robot": job.robot, "task": job.task, "brain": label, "seed": job.seed,
        "status": res.get("status", "error"), "success": bool(res.get("success")),
        "success_time_s": res.get("success_time_s"), "progress": res.get("progress", 0.0),
        "sim_time_s": res.get("sim_time_s"), "wall_time_s": res.get("wall_time_s"),
        "tool_calls": bs.get("tool_calls"), "invalid_calls": bs.get("invalid_calls"),
        "claimed_success": bs.get("claimed_success"), "overclaimed": bool(bs.get("overclaimed")),
        "tokens": tokens, "cost_usd": llm.get("cost_usd"), "llm_calls": llm.get("llm_calls"),
        "model": bs.get("model") or llm.get("model"), "harness": llm.get("harness"), "run_id": res.get("run_id"),
        "error": error,
    }


async def _run_all(jobs: list[Job], mode: str, parallel: int, max_turns: int, record: bool,
                   progress_cb) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(parallel)
    cmd_sem = asyncio.Semaphore(1)
    loop = asyncio.get_running_loop()

    async def one(job: Job) -> dict[str, Any]:
        brain = registry.resolve(job.brain)
        label = brain.name
        run_id = f"{slug(job.robot)}-{slug(job.task)}-{slug(job.brain)}-s{job.seed}"
        try:
            if isinstance(brain, registry.CommandBrain):
                async with cmd_sem:
                    res = await loop.run_in_executor(None, lambda: runner.run_command_brain(
                        job.robot, job.task, brain.command, mode=mode, seed=job.seed, run_id=run_id, record=record))
                label = res.get("brain") or label
            else:
                async with sem:
                    res = await runner.run_episode_async(job.robot, job.task, brain, mode=mode, seed=job.seed,
                                                         max_turns=max_turns, run_id=run_id, record=record)
            row = _row(job, label, res)
        except Exception as e:  # one broken episode shouldn't sink the bench
            row = _row(job, label, None, error=f"{type(e).__name__}: {e}"[:300])
        progress_cb(row)
        return row

    return await asyncio.gather(*(one(j) for j in jobs))


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def agg(group: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(group)
        wins = [r for r in group if r["success"]]
        claims = [r for r in group if r["claimed_success"]]
        times = [r["success_time_s"] for r in wins if r["success_time_s"] is not None]
        calls = [r["tool_calls"] for r in group if r["tool_calls"] is not None]
        tokens = [r["tokens"] for r in group if r["tokens"]]
        costs = [r["cost_usd"] for r in group if r.get("cost_usd") is not None]
        return {
            "episodes": n, "successes": len(wins), "success_rate": round(len(wins) / n, 3) if n else 0.0,
            "mean_progress": round(sum(r["progress"] or 0 for r in group) / n, 3) if n else 0.0,
            "mean_success_time_s": round(sum(times) / len(times), 1) if times else None,
            "mean_tool_calls": round(sum(calls) / len(calls), 1) if calls else None,
            "invalid_calls": sum(r["invalid_calls"] or 0 for r in group),
            "overclaim_rate": round(sum(r["overclaimed"] for r in claims) / len(claims), 3) if claims else None,
            "mean_tokens": round(sum(tokens) / len(tokens)) if tokens else None,
            "mean_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
            "cost_per_success_usd": round(sum(costs) / len(wins), 4) if costs and wins else None,
            "errors": sum(1 for r in group if r["error"]),
        }

    brains = sorted({r["brain"] for r in rows})
    by_brain = {b: agg([r for r in rows if r["brain"] == b]) for b in brains}
    cells: dict[str, dict[str, Any]] = {}
    for b in brains:
        for robot in sorted({r["robot"] for r in rows}):
            for task in sorted({r["task"] for r in rows}):
                group = [r for r in rows if r["brain"] == b and r["robot"] == robot and r["task"] == task]
                if group:
                    cells[f"{b}|{robot}|{task}"] = agg(group)
    leaderboard = sorted(by_brain.items(), key=lambda kv: (-kv[1]["success_rate"], -kv[1]["mean_progress"]))
    return {"by_brain": by_brain, "cells": cells, "leaderboard": [b for b, _ in leaderboard]}


def run_bench(robots: list[str], tasks: list[str], brains: list[str], seeds: int, mode: str = "paused",
              parallel: int = 3, max_turns: int = 40, record: bool = False, name: str = "",
              progress_cb=lambda row: None) -> dict[str, Any]:
    if tasks == ["all"]:
        tasks = [t.name for t in list_tasks()]
    for b in brains:
        registry.resolve(b)  # fail fast on typos
    jobs = [Job(r, t, b, s) for b in brains for r in robots for t in tasks for s in range(seeds) if compatible(r, t)]
    bench_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-bench" + (f"-{slug(name)}" if name else "")
    out = paths.RUNS_DIR / bench_id
    episodes = out / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    meta = {"bench_id": bench_id, "created": datetime.now().isoformat(timespec="seconds"), "mode": mode,
            "robots": robots, "tasks": tasks, "brains": brains, "seeds": seeds, "episodes": len(jobs)}
    original = paths.RUNS_DIR
    paths.RUNS_DIR = episodes  # every episode (and its robot server) writes inside the bench folder
    try:
        rows = asyncio.run(_run_all(jobs, mode, parallel, max_turns, record, progress_cb))
    finally:
        paths.RUNS_DIR = original
    summary = summarise(rows)
    with (out / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.json").write_text(json.dumps({**meta, **summary}, indent=2))
    (out / "report.html").write_text(render_report(meta, rows, summary))
    return {**meta, "dir": str(out), "report": str(out / "report.html"), **summary}


# --------------------------------------------------------------------- report
def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.0f}%"


def render_report(meta: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    e = html.escape
    robots = sorted({r["robot"] for r in rows})
    tasks = sorted({r["task"] for r in rows})
    lb_rows = []
    for rank, b in enumerate(summary["leaderboard"], 1):
        a = summary["by_brain"][b]
        lb_rows.append(
            f"<tr><td>{rank}</td><td class=name>{e(b)}</td><td><b>{_pct(a['success_rate'])}</b> "
            f"<span class=dim>{a['successes']}/{a['episodes']}</span></td><td>{_pct(a['mean_progress'])}</td>"
            f"<td>{a['mean_success_time_s'] or '–'}</td><td>{a['mean_tool_calls'] or '–'}</td>"
            f"<td>{a['invalid_calls']}</td><td>{_pct(a['overclaim_rate'])}</td><td>{a['mean_tokens'] or '–'}</td>"
            f"<td>{'$%.4f' % a['mean_cost_usd'] if a['mean_cost_usd'] is not None else '–'}</td>"
            f"<td>{'$%.4f' % a['cost_per_success_usd'] if a['cost_per_success_usd'] is not None else '–'}</td>"
            f"<td>{a['errors'] or ''}</td></tr>")
    head = "".join(f"<th>{e(t)}</th>" for t in tasks)
    grid = []
    for b in summary["leaderboard"]:
        for robot in robots:
            cells = []
            for t in tasks:
                c = summary["cells"].get(f"{b}|{robot}|{t}")
                if c is None:
                    cells.append("<td class=na>n/a</td>")
                    continue
                rate = c["success_rate"]
                time_s = f"<div class=dim>{c['mean_success_time_s']} s</div>" if c["mean_success_time_s"] else ""
                cells.append(f"<td style='--r:{rate}' class=cell>{c['successes']}/{c['episodes']}{time_s}</td>")
            grid.append(f"<tr><td class=name>{e(b)}</td><td>{e(robot)}</td>{''.join(cells)}</tr>")
    ep_rows = []
    for r in sorted(rows, key=lambda r: (r["brain"], r["robot"], r["task"], r["seed"])):
        status = "✓" if r["success"] else ("⚠ " + e(r["error"]) if r["error"] else e(str(r["status"])))
        claim = "claimed ✓, wasn't" if r["overclaimed"] else ""
        ep_rows.append(
            f"<tr><td>{e(r['brain'])}</td><td>{e(r['robot'])}</td><td>{e(r['task'])}</td><td>{r['seed']}</td>"
            f"<td>{status}</td><td>{_pct(r['progress'])}</td><td>{r['success_time_s'] or '–'}</td>"
            f"<td>{r['tool_calls'] if r['tool_calls'] is not None else '–'}</td><td class=warn>{claim}</td>"
            f"<td class=mono>{e(str(r['run_id'] or ''))}</td></tr>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RoboWorld bench</title>
<style>
:root {{ --bg:#fbfbfa; --fg:#1d1d1f; --dim:#6e6e73; --line:#e3e3e0; --good:46,160,90; --card:#fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#ececee; --dim:#9a9aa0; --line:#2c2c30;
  --card:#1c1c1f; }} }}
body {{ background:var(--bg); color:var(--fg); font:14px/1.45 -apple-system, system-ui, sans-serif;
  margin:0; padding:24px 16px 48px; }}
main {{ max-width:1200px; margin:0 auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:28px 0 8px; }}
.dim {{ color:var(--dim); font-size:12px; }} .mono {{ font-family:ui-monospace, monospace; font-size:12px; }}
.wrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }}
th {{ font-size:12px; color:var(--dim); font-weight:600; }}
.cell {{ background:rgba(var(--good), calc(var(--r) * 0.55)); text-align:center; }}
.na {{ color:var(--dim); text-align:center; }} .name {{ font-weight:600; }} .warn {{ color:#d9822b; }}
</style></head><body><main>
<h1>RoboWorld bench</h1>
<div class=dim>{e(meta['bench_id'])} · {e(meta['created'])} · mode {e(meta['mode'])} · {meta['seeds']} seed(s) ·
{meta['episodes']} episodes</div>
<h2>Leaderboard (brains)</h2>
<div class=wrap><table><tr><th>#</th><th>brain</th><th>success</th><th>progress</th><th>time to success (s)</th>
<th>tool calls</th><th>invalid calls</th><th>overclaim rate</th><th>tokens/episode</th><th>cost/episode</th>
<th>cost/success</th><th>errors</th></tr>
{''.join(lb_rows)}</table></div>
<p class=dim>Overclaim rate: of the episodes where the brain said it succeeded, how often the simulator disagreed.</p>
<h2>Success by task</h2>
<div class=wrap><table><tr><th>brain</th><th>robot</th>{head}</tr>{''.join(grid)}</table></div>
<h2>Episodes</h2>
<div class=wrap><table><tr><th>brain</th><th>robot</th><th>task</th><th>seed</th><th>result</th><th>progress</th>
<th>time (s)</th><th>tool calls</th><th></th><th>run</th></tr>{''.join(ep_rows)}</table></div>
<p class=dim>Replay an episode (if recorded): <span class=mono>ROBOWORLD_RUNS_DIR=runs/{e(meta['bench_id'])}/episodes
rw view &lt;run&gt;</span></p>
</main></body></html>"""
