"""Signal-integrity solver: characteristic impedance of every ``transmission_lines`` entry.

For each line the stack-up is turned into a cross-section
(:func:`pcbsim.si.xsection.resolve`) and solved two ways:

1. **2D FEM** (:mod:`pcbsim.si.fem2d`), which gives the reported value:
   Z0 = 1/(c₀√(C·C⁽⁰⁾)), ε_eff = C/C⁽⁰⁾; for a pair, Zdiff = 2·Z_odd.
2. **Closed form** (:func:`pcbsim.si.xsection.analytic_for`): Hammerstad–Jensen,
   Wheeler, Cohn (exact) or IPC-2141A, chosen by topology.

Checks
    * ``z0`` — |Z − Z_target| / Z_target > tolerance → violation. Z is Z0 for a
      single trace and Zdiff for a pair. The tolerance is the line's
      ``tolerance_pct`` or ``criteria.z0_tol_pct`` (default ±10 %).
    * ``z0_crosscheck`` — |Z_FEM − Z_formula| / Z_formula larger than the
      formula's expected accuracy → warning (the geometry is outside what the
      closed form models, e.g. solder mask, or an input mistake).

Options (``analysis.options.si``): ``mesh`` = ``coarse`` | ``normal`` | ``fine``
(minimum element size 1/12, 1/24 or 1/64 of the smallest feature),
``box_factor`` (outer shield distance / feature size, default 30).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pcbsim.errors import SolverError
from pcbsim.si.fem2d import FemOptions
from pcbsim.si.fem2d import solve as fem_solve
from pcbsim.si.xsection import analytic_for, resolve
from pcbsim.solvers.base import ResultSet, Severity, Solver, Violation, register

_MESH = {"coarse": 1 / 12, "normal": 1 / 24, "fine": 1 / 64}


class SiOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mesh: Literal["coarse", "normal", "fine"] = "normal"
    box_factor: float = Field(default=30.0, ge=5.0)


@register("si")
class SiSolver(Solver):
    description = "transmission-line Z0 / Zdiff: 2D FEM cross-section + closed forms"

    def validate_options(self) -> None:
        try:
            self.opts = SiOptions.model_validate(self.options)
        except ValidationError as exc:
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise SolverError(f"si options: {msgs}") from None
        if not self.ctx.board.transmission_lines:
            raise SolverError("si: config has no transmission_lines")

    def assemble(self) -> None:
        board, db = self.ctx.board, self.ctx.materials
        self._geoms = [
            resolve(
                board.stackup,
                db,
                tl.layer,
                tl.width,
                tl.spacing,
                tl.references or None,
            )
            for tl in board.transmission_lines
        ]
        self._phase = "assembled"

    def solve(self) -> None:
        self._require_phase("assembled")
        fo = FemOptions(h_min_frac=_MESH[self.opts.mesh], box_factor=self.opts.box_factor)
        self._fem = [fem_solve(g.xs, fo) for g in self._geoms]
        self._phase = "solved"

    def results(self) -> ResultSet:
        self._require_phase("solved")
        board = self.ctx.board
        rs = ResultSet(self.name)
        rows: list[dict[str, Any]] = []
        for tl, g, fem in zip(board.transmission_lines, self._geoms, self._fem, strict=True):
            z_fem = fem.pair() if g.differential else fem.single()
            z_ana, acc = analytic_for(g)
            value = z_fem.z_diff if g.differential else z_fem.z0
            ana_value = z_ana.z_diff if g.differential else z_ana.z0
            assert value is not None
            assert ana_value is not None
            dev = (value - ana_value) / ana_value
            quantity = "Zdiff" if g.differential else "Z0"
            tol = tl.tolerance_pct if tl.tolerance_pct is not None else board.criteria.z0_tol_pct
            row: dict[str, Any] = {
                "name": tl.name,
                "layer": tl.layer,
                "topology": ("differential " if g.differential else "") + g.topology,
                "references": list(g.references),
                "quantity": quantity,
                "width": tl.width,
                "spacing": tl.spacing,
                "h": g.h,
                "b": g.b,
                "t": g.t,
                "eps_r": g.er,
                "z_fem": value,
                "z0_fem": z_fem.z0,
                "eps_eff_fem": z_fem.eps_eff,
                "z_odd_fem": z_fem.z_odd,
                "z_even_fem": z_fem.z_even,
                "z_formula": ana_value,
                "formula": z_ana.method,
                "formula_note": z_ana.note,
                "crosscheck_dev": dev,
                "crosscheck_tol": acc,
                "target": tl.target,
                "tolerance_pct": tol,
                "c_per_m": fem.c.tolist(),
                "l_per_m": fem.l.tolist(),
                "fem_dofs": fem.n_dofs,
            }
            rs.scalars[f"{tl.name}.{quantity}"] = value
            rs.scalars[f"{tl.name}.eps_eff"] = z_fem.eps_eff
            if abs(dev) > acc:
                rs.violations.append(
                    Violation(
                        "z0_crosscheck",
                        tl.name,
                        dev * 100.0,
                        acc * 100.0,
                        "%",
                        Severity.WARNING,
                        message=(
                            f"{tl.name}: FEM {quantity} {value:.2f} Ω vs {z_ana.method} "
                            f"{ana_value:.2f} Ω ({dev * 100:+.1f} %, expected within "
                            f"±{acc * 100:.0f} %){'; ' + z_ana.note if z_ana.note else ''}"
                        ),
                    )
                )
            if tl.target is not None:
                err = (value - tl.target) / tl.target * 100.0
                row["target_dev_pct"] = err
                row["passed"] = abs(err) <= tol
                if abs(err) > tol:
                    rs.violations.append(
                        Violation(
                            "z0",
                            tl.name,
                            value,
                            tl.target,
                            "Ω",
                            message=(
                                f"{tl.name}: {quantity} {value:.2f} Ω is {err:+.1f} % from "
                                f"target {tl.target:g} Ω (tolerance ±{tol:g} %)"
                            ),
                        )
                    )
            rows.append(row)
        rs.meta["lines"] = rows
        return rs
