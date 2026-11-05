---
title: Skills and perception
description: The closed-loop behaviours brains use, and the honest perception they rely on.
---

A brain mostly works with **skills**: closed-loop behaviours such as `walk_to`, `look_around` and
`push`. Skills only know what the robot has **perceived**, through a simulated camera and a
memory of everything it has seen.

## Skills

A skill is a behaviour that reacts to the world while it runs. `walk_to` steers towards its target
on every control tick; `push` walks behind an object, lines up, dribbles it towards the goal and
backs off to check where it ended up. Skills are built from the same gaits and poses as any
RoboLang program, so they obey the same safety layer.

Which skills a robot has depends on its body:

| Needs | Skills |
|---|---|
| Nothing | `stand` |
| A gait (the robot can walk) | `walk`, `strafe`, `turn`, `face`, `walk_to`, `push` |
| A camera | `look_around` |
| A camera, plus a head that can turn or the ability to walk | `look_at` |
| At least one saved motion | `play` |

Skills walk at 85% of the robot's tested speed limits. The [skills reference](/RoboWorld/reference/skills/)
lists every skill and its arguments.

### Results, not exceptions

Every skill returns a result with `ok`, a `message` and the robot's pose. When a skill can't do
what was asked, it says why in words a model can act on, for example:

- the target hasn't been seen yet, with a list of what has been seen,
- something is in the way (`walk_to` reports `blocked`),
- the object is pinned against a wall, so it can't be pushed from behind.

A brain should read the message and adapt: look around, choose another target, or approach from a
different point.

### What skills deliberately don't do

`walk_to` has no obstacle avoidance: if something is in the way it stops and reports it. Planning a
route around obstacles is the brain's job, and a good harness can do it with intermediate `[x, y]`
targets. `push` is the exception: it plans its own approach and detours around walls and obstacles
it has seen, because lining up behind an object is part of pushing it.

## Perception

The robot learns about the world through a simulated object detector attached to its camera. An
object is detected only when:

- it is inside the camera's field of view,
- it is within range (5 m by default), and
- it is not hidden behind something. RoboWorld casts rays to several points on each object, so a
  partly hidden object is still seen.

Position estimates carry noise that grows with distance (2% of the distance by default). Walls are
detected too and reported as line segments, so brains and skills can plan around them.

### Memory

Every detection is stored in the robot's **memory**, with the time it was last seen. `observe`
returns the memory sorted by distance, with each object's estimated position, distance and bearing
from where the robot is now, and whether it is visible right now. `look` returns the camera image
and the objects visible at that moment.

Skills resolve names against memory, so `walk_to red_ball` works only after the ball has been seen,
and a looser name such as `"red ball"` matches too.

### Why perception is honest

A brain that could read object positions from the simulator would score well without being able to
search, explore or recover from mistakes. In RoboWorld, ground truth is used only to **score** an
episode, never to inform the brain or the skills. A task like "find the red ball" therefore really
tests searching.
