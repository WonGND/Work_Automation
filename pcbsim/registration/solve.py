"""Point-set registration: RANSAC (2-point hypotheses) → Umeyama/Kabsch → outline ICP.

Problem
-------
Find the similarity transform ``T(p) = s·R·M·p + t`` (see
:class:`~pcbsim.registration.transform.Similarity2D`) that maps reference
features of the mechanical drawing (mounting / tooling holes, fiducials,
optionally outline corners) onto the matching ECAD features, without knowing
the correspondences in advance.

1. **Hypotheses (RANSAC with 2-point minimal sets).** Two point pairs fix a 2D
   similarity. For every candidate scale ``s`` (1, or a list of unit factors
   such as 25.4 when unit-error detection is on) and reflection ``M`` (none /
   bottom-view mirror), each drawing pair (a, b) is matched against every ECAD
   pair (a', b') with ``| s·|ab| − |a'b'| | ≤ tol`` and compatible diameters
   and kinds; the pair lookup is a binary search in the sorted ECAD pair
   distances, so the search is exhaustive for small hole counts and randomly
   sub-sampled (fixed seed) otherwise [Fischler-Bolles].
   Rotation from the pair directions: ``θ = atan2(b'−a') − atan2(M(b−a))``.
2. **Consensus.** Each hypothesis transforms all drawing features; a feature is
   an inlier if its nearest compatible ECAD feature (k-d tree) lies within
   ``tol``; correspondences are made one-to-one greedily by distance. Score =
   (inlier count, −Σ residual).
3. **Refinement (Umeyama / Kabsch).** With correspondences fixed, the weighted
   least-squares similarity has the closed form [Umeyama-1991], [Kabsch-1976]::

       μ_x = Σ w x / Σ w,  μ_y = Σ w y / Σ w,   Σ_xy = Σ w (y−μ_y)(x−μ_x)ᵀ / Σ w
       U D Vᵀ = svd(Σ_xy),  S = diag(1, sign(det U det V))
       R = U S Vᵀ,  s = tr(D S) / σ_x²,  t = μ_y − s R μ_x

   The reflection is never chosen by the SVD: ``M`` is applied to the source
   points first and ``S`` forces a proper rotation, so mirror / no-mirror are
   separate, explicitly tested hypotheses. Re-match → re-fit until stable.
4. **Ambiguity.** All refined hypotheses whose inlier count equals the best and
   whose RMS is within the noise level are clustered (two transforms are the
   same if they move every corner of the square around the drawing's features
   by < tol — centred there, not at the file origin).
   More than one cluster means the hole pattern is symmetric: the result is
   flagged ``ambiguous`` and the user must name an asymmetric reference hole
   (``anchors``) — pcbsim does not guess.
5. **Outline ICP (second stage).** Points sampled on the drawing outline are
   projected exactly onto the ECAD outline segments (point-to-segment closest
   point); holes and outline samples are fitted jointly with weights by the
   same Umeyama step, iterated to convergence [Besl-McKay-1992]. With exact
   data the true transform is a fixed point. The ICP result is accepted only
   if it keeps every hole match and the hole RMS stays within max(2×, tol/10);
   otherwise a wrong drawing outline would pull the fit, so it is discarded.
   Anchors are checked after refinement (a 2-point hypothesis may miss a
   distant anchor by more than tol before refinement).

Residuals reported: RMS and max of matched features, RMS of outline samples.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree
from shapely.geometry import Polygon as ShPolygon

from pcbsim.errors import PcbsimError
from pcbsim.registration.transform import Similarity2D

FloatArray = NDArray[np.float64]

DEFAULT_SCALES: tuple[float, ...] = (1.0, 25.4, 1 / 25.4, 10.0, 0.1, 1000.0, 1e-3)
_UNIT_NAMES = {
    25.4: "drawing is in inch but read as mm (×25.4)",
    1 / 25.4: "drawing is in mm but read as inch (÷25.4)",
    10.0: "drawing is in cm but read as mm (×10)",
    0.1: "drawing is in mm but read as cm (÷10)",
    1000.0: "drawing is in m but read as mm (×1000)",
    1e-3: "drawing is in mm but read as m (÷1000)",
}


@dataclass(frozen=True, slots=True)
class Feature:
    """A reference point. ``diameter`` 0 for non-circular features (corners)."""

    x: float
    y: float
    diameter: float = 0.0
    kind: str = "hole"
    label: str = ""


@dataclass(frozen=True, slots=True)
class Anchor:
    """A user-fixed correspondence: drawing point ``mech`` ↔ board point ``board`` (m)."""

    mech: tuple[float, float]
    board: tuple[float, float]


@dataclass(frozen=True, slots=True)
class RegistrationOptions:
    tol: float = 0.3e-3
    diameter_tol: float = 0.15e-3
    mirror: str = "auto"  # auto | true | false
    allow_scale: bool = False
    scales: tuple[float, ...] = DEFAULT_SCALES
    free_scale: bool = False
    use_outline_icp: bool = True
    icp_iterations: int = 50
    outline_samples: int = 400
    outline_weight: float = 0.2
    max_pairs: int = 4000
    seed: int = 0
    anchors: tuple[Anchor, ...] = ()


@dataclass(slots=True)
class RegistrationResult:
    transform: Similarity2D
    matches: list[tuple[int, int]]
    rms: float
    max_residual: float
    n_src: int
    n_dst: int
    outline_rms: float | None = None
    outline_rms_before_icp: float | None = None
    ambiguous: bool = False
    alternatives: list[Similarity2D] = field(default_factory=list)
    unit_warning: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.ambiguous and len(self.matches) >= 2


class RegistrationError(PcbsimError, ValueError):
    """Registration impossible (too few features, nothing matches)."""


# --------------------------------------------------------------------------- core fit


def umeyama(
    src: FloatArray,
    dst: FloatArray,
    weights: FloatArray | None = None,
    *,
    mirror: bool = False,
    with_scale: bool = False,
    fixed_scale: float = 1.0,
) -> Similarity2D:
    """Weighted least-squares similarity ``dst ≈ s·R·M·src + t`` (closed form)."""
    x = np.asarray(src, dtype=np.float64).copy()
    y = np.asarray(dst, dtype=np.float64)
    if mirror:
        x[:, 0] = -x[:, 0]
    w = np.ones(len(x)) if weights is None else np.asarray(weights, dtype=np.float64)
    wsum = float(w.sum())
    mx = (w[:, None] * x).sum(0) / wsum
    my = (w[:, None] * y).sum(0) / wsum
    xc, yc = x - mx, y - my
    cov = (w[:, None, None] * (yc[:, :, None] * xc[:, None, :])).sum(0) / wsum
    u, d, vt = np.linalg.svd(cov)
    s_mat = np.diag([1.0, float(np.sign(np.linalg.det(u) * np.linalg.det(vt)) or 1.0)])
    r = u @ s_mat @ vt
    var_x = float((w * (xc**2).sum(1)).sum() / wsum)
    scale = float(np.trace(np.diag(d) @ s_mat) / var_x) if with_scale and var_x > 0 else fixed_scale
    t = my - scale * r @ mx
    angle = math.atan2(r[1, 0], r[0, 0])
    return Similarity2D(angle, float(t[0]), float(t[1]), scale, mirror)


def _compatible(a: Feature, b: Feature, scale: float, dtol: float) -> bool:
    if a.kind != b.kind:
        return False
    if a.diameter == 0.0 and b.diameter == 0.0:
        return True
    return abs(a.diameter * scale - b.diameter) <= dtol


def _match(
    t: Similarity2D,
    src: Sequence[Feature],
    dst: Sequence[Feature],
    tree: cKDTree,
    opts: RegistrationOptions,
) -> tuple[list[tuple[int, int]], FloatArray]:
    """Greedy one-to-one nearest compatible matching within ``tol``."""
    p = t.apply(np.array([[f.x, f.y] for f in src]))
    k = min(4, len(dst))
    dist, idx = tree.query(p, k=k, distance_upper_bound=opts.tol)
    dist = np.atleast_2d(np.asarray(dist).reshape(len(src), k))
    idx = np.atleast_2d(np.asarray(idx).reshape(len(src), k))
    cands: list[tuple[float, int, int]] = []
    for i in range(len(src)):
        for d, j in zip(dist[i], idx[i], strict=True):
            if np.isfinite(d) and _compatible(src[i], dst[int(j)], t.scale, opts.diameter_tol):
                cands.append((float(d), i, int(j)))
    cands.sort()
    used_i: set[int] = set()
    used_j: set[int] = set()
    pairs: list[tuple[int, int]] = []
    res: list[float] = []
    for d, i, j in cands:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append((i, j))
        res.append(d)
    return pairs, np.asarray(res, dtype=np.float64)


def _anchor_ok(t: Similarity2D, opts: RegistrationOptions) -> bool:
    for a in opts.anchors:
        if float(np.linalg.norm(t.apply([a.mech])[0] - np.asarray(a.board))) > opts.tol:
            return False
    return True


def _refit(
    t: Similarity2D,
    src: Sequence[Feature],
    dst: Sequence[Feature],
    tree: cKDTree,
    opts: RegistrationOptions,
) -> tuple[Similarity2D, list[tuple[int, int]], FloatArray]:
    pairs, res = _match(t, src, dst, tree, opts)
    for _ in range(10):
        if len(pairs) < 2:
            break
        s = np.array([[src[i].x, src[i].y] for i, _ in pairs])
        d = np.array([[dst[j].x, dst[j].y] for _, j in pairs])
        t_new = umeyama(s, d, mirror=t.mirror, with_scale=opts.free_scale, fixed_scale=t.scale)
        new_pairs, new_res = _match(t_new, src, dst, tree, opts)
        if len(new_pairs) < len(pairs):
            break
        stable = new_pairs == pairs
        t, pairs, res = t_new, new_pairs, new_res
        if stable:
            break
    return t, pairs, res


def _pair_index(pts: FloatArray) -> tuple[FloatArray, NDArray[np.int64]]:
    ij = np.array(list(itertools.combinations(range(len(pts)), 2)), dtype=np.int64)
    if len(ij) == 0:
        return np.zeros(0), np.zeros((0, 2), dtype=np.int64)
    d = np.linalg.norm(pts[ij[:, 0]] - pts[ij[:, 1]], axis=1)
    order = np.argsort(d)
    return d[order], ij[order]


def _hypotheses(
    src: Sequence[Feature], dst: Sequence[Feature], opts: RegistrationOptions
) -> list[Similarity2D]:
    sp = np.array([[f.x, f.y] for f in src])
    dp = np.array([[f.x, f.y] for f in dst])
    d_dist, d_ij = _pair_index(dp)
    s_pairs = list(itertools.combinations(range(len(src)), 2))
    rng = np.random.default_rng(opts.seed)
    if len(s_pairs) > opts.max_pairs:
        sel = rng.choice(len(s_pairs), opts.max_pairs, replace=False)
        s_pairs = [s_pairs[int(k)] for k in sel]
    # Long baselines first: their rotation estimate is least sensitive to noise.
    s_pairs.sort(key=lambda ij: -float(np.linalg.norm(sp[ij[0]] - sp[ij[1]])))
    scales = opts.scales if opts.allow_scale else (1.0,)
    mirrors = {"auto": (False, True), "true": (True,), "false": (False,)}[opts.mirror]
    out: list[Similarity2D] = []
    for scale in scales:
        for a, b in s_pairs:
            ds = scale * float(np.linalg.norm(sp[b] - sp[a]))
            if ds < 2 * opts.tol:
                continue
            lo = int(np.searchsorted(d_dist, ds - opts.tol, "left"))
            hi = int(np.searchsorted(d_dist, ds + opts.tol, "right"))
            for k in range(lo, hi):
                j0, j1 = int(d_ij[k, 0]), int(d_ij[k, 1])
                for c, e in ((j0, j1), (j1, j0)):
                    if not (
                        _compatible(src[a], dst[c], scale, opts.diameter_tol)
                        and _compatible(src[b], dst[e], scale, opts.diameter_tol)
                    ):
                        continue
                    for mir in mirrors:
                        out.append(umeyama(sp[[a, b]], dp[[c, e]], mirror=mir, fixed_scale=scale))
    return out


# --------------------------------------------------------------------------- outline ICP


def sample_boundary(poly: ShPolygon, n: int) -> FloatArray:
    """``n`` points evenly spaced along all rings, plus every vertex."""
    rings = [poly.exterior, *poly.interiors]
    total = sum(r.length for r in rings)
    pts: list[FloatArray] = []
    for r in rings:
        k = max(round(n * r.length / total), 4) if total > 0 else 4
        s = np.linspace(0.0, r.length, k, endpoint=False)
        pts.append(np.array([[p.x, p.y] for p in (r.interpolate(v) for v in s)]))
        pts.append(np.asarray(r.coords, dtype=np.float64)[:-1])
    return np.vstack(pts)


def _segments(poly: ShPolygon) -> tuple[FloatArray, FloatArray]:
    a_list, b_list = [], []
    for r in (poly.exterior, *poly.interiors):
        c = np.asarray(r.coords, dtype=np.float64)
        a_list.append(c[:-1])
        b_list.append(c[1:])
    return np.vstack(a_list), np.vstack(b_list)


def closest_on_segments(pts: FloatArray, a: FloatArray, b: FloatArray) -> FloatArray:
    """Exact closest point on any segment ``a_k b_k`` for every point (chunked)."""
    out = np.empty_like(pts)
    ab = b - a
    denom = np.maximum((ab * ab).sum(1), np.finfo(float).tiny)
    chunk = max(1, 2_000_000 // max(len(a), 1))
    for s in range(0, len(pts), chunk):
        p = pts[s : s + chunk]
        t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(2) / denom, 0.0, 1.0)
        q = a[None] + t[..., None] * ab[None]
        d2 = ((p[:, None, :] - q) ** 2).sum(2)
        k = d2.argmin(1)
        out[s : s + chunk] = q[np.arange(len(p)), k]
    return out


def outline_rms(t: Similarity2D, src_outline: ShPolygon, dst_outline: ShPolygon, n: int) -> float:
    a, b = _segments(dst_outline)
    p = t.apply(sample_boundary(src_outline, n))
    q = closest_on_segments(p, a, b)
    return float(np.sqrt(((p - q) ** 2).sum(1).mean()))


def icp_refine(
    t: Similarity2D,
    src_pts: FloatArray,
    dst_pts: FloatArray,
    src_outline: ShPolygon,
    dst_outline: ShPolygon,
    opts: RegistrationOptions,
) -> Similarity2D:
    """Joint hole + outline point-to-segment ICP, fixed mirror (and scale unless free)."""
    a, b = _segments(dst_outline)
    samples = sample_boundary(src_outline, opts.outline_samples)
    n_f = len(src_pts)
    w_o = opts.outline_weight * max(n_f, 1) / len(samples) if n_f else 1.0
    weights = np.concatenate([np.ones(n_f), np.full(len(samples), w_o)])
    for _ in range(opts.icp_iterations):
        q = closest_on_segments(t.apply(samples), a, b)
        src_all = np.vstack([src_pts, samples]) if n_f else samples
        dst_all = np.vstack([dst_pts, q]) if n_f else q
        t_new = umeyama(
            src_all,
            dst_all,
            weights,
            mirror=t.mirror,
            with_scale=opts.free_scale,
            fixed_scale=t.scale,
        )
        step = t_new.distance_to(t, 1.0)
        t = t_new
        if step < 1e-12:
            break
    return t


# --------------------------------------------------------------------------- driver


def _cluster(
    cands: list[Similarity2D], tol: float, dist: Callable[[Similarity2D, Similarity2D], float]
) -> list[Similarity2D]:
    reps: list[Similarity2D] = []
    for c in cands:
        if all(dist(c, r) > tol for r in reps):
            reps.append(c)
    return reps


def register(
    src: Sequence[Feature],
    dst: Sequence[Feature],
    opts: RegistrationOptions | None = None,
    *,
    src_outline: ShPolygon | None = None,
    dst_outline: ShPolygon | None = None,
) -> RegistrationResult:
    """Register drawing features ``src`` onto ECAD features ``dst``."""
    opts = opts or RegistrationOptions()
    warnings: list[str] = []
    if len(src) < 2 or len(dst) < 2:
        raise RegistrationError(
            f"need at least 2 reference features on each side (drawing {len(src)}, "
            f"board {len(dst)}); add mounting holes, fiducials or enable outline vertices"
        )
    dp = np.array([[f.x, f.y] for f in dst])
    sp_all = np.array([[f.x, f.y] for f in src])
    tree = cKDTree(dp)
    # Transforms are compared on a square around the drawing's features, so a
    # board far from its file origin does not inflate rotation differences.
    lo, hi = sp_all.min(axis=0), sp_all.max(axis=0)
    center = (float(lo[0] + hi[0]) / 2.0, float(lo[1] + hi[1]) / 2.0)
    extent = float(np.max(hi - lo)) / 2.0 or 1.0

    def same(a: Similarity2D, b: Similarity2D) -> float:
        return a.distance_to(b, extent, center)

    hyps = _hypotheses(src, dst, opts)
    if not hyps:
        raise RegistrationError(
            "no transform hypothesis: no pair of drawing features matches a pair of board "
            "features in distance/diameter (wrong units? enable allow_scale, or check the "
            "layer map)"
        )

    scored: list[tuple[int, float, Similarity2D, list[tuple[int, int]], FloatArray]] = []
    seen: list[Similarity2D] = []
    for h in hyps:
        if any(same(h, s) < opts.tol * 0.5 for s in seen):
            continue
        seen.append(h)
        t, pairs, res = _refit(h, src, dst, tree, opts)
        if len(pairs) < 2 or not _anchor_ok(t, opts):
            continue
        scored.append((len(pairs), float(np.sqrt((res**2).mean())), t, pairs, res))
    if not scored:
        if opts.anchors:
            raise RegistrationError(
                "no transform satisfies the registration anchors within tol; check that each "
                "anchor's drawing and board points really correspond"
            )
        raise RegistrationError("no hypothesis reached 2 inliers")
    best_n = max(s[0] for s in scored)
    top = [s for s in scored if s[0] == best_n]
    top.sort(key=lambda s: s[1])
    noise = max(top[0][1] * 3.0, opts.tol * 0.25)
    equal = [s for s in top if s[1] <= noise]
    reps = _cluster([s[2] for s in equal], opts.tol, same)
    _, rms, t, pairs, res = top[0]

    ambiguous = len(reps) > 1
    if ambiguous:
        warnings.append(
            f"{len(reps)} transforms fit the reference features equally well "
            f"({best_n} matches each): the hole pattern is symmetric. Add an asymmetric "
            "reference hole (registration.anchors) or a unique hole diameter."
        )

    unit_warning: str | None = None
    if abs(t.scale - 1.0) > 1e-3:
        near = min(_UNIT_NAMES, key=lambda k: abs(math.log(t.scale / k)))
        unit_warning = f"scale {t.scale:.6g} detected" + (
            f": {_UNIT_NAMES[near]}" if abs(math.log(t.scale / near)) < 1e-2 else ""
        )
        warnings.append(unit_warning)

    o_rms_before: float | None = None
    o_rms: float | None = None
    if src_outline is not None and dst_outline is not None:
        o_rms_before = outline_rms(t, src_outline, dst_outline, opts.outline_samples)
        if opts.use_outline_icp and not ambiguous:
            sp = np.array([[src[i].x, src[i].y] for i, _ in pairs])
            dq = np.array([[dst[j].x, dst[j].y] for _, j in pairs])
            t_icp = icp_refine(t, sp, dq, src_outline, dst_outline, opts)
            p_icp, r_icp = _match(t_icp, src, dst, tree, opts)
            rms_icp = float(np.sqrt((r_icp**2).mean())) if len(r_icp) else math.inf
            # The outline is what the checks are about to judge, so it must not drag
            # the hole fit: keep ICP only if it loses no match and the hole RMS stays
            # within max(2×, tol/10).
            if (
                len(p_icp) >= len(pairs)
                and rms_icp <= max(2.0 * rms, opts.tol * 0.1)
                and _anchor_ok(t_icp, opts)
            ):
                t, pairs, res, rms = t_icp, p_icp, r_icp, rms_icp
            else:
                warnings.append(
                    "outline ICP rejected: it degraded the hole fit (the drawing outline "
                    "probably differs from the board); transform from holes only"
                )
        o_rms = outline_rms(t, src_outline, dst_outline, opts.outline_samples)

    return RegistrationResult(
        transform=t,
        matches=pairs,
        rms=rms,
        max_residual=float(np.max(res)) if len(res) else math.nan,
        n_src=len(src),
        n_dst=len(dst),
        outline_rms=o_rms,
        outline_rms_before_icp=o_rms_before,
        ambiguous=ambiguous,
        alternatives=reps if ambiguous else [],
        unit_warning=unit_warning,
        warnings=warnings,
    )
