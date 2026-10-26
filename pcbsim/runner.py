"""Analysis runner: config → mesh → solvers (in order) → results on disk.

Solvers run in the order listed in ``analysis.solvers``, except that a solver
is moved after any requested solver it declares in ``Solver.uses`` (e.g.
``thermal`` after ``dc_ir`` for Joule heating). Each receives the
shared mesh and the results of the solvers that ran before it
(``SolverContext.upstream``) and the options of every solver
(``SolverContext.options``), which ``coupled`` uses to drive ``dc_ir`` and
``thermal`` with the user's settings.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pcbsim import __version__
from pcbsim.errors import SolverError
from pcbsim.io import LoadedConfig
from pcbsim.mesh import Grid, build_grid
from pcbsim.solvers import ResultSet, SolverContext, get_solver
from pcbsim.solvers.base import Severity


@dataclass(slots=True)
class RunResult:
    config: LoadedConfig
    grid: Grid
    results: dict[str, ResultSet] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results.values())


def order_solvers(names: list[str]) -> list[str]:
    """Stable topological order: a solver runs after the requested solvers it ``uses``."""
    remaining = list(dict.fromkeys(names))
    ordered: list[str] = []
    while remaining:
        for n in remaining:
            deps = [d for d in get_solver(n).uses if d in remaining and d != n]
            if not deps:
                ordered.append(n)
                remaining.remove(n)
                break
        else:
            raise SolverError(f"cyclic solver dependencies among {remaining}")
    return ordered


Progress = Callable[[int, int, str], None]


def run_analysis(
    cfg: LoadedConfig,
    solvers: list[str] | None = None,
    progress: Progress | None = None,
    cell: float | None = None,
) -> RunResult:
    """Mesh once, then run the solvers in dependency order.

    ``progress(i, n, label)`` is called before each step (``i`` = 0 … n−1: the mesh,
    then one call per solver) and once more with ``i = n`` when done. ``cell``
    overrides ``analysis.mesh`` (m).
    """
    names = order_solvers(solvers if solvers is not None else list(cfg.analysis.solvers))
    classes = [get_solver(n) for n in names]
    mesh = cfg.analysis.mesh
    n_steps = len(names) + 1
    if progress is not None:
        progress(0, n_steps, "mesh")
    grid = build_grid(cfg.board, cell if cell is not None else mesh.cell / mesh.refine)
    out = RunResult(cfg, grid)
    for k, (name, cls) in enumerate(zip(names, classes, strict=True), 1):
        if progress is not None:
            progress(k, n_steps, name)
        ctx = SolverContext(cfg.board, cfg.materials, grid, dict(out.results), cfg.analysis.options)
        solver = cls(cfg.analysis.options.get(name, {}))
        out.results[name] = solver.run(ctx)
    if progress is not None:
        progress(n_steps, n_steps, "done")
    return out


def _clean(x: Any) -> Any:
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, np.floating):
        return _clean(float(x))
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    return x


def _ring(points: Any) -> list[list[float]]:
    return [[float(x), float(y)] for x, y in np.asarray(points)]


def _geometry(run: RunResult) -> dict[str, Any]:
    """Board outline, ports and component footprints (m) for reports and viewers."""
    b = run.config.board
    return {
        "outline": _ring(b.outline.outer),
        "holes": [_ring(h) for h in b.outline.holes],
        "ports": [
            {"name": p.name, "layer": p.layer, "kind": p.kind.value, "ring": _ring(p.region.outer)}
            for p in b.ports
        ],
        "components": [
            {"ref": c.ref, "side": c.side.value, "ring": _ring(c.footprint.outer)}
            for c in b.components
        ],
    }


def to_json_dict(run: RunResult) -> dict[str, Any]:
    g = run.grid
    doc: dict[str, Any] = {
        "pcbsim_version": __version__,
        "board": run.config.board.name,
        "source": str(run.config.source) if run.config.source else None,
        "units": {
            "length": "m",
            "voltage": "V",
            "current": "A",
            "power": "W",
            "current_density": "A/m^2",
            "temperature": "K",
        },
        "mesh": {
            "dx": g.dx,
            "dy": g.dy,
            "nx": g.nx,
            "ny": g.ny,
            "layers": list(g.layers),
            "extent": list(g.extent),
        },
        "geometry": _geometry(run),
        "passed": run.passed,
        "solvers": {},
    }
    for name, rs in run.results.items():
        doc["solvers"][name] = {
            "passed": rs.passed,
            "scalars": rs.scalars,
            "violations": [
                {
                    "check": v.check,
                    "subject": v.subject,
                    "severity": v.severity.value,
                    "value": v.value,
                    "limit": v.limit,
                    "unit": v.unit,
                    "location": v.location,
                    "message": v.message,
                }
                for v in rs.violations
            ],
            "ports": rs.meta.get("ports", []),
            "vias": rs.meta.get("vias", []),
            "components": rs.meta.get("components", []),
            "history": rs.meta.get("history", {}),
            "lines": rs.meta.get("lines", []),
        }
    cleaned: dict[str, Any] = _clean(doc)
    return cleaned


def write_results(
    run: RunResult, out_dir: Path, plots: bool = True, report: bool = False
) -> list[Path]:
    """Write ``results.json`` (+ ``*.npz`` fields, PNG heat maps, ``report.html``)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    p = out_dir / "results.json"
    p.write_text(json.dumps(to_json_dict(run), indent=2, ensure_ascii=False), "utf-8")
    written.append(p)
    for name, rs in run.results.items():
        if rs.fields:
            arrays = {f"{f.name}__{f.layer}": f.values for f in rs.fields}
            npz = out_dir / f"{name}_fields.npz"
            np.savez_compressed(npz, **arrays)  # type: ignore[arg-type]
            written.append(npz)
    if plots:
        from pcbsim.post.convergence import plot_convergence
        from pcbsim.post.heatmap import plot_fields

        for rs in run.results.values():
            written += plot_fields(rs, run.config.board, out_dir)
            hist = rs.meta.get("history") or {}
            if "delta_t" in hist and "iteration" in hist:
                tol = rs.meta.get("tolerances", {})
                written.append(
                    plot_convergence(
                        hist,
                        out_dir / f"{rs.solver}_convergence.png",
                        tol.get("tol_t"),
                        tol.get("tol_v"),
                        f"{rs.solver}: electro-thermal iteration",
                    )
                )
    if report:
        from pcbsim.report import write_report

        written.append(write_report(out_dir))
    return written


def violation_counts(run: RunResult) -> dict[Severity, int]:
    counts = dict.fromkeys(Severity, 0)
    for rs in run.results.values():
        for v in rs.violations:
            counts[v.severity] += 1
    return counts
