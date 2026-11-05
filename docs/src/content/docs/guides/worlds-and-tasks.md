---
title: Creating worlds and tasks
description: Describe rooms, objects and terrain in YAML, and turn them into scored tasks.
---

A **world** is a place: walls, objects, painted areas and rough ground. A **task** puts an
instruction and a success rule on top of a world. Both are YAML files.

Put your own files in `library/worlds/` and `library/tasks/`. A file with the same name as a
built-in one replaces it.

## Write a world

```yaml title="library/worlds/fetch_room.yaml"
name: fetch_room
description: >-
  A 4 x 4 m walled room with a red ball, a blue crate and a green goal area.
  The robot starts in the middle facing +x.
walls: {half_size: [2.0, 2.0], height: 0.25}
robot_start: {pos: [0.0, 0.0], yaw_deg: 0, yaw_range_deg: [-30, 30]}
objects:
  - {name: red_ball, shape: sphere, size: [0.1], pos: [0.9, 0.4],
     place_in: [[0.5, 1.2], [-0.8, 0.8]], color: red, mass: 0.2}
  - {name: blue_crate, shape: box, size: [0.12, 0.12, 0.1], pos: [-0.6, -1.1],
     color: blue, mass: 2.0, movable: false}
  - {name: green_goal, shape: region, size: [0.3, 0.3], pos: [1.5, -0.9],
     color: green, kind: goal}
```

The coordinates are world metres: `x` is forward from the robot's start, `y` is to its left, and
`z` is up. The world's centre is `[0, 0]`.

### Objects

| Shape | `size` | Notes |
|---|---|---|
| `sphere` | `[radius]` | Rolls when pushed |
| `box` | `[hx, hy, hz]` (half sizes) | Slides when pushed |
| `cylinder` | `[radius, half_height]` | |
| `region` | `[hx, hy]` (half sizes) | A painted area on the floor; robots and objects pass over it |

Objects rest on the floor unless `pos` gives a height. Set `movable: false` for fixed obstacles,
and `kind` to give an object a meaning the brain sees (such as `goal` or `area`). Colours are
named (`red`, `green`, `blue`, `yellow`, `orange`, `purple`, `white`, `black`, `gray`, `brown`,
`pink`, `cyan`) or given as `[r, g, b, a]`.

### Random placement

`place_in: [[x_min, x_max], [y_min, y_max]]` places an object at random inside a rectangle, and
`yaw_range_deg` turns the robot's starting heading at random. The seed of the episode picks the
values, so the same seed always gives the same layout.

### Rough ground

`bumps` scatters small fixed bumps over an area:

```yaml
bumps:
  - {area: [[-0.6, 0.9], [-1.8, 1.8]], count: 140, height: [0.005, 0.015], size: [0.03, 0.08]}
```

## Write a task

```yaml title="library/tasks/fetch_ball_to_goal.yaml"
name: fetch_ball_to_goal
instruction: Push the red ball into the green goal area painted on the floor.
world: fetch_room
success: {object_in_region: {object: red_ball, region: green_goal}}
time_limit_s: 180
```

| Field | Meaning |
|---|---|
| `instruction` | What the brain is told to do |
| `world` | A world name, or a whole world written inline |
| `success` | The rule that ends the episode with success |
| `fail_if` | Optional rule that ends the episode with failure as soon as it holds |
| `time_limit_s` | Simulated seconds before the episode ends (default 120) |
| `robots` | Optional list of the robots the task is designed for |

### Success rules

| Rule | Holds when |
|---|---|
| `object_in_region: {object, region}` | The object's centre is inside the region |
| `robot_in_region: <region>` | The robot's body centre is inside the region |
| `robot_near: {object, distance}` | The robot's body centre is within `distance` metres of the object (default 0.5) |
| `answer: <text or list>` | The brain's `finish(answer=...)` matches one of the values (number words like "three" count as digits) |
| `all: [...]` | Every rule holds |
| `any: [...]` | At least one rule holds |
| `sequence: [...]` | The rules become true in this order |

For example, a two-step errand:

```yaml
success:
  sequence:
    - {robot_near: {object: blue_crate, distance: 0.6}}
    - {robot_near: {object: red_ball, distance: 0.6}}
```

And a constraint that fails the episode:

```yaml
success: {robot_in_region: green_area}
fail_if: {robot_in_region: red_zone}
```

### Partial credit

Each episode also reports **progress** from 0 to 1, which shows how close an unsuccessful brain
got. For distance-based rules it is the share of the starting distance that was closed; for
`sequence` it counts the completed steps. See [Episodes and scoring](/RoboWorld/concepts/episodes-and-scoring/).

## Try it

```sh
uv run rw tasks
uv run rw episode --robot go2 --task fetch_ball_to_goal --brain baseline --seed 0
uv run rw view latest
```

Run a few seeds with the baseline to check that the task is possible and that random placements
don't produce impossible layouts. Then add it to your benchmarks.

The [world and task format reference](/RoboWorld/reference/worlds-and-tasks/) lists every field.
