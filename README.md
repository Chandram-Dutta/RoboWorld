# RoboWorld

Build robots, move them with **RoboLang** (a small language LLMs can write), and test
them in simulated worlds. Think "a suite for making microducks", in many shapes for
many tasks.

Everything runs on a laptop CPU, including an 8 GB M2 Mac. Robots move without any
GPU training: RoboLang compiles to inverse kinematics, gait generators and balance
control. Trained RL policies are an optional upgrade that plugs into the same
interface.

```
builder:  Claude Code / Desktop ──MCP──► rw serve-mcp ──► RoboLang ──► MuJoCo ──► Rerun recording
brain:    any MCP client (Claude, Codex, Gemini, Ollama…) ──MCP──► rw serve-robot ──► skills ──► robot in a world
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
# fixed script (baseline / tests)
uv run rw episode --robot go2 --task find_red_ball --brain scripted --script examples/brains/find_ball_scripted.yaml
# any OpenAI-compatible endpoint: Ollama, LM Studio, vLLM, OpenRouter, OpenAI...
uv run rw episode --robot open_duck_mini_v2 --task push_ball_to_goal --brain openai \
    --base-url http://localhost:11434/v1 --model qwen3:4b
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
  brain/     brains.py (scripted, OpenAI-compatible), runner.py (episodes, agent CLIs)
  episode.py, api.py, cli.py, store.py
examples/    runnable programs
tests/       uv run pytest
```

## Known limits

- Gaits stop gracefully: they finish the current step and decelerate. Expect a few
  centimetres or degrees of overshoot after an `until` fires. For example, a
  quadruped turn overshoots about 9° at 0.9 rad/s.
- Speeds are only tuned inside each gait's `limits` (see `describe_robot`).
  Validation warns when a command goes outside that range.
- Worlds are flat rooms with simple shapes for now. Terrain, randomisation and more
  tasks come in phase 3.
- `walk_to` and `push` have no obstacle avoidance and don't know where the walls
  are.
  - Go2 can push the ball against a wall and then can't get behind it. An LLM
    brain recovers part of the way: in one test it reached 0.2 progress.
  - The duck pushes the ball into the goal in about 37 s.

## Roadmap

Each phase ends with a demo:
1. Foundation and RoboLang v0 (done).
2. Skills, honest perception, episodes, and the robot as an MCP server with
   vendor-neutral brains (done).
3. Worlds (terrain, rooms, objects), tasks and success checks, sweeps comparing
   robots × brains × worlds, reports.
4. Prompt-to-robot design: RoboSpec templates compiled through MjSpec, a servo
   catalog, design checks, version history, and Optuna CMA-ES refinement.
5. Web app with the `@mujoco/mujoco` WASM viewer.
6. Optional:
   - one-time GPU RL per robot family (`stabilizer: policy`)
   - buildable parts (build123d) with a parts list
   - hardware bridges
