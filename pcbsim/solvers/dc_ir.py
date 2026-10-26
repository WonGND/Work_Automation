"""Multi-layer DC IR-drop solver (2.5D finite volume + 1D via elements).

Governing equation
------------------
Each conductor layer is a thin sheet of thickness ``t`` and conductivity ``σ``.
Charge conservation with Ohm's law gives the 2D Poisson equation::

    ∇·(σ t ∇V) = −i_s          (i_s: injected current per unit area)

Discretisation (cell-centred finite volume on :class:`~pcbsim.mesh.Grid`)
-------------------------------------------------------------------------
The conductance between two neighbouring copper cells *i, j* of the same net
on the same layer (x-direction; y analogous with ``dx ↔ dy``)::

    G_ij = t·Δy / (Δx/2 · ρ_i + Δx/2 · ρ_j),       ρ = 1/σ(T)

i.e. two half-cells in series (harmonic mean of σ). This yields the exact
uniform-sheet result ``R = R_s · L / W`` with ``R_s = ρ / t``.

Vias are 1D resistors between the cells they pierce on every conductor layer
of their span that carries copper of the via's net::

    G_via = (σ_Cu · A_barrel + σ_fill · A_fill) / L
    A_barrel = π/4 · (d² − (d − 2 t_p)²),     L = |z_c(l_a) − z_c(l_b)|

Ports (boundary conditions)
---------------------------
* Voltage source (VRM): all its cells are merged into one node with Dirichlet
  ``V = V_set``. The merged region is a perfect conductor (ρ = 0), so a link
  from it to a neighbour is only the neighbour's half-cell.
* Current sink, ``uniform``: ``−I/n`` is drawn from each of its ``n`` cells.
* Current sink, ``equipotential``: cells merged into one node drawing ``−I``.
* ``reference_net``: the return terminal of the port on the reference net
  (Dirichlet 0 V for sources, ``+I`` injection for sinks).

Temperature dependence
----------------------
``ρ(T) = ρ₀ [1 + α (T − T_ref)]`` per cell (option ``temperature`` or a full
``temperature_field`` of shape ``(n_layers, ny, nx)`` in K, used by the
electro-thermal ``coupled`` solver).

Post-processing
---------------
* Link current ``I = G ΔV``; Joule power ``P = G ΔV²`` is split between the two
  end cells in proportion to their half-cell resistances.
* Cell current density: average of the signed face currents on the two faces
  of each axis (a missing face — copper edge — contributes zero normal flux),
  ``J = √(J_x² + J_y²)``. At re-entrant (270°) copper corners the exact J is
  singular (∝ r^(−1/3)), so the peak cell value there grows slowly with mesh
  refinement; treat corner hot-spots as "needs a radius / wider neck".
* IR drop at a sink: ``V_seen = min V_net − max V_ref`` over the sink cells
  (worst pin pair); ``drop % = (V_nom − V_seen)/V_nom · 100``.
* Energy balance: ``Σ G ΔV² = Σ V_src I_src + Σ V_node b_node`` (checked in tests).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import cg, spsolve

from pcbsim.errors import MaterialError, SolverError
from pcbsim.mesh import Grid, build_grid
from pcbsim.model import Port, PortKind, SinkDistribution
from pcbsim.solvers.base import FieldData, ResultSet, Severity, Solver, Violation, register
from pcbsim.standards import allowed_current_density, ipc2152_current
from pcbsim.units import celsius_to_kelvin

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


class DcIrOptions(BaseModel):
    """Options of the ``dc_ir`` solver (``analysis.options.dc_ir`` in the config)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    temperature: float | None = Field(
        default=None, description="uniform conductor temperature in °C (default: material T_ref)"
    )
    temperature_field: Any = Field(default=None, description="(n_layers, ny, nx) array in K")
    cell: float | None = Field(
        default=None, gt=0.0, description="grid cell [m] if no mesh is supplied by the runner"
    )
    method: str = "direct"
    cg_rtol: float = Field(default=1e-10, gt=0.0)
    cg_maxiter: int = Field(default=20_000, ge=1)
    via_check: bool = True

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in ("direct", "cg"):
            raise ValueError("method must be 'direct' or 'cg'")
        return v


