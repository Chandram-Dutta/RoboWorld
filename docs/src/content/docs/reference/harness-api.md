---
title: Harness API
description: The Python classes and functions for writing a harness - Harness, Robot, TaskInfo and helpers.
---

```python
from roboworld.harness import Harness, Robot, TaskInfo, ToolResult, connect_and_run, objects_text
```

See [Building a harness](/RoboWorld/guides/building-a-harness/) for a walkthrough.

## `Harness`

Subclass it and implement `run`.

| Member | Description |
|---|---|
| `name: str` | The harness's name in results and reports. Default `"harness"`. |
| `stats: dict` | Anything you put here is saved with the episode (under `brain_stats.llm` in `result.json`) and summarised in benchmark reports. Call `super().__init__()` to create it. |
| `async run(robot, task) -> None` | Your control loop. Required. |

The runner connects to the robot server, builds a `TaskInfo`, and awaits `run`. If `run` returns
without calling `robot.finish`, the runner finishes the episode for you.

These `stats` keys have special meaning in benchmark reports:

| Key | Meaning |
|---|---|
| `llm_calls` | Number of model calls |
| `prompt_tokens`, `completion_tokens` | Token counts; their sum is reported as tokens per episode |
| `cost_usd` | Cost of the episode; reported per episode and per success |

## `Robot`

The robot as a harness sees it: typed helpers over the robot server's MCP tools. Every call goes
over MCP, so a harness behaves the same in a local episode, against a remote server and in a
benchmark.

### Methods

| Method | Returns |
|---|---|
| `await robot.observe()` | The robot's state, objects seen so far and the last action's result |
| `await robot.look()` | `(png_bytes or None, info)`: the camera image and the objects visible right now |
| `await robot.seen()` | The list of objects seen so far, walls included |
| `await robot.skills()` | `{"skills": [...], "saved_motions": [...]}` |
| `await robot.do(skill, **args)` | The skill's result: `ok`, `message`, `robot` and `episode` |
| `await robot.run(program)` | The result of a RoboLang program given as YAML text |
| `await robot.status()` | The task, clock and success so far |
| `await robot.finish(summary="", success=None, answer=None)` | Ends the episode |
| `await robot.call(name, args=None)` | Calls any tool by name and returns a `ToolResult` |

`do` takes skill arguments as keyword arguments: `await robot.do("walk_to", target="red_ball")`.

### Attributes

| Attribute | Description |
|---|---|
| `tools` | The raw MCP tool definitions (name, description, input schema), for models with function calling |
| `over` | `True` once the episode has ended |
| `ended_by` | Why it ended: `success`, `failed`, `fell`, `time_limit`, `brain_finished` and so on |
| `finished` | `True` once `finish` has been called |
| `calls`, `failed_calls` | Number of tool calls, and how many failed |
| `log` | One entry per call: tool, arguments, `ok` and the start of the result |

## `TaskInfo`

| Field | Description |
|---|---|
| `robot` | The robot's name |
| `instruction` | The task, in words |
| `prompt` | A ready-made opening prompt for a model |
| `briefing` | The server's instructions: the robot, its tools, coordinates and the timing mode |
| `time_limit_s` | The task's time limit in simulated seconds |
| `mode` | `paused` or `realtime` |

## `ToolResult`

Returned by `robot.call`.

| Field | Description |
|---|---|
| `text` | The tool's text output |
| `data` | The text parsed as a JSON object, or `None` |
| `images` | Images returned by the tool, as bytes |
| `is_error` | Whether the MCP call itself failed |
| `ok` | `True` if the call succeeded and the result doesn't report `ok: false` or an error |

## `objects_text(seen)`

Formats a list of seen objects as compact lines for a prompt:

```text
- red_ball: red ball at (-1.12, 0.98), 1.49 m away, bearing 139°
- green_goal: green goal (painted on the floor) at (1.50, -0.90), 1.75 m away, bearing -31° (visible now)
- walls seen: wall_east, wall_north
```

## `connect_and_run`

```python
async def connect_and_run(harness, url=None, command=None) -> Robot
```

Runs a harness against a robot server you started yourself. Pass `url` for a server started with
`rw serve-robot --http <port>` (for example `http://127.0.0.1:8765/mcp`), or `command` (a list of
arguments) to launch a server over stdio. Returns the `Robot` after the harness has finished.
