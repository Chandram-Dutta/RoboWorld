---
title: Skills reference
description: Every skill, its arguments, and when a robot has it.
---

Skills are closed-loop behaviours. A brain runs them with `do(skill, args)` on the robot server, and
a program runs them with a `skill` step. Every skill returns:

```json
{"ok": true, "message": "...", "robot": {"x": 0.42, "y": -0.1, "heading_deg": 12, "tilt_deg": 2.1, "fallen": false}}
```

When `ok` is `false`, `message` explains why. Targets that name an object must refer to something
the robot has already seen; a target can also be a point `[x, y]` in world metres.

## Movement

### `stand`

Stops and returns to the default standing pose. No arguments. Available on every robot.

### `walk`

Walks straight forward, or backward with a negative distance, holding the current heading.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `distance` | −5 to 5 | yes | Metres; negative walks backward |
| `speed` | number > 0 | no | m/s; defaults to the robot's comfortable speed |

### `strafe`

Steps sideways without turning.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `distance` | −3 to 3 | yes | Metres; positive is to the robot's left |

### `turn`

Turns on the spot.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `degrees` | −720 to 720 | yes | Positive turns left (counter-clockwise) |

### `face`

Turns on the spot to face a seen object or a point.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `target` | object name or `[x, y]` | yes | What to face |

### `walk_to`

Walks to a seen object or a point, steering as it goes. It stops next to solid objects and walks
onto painted areas. It has no obstacle avoidance: if something is in the way it reports `blocked`,
and the brain can route around it with intermediate `[x, y]` points.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `target` | object name or `[x, y]` | yes | Where to go |
| `stop_distance` | number > 0 | no | Stop this far from the target's centre, m |
| `speed` | number > 0 | no | m/s |

## Perception

### `look_around`

Scans the surroundings with a head sweep, by turning on the spot, or both, and reports everything
seen. Use it to search. No arguments.

### `look_at`

Points the head (or the whole body, if the robot has no head) at a seen object or a point.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `target` | object name or `[x, y]` | yes | What to look at |

## Manipulation

### `push`

Pushes a seen object to a seen area or a point. It walks around behind the object, lines up and
dribbles it along. It plans around walls and obstacles it has seen, using a detour point if the
object is close to a wall, and backs off to find the object again if it loses track. If the object
is pinned against a wall, it reports that instead of trying.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `object` | object name | yes | The object to push |
| `to` | area or object name, or `[x, y]` | yes | Where to push it |
| `speed` | number > 0 | no | m/s |

## Motions

### `play`

Plays a saved RoboLang motion, such as a wave or a dance.

| Argument | Type | Required | Meaning |
|---|---|---|---|
| `motion` | string | yes | The name of a saved motion |

Motions are saved with the builder server's `save_motion` tool, or as files in
`library/motions/<robot>/`. The `skills` tool on the robot server lists a robot's saved motions.

## Availability

| Skill | Available when |
|---|---|
| `stand` | Always |
| `walk`, `strafe`, `turn`, `face`, `walk_to`, `push` | The robot has a gait for its kind |
| `look_around` | The robot has a camera |
| `look_at` | The robot has a camera and either a head yaw joint or a gait |
| `play` | The robot has at least one saved motion |

Movement skills use the robot's default gait at 85% of its tested speed limits, unless a `speed`
argument says otherwise.
