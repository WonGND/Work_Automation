"""End-to-end ECAD–MCAD match: load → register → map → check → thermal BCs → result.

The persisted result (``match.json``) holds the transform, the check table and
the derived thermal boundaries in board coordinates (metres, ECAD origin).
``pcbsim run`` reads it through the config key ``mechanical.match`` and

* refuses to simulate when the match is NG (exit code 5) unless ``--force``;
* appends the derived boundaries to ``thermal_boundaries`` (shifted by the
  config's ``mechanical.offset`` if the config uses a different origin than
  the Gerber files).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from pcbsim import __version__
from pcbsim.errors import ConfigError
from pcbsim.io.cad import MechDrawing
from pcbsim.registration.checks import CheckReport, Status, run_checks
from pcbsim.registration.features import (
    EcadData,
    MechBody,
    MechFeatures,
    extract_mech,
    load_ecad,
    register_mech,
    transform_body,
)
from pcbsim.registration.layermap import LayerMap
from pcbsim.registration.solve import Feature, RegistrationResult
from pcbsim.registration.thermal_bc import MechBoundary, derive_boundaries
from pcbsim.registration.transform import Similarity2D


@dataclass(slots=True)
class MatchResult:
    ecad: EcadData
    mech: MechFeatures
    registration: RegistrationResult
    src_features: list[Feature]
    dst_features: list[Feature]
    mech_outline: Polygon | None
    mech_holes: list[Feature]
    bodies: list[MechBody]
    report: CheckReport
    boundaries: list[MechBoundary] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report.ok and self.registration.ok


def _tf_feature(t: Similarity2D, f: Feature) -> Feature:
    p = t.apply([(f.x, f.y)])[0]
    return Feature(float(p[0]), float(p[1]), f.diameter * t.scale, f.kind, f.label)


def match(
    ecad: EcadData,
    drawing: MechDrawing,
    lmap: LayerMap,
    inputs: dict[str, Any] | None = None,
) -> MatchResult:
    mf = extract_mech(drawing, lmap)
    res, src, dst = register_mech(ecad, mf, lmap)
    t = res.transform
    outline = t.apply_geometry(mf.outline) if mf.outline is not None else None
    assert outline is None or isinstance(outline, Polygon)
    holes = [_tf_feature(t, f) for f in mf.holes]
    bodies = [transform_body(t, b) for b in mf.bodies]
    from pcbsim.registration.checks import assign_refs

    bodies = assign_refs(bodies, ecad.components, lmap.checks.component_search_radius)
    report = run_checks(res, ecad, outline, holes, bodies, lmap.checks)
    fps: dict[str, BaseGeometry] = {
        b.ref: b.geometry for b in bodies if b.role == "comp_3d" and b.ref
    }
    bcs, notes = derive_boundaries(bodies, ecad.components, lmap, ecad.outline, fps)
    return MatchResult(
        ecad, mf, res, src, dst, outline, holes, bodies, report, bcs, notes, inputs or {}
    )


def run_match(
    gerber_dir: Path | None,
    drills: list[Path],
    mech: list[Path],
    lmap: LayerMap,
    pnp: Path | None = None,
) -> MatchResult:
    from pcbsim.io.mech import merge_drawings, read_mech

    if not mech:
        raise ConfigError("match needs at least one mechanical file (--mech)")
    drawing: MechDrawing | None = None
    for p in mech:
        d = (
            read_mech(p, unit_override=lmap.units)
            if p.suffix.lower() in {".dxf", ".dwg"}
            else (read_mech(p))
        )
        drawing = d if drawing is None else merge_drawings(drawing, d)
    assert drawing is not None
    ecad = load_ecad(gerber_dir, drills, pnp)
    inputs = {
        "gerber": str(gerber_dir) if gerber_dir else None,
        "drill": [str(p) for p in drills],
        "mech": [str(p) for p in mech],
        "pnp": str(pnp) if pnp else None,
    }
    return match(ecad, drawing, lmap, inputs)


# --------------------------------------------------------------------------- persistence


def to_json_dict(m: MatchResult) -> dict[str, Any]:
    r = m.registration
    return {
        "pcbsim_version": __version__,
        "kind": "pcbsim.match",
        "ok": m.ok,
        "units": {"length": "m", "check_values": "mm (deg for rotation)"},
        "inputs": m.inputs,
        "registration": {
            "transform": r.transform.to_dict(),
            "rms_m": r.rms,
            "max_residual_m": r.max_residual,
            "outline_rms_m": r.outline_rms,
            "outline_rms_before_icp_m": r.outline_rms_before_icp,
            "matched": len(r.matches),
            "n_drawing_features": r.n_src,
            "n_board_features": r.n_dst,
            "ambiguous": r.ambiguous,
            "alternatives": [a.to_dict() for a in r.alternatives],
            "warnings": r.warnings,
        },
        "summary": {
            "ng": m.report.n_ng,
            "warn": sum(1 for i in m.report.items if i.status is Status.WARN),
            "ok": sum(1 for i in m.report.items if i.status is Status.OK),
        },
        "checks": [i.to_dict() for i in m.report.items],
        "thermal_boundaries": [b.to_dict() for b in m.boundaries],
        "notes": m.notes,
        "warnings": m.ecad.warnings + m.mech.warnings,
        "component_source": m.ecad.component_source,
    }


def write_match(m: MatchResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(to_json_dict(m)), indent=2, ensure_ascii=False), "utf-8")
    return path


def _clean(x: Any) -> Any:
    import math

    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    return x


@dataclass(frozen=True, slots=True)
class StoredMatch:
    ok: bool
    n_ng: int
    boundaries: tuple[MechBoundary, ...]
    ng_items: tuple[str, ...]
    path: Path


def load_match(path: Path) -> StoredMatch:
    try:
        doc = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"mechanical.match: file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"mechanical.match: {path} is not valid JSON: {exc}") from None
    if doc.get("kind") != "pcbsim.match":
        raise ConfigError(f"mechanical.match: {path} is not a pcbsim match result")
    ng = tuple(
        f"[{c['category']}] {c['subject']}: {c.get('message') or c.get('value')}"
        for c in doc.get("checks", [])
        if c.get("status") == "NG"
    )
    return StoredMatch(
        ok=bool(doc.get("ok")),
        n_ng=len(ng),
        boundaries=tuple(MechBoundary.from_dict(b) for b in doc.get("thermal_boundaries", [])),
        ng_items=ng,
        path=path,
    )


def board_bbox(m: MatchResult) -> Polygon:
    geoms: list[BaseGeometry] = []
    if m.ecad.outline is not None:
        geoms.append(m.ecad.outline)
    if m.mech_outline is not None:
        geoms.append(m.mech_outline)
    if not geoms:
        return box(0, 0, 0.01, 0.01)
    xs0, ys0, xs1, ys1 = zip(*(g.bounds for g in geoms), strict=True)
    return box(min(xs0), min(ys0), max(xs1), max(ys1))
