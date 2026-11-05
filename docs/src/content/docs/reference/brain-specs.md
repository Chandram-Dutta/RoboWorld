---
title: Brain specs
description: How brains are named, configured and resolved by rw episode, rw bench and rw harness check.
---

Wherever RoboWorld asks for a brain (`--brain`, `--brains` or a harness check), you can give:

| Value | Meaning |
|---|---|
| `baseline` | The built-in rule-based brain. No model, no cost. |
| `codex`, `claude-code` | Presets that run these agent CLIs as the brain |
| A path to a `.yaml` file | A brain spec file |
| A name | `library/brains/<name>.yaml`, or an installed harness entry point |

`rw episode` also accepts `scripted` (with `--script`) and `cmd` (with `--cmd`). `rw brains` lists
everything available.

## Spec files

A spec file names a brain and says how to build it. Its `type` decides the other fields.

### `harness`

Your own `Harness` subclass.

```yaml
name: my-harness
type: harness
harness: harnesses/my_harness.py:MyHarness   # a file path, package.module:Class, or an entry point name
params: {model: my-model, max_steps: 20}     # keyword arguments for the constructor
```

### `command`

An external agent that speaks MCP itself. RoboWorld writes an MCP configuration for the episode,
fills in the placeholders and runs the command.

```yaml
name: my-agent
type: command
command: "my-agent --mcp-config {mcp_config} {prompt}"
```

| Placeholder | Value |
|---|---|
| `{prompt}` | The task prompt |
| `{mcp_config}` | Path to the episode's MCP configuration file |
| `{run_dir}` | The episode's results folder |
| `{run_id}` | The episode's run ID |
| `{codex_flags}` | The server configuration as Codex `-c` flags |

`command` may also be the name of a preset (`codex` or `claude-code`). A command brain runs for at
most 30 minutes per episode.

### `scripted`

A fixed list of tool calls, mainly for tests.

```yaml
name: find-ball-script
type: scripted
script: examples/brains/find_ball_scripted.yaml
```

The script is a YAML list of single-key mappings, tool name to arguments:

```yaml
- look: {}
- do: {skill: look_around}
- do: {skill: walk_to, args: {target: red_ball}}
- finish: {summary: walked to the red ball}
```

### `baseline`

The built-in rule-based brain, with optional `params`.

```yaml
name: baseline
type: baseline
```

### `python`

A brain class with the older `run(session, ...)` interface, loaded from `entry: package.module:Class`
with optional `params`. New brains should use `type: harness`.

## Entry points

Installed packages can register harnesses under the `roboworld.harnesses` entry-point group. They
can then be used by name:

```toml
[project.entry-points."roboworld.harnesses"]
my-harness = "my_package.harness:MyHarness"
```

## Presets

| Name | Command |
|---|---|
| `codex` | `codex exec --skip-git-repo-check --ephemeral -s read-only -o {run_dir}/brain_last_message.txt {codex_flags} {prompt}` |
| `claude-code` | `claude -p {prompt} --mcp-config {mcp_config} --strict-mcp-config --allowedTools mcp__robot` |

The presets need the corresponding CLI installed and signed in.
