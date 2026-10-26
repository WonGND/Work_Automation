"""ECAD–MCAD consistency checks (after registration, everything in the board frame).

Holes
    Every ECAD hole with diameter ≥ ``mech_hole_min_diameter`` and every
    drawing hole is paired by nearest neighbour within ``hole_search_radius``
    (one-to-one, closest first). Paired: position deviation ``|p_mech − p_ecad|``
    vs ``hole_position_tol`` and diameter deviation vs ``hole_diameter_tol``.
    Unpaired ECAD hole → *missing in drawing*; unpaired drawing hole → *extra
    in drawing* (no drilled hole for a mechanical screw / pin).

Outline
    Symmetric Hausdorff distance ``d_H(A, B) = max(sup_a d(a, B), sup_b d(b, A))``
    between the exterior rings (shapely ``hausdorff_distance`` with 0.1 mm
    densification) vs ``outline_tol``. Cutouts (interior rings) are paired by
    nearest centroid; unpaired cutouts on either side and paired ones with
    Hausdorff > ``cutout_tol`` are NG.

Components
    The refdes of a drawing body comes from the ``ref`` group of the
    ``comp_3d`` layer pattern, else the nearest ECAD placement (same side)
    within ``component_search_radius``. Position deviation = centroid of the
    body footprint vs the ECAD reference point. Rotation: if the layer name has
    a ``rot`` group it is compared directly; otherwise the orientation of the
    body's minimum rotated rectangle is compared modulo 90° (a rectangle cannot
    tell 0° from 90°/180°), which still catches any skew that is not a multiple
    of 90°. Square or round bodies (aspect ≤ 1.05) have no measurable
    orientation and are reported OK with no value.

Heights
    The ceiling over a point is the minimum of: the default ``case_height``,
    the ``limit`` of every keepout polygon whose region intersects the item
    footprint, and the underside ``z_base`` of every ``case`` item above it.
    Clearance = ceiling − z_top; NG when clearance < ``min_clearance``. Items
    checked: drawing component bodies and heat sinks, plus ECAD placements with
    a height (Gerber X3 ``CHgt`` or pick-and-place CSV) that have no body.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

from pcbsim.io.cad import Hole, PlacedComponent
from pcbsim.registration.features import EcadData, MechBody
from pcbsim.registration.layermap import CheckOptions
from pcbsim.registration.solve import Feature, RegistrationResult


class Status(StrEnum):
    OK = "OK"
    NG = "NG"
    WARN = "WARN"


@dataclass(slots=True)
class CheckItem:
    category: str
    subject: str
    status: Status
    value: float | None = None
    limit: float | None = None
    unit: str = "mm"
    message: str = ""
    location: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass(slots=True)
class CheckReport:
    items: list[CheckItem] = field(default_factory=list)

    @property
    def n_ng(self) -> int:
        return sum(1 for i in self.items if i.status is Status.NG)

    @property
    def ok(self) -> bool:
        return self.n_ng == 0

    def ng(self) -> list[CheckItem]:
        return [i for i in self.items if i.status is Status.NG]

    def by_category(self, cat: str) -> list[CheckItem]:
        return [i for i in self.items if i.category == cat]


def _mm(x: float) -> float:
    return x * 1e3


def _st(ok: bool) -> Status:
    return Status.OK if ok else Status.NG


def _pair(
    a: list[tuple[float, float]], b: list[tuple[float, float]], radius: float
) -> tuple[list[tuple[int, int, float]], set[int], set[int]]:
    cands: list[tuple[float, int, int]] = []
    for i, p in enumerate(a):
        for j, q in enumerate(b):
            d = math.dist(p, q)
            if d <= radius:
                cands.append((d, i, j))
    cands.sort()
    ua: set[int] = set()
    ub: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for d, i, j in cands:
        if i in ua or j in ub:
            continue
        ua.add(i)
        ub.add(j)
        pairs.append((i, j, d))
    return pairs, set(range(len(a))) - ua, set(range(len(b))) - ub


# --------------------------------------------------------------------------- registration


def check_registration(res: RegistrationResult, opts: CheckOptions) -> list[CheckItem]:
    out = [
        CheckItem(
            "registration",
            "feature RMS",
            _st(res.rms <= opts.registration_rms_max and not res.ambiguous),
            _mm(res.rms),
            _mm(opts.registration_rms_max),
            message=f"{len(res.matches)} of {res.n_src} drawing features matched",
        )
    ]
    if res.ambiguous:
        out.append(
            CheckItem(
                "registration",
                "ambiguity",
                Status.NG,
                float(len(res.alternatives)),
                1.0,
                unit="solutions",
                message=res.warnings[0] if res.warnings else "symmetric reference pattern",
            )
        )
    if res.unit_warning:
        out.append(
            CheckItem(
                "registration",
                "scale",
                Status.WARN,
                res.transform.scale,
                1.0,
                unit="",
                message=res.unit_warning,
            )
        )
    if res.outline_rms is not None:
        out.append(
            CheckItem(
                "registration",
                "outline RMS (after ICP)",
                Status.OK,
                _mm(res.outline_rms),
                None,
                message=(
                    f"before ICP {_mm(res.outline_rms_before_icp or 0.0):.4f} mm"
                    if res.outline_rms_before_icp is not None
                    else ""
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- holes


def check_holes(
    ecad_holes: list[Hole], mech_holes: list[Feature], opts: CheckOptions
) -> list[CheckItem]:
    eh = [h for h in ecad_holes if h.diameter >= opts.mech_hole_min_diameter]
    a = [(h.x, h.y) for h in eh]
    b = [(f.x, f.y) for f in mech_holes]
    pairs, miss, extra = _pair(a, b, opts.hole_search_radius)
    out: list[CheckItem] = []
    for i, j, d in pairs:
        h, f = eh[i], mech_holes[j]
        name = f"hole @({_mm(h.x):.2f}, {_mm(h.y):.2f}) ⌀{_mm(h.diameter):.2f}"
        out.append(
            CheckItem(
                "hole_position",
                name,
                _st(d <= opts.hole_position_tol),
                _mm(d),
                _mm(opts.hole_position_tol),
                location=(h.x, h.y),
            )
        )
        dd = f.diameter - h.diameter
        out.append(
            CheckItem(
                "hole_diameter",
                name,
                _st(abs(dd) <= opts.hole_diameter_tol),
                _mm(dd),
                _mm(opts.hole_diameter_tol),
                message=f"drawing ⌀{_mm(f.diameter):.3f} mm vs drill ⌀{_mm(h.diameter):.3f} mm",
                location=(h.x, h.y),
            )
        )
    for i in sorted(miss):
        h = eh[i]
        out.append(
            CheckItem(
                "hole_missing",
                f"drill ⌀{_mm(h.diameter):.2f} @({_mm(h.x):.2f}, {_mm(h.y):.2f})",
                Status.NG,
                message="drilled hole has no counterpart in the mechanical drawing",
                location=(h.x, h.y),
            )
        )
    for j in sorted(extra):
        f = mech_holes[j]
        out.append(
            CheckItem(
                "hole_extra",
                f"drawing hole ⌀{_mm(f.diameter):.2f} @({_mm(f.x):.2f}, {_mm(f.y):.2f})",
                Status.NG,
                message="mechanical hole has no drilled hole on the board",
                location=(f.x, f.y),
            )
        )
    return out


# --------------------------------------------------------------------------- outline


def _hausdorff(a: BaseGeometry, b: BaseGeometry) -> float:
    return float(shapely.hausdorff_distance(a, b, densify=0.05))


def check_outline(
    ecad: Polygon | None, mech: Polygon | None, opts: CheckOptions
) -> list[CheckItem]:
    if ecad is None or mech is None:
        which = "Gerber profile" if ecad is None else "drawing outline"
        return [CheckItem("outline", "board outline", Status.WARN, message=f"no {which}")]
    d = _hausdorff(ecad.exterior, mech.exterior)
    out = [
        CheckItem(
            "outline",
            "board outline (Hausdorff)",
            _st(d <= opts.outline_tol),
            _mm(d),
            _mm(opts.outline_tol),
        )
    ]
    ec = [Polygon(r) for r in ecad.interiors]
    mc = [Polygon(r) for r in mech.interiors]
    a = [(p.centroid.x, p.centroid.y) for p in ec]
    b = [(p.centroid.x, p.centroid.y) for p in mc]
    radius = max([math.sqrt(p.area) for p in ec + mc] + [1e-3])
    pairs, miss, extra = _pair(a, b, radius)
    for i, j, _ in pairs:
        dh = _hausdorff(ec[i].exterior, mc[j].exterior)
        out.append(
            CheckItem(
                "cutout",
                f"cutout @({_mm(a[i][0]):.2f}, {_mm(a[i][1]):.2f})",
                _st(dh <= opts.cutout_tol),
                _mm(dh),
                _mm(opts.cutout_tol),
                location=a[i],
            )
        )
    for i in sorted(miss):
        out.append(
            CheckItem(
                "cutout",
                f"cutout @({_mm(a[i][0]):.2f}, {_mm(a[i][1]):.2f})",
                Status.NG,
                message="board cutout missing in the drawing",
                location=a[i],
            )
        )
    for j in sorted(extra):
        out.append(
            CheckItem(
                "cutout",
                f"drawing cutout @({_mm(b[j][0]):.2f}, {_mm(b[j][1]):.2f})",
                Status.NG,
                message="drawing cutout missing on the board",
                location=b[j],
            )
        )
    return out


# --------------------------------------------------------------------------- components


SQUARE_ASPECT = 1.05


def body_orientation(geom: BaseGeometry) -> float | None:
    """Orientation (degrees, [0, 90)) of the minimum rotated rectangle's first edge.

    ``None`` when the footprint has no orientation of its own: a square or round
    body (aspect ≤ 1.05, e.g. QFN, BGA, electrolytic can) whose minimum
    rectangle may be found at any angle — and a circle drawn as a polygon wobbles
    by ±180°/n.
    """
    rect = geom.minimum_rotated_rectangle
    if not isinstance(rect, Polygon):
        return None
    c = np.asarray(rect.exterior.coords)
    v, w = c[1] - c[0], c[2] - c[1]
    a, b = float(np.hypot(*v)), float(np.hypot(*w))
    if min(a, b) <= 0 or max(a, b) / min(a, b) <= SQUARE_ASPECT:
        return None
    return math.degrees(math.atan2(float(v[1]), float(v[0]))) % 90.0


def _angle_diff(a: float, b: float, period: float) -> float:
    d = (a - b) % period
    return min(d, period - d)


def assign_refs(
    bodies: list[MechBody], comps: list[PlacedComponent], radius: float
) -> list[MechBody]:
    """Fill ``ref`` of component bodies without one from the nearest ECAD placement."""
    taken = {b.ref for b in bodies if b.ref}
    free = [c for c in comps if c.ref not in taken]

    def candidates(b: MechBody) -> list[PlacedComponent]:
        return [c for c in free if c.side == b.side]

    out: list[MechBody] = []
    for b in bodies:
        if b.role != "comp_3d" or b.ref:
            out.append(b)
            continue
        cen = b.geometry.centroid
        best = min(candidates(b), key=lambda c: math.dist((c.x, c.y), (cen.x, cen.y)), default=None)
        if best is not None and math.dist((best.x, best.y), (cen.x, cen.y)) <= radius:
            free.remove(best)
            b = replace(b, ref=best.ref)
        out.append(b)
    return out


def check_components(
    bodies: list[MechBody],
    comps: list[PlacedComponent],
    opts: CheckOptions,
    rotations: dict[str, float] | None = None,
) -> list[CheckItem]:
    by_ref = {c.ref: c for c in comps}
    out: list[CheckItem] = []
    for b in bodies:
        if b.role != "comp_3d":
            continue
        if not b.ref:
            cen = b.geometry.centroid
            out.append(
                CheckItem(
                    "component_unmatched",
                    f"body on {b.layer}",
                    Status.WARN,
                    message="no ECAD component near this drawing body",
                    location=(cen.x, cen.y),
                )
            )
            continue
        c = by_ref.get(b.ref)
        if c is None:
            out.append(
                CheckItem(
                    "component_unmatched",
                    b.ref,
                    Status.NG,
                    message=f"drawing body {b.layer} names {b.ref}, which is not on the board",
                )
            )
            continue
        cen = b.geometry.centroid
        d = math.dist((cen.x, cen.y), (c.x, c.y))
        out.append(
            CheckItem(
                "component_position",
                b.ref,
                _st(d <= opts.component_position_tol),
                _mm(d),
                _mm(opts.component_position_tol),
                location=(c.x, c.y),
            )
        )
        if rotations is not None and b.ref in rotations:
            dr = _angle_diff(rotations[b.ref], c.rotation, 360.0)
            msg = "rotation from drawing layer name"
        else:
            orient = body_orientation(b.geometry)
            if orient is None:
                out.append(
                    CheckItem(
                        "component_rotation",
                        b.ref,
                        Status.OK,
                        None,
                        opts.component_rotation_tol,
                        unit="deg",
                        message="square/round body: rotation not checkable from its outline",
                        location=(c.x, c.y),
                    )
                )
                continue
            dr = _angle_diff(orient, c.rotation % 90.0, 90.0)
            msg = "body outline orientation, compared modulo 90°"
        out.append(
            CheckItem(
                "component_rotation",
                b.ref,
                _st(dr <= opts.component_rotation_tol),
                dr,
                opts.component_rotation_tol,
                unit="deg",
                message=msg,
                location=(c.x, c.y),
            )
        )
    return out


# --------------------------------------------------------------------------- heights


def ceiling_for(
    geom: BaseGeometry, bodies: list[MechBody], opts: CheckOptions, side: str = "top"
) -> float:
    """Lowest ceiling over ``geom`` from keepouts and case items on the same side."""
    ceil = opts.case_height if opts.case_height is not None else math.inf
    for k in bodies:
        if k.side != side:
            continue
        if k.role == "keepout" and k.limit is not None and k.geometry.intersects(geom):
            if k.geometry.intersection(geom).area > 0 or geom.area == 0:
                ceil = min(ceil, k.limit)
        elif k.role == "case" and k.z_base > 0 and k.geometry.intersects(geom):
            ceil = min(ceil, k.z_base)
    return ceil


def check_heights(
    bodies: list[MechBody], comps: list[PlacedComponent], opts: CheckOptions
) -> list[CheckItem]:
    out: list[CheckItem] = []
    with_body: set[str] = set()

    drawing_sides = {b.side for b in bodies}

    def one(name: str, geom: BaseGeometry, z_top: float, cat: str, side: str) -> None:
        ceil = ceiling_for(geom, bodies, opts, side)
        if not math.isfinite(ceil):
            return
        clr = ceil - z_top
        cen = geom.centroid
        out.append(
            CheckItem(
                cat,
                name,
                _st(clr >= opts.min_clearance),
                _mm(clr),
                _mm(opts.min_clearance),
                message=f"top {_mm(z_top):.2f} mm, ceiling {_mm(ceil):.2f} mm",
                location=(cen.x, cen.y),
            )
        )

    for b in bodies:
        if b.role == "comp_3d":
            if b.ref:
                with_body.add(b.ref)
            one(b.ref or b.layer, b.geometry, b.z_top, "height", b.side)
        elif b.role == "heatsink":
            one(f"heatsink {b.layer}", b.geometry, b.z_top, "height", b.side)
    for c in comps:
        # The drawing only constrains the side it shows; with no drawing items at all
        # (case_height alone) every side is checked.
        if c.height is None or c.ref in with_body:
            continue
        if drawing_sides and c.side not in drawing_sides:
            continue
        pt = Point(c.x, c.y).buffer(1e-4)
        one(f"{c.ref} (ECAD height)", pt, c.height, "height", c.side)
    return out


def run_checks(
    res: RegistrationResult,
    ecad: EcadData,
    mech_outline: Polygon | None,
    mech_holes: list[Feature],
    bodies: list[MechBody],
    opts: CheckOptions,
    rotations: dict[str, float] | None = None,
) -> CheckReport:
    rep = CheckReport()
    rep.items += check_registration(res, opts)
    rep.items += check_holes(ecad.holes, mech_holes, opts)
    rep.items += check_outline(ecad.outline, mech_outline, opts)
    rep.items += check_components(bodies, ecad.components, opts, rotations)
    rep.items += check_heights(bodies, ecad.components, opts)
    return rep
