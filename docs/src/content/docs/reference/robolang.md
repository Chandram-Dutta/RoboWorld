---
title: RoboLang reference
description: The complete RoboLang syntax - programs, verbs, gaits, conditions and validation rules.
---

RoboLang programs are YAML or JSON. Units are radians, metres and seconds. Unknown fields are
errors, so typos are caught before a program runs. `rw lang` prints a condensed version of this
page, and the builder MCP server returns it from `language_reference`.

## Program

```yaml
robot: go2              # optional; checked against the robot the program runs on
name: trot a square     # optional
description: ...        # optional
on_fall: stop           # stop (default) | continue
do:                     # required: one or more steps
  - ...
```

A bare list of steps is also accepted and treated as the `do` list.

## Steps

Every step has exactly one **verb**, plus these optional fields:

| Field | Type | Meaning |
|---|---|---|
| `label` | string | A name shown in the event log |
| `until` | [condition](#conditions) | End the step early when the condition holds |

### `pose`

Moves joints to a named pose or to explicit angles.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `pose` | string or `{joint: radians}` | required | A named pose, or a map of joints to angles |
| `duration` | number > 0 | `0.6` | Seconds to get there |
| `ease` | `min_jerk`, `cubic`, `linear` | `min_jerk` | Interpolation curve |
| `relative` | boolean | `false` | Treat angles as offsets from the current targets |
| `hold` | number ≥ 0 | `0` | Seconds to hold after arriving |

```yaml
- pose: {head.pitch: 0.3, head.yaw: -0.4}
  duration: 0.5
```

### `clip`

Plays keyframes.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `clip.keys` | list of keys | required | At least one keyframe |
| `clip.repeat` | 1–100 | `1` | Number of times to play the keys |
| `clip.ease` | `min_jerk`, `cubic`, `linear` | `min_jerk` | Default curve for every key |
| `clip.relative` | boolean | `false` | Angles are offsets from the targets when the clip starts |

Each key has:

| Field | Type | Meaning |
|---|---|---|
| `t` | number > 0 | Seconds to reach this key from the previous one |
| `pose` | string | Optional named pose to start from |
| `ease` | curve | Optional curve for this key only |
| *any joint name* | number | A joint angle; equivalent to listing it under `joints` |

A key needs a `pose`, joint angles, or both:

```yaml
- clip:
    keys:
      - {t: 0.4, pose: crouch, head.pitch: 0.2}
      - {t: 0.4, joints: {head.pitch: -0.2}}
    repeat: 3
```

### `gait`

Walks with a velocity command. A gait step needs a `duration` or an `until`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `gait.type` | string | required | A gait name, such as `biped_walk` or `quadruped_trot` |
| `gait.velocity.vx` | number | `0` | Forward speed, m/s |
| `gait.velocity.vy` | number | `0` | Sideways speed to the left, m/s |
| `gait.velocity.wz` | number | `0` | Turning rate, rad/s, positive to the left |
| `gait.period` | 0.1–5 | robot default | Seconds per gait cycle |
| `gait.step_height` | 0–0.5 | robot default | Foot lift, m |
| `gait.duty_factor` | 0.2–0.95 | robot default | Fraction of the cycle a foot is down |
| `gait.double_support` | 0–0.9 | robot default | Biped: fraction of a step on both feet |
| `gait.body_height` | −0.3–0.3 | robot default | Raise (+) or lower (−) the body, m |
| `gait.stabilizer` | `none`, `imu_feedback`, `lipm_zmp`, `policy` | robot default | Feedback mode; see [Gaits](/RoboWorld/concepts/gaits/#stabilizers) |
| `gait.params` | `{name: number}` | | Gait-specific knobs, such as `tilt_gain` |
| `duration` | number > 0 | | Seconds to run |

```yaml
- gait: {type: quadruped_trot, velocity: {vx: 0.4, wz: 0.2}, step_height: 0.06}
  until: {any: [{distance_traveled: 1.0}, {timeout: 8}]}
```

### `reach`

Moves an end-effector to a point with inverse kinematics.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `reach.effector` | string | required | An end-effector name |
| `reach.pos` | `[x, y, z]` | required | Target position, m |
| `reach.frame` | `base`, `world` | `base` | Frame of `pos` |
| `reach.relative` | boolean | `false` | `pos` is an offset from the effector's current position |
| `reach.duration` | number > 0 | `0.8` | Seconds to get there |
| `reach.ease` | curve | `min_jerk` | Interpolation curve |

### `wait`

Holds still. `wait: <seconds>`, or `wait: null` together with an `until` condition.

### `repeat`

Runs a block several times.

```yaml
- repeat:
    times: 4          # 1–1000
    do: [...]
```

### `parallel`

Runs two or more blocks at the same time, on disjoint joints.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `parallel` | list of steps (at least 2) | required | The blocks to run |
| `race` | boolean | `false` | Finish when the first block finishes, instead of when all have |

### `do`

A plain block of steps. Useful as a branch of `parallel`.

### `skill`

Runs a closed-loop [skill](/RoboWorld/reference/skills/).

```yaml
- skill: walk_to
  args: {target: red_ball, stop_distance: 0.3}
```

## Joint names

Anywhere a joint is expected, you can use:

- its exact name in the model,
- an alias from the manifest, such as `head.pitch`,
- `<limb>.<suffix>`, such as `left_leg.knee`, when exactly one joint of the limb matches.

## Conditions

A condition has exactly one field. Distances and angles are measured from when the step started.

| Condition | Holds when |
|---|---|
| `timeout: <s>` | The step has run for this many seconds |
| `distance_traveled: <m>` | The body has covered this much ground path |
| `displacement: <m>` | The body is this far, in a straight line, from where it started |
| `turned: <deg>` | The heading has changed by this many degrees, in either direction |
| `fallen: true` | The robot has tipped over |
| `reached: [x, y]` or `[x, y, tolerance]` | The body is at this world position |
| `any: [...]` | Any of the conditions holds |
| `all: [...]` | All of the conditions hold |

## Validation

`rw check` and the `validate_program` tool report:

**Errors** (the program won't run):

- unknown verbs, fields, joints, poses, end-effectors or skills,
- a gait that isn't available for this kind of robot,
- a gait step without `duration` or `until`, or `wait: null` without `until`,
- parallel branches that control the same joint,
- skill arguments that don't match the skill,
- a `robot:` field that names a different robot.

**Warnings** (the program runs, but not as written):

- a target outside a joint's range (it is clamped),
- a move faster than the servo limit (it is slowed down),
- a gait velocity outside the robot's tested limits (it may fall).

## Safety at run time

Whatever the program says, targets are clamped to joint ranges and rate-limited to the servo speed,
and with `on_fall: stop` the program stops if the robot falls. See
[The control loop](/RoboWorld/concepts/control-loop/#the-safety-layer).

## JSON schema

The schema is defined with Pydantic in `roboworld.lang.schema`. `program_json_schema()` returns it
as JSON Schema, for tools that generate or check programs.
