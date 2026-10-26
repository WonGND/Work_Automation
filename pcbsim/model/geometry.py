"""2D geometry primitives used by the board model.

Area uses the shoelace formula ``A = ½ |Σ (x_i·y_{i+1} − x_{i+1}·y_i)|``;
holes are subtracted. Point-in-polygon uses the even-odd rule via
:class:`matplotlib.path.Path`, which is also what the 2.5D rasteriser in
:mod:`pcbsim.mesh` will use to assign grid cells to copper.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from matplotlib.path import Path
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


def _as_ring(points: ArrayLike) -> FloatArray:
    ring = np.asarray(points, dtype=np.float64)
    if ring.ndim != 2 or ring.shape[1] != 2:
        raise ValueError(f"polygon ring must have shape (N, 2), got {ring.shape}")
    if len(ring) >= 2 and np.allclose(ring[0], ring[-1]):
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("polygon ring needs at least 3 distinct vertices")
    return ring


def _signed_area(ring: FloatArray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


@dataclass(frozen=True, slots=True, eq=False)
class Polygon:
    """Simple polygon with optional holes. Coordinates in metres."""

    outer: FloatArray
    holes: tuple[FloatArray, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outer", _as_ring(self.outer))
        object.__setattr__(self, "holes", tuple(_as_ring(h) for h in self.holes))

    @classmethod
    def from_points(cls, outer: ArrayLike, holes: Sequence[ArrayLike] = ()) -> Polygon:
        return cls(np.asarray(outer, dtype=np.float64), tuple(np.asarray(h) for h in holes))

    @classmethod
    def rectangle(cls, x0: float, y0: float, x1: float, y1: float) -> Polygon:
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        return cls(np.array([[xa, ya], [xb, ya], [xb, yb], [xa, yb]], dtype=np.float64))

    @classmethod
    def circle(cls, cx: float, cy: float, r: float, n: int = 32) -> Polygon:
        t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
        return cls(np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)]))

    def area(self) -> float:
        return abs(_signed_area(self.outer)) - sum(abs(_signed_area(h)) for h in self.holes)

    def bbox(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax)."""
        xmin, ymin = self.outer.min(axis=0)
        xmax, ymax = self.outer.max(axis=0)
        return float(xmin), float(ymin), float(xmax), float(ymax)

    def path(self) -> Path:
        """Compound matplotlib path (outer + holes) for even-odd containment tests."""
        verts: list[FloatArray] = []
        codes: list[NDArray[np.uint8]] = []
        for ring in (self.outer, *self.holes):
            closed = np.vstack([ring, ring[:1]])
            c = np.full(len(closed), Path.LINETO, dtype=np.uint8)
            c[0] = Path.MOVETO
            c[-1] = Path.CLOSEPOLY
            verts.append(closed)
            codes.append(c)
        return Path(np.vstack(verts), np.concatenate(codes))

    def contains(self, points: ArrayLike) -> NDArray[np.bool_]:
        """Vectorised point-in-polygon test (points on holes are outside)."""
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        inside = Path(np.vstack([self.outer, self.outer[:1]])).contains_points(pts)
        for h in self.holes:
            inside &= ~Path(np.vstack([h, h[:1]])).contains_points(pts)
        return np.asarray(inside, dtype=np.bool_)

    def distance_to_boundary(self, points: ArrayLike) -> FloatArray:
        """Minimum Euclidean distance from each point to any ring edge."""
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        best = np.full(len(pts), np.inf)
        for ring in (self.outer, *self.holes):
            a = ring
            b = np.roll(ring, -1, axis=0)
            ab = b - a
            ap = pts[:, None, :] - a[None, :, :]
            denom = np.maximum(np.einsum("ij,ij->i", ab, ab), np.finfo(float).tiny)
            t = np.clip(np.einsum("pij,ij->pi", ap, ab) / denom, 0.0, 1.0)
            closest = a[None, :, :] + t[..., None] * ab[None, :, :]
            d = np.linalg.norm(pts[:, None, :] - closest, axis=2).min(axis=1)
            best = np.minimum(best, d)
        return best

    def covers(self, points: ArrayLike, tol: float | None = None) -> NDArray[np.bool_]:
        """Like :meth:`contains` but points within ``tol`` of the boundary count as inside.

        Default ``tol`` is 1e-9 × the bbox diagonal (robust to float round-off).
        """
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        if tol is None:
            xmin, ymin, xmax, ymax = self.bbox()
            tol = 1e-9 * float(np.hypot(xmax - xmin, ymax - ymin))
        return self.contains(pts) | (self.distance_to_boundary(pts) <= tol)

    def contains_polygon_bbox(self, other: Polygon) -> bool:
        """Every vertex of ``other`` lies inside or on the boundary of this polygon."""
        return bool(np.all(self.covers(other.outer)))

    def translated(self, dx: float, dy: float) -> Polygon:
        off = np.array([dx, dy])
        return Polygon(self.outer + off, tuple(h + off for h in self.holes))

    def __repr__(self) -> str:
        return f"Polygon(n={len(self.outer)}, holes={len(self.holes)}, area={self.area():.3e} m²)"
