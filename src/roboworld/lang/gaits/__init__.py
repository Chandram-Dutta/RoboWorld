"""Gait library: name -> controller. Gaits share one interface: a velocity
command (vx, vy, wz) plus style knobs. A trained RL policy can later register
under the same names (``stabilizer: policy``) without changing any program."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from roboworld.lang import schema
from roboworld.lang.gaits.base import GaitController
from roboworld.lang.gaits.biped import BipedWalk
from roboworld.lang.gaits.periodic import PATTERNS, PeriodicGait
from roboworld.lang.manifest import Manifest

if TYPE_CHECKING:
    from roboworld.lang.interpreter import Ctx

GaitFactory = Callable[["Ctx", schema.Gait], GaitController]

GAITS: dict[str, tuple[tuple[str, ...], GaitFactory]] = {
    "biped_walk": (BipedWalk.kinds, lambda ctx, spec: BipedWalk(ctx, spec)),
}
for _name in PATTERNS:
    GAITS[_name] = (("quadruped",), lambda ctx, spec, n=_name: PeriodicGait(ctx, spec, n))


def available_gaits(manifest: Manifest) -> list[str]:
    names = [n for n, (kinds, _) in GAITS.items() if manifest.kind in kinds]
    return sorted(set(names) | {n for n in manifest.gaits if n in GAITS})


def make_gait(ctx: Ctx, spec: schema.Gait) -> GaitController:
    if spec.type not in GAITS:
        raise KeyError(f"Unknown gait '{spec.type}'. Known gaits: {sorted(GAITS)}")
    return GAITS[spec.type][1](ctx, spec)
