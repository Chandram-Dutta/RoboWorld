---
title: Running benchmarks
description: Compare brains and robots across tasks and seeds with rw bench, and read the report.
---

`rw bench` runs every combination of robots × brains × tasks × seeds and writes a comparison
report. Because every brain gets the same robots, tasks and seeds, differences in the results come
from the brains (or, if you vary the robots, from the bodies).

## Run a benchmark

```sh
uv run rw tasks     # the tasks you can use
uv run rw brains    # the brains you can use
uv run rw bench --robots go2,open_duck_mini_v2 --tasks all \
    --brains baseline,harnesses/my_harness.yaml,codex --seeds 3
```

| Option | Default | Meaning |
|---|---|---|
| `--robots` | `go2,open_duck_mini_v2` | Comma-separated robots |
| `--tasks` | `all` | Comma-separated tasks, or `all` |
| `--brains` | `baseline` | Comma-separated brains: names, presets or spec files |
| `--seeds` | `2` | Random placements per task |
| `--mode` | `paused` | `paused` or `realtime` |
| `--jobs` | `3` | Episodes run in parallel |
| `--max-turns` | `40` | Turn limit for in-process brains |
| `--record` | off | Keep Rerun recordings (roughly 5–15 MB per episode) |
| `--name` | | A label added to the benchmark folder's name |

In-process brains (the baseline and Python harnesses) run `--jobs` episodes at a time. Agent CLIs
such as `codex` and `claude-code` run one episode at a time.

Robots are only paired with tasks they can do. A task can name the robots it is designed for;
otherwise it needs a robot that can walk, so a fixed arm is skipped for navigation tasks.

## Seeds

A seed fixes the random placement of objects (and, in some worlds, the robot's starting heading).
Seed `0` with the same task always produces the same layout, so a result can be reproduced with
`rw episode --seed <n>`. More seeds give a more reliable comparison.

## Read the report

The command prints one line per episode as it goes, then a leaderboard:

```text
  ✓ baseline:keyword         go2                find_red_ball                s0 success
  ✓ baseline:keyword         go2                push_ball_to_goal            s0 success

baseline:keyword             success 4/4 (100%)  progress 100%  overclaim 0.0

report: runs/20261105-181453-bench/report.html
```

`report.html` has three parts:

1. **A leaderboard** of brains with these columns:

   | Column | Meaning |
   |---|---|
   | Success | Episodes that met the task's success rule |
   | Progress | Mean progress towards the goal, from 0 to 1 (partial credit) |
   | Time to success | Mean simulated seconds of the successful episodes |
   | Tool calls | Mean tool calls per episode |
   | Invalid calls | Tool calls with bad arguments or unknown names |
   | Overclaim rate | Share of claimed successes that the simulator didn't confirm |
   | Tokens, cost | Per episode, when the harness reports them; cost is also shown per success |
   | Errors | Episodes that crashed instead of finishing |

2. **A task-by-robot grid** of success rates for each brain.
3. **Every episode**, with its result, progress, time, tool calls and run ID.

`results.csv` has one row per episode and `summary.json` has the aggregated numbers, for your own
analysis. Each episode's folder in `episodes/` holds its `result.json` and transcript.

## Make comparisons fair

- Compare brains on the **same seeds**. `rw bench` does this for you.
- Use **paused** mode to compare reasoning, and **realtime** mode when speed matters too.
- Include the **baseline**. It costs nothing to run and shows how much of a task the skills solve
  on their own.
- Look at the **overclaim rate** as well as success: a brain that claims success it didn't reach
  is less useful than its success rate suggests.

To compare robot *bodies* under one brain instead, use
[`rw design compare`](/RoboWorld/guides/designing-robots/#compare-designs).
