"""Brain specs: how a brain is named and plugged in.

RoboWorld doesn't ship LLM harnesses. A brain is either
- **your harness**: a ``roboworld.harness.Harness`` subclass (or any class with
  ``async run(...)``), loaded from a file, a module or an installed entry point
- **an external agent** that speaks MCP itself (Codex, Claude Code, ...)
- a test helper: the rule-based ``baseline`` or a ``scripted`` list of tool calls

Spec sources, by name:
    baseline                 built-in rule-based reference floor (no LLM, free)
    codex | claude-code      agent CLI presets
    path/to/brain.yaml       a spec file
    <name>                   library/brains/<name>.yaml, or an installed entry point

Spec files::

    name: my-harness
    type: harness
    harness: path/to/my_harness.py:MyHarness     # or package.module:MyHarness, or an entry point name
    params: {model: my-model, max_turns: 30}      # passed to your class's constructor

    name: gemini-cli
    type: command
    command: "gemini -p {prompt} ..."              # {prompt} {mcp_config} {codex_flags} {run_dir}
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from roboworld import paths
from roboworld.brain.baseline import KeywordHarness
from roboworld.brain.brains import Brain, ScriptedBrain
from roboworld.brain.runner import PRESETS
from roboworld.harness import Harness, HarnessBrain

ENTRY_POINT_GROUP = "roboworld.harnesses"


@dataclass
class CommandBrain:
    """An external agent CLI; it starts the robot server itself from a generated MCP config."""

    name: str
    command: str


def _load_entry(entry: str) -> type:
    target, _, attr = entry.rpartition(":")
    if not target or not attr:
        raise ValueError(f"entry must look like 'package.module:Class' or 'path/file.py:Class', got '{entry}'")
    if target.endswith(".py"):
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = paths.HOME / path
        mod_name = f"roboworld_user_{path.stem}"
        mod_spec = importlib.util.spec_from_file_location(mod_name, path)
        if mod_spec is None or mod_spec.loader is None:
            raise ImportError(f"can't load {path}")
        module = importlib.util.module_from_spec(mod_spec)
        sys.modules[mod_name] = module  # dataclasses and pickling look the module up by name
        mod_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    return getattr(module, attr)


def entry_points() -> dict[str, Any]:
    """Harnesses installed by Python packages under the ``roboworld.harnesses`` entry-point group."""
    from importlib.metadata import entry_points as eps

    return {ep.name: ep for ep in eps(group=ENTRY_POINT_GROUP)}


def harness_class(ref: str) -> type:
    """An installed entry point name, or 'path/file.py:Class' / 'package.module:Class'."""
    installed = entry_points()
    if ref in installed:
        return installed[ref].load()
    return _load_entry(ref)


def as_brain(obj: Any, name: str | None) -> Brain:
    """Wrap a Harness (run(robot, task)) or accept an old-style brain (run(session, ...))."""
    if isinstance(obj, Harness):
        if name:
            obj.name = name
        return HarnessBrain(harness=obj, name=obj.name)
    if not hasattr(obj, "run"):
        raise TypeError(f"{type(obj).__name__} has no async run(robot, task)")
    obj.name = name or getattr(obj, "name", type(obj).__name__)
    for attr, default in (("stats", {}), ("log", [])):
        if not hasattr(obj, attr):
            setattr(obj, attr, default)
    return obj


def from_spec(spec: dict[str, Any]) -> Brain | CommandBrain:
    kind = spec.get("type")
    name = spec.get("name")
    params = dict(spec.get("params") or {})
    if kind == "baseline":
        return as_brain(KeywordHarness(**params), name)
    if kind == "scripted":
        b = ScriptedBrain.from_file(spec["script"])
        b.name = name or b.name
        return b
    if kind == "harness":
        return as_brain(harness_class(spec["harness"])(**params), name)
    if kind == "python":
        return as_brain(_load_entry(spec["entry"])(**params), name)
    if kind == "command":
        return CommandBrain(name=name or "command", command=PRESETS.get(spec["command"], spec["command"]))
    raise ValueError(f"unknown brain type '{kind}' (harness | command | scripted | baseline | python)")


def library_specs() -> dict[str, Path]:
    found = {}
    for base in (paths.PACKAGE_DIR / "brain" / "library", paths.LIBRARY_DIR / "brains"):
        if base.exists():
            for f in sorted(base.glob("*.yaml")):
                found[f.stem] = f
    return found


def resolve(ref: str) -> Brain | CommandBrain:
    if ref == "baseline":
        return as_brain(KeywordHarness(), None)
    if ref in PRESETS:
        return CommandBrain(name=ref, command=PRESETS[ref])
    path = Path(ref)
    if path.suffix in (".yaml", ".yml") and path.exists():
        return from_spec(yaml.safe_load(path.read_text()))
    lib = library_specs()
    if ref in lib:
        return from_spec(yaml.safe_load(lib[ref].read_text()))
    installed = entry_points()
    if ref in installed:  # an installed harness that needs no model/params
        return as_brain(installed[ref].load()(), ref)
    known = ["baseline", *PRESETS, *lib, *installed]
    raise KeyError(f"unknown brain '{ref}'. Known: {known} (or a path to a brain .yaml)")


def list_brains() -> list[dict[str, str]]:
    out = [{"name": "baseline", "type": "baseline", "about": "rule-based harness, no LLM (free)"}]
    out += [{"name": k, "type": "command", "about": v} for k, v in PRESETS.items()]
    for name, f in library_specs().items():
        spec = yaml.safe_load(f.read_text()) or {}
        out.append({"name": name, "type": spec.get("type", "?"), "about": str(f)})
    for name, ep in entry_points().items():
        out.append({"name": name, "type": "installed", "about": ep.value})
    return out
