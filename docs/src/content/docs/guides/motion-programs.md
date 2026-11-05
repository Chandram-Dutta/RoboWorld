---
title: Writing motion programs
description: Write, validate and run RoboLang programs that make a robot move.
---

A RoboLang program is a YAML (or JSON) file with a `do:` list of steps. Each step has one verb,
such as `pose`, `clip` or `gait`. This guide builds a program step by step. The complete syntax is
in the [RoboLang reference](/RoboWorld/reference/robolang/).

## Find out what the robot has

Programs refer to a robot's parts by name. Ask RoboWorld for them first:

```sh
uv run rw describe go2
```

The output lists the robot's joints (with ranges), limbs, aliases, end-effectors, feet, named
poses and gaits with their tuned defaults and speed limits. For the Go2 quadruped, for example:

```json
{
  "limbs": {"FL": ["FL_hip_joint", "FL_thigh_joint", "FL_calf_joint"], "...": "..."},
  "aliases": {"FL.hip": "FL_hip_joint", "FL.thigh": "FL_thigh_joint", "...": "..."},
  "poses": ["crouch", "home", "stand_tall", "zero"],
  "default_pose": "home",
  "gaits": {
    "quadruped_trot": {
      "period": 0.4, "step_height": 0.08, "duty_factor": 0.6,
      "limits": {"vx": [-0.5, 0.9], "vy": [-0.3, 0.3], "wz": [-1.0, 1.0]}
    }
  }
}
```

Angles are in radians, distances in metres and times in seconds.

## Move to a pose

`pose` moves joints to a named pose, or to explicit angles, over a duration:

```yaml
do:
  - pose: crouch
    duration: 0.8
  - pose: home
    duration: 0.8
    hold: 0.5          # stay there for half a second
```

Explicit angles can use joint names or aliases:

```yaml
do:
  - pose: {FL.thigh: 1.0, FR.thigh: 1.0}
    duration: 0.5
```

## Animate with keyframes

`clip` plays keyframes. Each key gives the time to reach it from the previous key, plus the joint
angles. This makes the duck nod twice:

```yaml
robot: open_duck_mini_v2
do:
  - clip:
      keys:
        - {t: 0.3, head.pitch: 0.3}
        - {t: 0.3, head.pitch: -0.2}
      repeat: 2
```

## Walk with a gait

`gait` walks with a velocity command: `vx` forward, `vy` to the left and `wz` turning left, in
m/s and rad/s. A gait never stops on its own, so give it a `duration` or an `until` condition:

```yaml
do:
  - gait: {type: quadruped_trot, velocity: {vx: 0.5}}
    until: {any: [{distance_traveled: 0.8}, {timeout: 6}]}
  - gait: {type: quadruped_trot, velocity: {wz: 0.9}}
    until: {any: [{turned: 90}, {timeout: 6}]}
```

Combining a goal with a `timeout` is good practice: if the goal is never met, the step still ends.
Leave out optional gait fields to use the robot's tuned defaults. See [Gaits](/RoboWorld/concepts/gaits/)
for how the gaits work.

## Do several things at once

`parallel` runs blocks at the same time on **different** joints. With `race: true` the step ends
as soon as the first block finishes:

```yaml
do:
  - parallel:
      - gait: {type: biped_walk, velocity: {vx: 0.12}}
        until: {any: [{distance_traveled: 1.0}, {timeout: 15}]}
      - clip:
          keys: [{t: 0.4, head.pitch: 0.25}, {t: 0.4, head.pitch: -0.15}]
          repeat: 30
    race: true
```

`repeat` loops a block, and `do` groups steps into a block.

## Reach a point

`reach` moves an end-effector to a point with inverse kinematics. This moves the SO-101 gripper
6 cm down from where it is:

```yaml
robot: so_arm101
do:
  - reach: {effector: gripper, pos: [0.0, 0.0, -0.06], relative: true, duration: 1.0}
```

## Call a skill

Programs can also call closed-loop [skills](/RoboWorld/reference/skills/), such as `turn` or `walk_to`.
Skills that use perception need a world, so they are most useful inside an episode:

```yaml
do:
  - skill: turn
    args: {degrees: 90}
```

## Validate the program

`rw check` validates a program against a robot without running it:

```sh
uv run rw check go2 my_program.yaml
```

```json
{
  "ok": false,
  "errors": [
    "do[0]: a gait never stops on its own; add 'duration' or 'until'",
    "do[1]: Unknown joint 'FL_knee' on go2. Did you mean: FL_hip_joint, FL_calf_joint?"
  ],
  "warnings": [],
  "estimated_duration_s": null
}
```

**Errors** must be fixed before the program can run. **Warnings** point out steps that will run
differently from how they are written:

- a target outside a joint's range is clamped to the range;
- a move faster than the servos allow is slowed down;
- a gait speed outside the robot's tested range may make it fall.

The command exits with status 1 when there are errors, so you can use it in scripts.

## Run it

```sh
uv run rw run go2 my_program.yaml
```

| Option | Default | Meaning |
|---|---|---|
| `--seconds` | `30` | Stop after this much simulated time. |
| `--snapshots` | `4` | Number of snapshot images to save. |
| `--view` | off | Open the Rerun viewer when the run finishes. |
| `--idle` | off | Ignore the program and stand still for a few seconds. |

`rw run` exits with status 0 when the program completes and 1 otherwise (for example if the robot
fell).

## Improve it

Read the metrics in the result to decide what to change:

- `fell` and `max_tilt_deg`: did the robot stay upright?
- `forward_m`, `lateral_drift_m` and `heading_change_deg`: did it go where you meant?
- `peak_torque_ratio`: values above 0.9 mean the servos are working at their limit.
- `joint_limit_hits`: how often joints were pressed against the end of their range.

Two habits help:

- Start from the robot's default pose, and return to it before starting a gait.
- Keep keyframes at least 0.15 s apart for large moves. Servos have a speed limit, and the safety
  layer slows down targets that ask for more.

[Analysing runs](/RoboWorld/guides/analysing-runs/) shows how to inspect a run in more depth.

## Save a motion for robot brains

A motion saved to the robot's library can be played by a robot brain with the `play` skill. Save
it with the builder MCP server's `save_motion` tool, or place the program in
`library/motions/<robot>/<name>.yaml` with `name` and `description` fields:

```yaml title="library/motions/open_duck_mini_v2/happy_nod.yaml"
robot: open_duck_mini_v2
name: happy_nod
description: nod three times and wiggle the head
do:
  - clip:
      keys: [{t: 0.3, head.pitch: 0.3}, {t: 0.3, head.pitch: -0.2}]
      repeat: 3
```
