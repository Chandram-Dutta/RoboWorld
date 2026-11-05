---
title: Robot configuration
description: The registry entry and manifest fields that describe a robot to RoboWorld.
---

Every robot has a registry entry: a YAML file in the package's built-in manifests folder, or in
`library/robots/` for your own robots. See [Adding your own robot](/RoboWorld/guides/adding-a-robot/) for a
walkthrough.

```yaml
name: my_dog
source: {type: path, path: ../../my_models/my_dog, model: my_dog.xml}
sim: {iterations: 20}
manifest:
  kind: quadruped
  # ...
```

## Entry

| Field | Type | Meaning |
|---|---|---|
| `name` | string | The robot's name |
| `source` | [source](#source) | Where the model comes from |
| `sim` | mapping | Overrides for MuJoCo's `<option>` settings, such as `iterations` or `timestep` |
| `manifest` | [manifest](#manifest) | Additions and corrections to the generated manifest |

## Source

| Field | Applies to | Meaning |
|---|---|---|
| `type` | both | `git` (downloaded by `rw fetch`) or `path` (a local folder) |
| `model` | both | The MJCF file, relative to the source folder |
| `repo` | `git` | Repository URL |
| `commit` | `git` | The pinned commit |
| `subdir` | `git` | Folder inside the repository that holds the model |
| `include` | `git` | Files and folders to check out (sparse clone) |
| `path` | `path` | Folder that holds the model, relative to the entry's YAML file |

Models from `git` sources are stored in `assets/robots/<name>/`.

## Manifest

Fields you can set under `manifest:`. Anything you leave out is generated from the model.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `kind` | `biped`, `quadruped`, `hexapod`, `arm`, `wheeled`, `mobile_manipulator`, `other` | `other` | Decides which gaits and skills apply |
| `description` | string | `""` | Shown to brains and in `rw describe` |
| `limbs` | `{limb: [joints]}` | grouped by body-tree branch | Named joint groups |
| `aliases` | `{alias: joint}` | `<limb>.<suffix>` names | Extra joint names, merged with the generated ones |
| `end_effectors` | `{name: effector}` | sites named like `foot`, `hand`, `gripper`, `tool`, `ee` | Points for `reach` and the gaits |
| `feet` | list of end-effectors | `[]` | The end-effectors the gaits put on the ground |
| `poses` | `{pose: {joint: radians}}` | `zero` and the model's keyframes | Named poses; a pose with an existing name is updated |
| `default_pose` | string | `zero` | The standing pose everything starts from |
| `camera` | [camera](#camera) | none | The robot's eye |
| `default_gait` | string | none | The gait skills use |
| `gaits` | `{gait: settings}` | `{}` | Tuned settings and speed limits per gait |
| `max_joint_speed` | rad/s | `6.0` | Rate limit for every joint target |
| `joint_gains` | `{kp, kd}` | from each joint's force limit | PD gains for torque-controlled joints |
| `joint_overrides` | `{joint: {field: value}}` | | Per-joint changes, such as `kp`, `kd` or `range` |

### End-effector

Exactly one of `site`, `geom` or `body`, plus the limb that moves it:

```yaml
end_effectors:
  left_foot: {site: left_foot, limb: left_leg}
  gripper: {site: gripperframe, limb: arm}
```

### Camera

| Field | Type | Default | Meaning |
|---|---|---|---|
| `body` or `site` | string | | What the camera is attached to |
| `pos` | `[x, y, z]` | `[0, 0, 0]` | Offset from the body or site, in the base frame at the default pose, m |
| `look` | `[x, y, z]` | `[1, 0, -0.3]` | Viewing direction in the base frame |
| `fovy` | degrees | `60` | Vertical field of view |
| `width`, `height` | pixels | `320`, `240` | Image size |
| `max_range` | m | `5.0` | Perception range |

### Gait settings

Each entry under `gaits` may set `period`, `step_height`, `duty_factor`, `double_support`,
`body_height`, `stabilizer` and `params` (see [Gaits](/RoboWorld/concepts/gaits/#settings)), plus the tested
speed limits:

```yaml
gaits:
  quadruped_trot:
    period: 0.4
    step_height: 0.08
    duty_factor: 0.6
    limits: {vx: [-0.5, 0.9], vy: [-0.3, 0.3], wz: [-1.0, 1.0]}
```

## Generated fields

These come from the model and can't be set in the entry:

| Field | Source |
|---|---|
| `joints` | Every joint driven by an actuator: range, actuator, control type (`position` or `torque`), force limit |
| `floating_base`, `base_body` | Whether the model has a free joint, and the body it moves |
| `imu_site` | A site named `imu`, `IMU` or `imu_site`, if present |
| `mass` | The total mass of the robot |
