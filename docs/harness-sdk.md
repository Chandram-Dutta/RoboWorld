# Bring your own harness

A **harness** is the control loop around a robot's brain. It decides:
- what the model sees
- when the model is asked
- how tool calls are run
- what gets remembered
- when to stop

Two harnesses on the same model and robot can score very differently. In the
benchmark, a rule-based harness went from 53% to 81% success just by adding
exploration and detours.

RoboWorld doesn't ship LLM harnesses. **You build the harness and call whatever
model you like.** RoboWorld provides the robot, the worlds, the interface, the
plug-in points and the test bench.

```
your harness ──► Robot (typed helpers) ──MCP──► rw serve-robot ──► skills ──► simulated robot
```

A harness never touches the simulator. It talks to the robot's MCP server, the
same one Codex or Claude Code would use, so the same harness works:
- in `rw episode` and `rw bench`
- against a robot server you start yourself
- side by side with external agents in one benchmark

## 1. Write one

```bash
uv run rw harness new my_harness            # writes harnesses/my_harness.py + .yaml
uv run rw harness check harnesses/my_harness.yaml
uv run rw bench --brains baseline,harnesses/my_harness.yaml,codex --tasks all --seeds 2
```

```python
from roboworld.harness import Harness, Robot, TaskInfo

class MyHarness(Harness):
    name = "my-harness"

    def __init__(self, model: str = "my-model"):     # constructor args come from the spec's params:
        super().__init__()
        self.model = model

    async def run(self, robot: Robot, task: TaskInfo) -> None:
        await robot.do("look_around")
        seen = await robot.seen()
        target = ...                                   # your logic, or a call to your model
        result = await robot.do("walk_to", target=target)
        self.stats.update(llm_calls=1, cost_usd=0.002)  # anything here is reported
        await robot.finish("went there", success=result.get("ok"))
```

**Rules:**
- Implement `async run(robot, task)`.
- Call `robot.finish(...)` when you're done. If you forget, the runner finishes
  the episode for you and `rw harness check` flags it.
- Only claim `success=True` when you've checked. The benchmark reports the
  overclaim rate.

`examples/harnesses/llm_harness.py` is a short, complete LLM loop: look, ask the
model for the next skill as JSON, do it, repeat. Its `ask()` uses the Codex CLI,
so you can run it with your Codex login and no API key. Replace `ask()` with any
model API.

## 2. `Robot`: what a harness can do

| method | returns |
|---|---|
| `await robot.look()` | `(png_bytes, {"visible_objects": [...], "robot": {...}})` |
| `await robot.observe()` | robot pose, everything seen so far (distance and bearing), last action |
| `await robot.seen()` | just the seen-objects list (walls included, as segments) |
| `await robot.skills()` | skills with argument schemas, plus saved motions |
| `await robot.do(skill, **args)` | `{"ok", "message", "robot", "episode", ...}` |
| `await robot.run(yaml_program)` | runs a RoboLang program |
| `await robot.finish(summary, success=None, answer=None)` | ends the episode |
| `await robot.call(name, args)` | any tool by name, as a `ToolResult` (`text`, `data`, `images`, `is_error`, `ok`) |
| `robot.tools` | the raw MCP tool list, if your model does function calling |
| `robot.over`, `robot.ended_by`, `robot.finished`, `robot.calls`, `robot.log` | state and bookkeeping |

`task` is a `TaskInfo`:
- `instruction`: the task in words
- `prompt`: a ready-made opening prompt
- `briefing`: the server's description of the robot, its tools, coordinates and
  timing
- `robot`, `mode`, `time_limit_s`

`objects_text(seen)` formats what's been seen as compact lines for a prompt.

## 3. Plug it in

**Spec files**, used with `--brains path.yaml` or saved as
`library/brains/<name>.yaml`:

```yaml
name: my-harness
type: harness
harness: path/to/my_harness.py:MyHarness    # or package.module:MyHarness, or an installed entry point name
params: {model: my-model}                   # passed to your constructor
```

**Packages.** Expose harnesses under an entry-point group, and `rw brains` lists
them so they can be used by name:

```toml
[project.entry-points."roboworld.harnesses"]
my-harness = "my_package.harness:MyHarness"
```

**Standalone.** Point a harness at a robot server you started yourself:

```python
import asyncio
from roboworld.harness import connect_and_run
asyncio.run(connect_and_run(MyHarness(), url="http://127.0.0.1:8765/mcp"))   # rw serve-robot ... --http 8765
```

**External agents** that speak MCP themselves (Codex, Claude Code, any CLI) run as
`command` brains. The presets are `codex` and `claude-code`; anything else goes in
`type: command` with a `command:` template.

## 4. Test it

- `rw harness check <spec>` runs one episode (Go2, find the ball, by default) and
  flags:
  - an episode left open
  - invalid tool calls
  - claims of success the simulator didn't confirm
- `rw bench` reports success, progress, time to success, tool calls, invalid calls
  and overclaim rate per brain. If your harness reports `cost_usd`, it also shows
  cost per episode and per success.
- Every episode in `runs/` keeps:
  - `result.json` (your `stats` are under `brain_stats.llm`)
  - `transcript.jsonl` (every tool call)
  - the camera frames the brain looked at
  - a Rerun recording (`rw view <run>`) with the robot's eye view throughout
