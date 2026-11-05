---
title: Robot design spec
description: Every field of a robot design spec, how it compiles, the servo catalog and the design checks.
---

A robot design spec describes a legged robot in a few numbers. `rw design new` and `rw design
derive` build one from a template plus your changes, and RoboWorld compiles it into a MuJoCo model
and a manifest. See [Designing robots](/RoboWorld/guides/designing-robots/) for a walkthrough. Unknown fields
are errors.

## Spec

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Lower-case letters, digits and `_`; starts with a letter; 2–41 characters |
| `kind` | `biped`, `quadruped`, `hexapod` | required | Needs 2, 4 or 6 legs respectively |
| `description` | string | `""` | |
| `template` | string | set by `rw design new` | The template the design started from |
| `body` | [body](#body) | required | The torso |
| `legs` | list of [legs](#leg) | required | Leg names must be unique |
| `head` | [head](#head) | none | A head with a camera |
| `gait` | mapping | `{}` | Overrides for the default gait's settings, such as `period` or `params.tilt_gain` |

### Body

| Field | Type | Default | Meaning |
|---|---|---|---|
| `size` | `[x, y, z]` | required | Torso length, width and height, m |
| `mass` | 0–50 | required | Torso mass including battery and electronics, kg |
| `color` | colour | `white` | |

### Leg

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | For example `left_leg`, `FL` or `L1` |
| `mount` | `[x, y, z]` | required | Hip position relative to the torso centre, m |
| `dof` | `biped5`, `biped6`, `quad3` | required | The joints in the leg (see below) |
| `thigh` | 0.01–0.6 | `0.08` | Hip-to-knee length, m |
| `shin` | 0.01–0.6 | `0.08` | Knee-to-ankle length, m |
| `foot` | list | `[0.10, 0.05]` | Bipeds: `[length, width]` of a flat foot. Quadrupeds and hexapods: `[radius]` of a ball foot |
| `knee` | `forward`, `backward` | `forward` | Which way the knee bends |
| `stance` | 0.4–0.98 | `0.85` | Standing hip height as a fraction of thigh + shin |
| `servo` | servo name | `sts3215` | From the [servo catalog](#servo-catalog) |
| `segment_mass` | kg | `0.07` | Mass of each leg segment (servo and bracket) |
| `color` | colour | `gray` | |

Bipeds use `biped5` or `biped6` legs; quadrupeds and hexapods use `quad3` legs.

| `dof` | Joints, from the hip down |
|---|---|
| `biped5` | `hip_yaw`, `hip_roll`, `hip_pitch`, `knee`, `ankle` |
| `biped6` | `hip_yaw`, `hip_roll`, `hip_pitch`, `knee`, `ankle`, `ankle_roll` |
| `quad3` | `abduct`, `hip`, `knee` |

### Head

| Field | Type | Default | Meaning |
|---|---|---|---|
| `size` | `[x, y, z]` | `[0.08, 0.08, 0.06]` | Head size, m |
| `mount` | `[x, y, z]` | required | Neck base relative to the torso centre, m |
| `neck` | 0–0.4 | `0.05` | Neck length, m |
| `dof` | `pitch_yaw`, `fixed` | `pitch_yaw` | A moving neck, or a fixed head |
| `servo` | servo name | `sts3215` | |
| `camera_look` | `[x, y, z]` | `[1.0, 0.0, -0.7]` | Camera direction in the base frame |
| `camera_fovy` | degrees | `80` | Vertical field of view |
| `color` | colour | `white` | |

## Changes

`--set`, `--changes` and the MCP tools' `changes` argument are merged into the spec:

| Form | Effect |
|---|---|
| `{"body.mass": 1.5}` | A dotted key sets one nested field |
| `{all_legs: {thigh: 0.1}}` | Applies to every leg |
| `{legs: {left_leg: {foot: [0.12, 0.06]}}}` | Edits legs by name; unknown names are errors |
| `{legs: [...]}` | A list replaces all legs |

## What a spec compiles to

| Item | Name |
|---|---|
| Base body | Free joint `root`, torso box, `imu` site |
| Leg joints | `<leg>_<joint>`, for example `left_leg_knee` or `FL_hip` |
| Feet | `<leg>_foot` sites (end-effectors) |
| Limbs | One limb per leg, named after the leg, plus `head` for a moving neck |
| Neck | `neck_pitch` and `head_yaw`, aliased as `head.pitch` and `head.yaw` |
| Camera | The `head_cam` site |
| Poses | `home` (standing) and `crouch` |
| Actuators | Position servos with the servo's stiffness, torque limit, damping, armature and friction |
| Default gait | `biped_walk`, `quadruped_trot` or `hexapod_tripod` |

The compiler derives the default gait settings and speed limits from the leg length `L` (thigh +
shin):

| Kind | Period | Step height | Speed limits |
|---|---|---|---|
| Biped | 0.6 s | 0.2 L | `vx` −0.6 L to 1.1 L, `vy` ±0.35 L, `wz` ±0.6 |
| Quadruped | 0.35 s | 0.35 L | `vx` −1.2 L to 1.8 L, `vy` ±0.8 L, `wz` ±1.0 |
| Hexapod | 0.7 s | 0.35 L | `vx` −1.2 L to 1.5 L, `vy` ±0.8 L, `wz` ±1.0 |

Values in the spec's `gait` field override these.

A design's parts don't collide with each other; they do collide with the floor and world objects.

## Servo catalog

| Servo | Torque | Speed | Mass | Note |
|---|---|---|---|---|
| `sts3215` | 3.0 N·m | 5.2 rad/s | 65 g | Feetech 12 V, used in Open Duck Mini and SO-101 |
| `sts3250` | 5.0 N·m | 4.0 rad/s | 80 g | Feetech high-torque |
| `xl330` | 0.6 N·m | 9.6 rad/s | 22 g | Dynamixel, light and fast |
| `xm430` | 4.1 N·m | 4.8 rad/s | 95 g | Dynamixel mid-size |
| `mg996r` | 1.0 N·m | 7.0 rad/s | 60 g | Cheap analog metal-gear |

`rw design servos` prints the catalog.

## Design checks

`rw design check` (and every `new` and `derive` unless you pass `--no-check`) runs these checks. The
overall result is the worst status among them.

| Check | Pass | Warn | Fail |
|---|---|---|---|
| `mass` | under 25 kg | 25 kg or more | |
| `standing_height` | always (reports the height) | | |
| `home_pose_in_range` | every joint at least 0.02 rad inside its range | | a joint at its limit |
| `parts_overlap` | no intersecting parts at the standing pose | parts intersect | |
| `stands` | stands still for 2 s | | falls |
| `standing_torque` | peak servo load under 60% of the limit | 60–90% | 90% or more, or falls |
| `sag` | body sinks less than 5% of the leg length | more | |
| `walks` | covers at least 40% of the expected distance | less | falls |
| `walk_straightness` | heading drifts less than 15° | more | |
| `walking_effort` | information only | | |
| `turns` | turns more than 45° in 5 s | less | falls |

The walking and turning checks command 85% of the gait's speed limits for 5 s, the same speed the
skills use.

## Storage

| Path | Contents |
|---|---|
| `library/designs/<name>/spec.yaml` | The spec |
| `library/designs/<name>/robot.xml` | The compiled model |
| `library/designs/<name>/meta.json` | `name`, `digest`, `parent`, `note`, `template`, `created` and the last check report |
| `library/robots/<name>.yaml` | The registry entry with the generated manifest |

The **digest** is a hash of the spec's content (excluding its name, description and template), so
two designs with the same body have the same digest.
