"""YAML configuration loader (pydantic v2 schema → SI :class:`~pcbsim.model.Board`).

Unit rules
----------
* Any length may be a number or a string with a unit: ``1.6``, ``"1.6 mm"``,
  ``"10 mil"``, ``"35 um"``, ``"1 oz"``. Bare numbers use ``units.length``
  (default ``mm``).
* Temperatures: bare numbers are °C, or ``"358 K"`` / ``"85 C"``.
* Voltage / current / power: bare numbers are V / A / W, or ``"500 mV"`` etc.

Errors are reported as :class:`~pcbsim.errors.ConfigError` with a dotted path
into the document, e.g. ``board.stackup[2].thickness: unknown length unit 'mll'``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import numpy as np
import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from pcbsim.errors import ConfigError, MaterialError, ModelError, UnitError
from pcbsim.materials import MaterialDB
from pcbsim.model import (
    Board,
    Component,
    Criteria,
    CurrentDensityMethod,
    Layer,
    LayerKind,
    LayerRole,
    Net,
    NetKind,
    Polygon,
    Port,
    PortKind,
    Shape,
    Side,
    SinkDistribution,
    Stackup,
    ThermalBoundary,
    ThermalBoundaryKind,
    TransmissionLine,
    Via,
)
from pcbsim.units import Kind, parse_quantity, to_si

if TYPE_CHECKING:
    from pcbsim.io.kicad import KicadBoard


def _quantity(kind: Kind) -> Any:
    def parse(value: Any, info: ValidationInfo) -> float:
        if isinstance(value, int | float) and not isinstance(value, bool) and kind is Kind.LENGTH:
            unit = (info.context or {}).get("length_unit", "mm")
            return to_si(float(value), unit, Kind.LENGTH)
        if isinstance(value, str | int | float):
            try:
                return parse_quantity(value, kind)
            except UnitError as exc:
                raise ValueError(str(exc)) from exc
        raise ValueError(f"expected a {kind.value} (number or string with unit), got {value!r}")

    return BeforeValidator(parse)


Length = Annotated[float, _quantity(Kind.LENGTH)]
Temperature = Annotated[float, _quantity(Kind.TEMPERATURE)]
Voltage = Annotated[float, _quantity(Kind.VOLTAGE)]
Current = Annotated[float, _quantity(Kind.CURRENT)]
Power = Annotated[float, _quantity(Kind.POWER)]
CurrentDensity = Annotated[float, _quantity(Kind.CURRENT_DENSITY)]
ThermalRes = float

PositiveLength = Annotated[Length, Field(gt=0.0)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class CircleSpec(_Model):
    center: tuple[Length, Length]
    r: PositiveLength
    segments: int = Field(default=32, ge=8)


class GeomSpec(_Model):
    """Exactly one of ``rect`` [x0, y0, x1, y1], ``polygon`` [[x, y], ...], ``circle``."""

    rect: tuple[Length, Length, Length, Length] | None = None
    polygon: list[tuple[Length, Length]] | None = None
    circle: CircleSpec | None = None
    holes: list[GeomSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_kind(self) -> GeomSpec:
        given = [k for k in ("rect", "polygon", "circle") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(
                f"specify exactly one of rect / polygon / circle (got {given or 'none'})"
            )
        if self.rect is not None and (self.rect[0] == self.rect[2] or self.rect[1] == self.rect[3]):
            raise ValueError("rect has zero width or height")
        if self.polygon is not None and len(self.polygon) < 3:
            raise ValueError("polygon needs at least 3 vertices")
        return self

    def to_polygon(self) -> Polygon:
        if self.rect is not None:
            base = Polygon.rectangle(*self.rect)
        elif self.polygon is not None:
            base = Polygon(np.asarray(self.polygon, dtype=np.float64))
        else:
            assert self.circle is not None
            c = self.circle
            base = Polygon.circle(c.center[0], c.center[1], c.r, c.segments)
        if not self.holes:
            return base
        return Polygon(base.outer, tuple(h.to_polygon().outer for h in self.holes))


class _HasGeom(_Model):
    rect: tuple[Length, Length, Length, Length] | None = None
    polygon: list[tuple[Length, Length]] | None = None
    circle: CircleSpec | None = None
    holes: list[GeomSpec] = Field(default_factory=list)

    def geom(self) -> GeomSpec | None:
        if self.rect is None and self.polygon is None and self.circle is None:
            return None
        # Fields are already validated (and converted to SI); re-validating would
        # apply the length-unit scaling a second time.
        return GeomSpec.model_construct(
            rect=self.rect, polygon=self.polygon, circle=self.circle, holes=self.holes
        )


class UnitsSpec(_Model):
    length: Literal["mm", "mil", "um", "in", "m"] = "mm"


class LayerSpec(_Model):
    name: str
    kind: LayerKind
    thickness: PositiveLength
    material: str
    role: LayerRole = LayerRole.NONE


class BoardSpec(_Model):
    """Required without ``kicad:``; with it, each given field overrides the file."""

    outline: GeomSpec | None = None
    stackup: list[LayerSpec] | None = Field(default=None, min_length=1)


class KicadSpec(_Model):
    """``kicad:`` section — geometry from a ``.kicad_pcb`` file (see :mod:`pcbsim.io.kicad`)."""

    file: str
    origin: Literal["board", "aux", "file"] = "board"
    nets: list[str] | None = Field(
        default=None, description="import copper of these nets only (default: all nets)"
    )
    components: Literal["listed", "all"] = Field(
        default="listed",
        description="'listed': only footprints named in 'components'; 'all': every footprint",
    )
    vias: list[KicadViaSpec] = Field(
        default_factory=list, description="plating / fill of KiCad vias (KiCad does not store it)"
    )


class KicadViaSpec(_Model):
    """Applies to every imported via matching ``net`` and/or ``drill`` (±1 µm)."""

    net: str | None = None
    drill: PositiveLength | None = None
    plating: PositiveLength | None = None
    material: str | None = None
    filled: bool | None = None
    filler: str | None = None

    @model_validator(mode="after")
    def _check(self) -> KicadViaSpec:
        if self.filled and self.filler is None:
            raise ValueError("filled via requires 'filler' material")
        return self


class NetSpec(_Model):
    name: str
    kind: NetKind = NetKind.SIGNAL
    voltage: Voltage | None = None


class ShapeSpec(_HasGeom):
    name: str = ""
    net: str
    layer: str
    fill: bool = Field(default=False, description="fill the whole board outline (planes)")

    @model_validator(mode="after")
    def _geom_or_fill(self) -> ShapeSpec:
        if self.fill == (self.geom() is not None):
            raise ValueError("give either a geometry (rect/polygon/circle) or 'fill: true'")
        return self


class ViaArraySpec(_Model):
    origin: tuple[Length, Length]
    pitch: tuple[PositiveLength, PositiveLength]
    count: tuple[Annotated[int, Field(ge=1)], Annotated[int, Field(ge=1)]]


class ViaSpec(_Model):
    at: tuple[Length, Length] | None = None
    array: ViaArraySpec | None = None
    drill: PositiveLength
    net: str
    from_layer: str | None = Field(default=None, alias="from")
    to_layer: str | None = Field(default=None, alias="to")
    plating: PositiveLength = 25e-6
    material: str = "copper_ed"
    filled: bool = False
    filler: str | None = None

    @model_validator(mode="after")
    def _at_or_array(self) -> ViaSpec:
        if (self.at is None) == (self.array is None):
            raise ValueError("give exactly one of 'at' or 'array'")
        if self.filled and self.filler is None:
            raise ValueError("filled via requires 'filler' material")
        return self

    def positions(self) -> list[tuple[float, float]]:
        if self.at is not None:
            return [self.at]
        assert self.array is not None
        a = self.array
        return [
            (a.origin[0] + i * a.pitch[0], a.origin[1] + j * a.pitch[1])
            for j in range(a.count[1])
            for i in range(a.count[0])
        ]


class ComponentSpec(_HasGeom):
    ref: str
    side: Side | None = None
    power: Annotated[Power, Field(ge=0.0)] = 0.0
    tj_max: Temperature | None = None
    theta_jc: Annotated[ThermalRes, Field(gt=0.0)] | None = None
    theta_jb: Annotated[ThermalRes, Field(gt=0.0)] | None = None


class ThermalBoundarySpec(_HasGeom):
    name: str
    kind: ThermalBoundaryKind
    side: Side = Side.BOTTOM
    component: str | None = Field(
        default=None, description="convection: heat sink on this component's case"
    )
    temperature: Temperature | None = None
    h: Annotated[float, Field(gt=0.0)] | None = None
    resistance: Annotated[ThermalRes, Field(gt=0.0)] | None = None
    ambient: Temperature | None = None

    @model_validator(mode="after")
    def _check(self) -> ThermalBoundarySpec:
        has_geom = self.geom() is not None
        if self.kind is ThermalBoundaryKind.FIXED_TEMPERATURE:
            if self.temperature is None:
                raise ValueError("fixed_temperature boundary needs 'temperature'")
            if self.h is not None or self.resistance is not None or self.ambient is not None:
                raise ValueError("fixed_temperature boundary takes no h / resistance / ambient")
            if self.component is not None:
                raise ValueError("'component' only applies to convection boundaries")
            if not has_geom:
                raise ValueError("fixed_temperature boundary needs a region (rect/polygon/circle)")
        else:
            if (self.h is None) == (self.resistance is None):
                raise ValueError("convection boundary needs exactly one of 'h' or 'resistance'")
            if self.temperature is not None:
                raise ValueError("convection boundary uses 'ambient', not 'temperature'")
            if has_geom == (self.component is not None):
                raise ValueError("give either a region or 'component: <ref>'")
        return self


class PortSpec(_HasGeom):
    name: str
    kind: PortKind
    net: str
    layer: str
    component: str | None = Field(default=None, description="use this component's footprint")
    reference_net: str | None = None
    reference_layer: str | None = None
    distribution: SinkDistribution = SinkDistribution.UNIFORM
    voltage: Voltage | None = None
    current: Current | None = None

    @model_validator(mode="after")
    def _check(self) -> PortSpec:
        if (self.component is None) == (self.geom() is None):
            raise ValueError("give either a geometry or 'component: <ref>' for the port region")
        if self.kind is PortKind.VOLTAGE_SOURCE and (
            self.voltage is None or self.current is not None
        ):
            raise ValueError("voltage_source port needs 'voltage' (and no 'current')")
        if self.kind is PortKind.CURRENT_SINK and (
            self.current is None or self.voltage is not None
        ):
            raise ValueError("current_sink port needs 'current' (and no 'voltage')")
        if (
            self.kind is PortKind.VOLTAGE_SOURCE
            and "distribution" in self.model_fields_set
            and self.distribution is not SinkDistribution.EQUIPOTENTIAL
        ):
            raise ValueError("voltage_source ports are always equipotential")
        return self

    @property
    def value(self) -> float:
        v = self.voltage if self.kind is PortKind.VOLTAGE_SOURCE else self.current
        assert v is not None
        return v


class TransmissionLineSpec(_Model):
    name: str
    layer: str
    width: PositiveLength
    spacing: PositiveLength | None = None
    target: Annotated[float, Field(gt=0.0)] | None = Field(
        default=None, description="Ω; single-ended Z0, or Zdiff for a pair"
    )
    references: list[str] = Field(default_factory=list)
    tolerance_pct: Annotated[float, Field(gt=0.0, le=100.0)] | None = None


class CriteriaSpec(_Model):
    ir_drop_pct: Annotated[float, Field(gt=0.0, le=100.0)] = 3.0
    tj_max_default: Temperature = 105.0 + 273.15
    current_density: CurrentDensityMethod = CurrentDensityMethod.IPC2152
    current_density_temp_rise: Annotated[float, Field(gt=0.0)] = 10.0
    current_density_limit: Annotated[CurrentDensity, Field(gt=0.0)] | None = None
    current_density_ref_width: PositiveLength = 1e-3
    z0_tol_pct: Annotated[float, Field(gt=0.0, le=100.0)] = 10.0


class MeshSpec(_Model):
    cell: PositiveLength = 0.5e-3
    refine: Annotated[int, Field(ge=1)] = 1


# Composite solvers run these solvers internally, so their options are accepted
# even when only the composite is listed in ``analysis.solvers``.
_DRIVES: dict[str, set[str]] = {"coupled": {"dc_ir", "thermal"}}


class AnalysisSpec(_Model):
    solvers: list[str] = Field(default_factory=list)
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    output_dir: str = "results"
    options: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="per-solver options, validated by each solver"
    )

    @model_validator(mode="after")
    def _options_match(self) -> AnalysisSpec:
        allowed = set(self.solvers)
        for name in self.solvers:
            allowed |= _DRIVES.get(name, set())
        stray = set(self.options) - allowed
        if stray:
            raise ValueError(f"options given for solvers not listed in 'solvers': {sorted(stray)}")
        return self


class MechanicalSpec(_Model):
    """Link to an ECAD–MCAD match result (``pcbsim match --json``)."""

    match: str
    offset: tuple[Length, Length] = (0.0, 0.0)
    apply_boundaries: bool = True
    require_ok: bool = True


class ConfigSpec(_Model):
    version: Literal[1] = 1
    name: str = "board"
    units: UnitsSpec = Field(default_factory=UnitsSpec)
    material_files: list[str] = Field(default_factory=list)
    materials: dict[str, dict[str, Any]] = Field(default_factory=dict)
    kicad: KicadSpec | None = None
    board: BoardSpec = Field(default_factory=BoardSpec)
    nets: list[NetSpec] = Field(default_factory=list)
    shapes: list[ShapeSpec] = Field(default_factory=list)
    vias: list[ViaSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)
    ports: list[PortSpec] = Field(default_factory=list)
    thermal_boundaries: list[ThermalBoundarySpec] = Field(default_factory=list)
    transmission_lines: list[TransmissionLineSpec] = Field(default_factory=list)
    criteria: CriteriaSpec = Field(default_factory=CriteriaSpec)
    analysis: AnalysisSpec = Field(default_factory=AnalysisSpec)
    mechanical: MechanicalSpec | None = None

    @model_validator(mode="after")
    def _board_source(self) -> ConfigSpec:
        if self.kicad is None:
            missing = [k for k in ("outline", "stackup") if getattr(self.board, k) is None]
            if missing:
                raise ValueError(f"board needs {' and '.join(missing)} (or give a 'kicad:' file)")
            for i, c in enumerate(self.components):
                if c.geom() is None:
                    raise ValueError(
                        f"components[{i}] ({c.ref}): needs a footprint geometry "
                        "(rect/polygon/circle) unless it comes from a 'kicad:' file"
                    )
        return self


@dataclass(frozen=True, slots=True)
class KicadInfo:
    """What a ``kicad:`` import produced, for ``pcbsim check``."""

    path: Path
    counts: Mapping[str, int]
    notes: tuple[str, ...]
    min_width: Mapping[str, float]
    footprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeshOptions:
    cell: float
    refine: int = 1


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    solvers: tuple[str, ...] = ()
    mesh: MeshOptions = field(default_factory=lambda: MeshOptions(cell=0.5e-3))
    output_dir: Path = Path("results")
    options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MechanicalLink:
    """Resolved ``mechanical:`` section: the match file and whether it passed."""

    match_path: Path
    ok: bool
    require_ok: bool
    ng_items: tuple[str, ...] = ()
    applied_boundaries: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    board: Board
    materials: MaterialDB
    analysis: AnalysisConfig
    source: Path | None = None
    mechanical: MechanicalLink | None = None
    kicad: KicadInfo | None = None


def format_loc(loc: Sequence[int | str]) -> str:
    """('board', 'stackup', 2, 'thickness') → 'board.stackup[2].thickness'."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "<root>"


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_url=False):
        loc = [p for p in err["loc"] if not (isinstance(p, str) and p.startswith("function-"))]
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"{format_loc(loc)}: {msg}")
    return "\n".join(lines)


