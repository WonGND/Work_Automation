"""KiCad ``.kicad_pcb`` reader (KiCad 6–9 S-expression board files) → pcbsim geometry.

What is read (all from the public format description, KiCad developer docs
"Board File Format" / "Footprint Library File Format", <https://dev-docs.kicad.org/en/file-formats/>):

==================  =================================================================
file item           pcbsim
==================  =================================================================
``setup/stackup``   :class:`~pcbsim.model.Stackup` (copper, dielectric incl. sub-layers,
                    solder mask; ``epsilon_r`` / ``loss_tangent`` per dielectric)
``layers``          copper layer roles (signal / power → plane / mixed) and user names
``Edge.Cuts``       board outline (largest closed ring) and cutouts (rings inside it)
``net``             :class:`~pcbsim.model.Net` (``GND``-like names → ground)
``segment``/``arc`` copper: centre line buffered by ``width/2`` with round caps
``zone``            copper: every ``filled_polygon`` (unfilled zones: outline minus
                    other-net copper grown by the zone clearance, with a note)
``pad``             copper on each listed copper layer; plated holes become vias
``via``             :class:`~pcbsim.model.Via` between its two layers + annular rings
``footprint``       component outline (courtyard, else pad hull), side, pads
==================  =================================================================

Coordinates
-----------
KiCad stores millimetres with **y pointing down**. pcbsim uses metres with y up.
With ``origin = "board"`` (default) a point maps to
``(x − x_min, y_max − y) · 10⁻³`` where the extents are those of ``Edge.Cuts``,
so the lower-left corner of the board is (0, 0), as in the YAML examples.
``"aux"`` measures from the drill/place (``aux_axis_origin``), ``"file"`` keeps
the file origin (only y negated).

Footprint items are local: ``p = p_fp + R(θ_fp)·(x_l, −y_l)`` in the y-up frame,
with ``R`` a counter-clockwise rotation (KiCad angles are CCW on screen). Pad
``(at x y θ)`` angles in a *board* file include the footprint rotation, so the
pad shape is rotated by ``θ`` alone. Bottom-side footprints are stored already
mirrored, so no extra flip is applied.

Arcs (``start``/``mid``/``end``) are approximated by chords with a sagitta of
at most ``ARC_TOL`` (1 µm): ``n = ⌈sweep / (2 acos(1 − tol/r))⌉``.

Copper of one net on one layer is merged (union) before it becomes
:class:`~pcbsim.model.Shape` polygons. Cells are later assigned by their centre
(:mod:`pcbsim.mesh`), so tracks narrower than the mesh cell can vanish;
:attr:`KicadBoard.min_width` records the narrowest track per net for the check.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, box
from shapely.geometry import Polygon as SPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from pcbsim.errors import ConfigError
from pcbsim.io.sexpr import Node, parse
from pcbsim.model import Layer, LayerKind, LayerRole, Net, NetKind, Polygon, Shape, Side, Via

ARC_TOL = 1e-3  # mm (1 µm) maximum chord sagitta
CU_DEFAULT = 0.035  # mm, stack-up without a setup/stackup section
MASK_DEFAULT = 0.01  # mm
DEFAULT_CLEARANCE = 0.2  # mm, unfilled-zone fallback when the zone has none

_GROUND = re.compile(r"^/?(?:[ADPS]?GND\w*|VSS\w*|GROUND\w*|0V)$", re.I)
_CU = re.compile(r"^(F|B|In\d+)\.Cu$")


@dataclass(frozen=True, slots=True)
class Footprint:
    """A placed footprint. ``outline`` is in metres (pcbsim frame)."""

    ref: str
    side: Side
    outline: Polygon
    x: float
    y: float
    rotation: float
    value: str = ""
    pad_nets: tuple[str, ...] = ()


@dataclass(slots=True)
class KicadBoard:
    """Everything pcbsim takes from a ``.kicad_pcb`` file (SI units)."""

    path: Path
    name: str
    stackup: tuple[Layer, ...]
    materials: dict[str, dict[str, Any]]
    outline: Polygon
    nets: tuple[Net, ...]
    shapes: tuple[Shape, ...]
    vias: tuple[Via, ...]
    footprints: dict[str, Footprint]
    layer_alias: dict[str, str]
    min_width: dict[str, float]
    counts: dict[str, int]
    notes: list[str] = field(default_factory=list)

    def resolve_layer(self, name: str) -> str:
        """pcbsim layer name for a KiCad canonical (``F.Cu``) or user (``L1_TOP``) name."""
        return self.layer_alias.get(name, name)

    def resolve_net(self, name: str) -> str:
        names = {n.name for n in self.nets}
        if name in names:
            return name
        for cand in (f"/{name}", name.lstrip("/")):
            if cand in names:
                return cand
        return name


# ------------------------------------------------------------------ geometry helpers


def _arc_points(
    s: tuple[float, float], m: tuple[float, float], e: tuple[float, float]
) -> list[tuple[float, float]]:
    """Chord points of the circular arc start → mid → end (inclusive)."""
    ax, ay = s
    bx, by = m
    cx, cy = e
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [s, e]
    ux = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / d
    uy = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / d
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(by - uy, bx - ux)
    a1 = math.atan2(cy - uy, cx - ux)
    ccw = ((am - a0) % (2 * math.pi)) < ((a1 - a0) % (2 * math.pi))
    sweep = (a1 - a0) % (2 * math.pi)
    if not ccw:
        sweep -= 2 * math.pi
    if s == e:
        sweep = 2 * math.pi if ccw else -2 * math.pi
    step = 2.0 * math.acos(max(1.0 - ARC_TOL / r, -1.0)) if r > ARC_TOL else math.pi / 2
    n = max(math.ceil(abs(sweep) / max(step, 1e-6)), 2)
    pts = [
        (ux + r * math.cos(a0 + sweep * k / n), uy + r * math.sin(a0 + sweep * k / n))
        for k in range(n + 1)
    ]
    pts[0], pts[-1] = s, e
    return pts


def _circle(cx: float, cy: float, r: float) -> SPolygon:
    n = (
        max(math.ceil(2 * math.pi / (2.0 * math.acos(max(1.0 - ARC_TOL / r, -1.0)))), 16)
        if r > ARC_TOL
        else 16
    )
    t = np.linspace(0.0, 2 * math.pi, min(n, 720), endpoint=False)
    return SPolygon(np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)]))


def _polygons(g: BaseGeometry) -> list[SPolygon]:
    if isinstance(g, SPolygon):
        return [g] if not g.is_empty else []
    if isinstance(g, MultiPolygon):
        return [p for p in g.geoms if not p.is_empty]
    if hasattr(g, "geoms"):
        out: list[SPolygon] = []
        for sub in g.geoms:
            out += _polygons(sub)
        return out
    return []


def _clean(g: BaseGeometry) -> BaseGeometry:
    return g if g.is_valid else shapely.make_valid(g).buffer(0)


def _pts(node: Node) -> list[tuple[float, float]]:
    """``(pts (xy x y) ... (arc (start ..) (mid ..) (end ..)))`` in file coordinates."""
    out: list[tuple[float, float]] = []
    for c in node.children:
        if c.tag == "xy":
            v = c.floats()
            out.append((v[0], v[1]))
        elif c.tag == "arc":
            s, m, e = c.xy("start"), c.xy("mid"), c.xy("end")
            if s is None or m is None or e is None:
                raise ConfigError("(pts (arc ...)): needs start, mid and end")
            arc = _arc_points(s, m, e)
            if out and out[-1] == arc[0]:
                arc = arc[1:]
            out += arc
    return out


class _Frame:
    """File (mm, y down) → working frame (mm, y up, translated). SI only at the end."""

    def __init__(self, dx: float = 0.0, dy: float = 0.0) -> None:
        self.dx, self.dy = dx, dy

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.dx, self.dy - y)

    def many(self, pts: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
        return [self.p(x, y) for x, y in pts]


class _Local:
    """Footprint-local (mm, y down) → working frame via the footprint placement."""

    def __init__(self, frame: _Frame, x: float, y: float, angle: float) -> None:
        self.ox, self.oy = frame.p(x, y)
        self.c, self.s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def p(self, x: float, y: float) -> tuple[float, float]:
        lx, ly = x, -y
        return (self.ox + self.c * lx - self.s * ly, self.oy + self.s * lx + self.c * ly)

    def many(self, pts: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
        return [self.p(x, y) for x, y in pts]


_Mapper = _Frame | _Local


def _graphic(node: Node, f: _Mapper) -> tuple[BaseGeometry | None, bool]:
    """Geometry of a gr_*/fp_* item in the working frame and whether it is a closed area."""
    kind = node.tag.split("_", 1)[-1]
    if kind == "line":
        s, e = node.xy("start"), node.xy("end")
        if s is None or e is None:
            return None, False
        return LineString(f.many([s, e])), False
    if kind == "arc":
        s, m, e = node.xy("start"), node.xy("mid"), node.xy("end")
        if s is None or e is None:
            return None, False
        if m is None:
            return None, False
        return LineString(f.many(_arc_points(s, m, e))), False
    if kind == "rect":
        s, e = node.xy("start"), node.xy("end")
        if s is None or e is None:
            return None, False
        ring = [s, (e[0], s[1]), e, (s[0], e[1])]
        return SPolygon(f.many(ring)), True
    if kind == "circle":
        c, e = node.xy("center"), node.xy("end")
        if c is None or e is None:
            return None, False
        cx, cy = f.p(*c)
        return _circle(cx, cy, math.hypot(e[0] - c[0], e[1] - c[1])), True
    if kind == "poly":
        pn = node.find("pts")
        if pn is None:
            return None, False
        pts = _pts(pn)
        if len(pts) < 3:
            return None, False
        return SPolygon(f.many(pts)), True
    return None, False


def _boundary_lines(g: BaseGeometry, closed: bool) -> list[BaseGeometry]:
    return [g.exterior] if closed and isinstance(g, SPolygon) else [g]


def _layers_of(node: Node) -> list[str]:
    ln = node.find("layer")
    if ln is not None:
        return ln.atoms[:1]
    ls = node.find("layers")
    return ls.atoms if ls is not None else []


# ------------------------------------------------------------------ stack-up


_DIELECTRIC_BASE = (("ro4350", "ro4350b"), ("fr4", "fr4"), ("fr-4", "fr4"))


def _material_base(text: str, notes: list[str], where: str) -> str:
    key = re.sub(r"[^a-z0-9-]", "", text.lower())
    for pat, base in _DIELECTRIC_BASE:
        if pat in key:
            return base
    if text and text.lower() not in ("not specified", "none"):
        notes.append(
            f"{where}: material {text!r} not in the database — "
            "fr4 thermal values with the file's εr"
        )
    return "fr4"


def _stackup(
    root: Node, cu_names: Sequence[str], roles: dict[str, LayerRole], notes: list[str]
) -> tuple[tuple[Layer, ...], dict[str, dict[str, Any]]]:
    setup = root.find("setup")
    st = setup.find("stackup") if setup is not None else None
    mats: dict[str, dict[str, Any]] = {}
    layers: list[Layer] = []
    if st is None:
        general = root.find("general")
        total = (general.number("thickness") if general is not None else None) or 1.6
        n = len(cu_names)
        d = max(total - n * CU_DEFAULT, 0.1) / max(n - 1, 1)
        notes.append(
            f"no stack-up in the file: {n} × 35 µm copper, FR-4 dielectrics of {d:.3f} mm "
            f"(board {total:g} mm); define it in KiCad (Board Setup → Physical Stackup) "
            "or in 'board.stackup'"
        )
        for i, name in enumerate(cu_names):
            layers.append(
                Layer(
                    name,
                    LayerKind.CONDUCTOR,
                    CU_DEFAULT * 1e-3,
                    "copper_ed",
                    roles.get(name, LayerRole.NONE),
                )
            )
            if i < n - 1:
                layers.append(Layer(f"dielectric {i + 1}", LayerKind.DIELECTRIC, d * 1e-3, "fr4"))
        return tuple(layers), mats

    for ln in st.find_all("layer"):
        name = ln.atom(0)
        typ = (ln.value("type") or "").lower()
        if _CU.match(name):
            t = ln.number("thickness") or CU_DEFAULT
            layers.append(
                Layer(
                    name,
                    LayerKind.CONDUCTOR,
                    t * 1e-3,
                    "copper_ed",
                    roles.get(name, LayerRole.NONE),
                )
            )
            continue
        if "solder mask" in typ or name in ("F.Mask", "B.Mask"):
            t = ln.number("thickness") or MASK_DEFAULT
            mname = f"kicad:{name}"
            props: dict[str, Any] = {}
            er = ln.number("epsilon_r")
            if er is not None:
                props["eps_r"] = er
            mats[mname] = {"base": "soldermask", **props}
            layers.append(Layer(name, LayerKind.SOLDERMASK, t * 1e-3, mname))
            continue
        if not (name.startswith("dielectric") or typ in ("core", "prepreg")):
            continue
        subs: list[dict[str, Any]] = [{}]
        for a in ln.args[1:]:
            if isinstance(a, str):
                if a == "addsublayer":
                    subs.append({})
                continue
            if a.tag in ("thickness", "epsilon_r", "loss_tangent") and a.atoms:
                subs[-1][a.tag] = a.num(0)
            elif a.tag == "material" and a.atoms:
                subs[-1]["material"] = a.atom(0)
        for k, sub in enumerate(subs):
            t_sub = sub.get("thickness")
            if t_sub is None or t_sub <= 0:
                notes.append(f"stack-up {name}: dielectric without thickness skipped")
                continue
            lname = name if len(subs) == 1 else f"{name}.{k + 1}"
            mname = f"kicad:{lname}"
            base = _material_base(str(sub.get("material", "")), notes, f"stack-up {lname}")
            props = {"base": base}
            if "epsilon_r" in sub:
                props["eps_r"] = sub["epsilon_r"]
            if "loss_tangent" in sub:
                props["tan_d"] = sub["loss_tangent"]
            mats[mname] = props
            layers.append(Layer(lname, LayerKind.DIELECTRIC, float(t_sub) * 1e-3, mname))
    missing = [n for n in cu_names if n not in {la.name for la in layers}]
    if missing:
        raise ConfigError(f"KiCad stack-up lacks copper layer(s) {missing}")
    return tuple(layers), mats


# ------------------------------------------------------------------ pads


def _pad_shape(pad: Node, notes: list[str], where: str) -> BaseGeometry:
    """Pad copper centred at the origin, unrotated, y up."""
    shape = pad.atom(2, "rect")
    size = pad.find("size")
    w, h = (size.num(0), size.num(1, size.num(0))) if size is not None else (0.0, 0.0)
    if w <= 0 or h <= 0:
        return SPolygon()
    if shape == "circle":
        return _circle(0.0, 0.0, w / 2)
    if shape == "oval":
        if abs(w - h) < 1e-9:
            return _circle(0.0, 0.0, w / 2)
        if w > h:
            return LineString([(-(w - h) / 2, 0), ((w - h) / 2, 0)]).buffer(h / 2, quad_segs=16)
        return LineString([(0, -(h - w) / 2), (0, (h - w) / 2)]).buffer(w / 2, quad_segs=16)
    if shape == "roundrect":
        r = min(pad.number("roundrect_rratio") or 0.25, 0.5) * min(w, h)
        if r <= 0:
            return box(-w / 2, -h / 2, w / 2, h / 2)
        return box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r).buffer(r, quad_segs=8)
    if shape == "custom":
        opts = pad.find("options")
        anchor = opts.value("anchor", "rect") if opts is not None else "rect"
        g: BaseGeometry = (
            _circle(0.0, 0.0, w / 2) if anchor == "circle" else box(-w / 2, -h / 2, w / 2, h / 2)
        )
        prims = pad.find("primitives")
        parts = [g]
        if prims is not None:
            flip = _Local(_Frame(), 0.0, 0.0, 0.0)
            for item in prims.children:
                geom, closed = _graphic(Node(item.tag.replace("gr_", "fp_"), item.args), flip)
                if geom is None:
                    continue
                width = item.number("width")
                stroke = item.find("stroke")
                if width is None and stroke is not None:
                    width = stroke.number("width")
                fill = (item.value("fill") or "yes") in ("yes", "solid") if closed else False
                if closed and fill:
                    parts.append(geom.buffer(width / 2) if width else geom)
                elif width:
                    for line in _boundary_lines(geom, closed):
                        parts.append(line.buffer(width / 2))
        return unary_union(parts)
    if shape == "trapezoid":
        notes.append(f"{where}: trapezoid pad approximated by its bounding rectangle")
    return box(-w / 2, -h / 2, w / 2, h / 2)


def _place(g: BaseGeometry, angle: float, x: float, y: float) -> BaseGeometry:
    if angle:
        g = shapely.affinity.rotate(g, angle, origin=(0.0, 0.0))
    return shapely.affinity.translate(g, x, y)


# ------------------------------------------------------------------ reader


def read_kicad(path: str | Path, origin: str = "board") -> KicadBoard:
    """Read a ``.kicad_pcb`` file; see the module docstring for the mapping."""
    p = Path(path)
    try:
        text = p.read_text("utf-8")
    except FileNotFoundError:
        raise ConfigError(f"KiCad file not found: {p}") from None
    except UnicodeDecodeError:
        raise ConfigError(f"{p}: not a UTF-8 text file (KiCad 6+ boards are)") from None
    try:
        root = parse(text)
    except ConfigError as exc:
        raise ConfigError(f"{p}: {exc}") from None
    if root.tag not in ("kicad_pcb",):
        raise ConfigError(f"{p}: not a KiCad board file (top-level token {root.tag!r})")
    return _Reader(root, p, origin).run()


class _Reader:
    def __init__(self, root: Node, path: Path, origin: str) -> None:
        if origin not in ("board", "aux", "file"):
            raise ConfigError("kicad.origin must be 'board', 'aux' or 'file'")
        self.root, self.path, self.origin = root, path, origin
        self.notes: list[str] = []
        self.counts: dict[str, int] = defaultdict(int)
        self.copper: dict[tuple[str, str], list[BaseGeometry]] = defaultdict(list)
        self.min_width: dict[str, float] = {}
        self.vias: list[Via] = []
        self.via_rings: list[tuple[str, str, BaseGeometry]] = []

    # ---------------------------------------------------------------- layers / nets

    def _layer_table(self) -> tuple[list[str], dict[str, LayerRole], dict[str, str]]:
        cu: list[tuple[int, str]] = []
        roles: dict[str, LayerRole] = {}
        alias: dict[str, str] = {}
        lt = self.root.find("layers")
        if lt is None:
            raise ConfigError(f"{self.path}: no (layers ...) section")
        role_map = {
            "signal": LayerRole.SIGNAL,
            "power": LayerRole.PLANE,
            "mixed": LayerRole.MIXED,
            "jumper": LayerRole.SIGNAL,
        }
        for entry in lt.children:
            at = [entry.tag, *entry.atoms]
            if len(at) < 3:
                continue
            ordinal, name, typ = at[0], at[1], at[2]
            user = at[3] if len(at) > 3 else None
            if user and user != name and _CU.match(name):
                alias[name] = user
            if _CU.match(name):
                try:
                    order = int(ordinal)
                except ValueError:
                    order = len(cu)
                cu.append((order, name))
                roles[name] = role_map.get(typ, LayerRole.NONE)
        names = [n for _, n in cu]
        names.sort(
            key=lambda n: (
                0 if n == "F.Cu" else 2 if n == "B.Cu" else 1,
                int(n[2:-3]) if n.startswith("In") else 0,
            )
        )
        if not names:
            raise ConfigError(f"{self.path}: no copper layers")
        return names, roles, alias

    def _nets(self) -> dict[str, str]:
        nets: dict[str, str] = {}
        for n in self.root.find_all("net"):
            at = n.atoms
            if len(at) >= 2 and at[1]:
                nets[at[0]] = at[1]
        return nets

    def _net_of(self, node: Node) -> str | None:
        """Net name of a pad/track/via/zone: ``(net ID "NAME")``, ``(net ID)``,
        ``(net "NAME")`` (KiCad 9+) or a zone's ``(net_name "NAME")``."""
        n = node.find("net")
        at = n.atoms if n is not None else []
        if len(at) >= 2:
            return at[1] or None
        if at and at[0] in self.net_by_id:
            return self.net_by_id[at[0]]
        if at and at[0] and not at[0].isdigit():
            return at[0]
        return node.value("net_name") or None

    def _cu_targets(self, layers: Iterable[str]) -> list[str]:
        out: list[str] = []
        for name in layers:
            if name in ("*.Cu", "F&B.Cu"):
                targets = self.cu if name == "*.Cu" else [self.cu[0], self.cu[-1]]
                out += [t for t in targets if t not in out]
            elif name in self.cu and name not in out:
                out.append(name)
        return out

    # ---------------------------------------------------------------- outline

    def _outline(self) -> SPolygon:
        lines: list[BaseGeometry] = []
        areas: list[SPolygon] = []
        ident = _Frame()

        def take(node: Node, f: _Mapper) -> None:
            if _layers_of(node)[:1] != ["Edge.Cuts"]:
                return
            g, closed = _graphic(node, f)
            if g is None:
                if node.tag.endswith("arc"):
                    self.notes.append("Edge.Cuts: legacy arc without 'mid' ignored")
                return
            if closed and isinstance(g, SPolygon):
                areas.append(g)
            else:
                lines.append(g)

        for item in self.root.children:
            if item.tag.startswith("gr_"):
                take(item, ident)
            elif item.tag == "footprint":
                loc = self._fp_local(item, ident)
                for sub in item.children:
                    if sub.tag.startswith("fp_"):
                        take(sub, loc)
        if lines:
            merged = unary_union([shapely.set_precision(ln, 1e-6) for ln in lines])
            areas += [SPolygon(pg.exterior) for pg in polygonize(merged)]
        if not areas:
            raise ConfigError(f"{self.path}: no closed board outline on Edge.Cuts")
        areas.sort(key=lambda a: -a.area)
        outer = areas[0]
        holes = [
            a for a in areas[1:] if outer.contains(a.representative_point()) and a.area < outer.area
        ]
        nested = [h for h in holes if any(o is not h and o.contains(h) for o in holes)]
        holes = [h for h in holes if h not in nested]
        if len(areas) - 1 > len(holes) + len(nested):
            self.notes.append("Edge.Cuts: closed rings outside the board outline ignored")
        return SPolygon(outer.exterior, [h.exterior for h in holes])

    @staticmethod
    def _fp_local(fp: Node, frame: _Frame) -> _Local:
        at = fp.find("at")
        v = at.floats() if at is not None else [0.0, 0.0]
        return _Local(frame, v[0], v[1], v[2] if len(v) > 2 else 0.0)

    # ---------------------------------------------------------------- copper items

    def _tracks(self, f: _Frame) -> None:
        for t in self.root.children:
            if t.tag not in ("segment", "arc"):
                continue
            net = self._net_of(t)
            lay = _layers_of(t)
            width = t.number("width") or 0.0
            if net is None or not lay or lay[0] not in self.cu or width <= 0:
                self.counts["tracks_skipped"] += 1
                continue
            s, e = t.xy("start"), t.xy("end")
            if s is None or e is None:
                continue
            if t.tag == "arc":
                m = t.xy("mid")
                pts = _arc_points(s, m, e) if m is not None else [s, e]
            else:
                pts = [s, e]
            pts = f.many(pts)
            g = (
                Point(pts[0]).buffer(width / 2, quad_segs=8)
                if pts[0] == pts[-1] and len(pts) == 2
                else LineString(pts).buffer(width / 2, quad_segs=8)
            )
            self.copper[(lay[0], net)].append(g)
            self.min_width[net] = min(self.min_width.get(net, math.inf), width)
            self.counts["tracks"] += 1

    def _via(self, v: Node, f: _Frame, plating: float) -> None:
        net = self._net_of(v)
        at = v.xy("at")
        drill = v.number("drill")
        size = v.number("size")
        lay = [x for x in _layers_of(v) if x in self.cu]
        if at is None or drill is None or drill <= 0:
            return
        if net is None:
            self.counts["vias_skipped"] += 1
            return
        if len(lay) < 2:
            lay = [self.cu[0], self.cu[-1]]
        lay.sort(key=self.cu.index)
        x, y = f.p(*at)
        self._add_via(x, y, drill, lay[0], lay[-1], net, plating)
        if size and size > drill:
            for ln in (lay[0], lay[-1]):
                self.copper[(ln, net)].append(_circle(x, y, size / 2))
        self.counts["vias"] += 1

    def _add_via(
        self, x: float, y: float, drill: float, top: str, bot: str, net: str, plating: float
    ) -> None:
        pl = min(plating, 0.49 * drill)
        self.vias.append(
            Via(
                x=x * 1e-3,
                y=y * 1e-3,
                drill=drill * 1e-3,
                from_layer=top,
                to_layer=bot,
                net=net,
                plating_thickness=pl * 1e-3,
                material="copper_ed",
            )
        )
        for ln in self.cu[self.cu.index(top) : self.cu.index(bot) + 1]:
            self.via_rings.append((ln, net, Point(x, y).buffer(drill / 2, quad_segs=8)))

    def _footprints(self, f: _Frame, plating: float) -> dict[str, Footprint]:
        out: dict[str, Footprint] = {}
        for fp in self.root.find_all("footprint"):
            self.counts["footprints"] += 1
            loc = self._fp_local(fp, f)
            at = fp.find("at")
            av = at.floats() if at is not None else [0.0, 0.0]
            side = Side.BOTTOM if (fp.value("layer") or "F.Cu").startswith("B.") else Side.TOP
            ref = ""
            value = ""
            for prop in fp.find_all("property"):
                if prop.atom(0, "") == "Reference":
                    ref = prop.atom(1, "")
                elif prop.atom(0, "") == "Value":
                    value = prop.atom(1, "")
            for txt in fp.find_all("fp_text"):
                if txt.atom(0, "") == "reference" and not ref:
                    ref = txt.atom(1, "")
                elif txt.atom(0, "") == "value" and not value:
                    value = txt.atom(1, "")
            court_lines: list[BaseGeometry] = []
            court_areas: list[SPolygon] = []
            crt = "B.CrtYd" if side is Side.BOTTOM else "F.CrtYd"
            for g in fp.children:
                if not g.tag.startswith("fp_") or _layers_of(g)[:1] != [crt]:
                    continue
                geom, closed = _graphic(g, loc)
                if geom is None:
                    continue
                if closed and isinstance(geom, SPolygon):
                    court_areas.append(geom)
                else:
                    court_lines.append(geom)
            pad_geoms: list[BaseGeometry] = []
            pad_nets: list[str] = []
            for pad in fp.find_all("pad"):
                pad_g = self._pad(pad, loc, f, plating, ref)
                if pad_g is not None:
                    pad_geoms.append(pad_g)
                net = self._net_of(pad)
                if net and net not in pad_nets:
                    pad_nets.append(net)
            if court_lines:
                merged = unary_union([shapely.set_precision(ln, 1e-6) for ln in court_lines])
                court_areas += list(polygonize(merged))
            if court_areas:
                hull = unary_union(court_areas)
                outline_g = hull if isinstance(hull, SPolygon) else hull.convex_hull
            elif pad_geoms:
                outline_g = unary_union(pad_geoms).convex_hull
            else:
                continue
            outline_g = _clean(outline_g.intersection(self.board_poly))
            polys = _polygons(outline_g)
            if not ref or not polys:
                continue
            if ref in out:
                self.notes.append(f"duplicate footprint reference {ref!r}: the first one is used")
                continue
            biggest = max(polys, key=lambda q: q.area)
            out[ref] = Footprint(
                ref=ref,
                side=side,
                outline=_to_polygon(SPolygon(biggest.exterior)),
                x=loc.ox * 1e-3,
                y=loc.oy * 1e-3,
                rotation=av[2] if len(av) > 2 else 0.0,
                value=value,
                pad_nets=tuple(pad_nets),
            )
        return out

    def _pad(
        self, pad: Node, loc: _Local, f: _Frame, plating: float, ref: str
    ) -> BaseGeometry | None:
        typ = pad.atom(1, "smd")
        at = pad.find("at")
        v = at.floats() if at is not None else [0.0, 0.0]
        cx, cy = loc.p(v[0], v[1])
        angle = v[2] if len(v) > 2 else 0.0
        self.counts["pads"] += 1
        where = f"pad {ref}.{pad.atom(0, '?')}"
        shape = _place(_pad_shape(pad, self.notes, where), angle, cx, cy)
        net = self._net_of(pad)
        if typ == "np_thru_hole":
            return shape
        targets = self._cu_targets(_layers_of(pad))
        if net is None:
            return shape
        for ln in targets:
            self.copper[(ln, net)].append(shape)
        if typ == "thru_hole":
            dr = pad.find("drill")
            if dr is not None:
                dims = dr.floats()
                if dims:
                    drill = min(dims[:2]) if len(dims) >= 2 and dr.has_atom("oval") else dims[0]
                    off = dr.xy("offset") or (0.0, 0.0)
                    a = math.radians(angle)
                    ox, oy = off[0], -off[1]
                    hx = cx + math.cos(a) * ox - math.sin(a) * oy
                    hy = cy + math.sin(a) * ox + math.cos(a) * oy
                    if len(targets) >= 2:
                        self._add_via(hx, hy, drill, targets[0], targets[-1], net, plating)
                        self.counts["plated_holes"] += 1
        return shape

    def _zones(self, f: _Frame) -> None:
        pending: list[tuple[int, str, BaseGeometry, float, str]] = []
        for z in self.root.find_all("zone"):
            if z.find("keepout") is not None:
                continue
            net = self._net_of(z)
            layers = self._cu_targets(_layers_of(z))
            if not layers:
                continue
            name = z.value("name") or ""
            if net is None:
                self.notes.append(
                    f"zone {name or '(unnamed)'} on {', '.join(layers)} has no net — ignored"
                )
                continue
            self.counts["zones"] += 1
            filled: dict[str, list[BaseGeometry]] = defaultdict(list)
            for fpn in z.find_all("filled_polygon"):
                ln = fpn.value("layer") or layers[0]
                pn = fpn.find("pts")
                if pn is None or ln not in layers:
                    continue
                pts = f.many(_pts(pn))
                if len(pts) >= 3:
                    filled[ln].append(_clean(SPolygon(pts)))
            for ln, geoms in filled.items():
                self.copper[(ln, net)].append(unary_union(geoms))
            missing = [ln for ln in layers if ln not in filled]
            if not missing:
                continue
            poly = z.find("polygon")
            pn = poly.find("pts") if poly is not None else None
            if pn is None:
                continue
            outline = _clean(SPolygon(f.many(_pts(pn))))
            cp = z.find("connect_pads")
            clr = (cp.number("clearance") if cp is not None else None) or DEFAULT_CLEARANCE
            prio_n = z.find("priority")
            prio = int(prio_n.num(0)) if prio_n is not None else 0
            for ln in missing:
                pending.append((prio, ln, outline, clr, net))
            self.notes.append(
                f"zone {name or net} on {', '.join(missing)} is not filled in the file — "
                f"approximated by its outline minus other-net copper + {clr:g} mm; "
                "fill zones in KiCad (B) and save for exact copper"
            )
        pending.sort(key=lambda t: -t[0])
        for _, ln, outline, clr, net in pending:
            others = [
                g for (lay, n), gs in self.copper.items() if lay == ln and n != net for g in gs
            ]
            others += [g for lay, n, g in self.via_rings if lay == ln and n != net]
            area = outline.intersection(self.board_poly)
            if others:
                area = area.difference(unary_union(others).buffer(clr, quad_segs=4))
            self.copper[(ln, net)].append(_clean(area))

    # ---------------------------------------------------------------- run

    def run(self) -> KicadBoard:
        self.cu, roles, alias = self._layer_table()
        self.net_by_id = self._nets()
        setup = self.root.find("setup")
        outline0 = self._outline()
        if self.origin == "board":
            x0, y0, _, _ = outline0.bounds
            frame = _Frame(x0, -y0)
            self.board_poly = shapely.affinity.translate(outline0, -x0, -y0)
        elif self.origin == "aux":
            aux = setup.xy("aux_axis_origin") if setup is not None else None
            ax, ay = aux or (0.0, 0.0)
            frame = _Frame(ax, ay)
            self.board_poly = shapely.affinity.translate(outline0, -ax, ay)
        else:
            frame = _Frame()
            self.board_poly = outline0
        stackup, mats = _stackup(self.root, self.cu, roles, self.notes)
        plating = 0.025
        self._tracks(frame)
        for v in self.root.find_all("via"):
            self._via(v, frame, plating)
        footprints = self._footprints(frame, plating)
        self._zones(frame)

        shapes: list[Shape] = []
        board = self.board_poly
        for (ln, net), geoms in sorted(self.copper.items()):
            merged = _clean(unary_union(geoms)).intersection(board)
            for k, pg in enumerate(_polygons(_clean(merged))):
                if pg.area < 1e-8:
                    continue
                shapes.append(
                    Shape(net=net, layer=ln, polygon=_to_polygon(pg), name=f"kicad:{ln}:{net}:{k}")
                )
        if alias:
            ren = alias.get
            stackup = tuple(replace(la, name=ren(la.name, la.name)) for la in stackup)
            shapes = [
                replace(
                    sh,
                    layer=ren(sh.layer, sh.layer),
                    name=f"kicad:{ren(sh.layer, sh.layer)}:{sh.net}:{sh.name.rsplit(':', 1)[-1]}",
                )
                for sh in shapes
            ]
            self.vias = [
                replace(
                    v,
                    from_layer=ren(v.from_layer, v.from_layer),
                    to_layer=ren(v.to_layer, v.to_layer),
                )
                for v in self.vias
            ]
        names = dict.fromkeys([*self.net_by_id.values(), *(s.net for s in shapes)])
        nets = tuple(
            Net(name, NetKind.GROUND if _GROUND.match(name) else NetKind.SIGNAL) for name in names
        )
        title = self.root.find("title_block")
        name = (title.value("title") if title is not None else None) or self.path.stem
        return KicadBoard(
            path=self.path,
            name=name,
            stackup=stackup,
            materials=mats,
            outline=_to_polygon(board),
            nets=nets,
            shapes=tuple(shapes),
            vias=tuple(self.vias),
            footprints=footprints,
            layer_alias=alias,
            min_width={k: v * 1e-3 for k, v in self.min_width.items()},
            counts=dict(self.counts),
            notes=self.notes,
        )


def _to_polygon(pg: SPolygon) -> Polygon:
    """Shapely polygon (mm) → pcbsim :class:`Polygon` (m)."""
    pg = shapely.simplify(pg, 1e-5) if len(pg.exterior.coords) > 8 else pg
    outer = np.asarray(pg.exterior.coords, dtype=np.float64) * 1e-3
    holes = tuple(
        np.asarray(r.coords, dtype=np.float64) * 1e-3 for r in pg.interiors if len(r.coords) >= 4
    )
    return Polygon(outer, holes)
