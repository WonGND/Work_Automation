"""Per-layer heat maps of solver fields (matplotlib, Agg backend).

One PNG per (field, layer). Copper outlines of the layer are drawn on top,
port regions are outlined, and the worst violation location is marked.
Voltage maps use a sequential colormap anchored at the field's own min/max so
small drops stay visible.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from pcbsim.model import Board
from pcbsim.solvers.base import FieldData, ResultSet

_SCALE: dict[str, tuple[float, float, str, str]] = {
    "voltage": (1.0, 0.0, "V", "viridis"),
    "current_density": (1e-6, 0.0, "A/mm²", "inferno"),
    "power_density": (1e-4, 0.0, "W/cm²", "magma"),
    "temperature": (1.0, -273.15, "°C", "plasma"),
}


def plot_field(f: FieldData, board: Board, rs: ResultSet, path: Path) -> Path:
    scale, offset, unit, cmap = _SCALE.get(f.name, (1.0, 0.0, f.unit, "viridis"))
    data = f.values * scale + offset
    finite = np.isfinite(data)
    fig, ax = plt.subplots(figsize=(7.0, 4.6), dpi=130)
    x0, x1, y0, y1 = (v * 1e3 for v in f.extent)
    if finite.any():
        im = ax.imshow(
            np.ma.masked_invalid(data),
            origin="lower",
            extent=(x0, x1, y0, y1),
            cmap=cmap,
            interpolation="nearest",
        )
        cb = fig.colorbar(im, ax=ax, shrink=0.85)
        cb.set_label(f"{f.name.replace('_', ' ')} [{unit}]")
    ox = np.append(board.outline.outer[:, 0], board.outline.outer[0, 0]) * 1e3
    oy = np.append(board.outline.outer[:, 1], board.outline.outer[0, 1]) * 1e3
    ax.plot(ox, oy, color="0.35", lw=0.8)
    for p in board.ports:
        if p.layer != f.layer:
            continue
        ring = np.vstack([p.region.outer, p.region.outer[:1]]) * 1e3
        ax.plot(ring[:, 0], ring[:, 1], color="white", lw=1.0, ls="--")
        cx, cy = p.region.outer.mean(axis=0) * 1e3
        ax.annotate(p.name, (cx, cy), color="white", fontsize=7, ha="center", va="center")
    for v in rs.violations:
        if v.location is not None and (
            v.subject == f.layer or f.name in ("voltage", "temperature")
        ):
            ax.plot(v.location[0] * 1e3, v.location[1] * 1e3, marker="x", color="red", ms=7)
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    if finite.any():
        lo, hi = float(np.nanmin(data)), float(np.nanmax(data))
        ax.set_title(
            f"{f.layer} · {f.name.replace('_', ' ')}  (min {lo:.4g}, max {hi:.4g} {unit})",
            fontsize=9,
            loc="left",
        )
    else:
        ax.set_title(f"{f.layer} · no copper", fontsize=9, loc="left")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_fields(rs: ResultSet, board: Board, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for f in rs.fields:
        if f.name == "power_density":
            continue
        written.append(plot_field(f, board, rs, out_dir / f"{rs.solver}_{f.name}_{f.layer}.png"))
    return written
