---
title: World and task format
description: Every field of world and task files.
---

Worlds and tasks are YAML files. Built-in ones ship with the package; your own go in
`library/worlds/<name>.yaml` and `library/tasks/<name>.yaml`, and replace a built-in file of the
same name. Unknown fields are errors. See [Creating worlds and tasks](/RoboWorld/guides/worlds-and-tasks/) for
a walkthrough.

## World

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | The world's name |
| `description` | string | `""` | A description for people |
| `walls` | [walls](#walls) | none | A rectangular walled area |
| `objects` | list of [objects](#objects) | `[]` | Balls, boxes, cylinders and painted regions |
| `robot_start` | [robot start](#robot-start) | origin, facing +x | Where the robot starts |
| `bumps` | list of [bump patches](#bumps) | `[]` | Rough ground |

### Walls

| Field | Type | Default | Meaning |
|---|---|---|---|
| `half_size` | `[hx, hy]` | required | Half the size of the enclosed area, m |
| `height` | number | `0.25` | Wall height, m |
| `thickness` | number | `0.04` | Wall thickness, m |
| `color` | colour | `white` | |

The four walls are named `wall_east` (+x), `wall_west` (−x), `wall_north` (+y) and `wall_south`
(−y). Perception reports them as line segments.

### Objects

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Unique name; this is what brains and skills refer to |
| `shape` | `sphere`, `box`, `cylinder`, `region` | required | |
| `size` | list | required | `sphere`: `[r]`; `box`: `[hx, hy, hz]`; `cylinder`: `[r, half_height]`; `region`: `[hx, hy]` |
| `pos` | `[x, y]` or `[x, y, z]` | required | Position; with two values the object rests on the floor |
| `yaw` | number | `0` | Rotation about the vertical axis, degrees |
| `color` | colour | `gray` | |
| `mass` | number | `0.2` | kg |
| `movable` | boolean | `true` | `false` makes the object a fixed obstacle |
| `friction` | number | MuJoCo default | Sliding friction |
| `kind` | string | from the shape | The label brains see, such as `ball`, `box`, `goal` or `area` |
| `place_in` | `[[x_min, x_max], [y_min, y_max]]` | none | Random position per seed; overrides `pos` x and y |

A `region` is painted on the floor: it has no collision, and robots and objects move over it. The
default `kind` is `ball` for spheres, `box` for boxes, `cylinder` for cylinders and `area` for
regions.

**Colours** are one of `red`, `green`, `blue`, `yellow`, `orange`, `purple`, `white`, `black`,
`gray`, `brown`, `pink` and `cyan`, or an `[r, g, b, a]` list with values from 0 to 1.

### Robot start

| Field | Type | Default | Meaning |
|---|---|---|---|
| `pos` | `[x, y]` | `[0, 0]` | Starting position |
| `yaw_deg` | number | `0` | Starting heading, degrees |
| `yaw_range_deg` | `[min, max]` | none | Random heading per seed, drawn from this range in place of `yaw_deg` |

Randomly placed objects are kept apart from each other, from fixed objects and from the robot's
starting position.

### Bumps

| Field | Type | Default | Meaning |
|---|---|---|---|
| `area` | `[[x_min, x_max], [y_min, y_max]]` | required | Where the bumps go |
| `count` | 1–400 | `30` | Number of bumps |
| `height` | `[min, max]` | `[0.005, 0.015]` | Bump height range, m |
| `size` | `[min, max]` | `[0.03, 0.08]` | Bump size range, m |
| `color` | colour | `brown` | |

## Task

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | The task's name |
| `instruction` | string | required | What the brain is told to do |
| `world` | world name or inline world | required | Where the task takes place |
| `success` | [rule](#rules) | required | Ends the episode with success when it holds |
| `fail_if` | [rule](#rules) | none | Ends the episode with failure as soon as it holds |
| `time_limit_s` | number | `120` | Simulated seconds |
| `robots` | list of names | any robot that can walk | The robots the task is designed for |

### Rules

A rule has exactly one field:

| Rule | Holds when |
|---|---|
| `object_in_region: {object, region}` | The object's centre is inside the region's rectangle |
| `robot_in_region: <region>` | The robot's body centre is inside the region's rectangle |
| `robot_near: {object, distance}` | The robot's body centre is within `distance` m of the object's centre (default 0.5) |
| `answer: <string or list>` | The brain's `finish(answer=...)` matches one of the values; number words up to "twelve" match digits |
| `all: [rules]` | Every rule holds |
| `any: [rules]` | At least one rule holds |
| `sequence: [rules]` | The rules become true in this order; each step stays done once reached |

Rules are evaluated against the simulator's ground truth on every control tick.
