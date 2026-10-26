"""2.5D steady-state and transient thermal solver.

Model (compact "layer-lumped" PCB model)
----------------------------------------
Every conductor layer is a *sheet* of nodes, one per board cell of the shared
:class:`~pcbsim.mesh.Grid`. Dielectric layers are not separate nodes: each
contributes in-plane conduction and heat capacity to the conductor sheets next
to it (an inner dielectric is split half/half between the two sheets around it;
outer layers such as solder mask go entirely to the outer sheet) and adds a
through-plane series resistance between sheets.

Energy balance per node, finite volume::

    C_i dT_i/dt = Σ_j G_ij (T_j − T_i) + G_amb,i (T_∞ − T_i) + P_i

In-plane conductance (x; y analogous) with the sheet conductance per cell
``(kt)_i = k_cell·t_layer + Σ_lumped k_xy,d·t_d``::

    G_ij = 1 / ( (Δx/2)/((kt)_i Δy) + (Δx/2)/((kt)_j Δy) )

``k_cell`` is copper where the layer has copper and the *fill* (adjacent
dielectric) elsewhere, so planes spread heat and the gaps between traces don't.

Through-plane conductance between consecutive sheets a, b per cell (series)::

    G_ab = A / ( t_a/(2 k_z,a) + Σ_d t_d/k_z,d + t_b/(2 k_z,b) )

Thermal vias (parallel to the dielectric), between consecutive pierced sheets::

    G_via = (k_barrel·A_barrel + k_fill·A_fill) / L

A via pierces its ``from``/``to`` layers (pads) and every layer in between that
carries copper of its own net at the via location (antipads elsewhere).

Surfaces (per face cell, series path through the outer layers)::

    G_face = A / ( R_s + 1/(h + h_rad) ),   R_s = t_cu/(2 k_z) + Σ_outer t/k_z
    h_rad  = ε σ_SB (T_s² + T_∞²)(T_s + T_∞)            (linearised radiation)

Steady state solves the exact (nonlinear) face law by Newton iteration with
the tangent ``dq/dT_n = A/(R_s + 1/(h + 4εσT_s³))``; transient runs lag the
secant ``h_rad`` by one step. The matrix is factorised once (sparse LU,
minimum-degree ordering); later updates only change the diagonal and are
solved by CG preconditioned with that factorisation. Board edges use
``h_edge`` (default 0, adiabatic).

Components
----------
* With ``theta_jb``: JEDEC two-resistor compact model (JESD15-3). A junction
  node carries the power; ``θ_jb`` connects it to the outer sheet under the
  footprint (distributed by area) and ``θ_jc + R_case→amb`` connects it to
  ambient, where ``R_case→amb = 1/(h_face·A)`` or a heat-sink boundary.
  The board face under the package does not convect.
* Without ``theta_jb``: the power is spread uniformly over the footprint cells
  of the outer sheet and ``Tj`` is reported as the hottest board cell under it.

Boundaries: ``fixed_temperature`` (Dirichlet on the outer sheet under the region)
and ``convection`` (replaces h on that face under the region; radiation off).

Transient: implicit (backward) Euler,
``(C/Δt + K) Tⁿ⁺¹ = C/Δt Tⁿ + f(tⁿ⁺¹)``; unconditionally stable, first order.

Heat sources: component power, plus Joule heat ``P = Σ G ΔV²`` from an upstream
``dc_ir`` result (option ``joule``) or an explicit ``joule_field``.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from scipy.sparse.linalg import LinearOperator, cg, splu

from pcbsim.errors import MaterialError, SolverError
from pcbsim.materials import Material
from pcbsim.mesh import Grid, build_grid
from pcbsim.model import Component, Side, ThermalBoundaryKind
from pcbsim.solvers.base import FieldData, ResultSet, Severity, Solver, Violation, register
from pcbsim.units import celsius_to_kelvin, kelvin_to_celsius

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

SIGMA_SB = 5.670374419e-8


class TransientOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_end: float = Field(gt=0.0, description="simulated time [s]")
    dt: float = Field(gt=0.0, description="time step [s]")
    initial: float | str = Field(
        default="ambient", description="'ambient', 'steady' or a temperature in °C"
    )
    power_steps: list[tuple[float, float]] = Field(
        default_factory=list,
        description="piecewise-constant power scale [[t_start_s, scale], ...]; default 1",
    )

    @field_validator("initial")
    @classmethod
    def _initial(cls, v: float | str) -> float | str:
        if isinstance(v, str) and v not in ("ambient", "steady"):
            raise ValueError("initial must be 'ambient', 'steady' or a number (°C)")
        return v

    @field_validator("power_steps")
    @classmethod
    def _steps(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        times = [t for t, _ in v]
        if times != sorted(times):
            raise ValueError("power_steps must be sorted by time")
        if any(s < 0.0 for _, s in v):
            raise ValueError("power scale must be >= 0")
        return v

    def scale(self, t: float) -> float:
        s = 1.0
        for t0, val in self.power_steps:
            if t >= t0:
                s = val
        return s


class ThermalOptions(BaseModel):
    """Options of the ``thermal`` solver (``analysis.options.thermal``). Temperatures in °C."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    ambient: float = 25.0
    h_top: float = Field(default=10.0, ge=0.0)
    h_bottom: float = Field(default=10.0, ge=0.0)
    h_edge: float = Field(default=0.0, ge=0.0)
    radiation: bool = True
    emissivity_top: float | None = Field(default=None, ge=0.0, le=1.0)
    emissivity_bottom: float | None = Field(default=None, ge=0.0, le=1.0)
    joule: bool = True
    joule_field: Any = Field(default=None, description="(n_layers, ny, nx) W per cell")
    fill_material: str | None = None
    cell: float | None = Field(default=None, gt=0.0)
    mode: str = "steady"
    transient: TransientOptions | None = None
    picard_tol: float = Field(
        default=1e-6, ge=1e-9, description="Newton step tolerance for radiation [K]"
    )
    picard_maxiter: int = Field(default=100, ge=1)

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("steady", "transient"):
            raise ValueError("mode must be 'steady' or 'transient'")
        return v


