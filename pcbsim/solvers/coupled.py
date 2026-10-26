"""Electro-thermal coupling of ``dc_ir`` and ``thermal`` (Picard / fixed-point iteration).

Physics
-------
Copper resistivity rises with temperature (linear model, §2.1 of ``docs/theory.md``)::

    ρ(T) = ρ₀ [1 + α (T − T_ref)]

and the conduction loss heats the board::

    q = J²ρ = σ |∇V|²     (per cell: P = Σ G ΔV², split over the two half-cells)

so the IR drop and the temperature field depend on each other.

Iteration (the 2.5D fields share one :class:`~pcbsim.mesh.Grid`)
----------------------------------------------------------------
::

    k = 0:  V⁰ = dc_ir(user options)            ← identical to an uncoupled dc_ir run
            T⁰ = thermal(P(V⁰))                  ← identical to an uncoupled thermal run
    k ≥ 1:  Vᵏ = dc_ir(ρ(T̃ᵏ⁻¹))                 per-cell ρ(T), vias at the mean T of their ends
            T* = thermal(P(Vᵏ))                  steady state, warm start, cached LU
            T̃ᵏ = T̃ᵏ⁻¹ + ω (T* − T̃ᵏ⁻¹)            under-relaxation, 0 < ω ≤ 1 (T̃⁰ = T⁰)
    stop when  max|T* − T̃ᵏ⁻¹| < tol_T  and  max|Vᵏ − Vᵏ⁻¹| < tol_V

Convergence
-----------
For a lumped conductor ``R(T) = R₀[1 + α(T − T_ref)]`` carrying a fixed current
``I`` through a thermal resistance ``R_th`` to ambient ``T_a`` the iteration is
``Tᵏ⁺¹ = T_a + K[1 + α(Tᵏ − T_ref)]`` with ``K = R_th I² R₀``. It is a
contraction with ratio ``κ = αK`` and converges to::

    T* = T_a + K [1 + α (T_a − T_ref)] / (1 − αK)

For ``αK ≥ 1`` there is no physical fixed point (thermal runaway): every pass
heats the conductor more than the last. Under-relaxation changes the ratio to
``1 − ω(1 − κ)``; it cannot rescue a runaway, but it damps oscillation when a
voltage-driven load makes κ effectively negative. The solver estimates κ from
successive ΔT and stops with a ``thermal_runaway`` violation when the error
grows for three passes in a row. Sources: the fixed-point (Banach) contraction
argument, e.g. Kelley, *Iterative Methods for Linear and Nonlinear Equations*,
SIAM 1995, ch. 4; the lumped model is the classic resistor self-heating balance.

Regression property: with ``α = 0`` the first pass reproduces V⁰ and T⁰, so
the coupled result equals the uncoupled ``dc_ir`` + ``thermal`` result.

Results
-------
The final ``dc_ir`` and ``thermal`` results merged into one result set (their
scalars, fields, checks and tables), plus ``iterations``, ``converged``,
``delta_t``, ``delta_v``, the uncoupled reference values ``*.uncoupled`` and a
per-pass ``history`` (ΔT, ΔV, T_max, Joule power, worst IR drop).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pcbsim.errors import SolverError
from pcbsim.mesh import Grid, build_grid
from pcbsim.solvers.base import ResultSet, Severity, Solver, SolverContext, Violation, register
from pcbsim.solvers.dc_ir import DcIrSolver
from pcbsim.solvers.thermal import ThermalSolver, set_joule
from pcbsim.units import celsius_to_kelvin

FloatArray = NDArray[np.float64]

_RUNAWAY_PASSES = 3


class CoupledOptions(BaseModel):
    """Options of the ``coupled`` solver (``analysis.options.coupled``)."""

    model_config = ConfigDict(extra="forbid")

    tol_t: float = Field(default=0.01, gt=0.0, description="max |ΔT| between passes [K]")
    tol_v: float = Field(default=1e-5, gt=0.0, description="max |ΔV| between passes [V]")
    max_iter: int = Field(default=50, ge=1)
    relaxation: float = Field(default=1.0, gt=0.0, le=1.0, description="ω, 0 < ω ≤ 1")
    cell: float | None = Field(
        default=None, gt=0.0, description="grid cell [m] if no mesh is supplied by the runner"
    )
    dc_ir: dict[str, Any] = Field(
        default_factory=dict, description="overrides of analysis.options.dc_ir"
    )
    thermal: dict[str, Any] = Field(
        default_factory=dict, description="overrides of analysis.options.thermal"
    )


def _merged(ctx: SolverContext, name: str, override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(ctx.options.get(name, {}))
    out.update(override)
    return out


@register("coupled")
class CoupledSolver(Solver):
    description = "electro-thermal iteration: dc_ir with ρ(T) ⇄ thermal with Joule heat"
    uses = ("dc_ir", "thermal")

    def validate_options(self) -> None:
        try:
            self.opts = CoupledOptions.model_validate(self.options)
        except ValidationError as exc:
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise SolverError(f"coupled options: {msgs}") from None
        self.notes: list[str] = []
        dc = _merged(self.ctx, "dc_ir", self.opts.dc_ir)
        dc.pop("temperature_field", None)
        th = _merged(self.ctx, "thermal", self.opts.thermal)
        if th.get("joule") is False:
            raise SolverError("coupled: thermal option joule: false disables the coupling")
        th.pop("joule_field", None)
        if th.get("mode", "steady") != "steady":
            self.notes.append("thermal mode forced to 'steady' (coupled is a steady-state solve)")
            th["mode"] = "steady"
            th.pop("transient", None)
        self.dc_options, self.th_options = dc, th

    def assemble(self) -> None:
        self._require_phase("setup")
        ctx = self.ctx
        grid = ctx.mesh if isinstance(ctx.mesh, Grid) else None
        if grid is None:
            grid = build_grid(ctx.board, self.opts.cell or 0.5e-3)
        self.grid = grid
        sub = SolverContext(ctx.board, ctx.materials, grid, {}, ctx.options)
        self.dc = DcIrSolver(self.dc_options)
        self.dc.setup(sub)
        self.dc.assemble()
        self.th = ThermalSolver({**self.th_options, "joule": False})
        self.th.setup(sub)
        self.th.assemble()
        self._phase = "assembled"

    def solve(self) -> None:
        self._require_phase("assembled")
        o, grid = self.opts, self.grid
        t_amb = celsius_to_kelvin(self.th.opts.ambient)
        copper = grid.net_map >= 0
        inside = np.broadcast_to(grid.inside, copper.shape)

        self.dc.solve()
        dc_rs = self.dc.results()
        set_joule(self.th.system, np.asarray(dc_rs.meta["joule_cell"], dtype=np.float64))
        self.th.solve()
        th_rs = self.th.results()
        self.uncoupled = (dc_rs, th_rs)

        def temp_field(rs: ResultSet) -> FloatArray:
            t = np.asarray(rs.meta["temperature"], dtype=np.float64)
            return np.where(np.isfinite(t), t, t_amb)

        v_prev = np.asarray(dc_rs.meta["voltage"], dtype=np.float64)
        t_relax = temp_field(th_rs)
        hist: dict[str, list[float]] = {
            "iteration": [0.0],
            "delta_t": [math.nan],
            "delta_v": [math.nan],
            "t_max": [th_rs.scalars["t_max"]],
            "joule_power": [dc_rs.scalars["joule_power"]],
            "drop_pct_max": [_worst_drop(dc_rs)],
        }
        converged = False
        runaway = False
        growing = 0
        d_t = d_v = math.inf
        it = 0
        for it in range(1, o.max_iter + 1):
            self.dc.resolve(t_relax)
            dc_rs = self.dc.results()
            v_new = np.asarray(dc_rs.meta["voltage"], dtype=np.float64)
            self.th.resolve(np.asarray(dc_rs.meta["joule_cell"], dtype=np.float64))
            th_rs = self.th.results()
            t_new = temp_field(th_rs)

            d_t_prev = d_t
            d_t = float(np.max(np.abs(t_new - t_relax)[inside]))
            dv = np.abs(v_new - v_prev)[copper]
            dv = dv[np.isfinite(dv)]
            d_v = float(dv.max()) if dv.size else 0.0
            t_relax = t_relax + o.relaxation * (t_new - t_relax)
            v_prev = v_new

            hist["iteration"].append(float(it))
            hist["delta_t"].append(d_t)
            hist["delta_v"].append(d_v)
            hist["t_max"].append(th_rs.scalars["t_max"])
            hist["joule_power"].append(dc_rs.scalars["joule_power"])
            hist["drop_pct_max"].append(_worst_drop(dc_rs))

            if d_t < o.tol_t and d_v < o.tol_v:
                converged = True
                break
            growing = growing + 1 if (math.isfinite(d_t_prev) and d_t >= d_t_prev) else 0
            if growing >= _RUNAWAY_PASSES:
                runaway = True
                break

        self.final = (dc_rs, th_rs)
        self.history = hist
        self.iterations = it
        self.converged = converged
        self.runaway = runaway
        self.delta = (d_t, d_v)
        self._phase = "solved"

    def results(self) -> ResultSet:
        self._require_phase("solved")
        return _postprocess(self)


def _worst_drop(rs: ResultSet) -> float:
    drops = [float(r["drop_pct"]) for r in rs.meta["ports"] if "drop_pct" in r]
    drops = [d for d in drops if math.isfinite(d)]
    return max(drops) if drops else math.nan


def _contraction(hist: Mapping[str, list[float]]) -> float:
    """Estimated contraction ratio κ = ΔTₖ/ΔTₖ₋₁ from the last two passes."""
    d = [x for x in hist["delta_t"] if math.isfinite(x) and x > 0.0]
    if len(d) < 2:
        return math.nan
    return d[-1] / d[-2]


def _postprocess(s: CoupledSolver) -> ResultSet:
    dc, th = s.final
    dc0, th0 = s.uncoupled
    o = s.opts
    rs = ResultSet(s.name)
    rs.scalars.update(dc.scalars)
    rs.scalars.update(th.scalars)
    rs.fields.extend(dc.fields)
    rs.fields.extend(th.fields)

    d_t, d_v = s.delta
    rs.scalars["iterations"] = float(s.iterations)
    rs.scalars["converged"] = 1.0 if s.converged else 0.0
    rs.scalars["delta_t"] = d_t
    rs.scalars["delta_v"] = d_v
    rs.scalars["contraction"] = _contraction(s.history)
    rs.scalars["t_max.uncoupled"] = th0.scalars["t_max"]
    rs.scalars["joule_power.uncoupled"] = dc0.scalars["joule_power"]
    for r in dc0.meta["ports"]:
        if "drop_pct" in r:
            rs.scalars[f"{r['name']}.drop_pct.uncoupled"] = float(r["drop_pct"])
    for r in th0.meta["components"]:
        rs.scalars[f"{r['ref']}.tj.uncoupled"] = float(r["tj"])

    rs.violations.extend(dc.violations)
    rs.violations.extend(th.violations)
    if s.runaway:
        rs.violations.append(
            Violation(
                check="thermal_runaway",
                subject="coupled",
                value=rs.scalars["contraction"],
                limit=1.0,
                unit="",
                message=(
                    f"electro-thermal iteration diverges after {s.iterations} passes "
                    f"(ΔT grows, ratio {rs.scalars['contraction']:.2f} ≥ 1): "
                    "Joule heating outruns cooling — thermal runaway"
                ),
            )
        )
    elif not s.converged:
        rs.violations.append(
            Violation(
                check="convergence",
                subject="coupled",
                value=d_t,
                limit=o.tol_t,
                unit="K",
                message=(
                    f"electro-thermal iteration not converged in {o.max_iter} passes "
                    f"(ΔT {d_t:.3g} K, ΔV {d_v:.3g} V); raise max_iter or lower relaxation"
                ),
            )
        )
    for note in s.notes:
        rs.violations.append(Violation("model", "coupled", 0.0, 0.0, "", Severity.INFO, None, note))

    rs.meta.update(
        grid=s.grid,
        voltage=dc.meta["voltage"],
        current_density=dc.meta["current_density"],
        joule_cell=dc.meta["joule_cell"],
        temperature=th.meta["temperature"],
        ports=dc.meta["ports"],
        vias=dc.meta["vias"],
        components=th.meta["components"],
        heat_out=th.meta["heat_out"],
        history=s.history,
        tolerances={"tol_t": o.tol_t, "tol_v": o.tol_v},
        iterations=s.iterations,
        converged=s.converged,
        uncoupled={"dc_ir": dc0, "thermal": th0},
        warnings=[*dc.meta["warnings"], *th.meta["warnings"], *s.notes],
    )
    return rs
