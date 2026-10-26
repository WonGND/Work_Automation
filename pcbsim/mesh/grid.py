"""2.5D structured grid: one uniform cell grid shared by every conductor layer.

Discretisation
--------------
The board bounding box is divided into ``nx × ny`` square-ish cells
(``dx = W/nx``, ``dy = H/ny`` with ``nx = ceil(W/h)``). A cell belongs to a net
on a layer if its **centre** lies inside a copper shape of that net (staircase
approximation; the error vanishes as ``h → 0``, see the mesh-convergence tests).

``net_map[l, iy, ix]`` holds the net index of the copper in each cell, or ``-1``.
Overlapping copper of two different nets on the same layer is a short circuit
and raises :class:`~pcbsim.errors.SolverError`.

Vias are not part of the grid; solvers attach them as 1D inter-layer elements
to the cells around their (x, y) location.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pcbsim.errors import SolverError
from pcbsim.model import Board, Polygon

IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True, eq=False)
class Grid:
    x0: float
    y0: float
    dx: float
    dy: float
    nx: int
    ny: int
    layers: tuple[str, ...]
    nets: tuple[str, ...]
    net_map: NDArray[np.int32]
    inside: BoolArray

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    @property
    def cell_area(self) -> float:
        return self.dx * self.dy

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """(x_min, x_max, y_min, y_max) — matplotlib ``imshow`` order."""
        return (self.x0, self.x0 + self.nx * self.dx, self.y0, self.y0 + self.ny * self.dy)

    def xc(self) -> FloatArray:
        return self.x0 + (np.arange(self.nx, dtype=np.float64) + 0.5) * self.dx

    def yc(self) -> FloatArray:
        return self.y0 + (np.arange(self.ny, dtype=np.float64) + 0.5) * self.dy

    def layer_index(self, name: str) -> int:
        try:
            return self.layers.index(name)
        except ValueError:
            raise SolverError(f"layer {name!r} is not a conductor layer of the grid") from None

    def net_index(self, name: str) -> int:
        try:
            return self.nets.index(name)
        except ValueError:
            return -1

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """(iy, ix) of the cell containing (x, y), clipped to the grid."""
        ix = min(max(math.floor((x - self.x0) / self.dx), 0), self.nx - 1)
        iy = min(max(math.floor((y - self.y0) / self.dy), 0), self.ny - 1)
        return iy, ix

    def center_of(self, iy: int, ix: int) -> tuple[float, float]:
        return (self.x0 + (ix + 0.5) * self.dx, self.y0 + (iy + 0.5) * self.dy)

    def _window(self, poly: Polygon) -> tuple[slice, slice]:
        xmin, ymin, xmax, ymax = poly.bbox()
        ix0 = max(math.floor((xmin - self.x0) / self.dx), 0)
        ix1 = min(math.ceil((xmax - self.x0) / self.dx), self.nx)
        iy0 = max(math.floor((ymin - self.y0) / self.dy), 0)
        iy1 = min(math.ceil((ymax - self.y0) / self.dy), self.ny)
        return slice(iy0, max(iy1, iy0)), slice(ix0, max(ix1, ix0))

    def mask(self, poly: Polygon) -> BoolArray:
        """Cells whose centre lies inside ``poly``."""
        out = np.zeros(self.shape, dtype=np.bool_)
        sy, sx = self._window(poly)
        xc, yc = self.xc()[sx], self.yc()[sy]
        if xc.size == 0 or yc.size == 0:
            return out
        xx, yy = np.meshgrid(xc, yc)
        pts = np.column_stack([xx.ravel(), yy.ravel()])
        out[sy, sx] = poly.contains(pts).reshape(xx.shape)
        return out

    def region_mask(self, poly: Polygon) -> BoolArray:
        """Board cells (inside the outline) under ``poly``, with a centroid fallback
        for regions smaller than one cell."""
        sel: BoolArray = self.mask(poly) & self.inside
        if not sel.any():
            cx, cy = (float(v) for v in poly.outer.mean(axis=0))
            iy, ix = self.cell_of(cx, cy)
            if self.inside[iy, ix]:
                sel[iy, ix] = True
        return sel

    def region_cells(self, poly: Polygon, layer: str, net: str) -> BoolArray:
        """Cells of ``net`` copper on ``layer`` under ``poly``.

        If ``poly`` is smaller than a cell (no centre inside), fall back to the
        cell containing its centroid.
        """
        li = self.layer_index(layer)
        ni = self.net_index(net)
        if ni < 0:
            return np.zeros(self.shape, dtype=np.bool_)
        copper: BoolArray = np.asarray(self.net_map[li] == ni, dtype=np.bool_)
        sel: BoolArray = self.mask(poly) & copper
        if not sel.any():
            cx, cy = (float(v) for v in poly.outer.mean(axis=0))
            iy, ix = self.cell_of(cx, cy)
            if copper[iy, ix]:
                sel[iy, ix] = True
        return sel

    def copper_cells(self) -> int:
        return int(np.count_nonzero(self.net_map >= 0))


def build_grid(board: Board, cell: float) -> Grid:
    """Rasterise all copper shapes of ``board`` onto a grid of target size ``cell`` [m]."""
    if cell <= 0.0:
        raise SolverError("mesh cell size must be > 0")
    xmin, ymin, xmax, ymax = board.outline.bbox()
    nx = max(math.ceil((xmax - xmin) / cell - 1e-9), 1)
    ny = max(math.ceil((ymax - ymin) / cell - 1e-9), 1)
    if nx * ny > 20_000_000:
        raise SolverError(f"mesh too fine: {nx}×{ny} cells; increase analysis.mesh.cell")
    dx, dy = (xmax - xmin) / nx, (ymax - ymin) / ny
    layers = tuple(layer.name for layer in board.stackup.conductor_layers())
    nets = tuple(n.name for n in board.nets)
    net_map = np.full((len(layers), ny, nx), -1, dtype=np.int32)

    proto = Grid(xmin, ymin, dx, dy, nx, ny, layers, nets, net_map, np.ones((ny, nx), np.bool_))
    inside = proto.mask(board.outline)

    shorts: list[str] = []
    for li, lname in enumerate(layers):
        for shape in board.shapes_on(lname):
            ni = nets.index(shape.net)
            m = proto.mask(shape.polygon) & inside
            clash = m & (net_map[li] >= 0) & (net_map[li] != ni)
            if clash.any():
                other = nets[int(net_map[li][clash][0])]
                shorts.append(
                    f"layer {lname}: nets {other!r} and {shape.net!r} overlap "
                    f"({int(clash.sum())} cells) — short circuit"
                )
            net_map[li][m] = ni
    if shorts:
        raise SolverError("\n".join(shorts))
    return Grid(xmin, ymin, dx, dy, nx, ny, layers, nets, net_map, inside)