@dataclass(slots=True)
class _Face:
    """Per-cell surface path of one board face (top or bottom)."""

    nodes: IntArray
    area: float
    r_series: FloatArray
    h: FloatArray
    ambient: FloatArray
    emissivity: FloatArray
    label: IntArray


@dataclass(slots=True)
class _Junction:
    comp: Component
    node: int
    sheet_nodes: IntArray
    g_board: FloatArray
    g_amb: float
    ambient: float


@dataclass(slots=True)
class ThermalSystem:
    grid: Grid
    nid: NDArray[np.int64]
    n_sheet: int
    n_nodes: int
    k_static: sp.csr_matrix
    g_amb_static: FloatArray
    t_amb_static: FloatArray
    faces: list[_Face]
    capacity: FloatArray
    power: FloatArray
    dirichlet: dict[int, float]
    junctions: list[_Junction]
    lumped: dict[str, BoolArray]
    face_labels: list[str]
    p_components: float
    p_joule: float
    warnings: list[str] = field(default_factory=list)


@register("thermal")
class ThermalSolver(Solver):
    description = "2.5D steady/transient conduction, convection, radiation, thermal vias"
    uses = ("dc_ir",)

    def validate_options(self) -> None:
        try:
            self.opts = ThermalOptions.model_validate(self.options)
        except ValidationError as exc:
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise SolverError(f"thermal options: {msgs}") from None
        if self.opts.mode == "transient" and self.opts.transient is None:
            raise SolverError("thermal options: mode 'transient' needs a 'transient' section")

    def assemble(self) -> None:
        self._require_phase("setup")
        ctx = self.ctx
        grid = ctx.mesh if isinstance(ctx.mesh, Grid) else None
        if grid is None:
            grid = build_grid(ctx.board, self.opts.cell or 0.5e-3)
        self.system = _assemble(self, grid)
        self._phase = "assembled"

    def solve(self) -> None:
        self._require_phase("assembled")
        sysm, o = self.system, self.opts
        self.history: dict[str, list[float]] = {}
        if o.mode == "steady":
            self.t_node, self.iterations = _solve_steady(sysm, o)
        else:
            assert o.transient is not None
            self.t_node, self.history = _solve_transient(sysm, o, o.transient)
            self.iterations = 0
        self._phase = "solved"

    def results(self) -> ResultSet:
        self._require_phase("solved")
        return _postprocess(self)


def _fill_material(solver: ThermalSolver, li_stack: int) -> Material:
    db, layers = solver.ctx.materials, solver.ctx.board.stackup.layers
    if solver.opts.fill_material is not None:
        return db[solver.opts.fill_material]
    for j in (li_stack + 1, li_stack - 1):
        if 0 <= j < len(layers) and not layers[j].is_conductor:
            return db[layers[j].material]
    return db["fr4"] if "fr4" in db else db[layers[li_stack].material]


def _req(m: Material, *props: str) -> None:
    try:
        m.require(*props)
    except MaterialError as exc:
        raise SolverError(f"thermal: {exc}") from None


