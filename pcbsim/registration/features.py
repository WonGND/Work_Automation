"""ECAD / MCAD feature extraction and the end-to-end ``match`` pipeline.

ECAD side (electrical reference = Gerber + Excellon):
    board outline + cutouts from the X2 ``Profile`` layer (centre lines),
    drill holes, X2 ``FiducialPad`` flashes, component placements from the X3
    component layer, ``TO.C`` copper flashes, or a pick-and-place CSV.

MCAD side (mechanical reference = DXF / DWG / STEP), selected by the layer map:
    outline, hole circles, fiducial circles, component bodies (``comp_3d``,
    refdes from the layer name or the nearest ECAD component after
    registration), heat sinks, height keepouts, chassis contacts, case.

Coordinate convention: the drawing's z = 0 is the board's top surface
(component side); z grows away from the board. Bottom-side items of a bottom
view drawing also use z ≥ 0 measured from the bottom surface.

The pipeline registers MCAD → ECAD (:func:`pcbsim.registration.solve.register`),
maps every mechanical item into the board frame, runs the checks of
:mod:`pcbsim.registration.checks`, and derives thermal boundary conditions
(:mod:`pcbsim.registration.thermal_bc`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import Hole, MechDrawing, MechItem, PlacedComponent, Slot
from pcbsim.registration.layermap import LayerMap, fullmatch
from pcbsim.registration.solve import (
    Anchor,
    Feature,
    RegistrationOptions,
    RegistrationResult,
    register,
)
from pcbsim.registration.transform import Similarity2D

CORNER_MIN_TURN_DEG = 30.0


@dataclass(slots=True)
class EcadData:
    outline: Polygon | None
    holes: list[Hole] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    components: list[PlacedComponent] = field(default_factory=list)
    fiducials: list[tuple[float, float]] = field(default_factory=list)
    component_source: str = ""
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MechBody:
    """A 3D / 2.5D item in the board frame (after registration)."""

    layer: str
    role: str  # comp_3d | heatsink | keepout | chassis | case
    geometry: BaseGeometry
    z_base: float
    z_top: float
    ref: str | None = None
    limit: float | None = None  # keepout ceiling (m above the board)


@dataclass(slots=True)
class MechFeatures:
    outline: Polygon | None
    holes: list[Feature] = field(default_factory=list)
    fiducials: list[Feature] = field(default_factory=list)
    bodies: list[MechBody] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- ECAD


def load_ecad(
    gerber_dir: Path | None,
    drills: Sequence[Path] = (),
    pnp: Path | None = None,
) -> EcadData:
    from pcbsim.io.excellon import load_drills
    from pcbsim.io.gerber import component_centroids, find_layer, load_gerber_dir, outline_polygons

    outline: Polygon | None = None
    comps: list[PlacedComponent] = []
    fids: list[tuple[float, float]] = []
    warnings: list[str] = []
    sources: list[str] = []
    comp_src = ""
    drill_paths = list(drills)
    if gerber_dir is not None:
        if not gerber_dir.is_dir():
            raise CadFormatError(f"Gerber directory not found: {gerber_dir}")
        layers = load_gerber_dir(gerber_dir)
        sources += [str(g.path) for g in layers if g.path is not None]
        prof = find_layer(layers, "Profile")
        if prof is None:
            warnings.append("no Profile (board outline) layer found among the Gerber files")
        else:
            boards = outline_polygons(prof)
            if boards:
                outline = boards[0]
                if len(boards) > 1:
                    warnings.append(
                        f"profile has {len(boards)} separate outlines; using the largest"
                    )
            else:
                warnings.append(f"{prof.path}: profile does not form a closed outline")
        for side in ("top", "bottom"):
            cl = find_layer(layers, "Component", side)
            if cl is not None and cl.components:
                comps += cl.components
                comp_src = "gerber_x3"
        if not comps:
            for g in layers:
                if g.kind.lower() != "copper" or g.side not in ("top", "bottom"):
                    continue
                for ref, (x, y) in component_centroids(g).items():
                    if ref not in {c.ref for c in comps}:
                        comps.append(PlacedComponent(ref, x, y, side=g.side))
            if comps:
                comp_src = "gerber_x2_pads"
        for g in layers:
            for f in g.flashes:
                fn = f.attributes.get("AperFunction", ())
                if fn and fn[0].lower().startswith("fiducialpad"):
                    fids.append((f.x, f.y))
            warnings += [f"{g.path.name if g.path else 'gerber'}: {w}" for w in g.warnings]
        if not drill_paths:
            drill_paths = sorted(
                p for p in gerber_dir.iterdir() if p.suffix.lower() in {".drl", ".xln", ".exc"}
            )
    holes: list[Hole] = []
    slots: list[Slot] = []
    if drill_paths:
        dd = load_drills(drill_paths)
        holes, slots = dd.holes, dd.slots
        warnings += dd.warnings
        sources += [str(p) for p in drill_paths]
    if pnp is not None:
        from pcbsim.io.pnp import parse_pnp

        comps = parse_pnp(pnp)
        comp_src = "pnp_csv"
        sources.append(str(pnp))
    # dedupe fiducials (same pad on mask/paste/copper)
    uniq: list[tuple[float, float]] = []
    for p in fids:
        if all(math.dist(p, q) > 1e-5 for q in uniq):
            uniq.append(p)
    return EcadData(outline, holes, slots, comps, uniq, comp_src, sources, warnings)


def corner_features(poly: Polygon, kind: str = "corner") -> list[Feature]:
    """Outline vertices whose direction changes by more than 30° (arc chords excluded)."""
    ring = np.asarray(poly.exterior.simplify(1e-6).coords, dtype=np.float64)[:-1]
    out: list[Feature] = []
    n = len(ring)
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        u, v = b - a, c - b
        nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
        if nu == 0 or nv == 0:
            continue
        cosang = float(np.clip(np.dot(u, v) / (nu * nv), -1.0, 1.0))
        if math.degrees(math.acos(cosang)) >= CORNER_MIN_TURN_DEG:
            out.append(Feature(float(b[0]), float(b[1]), 0.0, kind))
    return out


def ecad_reference_features(ecad: EcadData, lmap: LayerMap) -> list[Feature]:
    e = lmap.ecad
    feats = [
        Feature(h.x, h.y, h.diameter, "hole", f"{h.tool}")
        for h in ecad.holes
        if h.diameter >= e.ref_hole_min_diameter and (e.ref_holes == "all" or h.plated is not True)
    ]
    if lmap.registration.use_fiducials:
        feats += [Feature(x, y, 0.0, "fiducial") for x, y in ecad.fiducials]
    if lmap.registration.use_outline_vertices and ecad.outline is not None:
        feats += corner_features(ecad.outline)
    return feats


# --------------------------------------------------------------------------- MCAD


def _ref_from_match(pattern: str | None, layer: str) -> str | None:
    m = fullmatch(pattern, layer)
    if m is None:
        return None
    gd = m.groupdict()
    return gd.get("ref") or None


def extract_mech(drawing: MechDrawing, lmap: LayerMap) -> MechFeatures:
    from pcbsim.io.dxf import outline_with_cutouts

    ml = lmap.mech
    warnings = list(drawing.warnings)
    outline = outline_with_cutouts(drawing, ml.outline)
    if outline is None:
        warnings.append(f"no closed outline on drawing layers matching {ml.outline!r}")
    holes = [
        Feature(c.x, c.y, c.diameter, "hole", c.layer)
        for c in drawing.circles
        if fullmatch(ml.holes, c.layer)
    ]
    fids = [
        Feature(c.x, c.y, 0.0, "fiducial", c.layer)
        for c in drawing.circles
        if fullmatch(ml.fiducials, c.layer)
    ]
    bodies: list[MechBody] = []
    roles: list[tuple[str, str | None]] = [
        ("comp_3d", ml.comp_3d),
        ("heatsink", ml.heatsink),
        ("keepout", ml.keepout),
        ("chassis", ml.chassis),
        ("case", ml.case),
    ]
    items: list[MechItem] = list(drawing.items)
    for it in items:
        if it.kind == "CIRCLE" and fullmatch(ml.holes, it.layer):
            continue
        for role, pattern in roles:
            m = fullmatch(pattern, it.layer)
            if m is None:
                continue
            geom = it.geometry
            if isinstance(geom, LineString):
                if geom.is_ring:
                    geom = Polygon(geom.coords)
                elif role != "comp_3d":
                    continue
            gd = m.groupdict()
            limit: float | None = None
            hval = gd.get("h") or gd.get("height")
            if role == "keepout":
                if hval is not None:
                    limit = float(hval) * _map_unit_scale(lmap)
                elif it.height > 0 or it.z_base > 0:
                    limit = it.z_top
                else:
                    limit = 0.0
            bodies.append(
                MechBody(it.layer, role, geom, it.z_base, it.z_top, gd.get("ref") or None, limit)
            )
            break
    if ml.comp_3d is not None:
        for b in drawing.boxes:
            if fullmatch(ml.comp_3d, b.name) or b.name.startswith("solid_"):
                bodies.append(
                    MechBody(
                        b.name,
                        "comp_3d",
                        Polygon(
                            [(b.xmin, b.ymin), (b.xmax, b.ymin), (b.xmax, b.ymax), (b.xmin, b.ymax)]
                        ),
                        b.zmin,
                        b.zmax,
                        _ref_from_match(ml.comp_3d, b.name),
                    )
                )
    return MechFeatures(outline, holes, fids, bodies, warnings)


def _map_unit_scale(lmap: LayerMap) -> float:
    from pcbsim.units import Kind, to_si

    return to_si(1.0, lmap.units or "mm", Kind.LENGTH)


def mech_reference_features(mf: MechFeatures, lmap: LayerMap) -> list[Feature]:
    feats = list(mf.holes)
    if lmap.registration.use_fiducials:
        feats += mf.fiducials
    if lmap.registration.use_outline_vertices and mf.outline is not None:
        feats += corner_features(mf.outline)
    return feats


def registration_options(lmap: LayerMap) -> RegistrationOptions:
    r = lmap.registration
    return RegistrationOptions(
        tol=r.tol,
        diameter_tol=r.diameter_tol,
        mirror=r.mirror,
        allow_scale=r.allow_scale,
        use_outline_icp=r.use_outline_icp,
        anchors=tuple(Anchor(a.mech, a.board) for a in r.anchors),
    )


def transform_body(t: Similarity2D, b: MechBody) -> MechBody:
    s = t.scale
    return MechBody(
        b.layer,
        b.role,
        t.apply_geometry(b.geometry),
        b.z_base * s,
        b.z_top * s,
        b.ref,
        b.limit,
    )


def register_mech(
    ecad: EcadData, mf: MechFeatures, lmap: LayerMap
) -> tuple[RegistrationResult, list[Feature], list[Feature]]:
    src = mech_reference_features(mf, lmap)
    dst = ecad_reference_features(ecad, lmap)
    res = register(
        src,
        dst,
        registration_options(lmap),
        src_outline=mf.outline,
        dst_outline=ecad.outline,
    )
    return res, src, dst
