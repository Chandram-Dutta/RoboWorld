"""A zero-cost baseline harness: simple rules, no LLM.

It reads the task instruction, looks around, maps phrases like "the green goal
area" onto objects it has seen, and calls skills. It's the floor every LLM
harness should beat, and a small example of writing your own harness: subclass
``Brain`` and implement ``run``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from roboworld.brain.brains import Brain, call_tool

STOP = {"the", "a", "an", "to", "into", "in", "on", "of", "next", "it", "and", "then", "first", "only", "go",
        "stand", "find", "push", "painted", "floor", "area", "somewhere", "behind", "row", "is", "there", "your",
        "with", "within", "m", "body", "centre", "center", "near", "far", "side", "across", "without", "falling",
        "walk", "never", "step", "touching", "fails", "task", "you", "cannot", "through", "at", "least"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", text.lower()) if t not in STOP}


@dataclass
class KeywordBrain(Brain):
    name: str = "baseline:keyword"
    retries: int = 2

    async def _json(self, session, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        out = await call_tool(session, tool, args)
        self.log.append({"tool": tool, "args": args, "result": out.text[:300]})
        try:
            return json.loads(out.text) if out.text.startswith("{") else {"text": out.text}
        except json.JSONDecodeError:
            return {"text": out.text}

    async def _seen(self, session) -> list[dict[str, Any]]:
        return (await self._json(session, "observe", {})).get("objects_seen", [])

    def _match(self, phrase: str, seen: list[dict[str, Any]]) -> str | None:
        """The seen object whose name/kind/colour best matches the phrase."""
        want = _tokens(phrase)
        best, best_score = None, 0
        for o in seen:
            if o.get("kind") == "wall":
                continue
            have = _tokens(f"{o['name'].replace('_', ' ')} {o.get('kind', '')} {o.get('color', '')}")
            score = len(want & have)
            if score > best_score:
                best, best_score = o["name"], score
        return best

    async def _do(self, session, skill: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._json(session, "do", {"skill": skill, "args": args})

    async def run(self, session, instructions, prompt, tools, max_turns) -> None:
        task = prompt.split("Task:", 1)[-1].split("You have", 1)[0].strip()
        await self._do(session, "look_around", {})
        seen = await self._seen(session)
        text = task.lower()
        ok, note = False, "no rule matched the instruction"

        count = re.search(r"how many (\w+) (\w+?)s? ", text + " ")
        push = re.search(r"push the (.+?) (?:into|to|onto) the (.+?)(?:\.|$)", text)
        if count:
            colour, kind = count.group(1), count.group(2)
            n = sum(1 for o in seen if o.get("color") == colour and kind.startswith(o.get("kind", "")[:4]))
            await self._json(session, "finish", {"summary": f"counted {n}", "answer": str(n)})
            return
        if push:
            obj, dest = self._match(push.group(1), seen), self._match(push.group(2), seen)
            if obj and dest:
                for _ in range(self.retries + 1):
                    r = await self._do(session, "push", {"object": obj, "to": dest})
                    ok, note = bool(r.get("ok")), r.get("message", "")
                    if ok or r.get("episode", {}).get("over"):
                        break
                    await self._do(session, "look_around", {})
            else:
                note = "couldn't find the objects named in the task"
        else:
            # "go next to X", "stand on Y", "first ... then ..."
            clauses = re.split(r"\bthen\b", text)
            for clause in clauses:
                target = self._match(clause, seen)
                if target is None:
                    note = f"nothing seen matches '{clause.strip()}'"
                    ok = False
                    break
                r = await self._do(session, "walk_to", {"target": target})
                ok, note = bool(r.get("ok")), r.get("message", "")
                if r.get("episode", {}).get("over") or not ok:
                    break
        await self._json(session, "finish", {"summary": f"baseline: {note}", "success": ok})
