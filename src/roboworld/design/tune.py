"""Tune a design's gait on a test course: random search, then refine around the best.

The objective is simple and physical: how far the robot gets in a fixed time
(walking straight ahead, on flat ground or across a task's terrain), with a
penalty for falling. Runs in parallel on CPU cores; no GPU or learning needed.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from roboworld import paths

COURSES = {"flat": None, "bumpy": "bumpy_field"}


def search_space(kind: str, leg_len: float) -> dict[str, tuple[float, float]]:
    if kind == "biped":
        return {"period": (0.45, 1.0), "step_height": (0.1 * leg_len, 0.6 * leg_len),
                "double_support": (0.15, 0.45), "tilt_gain": (0.0, 1.0), "speed": (0.4, 1.0)}
    return {"period": (0.3, 0.8), "step_height": (0.2 * leg_len, 0.5 * leg_len), "duty_factor": (0.5, 0.75),
            "tilt_gain": (0.0, 1.0), "speed": (0.4, 1.0)}


def _program(gait: str, vmax: float, p: dict[str, float], seconds: float) -> str:
    extra = {k: round(v, 4) for k, v in p.items() if k in ("period", "step_height", "double_support", "duty_factor")}
    fields = ", ".join(f"{k}: {v}" for k, v in extra.items())
    vx = round(p["speed"] * vmax, 4)
    return (f"do: [{{gait: {{type: {gait}, velocity: {{vx: {vx}}}, {fields}, "
            f"params: {{tilt_gain: {round(p['tilt_gain'], 3)}}}}}, duration: {seconds}}}]")


def evaluate(job: tuple[str, str | None, dict[str, float], list[int], float, str]) -> float:
    """Mean metres gained per trial (minus a fall penalty). Runs in a worker process."""
    robot, course, p, seeds, seconds, library = job
    paths.LIBRARY_DIR = paths.Path(library)  # workers see the same design library
    from roboworld.robots import load_manifest
    from roboworld.sim.runner import Simulation
    from roboworld.world.spec import load_world

    m = load_manifest(robot)
    gait = m.default_gait
    vmax = float(m.gaits[gait]["limits"]["vx"][1])
    scores = []
    for seed in seeds:
        world = load_world(course).resolved(seed) if course else None
        res = Simulation(robot, world).run(_program(gait, vmax, p, seconds), save=False)
        score = float(res.metrics["forward_m"])
        if res.metrics["fell"]:
            score -= 0.5
        scores.append(score)
    return float(np.mean(scores))


def tune(robot: str, course: str = "flat", trials: int = 24, seeds: int = 2, seconds: float = 8.0,
         workers: int = 4, rng_seed: int = 0) -> dict[str, Any]:
    from roboworld.robots import load_manifest
    from roboworld.sim.runner import Simulation

    if course not in COURSES:
        raise KeyError(f"unknown course '{course}'; choose from {sorted(COURSES)}")
    m = load_manifest(robot)
    sim = Simulation(robot)
    frames = sim.kin.fk(sim.default_targets(), m.feet)
    leg_len = float(-np.mean([f.pos[2] for f in frames.values()]))
    space = search_space(m.kind, leg_len)
    gait_defaults = m.gaits[m.default_gait]
    baseline = {k: float(gait_defaults.get(k, gait_defaults.get("params", {}).get(k, (lo + hi) / 2)))
                for k, (lo, hi) in space.items() if k != "speed"} | {"speed": 0.6}
    rng = np.random.default_rng(rng_seed)
    seed_list = list(range(seeds))
    library = str(paths.LIBRARY_DIR)

    def sample(center: dict[str, float] | None, scale: float) -> dict[str, float]:
        out = {}
        for k, (lo, hi) in space.items():
            if center is None:
                out[k] = float(rng.uniform(lo, hi))
            else:
                out[k] = float(np.clip(center[k] + rng.normal(0, scale * (hi - lo)), lo, hi))
        return out

    explore = max(trials // 2, 2)
    candidates = [baseline] + [sample(None, 1.0) for _ in range(explore - 1)]
    tried: list[tuple[float, dict[str, float]]] = []
    with ProcessPoolExecutor(workers) as pool:
        scores = list(pool.map(evaluate, [(robot, COURSES[course], c, seed_list, seconds, library)
                                          for c in candidates]))
        tried += list(zip(scores, candidates, strict=True))
        best = max(tried, key=lambda t: t[0])[1]
        refine = [sample(best, 0.12) for _ in range(trials - explore)]
        scores = list(pool.map(evaluate, [(robot, COURSES[course], c, seed_list, seconds, library) for c in refine]))
        tried += list(zip(scores, refine, strict=True))
    tried.sort(key=lambda t: -t[0])
    best_score, best = tried[0]
    base_score = next(s for s, c in tried if c is baseline)
    vmax = float(gait_defaults["limits"]["vx"][1])
    overrides = {k: round(v, 4) for k, v in best.items() if k in ("period", "step_height", "double_support",
                                                                   "duty_factor")}
    overrides["params"] = {"tilt_gain": round(best["tilt_gain"], 3)}
    return {"robot": robot, "course": course, "trials": len(tried), "baseline_score_m": round(base_score, 3),
            "best_score_m": round(best_score, 3), "best": {k: round(v, 4) for k, v in best.items()},
            "suggested_speed_mps": round(best["speed"] * vmax, 3), "gait_overrides": overrides,
            "top5": [{"score_m": round(s, 3), **{k: round(v, 3) for k, v in c.items()}} for s, c in tried[:5]]}
