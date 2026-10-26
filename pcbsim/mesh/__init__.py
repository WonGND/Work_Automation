"""Meshing: 2.5D per-layer structured grids (stage 2), triangular meshes later.

Vias are modelled as 1D inter-layer connection elements by the solvers.
"""

from __future__ import annotations

from pcbsim.mesh.grid import Grid, build_grid

__all__ = ["Grid", "build_grid"]
