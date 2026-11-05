"""Brain specs: how a brain (harness + model) is named and built.

A brain is either
- an in-process harness: a ``Brain`` subclass whose ``run`` drives the robot's MCP
  session (built-ins, or yours via ``type: python``), or
- an external agent command (Codex, Claude Code, anything that speaks MCP).

Spec sources, by name:
    baseline                 built-in rule-based harness (no LLM, free)
    codex | claude-code      agent CLI presets
    path/to/brain.yaml       a spec file
    <name>                   library/brains/<name>.yaml

Spec file examples::

    name: qwen-local
    type: openai
    base_url: http://localhost:11434/v1
    model: qwen3:4b

    name: my-harness
    type: python
    entry: my_package.harness:MyHarness      # or path/to/file.py:MyHarness
    params: {model: qwen3:4b, memory: true}

    name: gemini-cli
    type: command
    command: "gemini -p {prompt} ..."          # {prompt} {mcp_config} {codex_flags} {run_dir}
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from roboworld import paths
from roboworld.brain.baseline import KeywordBrain
from roboworld.brain.brains import Brain, OpenAICompatBrain, ScriptedBrain
from roboworld.brain.runner import PRESETS


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


def from_spec(spec: dict[str, Any]) -> Brain | CommandBrain:
    kind = spec.get("type")
    name = spec.get("name") or kind or "brain"
    params = dict(spec.get("params") or {})
    if kind == "baseline":
        return KeywordBrain(name=name, **params)
    if kind == "scripted":
        b = ScriptedBrain.from_file(spec["script"])
        b.name = name
        return b
    if kind == "openai":
        key_env = spec.get("api_key_env")
        return OpenAICompatBrain(name=name, base_url=spec.get("base_url", "http://localhost:11434/v1"),
                                 model=spec["model"], api_key=os.environ.get(key_env) if key_env else None,
                                 vision=spec.get("vision", True), temperature=spec.get("temperature", 0.2))
    if kind == "python":
        cls = _load_entry(spec["entry"])
        brain = cls(**params)
        if not hasattr(brain, "run"):
            raise TypeError(f"{spec['entry']} has no async run(session, instructions, prompt, tools, max_turns)")
        brain.name = name if spec.get("name") else getattr(brain, "name", name)
        if not hasattr(brain, "stats"):
            brain.stats = {}
        if not hasattr(brain, "log"):
            brain.log = []
        return brain
    if kind == "command":
        return CommandBrain(name=name, command=PRESETS.get(spec["command"], spec["command"]))
    raise ValueError(f"unknown brain type '{kind}' (baseline | scripted | openai | python | command)")


def library_specs() -> dict[str, Path]:
    found = {}
    for base in (paths.PACKAGE_DIR / "brain" / "library", paths.LIBRARY_DIR / "brains"):
        if base.exists():
            for f in sorted(base.glob("*.yaml")):
                found[f.stem] = f
    return found


def resolve(ref: str) -> Brain | CommandBrain:
    if ref == "baseline":
        return KeywordBrain()
    if ref in PRESETS:
        return CommandBrain(name=ref, command=PRESETS[ref])
    path = Path(ref)
    if path.suffix in (".yaml", ".yml") and path.exists():
        return from_spec(yaml.safe_load(path.read_text()))
    lib = library_specs()
    if ref in lib:
        return from_spec(yaml.safe_load(lib[ref].read_text()))
    known = ["baseline", *PRESETS, *lib]
    raise KeyError(f"unknown brain '{ref}'. Known: {known} (or a path to a brain .yaml)")


def list_brains() -> list[dict[str, str]]:
    out = [{"name": "baseline", "type": "baseline", "about": "rule-based harness, no LLM (free)"}]
    out += [{"name": k, "type": "command", "about": v} for k, v in PRESETS.items()]
    for name, f in library_specs().items():
        spec = yaml.safe_load(f.read_text()) or {}
        out.append({"name": name, "type": spec.get("type", "?"), "about": str(f)})
    return out