def _assemble(solver: ThermalSolver, grid: Grid) -> ThermalSystem:
    board, db, o = solver.ctx.board, solver.ctx.materials, solver.opts
    stack = board.stackup
    layers = stack.layers
    cond_stack_idx = [i for i, layer in enumerate(layers) if layer.is_conductor]
    n_l = len(cond_stack_idx)
    inside = grid.inside
    n_in = int(inside.sum())
    if n_in == 0:
        raise SolverError("thermal: board outline covers no grid cell")
    nid = np.full((n_l, grid.ny, grid.nx), -1, dtype=np.int64)
    for li in range(n_l):
        nid[li][inside] = li * n_in + np.arange(n_in)
    n_sheet = n_l * n_in
    a_cell = grid.cell_area
    warnings: list[str] = []

    kt = np.zeros((n_l, grid.ny, grid.nx))
    cap = np.zeros((n_l, grid.ny, grid.nx))
    kz_half = np.zeros((n_l, grid.ny, grid.nx))
    t_sheet = np.zeros(n_l)
    for li, si in enumerate(cond_stack_idx):
        layer = layers[si]
        m_cu = db[layer.material]
        m_fill = _fill_material(solver, si)
        for m in (m_cu, m_fill):
            _req(m, "k_inplane", "k_through", "density", "cp")
        assert m_cu.k_inplane
        assert m_cu.k_through
        assert m_cu.density
        assert m_cu.cp
        assert m_fill.k_inplane
        assert m_fill.k_through
        assert m_fill.density
        assert m_fill.cp
        cu = grid.net_map[li] >= 0
        t = layer.thickness
        kt[li] = np.where(cu, m_cu.k_inplane, m_fill.k_inplane) * t
        cap[li] = np.where(cu, m_cu.density * m_cu.cp, m_fill.density * m_fill.cp) * t * a_cell
        kz_half[li] = t / (2.0 * np.where(cu, m_cu.k_through, m_fill.k_through))
        t_sheet[li] = t

    def lump(si: int, li: int, frac: float) -> None:
        m = db[layers[si].material]
        _req(m, "k_inplane", "density", "cp")
        assert m.k_inplane is not None
        assert m.density is not None
        assert m.cp is not None
        t = layers[si].thickness * frac
        kt[li] += m.k_inplane * t
        cap[li] += m.density * m.cp * t * a_cell
        t_sheet[li] += t

    r_between = np.zeros(max(n_l - 1, 0))
    for si, layer in enumerate(layers):
        if layer.is_conductor:
            continue
        above = [k for k, c in enumerate(cond_stack_idx) if c < si]
        below = [k for k, c in enumerate(cond_stack_idx) if c > si]
        m = db[layer.material]
        _req(m, "k_through")
        assert m.k_through is not None
        if above and below:
            lump(si, above[-1], 0.5)
            lump(si, below[0], 0.5)
            r_between[above[-1]] += layer.thickness / m.k_through
        else:
            lump(si, above[-1] if above else below[0], 1.0)

    rows: list[IntArray] = []
    cols: list[IntArray] = []
    vals: list[FloatArray] = []

    def add(i: IntArray, j: IntArray, g: FloatArray) -> None:
        rows.extend([i, j, i, j])
        cols.extend([i, j, j, i])
        vals.extend([g, g, -g, -g])

    for li in range(n_l):
        for sl_a, sl_b, along, across in (
            ((slice(None), slice(None, -1)), (slice(None), slice(1, None)), grid.dx, grid.dy),
            ((slice(None, -1), slice(None)), (slice(1, None), slice(None)), grid.dy, grid.dx),
        ):
            ok = inside[sl_a] & inside[sl_b]
            ra = (along / 2.0) / (kt[li][sl_a][ok] * across)
            rb = (along / 2.0) / (kt[li][sl_b][ok] * across)
            add(nid[li][sl_a][ok], nid[li][sl_b][ok], 1.0 / (ra + rb))

    for li in range(n_l - 1):
        r_area = kz_half[li][inside] + r_between[li] + kz_half[li + 1][inside]
        add(nid[li][inside], nid[li + 1][inside], a_cell / r_area)

    n_via_links = 0
    cond_names = [layers[i].name for i in cond_stack_idx]
    for k, v in enumerate(board.vias):
        iy, ix = grid.cell_of(v.x, v.y)
        if not inside[iy, ix]:
            continue
        a, b = cond_names.index(v.from_layer), cond_names.index(v.to_layer)
        ni = grid.net_index(v.net)
        hit = [li for li in range(a, b + 1) if li in (a, b) or grid.net_map[li, iy, ix] == ni]
        m_b = db[v.material]
        _req(m_b, "k_through")
        assert m_b.k_through is not None
        k_fill = 0.0
        if v.filled and v.filler:
            m_f = db[v.filler]
            _req(m_f, "k_through")
            assert m_f.k_through is not None
            k_fill = m_f.k_through
        for la, lb in itertools.pairwise(hit):
            length = stack.span(cond_names[la], cond_names[lb])
            g = (m_b.k_through * v.barrel_area + k_fill * v.fill_area) / length
            add(np.array([nid[la, iy, ix]]), np.array([nid[lb, iy, ix]]), np.array([g]))
            n_via_links += 1
        if v.filled and v.filler is None:
            warnings.append(f"via {k}: filled but no filler material")

    t_amb = celsius_to_kelvin(o.ambient)
    g_amb_static = np.zeros(n_sheet + len(board.components))
    t_amb_static = np.full(n_sheet + len(board.components), t_amb)

    if o.h_edge > 0.0:
        pad = np.pad(inside, 1, constant_values=False)
        for li in range(n_l):
            exposed_len = np.zeros(grid.shape)
            for dy_, dx_, length in (
                (0, 1, grid.dy),
                (0, -1, grid.dy),
                (1, 0, grid.dx),
                (-1, 0, grid.dx),
            ):
                nb = pad[1 + dy_ : 1 + dy_ + grid.ny, 1 + dx_ : 1 + dx_ + grid.nx]
                exposed_len += np.where(inside & ~nb, length, 0.0)
            g_e = o.h_edge * exposed_len * t_sheet[li]
            sel = inside & (g_e > 0)
            g_amb_static[nid[li][sel]] += g_e[sel]

    def outer_series(top: bool) -> float:
        rng = range(0, cond_stack_idx[0]) if top else range(cond_stack_idx[-1] + 1, len(layers))
        r = 0.0
        for si in rng:
            m = db[layers[si].material]
            assert m.k_through is not None
            r += layers[si].thickness / m.k_through
        return r

    def outer_emissivity(top: bool) -> float:
        explicit = o.emissivity_top if top else o.emissivity_bottom
        if explicit is not None:
            return explicit
        si = 0 if top else len(layers) - 1
        e = db[layers[si].material].emissivity
        return e if e is not None else 0.0

    faces: list[_Face] = []
    face_labels = ["default"]
    lumped: dict[str, BoolArray] = {}
    label_maps: list[IntArray] = []
    for top in (True, False):
        li = 0 if top else n_l - 1
        nodes = nid[li][inside]
        faces.append(
            _Face(
                nodes=nodes,
                area=a_cell,
                r_series=kz_half[li][inside] + outer_series(top),
                h=np.full(n_in, o.h_top if top else o.h_bottom),
                ambient=np.full(n_in, t_amb),
                emissivity=np.full(n_in, outer_emissivity(top) if o.radiation else 0.0),
                label=np.zeros(n_in, dtype=np.int64),
            )
        )
        label_maps.append(np.full(grid.shape, -1, dtype=np.int64))
        label_maps[-1][inside] = np.arange(n_in)

    def face_of(side: Side) -> tuple[_Face, int, IntArray]:
        idx = 0 if side is Side.TOP else 1
        return faces[idx], (0 if idx == 0 else n_l - 1), label_maps[idx]

    dirichlet: dict[int, float] = {}
    for tb in board.thermal_boundaries:
        if tb.component is not None:
            continue
        face, li, lmap = face_of(tb.side)
        sel = grid.region_mask(tb.region)
        if not sel.any():
            raise SolverError(f"thermal boundary {tb.name}: region covers no board cell")
        face_labels.append(tb.name)
        lab = len(face_labels) - 1
        if tb.kind is ThermalBoundaryKind.FIXED_TEMPERATURE:
            assert tb.temperature is not None
            for n in nid[li][sel]:
                dirichlet[int(n)] = tb.temperature
            face.label[lmap[sel]] = lab
        else:
            area = float(sel.sum()) * a_cell
            h = tb.h if tb.h is not None else 1.0 / (float(tb.resistance or 0.0) * area)
            face.h[lmap[sel]] = h
            face.emissivity[lmap[sel]] = 0.0
            face.ambient[lmap[sel]] = tb.ambient if tb.ambient is not None else t_amb
            face.label[lmap[sel]] = lab

    power = np.zeros(n_sheet + len(board.components))
    junctions: list[_Junction] = []
    hs_by_comp = {tb.component: tb for tb in board.thermal_boundaries if tb.component}
    n_nodes = n_sheet
    p_comp = 0.0
    for c in board.components:
        face, li, lmap = face_of(c.side)
        sel = grid.region_mask(c.footprint)
        lumped[c.ref] = sel
        p_comp += c.power
        hs = hs_by_comp.get(c.ref)
        if c.theta_jb is None:
            if hs is not None:
                warnings.append(f"{c.ref}: heat sink ignored (needs theta_jb two-resistor model)")
            cells = nid[li][sel]
            np.add.at(power, cells, c.power / cells.size)
            continue
        node = n_nodes
        n_nodes += 1
        sheet_nodes = nid[li][sel]
        g_board = np.full(sheet_nodes.size, (1.0 / c.theta_jb) / sheet_nodes.size)
        area = float(sel.sum()) * a_cell
        theta_jc = c.theta_jc if c.theta_jc is not None else 0.0
        if hs is not None:
            r_ca = hs.resistance if hs.resistance is not None else 1.0 / (float(hs.h or 0.0) * area)
            amb = hs.ambient if hs.ambient is not None else t_amb
        else:
            h_face = o.h_top if c.side is Side.TOP else o.h_bottom
            r_ca = 1.0 / (h_face * area) if h_face > 0 else math.inf
            amb = t_amb
            if c.theta_jc is None:
                r_ca = math.inf
        g_amb = 0.0 if math.isinf(r_ca + theta_jc) else 1.0 / (r_ca + theta_jc)
        face.h[lmap[sel]] = 0.0
        face.emissivity[lmap[sel]] = 0.0
        add(np.full(sheet_nodes.size, node, dtype=np.int64), sheet_nodes, g_board)
        g_amb_static[node] += g_amb
        t_amb_static[node] = amb
        power[node] += c.power
        junctions.append(_Junction(c, node, sheet_nodes, g_board, g_amb, amb))

    g_amb_static = g_amb_static[:n_nodes]
    t_amb_static = t_amb_static[:n_nodes]
    power = power[:n_nodes]

    p_joule = 0.0
    joule = _joule_field(solver, grid)
    if joule is not None:
        jl = np.where(inside[None, :, :], joule, 0.0)
        lost = float(np.sum(joule) - np.sum(jl))
        if lost > 1e-12 * max(float(np.sum(joule)), 1.0):
            warnings.append(f"{lost:.3g} W of Joule heat lies outside the board outline")
        in3 = np.broadcast_to(inside, jl.shape)
        np.add.at(power, nid[in3], jl[in3])
        p_joule = float(np.sum(jl))

    k = sp.coo_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n_nodes, n_nodes),
    ).tocsr()
    capacity = np.zeros(n_nodes)
    capacity[:n_sheet] = np.concatenate([cap[li][inside] for li in range(n_l)])

    for f in faces:
        f.r_series = np.asarray(f.r_series, dtype=np.float64)

    sysm = ThermalSystem(
        grid=grid,
        nid=nid,
        n_sheet=n_sheet,
        n_nodes=n_nodes,
        k_static=sp.csr_matrix(k),
        g_amb_static=g_amb_static,
        t_amb_static=t_amb_static,
        faces=faces,
        capacity=capacity,
        power=power,
        dirichlet=dirichlet,
        junctions=junctions,
        lumped=lumped,
        face_labels=face_labels,
        p_components=p_comp,
        p_joule=p_joule,
        warnings=warnings,
    )
    _check_grounded(sysm)
    return sysm