def _check_materials(spec: ConfigSpec, db: MaterialDB, stack: Sequence[Layer]) -> list[str]:
    problems: list[str] = []

    def lookup(path: str, name: str) -> None:
        try:
            db[name]
        except MaterialError as exc:
            problems.append(f"{path}: {exc}")

    for i, ls in enumerate(stack):
        path = f"board.stackup[{i}].material" if spec.kicad is None else f"stack-up {ls.name}"
        try:
            m = db[ls.material]
        except MaterialError as exc:
            problems.append(f"{path}: {exc}")
            continue
        if ls.kind is LayerKind.CONDUCTOR and not m.is_conductor:
            problems.append(f"{path}: conductor layer uses non-conductive material {m.name!r}")
        if ls.kind is not LayerKind.CONDUCTOR and m.eps_r is None:
            problems.append(f"{path}: dielectric layer material {m.name!r} has no eps_r")
        if m.k_inplane is None:
            problems.append(f"{path}: material {m.name!r} has no thermal conductivity")
    for i, kv in enumerate(spec.kicad.vias if spec.kicad is not None else []):
        if kv.material is not None:
            lookup(f"kicad.vias[{i}].material", kv.material)
        if kv.filler is not None:
            lookup(f"kicad.vias[{i}].filler", kv.filler)
    for i, vs in enumerate(spec.vias):
        lookup(f"vias[{i}].material", vs.material)
        if vs.filler is not None:
            lookup(f"vias[{i}].filler", vs.filler)
    return problems


