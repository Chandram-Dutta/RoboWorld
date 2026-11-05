---
title: Builder MCP server
description: The tools of the builder MCP server, for writing motions and designing robots.
---

The builder MCP server is for building: describing robots, writing and simulating motions, and
designing robots. Start it with `rw serve-mcp` (stdio). See
[Using the builder MCP server](/RoboWorld/guides/builder-mcp/) for how to register it with a client.

## Robots and motions

| Tool | Arguments | Returns |
|---|---|---|
| `list_robots` | | Every robot with its kind and description |
| `describe_robot` | `robot` | Joints with ranges, aliases, limbs, end-effectors, poses and gaits with tuned defaults |
| `language_reference` | | The RoboLang reference |
| `validate_program` | `robot`, `program` | Errors, warnings and the estimated duration |
| `simulate` | `robot`, `program`, `max_seconds = 30`, `look = true` | Status, metrics, events and run ID; with `look`, a contact sheet of snapshots as an image |
| `render_snapshot` | `robot`, `pose?`, `joints?`, `azimuth = 135` | A picture of the robot in a pose, optionally with joint overrides |
| `save_motion` | `robot`, `name`, `program`, `description?` | Validates the program and saves it as a motion that brains can `play` |
| `list_motions` | `robot` | The robot's saved motions |

`program` is RoboLang as YAML or JSON text. `simulate` returns one of these statuses: `completed`,
`fell`, `timeout` or `invalid`.

Motion names use 1–40 characters from `a-z`, `0-9` and `_`.

## Tasks and runs

| Tool | Arguments | Returns |
|---|---|---|
| `list_tasks` | | Every task with its world and instruction |
| `list_runs` | `limit = 10` | The most recent runs |
| `get_run` | `run_id` | A run's full result: metrics, events, program and recording paths |

## Robot design

| Tool | Arguments | Returns |
|---|---|---|
| `design_templates` | | The design templates and the servo catalog |
| `design_robot` | `name`, `template`, `changes?`, `note?` | Creates, compiles and checks a design; returns its spec, check report and a picture |
| `derive_robot` | `parent`, `name`, `changes`, `note?` | Creates a child design; returns the same as `design_robot` |
| `check_design` | `name` | The check report for a design or any robot |
| `list_designs` | | Every design with its parent, last check result and note |
| `design_history` | `name` | A design and its ancestors, newest first |
| `tune_design` | `name`, `course = "flat"`, `trials = 24` | The tuning result; saves the best settings as a child design if they are better |
| `compare_designs` | `robots`, `tasks = "all"`, `seeds = 2`, `brain = "baseline"` | Success per robot and per task, and the report path |

`changes` is a YAML mapping in the same form as the CLI's `--changes`; see
[Describe changes](/RoboWorld/guides/designing-robots/#describe-changes).
