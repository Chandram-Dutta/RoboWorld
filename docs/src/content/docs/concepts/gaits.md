---
title: Gaits
description: How RoboWorld's robots walk without training, and how gait settings are chosen.
---

A gait turns a **velocity command** into joint targets, tick by tick. Every gait has the same
interface, so a program says *how fast to go*, not *how to move each leg*:

```yaml
- gait: {type: quadruped_trot, velocity: {vx: 0.5, vy: 0.0, wz: 0.3}}
  duration: 4
```

`vx` is forward speed and `vy` sideways speed in m/s; `wz` is the turning rate in rad/s, positive to
the left. All three are in the robot's base frame.

## Available gaits

| Gait | Robots | How it moves |
|---|---|---|
| `biped_walk` | bipeds | Footstep planning with balance control (see below) |
| `quadruped_trot` | quadrupeds | Diagonal leg pairs move together |
| `quadruped_pace` | quadrupeds | Legs on the same side move together |
| `quadruped_bound` | quadrupeds | Front legs, then rear legs |
| `quadruped_walk` | quadrupeds | One leg at a time; at least three feet down |
| `hexapod_tripod` | hexapods | Two alternating tripods of three legs |

`rw describe <robot>` lists the gaits a robot can use, with its tuned settings and speed limits.

## Settings

| Setting | Meaning |
|---|---|
| `period` | Seconds per full gait cycle |
| `step_height` | How high a foot lifts, in metres |
| `duty_factor` | Fraction of the cycle a foot is on the ground (multi-legged gaits) |
| `double_support` | Fraction of a step with both feet down (`biped_walk`) |
| `body_height` | Raise (+) or lower (−) the body, in metres |
| `stabilizer` | `none` turns tilt feedback off; see below |
| `params` | Gait-specific tuning knobs, such as `tilt_gain` |

Each setting is chosen in this order: the value in the program, then the robot's tuned default from
its manifest, then the gait's built-in default. Leave settings out unless you have a reason to change
them.

Each robot's manifest also records **speed limits** per gait: the velocities that have been
tested. The validator warns about commands outside them, and skills walk at 85% of them.

## How the biped walks

`biped_walk` keeps a two-legged robot balanced without any learning. It works in five stages:

1. **Footstep planning.** The velocity command becomes a sequence of alternating footsteps. The
   plan is recomputed at every step boundary, and a heading hold steers it back on course.
2. **Zero-moment point (ZMP) reference.** For the robot not to tip, the point where the ground
   pushes back (the ZMP) must stay inside the supporting foot. The gait builds a ZMP path that sits
   on the stance foot and moves across during double support.
3. **Preview control.** Kajita's preview controller, applied to a linear inverted pendulum model of
   the robot, computes a centre-of-mass path that follows the ZMP reference. It looks ahead at the
   upcoming footsteps, so the body starts shifting before a foot lifts.
4. **Swing feet.** Each swinging foot follows a smooth arc to its next footstep.
5. **Inverse kinematics.** IK turns the body and foot targets into joint targets. A tilt correction
   (`tilt_gain`) keeps the feet level if the torso leans.

Small bipeds without ankle roll, like the Open Duck, can't shift their weight sideways with both feet
flat. For them the gait lets the feet roll and constrains only foot pitch and yaw.

## How multi-legged gaits work

The periodic gaits (`quadruped_*` and `hexapod_tripod`) give each foot the same cycle with a phase
offset. During stance a foot slides backwards under the body at the commanded speed; during swing it
lifts and returns forwards. IK turns the foot positions into joint targets. These gaits are stable
enough to run without feedback, and a tilt correction levels the body on uneven ground.

## Stabilizers

The `stabilizer` field selects the feedback a gait uses:

| Value | Meaning |
|---|---|
| `lipm_zmp` | Default for `biped_walk`: preview control plus tilt correction |
| `imu_feedback` | Default for periodic gaits: tilt correction from the body's measured tilt |
| `none` | No tilt feedback |
| `policy` | Reserved for trained policies; not available yet |

## Inverse kinematics

Gaits and `reach` steps express targets in the robot's base frame. RoboWorld solves inverse
kinematics with [mink](https://github.com/kevinzakka/mink) on a copy of the robot whose base is
fixed, so "base frame" positions are well defined, and sends the resulting joint angles to the
safety layer.
