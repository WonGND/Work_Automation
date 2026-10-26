"""DXF reader for the mechanical (MCAD) side of ECAD–MCAD registration.

Built on :mod:`ezdxf` and the public Autodesk *DXF Reference*. Everything is
converted to SI metres at this boundary; see :mod:`pcbsim.io.cad` for the result types.

Units
    The header variable ``$INSUNITS`` (group code 70) gives the drawing unit
    (0 unitless, 1 in, 2 ft, 3 mi, 4 mm, 5 cm, 6 m, 7 km, 8 µin, 9 mil, 10 yd, 11 Å,
    12 nm, 13 µm, 14 dm, 15 dam, 16 hm, 17 Gm, 18 AU, 19 ly, 20 pc, 21 US survey ft),
    see :data:`INSUNITS_TO_M`. ``unit_override`` wins over the header; a missing / zero
    ``$INSUNITS`` falls back to ``default_unit`` with a warning.

2.5D entities
    Planar entities (LINE, ARC, CIRCLE, LWPOLYLINE, …) carry an *elevation*
    (group code 38 for LWPOLYLINE, the z of the first point / centre otherwise) and a
    *thickness* (group code 39), the extrusion length along the *extrusion direction*
    (group codes 210/220/230). An item occupies ``[z_base, z_base + height]``; a negative
    effective thickness extrudes downwards, so ``z_base += thickness`` and
    ``height = |thickness|``.

Object coordinate system (OCS)
    Planar entities are stored in their OCS, derived from the extrusion vector with
    the DXF *arbitrary axis algorithm*: if ``|Nx| < 1/64`` and ``|Ny| < 1/64`` then
    ``Ax = Wy × N`` else ``Ax = Wz × N``; ``Ay = N × Ax``. For extrusion ``(0, 0, -1)``
    this mirrors X. All geometry here is converted to WCS with :func:`ezdxf.path.make_path`
    (which applies the OCS transform) or ``entity.ocs().to_wcs()``, so the XY footprint
    is correct for any extrusion.

Bulges
    LWPOLYLINE / POLYLINE vertices carry a *bulge* (group code 42): the tangent of a
    quarter of the included angle of the arc to the next vertex, i.e. the arc angle
    is θ = 4·atan(bulge) (positive = counter-clockwise, 0 = straight). ezdxf's path
    conversion turns bulge segments into arcs which are then flattened to chords with
    a maximum sagitta of ``chord_tol``.

Blocks
    INSERT (and MINSERT arrays) are expanded recursively with
    :meth:`ezdxf.entities.Insert.virtual_entities`, which applies insertion point,
    scale (including negative = mirrored), rotation and the block base point.
    Entities on layer ``"0"`` inside a block inherit the INSERT's layer (standard
    AutoCAD behaviour).

Joining
    Open LINE / ARC / polyline / spline pieces on the same layer whose endpoints
    coincide within 1 µm are joined (:func:`shapely.ops.linemerge` +
    :func:`shapely.ops.polygonize`) into closed polygons of kind ``"CHAIN"``. This is
    how FreeCAD and many MCAD tools export board outlines. Leftover open pieces remain
    ``LineString`` items.

3D entities
    3DFACE, polyface / polygon-mesh POLYLINE and MESH become :class:`Mesh3D`.
    Adjacent 3DFACEs are merged into **one Mesh3D per layer per block instance**
    (modelspace counts as one instance), because exporters typically emit one
    3DFACE per triangle of a single body. Every mesh also gets a footprint
    :class:`MechItem` (union of the XY projections of its faces, or the convex hull
    of its vertices when all faces are vertical) spanning ``[z_min, z_max]``.
    Polygon meshes (M×N) are reported with kind ``"POLYFACE"`` as well.

    ACIS bodies (3DSOLID, BODY, REGION, SURFACE, …) are proprietary SAT/SAB data and
    are not parsed; a warning asks the user to export those parts as STEP.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from ezdxf import path as ezpath
from ezdxf.document import Drawing
from ezdxf.entities.dxfgfx import DXFGraphic
from ezdxf.entities.insert import Insert
from ezdxf.filemanagement import readfile as ezdxf_readfile
from ezdxf.lldxf.const import DXFError, DXFStructureError
from ezdxf.math import Vec3
from ezdxf.render.mesh import MeshBuilder
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, polygonize, unary_union

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import MechCircle, MechDrawing, MechItem, Mesh3D

__all__ = [
    "INSUNITS_TO_M",
    "UNIT_NAMES_TO_M",
    "layer_polygons",
    "match_layers",
    "outline_with_cutouts",
    "read_dxf",
    "read_dxf_doc",
]

_INCH = 0.0254

#: ``$INSUNITS`` code → metres per drawing unit (DXF Reference, HEADER section).
#: Code 0 (unitless) maps to 0.0 and means "unknown".
INSUNITS_TO_M: dict[int, float] = {
    0: 0.0,
    1: _INCH,
    2: 12 * _INCH,
    3: 63360 * _INCH,
    4: 1e-3,
    5: 1e-2,
    6: 1.0,
    7: 1e3,
    8: 1e-6 * _INCH,
    9: 1e-3 * _INCH,
    10: 36 * _INCH,
    11: 1e-10,
    12: 1e-9,
    13: 1e-6,
    14: 1e-1,
    15: 1e1,
    16: 1e2,
    17: 1e9,
    18: 149_597_870_700.0,
    19: 9_460_730_472_580_800.0,
    20: 3.085_677_581_491_367e16,
    21: 1200.0 / 3937.0,
}

#: User-facing unit names → metres (``--dxf-unit``, ``unit_override``, ``default_unit``).
UNIT_NAMES_TO_M: dict[str, float] = {
    "mm": 1e-3,
    "cm": 1e-2,
    "m": 1.0,
    "um": 1e-6,
    "in": _INCH,
    "inch": _INCH,
    "mil": 1e-3 * _INCH,
    "ft": 12 * _INCH,
}

#: Annotation / non-geometric entities that are ignored without a warning.
_IGNORED = frozenset(
    {
        "TEXT",
        "MTEXT",
        "DIMENSION",
        "ARC_DIMENSION",
        "LARGE_RADIAL_DIMENSION",
        "POINT",
        "ATTRIB",
        "ATTDEF",
        "VIEWPORT",
        "LEADER",
        "MULTILEADER",
        "MLEADER",
        "TOLERANCE",
        "XLINE",
        "RAY",
        "IMAGE",
        "WIPEOUT",
    }
)

#: ACIS-based entities: proprietary SAT/SAB payload, never parsed.
_ACIS = frozenset(
    {
        "3DSOLID",
        "BODY",
        "REGION",
        "SURFACE",
        "EXTRUDEDSURFACE",
        "LOFTEDSURFACE",
        "REVOLVEDSURFACE",
        "SWEPTSURFACE",
        "PLANESURFACE",
        "NURBSURFACE",
    }
)

#: Entities converted with :func:`ezdxf.path.make_path` into 2D items.
_PATH_TYPES = frozenset(
    {"LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "LWPOLYLINE", "SOLID", "TRACE"}
)

#: Kinds that are joinable into ``"CHAIN"`` polygons when open.
_JOIN_TOL = 1e-6  # m
_MAX_DEPTH = 32


def _unit_scale(name: str) -> float:
    try:
        return UNIT_NAMES_TO_M[name.strip().lower()]
    except KeyError:
        known = ", ".join(sorted(UNIT_NAMES_TO_M))
        raise CadFormatError(f"unknown DXF unit {name!r} (known: {known})") from None


# --------------------------------------------------------------------------- public API


def read_dxf(
    path: str | Path,
    *,
    default_unit: str = "mm",
    unit_override: str | None = None,
    chord_tol: float = 1e-6,
) -> MechDrawing:
    """Read a DXF file. ``chord_tol`` is the maximum chord sagitta in metres."""
    p = Path(path)
    if not p.is_file():
        raise CadFormatError(f"{p}: DXF file not found")
    try:
        doc = ezdxf_readfile(p)
    except DXFStructureError:
        try:
            from ezdxf import recover

            doc, _auditor = recover.readfile(p)
        except (OSError, DXFError) as exc:
            raise CadFormatError(f"{p}: not a readable DXF file: {exc}") from exc
    except (OSError, DXFError, UnicodeDecodeError) as exc:
        raise CadFormatError(f"{p}: not a readable DXF file: {exc}") from exc
    return read_dxf_doc(
        doc, p, default_unit=default_unit, unit_override=unit_override, chord_tol=chord_tol
    )


def read_dxf_doc(
    doc: Drawing,
    path: Path | None = None,
    *,
    default_unit: str = "mm",
    unit_override: str | None = None,
    chord_tol: float = 1e-6,
) -> MechDrawing:
    """Convert an in-memory :mod:`ezdxf` document (modelspace) to a :class:`MechDrawing`."""
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    warnings: list[str] = []
    if unit_override is not None:
        scale = _unit_scale(unit_override)
    elif INSUNITS_TO_M.get(insunits, 0.0) > 0.0:
        scale = INSUNITS_TO_M[insunits]
    else:
        scale = _unit_scale(default_unit)
        if insunits not in INSUNITS_TO_M:
            warnings.append(f"unknown $INSUNITS {insunits}; assuming {default_unit}")
        else:
            warnings.append(f"drawing has no $INSUNITS; assuming {default_unit}")
    if chord_tol <= 0:
        raise CadFormatError("chord_tol must be positive")

    drawing = MechDrawing(path=path, unit_scale=scale, insunits=insunits, warnings=warnings)
    reader = _Reader(drawing, scale, chord_tol / scale)
    reader.process(doc.modelspace(), layer_override=None, depth=0)
    reader.finish()
    return drawing


def match_layers(drawing: MechDrawing, pattern: str) -> list[str]:
    """Layer names fully matching the regex ``pattern`` (case-insensitive), sorted."""
    rx = re.compile(pattern, re.IGNORECASE)
    return sorted(name for name in drawing.layers() if rx.fullmatch(name))


def layer_polygons(drawing: MechDrawing, pattern: str) -> list[Polygon]:
    """All polygon items (MultiPolygons exploded) on layers matching ``pattern``."""
    layers = set(match_layers(drawing, pattern))
    out: list[Polygon] = []
    for item in drawing.items:
        if item.layer in layers:
            out.extend(_polygons_of(item.geometry))
    return out


def outline_with_cutouts(drawing: MechDrawing, pattern: str) -> Polygon | None:
    """Largest polygon on matching layers with the polygons inside it as holes.

    Only the outermost nested level is subtracted (a pad inside a cutout is not
    re-added). Returns ``None`` when there is no polygon on the matching layers.
    """
    polys = [p for p in layer_polygons(drawing, pattern) if not p.is_empty and p.area > 0]
    if not polys:
        return None
    outer = max(polys, key=lambda p: p.area)
    shell = Polygon(outer.exterior)
    inside = [
        p
        for p in polys
        if p is not outer and p.area < outer.area and shell.contains(p) and not p.equals(outer)
    ]
    # drop exact duplicates, keep outermost level only
    unique: list[Polygon] = []
    for p in sorted(inside, key=lambda q: -q.area):
        if any(u.equals(p) for u in unique):
            continue
        unique.append(p)
    top = [p for p in unique if not any(q is not p and q.contains(p) for q in unique)]
    holes = [list(r.coords) for r in outer.interiors] + [list(p.exterior.coords) for p in top]
    result = Polygon(outer.exterior.coords, holes)
    if not result.is_valid:
        diff = shell.difference(unary_union([*top, *(Polygon(r) for r in outer.interiors)]))
        parts = _polygons_of(diff)
        if not parts:
            return None
        result = max(parts, key=lambda p: p.area)
    return result


# --------------------------------------------------------------------------- internals


def _polygons_of(geom: BaseGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if hasattr(geom, "geoms"):
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(_polygons_of(g))
        return out
    return []


def _clean_polygon(poly: Polygon) -> BaseGeometry:
    if poly.is_valid:
        return poly
    fixed = shapely.make_valid(poly)
    parts = _polygons_of(fixed)
    if not parts:
        return poly
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


@dataclass
class _Piece:
    layer: str
    coords: list[tuple[float, float]]
    z_base: float
    height: float
    handle: str


@dataclass
class _FaceGroup:
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)
    index: dict[tuple[float, float, float], int] = field(default_factory=dict)

    def add(self, pts: Iterable[tuple[float, float, float]]) -> None:
        face: list[int] = []
        for v in pts:
            key = (round(v[0], 12), round(v[1], 12), round(v[2], 12))
            idx = self.index.get(key)
            if idx is None:
                idx = len(self.vertices)
                self.vertices.append(v)
                self.index[key] = idx
            if not face or face[-1] != idx:
                face.append(idx)
        if len(face) > 1 and face[0] == face[-1]:
            face.pop()
        if len(face) >= 3:
            self.faces.append(tuple(face))


class _Reader:
    def __init__(self, drawing: MechDrawing, scale: float, flat_dist: float) -> None:
        self.d = drawing
        self.s = scale
        self.flat = flat_dist
        self.open_pieces: list[_Piece] = []
        self.acis: dict[str, list[str]] = defaultdict(list)
        self.unknown: dict[str, int] = defaultdict(int)

    # ---------------------------------------------------------------- traversal
    def process(
        self, entities: Iterable[DXFGraphic], layer_override: str | None, depth: int
    ) -> None:
        faces: dict[str, _FaceGroup] = defaultdict(_FaceGroup)
        for e in entities:
            try:
                self._entity(e, layer_override, depth, faces)
            except Exception as exc:  # never crash on one odd entity
                self.d.warnings.append(
                    f"skipped {e.dxftype()} (handle {e.dxf.get('handle', '?')}): {exc}"
                )
        for layer, grp in faces.items():
            self._add_mesh(layer, grp, "3DFACE")

    def _layer(self, e: DXFGraphic, override: str | None) -> str:
        layer = str(e.dxf.get("layer", "0"))
        if override is not None and layer == "0":
            return override
        return layer

    def _entity(
        self,
        e: DXFGraphic,
        override: str | None,
        depth: int,
        faces: dict[str, _FaceGroup],
    ) -> None:
        t = e.dxftype()
        layer = self._layer(e, override)
        if t == "INSERT":
            assert isinstance(e, Insert)
            self._insert(e, layer, depth)
        elif t in _IGNORED:
            return
        elif t in _ACIS:
            self.acis[t].append(layer)
        elif t == "3DFACE":
            pts = [self._v3(v) for v in e.wcs_vertices()]  # type: ignore[attr-defined]
            faces[layer].add(pts)
        elif t == "MESH":
            self._mesh_builder(layer, MeshBuilder.from_mesh(e), "MESH")  # type: ignore[arg-type]
        elif t == "POLYLINE":
            if e.is_poly_face_mesh or e.is_polygon_mesh:  # type: ignore[attr-defined]
                mb = MeshBuilder.from_polyface(e)  # type: ignore[arg-type]
                self._mesh_builder(layer, mb, "POLYFACE")
            else:
                self._path_entity(e, layer, "POLYLINE")
        elif t in _PATH_TYPES:
            self._path_entity(e, layer, t)
        elif t in ("HATCH", "MPOLYGON"):
            self._hatch(e, layer, t)
        else:
            self.unknown[t] += 1

    def _insert(self, ins: Insert, layer: str, depth: int) -> None:
        if depth >= _MAX_DEPTH:
            self.d.warnings.append(f"block nesting deeper than {_MAX_DEPTH}; INSERT skipped")
            return
        inserts: Iterable[Insert] = ins.multi_insert() if ins.mcount > 1 else [ins]
        for single in inserts:
            skipped: list[str] = []

            def _cb(entity: DXFGraphic, reason: str, _s: list[str] = skipped) -> None:
                _s.append(f"{entity.dxftype()}: {reason}")

            children = list(single.virtual_entities(skipped_entity_callback=_cb))
            self.process(children, layer, depth + 1)
            for msg in sorted(set(skipped)):
                if msg.split(":")[0] not in _IGNORED | _ACIS:
                    self.d.warnings.append(f"block {ins.dxf.name!r}: skipped {msg}")
                elif msg.split(":")[0] in _ACIS:
                    self.acis[msg.split(":")[0]].append(layer)

    # ---------------------------------------------------------------- helpers
    def _v3(self, v: Vec3) -> tuple[float, float, float]:
        return (v.x * self.s, v.y * self.s, v.z * self.s)

    def _z_extent(self, e: DXFGraphic, z_wcs: float) -> tuple[float, float]:
        """(z_base, height) in metres from WCS z (drawing units) and thickness (39)."""
        thickness = float(e.dxf.get("thickness", 0.0) or 0.0)
        if thickness == 0.0:
            return z_wcs * self.s, 0.0
        ext = Vec3(e.dxf.get("extrusion", (0.0, 0.0, 1.0)))
        nz = ext.normalize().z if not ext.is_null else 1.0
        dz = thickness * nz * self.s
        z0 = z_wcs * self.s
        if dz < 0:
            return z0 + dz, -dz
        return z0, dz

    def _flatten(self, p: ezpath.Path) -> list[tuple[float, float, float]]:
        return [self._v3(v) for v in p.flattening(self.flat, segments=8)]

    def _path_entity(self, e: DXFGraphic, layer: str, kind: str) -> None:
        p = ezpath.make_path(e)
        if len(p) == 0 and kind not in ("LINE",):
            return
        pts = self._flatten(p)
        if len(pts) < 2:
            return
        z_base, height = self._z_extent(e, p.start.z)
        handle = str(e.dxf.get("handle", "") or "")
        xy = [(x, y) for x, y, _ in pts]

        if kind == "CIRCLE":
            c = e.ocs().to_wcs(e.dxf.center)
            self.d.circles.append(
                MechCircle(
                    layer=layer,
                    x=c.x * self.s,
                    y=c.y * self.s,
                    diameter=2.0 * float(e.dxf.radius) * self.s,
                )
            )
        closed = kind in ("CIRCLE", "SOLID", "TRACE") or self._is_closed(e, kind, p)
        if closed and len(xy) >= 3:
            poly = _clean_polygon(Polygon(xy))
            if not poly.is_empty and poly.area > 0:
                self.d.items.append(MechItem(layer, kind, poly, z_base, height, handle))
                return
        if kind in ("SOLID", "TRACE", "CIRCLE"):
            return  # degenerate
        self.open_pieces.append(_Piece(layer, xy, z_base, height, handle))

    def _is_closed(self, e: DXFGraphic, kind: str, p: ezpath.Path) -> bool:
        if kind == "LINE":
            return False
        if kind == "LWPOLYLINE" and e.closed:  # type: ignore[attr-defined]
            return True
        if kind == "POLYLINE" and e.is_closed:  # type: ignore[attr-defined]
            return True
        if kind == "SPLINE" and e.closed:  # type: ignore[attr-defined]
            return True
        return bool(p.start.isclose(p.end, abs_tol=_JOIN_TOL / self.s))

    def _hatch(self, e: DXFGraphic, layer: str, kind: str) -> None:
        polys: list[Polygon] = []
        z = 0.0
        for bp in ezpath.from_hatch(e):  # type: ignore[arg-type]
            pts = self._flatten(bp)
            if len(pts) >= 3:
                z = pts[0][2]
                poly = _clean_polygon(Polygon([(x, y) for x, y, _ in pts]))
                polys.extend(q for q in _polygons_of(poly) if q.area > 0)
        if not polys:
            return
        # even-odd fill: nested boundary paths become holes
        geom: BaseGeometry = polys[0]
        for q in polys[1:]:
            geom = geom.symmetric_difference(q)
        handle = str(e.dxf.get("handle", "") or "")
        for part in _polygons_of(geom):
            self.d.items.append(MechItem(layer, kind, part, z, 0.0, handle))

    def _mesh_builder(self, layer: str, mb: MeshBuilder, kind: str) -> None:
        grp = _FaceGroup()
        for face in mb.faces:
            grp.add(self._v3(Vec3(mb.vertices[i])) for i in face)
        self._add_mesh(layer, grp, kind)

    def _add_mesh(self, layer: str, grp: _FaceGroup, kind: str) -> None:
        if not grp.faces:
            return
        verts = np.asarray(grp.vertices, dtype=np.float64).reshape(-1, 3)
        mesh = Mesh3D(layer=layer, vertices=verts, faces=tuple(grp.faces), kind=kind)
        self.d.meshes.append(mesh)
        projected: list[Polygon] = []
        for f in grp.faces:
            if len(f) < 3:
                continue
            poly = Polygon([(verts[i, 0], verts[i, 1]) for i in f])
            if not poly.is_valid:
                poly = _clean_polygon(poly)  # type: ignore[assignment]
            projected.extend(q for q in _polygons_of(poly) if q.area > 0)
        footprint: BaseGeometry
        if projected:
            footprint = unary_union(projected)
        else:
            footprint = shapely.MultiPoint([tuple(v) for v in verts[:, :2]]).convex_hull
        self.d.items.append(
            MechItem(layer, kind, footprint, mesh.z_min, mesh.z_max - mesh.z_min, "")
        )

    # ---------------------------------------------------------------- finish
    def finish(self) -> None:
        self._join_open_pieces()
        for t in sorted(self.acis):
            layers = ", ".join(sorted(set(self.acis[t])))
            n = len(self.acis[t])
            self.d.warnings.append(
                f"{n} {t} (ACIS) entities on layer(s) {layers} were skipped; "
                "export those parts as STEP and pass them with --step"
            )
        for t in sorted(self.unknown):
            self.d.warnings.append(f"{self.unknown[t]} unsupported {t} entities were ignored")

    def _join_open_pieces(self) -> None:
        by_layer: dict[str, list[_Piece]] = defaultdict(list)
        for piece in self.open_pieces:
            by_layer[piece.layer].append(piece)
        for layer in sorted(by_layer):
            pieces = by_layer[layer]
            _snap_endpoints(pieces, _JOIN_TOL)
            lines = [LineString(pc.coords) for pc in pieces if _has_length(pc.coords)]
            z_base = min(pc.z_base for pc in pieces)
            height = max(pc.z_base + pc.height for pc in pieces) - z_base
            if not lines:
                continue
            merged = linemerge(lines) if len(lines) > 1 else lines[0]
            merged_lines = list(_iter_lines(merged))
            faces = list(polygonize(merged_lines))
            chains: list[Polygon] = []
            for f in faces:
                shell = Polygon(f.exterior)
                if shell.area > 0 and not any(c.equals(shell) for c in chains):
                    chains.append(shell)
            for c in chains:
                self.d.items.append(MechItem(layer, "CHAIN", c, z_base, height, ""))
            if chains:
                used = unary_union([c.exterior for c in chains]).buffer(_JOIN_TOL)
                leftovers = [ln for ln in merged_lines if not used.contains(ln)]
            else:
                leftovers = merged_lines
            if len(leftovers) == len(lines) and not chains:
                # nothing joined: keep per-entity metadata
                for pc in pieces:
                    if _has_length(pc.coords):
                        self.d.items.append(
                            MechItem(
                                layer,
                                "LINE",
                                LineString(pc.coords),
                                pc.z_base,
                                pc.height,
                                pc.handle,
                            )
                        )
                continue
            for ln in leftovers:
                self.d.items.append(MechItem(layer, "LINE", ln, z_base, height, ""))


def _has_length(coords: list[tuple[float, float]]) -> bool:
    return len(coords) >= 2 and any(c != coords[0] for c in coords[1:])


def _iter_lines(geom: BaseGeometry) -> Iterator[LineString]:
    if isinstance(geom, LineString):
        yield geom
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from _iter_lines(g)


def _snap_endpoints(pieces: list[_Piece], tol: float) -> None:
    """Snap piece endpoints that lie within ``tol`` of each other to one shared point."""
    grid: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)

    def snap(pt: tuple[float, float]) -> tuple[float, float]:
        gx, gy = math.floor(pt[0] / tol), math.floor(pt[1] / tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in grid.get((gx + dx, gy + dy), ()):
                    if math.hypot(q[0] - pt[0], q[1] - pt[1]) <= tol:
                        return q
        grid[(gx, gy)].append(pt)
        return pt

    for pc in pieces:
        pc.coords[0] = snap(pc.coords[0])
        pc.coords[-1] = snap(pc.coords[-1])
