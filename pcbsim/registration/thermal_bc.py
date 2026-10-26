"""Thermal boundary conditions derived from registered mechanical items.

Everything here is in the board frame (after registration) and SI.

Heat sink — given thermal resistance
    ``R_sa`` [K/W] from the layer map. Attached to a component (rule
    ``component:`` or footprint overlap) it becomes that component's
    case-to-ambient path (needs the JEDEC two-resistor model, ``theta_jb``);
    otherwise a ``convection`` boundary on the board face under the heat sink
    footprint with ``h = 1 / (R_sa · A_base)``.

Heat sink — plate-fin geometry [Incropera §3.6.4–3.6.5]
    Straight rectangular fins, adiabatic tip with corrected length
    ``L_c = H + t/2``::

        m      = √(2 h / (k t))                (fin parameter, w ≫ t)
        η_f    = tanh(m L_c) / (m L_c)         (single-fin efficiency)
        A_f    = 2 · L_c · ℓ                   (one fin, both faces; ℓ = fin length)
        A_b    = A_base − N · t · ℓ            (exposed base)
        A_t    = N · A_f + A_b
        η_o    = 1 − N A_f / A_t · (1 − η_f)   (overall surface efficiency)
        R_sa   = 1 / (η_o · h · A_t)

    ``ℓ`` defaults to the footprint extent along the fins (the longer side of
    the minimum rotated rectangle).

Chassis contact
    Ideal contact → ``fixed_temperature`` boundary at the chassis temperature.
    With a contact resistance ``R_c`` [K/W] for the whole contact patch, or a
    contact conductance ``h_c`` [W/(m²K)], the patch is a ``convection``
    boundary to the chassis temperature with ``h = 1/(R_c · A)`` or ``h_c``:
    a series resistance to a fixed temperature is exactly a Robin condition.

Case air gap
    Where a case surface lies at height ``g`` above the board face, still air
    conducts ``h_gap = k_air / g`` towards the case temperature (pure
    conduction; conservative when the gap is small enough that the Rayleigh
    number is below the onset of convection, Ra < 1708 [Incropera §9.8]).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from pcbsim.io.cad import PlacedComponent
from pcbsim.registration.features import MechBody
from pcbsim.registration.layermap import FinSpec, HeatsinkRule, LayerMap


@dataclass(frozen=True, slots=True)
class MechBoundary:
    """A thermal boundary in board coordinates, convertible to the config schema."""

    name: str
    kind: str  # convection | fixed_temperature
    side: str
    polygon: list[tuple[float, float]] | None
    component: str | None = None
    h: float | None = None
    resistance: float | None = None
    temperature: float | None = None  # K
    ambient: float | None = None  # K
    note: str = ""

    def to_config(self, offset: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
        """``thermal_boundaries`` entry (lengths as ``"<v> mm"`` strings, temps in K)."""
        d: dict[str, Any] = {"name": self.name, "kind": self.kind}
        if self.component is not None:
            d["component"] = self.component
        else:
            d["side"] = self.side
            assert self.polygon is not None
            d["polygon"] = [
                [f"{(x + offset[0]) * 1e3:.6f} mm", f"{(y + offset[1]) * 1e3:.6f} mm"]
                for x, y in self.polygon
            ]
        if self.h is not None:
            d["h"] = self.h
        if self.resistance is not None:
            d["resistance"] = self.resistance
        if self.temperature is not None:
            d["temperature"] = f"{self.temperature} K"
        if self.ambient is not None:
            d["ambient"] = f"{self.ambient} K"
        return d

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "side": self.side,
            "polygon_m": self.polygon,
            "component": self.component,
            "h": self.h,
            "resistance": self.resistance,
            "temperature_K": self.temperature,
            "ambient_K": self.ambient,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MechBoundary:
        poly = d.get("polygon_m")
        return cls(
            name=str(d["name"]),
            kind=str(d["kind"]),
            side=str(d.get("side", "top")),
            polygon=[(float(p[0]), float(p[1])) for p in poly] if poly else None,
            component=d.get("component"),
            h=d.get("h"),
            resistance=d.get("resistance"),
            temperature=d.get("temperature_K"),
            ambient=d.get("ambient_K"),
            note=str(d.get("note", "")),
        )


def fin_efficiency(h: float, k: float, t: float, height: float) -> float:
    """``η_f = tanh(m L_c)/(m L_c)``, ``L_c = H + t/2``, ``m = √(2h/(k t))``."""
    lc = height + t / 2.0
    m = math.sqrt(2.0 * h / (k * t))
    ml = m * lc
    return math.tanh(ml) / ml if ml > 0 else 1.0


def finned_resistance(base_area: float, fins: FinSpec, length: float, h: float, k: float) -> float:
    """Sink-to-ambient resistance of a straight plate-fin array (see module docstring)."""
    lc = fins.height + fins.thickness / 2.0
    a_f = 2.0 * lc * length
    a_b = max(base_area - fins.count * fins.thickness * length, 0.0)
    a_t = fins.count * a_f + a_b
    eta_f = fin_efficiency(h, k, fins.thickness, fins.height)
    eta_o = 1.0 - fins.count * a_f / a_t * (1.0 - eta_f)
    return 1.0 / (eta_o * h * a_t)


def _long_side(geom: BaseGeometry) -> float:
    rect = geom.minimum_rotated_rectangle
    if not isinstance(rect, Polygon):
        return 0.0
    c = list(rect.exterior.coords)
    return max(math.dist(c[0], c[1]), math.dist(c[1], c[2]))


def _ring(geom: BaseGeometry) -> list[tuple[float, float]]:
    poly = geom if isinstance(geom, Polygon) else geom.convex_hull
    if not isinstance(poly, Polygon):
        poly = geom.buffer(1e-4)
    assert isinstance(poly, Polygon)
    return [(float(x), float(y)) for x, y in list(poly.exterior.coords)[:-1]]


def _clip(geom: BaseGeometry, outline: Polygon | None) -> BaseGeometry | None:
    if outline is None:
        return geom
    g = geom.intersection(outline)
    return None if g.is_empty or g.area <= 0 else g


def heatsink_resistance(body: MechBody, rule: HeatsinkRule) -> tuple[float, str]:
    if rule.resistance is not None:
        return rule.resistance, f"R_sa = {rule.resistance:g} K/W (layer map)"
    area = float(body.geometry.area)
    if rule.fins is not None:
        length = rule.fins.length or _long_side(body.geometry)
        r = finned_resistance(area, rule.fins, length, rule.h, rule.k)
        eta = fin_efficiency(rule.h, rule.k, rule.fins.thickness, rule.fins.height)
        return r, (
            f"{rule.fins.count} fins H={rule.fins.height * 1e3:g} mm, η_f={eta:.3f}, "
            f"h={rule.h:g} W/m²K → R_sa={r:.3g} K/W"
        )
    r = 1.0 / (rule.h * area)
    return r, f"flat plate, h={rule.h:g} W/m²K → R_sa={r:.3g} K/W"


def derive_boundaries(
    bodies: list[MechBody],
    comps: list[PlacedComponent],
    lmap: LayerMap,
    outline: Polygon | None,
    comp_footprints: dict[str, BaseGeometry] | None = None,
) -> tuple[list[MechBoundary], list[str]]:
    """Heat sinks, chassis contacts and case gaps → thermal boundaries (board frame)."""
    out: list[MechBoundary] = []
    notes: list[str] = []
    fps = comp_footprints or {}
    names: set[str] = set()

    def uniq(base: str) -> str:
        n, k = base, 2
        while n in names:
            n, k = f"{base}_{k}", k + 1
        names.add(n)
        return n

    for b in bodies:
        if b.role != "heatsink":
            continue
        rule = lmap.heatsink_rule(b.layer)
        r, how = heatsink_resistance(b, rule)
        comp = rule.component
        if comp is None:
            for ref, fp in fps.items():
                if fp.intersects(b.geometry) and fp.intersection(b.geometry).area > 0:
                    comp = ref
                    break
        if comp is None:
            for c in comps:
                if b.geometry.contains(_pt(c.x, c.y)):
                    comp = c.ref
                    break
        if comp is not None:
            out.append(
                MechBoundary(
                    uniq(f"hs_{comp}"),
                    "convection",
                    "top",
                    None,
                    component=comp,
                    resistance=r,
                    ambient=rule.ambient,
                    note=f"heat sink {b.layer} on {comp}: {how}",
                )
            )
        else:
            g = _clip(b.geometry, outline)
            if g is None:
                notes.append(f"heat sink {b.layer} lies outside the board; ignored")
                continue
            out.append(
                MechBoundary(
                    uniq(f"hs_{b.layer}"),
                    "convection",
                    "top",
                    _ring(g),
                    h=1.0 / (r * float(g.area)),
                    ambient=rule.ambient,
                    note=f"heat sink {b.layer} on board face: {how}",
                )
            )

    if lmap.chassis is not None:
        ch = lmap.chassis
        for b in bodies:
            if b.role != "chassis":
                continue
            g = _clip(b.geometry, outline)
            if g is None:
                notes.append(f"chassis contact {b.layer} does not overlap the board; ignored")
                continue
            area = float(g.area)
            name = uniq(f"chassis_{b.layer}")
            if ch.contact_resistance is None and ch.h_contact is None:
                out.append(
                    MechBoundary(
                        name,
                        "fixed_temperature",
                        ch.side,
                        _ring(g),
                        temperature=ch.temperature,
                        note="ideal chassis contact",
                    )
                )
            else:
                h = (
                    ch.h_contact
                    if ch.h_contact is not None
                    else 1.0 / (float(ch.contact_resistance or 0.0) * area)
                )
                out.append(
                    MechBoundary(
                        name,
                        "convection",
                        ch.side,
                        _ring(g),
                        h=h,
                        ambient=ch.temperature,
                        note=f"chassis contact, h_c = {h:.4g} W/m²K",
                    )
                )

    if lmap.case is not None:
        cs = lmap.case
        for b in bodies:
            if b.role != "case" or b.z_base <= 0:
                continue
            g = _clip(b.geometry, outline)
            if g is None:
                continue
            h = cs.k_air / b.z_base
            out.append(
                MechBoundary(
                    uniq(f"case_{b.layer}"),
                    "convection",
                    cs.side,
                    _ring(g),
                    h=h,
                    ambient=cs.temperature,
                    note=f"air gap {b.z_base * 1e3:.2f} mm to case: h = k_air/g = {h:.3g} W/m²K",
                )
            )
    return out, notes


def _pt(x: float, y: float) -> BaseGeometry:
    from shapely.geometry import Point

    return Point(x, y)
