---
title: Roadmap
description: What is planned for RoboWorld, and where contributions help most.
---

RoboWorld today covers building and designing robots, controlling them with RoboLang, connecting
brains over MCP, and benchmarking them. These are the next areas of work.

## Planned

- **Web app.** Browse runs and benchmark reports, and replay recordings in the browser with MuJoCo's
  WebAssembly build, without installing the Rerun viewer.
- **Trained policies as an option.** A `policy` stabilizer that runs a trained walking policy behind
  the same velocity-command interface as the built-in gaits, so programs don't change. Training
  would be optional and done outside RoboWorld.
- **Buildable parts.** Export designed robots as printable parts and a bill of materials based on
  the servo catalog.
- **Hardware bridges.** Run RoboLang programs and skills on real servos.

## Where help is welcome

- **More tasks** that test distinct abilities: memory across rooms, multi-object goals, tasks that
  require a custom motion.
- **Sturdier small bipeds**, in particular on rough ground, where the duck-style robots still fall.
- **A get-up skill**, so a fall doesn't have to end an episode.
- **More robots**, from repositories with clear licences.
- **More design templates**, such as wheeled robots and arms.
