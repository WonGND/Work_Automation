"""Layer stack-up.

Layers are ordered **top to bottom**. The z coordinate of a layer is the
distance from the top surface of the board to the *top face* of the layer
(z grows downward), i.e. ``z_top(i) = Σ_{j<i} t_j``.

The DC sheet resistance of a conductor layer is ``R_s = ρ / t = 1 / (σ·t)`` [Ω/□]
— used by :mod:`pcbsim.solvers.dc_ir`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LayerKind(StrEnum):
    CONDUCTOR = "conductor"
    DIELECTRIC = "dielectric"
    SOLDERMASK = "soldermask"


class LayerRole(StrEnum):
    SIGNAL = "signal"
    PLANE = "plane"
    MIXED = "mixed"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Layer:
    """One physical layer. ``thickness`` in metres; ``material`` is a DB key."""

    name: str
    kind: LayerKind
    thickness: float
    material: str
    role: LayerRole = LayerRole.NONE

    @property
    def is_conductor(self) -> bool:
        return self.kind is LayerKind.CONDUCTOR


@dataclass(frozen=True, slots=True)
class Stackup:
    layers: tuple[Layer, ...]

    def __post_init__(self) -> None:
        names = [layer.name for layer in self.layers]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"duplicate layer names in stack-up: {sorted(dup)}")

    @property
    def total_thickness(self) -> float:
        return sum(layer.thickness for layer in self.layers)

    def conductor_layers(self) -> tuple[Layer, ...]:
        return tuple(layer for layer in self.layers if layer.is_conductor)

    def names(self) -> tuple[str, ...]:
        return tuple(layer.name for layer in self.layers)

    def index(self, name: str) -> int:
        for i, layer in enumerate(self.layers):
            if layer.name == name:
                return i
        raise KeyError(f"layer {name!r} not in stack-up")

    def get(self, name: str) -> Layer:
        return self.layers[self.index(name)]

    def z_top(self, name: str) -> float:
        i = self.index(name)
        return sum(layer.thickness for layer in self.layers[:i])

    def z_bottom(self, name: str) -> float:
        return self.z_top(name) + self.get(name).thickness

    def z_center(self, name: str) -> float:
        return self.z_top(name) + 0.5 * self.get(name).thickness

    def layers_between(self, upper: str, lower: str) -> tuple[Layer, ...]:
        """Layers strictly between two layers (e.g. dielectrics between copper)."""
        a, b = sorted((self.index(upper), self.index(lower)))
        return self.layers[a + 1 : b]

    def span(self, upper: str, lower: str) -> float:
        """Centre-to-centre distance between two layers (via barrel length estimate)."""
        return abs(self.z_center(lower) - self.z_center(upper))
