---
title: Architecture
description: The layers of RoboWorld and how a brain's request becomes robot motion.
---

RoboWorld is one Python package, `roboworld`, with a command-line tool (`rw`) and two MCP servers.
It is built in layers. Each layer only uses the layers below it.

```text
 brains          your harness · agent CLIs (Codex, Claude Code) · baseline · any MCP client
                    │                                           │
 servers         robot MCP server (rw serve-robot)         builder MCP server (rw serve-mcp)
                    │                                           │
 episodes        Episode: task, perception, scoring        api: describe, validate, simulate, design
                    │                                           │
 language        skills ─────────► RoboLang interpreter ◄───────┘
                                        │
 motion          gaits · inverse kinematics · safety layer · servo layer
                                        │
 simulation      MuJoCo physics · scene (robot + world) · metrics · Rerun recorder
                                        │
 robots          registry · manifests · design compiler
```

## Layers

| Layer | Package | Responsibility |
|---|---|---|
| Robots | `robots/`, `design/` | Find and load robot models; generate manifests that name their parts; compile robot design specs into models |
| Simulation | `sim/` | Assemble the scene, step MuJoCo physics, turn joint targets into actuator commands, measure metrics and record runs |
| Motion | `lang/gaits/`, `lang/ik.py` | Gait generators and inverse kinematics that turn velocity commands and end-effector targets into joint targets |
| Language | `lang/` | The RoboLang schema, validator and interpreter, and the closed-loop skills built on it |
| Worlds and tasks | `world/` | World and task specs, random placement per seed, success rules |
| Episodes | `episode.py`, `sim/perception.py` | One robot in one task: perception, timing, scoring, transcripts |
| Servers | `mcp/` | The robot MCP server for brains and the builder MCP server for authoring |
| Brains and harnesses | `brain/`, `harness/` | Brain specs, the harness interface and the episode runner |
| Benchmark | `bench.py` | Many episodes in parallel, aggregated into a report |

## From a tool call to motion

Here is what happens when a brain calls `do("walk_to", {"target": "red_ball"})`:

1. The **robot MCP server** receives the call and passes it to the episode on a single worker
   thread, which owns all MuJoCo and rendering state.
2. In realtime mode, the **episode** first advances the world by the time the brain spent
   thinking. It then validates the skill and its arguments.
3. The **skill** wraps itself in a one-step RoboLang program and hands it to the **interpreter**.
4. The interpreter runs at **50 Hz**. On each tick the `walk_to` skill reads the robot's
   **perception memory** (never ground truth), steers towards the ball's estimated position and
   updates the **gait**'s velocity command.
5. The gait computes foot and body targets; **inverse kinematics** turns them into joint targets.
6. The **safety layer** clamps the targets to joint ranges and rate-limits them to the servos'
   speed. The **servo layer** sends them to MuJoCo's actuators.
7. **MuJoCo** steps the physics several times per tick. **Perception** updates what the camera can
   see, the **task** checks its success and failure rules, and the **recorder** logs the frame.
8. When the skill finishes (or fails, or the task ends), the episode returns `ok`, a message and
   the robot's pose to the brain, and appends the call to the transcript.

## Two kinds of users, two servers

- The **robot MCP server** is for brains. It exposes one robot in one task with honest senses and a
  fixed set of tools. The brain cannot reset the world or read hidden state.
- The **builder MCP server** is for people and assistants who build things: it describes robots,
  validates and simulates programs, saves motions and runs the design tools.

## Design principles

- **Position targets everywhere.** RoboLang only speaks joint position targets, the way hobby
  servos are driven. The servo layer adapts them to each robot's actuators.
- **No training required.** Motion comes from planning and control that runs in real time on a
  CPU. A trained policy is an optional future upgrade behind the same gait interface.
- **Honesty.** Brains only know what the robot has seen; the simulator judges success; claims are
  checked.
- **Reproducibility.** A robot, task, seed and brain fully determine an episode in paused mode.
- **Platform, not harness.** RoboWorld provides robots, worlds, interfaces and measurements.
  Brains come from users.
