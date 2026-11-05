---
title: The control loop
description: How the interpreter runs a program, and how the safety and servo layers turn its targets into motion.
---

Every program, whether you wrote it or a skill generated it, runs through the same loop. Its output
is always a set of **joint position targets**, which pass through a safety layer and a servo layer
before they reach the physics.

```text
program ─► interpreter (50 Hz) ─► joint targets ─► safety layer ─► servo layer ─► MuJoCo (every physics step)
                ▲                                                                     │
                └──────────── robot state: pose, tilt, contacts, perception ◄─────────┘
```

## The interpreter

The interpreter turns each step of a program into an **action** and runs it at the control rate of
**50 Hz**. Between two control ticks, MuJoCo takes several physics steps.

- **Sequences** run their steps one after another.
- **Parallel blocks** run at the same time. Each action *claims* the joints it moves, and two
  branches may not claim the same joint; the validator reports conflicts before the program runs.
- **Joints that no running step controls** keep their last target, so a robot holds its pose.
- **`until` conditions** are checked on every tick, measured from the moment the step started.

Keyframe motion (`pose`, `clip`, `reach`) interpolates between targets with an easing curve:
`min_jerk` (the default, smooth start and stop), `cubic` or `linear`.

### Gaits stop gracefully

When a gait's duration ends or its `until` condition fires, the gait doesn't freeze mid-stride.
It finishes the step in progress, decelerates and settles before the next step runs. Expect a few
centimetres or degrees of overshoot after a condition fires.

## The safety layer

The safety layer is always on, for programs written by people, by models and by skills alike:

| Protection | Behaviour |
|---|---|
| Joint ranges | Targets are clamped to each joint's range. |
| Servo speed | Targets move no faster than the manifest's `max_joint_speed`, so a program can't ask for more than the servos can deliver. |
| Falls | The robot counts as fallen when it tips more than 60° or its body drops below 45% of its starting height. With `on_fall: stop` (the default) the program stops. |
| Validation | Unknown names, gaits without a stopping condition and conflicting parallel branches are rejected before the program runs. |

## The servo layer

RoboLang always speaks in joint position targets, the way hobby servos such as the STS3215 are
driven. The servo layer adapts them to each robot's actuators:

- **Position actuators** receive the target directly. The actuator's own gains and force limit
  model the servo.
- **Torque motors** get a PD controller that the servo layer closes on every physics step, with
  gains from the manifest (`joint_gains` or per-joint overrides).

Because programs never command torques, the same program runs on a hobby-servo duck and a
torque-controlled quadruped.

## Metrics along the way

While a program runs, RoboWorld measures the body's path, heading, tilt and height, the torque each
joint uses relative to its limit, energy, tracking error and limit hits. These become the metrics
in every result; see [Results and metrics](/RoboWorld/reference/results/).
