"""Analysis runner: config → mesh → solvers (in order) → results on disk.

Solvers run in the order listed in ``analysis.solvers``, except that a solver
is moved after any requested solver it declares in ``Solver.uses`` (e.g.
``thermal`` after ``dc_ir`` for Joule heating). Each receives the
shared mesh and the results of the solvers that ran before it
(``SolverContext.upstream``), which is how ``coupled`` will reuse ``dc_ir`` and
``thermal``.
"""

from __future__ import annotations

import json
import math
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


def run_analysis(cfg: LoadedConfig, solvers: list[str] | None = None) -> RunResult:
    names = order_solvers(solvers if solvers is not None else list(cfg.analysis.solvers))
    classes = [get_solver(n) for n in names]
    mesh = cfg.analysis.mesh
    grid = build_grid(cfg.board, mesh.cell / mesh.refine)
    out = RunResult(cfg, grid)
    for name, cls in zip(names, classes, strict=True):
        ctx = SolverContext(cfg.board, cfg.materials, grid, dict(out.results))
        solver = cls(cfg.analysis.options.get(name, {}))
        out.results[name] = solver.run(ctx)
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
        "mesh": {"dx": g.dx, "dy": g.dy, "nx": g.nx, "ny": g.ny, "layers": list(g.layers)},
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
        }
    cleaned: dict[str, Any] = _clean(doc)
    return cleaned


def write_results(run: RunResult, out_dir: Path, plots: bool = True) -> list[Path]:
    """Write ``results.json`` (+ ``*.npz`` fields and PNG heat maps) to ``out_dir``."""
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
        from pcbsim.post.heatmap import plot_fields

        for rs in run.results.values():
            written += plot_fields(rs, run.config.board, out_dir)
    return written


def violation_counts(run: RunResult) -> dict[Severity, int]:
    counts = dict.fromkeys(Severity, 0)
    for rs in run.results.values():
        for v in rs.violations:
            counts[v.severity] += 1
    return counts