@dataclass(slots=True)
class _Group:
    """A set of cells merged into one node (equipotential)."""

    mask: BoolArray
    label: str
    voltage: float | None = None
    current: float = 0.0


@dataclass(slots=True)
class _PortCells:
    port: Port
    net_cells: BoolArray
    ref_cells: BoolArray | None
    ref_layer: str | None


@dataclass(slots=True)
class _ViaLink:
    via_index: int
    ci: int
    cj: int
    g: float


def _via_footprint(
    grid: Grid, layer_idx: int, net_idx: int, x: float, y: float, r: float
) -> IntArray:
    """(iy, ix) pairs of same-net cells whose centre lies within the barrel radius.

    Always includes the cell containing (x, y) if it carries the net.
    """
    iy0, ix0 = grid.cell_of(x, y)
    ky = math.ceil(r / grid.dy) + 1
    kx = math.ceil(r / grid.dx) + 1
    ys = np.arange(max(iy0 - ky, 0), min(iy0 + ky + 1, grid.ny))
    xs = np.arange(max(ix0 - kx, 0), min(ix0 + kx + 1, grid.nx))
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    cx = grid.x0 + (xx + 0.5) * grid.dx
    cy = grid.y0 + (yy + 0.5) * grid.dy
    sel = (np.hypot(cx - x, cy - y) <= r) & (grid.net_map[layer_idx][yy, xx] == net_idx)
    sel |= (yy == iy0) & (xx == ix0) & (grid.net_map[layer_idx, iy0, ix0] == net_idx)
    return np.column_stack([yy[sel], xx[sel]]).astype(np.int64)


@dataclass(slots=True)
class DcIrSystem:
    """Assembled discrete system (exposed for tests and the coupled solver)."""

    grid: Grid
    cid: NDArray[np.int64]
    cell_index: tuple[IntArray, IntArray, IntArray]
    rho: FloatArray
    labels: IntArray
    n_nodes: int
    link_i: IntArray
    link_j: IntArray
    link_g: FloatArray
    link_share_i: FloatArray
    link_axis: NDArray[np.int8]
    link_layer: IntArray
    via_links: list[_ViaLink]
    dirichlet: dict[int, float]
    b: FloatArray
    floating: BoolArray
    ports: list[_PortCells]
    warnings: list[str] = field(default_factory=list)


@register("dc_ir")
class DcIrSolver(Solver):
    description = "multi-layer PDN IR drop (2.5D finite volume + via resistors)"

    def validate_options(self) -> None:
        try:
            self.opts = DcIrOptions.model_validate(self.options)
        except ValidationError as exc:
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise SolverError(f"dc_ir options: {msgs}") from None

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
        self.v_node = _solve(self.system, self.opts)
        self._phase = "solved"

    def results(self) -> ResultSet:
        self._require_phase("solved")
        return _postprocess(self, self.system, self.v_node)


def _temperature_cells(solver: DcIrSolver, grid: Grid) -> FloatArray | None:
    o = solver.opts
    shape = (len(grid.layers), grid.ny, grid.nx)
    if o.temperature_field is not None:
        tf = np.asarray(o.temperature_field, dtype=np.float64)
        if tf.shape != shape:
            raise SolverError(f"dc_ir: temperature_field shape {tf.shape} != grid shape {shape}")
        return tf
    if o.temperature is not None:
        return np.full(shape, celsius_to_kelvin(o.temperature))
    return None


def _resistivity(solver: DcIrSolver, grid: Grid, temp: FloatArray | None) -> FloatArray:
    board, db = solver.ctx.board, solver.ctx.materials
    rho = np.empty((len(grid.layers), grid.ny, grid.nx))
    for li, lname in enumerate(grid.layers):
        m = db[board.stackup.get(lname).material]
        if not m.is_conductor:
            raise SolverError(f"layer {lname}: material {m.name!r} is not a conductor")
        rho0 = m.resistivity()
        if temp is None:
            rho[li] = rho0
            continue
        factor = 1.0 + m.alpha_r * (temp[li] - m.t_ref)
        if np.any(factor <= 0.0):
            raise SolverError(f"layer {lname}: ρ(T) linear model invalid at the given temperature")
        rho[li] = rho0 * factor
    return rho


