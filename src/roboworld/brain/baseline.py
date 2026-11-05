"""A zero-cost baseline harness: simple rules, no LLM.

It reads the task instruction, looks around, maps phrases like "the green goal
area" onto objects it has seen, and calls skills. It's the floor every LLM
harness should beat, and a compact example of the Harness SDK.
"""

from __future__ import annotations

import re
from typing import Any

from roboworld.harness.core import Harness, Robot, TaskInfo

STOP = {"the", "a", "an", "to", "into", "in", "on", "of", "next", "it", "and", "then", "first", "only", "go",
        "stand", "find", "push", "painted", "floor", "area", "somewhere", "behind", "row", "is", "there", "your",
        "with", "within", "m", "body", "centre", "center", "near", "far", "side", "across", "without", "falling",
        "walk", "never", "step", "touching", "fails", "task", "you", "cannot", "through", "at", "least"}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", text.lower()) if t not in STOP}


def match(phrase: str, seen: list[dict[str, Any]]) -> str | None:
    """The seen object whose name/kind/colour best matches the phrase."""
    want = tokens(phrase)
    best, best_score = None, 0
    for o in seen:
        if o.get("kind") == "wall":
            continue
        have = tokens(f"{o['name'].replace('_', ' ')} {o.get('kind', '')} {o.get('color', '')}")
        score = len(want & have)
        if score > best_score:
            best, best_score = o["name"], score
    return best


class KeywordHarness(Harness):
    name = "baseline:keyword"

    def __init__(self, retries: int = 2, name: str | None = None):
        super().__init__()
        self.retries = retries
        if name:
            self.name = name

    async def run(self, robot: Robot, task: TaskInfo) -> None:
        text = task.instruction.lower()
        await robot.do("look_around")
        seen = await robot.seen()
        ok, note = False, "no rule matched the instruction"

        count = re.search(r"how many (\w+) (\w+?)s? ", text + " ")
        push = re.search(r"push the (.+?) (?:into|to|onto) the (.+?)(?:\.|$)", text)
        if count:
            colour, kind = count.group(1), count.group(2)
            n = sum(1 for o in seen if o.get("color") == colour and kind.startswith(o.get("kind", "")[:4]))
            await robot.finish(f"counted {n}", answer=str(n))
            return
        if push:
            obj, dest = match(push.group(1), seen), match(push.group(2), seen)
            if obj and dest:
                for _ in range(self.retries + 1):
                    r = await robot.do("push", object=obj, to=dest)
                    ok, note = bool(r.get("ok")), r.get("message", "")
                    if ok or robot.over:
                        break
                    await robot.do("look_around")
            else:
                note = "couldn't find the objects named in the task"
        else:  # "go next to X", "stand on Y", "first ... then ..."
            for clause in re.split(r"\bthen\b", text):
                target = match(clause, seen)
                if target is None:
                    ok, note = False, f"nothing seen matches '{clause.strip()}'"
                    break
                r = await robot.do("walk_to", target=target)
                ok, note = bool(r.get("ok")), r.get("message", "")
                if robot.over or not ok:
                    break
        if not robot.finished:
            await robot.finish(f"baseline: {note}", success=ok)
