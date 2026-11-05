---
title: Introduction
description: What RoboWorld is, who it is for, and how its parts fit together.
---

RoboWorld is a toolkit for **building simulated robots** and **testing the brains that control them**.
You describe or import a robot, move it with **RoboLang**, drop it into a world with a task, and let a
brain (your own harness, or any agent that speaks MCP) try to complete the task. RoboWorld records
everything and scores the result.

## Who it is for

- **Harness builders** who want to know how well their LLM control loop actually drives a robot,
  compared with other harnesses and agents on the same tasks.
- **Robot designers** who want to try body variations (leg length, servos, feet, gait settings)
  and see which design performs best under the same brain.
- **Researchers and hobbyists** who want a small, scriptable robotics sandbox that runs on a
  laptop CPU, with no GPU and no training required.

## What RoboWorld provides

| Part | What it does |
|---|---|
| Robots | Built-in models (a small biped duck, a quadruped and an arm), a design compiler for new robots, and support for your own MJCF models. |
| RoboLang | A typed YAML/JSON language for poses, keyframe clips, gaits, inverse kinematics and skills. |
| Simulation | MuJoCo physics with a servo layer and an always-on safety layer, recorded for replay in Rerun. |
| Worlds and tasks | Rooms, objects and terrain described in YAML, with success rules and random placements per seed. |
| Robot MCP server | Exposes one robot in one task as MCP tools, so any MCP client can be its brain. |
| Harness interface | A small Python API for writing your own brain, plus ways to plug it in. |
| Benchmark | Runs robots × brains × tasks × seeds and writes a comparison report. |
| Design tools | Templates, a servo catalog, physical and walking checks, design history, gait tuning and comparisons. |

## What RoboWorld does not do

RoboWorld is a platform, not a harness. It doesn't ship LLM harnesses or model clients, and it
doesn't need an API key. **You bring the brain** and call whatever model you like; RoboWorld gives
you the robot, the worlds, the interface and the test bench. A rule-based `baseline` brain is
included as a free reference point.

## Key ideas

**Robots move without training.** RoboLang compiles to motion planning that runs in real time on
a CPU: inverse kinematics, gait generators and balance control. Trained policies are an optional
future upgrade that plugs into the same interface.

**One language for people and models.** RoboLang programs are plain YAML or JSON validated by a
schema, so an LLM can write them reliably through a tool call and a person can read them.

**Vendor-neutral brains.** The robot is an MCP server. Codex, Claude Code, your own harness or any
other MCP client connects the same way.

**Honest perception and scoring.** A brain only learns about objects the robot's camera has seen.
Success is judged by the simulator from ground truth, never by the brain's own claim.

## How the parts fit together

```text
builder:  MCP client ──MCP──► rw serve-mcp ──► RoboLang ──► MuJoCo ──► Rerun recording
brain:    your harness or an MCP agent ──MCP──► rw serve-robot ──► skills ──► robot in a world
bench:    rw bench ──► many episodes ──► report.html, results.csv, summary.json
```

The [architecture](/RoboWorld/concepts/architecture/) page explains each layer in more detail.

## Next steps

- [Install RoboWorld](/RoboWorld/start/installation/) and fetch the robot models.
- Follow the [quickstart](/RoboWorld/start/quickstart/) to run a program, an episode and a small benchmark.
