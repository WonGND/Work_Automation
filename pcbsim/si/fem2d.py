"""2D electrostatic cross-section solver for transmission-line parameters (scikit-fem).

Quasi-TEM model
    In the cross-section the potential obeys ``∇·(ε_r ∇φ) = 0`` with
    φ = V_i on conductor i and φ = 0 on the reference (ground) conductors and
    on the outer box (a distant shield). Per-unit-length capacitance comes from
    the field energy::

        C_ij = ε₀ ∫ ε_r ∇φ_i · ∇φ_j dA = ε₀ · φ_iᵀ K φ_j

    where φ_i is the solution with conductor i at 1 V and all others at 0 —
    the Maxwell capacitance matrix, symmetric by construction and
    second-order accurate in the energy norm. Solving again with every
    ε_r = 1 gives C⁽⁰⁾, and for a TEM/quasi-TEM line [Pozar] §3.8, [Wadell] §1.4::

        L = μ₀ε₀ (C⁽⁰⁾)⁻¹,   Z0 = 1 / (c₀ √(C · C⁽⁰⁾))   (single line),
        ε_eff = C / C⁽⁰⁾

    A symmetric pair has odd/even modal capacitances ``C_o = C₁₁ − C₁₂`` and
    ``C_e = C₁₁ + C₁₂`` (C₁₂ < 0), giving ``Z_odd``, ``Z_even``,
    ``Z_diff = 2 Z_odd`` and ``Z_comm = Z_even / 2``.

Discretisation
    Quadratic Lagrange triangles (P2) on a tensor grid whose lines pass through
    every conductor edge, dielectric interface, and region boundary. Spacing
    grows geometrically (ratio ``growth``) away from conductor edges, where the
    field has a corner singularity (∝ r^(−1/3) for a 90° edge [Williams-1952]),
    from ``h_min`` up to ``h_max``. ε_r is piecewise constant per element,
    taken at the element centroid, so material interfaces must lie on grid
    lines; they do by construction.

    The outer box is a grounded shield, placed ``box_factor`` times the
    feature size away. Its effect on C decays like (size/distance)² for an
    open microstrip; the default keeps it below 0.1 % (see tests).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.sparse.linalg import splu
from skfem import Basis, BilinearForm, ElementTriP0, ElementTriP2, MeshTri, asm
from skfem.helpers import dot, grad

from pcbsim.errors import SolverError
from pcbsim.si.analytic import C0, LineZ

EPS0 = 8.8541878128e-12
FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Rect:
    x0: float
    x1: float
    y0: float
    y1: float

    def contains(self, x: FloatArray, y: FloatArray, tol: float) -> NDArray[np.bool_]:
        return (
            (x >= self.x0 - tol)
            & (x <= self.x1 + tol)
            & (y >= self.y0 - tol)
            & (y <= self.y1 + tol)
        )


@dataclass(frozen=True, slots=True)
class DielectricRegion:
    """Rectangular override of the layered permittivity (e.g. conformal solder mask)."""

    rect: Rect
    eps_r: float


@dataclass(slots=True)
class CrossSection:
    """Line cross-section, SI. y = 0 is the bottom reference plane (always grounded).

    ``bands``: horizontal dielectric layers ``(y0, y1, ε_r)``; space not covered is air.
    ``top_plane``: y of an upper reference plane (stripline) or ``None`` (microstrip).
    ``conductors``: signal conductors, rectangles (zero-thickness allowed: y0 == y1).
    ``regions``: rectangles overriding ``bands`` (later entries win).
    """

    conductors: list[Rect]
    bands: list[tuple[float, float, float]] = field(default_factory=list)
    top_plane: float | None = None
    regions: list[DielectricRegion] = field(default_factory=list)

    def feature_size(self) -> float:
        xs = [c.x1 - c.x0 for c in self.conductors]
        heights = [b[1] - b[0] for b in self.bands if b[1] > b[0]]
        return max([*xs, *heights, max(c.y1 for c in self.conductors)])

    def eps_at(self, x: FloatArray, y: FloatArray, vacuum: bool) -> FloatArray:
        eps = np.ones_like(x)
        if vacuum:
            return eps
        for y0, y1, er in self.bands:
            eps[(y >= y0) & (y < y1)] = er
        for r in self.regions:
            eps[r.rect.contains(x, y, 0.0)] = r.eps_r
        return eps


@dataclass(frozen=True, slots=True)
class FemOptions:
    h_min_frac: float = 1 / 24
    growth: float = 1.25
    h_max_frac: float = 0.5
    box_factor: float = 30.0


@dataclass(slots=True)
class FemResult:
    c: FloatArray
    c0: FloatArray
    n_dofs: int
    n_elements: int

    @property
    def l(self) -> FloatArray:  # noqa: E743 - L is the textbook symbol
        out: FloatArray = np.linalg.inv(self.c0) / C0**2
        return out

    def single(self, i: int = 0) -> LineZ:
        c, c0 = float(self.c[i, i]), float(self.c0[i, i])
        return LineZ(1.0 / (C0 * math.sqrt(c * c0)), c / c0, method="fem-2d")

    def pair(self) -> LineZ:
        if self.c.shape != (2, 2):
            raise SolverError("pair(): cross-section must have exactly two conductors")
        co = self.c[0, 0] - self.c[0, 1]
        ce = self.c[0, 0] + self.c[0, 1]
        co0 = self.c0[0, 0] - self.c0[0, 1]
        ce0 = self.c0[0, 0] + self.c0[0, 1]
        zo = 1.0 / (C0 * math.sqrt(co * co0))
        ze = 1.0 / (C0 * math.sqrt(ce * ce0))
        single = self.single(0)
        return LineZ(
            single.z0, float(co / co0), z_odd=zo, z_even=ze, z_diff=2.0 * zo, method="fem-2d"
        )


def _axis(
    keys: list[float], features: list[float], h_min: float, h_max: float, growth: float
) -> FloatArray:
    """Grid coordinates containing every ``keys`` value, with local spacing
    ``h(p) = min(h_max, h_min + (growth − 1)·d(p))`` where d is the distance to the
    nearest ``features`` coordinate (geometric grading away from conductor edges).
    Each interval between keys is walked with that spacing and then stretched
    uniformly so it ends exactly on the next key."""
    ks = np.unique(np.asarray(keys, dtype=np.float64))
    feat = np.asarray(features if features else [ks[0]], dtype=np.float64)

    def size_at(p: float) -> float:
        return min(h_max, h_min + (growth - 1.0) * float(np.min(np.abs(feat - p))))

    out = [float(ks[0])]
    for a, b in itertools.pairwise(ks):
        pts = [float(a)]
        while True:
            nxt = pts[-1] + size_at(pts[-1])
            if nxt >= b - 0.5 * size_at(float(b)):
                break
            pts.append(nxt)
        n = len(pts)
        if n > 1:
            span = pts[-1] - a + size_at(pts[-1])
            scale = (b - a) / span
            pts = [float(a) + (q - float(a)) * scale for q in pts]
        out.extend(pts[1:])
        out.append(float(b))
    return np.asarray(out)


def build_mesh(xs: CrossSection, opts: FemOptions) -> MeshTri:
    size = xs.feature_size()
    small = [c.x1 - c.x0 for c in xs.conductors]
    small += [c.y1 - c.y0 for c in xs.conductors if c.y1 > c.y0]
    if len(xs.conductors) > 1:
        cs = sorted(xs.conductors, key=lambda r: r.x0)
        small += [b.x0 - a.x1 for a, b in itertools.pairwise(cs) if b.x0 > a.x1]
    small += [c.y0 for c in xs.conductors if c.y0 > 0]
    if xs.top_plane is not None:
        small += [xs.top_plane - c.y1 for c in xs.conductors]
    h_min = min(small) * opts.h_min_frac
    xmid = 0.5 * (min(c.x0 for c in xs.conductors) + max(c.x1 for c in xs.conductors))
    half = opts.box_factor * size
    x_lo, x_hi = xmid - half, xmid + half
    y_top = xs.top_plane if xs.top_plane is not None else opts.box_factor * size
    h_max = max(size * opts.h_max_frac, h_min)
    h_far = max(h_max, (y_top if xs.top_plane is None else size) * 0.1)

    xkeys = [x_lo, x_hi]
    ykeys = [0.0, y_top]
    xfeat: list[float] = []
    yfeat: list[float] = [0.0]
    for c in xs.conductors:
        xkeys += [c.x0, c.x1]
        ykeys += [c.y0, c.y1]
        xfeat += [c.x0, c.x1]
        yfeat += [c.y0, c.y1]
    for y0, y1, _ in xs.bands:
        ykeys += [min(y0, y_top), min(y1, y_top)]
    for r in xs.regions:
        xkeys += [r.rect.x0, r.rect.x1]
        ykeys += [min(r.rect.y0, y_top), min(r.rect.y1, y_top)]
    if xs.top_plane is not None:
        yfeat.append(xs.top_plane)
    xkeys = [k for k in xkeys if x_lo <= k <= x_hi]
    x = _axis(xkeys, xfeat, h_min, h_far, opts.growth)
    y = _axis(ykeys, yfeat, h_min, h_far, opts.growth)
    return MeshTri.init_tensor(x, y)


@BilinearForm
def _laplace(u, v, w):  # type: ignore[no-untyped-def]
    return w.eps * dot(grad(u), grad(v))


def solve(xs: CrossSection, opts: FemOptions | None = None) -> FemResult:
    """Maxwell capacitance matrices with and without dielectrics (F/m)."""
    if not xs.conductors:
        raise SolverError("cross-section has no signal conductor")
    opts = opts or FemOptions()
    mesh = build_mesh(xs, opts)
    basis = Basis(mesh, ElementTriP2())
    b0 = basis.with_element(ElementTriP0())
    centroids = mesh.p[:, mesh.t].mean(axis=1)
    dx, dy = basis.doflocs
    tol = 1e-9 * xs.feature_size()

    ground = np.zeros(basis.N, dtype=bool)
    bx0, bx1 = float(mesh.p[0].min()), float(mesh.p[0].max())
    by1 = float(mesh.p[1].max())
    ground |= (np.abs(dx - bx0) < tol) | (np.abs(dx - bx1) < tol) | (np.abs(dy) < tol)
    ground |= np.abs(dy - by1) < tol
    cond_masks = [r.contains(dx, dy, tol) for r in xs.conductors]
    for k, m in enumerate(cond_masks):
        if np.any(m & ground):
            raise SolverError(f"conductor {k} touches a reference plane or the box")
        for m2 in cond_masks[k + 1 :]:
            if np.any(m & m2):
                raise SolverError("signal conductors overlap")
    fixed = ground.copy()
    for m in cond_masks:
        fixed |= m
    free = np.flatnonzero(~fixed)
    n = len(xs.conductors)

    def cap(vacuum: bool) -> FloatArray:
        eps = xs.eps_at(centroids[0], centroids[1], vacuum)
        k = asm(_laplace, basis, eps=b0.interpolate(eps)).tocsr()
        kff = k[free][:, free].tocsc()
        lu = splu(kff)
        phis = np.zeros((basis.N, n))
        for i, m in enumerate(cond_masks):
            u = np.zeros(basis.N)
            u[m] = 1.0
            rhs = -(k[free] @ u)
            u[free] = lu.solve(rhs)
            phis[:, i] = u
        out: FloatArray = EPS0 * (phis.T @ (k @ phis))
        return 0.5 * (out + out.T)

    c = cap(False)
    c0 = cap(True)
    return FemResult(c, c0, basis.N, mesh.t.shape[1])
