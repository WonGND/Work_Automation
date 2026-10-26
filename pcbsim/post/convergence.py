"""Convergence plot of an iterative solver's ``history`` (e.g. ``coupled``).

Draws max|ΔT| [K] and max|ΔV| [V] per pass on a log axis, with the
tolerances as dashed lines when the solver reports them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def plot_convergence(
    history: Mapping[str, Sequence[float]],
    path: Path,
    tol_t: float | None = None,
    tol_v: float | None = None,
    title: str = "",
) -> Path:
    it = list(history["iteration"])
    fig, ax = plt.subplots(figsize=(6.0, 3.8), dpi=130)
    for key, label, color, tol in (
        ("delta_t", "max |ΔT| [K]", "tab:red", tol_t),
        ("delta_v", "max |ΔV| [V]", "tab:blue", tol_v),
    ):
        pts = [
            (k, v) for k, v in zip(it, history[key], strict=True) if math.isfinite(v) and v > 0.0
        ]
        if pts:
            ax.semilogy([p[0] for p in pts], [p[1] for p in pts], "o-", color=color, label=label)
        if tol is not None:
            ax.axhline(tol, color=color, ls="--", lw=0.8)
    ax.set_xlabel("pass")
    ax.set_ylabel("change between passes")
    ax.grid(True, which="both", lw=0.3)
    ax.legend(fontsize=8)
    if title:
        ax.set_title(title, fontsize=9, loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
