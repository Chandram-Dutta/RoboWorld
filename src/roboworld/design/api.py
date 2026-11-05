"""Design operations shared by the CLI and the builder MCP server.

These are tools: a person, or the LLM they work with, does the designing. Each
call validates, compiles, checks and records history, and returns what to look
at next.
"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError

from roboworld.design import store
from roboworld.design.checks import run_checks
from roboworld.design.spec import RoboSpec, apply_changes, list_templates, load_template, servo_catalog


def _spec(data: dict[str, Any]) -> RoboSpec:
    try:
        return RoboSpec(**data)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'spec'}: {err['msg']}" for err in e.errors())
        raise ValueError(f"invalid design: {problems}") from None


def _changes(changes: str | dict[str, Any] | None) -> dict[str, Any]:
    if changes is None or changes == "":
        return {}
    data = yaml.safe_load(changes) if isinstance(changes, str) else changes
    if not isinstance(data, dict):
        raise ValueError("changes must be a mapping, e.g. {all_legs: {thigh: 0.1}}")
    return data


def _finish(design: store.Design, check: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"name": design.name, "parent": design.meta.get("parent"),
                           "digest": design.meta.get("digest"), "spec": design.spec.model_dump(exclude_defaults=True)}
    if check:
        report = run_checks(design.name)
        store.update_meta(design.name, check=report)
        out["check"] = report
    out["next"] = (f"rw design compare {design.name} <other> --tasks ...  |  rw episode --robot {design.name} ...  "
                   f"|  rw design tune {design.name}")
    return out


def templates() -> dict[str, str]:
    return list_templates()


def servos() -> dict[str, dict[str, Any]]:
    return servo_catalog()


def new(name: str, template: str, changes: str | dict | None = None, note: str = "", check: bool = True,
        overwrite: bool = False) -> dict[str, Any]:
    data = apply_changes(load_template(template), _changes(changes))
    data["name"] = name
    return _finish(store.save(_spec(data), note=note or f"from template {template}", overwrite=overwrite), check)


def derive(parent: str, name: str, changes: str | dict | None, note: str = "", check: bool = True,
           overwrite: bool = False) -> dict[str, Any]:
    base = store.load(parent).spec.model_dump()
    data = apply_changes(base, _changes(changes))
    data["name"] = name
    return _finish(store.save(_spec(data), parent=parent, note=note, overwrite=overwrite), check)


def check(name: str) -> dict[str, Any]:
    report = run_checks(name)
    try:
        store.update_meta(name, check=report)
    except FileNotFoundError:
        pass  # built-in robots have no design folder
    return report


def show(name: str) -> dict[str, Any]:
    d = store.load(name)
    return {"spec": d.spec.model_dump(), "meta": d.meta}


def history(name: str) -> list[dict[str, Any]]:
    return store.history(name)


def designs() -> list[dict[str, Any]]:
    return store.list_designs()


def compare(robots: list[str], tasks: list[str] | str = "all", seeds: int = 2, brain: str = "baseline",
            parallel: int = 3) -> dict[str, Any]:
    """Same brain, same tasks, same seeds: differences come from the bodies."""
    from roboworld.bench import compatible, run_bench

    task_list = ["all"] if tasks == "all" else (tasks if isinstance(tasks, list) else tasks.split(","))
    out = run_bench(robots, task_list, [brain], seeds, parallel=parallel, name="compare-" + "-vs-".join(robots))
    by_robot: dict[str, dict[str, Any]] = {}
    for key, cell in out["cells"].items():
        _, robot, task = key.split("|")
        r = by_robot.setdefault(robot, {"successes": 0, "episodes": 0, "tasks": {}})
        r["successes"] += cell["successes"]
        r["episodes"] += cell["episodes"]
        r["tasks"][task] = f"{cell['successes']}/{cell['episodes']}"
    for r in by_robot.values():
        r["success_rate"] = round(r["successes"] / r["episodes"], 3) if r["episodes"] else 0.0
    skipped = sorted({t for t in out["tasks"] for rb in robots if not compatible(rb, t)})
    return {"brain": brain, "seeds": seeds, "robots": by_robot, "skipped_incompatible": skipped,
            "report": out["report"]}


def tune(name: str, course: str = "flat", trials: int = 24, new_name: str | None = None,
         save: bool = True) -> dict[str, Any]:
    from roboworld.design.tune import tune as run_tune

    result = run_tune(name, course=course, trials=trials)
    if save and result["best_score_m"] > result["baseline_score_m"]:
        child = new_name or f"{name}_tuned_{course}"
        note = (f"gait tuned on {course}: {result['baseline_score_m']} m -> {result['best_score_m']} m "
                f"({result['trials']} trials)")
        result["saved_as"] = derive(name, child, {"gait": result["gait_overrides"]}, note=note, check=True,
                                    overwrite=True)["name"]
    return result