def _port_cells(solver: DcIrSolver, grid: Grid) -> list[_PortCells]:
    board = solver.ctx.board
    out: list[_PortCells] = []
    for p in board.ports:
        net_cells = np.zeros((len(grid.layers), grid.ny, grid.nx), dtype=np.bool_)
        li = grid.layer_index(p.layer)
        net_cells[li] = grid.region_cells(p.region, p.layer, p.net)
        if not net_cells.any():
            raise SolverError(
                f"port {p.name}: no {p.net} copper on layer {p.layer} under the port region"
            )
        ref_cells: BoolArray | None = None
        ref_layer: str | None = None
        if p.reference_net is not None:
            candidates = (
                [p.reference_layer]
                if p.reference_layer is not None
                else sorted(grid.layers, key=lambda n: abs(grid.layer_index(n) - li))
            )
            for lname in candidates:
                sel = grid.region_cells(p.region, lname, p.reference_net)
                if sel.any():
                    ref_cells = np.zeros_like(net_cells)
                    ref_cells[grid.layer_index(lname)] = sel
                    ref_layer = lname
                    break
            if ref_cells is None:
                where = p.reference_layer or "any conductor layer"
                raise SolverError(
                    f"port {p.name}: no {p.reference_net} copper on {where} under the port region"
                )
        out.append(_PortCells(p, net_cells, ref_cells, ref_layer))
    return out


@dataclass(slots=True)
class _Lateral:
    i: IntArray
    j: IntArray
    r_a: FloatArray
    r_b: FloatArray
    axis: NDArray[np.int8]
    layer: IntArray


def _lateral_links(
    grid: Grid, cid: NDArray[np.int64], rho: FloatArray, solver: DcIrSolver
) -> _Lateral:
    """Half-cell resistances of every same-net neighbour pair on every layer."""
    board = solver.ctx.board
    parts: list[tuple[IntArray, IntArray, FloatArray, FloatArray, int, int]] = []
    nm = grid.net_map
    for l_idx, lname in enumerate(grid.layers):
        t = board.stackup.get(lname).thickness
        for ax, (sl_a, sl_b, along, across) in enumerate(
            (
                ((slice(None), slice(None, -1)), (slice(None), slice(1, None)), grid.dx, grid.dy),
                ((slice(None, -1), slice(None)), (slice(1, None), slice(None)), grid.dy, grid.dx),
            )
        ):
            na, nb = nm[l_idx][sl_a], nm[l_idx][sl_b]
            ok = (na >= 0) & (na == nb)
            if not ok.any():
                continue
            half = (along / 2.0) / (t * across)
            parts.append(
                (
                    cid[l_idx][sl_a][ok],
                    cid[l_idx][sl_b][ok],
                    rho[l_idx][sl_a][ok] * half,
                    rho[l_idx][sl_b][ok] * half,
                    ax,
                    l_idx,
                )
            )
    if not parts:
        e_i = np.zeros(0, np.int64)
        e_f = np.zeros(0)
        return _Lateral(e_i, e_i, e_f, e_f, np.zeros(0, np.int8), e_i)
    return _Lateral(
        i=np.concatenate([p[0] for p in parts]),
        j=np.concatenate([p[1] for p in parts]),
        r_a=np.concatenate([p[2] for p in parts]),
        r_b=np.concatenate([p[3] for p in parts]),
        axis=np.concatenate([np.full(p[0].size, p[4], np.int8) for p in parts]),
        layer=np.concatenate([np.full(p[0].size, p[5], np.int64) for p in parts]),
    )