def _joule_field(solver: ThermalSolver, grid: Grid) -> FloatArray | None:
    o = solver.opts
    shape = (len(grid.layers), grid.ny, grid.nx)
    if o.joule_field is not None:
        arr = np.asarray(o.joule_field, dtype=np.float64)
        if arr.shape != shape:
            raise SolverError(f"thermal: joule_field shape {arr.shape} != grid shape {shape}")
        return arr
    if not o.joule:
        return None
    up = solver.ctx.upstream.get("dc_ir")
    if up is None:
        return None
    arr = np.asarray(up.meta.get("joule_cell"), dtype=np.float64)
    if arr.shape != shape:
        raise SolverError(
            "thermal: dc_ir result was computed on a different mesh; run both with the "
            "runner's shared mesh"
        )
    return arr


def _check_grounded(s: ThermalSystem) -> None:
    has_ambient = bool(np.any(s.g_amb_static > 0.0)) or bool(s.dirichlet)
    for f in s.faces:
        if np.any((f.h > 0.0) | (f.emissivity > 0.0)):
            has_ambient = True
    if not has_ambient:
        raise SolverError(
            "thermal: no path to ambient (all h, emissivity and fixed temperatures are zero)"
        )


def _face_conductance(f: _Face, t_node: FloatArray | None) -> tuple[FloatArray, FloatArray]:
    """Per-cell (G_face, h_rad) for the current temperature estimate."""
    if t_node is None:
        ts = f.ambient
    else:
        tn = t_node[f.nodes]
        h0 = f.h
        ts = tn.copy()
        for _ in range(3):
            hr = f.emissivity * SIGMA_SB * (ts**2 + f.ambient**2) * (ts + f.ambient)
            he = h0 + hr
            with np.errstate(divide="ignore", invalid="ignore"):
                frac = np.where(he > 0, (1.0 / he) / (f.r_series + 1.0 / he), 1.0)
            ts = f.ambient + (tn - f.ambient) * frac
    hr = f.emissivity * SIGMA_SB * (ts**2 + f.ambient**2) * (ts + f.ambient)
    he = f.h + hr
    with np.errstate(divide="ignore"):
        g = np.where(he > 0, f.area / (f.r_series + 1.0 / np.where(he > 0, he, 1.0)), 0.0)
    return g, hr


