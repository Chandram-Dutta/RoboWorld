---
title: Using the builder MCP server
description: Let an AI assistant write motions and design robots through RoboWorld's builder MCP server.
---

The builder MCP server gives an MCP client, such as an AI coding assistant, the tools to write
RoboLang programs, simulate them, look at the result and design robots. You describe what you
want; the assistant uses the tools and refines its work from the metrics and images RoboWorld
returns.

This is separate from the [robot MCP server](/RoboWorld/reference/robot-server/), which a robot *brain* uses
to control one robot inside a task.

## Start the server

The server speaks MCP over stdio:

```sh
uv run rw serve-mcp
```

You normally don't run this yourself. Register it with your MCP client, which then starts it as
needed. Replace `/path/to/RoboWorld` with the folder you cloned.

**Claude Code**

```sh
claude mcp add roboworld -- uv --directory /path/to/RoboWorld run rw serve-mcp
```

**Codex**

```sh
codex mcp add roboworld -- uv --directory /path/to/RoboWorld run rw serve-mcp
```

**Any client that takes a JSON configuration**

```json
{
  "mcpServers": {
    "roboworld": {
      "command": "uv",
      "args": ["--directory", "/path/to/RoboWorld", "run", "rw", "serve-mcp"]
    }
  }
}
```

If the client doesn't inherit your shell's `PATH`, use the absolute path to `uv` (run `which uv`
to find it).

## Write a motion

Ask for a motion in plain words, for example *"make the duck walk one metre while nodding, then
look around"*. A capable assistant works through these tools:

1. `describe_robot` to learn the robot's joints, poses and gaits.
2. `language_reference` to learn RoboLang.
3. `validate_program` to check the program it wrote.
4. `simulate` to run it. The result includes the metrics, the event log and a contact sheet of
   snapshots, so the assistant can see what happened.
5. Repeat until the motion works, then `save_motion` so robot brains can `play` it.

`render_snapshot` shows the robot in a pose, which helps when designing poses before animating
them.

## Design a robot

The same server has the design tools. Ask for something like *"make a duck with longer legs and
ankle roll, check it, and compare it with the template duck on the find-the-ball task"*. The
assistant can use:

- `design_templates` for the starting points and the servo catalog,
- `design_robot` and `derive_robot` to create designs (each returns the spec, the check results and
  a picture),
- `check_design`, `design_history` and `list_designs` to inspect them,
- `tune_design` to search gait settings on a course,
- `compare_designs` to run the same brain on several robots.

See [Designing robots](/RoboWorld/guides/designing-robots/) for what each step does.

## All tools

The [builder MCP server reference](/RoboWorld/reference/builder-server/) lists every tool and its arguments.
