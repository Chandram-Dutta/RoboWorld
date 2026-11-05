"""World and task specs (YAML). Phase 3 extends these with terrain and randomisation."""

from __future__ import annotations

import difflib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from roboworld import paths

COLORS: dict[str, tuple[float, float, float, float]] = {
    "red": (0.86, 0.16, 0.16, 1), "green": (0.18, 0.7, 0.3, 1), "blue": (0.2, 0.4, 0.9, 1),
    "yellow": (0.95, 0.82, 0.15, 1), "orange": (0.95, 0.5, 0.1, 1), "purple": (0.55, 0.3, 0.8, 1),
    "white": (0.95, 0.95, 0.95, 1), "black": (0.1, 0.1, 0.1, 1), "gray": (0.55, 0.55, 0.58, 1),
    "brown": (0.55, 0.35, 0.2, 1), "pink": (0.95, 0.5, 0.7, 1), "cyan": (0.2, 0.8, 0.85, 1),
}

WORLD_DIR = paths.PACKAGE_DIR / "world" / "library"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorldObject(_Strict):
    name: str
    shape: Literal["sphere", "box", "cylinder", "region"]
    size: list[float] = Field(description="sphere [r]; box [hx, hy, hz]; cylinder [r, half_height]; region [hx, hy]")
    pos: list[float] = Field(min_length=2, max_length=3, description="[x, y] (rests on the floor) or [x, y, z]")
    yaw: float = 0.0
    color: str | list[float] = "gray"
    mass: float = 0.2
    movable: bool = True
    friction: float | None = None
    kind: str | None = Field(None, description="semantic label, e.g. ball, box, goal (default from shape)")
    place_in: list[list[float]] | None = Field(
        None, description="random placement per seed: [[x_min, x_max], [y_min, y_max]] (overrides pos x, y)")

    @model_validator(mode="after")
    def _check(self) -> WorldObject:
        need = {"sphere": 1, "box": 3, "cylinder": 2, "region": 2}[self.shape]
        if len(self.size) != need:
            raise ValueError(f"{self.shape} '{self.name}' needs {need} size values, got {len(self.size)}")
        if isinstance(self.color, str) and self.color not in COLORS:
            raise ValueError(f"unknown color '{self.color}'; use one of {sorted(COLORS)} or [r, g, b, a]")
        return self

    @property
    def rgba(self) -> tuple[float, ...]:
        return COLORS[self.color] if isinstance(self.color, str) else tuple(self.color)

    @property
    def label(self) -> str:
        return self.kind or {"sphere": "ball", "box": "box", "cylinder": "cylinder", "region": "area"}[self.shape]

    @property
    def color_name(self) -> str:
        return self.color if isinstance(self.color, str) else "custom"

    @property
    def half_height(self) -> float:
        return {"sphere": self.size[0], "box": self.size[-1], "cylinder": self.size[-1], "region": 0.0005}[self.shape]

    @property
    def radius_xy(self) -> float:
        """Rough footprint radius, for approach planning."""
        if self.shape in ("sphere", "cylinder"):
            return self.size[0]
        return float((self.size[0] ** 2 + self.size[1] ** 2) ** 0.5)


WALL_NAMES = ("wall_east", "wall_west", "wall_north", "wall_south")


class Walls(_Strict):
    half_size: list[float] = Field(min_length=2, max_length=2, description="[hx, hy] of the enclosed area")
    height: float = 0.25
    thickness: float = 0.04
    color: str = "white"

    def segments(self) -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
        """Inner face of each wall as a 2-D segment."""
        hx, hy = self.half_size
        return {
            "wall_east": ((hx, -hy), (hx, hy)), "wall_west": ((-hx, -hy), (-hx, hy)),
            "wall_north": ((-hx, hy), (hx, hy)), "wall_south": ((-hx, -hy), (hx, -hy)),
        }


class RobotStart(_Strict):
    pos: list[float] = Field(default_factory=lambda: [0.0, 0.0], min_length=2, max_length=2)
    yaw_deg: float = 0.0
    yaw_range_deg: list[float] | None = Field(None, min_length=2, max_length=2, description="random yaw per seed")


class Bumps(_Strict):
    """A patch of small fixed bumps on the floor (rough ground)."""

    area: list[list[float]] = Field(description="[[x_min, x_max], [y_min, y_max]]")
    count: int = Field(30, ge=1, le=400)
    height: list[float] = Field(default_factory=lambda: [0.005, 0.015], min_length=2, max_length=2)
    size: list[float] = Field(default_factory=lambda: [0.03, 0.08], min_length=2, max_length=2)
    color: str = "brown"