def _stack_from_spec(spec: ConfigSpec) -> tuple[Layer, ...] | None:
    if spec.board.stackup is None:
        return None
    return tuple(
        Layer(ls.name, ls.kind, ls.thickness, ls.material, ls.role) for ls in spec.board.stackup
    )


def _build_board(spec: ConfigSpec, kb: KicadBoard | None = None) -> Board:
    if kb is None:
        layers = _stack_from_spec(spec)
        assert layers is not None
        assert spec.board.outline is not None
        stackup = Stackup(layers)
        outline = spec.board.outline.to_polygon()
    else:
        stackup = Stackup(_stack_from_spec(spec) or kb.stackup)
        outline = spec.board.outline.to_polygon() if spec.board.outline else kb.outline
    conductors = [layer.name for layer in stackup.conductor_layers()]

    def lay(name: str) -> str:
        return kb.resolve_layer(name) if kb is not None else name

    def net_name(name: str) -> str:
        return kb.resolve_net(name) if kb is not None else name

    user_nets = {net_name(n.name): n for n in spec.nets}
    nets_l: list[Net] = []
    if kb is not None:
        for n in kb.nets:
            u = user_nets.get(n.name)
            nets_l.append(Net(n.name, u.kind, u.voltage) if u is not None else n)
    known = {n.name for n in nets_l}
    nets_l += [Net(name, n.kind, n.voltage) for name, n in user_nets.items() if name not in known]
    nets = tuple(nets_l)

    shapes = tuple(kb.shapes if kb is not None else ()) + tuple(
        Shape(
            net=net_name(s.net),
            layer=lay(s.layer),
            polygon=outline if s.fill else _geom(s).to_polygon(),
            name=s.name,
        )
        for s in spec.shapes
    )

    vias: list[Via] = list(kb.vias) if kb is not None else []
    for vs in spec.vias:
        frm = lay(vs.from_layer) if vs.from_layer else (conductors[0] if conductors else "")
        to = lay(vs.to_layer) if vs.to_layer else (conductors[-1] if conductors else "")
        for x, y in vs.positions():
            vias.append(
                Via(
                    x=x,
                    y=y,
                    drill=vs.drill,
                    from_layer=frm,
                    to_layer=to,
                    net=net_name(vs.net),
                    plating_thickness=vs.plating,
                    material=vs.material,
                    filled=vs.filled,
                    filler=vs.filler,
                )
            )

    footprints = kb.footprints if kb is not None else {}
    comps: list[Component] = []
    for i, cs in enumerate(spec.components):
        g = cs.geom()
        fp = footprints.get(cs.ref)
        if g is not None:
            poly = g.to_polygon()
        elif fp is not None:
            poly = fp.outline
        else:
            raise ConfigError(
                f"components[{i}] ({cs.ref}): no footprint {cs.ref!r} in the KiCad file "
                "and no geometry given"
            )
        comps.append(
            Component(
                ref=cs.ref,
                footprint=poly,
                side=cs.side or (fp.side if fp is not None else Side.TOP),
                power=cs.power,
                tj_max=cs.tj_max,
                theta_jc=cs.theta_jc,
                theta_jb=cs.theta_jb,
            )
        )
    if kb is not None and spec.kicad is not None and spec.kicad.components == "all":
        listed = {c.ref for c in comps}
        comps += [
            Component(ref=r, footprint=fp.outline, side=fp.side)
            for r, fp in footprints.items()
            if r not in listed
        ]
    components = tuple(comps)
    by_ref = {c.ref: c for c in components}

    def region_of(ref: str, where: str) -> tuple[Polygon, Side]:
        if ref in by_ref:
            return by_ref[ref].footprint, by_ref[ref].side
        if ref in footprints:
            return footprints[ref].outline, footprints[ref].side
        raise ConfigError(f"{where}: unknown component {ref!r}")

    ports: list[Port] = []
    for i, p in enumerate(spec.ports):
        if p.component is not None:
            region, _ = region_of(p.component, f"ports[{i}].component")
        else:
            region = _geom(p).to_polygon()
        distribution = (
            SinkDistribution.EQUIPOTENTIAL if p.kind is PortKind.VOLTAGE_SOURCE else p.distribution
        )
        ports.append(
            Port(
                p.name,
                p.kind,
                net_name(p.net),
                lay(p.layer),
                region,
                p.value,
                reference_net=net_name(p.reference_net) if p.reference_net else None,
                reference_layer=lay(p.reference_layer) if p.reference_layer else None,
                distribution=distribution,
            )
        )

    c = spec.criteria
    criteria = Criteria(
        ir_drop_pct=c.ir_drop_pct,
        tj_max_default=c.tj_max_default,
        current_density=c.current_density,
        current_density_temp_rise=c.current_density_temp_rise,
        current_density_limit=c.current_density_limit,
        current_density_ref_width=c.current_density_ref_width,
        z0_tol_pct=c.z0_tol_pct,
    )
    boundaries: list[ThermalBoundary] = []
    for i, t in enumerate(spec.thermal_boundaries):
        if t.component is not None:
            if t.component not in by_ref:
                raise ConfigError(
                    f"thermal_boundaries[{i}].component: unknown component {t.component!r}"
                )
            region, side = region_of(t.component, f"thermal_boundaries[{i}].component")
        else:
            region = _geom(t).to_polygon()
            side = t.side
        boundaries.append(
            ThermalBoundary(
                name=t.name,
                kind=t.kind,
                side=side,
                region=region,
                temperature=t.temperature,
                h=t.h,
                resistance=t.resistance,
                ambient=t.ambient,
                component=t.component,
            )
        )

    return Board(
        name=spec.name,
        outline=outline,
        stackup=stackup,
        nets=nets,
        shapes=shapes,
        vias=tuple(vias),
        components=components,
        ports=tuple(ports),
        criteria=criteria,
        thermal_boundaries=tuple(boundaries),
        transmission_lines=tuple(
            TransmissionLine(
                name=t.name,
                layer=lay(t.layer),
                width=t.width,
                spacing=t.spacing,
                target=t.target,
                references=tuple(lay(r) for r in t.references),
                tolerance_pct=t.tolerance_pct,
            )
            for t in spec.transmission_lines
        ),
    )