def _via_links(
    solver: DcIrSolver, grid: Grid, cid: NDArray[np.int64], temp: FloatArray | None
) -> tuple[list[_ViaLink], list[IntArray], list[str]]:
    """Via resistors plus the barrel-footprint cell sets to merge on each layer."""
    board, db = solver.ctx.board, solver.ctx.materials
    links: list[_ViaLink] = []
    footprints: list[IntArray] = []
    warnings: list[str] = []
    cond_names = list(grid.layers)
    for k, v in enumerate(board.vias):
        iy, ix = grid.cell_of(v.x, v.y)
        ni = grid.net_index(v.net)
        a, b = cond_names.index(v.from_layer), cond_names.index(v.to_layer)
        hit = [li for li in range(a, b + 1) if grid.net_map[li, iy, ix] == ni]
        if len(hit) < 2:
            warnings.append(
                f"via {k} ({v.net} @ {v.x * 1e3:.2f},{v.y * 1e3:.2f} mm) touches "
                f"{len(hit)} layer(s) with {v.net} copper — ignored"
            )
            continue
        try:
            m_barrel = db[v.material]
            m_fill = db[v.filler] if (v.filled and v.filler) else None
        except MaterialError as exc:
            raise SolverError(f"via {k}: {exc}") from None
        for li in hit:
            fp = _via_footprint(grid, li, ni, v.x, v.y, 0.5 * v.drill)
            footprints.append(cid[li, fp[:, 0], fp[:, 1]])
        for la, lb in itertools.pairwise(hit):
            length = board.stackup.span(cond_names[la], cond_names[lb])
            t_via = None if temp is None else 0.5 * (temp[la, iy, ix] + temp[lb, iy, ix])
            g = m_barrel.conductivity(t_via) * v.barrel_area / length
            if m_fill is not None and m_fill.is_conductor:
                g += m_fill.conductivity(t_via) * v.fill_area / length
            links.append(_ViaLink(k, int(cid[la, iy, ix]), int(cid[lb, iy, ix]), g))
    return links, footprints, warnings


