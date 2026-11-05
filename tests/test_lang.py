"""RoboLang: parsing, manifests, validation, interpreter safety, IK."""

import numpy as np
import pytest

from roboworld.lang.ik import Frame, Kinematics
from roboworld.lang.interpreter import Interpreter
from roboworld.lang.schema import parse_program
from roboworld.lang.validate import check_source
from roboworld.robots import list_robots, load_manifest

ROBOTS = ["open_duck_mini_v2", "go2", "so_arm101"]


def test_parse_round_trip():
    src = """
    robot: open_duck_mini_v2
    do:
      - pose: home
      - parallel:
          - {gait: {type: biped_walk, velocity: {vx: 0.1}}, until: {distance_traveled: 1.0}}
          - {clip: {keys: [{t: 0.3, head.pitch: 0.2}], repeat: 2}}
        race: true
      - repeat: {times: 2, do: [{wait: 0.2}]}
    """
    program = parse_program(src)
    again = parse_program(program.model_dump(exclude_none=True))
    assert again == program
    assert program.do[1].parallel[1].clip.keys[0].joints == {"head.pitch": 0.2}


@pytest.mark.parametrize("bad", [
    "do: [{pose: home, gait: {type: x}}]",          # two verbs
    "do: [{dance: 1}]",                              # unknown verb
    "do: [{wait: 1, until: {timeout: 1, fallen: true}}]",  # condition with two keys
    "do: []",                                        # empty program
])
def test_schema_rejects(bad):
    with pytest.raises(ValueError):  # pydantic ValidationError is a ValueError
        parse_program(bad)


def test_registry_lists_builtin_robots():
    assert set(ROBOTS) <= {r.name for r in list_robots()}


@pytest.mark.parametrize("robot", ROBOTS)
def test_manifest(robot):
    m = load_manifest(robot)
    assert m.joints and m.limbs and m.default_pose in m.poses
    for joints in m.limbs.values():
        assert all(j in m.joints for j in joints)
    for alias in m.aliases:
        assert m.resolve_joint(alias) in m.joints
    with pytest.raises(KeyError, match="Did you mean"):
        m.resolve_joint(next(iter(m.joints))[:-1])


def test_validation_catches_common_mistakes():
    m = load_manifest("open_duck_mini_v2")
    _, report = check_source("""
    do:
      - pose: crouchh
      - gait: {type: quadruped_trot}
      - gait: {type: biped_walk}
      - parallel:
          - {gait: {type: biped_walk}, duration: 1}
          - {pose: home}
      - reach: {effector: beak, pos: [0, 0, 0]}
    """, m)
    text = "\n".join(report.errors)
    assert "Unknown pose 'crouchh'" in text
    assert "not available" in text
    assert "never stops" in text
    assert "already driven" in text
    assert "unknown end effector" in text


def test_validation_ok_and_duration():
    m = load_manifest("open_duck_mini_v2")
    _, report = check_source("do: [{pose: home, duration: 0.5}, {clip: {keys: [{t: 0.5, head.yaw: 0.3}], repeat: 2}}]", m)
    assert report.ok and report.estimated_duration_s == pytest.approx(1.5)


class _State:
    """Minimal stand-in for RobotState for interpreter-only tests."""

    def __init__(self, n):
        self.q = np.zeros(n)
        self.base_pos = np.zeros(3)
        self.base_rot = np.eye(3)
        self.yaw = 0.0
        self.up_z = 1.0


def test_interpreter_clamps_and_rate_limits():
    m = load_manifest("open_duck_mini_v2")
    kin = Kinematics("open_duck_mini_v2", m)
    program = parse_program("do: [{pose: {head_yaw: 99.0}, duration: 0.1}, {wait: 2}]")
    dt = 0.02
    interp = Interpreter(m, kin, program, dt)
    q0 = np.array([m.poses["home"][j] for j in m.joints])
    interp.start(_State(len(q0)), q0)
    i = list(m.joints).index("head_yaw")
    prev = q0[i]
    for k in range(1, 120):
        out = interp.tick(k * dt, _State(len(q0)))
        assert abs(out[i] - prev) <= m.max_joint_speed * dt + 1e-9  # rate limited
        prev = out[i]
    assert prev == pytest.approx(m.joints["head_yaw"].range[1])  # clamped to the limit


@pytest.mark.parametrize("robot", ROBOTS)
def test_ik_reaches_nearby_targets(robot):
    m = load_manifest(robot)
    kin = Kinematics(robot, m)
    q = np.array([m.poses[m.default_pose][j] for j in m.joints])
    effectors = m.feet or list(m.end_effectors)
    frames = kin.fk(q, effectors)
    targets = {e: Frame(f.pos + [0.01, 0.0, 0.01], f.rot) for e, f in frames.items()}
    q2, err = kin.solve(q, targets, iters=30)
    assert err < 2e-3
    reached = kin.fk(q2, effectors)
    for e in effectors:
        assert np.linalg.norm(reached[e].pos - targets[e].pos) < 2e-3
