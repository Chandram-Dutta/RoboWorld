"""Design checks: is this robot physically sensible, and can it stand, walk and turn?

Each check reports pass / warn / fail with a number and a reason, so a person
(or an LLM designing with these tools) knows what to change.
"""

from __future__ import annotations

from typing import Any

import mujoco
import numpy as np

from roboworld.robots import load_manifest, load_robot_spec
from roboworld.sim.runner import Simulation


def _check(name: str, status: str, value: Any, detail: str) -> dict[str, Any]:
    return {"check": name, "status": status, "value": value, "detail": detail}


def overlapping_parts(robot: str) -> list[tuple[str, str]]:
    """Pairs of robot bodies whose geometry intersects at the default pose (adjacent bodies excluded)."""
    spec = load_robot_spec(robot)
    m = load_manifest(robot)
    for g in spec.geoms:
        g.contype, g.conaffinity = 1, 1
    model = spec.compile()
    data = mujoco.MjData(model)
    for j, v in m.pose(m.default_pose).items():
        data.qpos[model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)]] = v
    data.qpos[2] += 5.0  # lift it clear of anything else
    mujoco.mj_forward(model, data)
    base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, m.base_body)

    def depth(b: int) -> int:
        d = 0
        while b not in (base, 0):
            b, d = int(model.body_parentid[b]), d + 1
        return d

    def near(a: int, b: int, hops: int = 2) -> bool:
        """Is b an ancestor of a within `hops` levels?"""
        for _ in range(hops):
            a = int(model.body_parentid[a])
            if a == b:
                return True
        return False

    pairs = set()
    for i in range(data.ncon):
        c = data.contact[i]
        b1, b2 = int(model.geom_bodyid[c.geom1]), int(model.geom_bodyid[c.geom2])
        if b1 == b2 or near(b1, b2) or near(b2, b1):
            continue  # a joint's parts are co-located by design (e.g. hip yaw/roll/pitch at one point)
        if base in (b1, b2) and depth(b2 if b1 == base else b1) <= 3:
            continue  # hip/neck mounts sitting in the torso are expected
        name = lambda b: mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b)  # noqa: E731
        pairs.add(tuple(sorted((name(b1), name(b2)))))
    return sorted(pairs)


def run_checks(robot: str, dynamic: bool = True) -> dict[str, Any]:
    m = load_manifest(robot)
    checks: list[dict[str, Any]] = []
    sim = Simulation(robot)
    start = sim.reset()
    leg_len = None
    if m.feet:
        frames = sim.kin.fk(sim.default_targets(), m.feet)
        leg_len = float(-np.mean([f.pos[2] for f in frames.values()]))

    checks.append(_check("mass", "pass" if m.mass < 25 else "warn", round(m.mass, 2), f"total mass {m.mass:.2f} kg"))
    height = float(start.base_pos[2])
    checks.append(_check("standing_height", "pass", round(height, 3), f"torso stands {height:.3f} m high after settling"))

    home = m.pose(m.default_pose)
    bad = [j for j, v in home.items() if not (m.joints[j].range[0] + 0.02 <= v <= m.joints[j].range[1] - 0.02)]
    checks.append(_check("home_pose_in_range", "fail" if bad else "pass", len(bad),
                          f"joints at their limit in the standing pose: {bad}" if bad else "all joints inside their range"))

    overlaps = overlapping_parts(robot)
    checks.append(_check("parts_overlap", "warn" if overlaps else "pass", len(overlaps),
                         f"parts intersect at the standing pose: {overlaps[:4]}" if overlaps else "no intersecting parts"))

    stand = sim.run("do: [{wait: 2.0}]", save=False)
    sm = stand.metrics
    ratio = sm["peak_torque_ratio"]
    status = "fail" if stand.status == "fell" else ("pass" if ratio < 0.6 else "warn" if ratio < 0.9 else "fail")
    checks.append(_check("stands", "fail" if stand.status == "fell" else "pass", stand.status,
                         "stands still for 2 s" if stand.status != "fell" else "falls over while standing"))
    checks.append(_check("standing_torque", status, ratio,
                         f"peak servo load while standing is {ratio:.0%} of the torque limit (aim for < 60%)"))
    sag = float(start.base_pos[2] - sm["min_base_height_m"])
    if leg_len:
        status = "pass" if sag < 0.05 * leg_len else "warn"
        checks.append(_check("sag", status, round(sag, 4), f"body sinks {1000 * sag:.1f} mm while standing "
                                                            f"(aim for < {50 * leg_len:.1f} mm)"))

    gait = m.default_gait
    if dynamic and gait:
        limits = m.gaits.get(gait, {}).get("limits", {})
        vx = 0.85 * float(limits.get("vx", [0, 0.2])[1])  # the speed skills like walk_to actually use
        wz = 0.85 * float(limits.get("wz", [-0.6, 0.6])[1])
        walk = Simulation(robot).run(f"do: [{{gait: {{type: {gait}, velocity: {{vx: {vx:.3f}}}}}, duration: 5}}]",
                                     save=False)
        wm = walk.metrics
        expected = vx * 4.0
        if walk.status == "fell":
            status, detail = "fail", f"falls while walking at {vx:.2f} m/s"
        elif wm["forward_m"] < 0.4 * expected:
            status, detail = "warn", f"walked {wm['forward_m']:.2f} m of ~{expected:.2f} m expected"
        else:
            status, detail = "pass", f"walked {wm['forward_m']:.2f} m in 5 s at {vx:.2f} m/s command"
        checks.append(_check("walks", status, wm["forward_m"], detail))
        drift = wm["heading_change_deg"]
        checks.append(_check("walk_straightness", "pass" if abs(drift) < 15 else "warn", drift,
                             f"heading drifts {drift:.1f}° while walking straight (aim for < 15°)"))
        load, sat = wm["mean_servo_load"], wm["torque_saturation_pct"]
        checks.append(_check("walking_effort", "info", load,
                             f"average servo effort while walking is {load:.0%} of the torque limit, at the limit "
                             f"{sat:.0f}% of the time. Position servos push in proportion to how far they lag, "
                             "so this tracks how hard the gait drives them; capacity is the standing_torque check"))
        turn = Simulation(robot).run(f"do: [{{gait: {{type: {gait}, velocity: {{wz: {wz:.3f}}}}}, duration: 5}}]",
                                     save=False)
        tm = turn.metrics
        status = "fail" if turn.status == "fell" else ("pass" if abs(tm["heading_change_deg"]) > 45 else "warn")
        checks.append(_check("turns", status, tm["heading_change_deg"],
                             f"turned {abs(tm['heading_change_deg']):.0f}° in 5 s at {wz:.2f} rad/s (aim for > 45°)"))

    worst = "fail" if any(c["status"] == "fail" for c in checks) else (
        "warn" if any(c["status"] == "warn" for c in checks) else "pass")
    fails = [c["check"] for c in checks if c["status"] in ("warn", "fail")]
    return {"robot": robot, "summary": worst + (f" ({', '.join(fails)})" if fails else ""), "status": worst,
            "checks": checks}