def _geom(item: _HasGeom) -> GeomSpec:
    g = item.geom()
    assert g is not None
    return g


def load_config_dict(data: Mapping[str, Any], base_dir: Path | None = None) -> LoadedConfig:
    """Validate a parsed YAML mapping and build the SI board model."""
    if not isinstance(data, Mapping):
        raise ConfigError("<root>: config must be a YAML mapping")
    raw_units = data.get("units") or {}
    length_unit = raw_units.get("length", "mm") if isinstance(raw_units, Mapping) else "mm"
    try:
        spec = ConfigSpec.model_validate(dict(data), context={"length_unit": length_unit})
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from None

    base = base_dir or Path.cwd()
    kb: KicadBoard | None = None
    if spec.kicad is not None:
        kb = _read_kicad(spec.kicad, base)
    try:
        db = MaterialDB.load(*(base / p for p in spec.material_files))
        if kb is not None:
            db = db.merged(_kicad_materials(kb, db))
        db = db.merged(spec.materials)
    except FileNotFoundError as exc:
        raise ConfigError(f"material_files: file not found: {exc.filename}") from None
    except MaterialError as exc:
        raise ConfigError(f"materials: {exc}") from None

    stack = _stack_from_spec(spec) or (kb.stackup if kb is not None else ())
    problems = _check_materials(spec, db, stack)
    if problems:
        raise ConfigError("\n".join(problems))

    board = _build_board(spec, kb)
    mech_link: MechanicalLink | None = None
    if spec.mechanical is not None:
        board, mech_link = _apply_mechanical(spec.mechanical, board, base_dir or Path.cwd())
    try:
        board.validate()
    except ModelError as exc:
        raise ConfigError("\n".join(exc.problems)) from None

    a = spec.analysis
    out_dir = Path(a.output_dir)
    analysis = AnalysisConfig(
        solvers=tuple(a.solvers),
        mesh=MeshOptions(cell=a.mesh.cell, refine=a.mesh.refine),
        output_dir=out_dir if out_dir.is_absolute() else base / out_dir,
        options={k: dict(v) for k, v in a.options.items()},
    )
    info = None
    if kb is not None:
        info = KicadInfo(
            path=kb.path,
            counts=kb.counts,
            notes=tuple(kb.notes),
            min_width=kb.min_width,
            footprints=tuple(kb.footprints),
        )
    return LoadedConfig(
        board=board, materials=db, analysis=analysis, mechanical=mech_link, kicad=info
    )


