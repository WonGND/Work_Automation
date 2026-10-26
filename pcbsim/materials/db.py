"""YAML material database.

Temperature-dependent resistivity (linear model, IEC 60028)::

    ρ(T) = ρ₀ · (1 + α·(T − T_ref)),   σ(T) = 1 / ρ(T)

Thermal diffusivity (for transient thermal)::

    a = k / (ρ_m · c_p)

The bundled database lives in ``pcbsim/materials/data/default.yaml``; user files
and inline overrides are merged on top property-by-property.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields, replace
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from pcbsim.errors import MaterialError

_NUMERIC_FIELDS = (
    "sigma",
    "alpha_r",
    "t_ref",
    "eps_r",
    "tan_d",
    "k_inplane",
    "k_through",
    "density",
    "cp",
    "emissivity",
)


@dataclass(frozen=True, slots=True)
class Material:
    """Material properties in SI. ``None`` means 'not applicable / unknown'."""

    name: str
    description: str = ""
    sigma: float | None = None
    alpha_r: float = 0.0
    t_ref: float = 293.15
    eps_r: float | None = None
    tan_d: float | None = None
    k_inplane: float | None = None
    k_through: float | None = None
    density: float | None = None
    cp: float | None = None
    emissivity: float | None = None
    source: str = ""

    @property
    def is_conductor(self) -> bool:
        return self.sigma is not None and self.sigma > 0.0

    def resistivity(self, temperature: float | None = None) -> float:
        """ρ(T) = ρ₀·(1 + α·(T − T_ref)) in Ω·m. ``temperature`` in K."""
        if not self.is_conductor:
            raise MaterialError(f"material {self.name!r} has no electrical conductivity")
        assert self.sigma is not None
        rho0 = 1.0 / self.sigma
        if temperature is None:
            return rho0
        factor = 1.0 + self.alpha_r * (temperature - self.t_ref)
        if factor <= 0.0:
            raise MaterialError(
                f"material {self.name!r}: linear ρ(T) model invalid at T={temperature:.1f} K"
            )
        return rho0 * factor

    def conductivity(self, temperature: float | None = None) -> float:
        return 1.0 / self.resistivity(temperature)

    def diffusivity(self, direction: str = "inplane") -> float:
        """Thermal diffusivity a = k / (ρ_m·c_p) [m²/s]."""
        k = self.k_inplane if direction == "inplane" else self.k_through
        if k is None or self.density is None or self.cp is None:
            raise MaterialError(f"material {self.name!r} lacks thermal properties")
        return k / (self.density * self.cp)

    def require(self, *props: str) -> None:
        missing = [p for p in props if getattr(self, p) is None]
        if missing:
            raise MaterialError(f"material {self.name!r} is missing required properties {missing}")


def _validate(m: Material) -> Material:
    for f in _NUMERIC_FIELDS:
        v = getattr(m, f)
        if v is None:
            continue
        if not math.isfinite(v):
            raise MaterialError(f"material {m.name!r}: {f} must be finite")
        if f not in ("alpha_r",) and v < 0.0:
            raise MaterialError(f"material {m.name!r}: {f} must be >= 0 (got {v})")
    if m.emissivity is not None and m.emissivity > 1.0:
        raise MaterialError(f"material {m.name!r}: emissivity must be <= 1")
    if m.eps_r is not None and m.eps_r < 1.0:
        raise MaterialError(f"material {m.name!r}: eps_r must be >= 1")
    if m.k_inplane is not None and m.k_through is None:
        m = replace(m, k_through=m.k_inplane)
    if m.k_through is not None and m.k_inplane is None:
        m = replace(m, k_inplane=m.k_through)
    return m


_ALLOWED_KEYS = {f.name for f in fields(Material)} - {"name"} | {"k"}


def material_from_mapping(
    name: str, data: Mapping[str, Any], base: Material | None = None
) -> Material:
    """Build a :class:`Material`, optionally overriding ``base`` field-by-field.

    The shorthand ``k`` sets both ``k_inplane`` and ``k_through``.
    """
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise MaterialError(f"material {name!r}: unknown properties {sorted(unknown)}")
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key == "k":
            kwargs["k_inplane"] = kwargs["k_through"] = float(value)
        elif key in ("description", "source"):
            kwargs[key] = str(value)
        else:
            kwargs[key] = None if value is None else float(value)
    m = replace(base, name=name, **kwargs) if base is not None else Material(name=name, **kwargs)
    return _validate(m)


class MaterialDB(Mapping[str, Material]):
    """Immutable-ish name → :class:`Material` mapping with layered overrides."""

    def __init__(self, materials: Mapping[str, Material] | None = None) -> None:
        self._m: dict[str, Material] = dict(materials or {})

    def __getitem__(self, name: str) -> Material:
        try:
            return self._m[name]
        except KeyError:
            known = ", ".join(sorted(self._m))
            raise MaterialError(f"unknown material {name!r}; known: {known}") from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._m)

    def __len__(self) -> int:
        return len(self._m)

    @classmethod
    def default(cls) -> MaterialDB:
        text = resources.files("pcbsim.materials").joinpath("data/default.yaml").read_text("utf-8")
        return cls().merged(_parse_doc(yaml.safe_load(text), "default.yaml"))

    @classmethod
    def load(cls, *paths: str | Path, include_default: bool = True) -> MaterialDB:
        db = cls.default() if include_default else cls()
        for p in paths:
            path = Path(p)
            db = db.merged(_parse_doc(yaml.safe_load(path.read_text("utf-8")), str(path)))
        return db

    def merged(self, overrides: Mapping[str, Mapping[str, Any]]) -> MaterialDB:
        """Return a new DB with ``overrides`` applied (partial updates allowed)."""
        out = dict(self._m)
        for name, props in overrides.items():
            out[name] = material_from_mapping(name, props, base=out.get(name))
        return MaterialDB(out)


def _parse_doc(doc: Any, origin: str) -> dict[str, dict[str, Any]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("materials"), dict):
        raise MaterialError(f"{origin}: expected a mapping with a top-level 'materials:' key")
    out: dict[str, dict[str, Any]] = {}
    for name, props in doc["materials"].items():
        if not isinstance(props, dict):
            raise MaterialError(f"{origin}: materials.{name} must be a mapping")
        out[str(name)] = props
    return out
