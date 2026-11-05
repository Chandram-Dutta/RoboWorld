---
title: Development setup
description: Set up RoboWorld for development, run the tests and linter, and work on the documentation.
---

## Set up

Follow [Installation](/RoboWorld/start/installation/) to clone the repository, run `uv sync` and fetch the
three built-in robots. `uv sync` also installs the development tools (pytest).

Many tests drive the built-in robots, so fetch all three before running the test suite.

## Run the tests

```sh
uv run pytest -q
```

The suite takes a few seconds to a minute, depending on the machine. Run a single file or test while
you work:

```sh
uv run pytest -q tests/test_design.py
uv run pytest -q -k pushes_ball
```

Tests that start robot servers or run benchmarks write to temporary folders through
`ROBOWORLD_RUNS_DIR` and `ROBOWORLD_LIBRARY_DIR`, so they don't touch your `runs/` or `library/`.
Follow the same pattern in new tests: the `library` fixture in `tests/test_design.py` shows how.

## Run the linter

```sh
uvx ruff check src tests --select F,E9,B --ignore B008
```

## Check the benchmark

Changes to skills, perception, gaits or tasks can change how well every brain does. Compare the
baseline before and after your change:

```sh
uv run rw bench --robots go2,open_duck_mini_v2 --tasks all --brains baseline --seeds 2 --name before
# make your change
uv run rw bench --robots go2,open_duck_mini_v2 --tasks all --brains baseline --seeds 2 --name after
```

Because the baseline is deterministic, any difference comes from your change.

## Scripts that run many simulations

For tuning sweeps and experiments:

- Call `Simulation(...).run(program, save=False)` so the runs don't fill `runs/`.
- Use a process pool for parallel work. On macOS and Windows, worker processes are started fresh,
  so put the script's entry point under `if __name__ == "__main__":` and run it from a file rather
  than from standard input.

## Work on the documentation

The documentation is an [Astro Starlight](https://starlight.astro.build) site in `docs/`. It needs
Node.js.

```sh
cd docs
npm install
npm run dev       # live preview at http://localhost:4321/RoboWorld/
npm run build     # production build; fails on broken internal links
```

Pages are Markdown or MDX files in `docs/src/content/docs/`. The sidebar is defined in
`docs/astro.config.mjs`; add new pages there.

When you document a command or field, check it against the code or run it: the documentation should
show real output.
