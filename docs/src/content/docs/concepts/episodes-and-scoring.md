---
title: Episodes and scoring
description: The life of an episode, how it ends, and how success, progress and overclaiming are measured.
---

An **episode** is one attempt at one task: one robot, one task, one seed, one timing mode and one
brain. The brain acts one tool call at a time; the episode owns the simulation, perception, scoring
and recording.

## Life of an episode

1. **Set-up.** RoboWorld builds the world for the seed (random placements and starting heading),
   places the robot, lets it settle and starts the clock.
2. **Turns.** The brain calls tools. Each call that moves the robot runs until the skill or program
   finishes, or until the episode ends.
3. **End.** The episode ends as soon as one of the conditions below happens.
4. **Results.** `result.json` and `transcript.jsonl` are written, and the recording is closed.

## How an episode ends

| `ended_by` | Cause |
|---|---|
| `success` | The task's success rule held |
| `failed` | The task's `fail_if` rule held (for example, the robot touched a no-go zone) |
| `time_limit` | The simulated clock reached the task's time limit |
| `fell` | The robot fell over |
| `brain_finished` | The brain called `finish` before any of the above |
| `disconnected` | The brain disconnected without calling `finish` |

Success is checked continuously, so a brain doesn't need to notice that it succeeded; the episode
ends the moment the rule holds. For question tasks, the brain's answer is checked when it calls
`finish(answer=...)`.

## Timing

The episode clock is **simulated time**, so results don't depend on how fast the computer is.

- **Paused mode** stops the world while the brain thinks. It measures the quality of the brain's
  decisions.
- **Realtime mode** charges the brain for thinking. Before each tool call, the world advances by the
  wall-clock time since the previous call ended, with the robot holding still. Objects keep moving,
  and slow brains run out of time sooner.

Both modes record the brain's total and mean thinking time.

## Scoring

**Success** is judged by the simulator from ground truth. A brain's own claim never counts.

**Progress** gives partial credit from 0 to 1. For distance-based rules it is the share of the
starting distance that was closed; for a sequence it counts the completed steps; for `all` it
averages the parts, and for `any` it takes the best one.

**Overclaiming** is when a brain calls `finish(success=true)` and the simulator disagrees. The
benchmark reports the overclaim rate per brain, because a brain that says it succeeded when it
didn't can't be trusted to work unsupervised.

**Brain statistics** include tool calls, invalid calls (unknown tools, bad arguments or invalid
programs), the skills used and thinking time, plus anything the harness reports itself, such as
model calls, tokens and cost.

## Reproducibility

On the simulator's side, randomness comes only from the seed: object placement, starting heading
and perception noise. In paused mode, the same robot, task and seed with a deterministic brain (such
as the baseline) produce the same episode every time. LLM brains usually vary from run to run, which
is why benchmarks use several seeds. Re-run a surprising result with `rw episode --seed <n>` and
replay it with `rw view`.
