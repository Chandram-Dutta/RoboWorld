---
title: Configuration
description: Environment variables and the folders RoboWorld reads and writes.
---

RoboWorld needs no configuration file. Its behaviour is set by command options, and its folders
by environment variables.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ROBOWORLD_HOME` | The project folder | The root for `assets/`, `runs/`, `library/` and `.cache/` |
| `ROBOWORLD_RUNS_DIR` | `$ROBOWORLD_HOME/runs` | Where results and recordings are written |
| `ROBOWORLD_LIBRARY_DIR` | `$ROBOWORLD_HOME/library` | Where your own robots, designs, motions, worlds, tasks and brains are read from |
| `MUJOCO_GL` | the platform default | MuJoCo's rendering backend; set it to `egl` on a machine without a display |

When RoboWorld starts a robot server or an agent, it passes `ROBOWORLD_HOME`,
`ROBOWORLD_RUNS_DIR` and `ROBOWORLD_LIBRARY_DIR` on, so every process uses the same folders.

## Folders

```text
<ROBOWORLD_HOME>/
├── assets/robots/<robot>/      downloaded robot models (rw fetch)
├── runs/                       one folder per run, episode and benchmark
└── library/                    your own content
    ├── robots/<name>.yaml      registry entries for your robots and designs
    ├── designs/<name>/         design specs, compiled models and metadata
    ├── motions/<robot>/        saved motions, playable with the play skill
    ├── worlds/<name>.yaml      your worlds
    ├── tasks/<name>.yaml       your tasks
    └── brains/<name>.yaml      brain specs usable by name
```

Files in `library/` with the same name as a built-in world or task replace it. Robot names of
built-in robots can't be reused by designs.

## Run IDs

Runs are named `<date>-<time>-<robot>-<suffix>`, episodes `<date>-<time>-<robot>-<task>-<suffix>`
and benchmarks `<date>-<time>-bench[-<name>]`. `rw view latest` opens the most recent recorded
run or episode.
