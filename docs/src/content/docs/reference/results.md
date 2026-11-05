---
title: Results and metrics
description: The fields of run results, episode results and benchmark outputs, and what every metric means.
---

## Metrics

Program runs and episodes both report these metrics, measured over the whole run.

| Metric | Unit | Meaning |
|---|---|---|
| `duration_s` | s | Simulated time |
| `fell` | | Whether the robot fell |
| `fall_time_s` | s | When it fell, or `null` |
| `forward_m` | m | Displacement along the starting heading |
| `lateral_drift_m` | m | Displacement to the left of the starting heading |
| `displacement_m` | m | Straight-line distance from the start |
| `distance_traveled_m` | m | Length of the path the body followed |
| `avg_speed_mps` | m/s | Displacement divided by duration |
| `heading_change_deg` | ° | Change in heading, positive to the left |
| `final_position` | m | Final `[x, y]` |
| `max_tilt_deg`, `mean_tilt_deg` | ° | Largest and average tilt of the body from upright |
| `min_base_height_m` | m | Lowest height of the body |
| `peak_torque_ratio` | | Highest joint torque as a fraction of its limit; above 0.9 the servos are struggling |
| `torque_saturation_pct` | % | Share of joint samples at 95% of the torque limit or more |
| `mean_servo_load` | | Average joint torque as a fraction of its limit |
| `energy_j` | J | Mechanical work done by the joints |
| `cost_of_transport` | | Energy per weight per distance, `energy / (m·g·d)`; `null` for distances under 5 cm |
| `tracking_rmse_rad` | rad | Root-mean-square gap between joint targets and measured angles |
| `joint_limit_hits` | | Joint samples at the end of their range |

## Program run result

`rw run` and the builder server's `simulate` return, and save as `result.json`:

| Field | Meaning |
|---|---|
| `run_id` | The run's ID and folder name in `runs/` |
| `robot` | The robot |
| `status` | `completed`, `fell`, `timeout` or `invalid` |
| `program_name` | The program's `name`, if it had one |
| `metrics` | See [Metrics](#metrics) |
| `events` | The event log: `{t, kind, text}` for steps starting and ending, conditions, gait starts, falls |
| `recording` | Path of the Rerun recording |

When a program is `invalid`, nothing runs: the result has only `status` and `validation`, which
holds the errors and warnings.

## Episode result

Each episode saves `result.json`:

| Field | Meaning |
|---|---|
| `run_id`, `robot`, `task`, `instruction`, `mode`, `seed`, `brain` | What was run |
| `status` | `success`, or the reason the episode ended |
| `success` | Whether the task succeeded, judged by the simulator |
| `success_time_s` | Simulated time of success, or `null` |
| `ended_by` | `success`, `failed`, `time_limit`, `fell`, `brain_finished` or `disconnected` |
| `progress` | Progress towards the goal, 0 to 1 |
| `sim_time_s`, `wall_time_s` | Simulated and real duration |
| `brain_stats` | See below |
| `metrics` | See [Metrics](#metrics) |
| `recording`, `view_with` | The recording's path and the command that replays it |

`brain_stats` contains:

| Field | Meaning |
|---|---|
| `tool_calls` | Number of tool calls |
| `invalid_calls` | Calls with unknown tools, bad arguments or invalid programs |
| `skills_used` | How many times each skill was called |
| `think_time_s`, `mean_think_s` | Total and mean time between tool calls |
| `summary` | The brain's `finish` summary |
| `claimed_success` | What the brain claimed in `finish` |
| `overclaimed` | The brain claimed success but the task didn't succeed |
| `answer` | The brain's answer, for question tasks |
| `llm` | Statistics reported by the harness (its `stats`) |

`transcript.jsonl` has one line per tool call: the call index, tool, arguments, `ok`, simulated and
wall-clock times, and the result.

## Benchmark outputs

A benchmark folder contains:

| File | Contents |
|---|---|
| `report.html` | Leaderboard, task-by-robot success grid, and every episode |
| `results.csv` | One row per episode: robot, task, brain, seed, status, success, times, progress, tool calls, invalid calls, claims, tokens, cost, model calls, run ID and any error |
| `summary.json` | The settings used (robots, tasks, brains, seeds, mode), aggregates per brain (`by_brain`) and per brain, robot and task (`cells`), and the `leaderboard` order |
| `episodes/` | One folder per episode, named `<robot>-<task>-<brain>-s<seed>` |

Each aggregate has:

| Field | Meaning |
|---|---|
| `episodes`, `successes`, `success_rate` | Counts and rate |
| `mean_progress` | Mean progress, 0 to 1 |
| `mean_success_time_s` | Mean time of the successful episodes |
| `mean_tool_calls` | Mean tool calls per episode |
| `invalid_calls` | Total invalid calls |
| `overclaim_rate` | Share of success claims that were wrong |
| `cost_per_success_usd` | Total reported cost divided by successes, when the harness reports cost |
