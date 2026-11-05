"""Run storage: one directory per run under ``runs/``."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from roboworld import paths


def new_run_dir(robot: str) -> tuple[str, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{robot}-{secrets.token_hex(2)}"
    run_dir = paths.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not paths.RUNS_DIR.exists():
        return []
    out = []
    for d in sorted(paths.RUNS_DIR.iterdir(), reverse=True):
        f = d / "result.json"
        if f.exists():
            data = json.loads(f.read_text())
            out.append({k: data.get(k) for k in ("run_id", "robot", "status", "program_name")}
                       | {"forward_m": data.get("metrics", {}).get("forward_m"),
                          "fell": data.get("metrics", {}).get("fell")})
        if len(out) >= limit:
            break
    return out


def run_dir(run_id: str) -> Path:
    if run_id == "latest":
        runs = list_runs(1)
        if not runs:
            raise FileNotFoundError("no runs yet")
        run_id = runs[0]["run_id"]
    d = paths.RUNS_DIR / run_id
    if not d.exists():
        matches = sorted(paths.RUNS_DIR.glob(f"*{run_id}*")) if paths.RUNS_DIR.exists() else []
        if len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(f"run '{run_id}' not found")
    return d


def load_run(run_id: str) -> dict[str, Any]:
    return json.loads((run_dir(run_id) / "result.json").read_text())
