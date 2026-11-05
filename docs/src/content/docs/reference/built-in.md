---
title: Built-in robots, worlds and tasks
description: The robots, design templates, worlds and tasks that come with RoboWorld.
---

## Robots

| Robot | Kind | Description | Model source |
|---|---|---|---|
| `open_duck_mini_v2` | biped | A 42 cm duck-style biped with 14 STS3215 position servos: 5 per leg (hip yaw, roll and pitch, knee, ankle pitch) and 4 in the neck and head. No ankle roll. | [Open Duck Playground](https://github.com/apirrone/Open_Duck_Playground); hardware design: [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini) |
| `go2` | quadruped | Unitree Go2, a 15 kg quadruped with 3 torque-controlled joints per leg (hip abduction, thigh, calf). | [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) |
| `so_arm101` | arm | SO-101, a 5-DoF arm with a gripper and six STS3215 position servos, fixed to the ground. | [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) |

`rw fetch <robot>` downloads each model from its source at a pinned commit. Models keep their
upstream licences and are not redistributed with RoboWorld.

| Robot | Default gait | Tested speed limits (`vx`, `vy` m/s; `wz` rad/s) | Poses |
|---|---|---|---|
| `open_duck_mini_v2` | `biped_walk` | `vx` −0.1 to 0.18, `vy` ±0.06, `wz` ±0.6 | `zero`, `home` |
| `go2` | `quadruped_trot` | `vx` −0.5 to 0.9, `vy` ±0.3, `wz` ±1.0 | `zero`, `home`, `crouch`, `stand_tall` |
| `so_arm101` | none | | `zero`, `gripper_open`, `gripper_closed` |

## Design templates

| Template | Kind | Description |
|---|---|---|
| `duck` | biped | A small duck-style biped: 5-DoF legs, a 2-DoF neck with a camera, STS3215 servos, about 2 kg |
| `mini_dog` | quadruped | A small hobby-servo quadruped: 3-DoF legs with backward knees and ball feet, a fixed head camera, STS3215 servos, about 2 kg |
| `hexapod` | hexapod | A six-legged walker: 3-DoF legs on light XL330 servos, tripod gait, a fixed front camera, about 1.3 kg. Very stable but slow. |

## Worlds

| World | Description |
|---|---|
| `ball_room` | A 4 × 4 m walled room with a red ball, a blue crate and a green goal area painted on the floor |
| `ball_pit` | A walled room with several balls of different colours scattered around |
| `box_room` | A walled room with a light blue box and a red area painted on the floor |
| `bumpy_field` | A walled room whose middle is covered in small bumps (5–15 mm), with a green area on the far side |
| `crate_barrier` | A row of crates across the room in front of the robot, with a yellow marker painted somewhere behind them |
| `danger_zone` | A green area on the far side of the room, with a red no-go zone painted between the robot and the green area |
| `hide_and_seek` | A 4 × 4 m walled room with a red ball somewhere behind the robot, and two crates that block parts of the view |

## Tasks

| Task | World | Time limit | Tests |
|---|---|---|---|
| `find_red_ball` | `hide_and_seek` | 150 s | Searching: the ball starts behind the robot |
| `push_ball_to_goal` | `ball_room` | 180 s | Pushing a rolling object into an area |
| `box_to_red_area` | `box_room` | 180 s | Pushing a sliding object into an area |
| `reach_marker_behind_crates` | `crate_barrier` | 180 s | Exploring and detouring to a hidden target |
| `cross_bumpy_ground` | `bumpy_field` | 150 s | Walking robustly over rough ground |
| `visit_crate_then_ball` | `ball_room` | 180 s | Completing goals in order |
| `count_red_balls` | `ball_pit` | 120 s | Perceiving and reporting: the answer goes in `finish(answer=...)` |
| `avoid_red_zone` | `danger_zone` | 150 s | Following a constraint: touching the red zone fails the task |

Every task uses random placements per seed. `rw tasks` prints the full instructions.

## Brains

| Brain | Type | Description |
|---|---|---|
| `baseline` | baseline | A rule-based brain with no model: it matches words in the instruction to objects and uses skills. A free reference point. |
| `codex` | command | Runs the Codex CLI as the brain |
| `claude-code` | command | Runs the Claude Code CLI as the brain |

The repository's `examples/harnesses/` folder has two example harnesses: `explorer` (rule-based,
with exploration and detours) and `llm_harness` (a short model-driven loop).