def _assemble(solver: DcIrSolver, grid: Grid) -> DcIrSystem:
    temp = _temperature_cells(solver, grid)
    rho = _resistivity(solver, grid, temp)
    ports = _port_cells(solver, grid)

    copper = grid.net_map >= 0
    n_cells = int(copper.sum())
    if n_cells == 0:
        raise SolverError("no copper on any conductor layer")
    cid = np.full(copper.shape, -1, dtype=np.int64)
    cid[copper] = np.arange(n_cells)
    cell_index = tuple(np.nonzero(copper))
    assert len(cell_index) == 3

    groups: list[_Group] = []
    b_cell = np.zeros(n_cells)
    for pc in ports:
        p = pc.port
        if p.kind is PortKind.VOLTAGE_SOURCE:
            groups.append(_Group(pc.net_cells, p.name, voltage=p.value))
            if pc.ref_cells is not None:
                groups.append(_Group(pc.ref_cells, f"{p.name}(ref)", voltage=0.0))
        elif p.distribution is SinkDistribution.EQUIPOTENTIAL:
            groups.append(_Group(pc.net_cells, p.name, current=-p.value))
            if pc.ref_cells is not None:
                groups.append(_Group(pc.ref_cells, f"{p.name}(ref)", current=+p.value))
        else:
            ids = cid[pc.net_cells]
            b_cell[ids] -= p.value / ids.size
            if pc.ref_cells is not None:
                rid = cid[pc.ref_cells]
                b_cell[rid] += p.value / rid.size

    group_of = np.full(n_cells, -1, dtype=np.int64)
    for gi, g in enumerate(groups):
        ids = cid[g.mask]
        clash = group_of[ids] >= 0
        if clash.any():
            other = groups[int(group_of[ids][clash][0])].label
            raise SolverError(f"port regions {other!r} and {g.label!r} overlap")
        group_of[ids] = gi

    lat = _lateral_links(grid, cid, rho, solver)
    gi_a, gi_b = group_of[lat.i], group_of[lat.j]
    same_group = (gi_a >= 0) & (gi_a == gi_b)
    r_a = np.where((gi_a >= 0) & (gi_b < 0), 0.0, lat.r_a)
    r_b = np.where((gi_b >= 0) & (gi_a < 0), 0.0, lat.r_b)

    via_links, via_fp, warnings = _via_links(solver, grid, cid, temp)

    merge_i = [cid[g.mask] for g in groups] + via_fp
    merge_j = [np.full(ids.size, ids[0], dtype=np.int64) for ids in merge_i]
    mi = np.concatenate([*merge_i, np.zeros(0, np.int64)])
    mj = np.concatenate([*merge_j, np.zeros(0, np.int64)])
    merge_graph = sp.coo_matrix((np.ones(mi.size), (mi, mj)), shape=(n_cells, n_cells))
    n_nodes, labels_raw = connected_components(merge_graph, directed=False)
    labels = np.asarray(labels_raw, dtype=np.int64)

    keep = ~same_group & (labels[lat.i] != labels[lat.j])
    r_tot = (r_a + r_b)[keep]
    link_i, link_j = lat.i[keep], lat.j[keep]
    link_g = 1.0 / r_tot
    link_share = r_a[keep] / r_tot
    link_axis, link_layer = lat.axis[keep], lat.layer[keep]

    dirichlet: dict[int, float] = {}
    owner: dict[int, str] = {}
    b = np.zeros(n_nodes)
    np.add.at(b, labels, b_cell)
    for g in groups:
        node = int(labels[cid[g.mask]][0])
        if g.voltage is not None:
            if node in dirichlet and not math.isclose(dirichlet[node], g.voltage, abs_tol=1e-12):
                raise SolverError(
                    f"voltage sources {owner[node]!r} and {g.label!r} are shorted together "
                    f"({dirichlet[node]:g} V vs {g.voltage:g} V)"
                )
            dirichlet[node] = g.voltage
            owner[node] = g.label
        b[node] += g.current

    all_i = np.concatenate([labels[link_i], np.array([labels[v.ci] for v in via_links], np.int64)])
    all_j = np.concatenate([labels[link_j], np.array([labels[v.cj] for v in via_links], np.int64)])
    graph = sp.coo_matrix((np.ones(all_i.size), (all_i, all_j)), shape=(n_nodes, n_nodes))
    n_comp, comp_raw = connected_components(graph, directed=False)
    comp = np.asarray(comp_raw, dtype=np.int64)
    has_dir = np.zeros(n_comp, dtype=np.bool_)
    if dirichlet:
        has_dir[comp[np.fromiter(dirichlet, dtype=np.int64)]] = True
    floating = ~has_dir[comp]
    loaded = np.zeros(n_comp, dtype=np.bool_)
    np.logical_or.at(loaded, comp, np.abs(b) > 0.0)
    bad = loaded & ~has_dir
    if bad.any():
        names = []
        for pc in ports:
            if pc.port.kind is not PortKind.CURRENT_SINK:
                continue
            for cells, suffix in ((pc.net_cells, ""), (pc.ref_cells, " (return)")):
                if cells is not None and bad[comp[labels[cid[cells]]]].any():
                    names.append(pc.port.name + suffix)
        raise SolverError(
            "current sink(s) not connected to any voltage source: "
            + ", ".join(sorted(set(names)) or ["?"])
        )
    if floating.any():
        n_float = int(floating[labels].sum())
        warnings.append(f"{n_float} copper cells are floating (no source) — V undefined there")

    return DcIrSystem(
        grid=grid,
        cid=cid,
        cell_index=(cell_index[0], cell_index[1], cell_index[2]),
        rho=rho,
        labels=labels,
        n_nodes=n_nodes,
        link_i=link_i,
        link_j=link_j,
        link_g=link_g,
        link_share_i=link_share,
        link_axis=link_axis,
        link_layer=link_layer,
        via_links=via_links,
        dirichlet=dirichlet,
        b=b,
        floating=floating,
        ports=ports,
        warnings=warnings,
    )


def stiffness(system: DcIrSystem) -> sp.csr_matrix:
    """Node-level conductance matrix K (n_nodes × n_nodes)."""
    lab = system.labels
    vi = np.array([lab[v.ci] for v in system.via_links], dtype=np.int64)
    vj = np.array([lab[v.cj] for v in system.via_links], dtype=np.int64)
    vg = np.array([v.g for v in system.via_links], dtype=np.float64)
    ia = np.concatenate([lab[system.link_i], vi])
    ib = np.concatenate([lab[system.link_j], vj])
    g = np.concatenate([system.link_g, vg])
    keep = ia != ib
    ia, ib, g = ia[keep], ib[keep], g[keep]
    n = system.n_nodes
    rows = np.concatenate([ia, ib, ia, ib])
    cols = np.concatenate([ia, ib, ib, ia])
    vals = np.concatenate([g, g, -g, -g])
    return sp.csr_matrix(sp.coo_matrix((vals, (rows, cols)), shape=(n, n)))


