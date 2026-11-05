"""Example custom harness: the baseline rules plus exploration and detours.

Plug it in without touching RoboWorld (see explorer.yaml):

    uv run rw bench --brains baseline,examples/harnesses/explorer.yaml --tasks all

A harness subclasses ``Harness`` and implements ``async run(robot, task)``.
``robot`` has typed helpers (look, observe, seen, do, run, finish) that talk to
the robot's MCP server. An LLM harness would call a model inside ``run``.
"""

from __future__ import annotations

import math
import re

from roboworld.brain.baseline import KeywordHarness, match
from roboworld.harness import Robot, TaskInfo


class ExplorerHarness(KeywordHarness):
    name = "example:explorer"
    lookouts = ((1.2, 1.2), (1.2, -1.2), (-1.2, 1.2), (-1.2, -1.2), (0.0, 1.5), (0.0, -1.5))

    async def pose(self, robot: Robot) -> tuple[float, float]:
        r = (await robot.observe()).get("robot", {})
        return r.get("x", 0.0), r.get("y", 0.0)

    async def find(self, robot: Robot, phrase: str) -> str | None:
        """Look for something matching phrase, walking to new lookout points if needed."""
        target = match(phrase, await robot.seen())
        x, y = await self.pose(robot)
        for lx, ly in sorted(self.lookouts, key=lambda p: math.dist(p, (x, y))):
            if target or robot.over:
                return target
            await robot.do("walk_to", target=[lx, ly])
            await robot.do("look_around")
            target = match(phrase, await robot.seen())
        return target

    async def goto(self, robot: Robot, target: str, avoid: dict | None) -> dict:
        seen = {o["name"]: o for o in await robot.seen()}
        x, y = await self.pose(robot)
        if avoid is not None:
            # Go round the no-go zone: a waypoint beside it, on the side closer to us.
            zx, zy = avoid["position"]
            hy = avoid.get("half_extent", [0.3, 0.3])[1]
            side = 1.0 if y >= zy else -1.0
            await robot.do("walk_to", target=[zx, zy + side * (hy + 0.45)])
        r = await robot.do("walk_to", target=target)
        if r.get("ok") or robot.over or "blocked" not in r.get("message", ""):
            return r
        # Blocked: try a detour on either side of the straight line, then go again.
        tx, ty = seen.get(target, {}).get("position", [x, y])
        mx, my, dx, dy = (x + tx) / 2, (y + ty) / 2, tx - x, ty - y
        norm = math.hypot(dx, dy) or 1.0
        for side in (1.0, -1.0):
            await robot.do("walk_to", target=[mx - side * dy / norm, my + side * dx / norm])
            r = await robot.do("walk_to", target=target)
            if r.get("ok") or robot.over:
                return r
        return r

    async def run(self, robot: Robot, task: TaskInfo) -> None:
        text = task.instruction.lower()
        if re.search(r"how many|push the", text):
            return await super().run(robot, task)
        await robot.do("look_around")
        avoid = next((o for o in await robot.seen() if "no-go" in o.get("kind", "")), None)
        ok, note = False, "nothing to do"
        for clause in re.split(r"\bthen\b", text):
            clause = re.sub(r"never .*", "", clause)
            target = await self.find(robot, clause)
            if target is None:
                ok, note = False, f"couldn't find anything matching '{clause.strip()}'"
                break
            r = await self.goto(robot, target, avoid)
            ok, note = bool(r.get("ok")), r.get("message", "")
            if not ok or robot.over:
                break
        await robot.finish(f"explorer: {note}", success=ok)
