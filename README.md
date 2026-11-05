# RoboWorld

A toolkit for **building robots** and **testing robot brains**:
- Build robots and move them with **RoboLang** (a small language LLMs can write).
- Bring your own brain (your harness, or any MCP agent) and test it in simulated
  worlds against a benchmark.

Think "a suite for making microducks", in many shapes for many tasks. RoboWorld
doesn't ship LLM harnesses; it gives you the robot, the worlds and the test bench
to build and compare yours.

Everything runs on a laptop CPU, including an 8 GB M2 Mac. Robots move without any
GPU training: RoboLang compiles to inverse kinematics, gait generators and balance
control. Trained RL policies are an optional upgrade that plugs into the same
interface.

```
builder:  Claude Code / Desktop ──MCP──► rw serve-mcp ──► RoboLang ──► MuJoCo ──► Rerun recording
brain:    your harness, or any MCP agent (Codex, Claude Code…) ──MCP──► rw serve-robot ──► skills ──► robot in a world
```

## Quick start

```bash
uv sync
uv run rw robots                          # built-in robots
uv run rw fetch open_duck_mini_v2         # download models (pinned, sparse clone)
uv run rw fetch go2 && uv run rw fetch so_arm101
uv run rw run open_duck_mini_v2 examples/duck_walk_and_nod.yaml
uv run rw view latest                     # replay in Rerun: 3D, joint plots, events
```

### Use it from Claude Code (MCP)

```bash
claude mcp add roboworld -- uv --directory /path/to/RoboWorld run rw serve-mcp
```

Then ask something like *"make the duck walk 1 m while nodding, then look around"*.
Claude reads `describe_robot` and `language_reference`, writes a program, then calls
`validate_program` and `simulate`. It looks at the returned metrics and snapshot
sheet, and refines.

| MCP tool | purpose |
|---|---|
| `list_robots`, `describe_robot` | names of joints, limbs, poses, gaits (and tuned defaults) |
| `language_reference` | RoboLang docs and examples |
| `validate_program` | errors and warnings before running |
| `simulate` | run it: status, metrics, events, a contact sheet of snapshots |
| `render_snapshot` | picture of a pose |
| `list_runs`, `get_run` | past runs |

## Robot brains over MCP (vendor-neutral)

The robot itself is an MCP server. Any MCP client can be its brain, and nothing on
the robot side depends on one model vendor.

```bash
uv run rw tasks                                   # find_red_ball, push_ball_to_goal, ...
uv run rw serve-robot --robot open_duck_mini_v2 --task push_ball_to_goal     # stdio
uv run rw serve-robot --robot go2 --task find_red_ball --http 8765          # or streamable HTTP
uv run rw robot-config --robot go2 --task find_red_ball                     # MCP config JSON for any client
```

The brain only gets what a real robot would have:

| tool | what it does |
|---|---|
| `observe` | the robot's pose, every object seen so far (with distance and bearing), and the last action's result |
| `look` | the head-camera image plus the objects visible right now (ray-cast detector) |
| `skills` | `stand`, `walk`, `strafe`, `turn`, `face`, `walk_to`, `look_around`, `look_at`, `push`, `play` |
| `do(skill, args)` | runs a skill and returns ok/failed with a reason |
| `run(program)` | runs any RoboLang program |
| `status`, `finish` | episode clock and wrap-up |

The simulator judges success from ground truth; the brain's own claim doesn't
count.

**Timing modes:**
- `paused`: the world waits while the brain thinks.
- `realtime`: the thinking time is simulated before the next action, so slow
  brains lose time and rolling balls keep rolling.

**Saved results** (in `runs/<id>/`):
- `result.json`: success, progress, time, tool calls, invalid calls, thinking time
  and tokens
- `transcript.jsonl`
- `recording.rrd`
- `eye/*.png` camera frames

Run unattended episodes (benchmarks) with any brain:

```bash
# your harness (see "Bring your own harness" below)
uv run rw episode --robot go2 --task find_red_ball --brain harnesses/my_harness.yaml
# fixed script (baseline / tests)
uv run rw episode --robot go2 --task find_red_ball --brain scripted --script examples/brains/find_ball_scripted.yaml
# an agent CLI as the brain (it launches the robot server itself from the generated MCP config)
uv run rw episode --robot go2 --task find_red_ball --brain codex
uv run rw episode --robot go2 --task find_red_ball --brain claude-code
uv run rw episode --robot go2 --task find_red_ball --brain cmd --cmd 'my-agent --mcp {mcp_config} {prompt}'
```

**Interactive Codex.** Register the robot once (one server is one episode; a new
Codex session starts a fresh one):

```bash
codex mcp add robot -- /opt/homebrew/bin/uv --directory /path/to/RoboWorld run rw serve-robot \
    --robot open_duck_mini_v2 --task push_ball_to_goal --brain codex
```