def _system_matrix(
    s: ThermalSystem, t_node: FloatArray | None
) -> tuple[sp.csr_matrix, FloatArray, list[FloatArray]]:
    g_amb = s.g_amb_static.copy()
    rhs_amb = s.g_amb_static * s.t_amb_static
    face_g: list[FloatArray] = []
    for f in s.faces:
        g, _ = _face_conductance(f, t_node)
        np.add.at(g_amb, f.nodes, g)
        np.add.at(rhs_amb, f.nodes, g * f.ambient)
        face_g.append(g)
    k = sp.csr_matrix(s.k_static + sp.diags(g_amb))
    return k, rhs_amb, face_g


def _apply_dirichlet(
    k: sp.csr_matrix, rhs: FloatArray, s: ThermalSystem
) -> tuple[sp.csc_matrix, FloatArray, IntArray, IntArray, FloatArray]:
    n = s.n_nodes
    d_idx = np.fromiter(s.dirichlet, dtype=np.int64)
    d_val = np.fromiter(s.dirichlet.values(), dtype=np.float64)
    free = np.ones(n, dtype=np.bool_)
    free[d_idx] = False
    f_idx = np.nonzero(free)[0]
    kff = sp.csc_matrix(k[f_idx][:, f_idx])
    r = rhs[f_idx] - (k[f_idx][:, d_idx] @ d_val if d_idx.size else 0.0)
    return kff, np.asarray(r, dtype=np.float64), f_idx, d_idx, d_val


