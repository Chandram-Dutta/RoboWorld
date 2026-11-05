---
title: Extending RoboWorld
description: How to add a skill, a gait, a task, a built-in robot, a design template or a servo.
---

This page shows where each kind of extension goes and what it must do. Read the
[conventions](/RoboWorld/contributing/conventions/) first.

## Add a skill

Skills live in `src/roboworld/lang/skills.py`. A skill has an argument model, a registration and a
class.

```python
class CircleArgs(_Args):
    target: Target = Field(description="an object you have seen or [x, y]")
    radius: float = Field(0.5, gt=0.1, le=2.0, description="metres")


@skill("circle", "Walk once around a seen object or point.", CircleArgs, can_move)
class Circle(MovingSkill):
    name = "circle"

    def setup(self, ctx: Ctx) -> None:
        self.centre, _ = self.locate(ctx, self.args.target)  # raises LookupError if never seen
        self.turned = 0.0

    def control(self, ctx: Ctx):
        ...
        if done:
            return True, "walked around it", {}           # finish: (ok, message, extra data)
        return vx, vy, heading                            # keep going: a velocity and a heading
```

- **Arguments** are a Pydantic model with bounds and descriptions. They become the schema brains see
  in `skills()`, so describe units and signs.
- **`@skill(name, description, args, applies)`** registers the skill. `applies` takes the robot's
  manifest and decides whether the robot has the skill (`can_move`, `has_camera`, or your own test).
- **`MovingSkill`** drives the robot's default gait. `setup` runs once; `control` runs every tick and
  returns either `(vx, vy, heading)` to keep moving or `(ok, message, data)` to finish. It gives up
  after `timeout` seconds.
- **Use perception only.** Find objects with `self.locate(ctx, target)` or `self.sense(ctx).memory`.
  A `LookupError` raised in `setup` or `control` becomes a failure with its message.
- For skills that don't walk, subclass `Skill`, implement `start` and `tick`, and call
  `self.report(ctx, ok, message)` and `self.finish(ctx)` when done.

Add a test in `tests/test_brain.py`, update the [skills reference](/RoboWorld/reference/skills/), and compare
the baseline benchmark before and after.

## Add a gait

Gaits live in `src/roboworld/lang/gaits/`.

**A new periodic pattern** for multi-legged robots only needs phase offsets per foot in `PATTERNS`
in `periodic.py`. Add it to `PATTERN_KINDS` if it isn't for quadrupeds:

```python
PATTERNS["hexapod_wave"] = {"L3": 0.0, "L2": 1/6, "L1": 2/6, "R3": 3/6, "R2": 4/6, "R1": 5/6}
PATTERN_KINDS["hexapod_wave"] = ("hexapod",)
```

**A new gait controller** subclasses `GaitController` from `base.py`:

| Member | Purpose |
|---|---|
| `name`, `kinds` | The gait's name and the robot kinds it supports |
| `fallback` | Default settings: `period`, `step_height`, `duty_factor`, `double_support`, `body_height`, `stabilizer`, `params` |
| `start(ctx)` | Called once; read `self.settings` and the robot's stance |
| `tick(ctx)` | Called at the control rate; write joint targets with `ctx.targets[self.claims] = ...` |
| `stop_requested`, `done` | When a stop is requested, finish the current step, settle, then set `done = True` |

Use `heading_correction` to hold or steer the heading, and `ctx.kin` for inverse kinematics in the
base frame. Register the controller in the `GAITS` table in `gaits/__init__.py`, and add a test in
`tests/test_sim.py` that the gait walks forward and turns without falling.

## Add a task or world

Built-in worlds and tasks are YAML files in `src/roboworld/world/library/worlds/` and
`src/roboworld/world/library/tasks/`; the format is in the
[world and task format reference](/RoboWorld/reference/worlds-and-tasks/). A new built-in task should:

- test an ability the existing tasks don't,
- use `place_in` so seeds vary the layout,
- be solvable by at least one built-in robot with the skills alone (check with the baseline or a
  scripted brain over several seeds).

`tests/test_bench.py` checks that every task loads; add a test for any new kind of success rule.

## Add a built-in robot

1. Add an entry in `src/roboworld/robots/manifests/<name>.yaml` with a `git` source: the repository,
   a **pinned commit**, the `subdir` and the `include` list for the sparse clone.
2. Fill in the manifest as described in [Adding your own robot](/RoboWorld/guides/adding-a-robot/), including
   tuned gait settings and tested speed limits.
3. Run `rw design check <name>` and the benchmark with the baseline, and add the robot to the tests
   that run every robot.
4. Note the model's source and licence in the entry's header comment and in
   [Built-in robots, worlds and tasks](/RoboWorld/reference/built-in/).

Only add models from repositories with a clear licence, and never commit the model files.

## Add a design template

Templates are robot design specs in `src/roboworld/design/templates/<name>.yaml`, with a
`description` that says what the robot is. `tests/test_design.py` compiles every template and
requires it to pass the static checks; make sure it also passes `rw design check` (stands, walks and
turns).

## Add a servo

Add an entry to `src/roboworld/design/servos.yaml` with `torque_nm`, `speed_rad_s`, `kp`, `damping`,
`armature`, `frictionloss`, `mass_kg` and a `note`. Use the manufacturer's stall torque and no-load
speed at the voltage you state in the note.