Then in `~/.codex/config.toml`, under `[mcp_servers.robot]`, set
`tool_timeout_sec = 900` (long skills take a while). Optionally also set
`default_tools_approval_mode = "approve"` so robot tools don't ask each time.

**Build to brain:** motions you design with the builder server's `save_motion`
become playable by the robot's brain through the `play` skill.

## RoboLang in 20 lines

```yaml
robot: open_duck_mini_v2
on_fall: stop
do:
  - pose: home                             # named pose or {joint: radians}
    duration: 0.4
  - parallel:                              # different limbs at the same time
      - gait: {type: biped_walk, velocity: {vx: 0.12}}
        until: {any: [{distance_traveled: 1.0}, {timeout: 15}]}
      - clip:                              # keyframes, aliases like head.pitch
          keys: [{t: 0.4, head.pitch: 0.25}, {t: 0.4, head.pitch: -0.15}]
          repeat: 30
    race: true
  - clip: {keys: [{t: 0.6, head.yaw: 0.8}, {t: 1.0, head.yaw: -0.8}, {t: 0.6, head.yaw: 0}]}
```

The verbs are `pose`, `clip`, `gait`, `reach` (IK), `wait`, `repeat`, `parallel` and
`do`. Any step can also take `until:` with `timeout`, `distance_traveled`,
`displacement`, `turned`, `fallen`, `reached`, `any` or `all`. The full reference is
[src/roboworld/lang/reference.md](src/roboworld/lang/reference.md), or run
`rw lang`.

**Levels.**
- A **manifest** names each robot's parts. It is generated from the model and
  refined by `src/roboworld/robots/manifests/<robot>.yaml`.
- **Motions and gaits** are what programs are written in.
- A **safety layer** always runs: it clamps to joint limits, limits joint speed to
  what the servos can do, and stops on a fall.

## Robots

| robot | kind | source |
|---|---|---|
| `open_duck_mini_v2` | biped (14× STS3215) | [Open Duck Playground](https://github.com/apirrone/Open_Duck_Playground) MJCF; hardware [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini) (Apache-2.0) |
| `go2` | quadruped | [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) (BSD-3) |
| `so_arm101` | arm | MuJoCo Menagerie (Apache-2.0) |

You can bring your own robot: add `library/robots/<name>.yaml` with
`source: {type: path, path: ..., model: robot.xml}` plus `manifest:` overrides.

## How the duck walks without RL

`biped_walk` works in four layers:
1. A footstep planner.
2. Kajita's ZMP preview control on a linear inverted pendulum.
3. Swing-foot arcs.
4. mink IK.

The Open Duck has no ankle roll, so a flat foot fixes where the foot sits sideways
relative to the hip. That means it can't shift its weight sideways with both feet
flat. The gait therefore lets the feet roll and constrains only foot pitch and yaw.
Heading hold steers the footstep plan back on course, and the footsteps are
re-planned at every step boundary.

The defaults in the manifest come from a sweep of 48 settings × 6 commands (forward,
fast, turn, sideways, backward, arc). The chosen set walks all six without falling.

## Layout

```
src/roboworld/
  lang/      schema.py (RoboLang), manifest.py, interpreter.py, validate.py, ik.py, gaits/, skills.py
  sim/       scene.py, servo.py, state.py, runner.py, metrics.py, recorder.py (Rerun), render.py, perception.py
  world/     spec.py + library/{worlds,tasks}/*.yaml
  robots/    registry.py + manifests/*.yaml
  mcp/       server.py (builder), robot_server.py (the robot as an MCP server)
  harness/   core.py (Harness, Robot, TaskInfo), adapter.py (runner/bench glue, connect_and_run)
  brain/     brains.py, baseline.py (rule-based harness), registry.py (specs, entry points), runner.py
  episode.py, bench.py, api.py, cli.py, store.py
docs/harness-sdk.md
examples/harnesses/  example harnesses (rule-based, short LLM loop);  examples/brains/  scripted brains
examples/    runnable programs
tests/       uv run pytest
```

## Benchmark: robots × brains × tasks

```bash
uv run rw tasks                       # 8 tasks, random placements per seed
uv run rw brains                      # baseline, codex, claude-code, your specs
uv run rw bench --robots go2,open_duck_mini_v2 --tasks all \
    --brains baseline,examples/harnesses/explorer.yaml,codex --seeds 3
```

Each run writes `runs/<bench>/report.html` with three parts:
- a leaderboard: success, progress, time, tool calls, invalid calls, overclaim
  rate and tokens
- a task-by-robot success grid
- every episode

`results.csv` and `summary.json` hold the same data for your own analysis.

| task | tests |
|---|---|
| `find_red_ball` | searching (the ball is somewhere behind the robot) |
| `push_ball_to_goal` | pushing a rolling object |
| `box_to_red_area` | pushing a sliding object |
| `reach_marker_behind_crates` | exploring and detouring (the target is hidden) |
| `cross_bumpy_ground` | walking robustness |
| `visit_crate_then_ball` | ordered, multi-step goals |
| `count_red_balls` | perception and reporting (`finish(answer=…)`) |
| `avoid_red_zone` | following a constraint (touching the zone fails the task) |

**Honest scoring.**
- The simulator judges success from ground truth.
- A brain can claim success with `finish(success=true)`. The report counts how
  often that claim was wrong (the overclaim rate).
- Perception only covers what the camera has seen, including walls.

Example: baseline vs. the example harness, same robots and skills, 2 seeds:

| | Go2 | Duck | total |
|---|---|---|---|
| `baseline` (rules) | 11/16 | 6/16 | 17/32 |
| `explorer` (rules + exploration + detours) | 15/16 | 10/16 | 25/32 |

**What changed with the brain (the harness):**
- avoid red zone: 0/4 → 4/4
- reach the marker behind the crates: 0/4 → 3/4

**What depends on the body:** the duck falls on the bumps and trips over the box,
whatever the brain does.

## Bring your own harness

A harness is the control loop around a robot brain. It decides what the model sees,
when the model is asked, how tool calls run, and when to stop. **You write the
harness and call whatever model you like**; RoboWorld gives you the interface, the
plug-in points and the test bench. The full guide is
[docs/harness-sdk.md](docs/harness-sdk.md).

```bash
uv run rw harness new my_harness                  # scaffold: harnesses/my_harness.py + .yaml
uv run rw harness check harnesses/my_harness.yaml # one quick episode + sanity checks
uv run rw bench --brains baseline,harnesses/my_harness.yaml,codex --tasks all --seeds 3
```

```python
from roboworld.harness import Harness, Robot, TaskInfo

class MyHarness(Harness):
    name = "my-harness"

    async def run(self, robot: Robot, task: TaskInfo) -> None:
        await robot.do("look_around")
        r = await robot.do("walk_to", target="red_ball")
        await robot.finish("done", success=r.get("ok"))
```

**What RoboWorld provides:**
- **`Robot`:** typed helpers over the robot's MCP tools (`look`, `observe`, `seen`,
  `do`, `run`, `finish`, `call`) and `TaskInfo` (the task, briefing, timing).
