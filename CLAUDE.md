# RoboWorld: notes for Claude

## Commands

| what | command |
|---|---|
| Run the tests (about 5 s) | `uv run pytest -q` |
| Lint | `uvx ruff check src tests --select F,E9,B --ignore B008` |
| Run a program | `uv run rw run <robot> <program.yaml>` |
| Replay a run | `uv run rw view latest` |

## Conventions

- **RoboLang programs speak joint position targets only.**
  - `sim/servo.py` turns targets into actuator commands: position actuators get the
    target directly; torque motors get a PD loop on every physics step.
  - Don't bypass the interpreter's safety layer (clamping and rate limits).
- **Frames:**
  - Gait and IK targets are in the base body's local frame. `lang/ik.py` uses a
    fixed-base copy of the robot (free joint and keyframes deleted).
  - Pitch is positive when the nose is down (R = Rz·Ry·Rx).
  - For tilt correction, bipeds use a positive gain (keep the legs vertical in the
    world) and quadrupeds use a negative gain (level the body by changing leg
    lengths).
- **Robot models are fetched, not vendored.**
  - `rw fetch` does a sparse clone at the pinned commit into `assets/robots/`, which
    is gitignored.
  - The Open Duck Playground repo has no license file, so never commit its files.
- **Tuning sweeps:**
  - Use `Simulation.run(..., save=False)` so they don't fill `runs/`.
  - On macOS, multiprocessing needs an `if __name__ == "__main__":` guard.
- **Episodes:**
  - The robot MCP server (`mcp/robot_server.py`) runs all MuJoCo and GL work on one
    executor thread. Keep it that way: macOS GL contexts are thread-bound.
  - Perception is honest: skills may only use `Perception.memory`, never ground
    truth. Ground truth (`Episode._distance`) is only for scoring.
  - Skills report failures through `Skill.report(ok=False, message)` with a reason
    an LLM can act on. Don't raise for expected failures.
  - Tests that spawn the server use `ROBOWORLD_RUNS_DIR`, which
    `runner.server_env` passes through.
- **Benchmark:**
  - `bench.run_bench` swaps `paths.RUNS_DIR` to the bench folder while it runs,
    and the robot servers get it through `ROBOWORLD_RUNS_DIR`.
  - Skill and task changes should be checked against
    `rw bench --brains baseline` for both robots before and after.
- **Harnesses:**
  - RoboWorld is a platform. It does **not** ship or tune LLM harnesses or model
    clients; users bring their own.
  - The core is the `Harness`/`Robot` interface, the plug-in points,
    `rw harness new/check`, and the benchmark.
  - When a harness does badly, improve the platform side (skills, perception,
    tasks, metrics).
  - Old `run(session, …)` brains still work through `registry.as_brain`.
- **Collision bits:**
  - World geoms use contype 9 / conaffinity 5.
  - Robot "body proxies" (visual meshes of bodies with no collision geometry) use
    4 / 8, so they hit objects but not the floor or themselves.
- **Library versions are newer than older docs:**
  - MCP 2.x: `from mcp.server.mcpserver import MCPServer` (FastMCP was renamed).
  - MuJoCo 3.17: lights use `type=mjLIGHT_DIRECTIONAL`.
  - Rerun 0.42: `set_time(..., duration=)` and `Scalars.columns`.
  - MCP types are snake_case (`input_schema`, `is_error`, `server_info`).
  - NumPy 2.5 has no 2-D `np.cross`.
