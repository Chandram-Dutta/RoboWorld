---
title: Robot MCP server
description: The tools, prompt and behaviour of the MCP server that exposes one robot in one task to a brain.
---

The robot MCP server exposes **one episode**: one robot, in one task, with one timing mode and
seed. Any MCP client can connect to it and act as the robot's brain.

```sh
rw serve-robot --robot <robot> --task <task> [--mode paused|realtime] [--seed 0] [--http <port>]
```

- **Transport:** stdio by default; streamable HTTP at `http://127.0.0.1:<port>/mcp` with `--http`.
- **Lifetime:** the world is built when the server starts. The episode ends when the brain calls
  `finish`, when the task ends it (success, failure, time limit or a fall), or when the client
  disconnects. Results are written to `runs/<run_id>/`.
- **Server name:** `robot`.

All options are listed under [`rw serve-robot`](/RoboWorld/reference/cli/#rw-serve-robot).

## Instructions

When a client connects, the server sends instructions that describe the robot, the task, the time
limit, the timing mode, the tools, and the coordinate conventions. A harness receives the same text
as `task.briefing`.

The server also offers one prompt, `start`, with the opening task prompt for the episode.

## Tools

### `observe`

Returns the robot's state, everything seen so far and the result of the last action.

```json
{
  "task": "Find the red ball and go stand next to it ...",
  "robot": {"x": 0.0, "y": 0.0, "heading_deg": 0, "tilt_deg": 1.2, "fallen": false},
  "objects_seen": [
    {"name": "red_ball", "kind": "ball", "color": "red", "position": [-1.12, 0.98], "size_m": 0.14,
     "distance_m": 1.49, "bearing_deg": 139, "visible_now": false, "last_seen_s_ago": 3.4}
  ],
  "last_action": {"tool": "do", "args": {...}, "ok": true, "message": "..."},
  "frame": "world metres; x was forward at the start, y to the left; heading in degrees, counter-clockwise"
}
```

`objects_seen` is sorted by distance. `bearing_deg` is relative to the robot's current heading.
Positions are estimates with distance-proportional noise. Walls also carry a `segment` with their
two end points, and areas and boxes a `half_extent`.

### `look`

Returns the robot's camera image (PNG) and the objects visible right now, with the robot's state.
Each `look` image is also saved in the episode's `eye/` folder.

### `skills`

Returns the robot's skills, each with a description, argument schema and required arguments, plus
the robot's saved motions.

### `do`

```text
do(skill: string, args: object | JSON string | null)
```

Runs one skill and waits for it to finish. Returns `ok`, a `message`, the robot's state and the
episode clock. See the [skills reference](/RoboWorld/reference/skills/).

### `run`

```text
run(program: string)
```

Runs a RoboLang program given as YAML text, for motions the skills don't cover. Invalid programs
return `ok: false` with the validation errors and warnings, and count as invalid calls.

### `status`

Returns the task, the robot, the timing mode, the time limit, whether the task has succeeded and the
number of tool calls so far.

### `finish`

```text
finish(summary: string = "", success: boolean | null = null, answer: string | null = null)
```

Ends the episode. `summary` describes what the brain did. `success` is the brain's own claim; it is
recorded and compared with the simulator's verdict but doesn't change it. `answer` is the answer for
tasks that ask a question.

## Episode clock

Every result includes the episode clock:

```json
"episode": {"time_s": 19.1, "time_left_s": 130.9, "over": true, "ended_by": "success"}
```

Once `over` is `true`, actions return `ok: false` with the reason the episode ended.

## Concurrency

All simulation and rendering work for an episode runs on a single worker thread, in the order the
calls arrive. A client may send calls concurrently, but they are executed one at a time.