class WorldSpec(_Strict):
    name: str
    description: str = ""
    walls: Walls | None = None
    objects: list[WorldObject] = Field(default_factory=list)
    robot_start: RobotStart = Field(default_factory=RobotStart)
    bumps: list[Bumps] = Field(default_factory=list)
    seed: int | None = Field(None, description="set when random placements have been resolved")

    def resolved(self, seed: int) -> WorldSpec:
        """A concrete copy: random placements drawn for this seed, kept apart from each other and the robot."""
        rng = np.random.default_rng(seed)
        out = self.model_copy(deep=True)
        start = out.robot_start
        if start.yaw_range_deg:
            start.yaw_deg = float(rng.uniform(*start.yaw_range_deg))
        placed: list[tuple[np.ndarray, float]] = [(np.asarray(start.pos, dtype=float), 0.45)]
        placed += [(np.asarray(o.pos[:2], dtype=float), o.radius_xy) for o in out.objects if o.place_in is None]
        for obj in out.objects:
            if obj.place_in is None:
                continue
            (x0, x1), (y0, y1) = obj.place_in
            for _ in range(500):
                p = np.array([rng.uniform(x0, x1), rng.uniform(y0, y1)])
                if all(np.linalg.norm(p - q) > obj.radius_xy + r + 0.15 for q, r in placed):
                    break
            obj.pos = [float(p[0]), float(p[1])] + list(obj.pos[2:])
            placed.append((p, obj.radius_xy))
        out.seed = seed
        return out

    def object(self, name: str) -> WorldObject:
        for o in self.objects:
            if o.name == name:
                return o
        close = difflib.get_close_matches(name, [o.name for o in self.objects], n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise KeyError(f"No object '{name}' in world '{self.name}'.{hint}")


# --------------------------------------------------------------------- tasks
class Predicate(_Strict):
    """Task success check, evaluated by the simulator (never by the brain). Exactly one key."""

    object_in_region: dict[str, str] | None = Field(None, description="{object, region}")
    robot_in_region: str | None = None
    robot_near: dict[str, Any] | None = Field(None, description="{object, distance}")
    answer: str | list[str] | None = Field(None, description="the brain's finish(answer=...) must match one of these")
    all: list[Predicate] | None = None
    any: list[Predicate] | None = None
    sequence: list[Predicate] | None = Field(None, description="each must become true, in this order")

    @model_validator(mode="after")
    def _one(self) -> Predicate:
        keys = [k for k, v in self if v is not None]
        if len(keys) != 1:
            raise ValueError(f"a predicate needs exactly one key, got {keys or 'none'}")
        return self


class TaskSpec(_Strict):
    name: str
    instruction: str = Field(description="what the brain is told to do")
    world: str | WorldSpec
    success: Predicate
    fail_if: Predicate | None = Field(None, description="the episode fails as soon as this is true")
    time_limit_s: float = 120.0
    robots: list[str] | None = Field(None, description="robots this task is designed for (None = any mobile)")

    def resolved_world(self) -> WorldSpec:
        return self.world if isinstance(self.world, WorldSpec) else load_world(self.world)


Predicate.model_rebuild()


def _library(kind: str) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in (WORLD_DIR / kind, paths.LIBRARY_DIR / kind):
        if base.exists():
            for f in sorted(base.glob("*.yaml")):
                found[f.stem] = f
    return found


@lru_cache(maxsize=None)
def load_world(name: str) -> WorldSpec:
    lib = _library("worlds")
    if name not in lib:
        raise KeyError(f"Unknown world '{name}'. Known: {sorted(lib)}")
    return WorldSpec(**yaml.safe_load(lib[name].read_text()))


@lru_cache(maxsize=None)
def load_task(name: str) -> TaskSpec:
    lib = _library("tasks")
    if name not in lib:
        raise KeyError(f"Unknown task '{name}'. Known: {sorted(lib)}")
    return TaskSpec(**yaml.safe_load(lib[name].read_text()))


def list_tasks() -> list[TaskSpec]:
    return [load_task(n) for n in _library("tasks")]


def list_worlds() -> list[WorldSpec]:
    return [load_world(n) for n in _library("worlds")]
