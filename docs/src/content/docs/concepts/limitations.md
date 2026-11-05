---
title: Known limitations
description: What RoboWorld doesn't do yet, and physical behaviour to expect from its robots.
---

These are the limitations to keep in mind when you write programs, build harnesses and read
benchmark results.

## Motion

- **Gaits overshoot a little.** Gaits finish the step in progress and decelerate before stopping,
  so expect a few centimetres or degrees of overshoot after an `until` condition fires.
- **Speeds are tuned only within limits.** Each robot's gaits are tested within the speed limits in
  its manifest. Faster commands are allowed, with a warning, and may make the robot fall.
- **No get-up skill.** A robot that falls stays down, and the episode ends.
- **Trained policies are not available yet.** The `policy` stabilizer is reserved for them.

## Skills

- **`walk_to` has no obstacle avoidance**, by design. It reports `blocked` when something is in the
  way, and leaves route planning to the brain.
- **`push` won't push an object pinned against a wall.** It reports the situation instead of
  trying.

## Physical findings

These are properties of the simulated bodies, not bugs, and they show up in benchmark results:

- **Small bipeds struggle on rough ground.** The Open Duck model and the designed ducks mostly fall
  on 1–1.5 cm bumps. Adding ankle roll, bigger feet and a tuned gait helps only a little.
- **The duck trips when shoving a box.** It handles balls better than boxes.
- **Boxes slide off line.** The Go2 quadruped pushes boxes to their target about half the time.

## Robots

- **MJCF only.** URDF models must be converted to MJCF and given actuators first; see
  [Adding your own robot](/RoboWorld/guides/adding-a-robot/).
- **Design templates cover legged robots.** The design compiler builds bipeds, quadrupeds and
  hexapods. Wheeled robots and arms can be added as your own models, but not designed from a spec.
