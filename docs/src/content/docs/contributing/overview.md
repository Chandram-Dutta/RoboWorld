---
title: Contributing to RoboWorld
description: Ways to contribute, the principles RoboWorld follows, and how to get a change merged.
---

Contributions of all sizes are welcome: bug reports, new tasks and worlds, robots, skills, gaits,
design templates and documentation.

## Ways to contribute

- **Report a bug.** Include the command you ran, the robot, the task and the seed, and attach the
  run's `result.json` (and `transcript.jsonl` for episodes). With the seed, most problems can be
  reproduced exactly.
- **Add a task or world.** New tasks that test a distinct ability (memory, tool use, cooperation
  between skills) make the benchmark more useful. See
  [Creating worlds and tasks](/RoboWorld/guides/worlds-and-tasks/).
- **Add a robot.** A built-in robot needs a model with a clear licence that can be fetched from a
  public repository at a pinned commit.
- **Improve skills, perception or gaits.** These are the platform's core; changes must be checked
  against the benchmark (see below).
- **Improve the documentation.** Every page has an "Edit page" link at the bottom.

## Principles

Keep these in mind when proposing a change. They are what make RoboWorld's measurements meaningful.

1. **RoboWorld is a platform, not a harness.** It provides robots, worlds, interfaces and
   measurements. It doesn't ship or tune LLM harnesses or model clients. When a brain does badly,
   improve the platform side (skills, perception, tasks, metrics), not a particular brain.
2. **Perception is honest.** Skills and brains may only use what the robot has perceived. Ground
   truth is for scoring only.
3. **Programs speak joint position targets.** Nothing bypasses the interpreter's safety layer.
4. **Failures are reported, not raised.** A skill that can't do something returns `ok: false` with
   a reason a model can act on.
5. **Results are reproducible.** The same robot, task, seed and deterministic brain give the same
   episode. Avoid anything that depends on timing, object identity or unordered iteration.
6. **Robot models are fetched, not vendored.** Never commit third-party model files.

## Making a change

1. **Discuss larger changes first** in an issue, so the design can be agreed before you write it.
2. **Create a branch** from `main`.
3. **Set up** your environment: [Development setup](/RoboWorld/contributing/development/).
4. **Write the change and its tests.** New behaviour needs a test; a bug fix needs a test that
   failed before the fix.
5. **Run the tests and the linter.** Both must pass.
6. **Check the benchmark** if you changed skills, perception, gaits or tasks: run
   `rw bench --brains baseline` on the Go2 and the Open Duck before and after, and include both
   results in the pull request.
7. **Update the documentation** for any user-visible change, in `docs/`.
8. **Open a pull request** that explains what changed and why, how you tested it, and the benchmark
   comparison where relevant.

## Next steps

- [Development setup](/RoboWorld/contributing/development/)
- [Project structure](/RoboWorld/contributing/project-structure/)
- [Conventions](/RoboWorld/contributing/conventions/)
- [Extending RoboWorld](/RoboWorld/contributing/extending/)