def _read_kicad(ks: KicadSpec, base: Path) -> KicadBoard:
    from dataclasses import replace

    from pcbsim.io.kicad import read_kicad

    path = Path(ks.file)
    kb = read_kicad(path if path.is_absolute() else base / path, origin=ks.origin)
    if ks.vias:
        kb = replace(kb, vias=tuple(_via_override(v, ks.vias, kb) for v in kb.vias))
    if ks.nets is None:
        return kb
    wanted = {kb.resolve_net(n) for n in ks.nets}
    unknown = sorted(wanted - {n.name for n in kb.nets})
    if unknown:
        raise ConfigError(f"kicad.nets: not in the KiCad file: {unknown}")
    return replace(
        kb,
        nets=tuple(n for n in kb.nets if n.name in wanted),
        shapes=tuple(s for s in kb.shapes if s.net in wanted),
        vias=tuple(v for v in kb.vias if v.net in wanted),
    )


def _via_override(v: Via, rules: Sequence[KicadViaSpec], kb: KicadBoard) -> Via:
    from dataclasses import replace

    for r in rules:
        if r.net is not None and kb.resolve_net(r.net) != v.net:
            continue
        if r.drill is not None and abs(r.drill - v.drill) > 1e-6:
            continue
        v = replace(
            v,
            plating_thickness=r.plating if r.plating is not None else v.plating_thickness,
            material=r.material or v.material,
            filled=r.filled if r.filled is not None else v.filled,
            filler=r.filler if r.filler is not None else v.filler,
        )
    return v