def _radiating(s: ThermalSystem) -> bool:
    return any(bool(np.any(f.emissivity > 0.0)) for f in s.faces)


class _Factor:
    """Sparse LU of a reference matrix, reused as a preconditioner.

    Radiation only changes the diagonal (h_rad) between Picard iterations or time
    steps, so CG preconditioned with the LU of an earlier matrix converges in a
    few iterations, far cheaper than re-factorising. The matrix is SPD, so a
    symmetric fill-reducing ordering (minimum degree on AᵀA+A) is used.
    """

    def __init__(self, a: sp.csc_matrix) -> None:
        self.lu = splu(a, permc_spec="MMD_AT_PLUS_A")
        n = a.shape[0]
        self.m = LinearOperator((n, n), matvec=self.lu.solve, dtype=np.float64)

    def solve(
        self, a: sp.csc_matrix, r: FloatArray, x0: FloatArray | None, exact: bool
    ) -> FloatArray:
        if exact or x0 is None:
            return np.asarray(self.lu.solve(r), dtype=np.float64)
        x, info = cg(a, r, x0=x0, rtol=1e-13, atol=0.0, maxiter=200, M=self.m)
        if info != 0:
            return np.asarray(splu(a, permc_spec="MMD_AT_PLUS_A").solve(r), dtype=np.float64)
        return np.asarray(x, dtype=np.float64)