def _solve(system: DcIrSystem, opts: DcIrOptions) -> FloatArray:
    k = stiffness(system)
    n = system.n_nodes
    v = np.full(n, np.nan)
    d_idx = np.fromiter(system.dirichlet, dtype=np.int64)
    d_val = np.fromiter(system.dirichlet.values(), dtype=np.float64)
    v[d_idx] = d_val
    free_mask = ~system.floating.copy()
    free_mask[d_idx] = False
    f_idx = np.nonzero(free_mask)[0]
    if f_idx.size == 0:
        return v
    kff = k[f_idx][:, f_idx].tocsc()
    rhs = system.b[f_idx] - k[f_idx][:, d_idx] @ d_val
    if opts.method == "direct":
        x = np.asarray(spsolve(kff, rhs), dtype=np.float64)
    else:
        diag = kff.diagonal()
        precond = sp.diags(1.0 / diag)
        x_raw, info = cg(kff, rhs, rtol=opts.cg_rtol, maxiter=opts.cg_maxiter, M=precond)
        if info != 0:
            raise SolverError(f"dc_ir: CG did not converge (info={info})")
        x = np.asarray(x_raw, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        raise SolverError("dc_ir: linear solve produced non-finite values (singular system?)")
    v[f_idx] = x
    return v


@dataclass(slots=True)
class _Fields:
    v: FloatArray
    j: FloatArray
    p_cell: FloatArray


def _fields(system: DcIrSystem, v_node: FloatArray, solver: DcIrSolver) -> _Fields:
    grid = system.grid
    shape = (len(grid.layers), grid.ny, grid.nx)
    lab = system.labels
    v_cell_flat = v_node[lab]
    v = np.full(shape, np.nan)
    v[system.cell_index] = v_cell_flat
    vz = np.nan_to_num(v_cell_flat)

    dv = vz[system.link_i] - vz[system.link_j]
    i_link = system.link_g * dv
    p_link = system.link_g * dv * dv
    p_flat = np.zeros(lab.size)
    np.add.at(p_flat, system.link_i, p_link * system.link_share_i)
    np.add.at(p_flat, system.link_j, p_link * (1.0 - system.link_share_i))
    for vl in system.via_links:
        dvv = vz[vl.ci] - vz[vl.cj]
        pv = vl.g * dvv * dvv
        p_flat[vl.ci] += 0.5 * pv
        p_flat[vl.cj] += 0.5 * pv
    p_cell = np.zeros(shape)
    p_cell[system.cell_index] = p_flat

    board = solver.ctx.board
    l_of = system.cell_index[0]
    iy_of = system.cell_index[1]
    ix_of = system.cell_index[2]
    jx = np.zeros(shape)
    jy = np.zeros(shape)
    for ax, target in ((0, jx), (1, jy)):
        sel = system.link_axis == ax
        if not sel.any():
            continue
        ci, cj, cur = system.link_i[sel], system.link_j[sel], i_link[sel]
        for cells in (ci, cj):
            idx = (l_of[cells], iy_of[cells], ix_of[cells])
            np.add.at(target, idx, 0.5 * cur)
    for li, lname in enumerate(grid.layers):
        t = board.stackup.get(lname).thickness
        jx[li] /= t * grid.dy
        jy[li] /= t * grid.dx
    j = np.hypot(jx, jy)
    j[grid.net_map < 0] = np.nan
    return _Fields(v=v, j=j, p_cell=p_cell)


def _postprocess(solver: DcIrSolver, system: DcIrSystem, v_node: FloatArray) -> ResultSet:
    board = solver.ctx.board
    grid = system.grid
    crit = board.criteria
    flds = _fields(system, v_node, solver)
    rs = ResultSet(solver.name)
    lab, cid = system.labels, system.cid

    k = stiffness(system)
    vz = np.nan_to_num(v_node)
    injected = k @ vz - system.b

    def node_of(mask: BoolArray) -> int:
        return int(lab[cid[mask]][0])

    port_rows: list[dict[str, Any]] = []
    for pc in system.ports:
        p = pc.port
        v_net = flds.v[pc.net_cells]
        v_ref = flds.v[pc.ref_cells] if pc.ref_cells is not None else np.zeros(1)
        row: dict[str, Any] = {
            "name": p.name,
            "kind": p.kind.value,
            "net": p.net,
            "layer": p.layer,
            "reference_net": p.reference_net,
            "reference_layer": pc.ref_layer,
        }
        if p.kind is PortKind.VOLTAGE_SOURCE:
            i_src = float(injected[node_of(pc.net_cells)])
            row.update(voltage=p.value, current=i_src, power=p.value * i_src)
            rs.scalars[f"{p.name}.current"] = i_src
        else:
            v_avg = float(np.mean(v_net) - np.mean(v_ref))
            v_min = float(np.min(v_net) - np.max(v_ref))
            sources = [
                q.value for q in board.ports if q.net == p.net and q.kind is PortKind.VOLTAGE_SOURCE
            ]
            net = board.net(p.net)
            v_nom = net.nominal_voltage or (max(sources) if sources else float("nan"))
            drop_pct = (v_nom - v_min) / v_nom * 100.0 if v_nom > 0 else float("nan")
            r_eff = (v_nom - v_avg) / p.value if p.value > 0 else float("nan")
            ok = not (drop_pct > crit.ir_drop_pct)
            row.update(
                current=p.value,
                v_nominal=v_nom,
                v_avg=v_avg,
                v_min=v_min,
                drop_v=v_nom - v_min,
                drop_pct=drop_pct,
                r_path=r_eff,
                limit_pct=crit.ir_drop_pct,
                passed=ok,
            )
            rs.scalars[f"{p.name}.v_avg"] = v_avg
            rs.scalars[f"{p.name}.v_min"] = v_min
            rs.scalars[f"{p.name}.drop_pct"] = drop_pct
            rs.scalars[f"{p.name}.r_path"] = r_eff
            if not ok:
                _, iy, ix = np.unravel_index(
                    int(np.argmin(np.where(pc.net_cells, flds.v, np.inf))), flds.v.shape
                )
                rs.violations.append(
                    Violation(
                        check="ir_drop",
                        subject=p.name,
                        value=drop_pct,
                        limit=crit.ir_drop_pct,
                        unit="%",
                        location=grid.center_of(int(iy), int(ix)),
                        message=(
                            f"{p.name} sees {v_min:.4f} V (nominal {v_nom:g} V): "
                            f"drop {drop_pct:.2f} % > {crit.ir_drop_pct:g} %"
                        ),
                    )
                )
        port_rows.append(row)

    p_total = float(np.sum(flds.p_cell))
    rs.scalars["joule_power"] = p_total
    for n in board.nets:
        ni = grid.net_index(n.name)
        vals = flds.v[(grid.net_map == ni)]
        vals = vals[np.isfinite(vals)]
        if vals.size:
            rs.scalars[f"{n.name}.v_max"] = float(vals.max())
            rs.scalars[f"{n.name}.v_min"] = float(vals.min())

    _current_density_checks(solver, grid, flds.j, rs)
    via_rows = _via_results(solver, system, vz, rs)

    for li, lname in enumerate(grid.layers):
        ext = grid.extent
        rs.fields.append(FieldData("voltage", "V", lname, flds.v[li], ext))
        rs.fields.append(FieldData("current_density", "A/m²", lname, flds.j[li], ext))
        pd = np.where(grid.net_map[li] >= 0, flds.p_cell[li] / grid.cell_area, np.nan)
        rs.fields.append(FieldData("power_density", "W/m²", lname, pd, ext))

    for w in system.warnings:
        rs.violations.append(Violation("model", "dc_ir", 0.0, 0.0, "", Severity.INFO, None, w))

    rs.meta.update(
        grid=grid,
        system=system,
        v_node=v_node,
        voltage=flds.v,
        current_density=flds.j,
        joule_cell=flds.p_cell,
        ports=port_rows,
        vias=via_rows,
        warnings=list(system.warnings),
        n_unknowns=int(system.n_nodes - len(system.dirichlet)),
    )
    return rs


def _current_density_checks(solver: DcIrSolver, grid: Grid, j: FloatArray, rs: ResultSet) -> None:
    board = solver.ctx.board
    crit = board.criteria
    n = len(grid.layers)
    for li, lname in enumerate(grid.layers):
        t = board.stackup.get(lname).thickness
        internal = 0 < li < n - 1
        limit = crit.current_density_limit or allowed_current_density(
            crit.current_density,
            t,
            crit.current_density_temp_rise,
            internal,
            crit.current_density_ref_width,
        )
        jl = j[li]
        finite = np.isfinite(jl)
        if not finite.any():
            continue
        j_max = float(np.nanmax(jl))
        rs.scalars[f"{lname}.j_max"] = j_max
        if limit is None:
            continue
        rs.scalars[f"{lname}.j_limit"] = limit
        over = finite & (np.nan_to_num(jl) > limit)
        if over.any():
            iy, ix = np.unravel_index(int(np.nanargmax(jl)), grid.shape)
            rs.violations.append(
                Violation(
                    check="current_density",
                    subject=lname,
                    value=j_max * 1e-6,
                    limit=limit * 1e-6,
                    unit="A/mm²",
                    location=grid.center_of(int(iy), int(ix)),
                    message=(
                        f"{lname}: {int(over.sum())} cells exceed {limit * 1e-6:.1f} A/mm² "
                        f"(max {j_max * 1e-6:.1f} A/mm²)"
                    ),
                )
            )


def _via_results(
    solver: DcIrSolver, system: DcIrSystem, vz: FloatArray, rs: ResultSet
) -> list[dict[str, Any]]:
    board = solver.ctx.board
    crit = board.criteria
    lab = system.labels
    per_via: dict[int, float] = {}
    for vl in system.via_links:
        cur = abs(vl.g * float(vz[lab[vl.ci]] - vz[lab[vl.cj]]))
        prev = per_via.get(vl.via_index, 0.0)
        per_via[vl.via_index] = cur if cur > prev else prev
    rows: list[dict[str, Any]] = []
    worst: dict[str, tuple[float, float, int, int]] = {}
    for k, cur in sorted(per_via.items()):
        v = board.vias[k]
        ip = ipc2152_current(
            math.pi * v.drill, v.plating_thickness, crit.current_density_temp_rise, True
        )
        limit = ip if solver.opts.via_check else float("inf")
        ok = cur <= limit
        rows.append(
            {
                "index": k,
                "net": v.net,
                "x": v.x,
                "y": v.y,
                "current": cur,
                "limit": limit,
                "passed": ok,
            }
        )
        if not ok:
            w = worst.get(v.net)
            ratio = cur / limit
            if w is None or ratio > w[0] / w[1]:
                worst[v.net] = (cur, limit, k, (w[3] if w else 0) + 1)
            else:
                worst[v.net] = (w[0], w[1], w[2], w[3] + 1)
    if per_via:
        rs.scalars["via.i_max"] = float(max(per_via.values()))
    for net, (cur, limit, k, count) in worst.items():
        v = board.vias[k]
        rs.violations.append(
            Violation(
                check="via_current",
                subject=f"{net} via {k}",
                value=cur,
                limit=limit,
                unit="A",
                severity=Severity.WARNING,
                location=(v.x, v.y),
                message=(
                    f"{count} {net} via(s) above IPC-2152 barrel limit; "
                    f"worst {cur:.2f} A > {limit:.2f} A"
                ),
            )
        )
    return rows


def summarize_ports(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sink rows only, worst drop first (used by the CLI and reports)."""
    sinks = [r for r in rows if r["kind"] == PortKind.CURRENT_SINK.value]
    return sorted(sinks, key=lambda r: -float(r.get("drop_pct", 0.0)))