def _kicad_materials(kb: KicadBoard, db: MaterialDB) -> dict[str, dict[str, Any]]:
    """``kicad:<layer>`` materials: a DB base material with the file's εr / tanδ."""
    from dataclasses import asdict

    out: dict[str, dict[str, Any]] = {}
    for name, props in kb.materials.items():
        base = asdict(db[props["base"]])
        base.pop("name")
        base["description"] = f"{name} (KiCad stack-up, based on {props['base']})"
        out[name] = {**base, **{k: v for k, v in props.items() if k != "base"}}
    return out


def _apply_mechanical(ms: MechanicalSpec, board: Board, base: Path) -> tuple[Board, MechanicalLink]:
    """Append the match result's thermal boundaries (board frame + ``offset``).

    Boundaries already defined in the config win: a match boundary is skipped if its
    name exists, or if it is a heat sink on a component that already has one.
    """
    from dataclasses import replace

    from pcbsim.registration.pipeline import load_match

    path = Path(ms.match)
    path = path if path.is_absolute() else base / path
    stored = load_match(path)
    applied: list[ThermalBoundary] = []
    if ms.apply_boundaries:
        existing = {t.name for t in board.thermal_boundaries}
        sunk = {t.component for t in board.thermal_boundaries if t.component is not None}
        refs = {c.ref for c in board.components}
        for mb in stored.boundaries:
            if mb.name in existing:
                continue
            if mb.component is not None and (mb.component not in refs or mb.component in sunk):
                continue
            if mb.component is not None:
                comp = next(c for c in board.components if c.ref == mb.component)
                region, side = comp.footprint, comp.side
            else:
                assert mb.polygon is not None
                pts = np.asarray(mb.polygon, dtype=np.float64) + np.asarray(ms.offset)
                region, side = Polygon(pts), Side(mb.side)
            applied.append(
                ThermalBoundary(
                    name=mb.name,
                    kind=ThermalBoundaryKind(mb.kind),
                    side=side,
                    region=region,
                    temperature=mb.temperature,
                    h=mb.h,
                    resistance=mb.resistance,
                    ambient=mb.ambient,
                    component=mb.component,
                )
            )
    board = replace(board, thermal_boundaries=board.thermal_boundaries + tuple(applied))
    link = MechanicalLink(
        match_path=path,
        ok=stored.ok,
        require_ok=ms.require_ok,
        ng_items=stored.ng_items,
        applied_boundaries=tuple(t.name for t in applied),
    )
    return board, link


def load_config(path: str | Path) -> LoadedConfig:
    """Load and validate a YAML config file, or a bare ``.kicad_pcb`` (geometry only)."""
    p = Path(path)
    if p.suffix == ".kicad_pcb":
        if not p.exists():
            raise ConfigError(f"KiCad file not found: {p}")
        data: Any = {"name": p.stem, "kicad": {"file": p.name}}
    else:
        try:
            text = p.read_text("utf-8")
        except FileNotFoundError:
            raise ConfigError(f"config file not found: {p}") from None
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{p}: YAML syntax error: {exc}") from None
    loaded = load_config_dict(data, base_dir=p.parent.resolve())
    return LoadedConfig(
        loaded.board,
        loaded.materials,
        loaded.analysis,
        source=p.resolve(),
        mechanical=loaded.mechanical,
        kicad=loaded.kicad,
    )
