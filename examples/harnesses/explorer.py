"""Example custom harness: the baseline rules plus exploration and detours.

Plug it in without touching RoboWorld (see explorer.yaml):

    uv run rw bench --brains baseline,examples/harnesses/explorer.yaml --tasks all

A harness is any class with ``async run(session, instructions, prompt, tools, max_turns)``
that drives the robot's MCP session. Subclassing a built-in (here the keyword baseline)
is the quickest start. An LLM harness would call a model inside ``run``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from roboworld.brain.baseline import KeywordBrain


@dataclass
class ExplorerBrain(KeywordBrain):
    name: str = "example:explorer"
    lookouts: tuple = ((1.2, 1.2), (1.2, -1.2), (-1.2, 1.2), (-1.2, -1.2), (0.0, 1.5), (0.0, -1.5))

    async def _pose(self, session) -> tuple[float, float]:
        r = (await self._json(session, "observe", {})).get("robot", {})
        return r.get("x", 0.0), r.get("y", 0.0)

    async def _find(self, session, phrase: str) -> str | None:
        """Look for something matching phrase, walking to new lookout points if needed."""
        seen = await self._seen(session)
        target = self._match(phrase, seen)
        x, y = await self._pose(session)
        for lx, ly in sorted(self.lookouts, key=lambda p: math.dist(p, (x, y))):
            if target:
                return target
            r = await self._do(session, "walk_to", {"target": [lx, ly]})
            if r.get("episode", {}).get("over"):
                return None
            await self._do(session, "look_around", {})
            target = self._match(phrase, await self._seen(session))
        return target

    async def _goto(self, session, target: str, avoid: dict | None) -> dict:
        seen = {o["name"]: o for o in await self._seen(session)}
        x, y = await self._pose(session)
        if avoid is not None and target in seen:
            # Go round the no-go zone: a waypoint beside it, on the side closer to us.
            zx, zy = avoid["position"]
            hx, hy = avoid.get("half_extent", [0.3, 0.3])
            side = 1.0 if y >= zy else -1.0
            await self._do(session, "walk_to", {"target": [zx, zy + side * (hy + 0.45)]})
        r = await self._do(session, "walk_to", {"target": target})
        if r.get("ok") or r.get("episode", {}).get("over") or "blocked" not in r.get("message", ""):
            return r
        # Blocked: try a detour on either side of the straight line, then go again.
        tx, ty = seen.get(target, {}).get("position", [x, y])
        mx, my, dx, dy = (x + tx) / 2, (y + ty) / 2, tx - x, ty - y
        norm = math.hypot(dx, dy) or 1.0
        for side in (1.0, -1.0):
            wp = [mx - side * dy / norm * 1.0, my + side * dx / norm * 1.0]
            await self._do(session, "walk_to", {"target": wp})
            r = await self._do(session, "walk_to", {"target": target})
            if r.get("ok") or r.get("episode", {}).get("over"):
                return r
        return r

    async def run(self, session, instructions, prompt, tools, max_turns) -> None:
        task = prompt.split("Task:", 1)[-1].split("You have", 1)[0].strip().lower()
        if re.search(r"how many|push the", task):
            return await super().run(session, instructions, prompt, tools, max_turns)
        await self._do(session, "look_around", {})
        seen = await self._seen(session)
        avoid = next((o for o in seen if "no-go" in o.get("kind", "")), None)
        ok, note = False, "nothing to do"
        for clause in re.split(r"\bthen\b", task):
            clause = re.sub(r"never .*", "", clause)
            target = await self._find(session, clause)
            if target is None:
                ok, note = False, f"couldn't find anything matching '{clause.strip()}'"
                break
            r = await self._goto(session, target, avoid)
            ok, note = bool(r.get("ok")), r.get("message", "")
            if not ok or r.get("episode", {}).get("over"):
                break
        await self._json(session, "finish", {"summary": f"explorer: {note}", "success": ok})
