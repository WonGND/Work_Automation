"""Board-level data model: nets, copper shapes, vias, components, ports, criteria.

Everything is SI: metres, kelvin, volts, amperes, watts.

Via barrel DC resistance (used later by :mod:`pcbsim.solvers.dc_ir`)::

    R_via = ρ · L / A,   A = π/4 · (d² − (d − 2·t_p)²)

where ``d`` is the finished hole (drill) diameter and ``t_p`` the plating
thickness. Filled vias add the filler in parallel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from pcbsim.errors import ModelError
from pcbsim.model.geometry import Polygon
from pcbsim.model.stackup import Stackup
from pcbsim.units import celsius_to_kelvin


class NetKind(StrEnum):
    POWER = "power"
    GROUND = "ground"
    SIGNAL = "signal"


class PortKind(StrEnum):
    VOLTAGE_SOURCE = "voltage_source"
    CURRENT_SINK = "current_sink"


class Side(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"


@dataclass(frozen=True, slots=True)
class Net:
    name: str
    kind: NetKind = NetKind.SIGNAL
    nominal_voltage: float | None = None


@dataclass(frozen=True, slots=True)
class Shape:
    """A copper region (trace, pad or plane) on one conductor layer."""

    net: str
    layer: str
    polygon: Polygon
    name: str = ""


@dataclass(frozen=True, slots=True)
class Via:
    x: float
    y: float
    drill: float
    from_layer: str
    to_layer: str
    net: str
    plating_thickness: float = 25e-6
    material: str = "copper"
    filled: bool = False
    filler: str | None = None

    @property
    def barrel_area(self) -> float:
        """Annular cross-section of the plated barrel ``π/4·(d² − (d−2t)²)``."""
        d = self.drill
        di = max(d - 2.0 * self.plating_thickness, 0.0)
        return math.pi / 4.0 * (d * d - di * di)

    @property
    def fill_area(self) -> float:
        di = max(self.drill - 2.0 * self.plating_thickness, 0.0)
        return math.pi / 4.0 * di * di if self.filled else 0.0


@dataclass(frozen=True, slots=True)
class Component:
    """A heat-dissipating / load component. ``power`` in W, temperatures in K."""

    ref: str
    footprint: Polygon
    side: Side = Side.TOP
    power: float = 0.0
    tj_max: float | None = None
    theta_jc: float | None = None
    theta_jb: float | None = None

    def effective_tj_max(self, default: float) -> float:
        return self.tj_max if self.tj_max is not None else default


class SinkDistribution(StrEnum):
    """How a current sink spreads its current over the port region.

    * ``uniform`` — equal current per unit area (one current source per pin).
    * ``equipotential`` — the region is an ideal conductor (pins shorted by the die).
    """

    UNIFORM = "uniform"
    EQUIPOTENTIAL = "equipotential"


@dataclass(frozen=True, slots=True)
class Port:
    """Electrical boundary condition: VRM (voltage source) or load (current sink).

    Voltage sources are always equipotential over their region. ``reference_net``
    names the return net; the return terminal sits on ``reference_layer`` or, if
    omitted, on the conductor layer nearest to ``layer`` that carries
    reference-net copper under the region.
    """

    name: str
    kind: PortKind
    net: str
    layer: str
    region: Polygon
    value: float
    reference_net: str | None = None
    reference_layer: str | None = None
    distribution: SinkDistribution = SinkDistribution.UNIFORM


class CurrentDensityMethod(StrEnum):
    IPC2152 = "ipc2152"
    IPC2221 = "ipc2221"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Criteria:
    """Pass/fail thresholds. Temperatures in K, current density in A/m², width in m."""

    ir_drop_pct: float = 3.0
    tj_max_default: float = celsius_to_kelvin(105.0)
    current_density: CurrentDensityMethod = CurrentDensityMethod.IPC2152
    current_density_temp_rise: float = 10.0
    current_density_limit: float | None = None
    current_density_ref_width: float = 1e-3
    z0_tol_pct: float = 10.0


class ThermalBoundaryKind(StrEnum):
    FIXED_TEMPERATURE = "fixed_temperature"
    CONVECTION = "convection"


@dataclass(frozen=True, slots=True)
class ThermalBoundary:
    """Extra thermal boundary condition on one board face (SI: K, W/(m²·K), K/W).

    * ``fixed_temperature`` — ideal clamp: the outer conductor-sheet cells under
      ``region`` are held at ``temperature`` (chassis contact, cold plate).
    * ``convection`` — replaces the default face h under ``region`` by ``h`` (or by
      ``1/(resistance·A)``) towards ``ambient`` (heat sink, fan-cooled zone). If
      ``component`` is set, it is the case-to-ambient path of that component
      instead (a heat sink on the package top).
    """

    name: str
    kind: ThermalBoundaryKind
    side: Side
    region: Polygon
    temperature: float | None = None
    h: float | None = None
    resistance: float | None = None
    ambient: float | None = None
    component: str | None = None


@dataclass(frozen=True, slots=True)
class Board:
    name: str
    outline: Polygon
    stackup: Stackup
    nets: tuple[Net, ...] = ()
    shapes: tuple[Shape, ...] = ()
    vias: tuple[Via, ...] = ()
    components: tuple[Component, ...] = ()
    ports: tuple[Port, ...] = ()
    criteria: Criteria = field(default_factory=Criteria)
    thermal_boundaries: tuple[ThermalBoundary, ...] = ()

    def net(self, name: str) -> Net:
        for n in self.nets:
            if n.name == name:
                return n
        raise KeyError(f"net {name!r} not defined")

    def net_names(self) -> set[str]:
        return {n.name for n in self.nets}

    def shapes_on(self, layer: str, net: str | None = None) -> tuple[Shape, ...]:
        return tuple(s for s in self.shapes if s.layer == layer and (net is None or s.net == net))

    @property
    def total_power(self) -> float:
        return sum(c.power for c in self.components)

    def validate(self) -> None:
        """Check referential integrity; raise :class:`ModelError` listing all problems."""
        problems: list[str] = []
        layer_names = set(self.stackup.names())
        conductor_names = {layer.name for layer in self.stackup.conductor_layers()}
        net_names = self.net_names()

        if not self.stackup.conductor_layers():
            problems.append("stack-up has no conductor layers")
        for layer in self.stackup.layers:
            if layer.thickness <= 0.0:
                problems.append(f"layer {layer.name!r}: thickness must be > 0")
        if self.outline.area() <= 0.0:
            problems.append("board outline has zero area")
        dup_nets = sorted(
            {n.name for n in self.nets if [m.name for m in self.nets].count(n.name) > 1}
        )
        if dup_nets:
            problems.append(f"duplicate net names: {dup_nets}")

        def need_conductor(where: str, name: str) -> None:
            if name not in layer_names:
                problems.append(f"{where}: unknown layer {name!r}")
            elif name not in conductor_names:
                problems.append(f"{where}: layer {name!r} is not a conductor layer")

        def need_net(where: str, name: str) -> None:
            if name not in net_names:
                problems.append(f"{where}: unknown net {name!r}")

        for i, s in enumerate(self.shapes):
            where = f"shapes[{i}]{f' ({s.name})' if s.name else ''}"
            need_conductor(where, s.layer)
            need_net(where, s.net)

        for i, v in enumerate(self.vias):
            where = f"vias[{i}]"
            need_conductor(where, v.from_layer)
            need_conductor(where, v.to_layer)
            need_net(where, v.net)
            if v.drill <= 0.0 or v.plating_thickness <= 0.0:
                problems.append(f"{where}: drill and plating thickness must be > 0")
            elif 2.0 * v.plating_thickness > v.drill:
                problems.append(f"{where}: plating thickness exceeds drill radius")
            if (
                v.from_layer in layer_names
                and v.to_layer in layer_names
                and (self.stackup.index(v.from_layer) >= self.stackup.index(v.to_layer))
            ):
                problems.append(f"{where}: from_layer must be above to_layer")
            if not bool(self.outline.covers([(v.x, v.y)])[0]):
                problems.append(f"{where}: located outside the board outline")

        refs = [c.ref for c in self.components]
        for r in sorted({r for r in refs if refs.count(r) > 1}):
            problems.append(f"duplicate component ref {r!r}")
        for c in self.components:
            if c.power < 0.0:
                problems.append(f"component {c.ref}: power must be >= 0")
            if not self.outline.contains_polygon_bbox(c.footprint):
                problems.append(f"component {c.ref}: footprint extends outside the board")

        port_names = [p.name for p in self.ports]
        for n in sorted({n for n in port_names if port_names.count(n) > 1}):
            problems.append(f"duplicate port name {n!r}")
        for p in self.ports:
            where = f"port {p.name}"
            need_conductor(where, p.layer)
            need_net(where, p.net)
            if p.reference_net is not None:
                need_net(where, p.reference_net)
                if p.reference_net == p.net:
                    problems.append(f"{where}: reference_net must differ from net")
            if p.reference_layer is not None:
                need_conductor(where, p.reference_layer)
                if p.reference_net is None:
                    problems.append(f"{where}: reference_layer given without reference_net")
            if not self.outline.contains_polygon_bbox(p.region):
                problems.append(f"{where}: region extends outside the board")
            if p.kind is PortKind.CURRENT_SINK and p.value < 0.0:
                problems.append(f"{where}: sink current must be >= 0")

        refs_set = set(refs)
        tb_names = [t.name for t in self.thermal_boundaries]
        for n in sorted({n for n in tb_names if tb_names.count(n) > 1}):
            problems.append(f"duplicate thermal boundary name {n!r}")
        for t in self.thermal_boundaries:
            where = f"thermal boundary {t.name}"
            if t.kind is ThermalBoundaryKind.FIXED_TEMPERATURE:
                if t.temperature is None or t.temperature <= 0.0:
                    problems.append(f"{where}: fixed_temperature needs temperature > 0 K")
                if t.component is not None:
                    problems.append(f"{where}: 'component' only applies to convection boundaries")
            else:
                if (t.h is None) == (t.resistance is None):
                    problems.append(f"{where}: give exactly one of h or resistance")
                if (t.h is not None and t.h <= 0.0) or (
                    t.resistance is not None and t.resistance <= 0.0
                ):
                    problems.append(f"{where}: h / resistance must be > 0")
            if t.component is not None and t.component not in refs_set:
                problems.append(f"{where}: unknown component {t.component!r}")
            if t.component is None and not self.outline.contains_polygon_bbox(t.region):
                problems.append(f"{where}: region extends outside the board")

        if problems:
            raise ModelError(problems)
