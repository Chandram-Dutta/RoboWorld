"""Simulation: robots stand, gaits walk where they are told, runs are recorded."""

import json

import pytest

from roboworld import api
from roboworld.sim.runner import Simulation


@pytest.fixture(scope="module")
def duck():
    return Simulation("open_duck_mini_v2")


@pytest.fixture(scope="module")
def go2():
    return Simulation("go2")


@pytest.mark.parametrize("robot", ["open_duck_mini_v2", "go2", "so_arm101"])
def test_robots_stand_still(robot):
    r = Simulation(robot).run("do: [{wait: 2}]", save=False)
    assert r.status == "completed"
    assert not r.metrics["fell"]
    assert r.metrics["displacement_m"] < 0.02
    assert r.metrics["max_tilt_deg"] < 3


def test_go2_trots_forward_straight(go2):
    r = go2.run("do: [{gait: {type: quadruped_trot, velocity: {vx: 0.4}}, duration: 6}]", save=False)
    m = r.metrics
    assert r.status == "completed" and not m["fell"]
    assert m["forward_m"] > 1.0
    assert abs(m["heading_change_deg"]) < 10


def test_go2_turns(go2):
    r = go2.run("do: [{gait: {type: quadruped_trot, velocity: {wz: 0.8}}, until: {turned: 90}}]", save=False)
    assert r.status == "completed"
    assert 80 < r.metrics["heading_change_deg"] < 120


@pytest.mark.parametrize("velocity,check", [
    ("{vx: 0.1}", lambda m: m["forward_m"] > 0.4 and abs(m["heading_change_deg"]) < 10),
    ("{vx: -0.08}", lambda m: m["forward_m"] < -0.2),
    ("{wz: 0.5}", lambda m: m["heading_change_deg"] > 60),
    ("{vy: 0.05}", lambda m: m["lateral_drift_m"] > 0.1),
])
def test_duck_walks_without_falling(duck, velocity, check):
    r = duck.run(f"do: [{{gait: {{type: biped_walk, velocity: {velocity}}}, duration: 6}}]", save=False)
    assert r.status == "completed", r.events
    assert not r.metrics["fell"]
    assert check(r.metrics), r.metrics


def test_until_distance_ignores_gait_sway(duck):
    r = duck.run("do: [{gait: {type: biped_walk, velocity: {vx: 0.12}}, until: {distance_traveled: 0.5}}]",
                 save=False)
    assert r.status == "completed"
    assert 0.4 < r.metrics["forward_m"] < 0.7


def test_fall_is_detected_and_stops(duck):
    # Throwing the legs to their limits while standing tips the duck over.
    r = duck.run("do: [{pose: {left_hip_roll: 0.43, right_hip_roll: 0.43, left_knee: -1.5}, duration: 0.2}, "
                 "{wait: 3}]", save=False)
    assert r.status == "fell"
    assert any(e["kind"] == "fall" for e in r.events)


def test_simulate_api_records_run(tmp_path, monkeypatch):
    from roboworld import paths, store

    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(store.paths, "RUNS_DIR", tmp_path)
    out = api.simulate("so_arm101", "do: [{reach: {effector: gripper, pos: [0, 0, 0.03], relative: true}}]")
    assert out["status"] == "completed"
    run = store.run_dir(out["run_id"])
    for name in ("program.yaml", "result.json", "recording.rrd", "trajectory.npz", "contact_sheet.png"):
        assert (run / name).exists(), name
    assert json.loads((run / "result.json").read_text())["run_id"] == out["run_id"]


def test_simulate_api_rejects_invalid():
    out = api.simulate("open_duck_mini_v2", "do: [{gait: {type: biped_walk}}]")
    assert out["status"] == "invalid"
    assert out["validation"]["errors"]
