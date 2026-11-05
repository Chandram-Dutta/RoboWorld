---
title: Conventions
description: The rules RoboWorld's code follows - control, frames, perception, collisions, threading and reproducibility.
---

These conventions keep RoboWorld's behaviour consistent and its measurements trustworthy. Follow
them in every change.

## Control

- **RoboLang speaks joint position targets only.** The servo layer (`sim/servo.py`) turns targets
  into actuator commands: position actuators get the target directly, torque motors get a PD loop
  on every physics step.
- **Never bypass the interpreter's safety layer.** Every target, including those from skills and
  gaits, is clamped to joint ranges and rate-limited.

## Frames and signs

- Gait and inverse-kinematics targets are in the base body's local frame. `lang/ik.py` uses a
  fixed-base copy of the robot, with the free joint and keyframes removed.
- Rotations compose as R = Rz · Ry · Rx. **Pitch is positive when the nose goes down.**
- Tilt correction: **bipeds use a positive gain** (keep the legs vertical in the world), and
  **multi-legged robots use a negative gain** (level the body by changing leg lengths).

## Perception and skills

- **Perception is honest.** Skills may only use `Perception.memory`, never ground truth. Ground
  truth (for example `Episode._distance`) is only for scoring.
- **Skills report failures with `ok: false`** and a reason a model can act on. Don't raise
  exceptions for expected failures such as an unseen target or a blocked path.
- **Skills run at the speeds checks use**: 85% of a gait's tested limits. Design checks test at the
  same speeds.

## Collisions

Collision groups use MuJoCo's `contype` and `conaffinity` bits:

| Geometry | `contype` | `conaffinity` | Touches |
|---|---|---|---|
| World objects and walls | 9 | 5 | Robots and each other |
| Body stand-ins (visual meshes of robot bodies with no collision geometry) | 4 | 8 | World objects only, not the floor or the robot |
| Designed robots | 2 | 1 | The floor and world objects, not themselves |

Painted regions have no collision.

## Threading

The robot MCP server runs all MuJoCo and rendering work on **one executor thread**. Keep it that
way: OpenGL contexts are bound to the thread that created them on some platforms.

## Reproducibility

- **Randomness comes from the seed only.** Use `numpy.random.default_rng(seed)`; never the global
  random state.
- **Don't depend on object identity or unordered iteration.** MuJoCo's `MjSpec` returns new
  Python wrapper objects on every access, so compare elements by name, never with `id()` or `is`.
  Iterate over sets of strings in sorted order when the order affects behaviour; Python randomises
  string hashing between processes.
- Tests that start robot servers use `ROBOWORLD_RUNS_DIR`, which the runner passes to every
  subprocess, together with `ROBOWORLD_LIBRARY_DIR`.

## Robot models

- **Models are fetched, not vendored.** `rw fetch` does a sparse clone at a pinned commit into
  `assets/robots/`, which is not in git.
- **Never commit third-party model files.** The Open Duck Playground repository has no licence
  file, so its files must never be added to this repository.
- New built-in robots must come from a public repository with a clear licence.

## Designed robots

- Generated robots follow the compiler's naming: `<leg>_<part>` joints, `<leg>_foot` sites, the
  `head_cam` site, and `neck_pitch` / `head_yaw` aliased to `head.pitch` / `head.yaw`.
- Designs live in `library/designs/<name>/` with registry entries in `library/robots/`. Both are
  user content and are not in git.
- Subprocesses find the library through `ROBOWORLD_LIBRARY_DIR`.

## Benchmark

- `bench.run_bench` points `paths.RUNS_DIR` at the benchmark folder while it runs; robot servers
  receive it through `ROBOWORLD_RUNS_DIR`.
- Check skill and task changes with `rw bench --brains baseline` on both the Go2 and the Open Duck,
  before and after.

## Library versions

RoboWorld uses current versions of its dependencies, which differ from older examples you may find:

| Library | Note |
|---|---|
| MCP 2.x | `from mcp.server.mcpserver import MCPServer` (formerly FastMCP). Types are snake_case: `input_schema`, `is_error`, `server_info`. |
| MuJoCo 3.17 | Lights use `type=mjLIGHT_DIRECTIONAL`. `joint.damping` is a 3-vector. |
| Rerun 0.42 | `set_time(..., duration=...)` and `Scalars.columns`. |
| NumPy 2.5 | `np.cross` no longer accepts 2-D vectors. |

## Code style

- Python 3.12 with type hints and `from __future__ import annotations`.
- Pydantic models with `extra="forbid"` for anything users or models write, so typos are errors.
- Error messages say what is wrong and what to do, and suggest close matches for unknown names.
- Keep the linter clean: `uvx ruff check src tests --select F,E9,B --ignore B008`.