- **Plug-in points:**
  - spec files (`type: harness`, `params:` for your constructor)
  - Python entry points (`roboworld.harnesses`)
  - standalone use via `connect_and_run(url=...)` against `rw serve-robot --http`
- **Testing:**
  - `rw harness check` runs one episode and sanity-checks it
  - `rw bench` compares your harness against the baseline and against agents such
    as Codex
  - every episode keeps its transcript and recording
  - whatever your harness puts in `self.stats` (model calls, tokens, `cost_usd`…)
    is reported, including cost per success
- **Examples:**
  - `examples/harnesses/explorer.py`: rule-based
  - `examples/harnesses/llm_harness.py`: a short LLM loop; its `ask()` uses the
    Codex CLI, so swap in your own model

## Known limits

- Gaits stop gracefully: they finish the current step and decelerate. Expect a few
  centimetres or degrees of overshoot after an `until` fires.
- Speeds are only tuned inside each gait's `limits`.
- `walk_to` has deliberately no obstacle avoidance; getting around things is the
  brain's job. `push` plans its own approach and detours around walls and obstacles
  it has seen.
  - If an object is pinned against a wall, `push` says so instead of trying.
- Physics findings, not bugs:
  - The duck (no ankle roll, soft servos) falls on 1–1.5 cm bumps.
  - The duck trips when shoving a box.
  - Go2 pushes boxes about half the time; they slide off-line.

## Roadmap

Each phase ends with a demo:
1. Foundation and RoboLang v0 (done).
2. The robot as an MCP server: skills, honest perception, episodes, and
   vendor-neutral brains (done).
3. Benchmark: 8 randomised tasks, walls in perception, a sturdier push, `rw bench`
   reports, plug-in harnesses, overclaim tracking (done).
4. Bring-your-own-harness: the `Harness`/`Robot` interface, plug-in points (specs,
   entry points, standalone), `rw harness new/check`, and harness-reported metrics
   in the benchmark (done).
5. Prompt-to-robot design: RoboSpec templates compiled through MjSpec, a servo
   catalog, checks, version history, and Optuna. The benchmark judges the designs.
6. Web app with the `@mujoco/mujoco` WASM viewer.
7. Optional:
   - GPU RL policy stabilizer
   - buildable parts
   - hardware bridges