def _face_flux(f: _Face, tn: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Exact per-cell face heat flow q [W] and its derivative dq/dT_node.

    Surface balance (per area): (T_n − T_s)/R_s = h(T_s − T∞) + εσ(T_s⁴ − T∞⁴) ≡ f(T_s),
    solved for T_s by scalar Newton. Then q = A·f(T_s) and, by implicit
    differentiation, dq/dT_n = A / (R_s + 1/f'(T_s)),  f' = h + 4εσT_s³.
    """
    amb, eps, h, rs = f.ambient, f.emissivity * SIGMA_SB, f.h, f.r_series
    ts = tn.copy()
    for _ in range(50):
        fv = h * (ts - amb) + eps * (ts**4 - amb**4)
        fp = h + 4.0 * eps * ts**3
        step = ((tn - ts) - rs * fv) / (1.0 + rs * fp)
        ts = ts + step
        if float(np.max(np.abs(step))) < 1e-12:
            break
    fv = h * (ts - amb) + eps * (ts**4 - amb**4)
    fp = h + 4.0 * eps * ts**3
    with np.errstate(divide="ignore"):
        dq = np.where(fp > 0, f.area / (rs + 1.0 / np.where(fp > 0, fp, 1.0)), 0.0)
    return f.area * fv, dq


def _solve_steady(
    s: ThermalSystem, o: ThermalOptions, scale: float = 1.0
) -> tuple[FloatArray, int]:
    """Linear solve; with radiation, Newton iteration on the exact face law.

    The start value is the linear solve with h_rad evaluated at ambient. Newton
    only changes the matrix diagonal, so every step reuses the first sparse LU
    as a CG preconditioner (see :class:`_Factor`).
    """
    k, rhs_amb, _ = _system_matrix(s, None)
    kff, r, f_idx, d_idx, d_val = _apply_dirichlet(k, rhs_amb + scale * s.power, s)
    factor = _Factor(kff)
    t = np.empty(s.n_nodes)
    t[d_idx] = d_val
    t[f_idx] = factor.solve(kff, r, None, True)
    if not np.all(np.isfinite(t)):
        raise SolverError("thermal: linear solve produced non-finite temperatures")
    if not _radiating(s):
        return t, 1
    base = sp.csr_matrix(s.k_static + sp.diags(s.g_amb_static))
    src = s.g_amb_static * s.t_amb_static + scale * s.power
    for it in range(2, o.picard_maxiter + 2):
        resid = base @ t - src
        diag = np.zeros(s.n_nodes)
        for f in s.faces:
            q, dq = _face_flux(f, t[f.nodes])
            np.add.at(resid, f.nodes, q)
            np.add.at(diag, f.nodes, dq)
        jac = sp.csr_matrix(base + sp.diags(diag))
        j_ff = sp.csc_matrix(jac[f_idx][:, f_idx])
        delta = factor.solve(j_ff, -resid[f_idx], np.zeros(f_idx.size), False)
        t[f_idx] += delta
        if not np.all(np.isfinite(t)):
            raise SolverError("thermal: Newton iteration produced non-finite temperatures")
        if float(np.max(np.abs(delta))) < o.picard_tol:
            return t, it
    raise SolverError(
        f"thermal: radiation Newton iteration did not converge in {o.picard_maxiter} steps"
    )


def _solve_transient(
    s: ThermalSystem, o: ThermalOptions, tr: TransientOptions
) -> tuple[FloatArray, dict[str, list[float]]]:
    n_steps = max(math.ceil(tr.t_end / tr.dt - 1e-9), 1)
    dt = tr.t_end / n_steps
    t_amb = celsius_to_kelvin(o.ambient)
    if tr.initial == "steady":
        t, _ = _solve_steady(s, o, tr.scale(0.0))
    elif tr.initial == "ambient":
        t = np.full(s.n_nodes, t_amb)
    else:
        t = np.full(s.n_nodes, celsius_to_kelvin(float(tr.initial)))
    for n, v in s.dirichlet.items():
        t[n] = v
    hist: dict[str, list[float]] = {"time": [0.0], "t_max": [float(np.max(t[: s.n_sheet]))]}
    for j in s.junctions:
        hist[f"{j.comp.ref}.tj"] = [float(t[j.node])]
    c_dt = s.capacity / dt
    radiating = _radiating(s)
    factor: _Factor | None = None
    kff: sp.csc_matrix | None = None
    for step in range(1, n_steps + 1):
        time = step * dt
        if factor is None or radiating:
            k, rhs_amb, _ = _system_matrix(s, t if radiating else None)
            a = sp.csr_matrix(k + sp.diags(c_dt))
            kff, _, f_idx, d_idx, d_val = _apply_dirichlet(a, np.zeros(s.n_nodes), s)
            kfd = a[f_idx][:, d_idx]
        assert kff is not None
        first = factor is None
        if factor is None:
            factor = _Factor(kff)
        rhs = rhs_amb + tr.scale(time) * s.power + c_dt * t
        r = rhs[f_idx] - (kfd @ d_val if d_idx.size else 0.0)
        t_new = np.empty(s.n_nodes)
        t_new[d_idx] = d_val
        t_new[f_idx] = factor.solve(
            kff, np.asarray(r, dtype=np.float64), t[f_idx], first or not radiating
        )
        t = t_new
        hist["time"].append(time)
        hist["t_max"].append(float(np.max(t[: s.n_sheet])))
        for j in s.junctions:
            hist[f"{j.comp.ref}.tj"].append(float(t[j.node]))
    if not np.all(np.isfinite(t)):
        raise SolverError("thermal: transient produced non-finite temperatures")
    return t, hist


def heat_flows(s: ThermalSystem, t: FloatArray, scale: float = 1.0) -> dict[str, float]:
    """Heat leaving the board per path [W] (positive = out of the board).

    Faces include clamped cells (their own convection). ``fixed_temperature`` is
    the heat absorbed by the clamps (negative if a clamp supplies heat). In steady
    state the values sum to the injected power.
    """
    out: dict[str, float] = {}
    for f, nm in zip(s.faces, ("top", "bottom"), strict=True):
        q, _ = _face_flux(f, t[f.nodes])
        for lab_i, lab in enumerate(s.face_labels):
            sel = f.label == lab_i
            if sel.any():
                key = nm if lab == "default" else lab
                out[key] = out.get(key, 0.0) + float(q[sel].sum())
    out["edges+packages"] = float(np.sum(s.g_amb_static * (t - s.t_amb_static)))
    if s.dirichlet:
        resid = s.k_static @ t + s.g_amb_static * (t - s.t_amb_static) - scale * s.power
        for f in s.faces:
            q, _ = _face_flux(f, t[f.nodes])
            np.add.at(resid, f.nodes, q)
        d_idx = np.fromiter(s.dirichlet, dtype=np.int64)
        out["fixed_temperature"] = -float(np.sum(resid[d_idx]))
    return out


def _postprocess(solver: ThermalSolver) -> ResultSet:
    s, t, grid, board = solver.system, solver.t_node, solver.system.grid, solver.ctx.board
    rs = ResultSet(solver.name)
    n_l = len(grid.layers)
    temp = np.full((n_l, grid.ny, grid.nx), np.nan)
    for li in range(n_l):
        temp[li][grid.inside] = t[s.nid[li][grid.inside]]
    for li, lname in enumerate(grid.layers):
        rs.fields.append(FieldData("temperature", "K", lname, temp[li], grid.extent))
        rs.scalars[f"{lname}.t_max"] = float(np.nanmax(temp[li]))
    rs.scalars["t_max"] = float(np.nanmax(temp))
    rs.scalars["t_min"] = float(np.nanmin(temp))
    rs.scalars["power_components"] = s.p_components
    rs.scalars["power_joule"] = s.p_joule

    scale = 1.0
    if solver.opts.mode == "transient" and solver.opts.transient is not None:
        scale = solver.opts.transient.scale(solver.opts.transient.t_end)
    flows = heat_flows(s, t, scale)
    p_in = scale * float(np.sum(s.power))
    total_out = float(sum(flows.values()))
    if solver.opts.mode == "steady":
        ref = max(p_in, float(sum(abs(q) for q in flows.values())), 1e-30)
        rs.scalars["heat_balance_error"] = (total_out - p_in) / ref
    for key, q in flows.items():
        rs.scalars[f"heat_out.{key}"] = q

    crit = board.criteria
    comp_rows: list[dict[str, Any]] = []
    j_by_ref = {j.comp.ref: j for j in s.junctions}
    hist = solver.history
    for c in board.components:
        sel = s.lumped[c.ref]
        li = 0 if c.side is Side.TOP else n_l - 1
        t_board = float(np.nanmax(temp[li][sel]))
        model = "two_resistor" if c.ref in j_by_ref else "board"
        tj = float(t[j_by_ref[c.ref].node]) if c.ref in j_by_ref else t_board
        if hist and f"{c.ref}.tj" in hist:
            tj_peak = max(hist[f"{c.ref}.tj"])
        elif hist:
            tj_peak = max(tj, float(np.nanmax(temp[li][sel])))
        else:
            tj_peak = tj
        limit = c.effective_tj_max(crit.tj_max_default)
        ok = tj_peak <= limit
        comp_rows.append(
            {
                "ref": c.ref,
                "power": c.power,
                "model": model,
                "tj": tj,
                "tj_peak": tj_peak,
                "t_board": t_board,
                "tj_max": limit,
                "margin": limit - tj_peak,
                "passed": ok,
            }
        )
        rs.scalars[f"{c.ref}.tj"] = tj
        rs.scalars[f"{c.ref}.t_board"] = t_board
        if not ok:
            cx, cy = (float(v) for v in c.footprint.outer.mean(axis=0))
            rs.violations.append(
                Violation(
                    check="temperature",
                    subject=c.ref,
                    value=kelvin_to_celsius(tj_peak),
                    limit=kelvin_to_celsius(limit),
                    unit="°C",
                    location=(cx, cy),
                    message=(
                        f"{c.ref}: Tj {kelvin_to_celsius(tj_peak):.1f} °C > "
                        f"Tj_max {kelvin_to_celsius(limit):.0f} °C"
                    ),
                )
            )

    for w in s.warnings:
        rs.violations.append(Violation("model", "thermal", 0.0, 0.0, "", Severity.INFO, None, w))

    rs.meta.update(
        grid=grid,
        system=s,
        t_node=t,
        temperature=temp,
        components=comp_rows,
        history=hist,
        iterations=solver.iterations,
        heat_out=flows,
        warnings=list(s.warnings),
    )
    return rs
