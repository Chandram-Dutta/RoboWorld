---
title: CLI reference
description: Every rw command, its arguments and options.
---

The command-line tool is installed as `rw` (and as `roboworld`). Run `rw <command> --help` for the
same information in the terminal. Commands that print structured results print JSON.

## Robots

### `rw robots`

Lists every robot (built-in, added and designed) with its kind, and whether its model is available.

### `rw fetch`

```sh
rw fetch <robot> [--force]
```

Downloads a robot's model files with a sparse clone of its source repository at the pinned commit,
into `assets/robots/<robot>/`. `--force` downloads again even if the files exist.

### `rw describe`

```sh
rw describe <robot>
```

Prints the robot's manifest: joints with ranges, limbs, aliases, end-effectors, feet, poses, gaits
with their tuned settings and limits, and safety settings.

### `rw snapshot`

```sh
rw snapshot <robot> [--pose <name>] [--out snapshot.png] [--azimuth 135]
```

Renders the robot standing in a pose (the default pose if omitted) to a PNG. `--azimuth` rotates
the camera around the robot, in degrees.

## Programs and runs

### `rw lang`

Prints the RoboLang reference.

### `rw check`

```sh
rw check <robot> <program>
```

Validates a program file against a robot without running it. Prints errors, warnings and the
estimated duration. Exits with status 1 if there are errors.

### `rw run`

```sh
rw run <robot> [program] [options]
```

Simulates a program and records the run in `runs/`. Exits with status 0 if the program completed.

| Option | Default | Meaning |
|---|---|---|
| `--idle` | off | Stand still for a few seconds instead of running a program |
| `--seconds <float>` | `30.0` | Maximum simulated seconds |
| `--snapshots <int>` | `4` | Number of snapshot images |
| `--view` | off | Open the Rerun viewer afterwards |

### `rw runs`

```sh
rw runs [--limit 15]
```

Lists recent runs with their status, forward distance and whether the robot fell.

### `rw view`

```sh
rw view [run_id] [--web]
```

Opens a run's recording in the Rerun viewer. `run_id` defaults to `latest`. `--web` opens the viewer
in a browser.

## Tasks and episodes

### `rw tasks`

Lists every task with its world and instruction.

### `rw serve-robot`

```sh
rw serve-robot --robot <robot> --task <task> [options]
```

Runs one episode as an MCP server, so any MCP client can be the robot's brain.

| Option | Default | Meaning |
|---|---|---|
| `--robot` | required | Robot name |
| `--task` | required | Task name |
| `--mode` | `paused` | `paused` or `realtime` |
| `--seed` | `0` | Random placement seed |
| `--run-id` | generated | Results go to `runs/<run_id>/` |
| `--brain` | | A label for the brain, recorded in the results |
| `--http <port>` | | Serve streamable HTTP on `127.0.0.1:<port>` instead of stdio |
| `--record` / `--no-record` | `--record` | Write a Rerun recording of the episode |

### `rw robot-config`

```sh
rw robot-config --robot <robot> --task <task> [--mode paused] [--seed 0] [--brain external]
```

Prints an MCP configuration (JSON) that starts the robot server for one episode, for MCP clients
that take a configuration file.

### `rw episode`

```sh
rw episode --robot <robot> --task <task> --brain <brain> [options]
```

Runs one episode with a brain and prints a summary of the result.

| Option | Default | Meaning |
|---|---|---|
| `--robot` | required | Robot name |
| `--task` | required | Task name |
| `--brain` | required | A brain name, a spec file, `scripted` or `cmd` (see [Brain specs](/RoboWorld/reference/brain-specs/)) |
| `--script <path>` | | For `scripted`: a YAML list of tool calls |
| `--cmd <command>` | | For `cmd`: an agent command with `{prompt}` and `{mcp_config}` placeholders |
| `--mode` | `paused` | `paused` or `realtime` |
| `--seed` | `0` | Random placement seed |
| `--max-turns` | `40` | Turn limit for in-process brains |

### `rw brains`

Lists the brains you can use: the baseline, agent presets, specs in `library/brains/` and installed
harness entry points.

### `rw bench`

```sh
rw bench [options]
```

Runs robots × brains × tasks × seeds and writes a report.

| Option | Default | Meaning |
|---|---|---|
| `--robots` | `go2,open_duck_mini_v2` | Comma-separated robots |
| `--tasks` | `all` | Comma-separated tasks, or `all` |
| `--brains` | `baseline` | Comma-separated brains |
| `--seeds` | `2` | Random placements per task |
| `--mode` | `paused` | `paused` or `realtime` |
| `--jobs` | `3` | Episodes in parallel (agent CLIs run one at a time) |
| `--max-turns` | `40` | Turn limit for in-process brains |
| `--record` / `--no-record` | `--no-record` | Keep Rerun recordings |
| `--name` | | Label for the benchmark folder |

## Harnesses

### `rw harness new`

```sh
rw harness new <name> [--dir harnesses]
```

Writes a harness class (`<name>.py`) and its spec (`<name>.yaml`).

### `rw harness check`

```sh
rw harness check <spec> [--robot go2] [--task find_red_ball] [--seed 0] [--max-turns 40]
```

Runs one episode with a harness and reports problems: an episode left open, a missing
`finish` call, invalid tool calls and unconfirmed success claims. Exits with status 1 if there are
problems other than an unconfirmed claim.

## Robot design

### `rw design templates`

Lists the design templates.

### `rw design servos`

Lists the servo catalog: torque, speed, mass and a note for each servo.

### `rw design new`

```sh
rw design new <name> --template <template> [--set key=value ...] [--changes <yaml>] [--note <text>] [--no-check]
```

Creates a robot from a template plus optional changes, compiles it and runs its checks. See
[Describe changes](/RoboWorld/guides/designing-robots/#describe-changes) for the change syntax.

### `rw design derive`

```sh
rw design derive <parent> <name> [--set key=value ...] [--changes <yaml>] [--note <text>] [--no-check]
```

Creates a child design from an existing design.

### `rw design check`

```sh
rw design check <name>
```

Runs the physical and walking checks on a design, or on any robot.

### `rw design show`

```sh
rw design show <name>
```

Prints a design's spec and metadata.

### `rw design list`

Lists every design with its parent, last check result and note.

### `rw design history`

```sh
rw design history <name>
```

Lists a design and its ancestors, newest first.

### `rw design tune`

```sh
rw design tune <name> [--course flat|bumpy] [--trials 24] [--as <new_name>]
```

Searches the design's gait settings on a course and saves the best as a child design, if it beats
the current settings.

### `rw design compare`

```sh
rw design compare <robot> <robot> ... [--tasks all] [--seeds 2] [--brain baseline] [--jobs 3]
```

Runs the same brain on several robots across tasks and seeds, and writes a benchmark report.

## MCP

### `rw serve-mcp`

Runs the [builder MCP server](/RoboWorld/reference/builder-server/) on stdio.
