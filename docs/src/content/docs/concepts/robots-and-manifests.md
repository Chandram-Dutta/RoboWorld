---
title: Robots and manifests
description: How RoboWorld finds robot models and names their parts so one language works on every body.
---

A robot in RoboWorld is a MuJoCo model plus a **manifest**. The model describes the physics. The
manifest describes the robot in terms a program can use: named joints, limbs, poses, feet, a camera
and gaits. Programs only ever refer to manifest names, which is how one language works across a
duck, a dog and an arm.

## Where robots come from

Every robot has a registry entry, a YAML file with three parts:

- **`source`**: where the model comes from. Built-in robots use `type: git`, a repository and a
  pinned commit, and are downloaded by `rw fetch`. Your own robots use `type: path`.
- **`sim`**: overrides for MuJoCo's simulation options, such as solver iterations.
- **`manifest`**: additions and corrections to the generated manifest.

Built-in entries ship with the package. Your entries, including every designed robot, live in
`library/robots/`.

## The manifest

RoboWorld generates most of the manifest from the model and merges the entry's overrides on top.

| Part | Meaning |
|---|---|
| `kind` | `biped`, `quadruped`, `hexapod`, `arm`, `wheeled`, `mobile_manipulator` or `other`. Decides which gaits and skills apply. |
| `joints` | Every actuated joint with its range, control type (`position` or `torque`) and gains |
| `limbs` | Named groups of joints, such as `left_leg` or `FL` |
| `aliases` | Friendly joint names such as `head.pitch` |
| `end_effectors` | Points that `reach` and the gaits can target: a site, geom or body, plus the limb that moves it |
| `feet` | The end-effectors the gaits place on the ground |
| `poses`, `default_pose` | Named joint configurations, and the standing pose everything starts from |
| `camera` | Where the robot's eye is and where it looks |
| `gaits`, `default_gait` | Tuned settings and tested speed limits per gait |
| `max_joint_speed` | The servo speed limit used by the safety layer |

`rw describe <robot>` prints a robot's manifest, and the
[robot configuration reference](/RoboWorld/reference/robot-config/) lists every field.

## Naming joints in programs

A program can refer to a joint in three ways:

1. Its exact name in the model, for example `FL_thigh_joint`.
2. An alias, for example `head.pitch`.
3. `<limb>.<suffix>`, for example `left_leg.knee`, when exactly one joint in the limb matches.

Unknown names are reported with suggestions, for example
`Unknown joint 'FL_knee' on go2. Did you mean: FL_hip_joint, FL_calf_joint?`.

## Frames and signs

- **World frame:** `x` forward from the robot's starting position, `y` to its left, `z` up.
  Headings are in degrees, counter-clockwise.
- **Base frame:** fixed to the robot's body, with the same axes when the robot stands at its start.
  Gait velocities, `reach` targets (by default) and camera directions are in this frame.
- **Velocity:** `vx` forward, `vy` left, `wz` counter-clockwise (left) in rad/s.
- **Pitch** is positive when the nose goes down.

## Designed robots

A [robot design spec](/RoboWorld/reference/robot-design-spec/) compiles into both a model and a complete
manifest, with consistent names: joints are `<leg>_<part>` (for example `left_leg_knee`), feet are
`<leg>_foot` sites, the camera is the `head_cam` site, and neck joints are aliased to `head.pitch`
and `head.yaw`.
