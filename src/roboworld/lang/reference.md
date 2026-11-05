# RoboLang reference

RoboLang is how you make a robot move. A program is YAML (or JSON) with a `do:` list
of steps. Each step has exactly one **verb**. Angles are radians, distances metres,
times seconds. Call `describe_robot` first: it lists the robot's joints, aliases,
limbs, end-effectors, named poses and gaits.

```yaml
robot: open_duck_mini_v2      # optional; checked against the robot it runs on
on_fall: stop                 # stop (default) | continue
do:
  - pose: home                # verb + its fields
    duration: 0.5
```

## Verbs

| verb | what it does | key fields |
|---|---|---|
| `pose` | move joints to a named pose or `{joint: angle}` | `duration` (0.6), `ease`, `relative`, `hold` |
| `clip` | keyframe animation | `keys: [{t, <joint>: angle, pose?}]`, `repeat`, `ease`, `relative` |
| `gait` | walk / trot with a velocity command | `type`, `velocity: {vx, vy, wz}`, `period`, `step_height`, `body_height`, `stabilizer`, `params`; needs `duration` or `until` |
| `reach` | move an end-effector to a point (IK) | `effector`, `pos: [x,y,z]`, `frame: base\|world`, `relative`, `duration` |
| `wait` | hold still | seconds, or `null` with `until` |
| `repeat` | loop a block | `{times, do: [...]}` |
| `parallel` | run blocks at once on **different** joints | list of steps; `race: true` ends when the first finishes |
| `do` | a plain block (handy inside `parallel`) | list of steps |

Every step also accepts `label:` (shows in the event log) and `until:` (end early).

**Joint names.** Use the exact joint name, an alias such as `head.pitch`, or
`<limb>.<suffix>` such as `left_leg.knee`. A key in a clip may mix a named `pose`
with joint overrides.

**Easing.** `min_jerk` (default, smooth), `cubic`, or `linear`.

**Gaits.** The velocity is in the body frame: `vx` forward, `vy` left, `wz` turn
(rad/s, positive = left). Gaits ramp in and stop gracefully: they finish the step
in progress and settle before the next step runs. Leave optional fields out to use
the robot's tuned defaults. `body_height` raises (+) or lowers (−) the body.
`stabilizer: none` disables tilt feedback.

## Conditions (`until`)

Exactly one key per condition, measured from when the step started:

- `timeout: s`
- `distance_traveled: m` (ground path)
- `displacement: m` (straight line)
- `turned: deg`
- `fallen: true`
- `reached: [x, y, tol]` (world)
- `any: [...]`
- `all: [...]`

## Safety (always on)

- Targets are clamped to joint limits.
- Joint speed is limited to what the servos can do.
- If the robot tips past ~60° the program stops (`on_fall: stop`).
- Validation reports unknown names, gaits with no stopping condition, and parallel
  branches that fight over the same joints.

## Examples

Walk 1 m while nodding, then look around:

```yaml
do:
  - parallel:
      - gait: {type: biped_walk, velocity: {vx: 0.12}}
        until: {any: [{distance_traveled: 1.0}, {timeout: 15}]}
      - clip: {keys: [{t: 0.4, head.pitch: 0.25}, {t: 0.4, head.pitch: -0.15}], repeat: 8}
    race: true
  - clip:
      keys:
        - {t: 0.6, head.yaw: 0.8}
        - {t: 1.0, head.yaw: -0.8}
        - {t: 0.6, head.yaw: 0.0}
```

Turn on the spot about 90° (quadruped):

```yaml
do:
  - gait: {type: quadruped_trot, velocity: {wz: 0.8}}
    until: {any: [{turned: 90}, {timeout: 6}]}
```

Arm: move the gripper 5 cm up, then close the gripper:

```yaml
do:
  - reach: {effector: gripper, pos: [0, 0, 0.05], relative: true, duration: 1.0}
  - pose: gripper_closed
    duration: 0.4
```

## Tips for writing good motions

- Start from the robot's `default_pose`. Return to it before starting a gait.
- Keep keyframes at least 0.15 s apart for large moves (servos are slow).
- Use `simulate`. Look at `fell`, `forward_m`, `lateral_drift_m`,
  `heading_change_deg`, `peak_torque_ratio` (>0.9 means the servos are struggling)
  and the snapshots. Adjust and try again.
