---
title: Adding your own robot
description: Register your own MuJoCo model as a RoboWorld robot and name its parts for RoboLang.
---

You can bring any robot that has a MuJoCo (MJCF) model. You register it with a short YAML file, and
RoboWorld generates a **manifest** that names its joints, limbs and poses for RoboLang. Most of the
work is telling RoboWorld which parts are feet, where the camera is and how fast it may walk.

## What the model needs

- **An MJCF file** that MuJoCo can load, together with its meshes.
- **Actuators on the joints you want to control.** RoboWorld only controls joints that have an
  actuator. Position actuators (like hobby servos) receive joint targets directly; motor actuators
  get a PD loop that RoboWorld closes on every physics step.
- **A free joint on the base** for a mobile robot. A model without one is treated as fixed to the
  ground, like an arm.
- **Joint ranges** on every controlled joint. Joints without a range are limited to ±π.
- Optional: **keyframes**, which become named poses, and a **site named `imu`** on the body.

:::tip[Starting from URDF]
URDF has no actuators. Load the URDF in MuJoCo, save it as MJCF, and add an `<actuator>` section
with one position actuator per joint before registering it.
:::

## Register the robot

Create `library/robots/<name>.yaml`. Paths in `source` are relative to this file:

```yaml title="library/robots/my_dog.yaml"
name: my_dog
source:
  type: path
  path: ../../my_models/my_dog     # folder containing the model
  model: my_dog.xml                # the MJCF file inside it
manifest:
  kind: quadruped
  description: A 3 kg quadruped with 3 position servos per leg.
```

Check that RoboWorld can load it, then look at the generated manifest:

```sh
uv run rw robots
uv run rw describe my_dog
uv run rw snapshot my_dog --out my_dog.png
```

## What RoboWorld generates

From the model alone, RoboWorld builds:

| Item | How it is generated |
|---|---|
| Joints | Every joint driven by an actuator, with its range and control type |
| Limbs | Joints grouped by the branch of the body tree they hang from |
| Aliases | `<limb>.<suffix>` names, for example `FL.thigh` for `FL_thigh_joint` |
| Poses | `zero` (all joints at 0, clipped to range) plus one pose per keyframe |
| End-effectors | Sites whose names contain `foot`, `hand`, `gripper`, `tool` or `ee` |
| Base body and mass | The body with the free joint, and the mass of its subtree |

Anything under `manifest:` in your YAML overrides or adds to this.

## Name the parts

A mobile robot needs feet, a default pose and a gait before it can walk. A complete entry looks
like this:

```yaml title="library/robots/my_dog.yaml"
name: my_dog
source: {type: path, path: ../../my_models/my_dog, model: my_dog.xml}
sim:
  iterations: 20                  # MuJoCo <option> overrides
manifest:
  kind: quadruped
  description: A 3 kg quadruped with 3 position servos per leg.
  limbs:
    FL: [fl_abduct, fl_hip, fl_knee]
    FR: [fr_abduct, fr_hip, fr_knee]
    RL: [rl_abduct, rl_hip, rl_knee]
    RR: [rr_abduct, rr_hip, rr_knee]
  end_effectors:
    FL_foot: {site: fl_foot, limb: FL}
    FR_foot: {site: fr_foot, limb: FR}
    RL_foot: {site: rl_foot, limb: RL}
    RR_foot: {site: rr_foot, limb: RR}
  feet: [FL_foot, FR_foot, RL_foot, RR_foot]
  poses:
    home: {fl_hip: 0.7, fr_hip: 0.7, rl_hip: 0.7, rr_hip: 0.7,
           fl_knee: -1.4, fr_knee: -1.4, rl_knee: -1.4, rr_knee: -1.4}
  default_pose: home
  camera: {body: trunk, pos: [0.15, 0.0, 0.03], look: [1.0, 0.0, -0.4], fovy: 80}
  default_gait: quadruped_trot
  max_joint_speed: 6.0
  gaits:
    quadruped_trot:
      period: 0.4
      step_height: 0.05
      limits: {vx: [-0.3, 0.5], vy: [-0.2, 0.2], wz: [-0.8, 0.8]}
```

Things to get right:

- **Feet and limbs.** Each foot is an end-effector whose `limb` lists the joints that move it.
  Gaits use these to place the feet with inverse kinematics.
- **Kind.** `biped_walk` needs `kind: biped` and exactly two feet. The quadruped gaits match feet
  by the prefixes `FL`, `FR`, `RL` and `RR`; `hexapod_tripod` uses `L1`–`L3` and `R1`–`R3`.
- **Default pose.** A comfortable standing pose with bent knees. Gaits start from it.
- **Camera.** `look` is a direction in the base frame. Without a camera, perception skills such as
  `look_around` are not available.
- **Speed limits.** `limits` under a gait are the velocities you have tested. The validator warns
  when a program asks for more, and skills walk at 85% of the limit.
- **Servo speed.** `max_joint_speed` (rad/s) is used to rate-limit every joint target. Set it to
  what your servos can really do.

The [robot configuration reference](/RoboWorld/reference/robot-config/) lists every field.

## Test it

```sh
uv run rw run my_dog --idle                 # does it stand?
uv run rw design check my_dog               # stands, walks, turns, torque headroom
uv run rw episode --robot my_dog --task find_red_ball --brain baseline
```

If it falls while walking, lower the speed limits, raise `period` or reduce `step_height` until
`rw design check` passes. Then tune `tilt_gain` under the gait's `params`.

## Collisions

RoboWorld adds collision to world objects and walls automatically. If your robot's visual meshes
have no collision geometry, RoboWorld uses the meshes as stand-ins that touch world objects (but
not the floor or the robot itself), so the robot can't walk through balls and boxes.
