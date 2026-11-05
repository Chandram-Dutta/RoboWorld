# RoboWorld

Build robots, move them with **RoboLang** (a small language LLMs can write), and test
them in simulated worlds. Think "a suite for making microducks", in many shapes for
many tasks.

Everything runs on a laptop CPU, including an 8 GB M2 Mac. Robots move without any
GPU training: RoboLang compiles to inverse kinematics, gait generators and balance
control. Trained RL policies are an optional upgrade that plugs into the same
interface.

```
Claude Code / Desktop ──MCP──► roboworld ──► RoboLang interpreter ──► MuJoCo ──► Rerun recording
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
  lang/      schema.py (RoboLang), manifest.py, interpreter.py, validate.py, ik.py, gaits/
  sim/       scene.py, servo.py, state.py, runner.py, metrics.py, recorder.py (Rerun), render.py
  robots/    registry.py + manifests/*.yaml
  mcp/       server.py
  api.py, cli.py, store.py
examples/    runnable programs
tests/       uv run pytest
```

## Known limits

- Gaits stop gracefully: they finish the current step and decelerate. Expect a few
  centimetres or degrees of overshoot after an `until` fires. For example, a
  quadruped turn overshoots about 9° at 0.9 rad/s.
- Speeds are only tuned inside each gait's `limits` (see `describe_robot`).
  Validation warns when a command goes outside that range.
- Everything runs on flat ground for now. Worlds and tasks come in phase 3.

## Roadmap

Each phase ends with a demo:
1. Foundation and RoboLang v0 (done).
2. Skills library and LLM brain harness (Claude / OpenAI-compatible), with camera
   observations and two timing modes: sim paused while the LLM thinks, or real time.
3. Worlds (terrain, rooms, objects), tasks and success checks, sweeps comparing
   robots × brains × worlds, reports.
4. Prompt-to-robot design: RoboSpec templates compiled through MjSpec, a servo
   catalog, design checks, version history, and Optuna CMA-ES refinement.
5. Web app with the `@mujoco/mujoco` WASM viewer.
6. Optional:
   - one-time GPU RL per robot family (`stabilizer: policy`)
   - buildable parts (build123d) with a parts list
   - hardware bridges
