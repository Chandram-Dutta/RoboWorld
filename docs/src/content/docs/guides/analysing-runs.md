---
title: Analysing runs
description: Replay recordings in Rerun and read the files every run leaves behind.
---

Every program run, episode and benchmark writes its results to a folder in `runs/`. This guide
shows how to find runs, replay them and read their files.

## List recent runs

```sh
uv run rw runs
```

Each line shows the run ID, the status, the distance walked forward and whether the robot fell.
Use `--limit` to show more than the default 15.

## Replay a run in Rerun

```sh
uv run rw view latest           # the most recent run
uv run rw view <run_id>         # a specific run
uv run rw view latest --web     # open the viewer in a browser
```

A recording contains, on one timeline:

| Entity | What it shows |
|---|---|
| `world/robot`, `world/static` | The robot and the scene in 3D |
| `world/trail` | The path the robot's body followed |
| `plots/joints/<joint>/q` and `/target` | Each joint's measured angle and its target |
| `plots/torque/<joint>` | Each joint's torque |
| `plots/base/height`, `plots/base/*_deg` | Body height, roll, pitch and yaw |
| `events` | The event log: steps starting and ending, conditions met, falls |
| `robot/eye` | Episodes only: the robot's camera view, five frames per second |

Comparing a joint's angle with its target is the quickest way to spot a servo that can't keep up:
a large, persistent gap means the joint is overloaded or the motion is too fast.

## Files in a run folder

A program run (`rw run`) writes:

| File | Contents |
|---|---|
| `result.json` | Status, metrics and the event log |
| `program.yaml` | The program that ran |
| `recording.rrd` | The Rerun recording |
| `trajectory.npz` | Time series of the robot's state, for your own analysis |
| `snapshots/`, `contact_sheet.png` | Snapshot images taken during the run |

An episode (`rw episode`, `rw serve-robot`) writes:

| File | Contents |
|---|---|
| `result.json` | Success, progress, timing, brain statistics and metrics |
| `transcript.jsonl` | Every tool call the brain made, with its arguments and result |
| `eye/` | The camera images the brain looked at |
| `recording.rrd` | The Rerun recording, when recording is on |

A benchmark writes a folder named `<timestamp>-bench[-<name>]` with `report.html`,
`results.csv`, `summary.json` and an `episodes/` folder that holds one episode folder per run.

[Results and metrics](/RoboWorld/reference/results/) describes every field.

## Picture a pose

`rw snapshot` renders a robot standing in a named pose, which is useful while writing poses:

```sh
uv run rw snapshot open_duck_mini_v2 --pose home --out duck.png --azimuth 90
```
