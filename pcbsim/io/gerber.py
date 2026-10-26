"""Gerber RS-274X reader with X2 / X3 attributes → shapely geometry (metres).

Source: Ucamco, *The Gerber Layer Format Specification* (public, rev. 2023.08).
Section numbers below refer to that document.

Coordinates (§4.2, §4.9)
    ``%FSLAX<i><d>Y<i><d>*%``: absolute (``A``) or incremental (``I``)
    notation, leading zeros omitted (``L``; deprecated ``T`` = trailing zeros
    omitted is also read). An integer coordinate ``n`` is ``n · 10^−d`` in the
    unit of ``%MOMM*%`` / ``%MOIN*%``. Missing X or Y keeps the previous value.

Apertures (§4.4)
    ``C,d[Xh]`` circle; ``R,w Xh[Xhd]`` rectangle; ``O,w Xh`` obround (stadium,
    semicircles on the short sides); ``P,D Xn[Xrot[Xh]]`` regular n-gon with
    outer diameter ``D``, first vertex at angle ``rot``. The optional hole of
    standard apertures is subtracted from the flash.

Aperture macros (§4.5)
    Primitives 1 circle, 20 vector line, 21 centre line, 4 outline, 5 polygon,
    7 thermal (annulus with four gaps), 0 comment. Exposure 1 adds, 0 clears
    within the macro. Rotation (last modifier) is about the macro origin.
    Expressions use ``+ - x / ( )`` with the usual precedence, unary minus, and
    variables ``$n`` (``$n`` = n-th AD parameter); ``$k=<expr>`` assigns.

Plotting (§4.7, §4.8)
    D01 draws with the current aperture: circle → buffer of the centre line by
    d/2 with round caps; rectangle (lines) → convex hull of the rectangle at
    both end points (Minkowski sum). D02 moves, D03 flashes.
    Arcs: ``G02`` clockwise, ``G03`` counter-clockwise. In multi-quadrant mode
    (``G75``) the centre is ``(x_s + I, y_s + J)`` with signed offsets and
    start == end means a full circle; in single-quadrant mode (``G74``) I, J
    are unsigned and the centre is the candidate (±I, ±J) whose arc is ≤ 90°
    in the requested direction. Arcs are flattened with sagitta ≤ 1 µm
    (``n = ceil(θ / (2·acos(1 − s/r)))``, at least 16 per full turn).

Regions (§4.10)
    Between ``G36`` and ``G37`` every D01 sequence is a contour; ``D02`` closes
    the current contour and starts a new one. Contours combine even-odd.

Polarity (§4.9.2)
    ``%LPD*%`` adds to the image, ``%LPC*%`` clears what was drawn before.
    Objects are batched per polarity run and merged with ``union_all``.

Step & repeat (§4.11) and block apertures (§4.12) are handled.

Attributes (§5)
    ``TF`` file attributes (``.FileFunction`` decides the layer kind and
    side), ``TA`` aperture attributes (bound to apertures at AD time), ``TO``
    object attributes (``.C`` component, ``.CRot``, ``.CFtp``, ``.CVal``,
    ``.CHgt``, ``.P``, ``.N``) and ``TD`` deletion. In X3 component layers each
    ``ComponentMain`` flash is a placement (§5.6.x "Component layers").
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import shapely
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.geometry import box as shp_box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import Flash, GerberLayer, PlacedComponent
from pcbsim.units import INCH, MM

SAGITTA = 1e-6
GERBER_SUFFIXES = {
    ".gbr", ".ger", ".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs", ".gtp", ".gbp",
    ".gm1", ".gko", ".gml", ".gbx", ".art", ".pho",
}  # fmt: skip
_INNER = re.compile(r"\.g\d+$", re.IGNORECASE)

Attrs = dict[str, tuple[str, ...]]


# --------------------------------------------------------------------------- file names


_NAME_RULES: list[tuple[re.Pattern[str], tuple[str, ...], str | None]] = [
    (re.compile(r"(edge[_.]?cuts|\.gm1$|\.gko$|\.gml$|outline|profile)", re.I), ("Profile", "NP"),
     None),
    (re.compile(r"(-f[_.]cu|\.gtl$)", re.I), ("Copper", "L1", "Top"), "top"),
    (re.compile(r"(-b[_.]cu|\.gbl$)", re.I), ("Copper", "Ln", "Bot"), "bottom"),
    (re.compile(r"(-f[_.]mask|\.gts$)", re.I), ("Soldermask", "Top"), "top"),
    (re.compile(r"(-b[_.]mask|\.gbs$)", re.I), ("Soldermask", "Bot"), "bottom"),
    (re.compile(r"(-f[_.]silks(creen)?|\.gto$)", re.I), ("Legend", "Top"), "top"),
    (re.compile(r"(-b[_.]silks(creen)?|\.gbo$)", re.I), ("Legend", "Bot"), "bottom"),
    (re.compile(r"(-f[_.]paste|\.gtp$)", re.I), ("Paste", "Top"), "top"),
    (re.compile(r"(-b[_.]paste|\.gbp$)", re.I), ("Paste", "Bot"), "bottom"),
]  # fmt: skip


def guess_function(filename: str) -> tuple[tuple[str, ...], str | None]:
    """X2-like file function from KiCad / Protel file-name conventions."""
    for pat, fn, side in _NAME_RULES:
        if pat.search(filename):
            return fn, side
    m = re.search(r"-in(\d+)[_.]cu", filename, re.I)
    if m or _INNER.search(filename):
        n = m.group(1) if m else filename.rsplit(".g", 1)[-1]
        return ("Copper", f"L{int(n) + 1}", "Inr"), None
    return (), None


def _side_of(function: tuple[str, ...]) -> str | None:
    for p in function[1:]:
        if p.lower() == "top":
            return "top"
        if p.lower() in ("bot", "bottom"):
            return "bottom"
    return None


# --------------------------------------------------------------------------- expressions


_TOK = re.compile(r"\s*(\$\d+|\d+\.?\d*|\.\d+|[-+xX/()])")


def eval_expr(text: str, var: dict[int, float]) -> float:
    """Evaluate a macro arithmetic expression (§4.5.4): ``x``/``X`` is multiplication."""
    tokens: list[str] = _TOK.findall(text.replace(" ", ""))
    if "".join(tokens) != text.replace(" ", ""):
        raise CadFormatError(f"bad macro expression {text!r}")
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        tok: str = tokens[pos - 1]
        return tok

    def atom() -> float:
        t = take()
        if t == "(":
            v = add()
            if take() != ")":
                raise CadFormatError(f"unbalanced parentheses in {text!r}")
            return v
        if t in "+-":
            v = atom()
            return -v if t == "-" else v
        if t.startswith("$"):
            return var.get(int(t[1:]), 0.0)
        return float(t)

    def mul() -> float:
        v = atom()
        while peek() in ("x", "X", "/"):
            op = take()
            r = atom()
            v = v * r if op in "xX" else v / r
        return v

    def add() -> float:
        v = mul()
        while peek() in ("+", "-"):
            op = take()
            r = mul()
            v = v + r if op == "+" else v - r
        return v

    if not tokens:
        return 0.0
    out = add()
    if pos != len(tokens):
        raise CadFormatError(f"trailing tokens in macro expression {text!r}")
    return out


# --------------------------------------------------------------------------- shapes


def _n_seg(radius: float, sweep: float) -> int:
    if radius <= SAGITTA:
        return 4
    step = 2.0 * math.acos(max(1.0 - SAGITTA / radius, -1.0))
    n = math.ceil(abs(sweep) / step) if step > 0 else 720
    return max(min(n, 720), math.ceil(16 * abs(sweep) / (2 * math.pi)), 1)


def _circle(cx: float, cy: float, d: float) -> Polygon:
    r = d / 2.0
    n = _n_seg(r, 2 * math.pi)
    t = [2 * math.pi * k / n for k in range(n)]
    return Polygon([(cx + r * math.cos(a), cy + r * math.sin(a)) for a in t])


def _buffer_res(radius: float) -> int:
    return max(4, math.ceil(_n_seg(radius, 2 * math.pi) / 4))


def _rotate(g: BaseGeometry, deg: float) -> BaseGeometry:
    return affinity.rotate(g, deg, origin=(0, 0)) if deg else g


@dataclass(slots=True)
class Aperture:
    """Aperture centred at the origin (metres); ``kind`` is C/R/O/P, M (macro) or B (block),
    ``diameter`` the circle diameter or the smallest extent (used for strokes)."""

    shape: BaseGeometry
    kind: str
    diameter: float = 0.0
    attributes: Attrs = field(default_factory=dict)
    block: list[tuple[bool, BaseGeometry]] | None = None


def _std_aperture(kind: str, params: list[float], unit: float) -> Aperture:
    p = [v * unit for v in params]
    if kind == "C":
        shape: BaseGeometry = _circle(0, 0, p[0])
        hole = p[1] if len(p) > 1 else 0.0
        dia = p[0]
    elif kind == "R":
        w, h = p[0], p[1]
        shape = shp_box(-w / 2, -h / 2, w / 2, h / 2)
        hole = p[2] if len(p) > 2 else 0.0
        dia = min(w, h)
    elif kind == "O":
        w, h = p[0], p[1]
        r = min(w, h) / 2
        if w >= h:
            core = LineString([(-(w / 2 - r), 0), (w / 2 - r, 0)])
        else:
            core = LineString([(0, -(h / 2 - r)), (0, h / 2 - r)])
        shape = core.buffer(r, quad_segs=_buffer_res(r)) if core.length > 0 else _circle(0, 0, w)
        hole = p[2] if len(p) > 2 else 0.0
        dia = min(w, h)
    elif kind == "P":
        d, n = p[0], round(params[1])
        rot = params[2] if len(params) > 2 else 0.0
        hole = p[3] if len(p) > 3 else 0.0
        if not 3 <= n <= 12:
            raise CadFormatError(f"polygon aperture needs 3..12 vertices, got {n}")
        shape = Polygon(
            [
                (
                    d / 2 * math.cos(math.radians(rot) + 2 * math.pi * k / n),
                    d / 2 * math.sin(math.radians(rot) + 2 * math.pi * k / n),
                )
                for k in range(n)
            ]
        )
        dia = d * math.cos(math.pi / n)
    else:
        raise CadFormatError(f"unknown standard aperture type {kind!r}")
    if hole > 0:
        shape = shape.difference(_circle(0, 0, hole))
    return Aperture(shape, kind, dia)


def _macro_shape(body: list[str], params: list[float], unit: float) -> BaseGeometry:
    var = {i + 1: v for i, v in enumerate(params)}
    dark: BaseGeometry = Polygon()
    for stmt in body:
        stmt = stmt.strip()
        if not stmt or stmt.startswith("0"):
            continue
        if stmt.startswith("$"):
            name, expr = stmt.split("=", 1)
            var[int(name[1:])] = eval_expr(expr, var)
            continue
        fields = stmt.split(",")
        code = int(fields[0])
        a = [eval_expr(f, var) for f in fields[1:]]
        u = unit
        exposure = round(a[0]) if a else 1
        if code == 1:
            g: BaseGeometry = _circle(a[2] * u, a[3] * u, a[1] * u)
            rot = a[4] if len(a) > 4 else 0.0
        elif code == 20:
            w = a[1] * u
            x0, y0, x1, y1 = a[2] * u, a[3] * u, a[4] * u, a[5] * u
            ln = math.hypot(x1 - x0, y1 - y0)
            if ln == 0:
                continue
            nx, ny = -(y1 - y0) / ln * w / 2, (x1 - x0) / ln * w / 2
            g = Polygon([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny),
                         (x0 - nx, y0 - ny)])  # fmt: skip
            rot = a[6] if len(a) > 6 else 0.0
        elif code == 21:
            w, h, cx, cy = a[1] * u, a[2] * u, a[3] * u, a[4] * u
            g = shp_box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            rot = a[5] if len(a) > 5 else 0.0
        elif code == 4:
            n = round(a[1])
            pts = [(a[2 + 2 * k] * u, a[3 + 2 * k] * u) for k in range(n + 1)]
            g = shapely.make_valid(Polygon(pts))
            rot = a[4 + 2 * n] if len(a) > 4 + 2 * n else 0.0
        elif code == 5:
            n = round(a[1])
            cx, cy, d = a[2] * u, a[3] * u, a[4] * u
            rot = a[5] if len(a) > 5 else 0.0
            g = Polygon(
                [
                    (cx + d / 2 * math.cos(2 * math.pi * k / n),
                     cy + d / 2 * math.sin(2 * math.pi * k / n))
                    for k in range(n)
                ]
            )  # fmt: skip
        elif code == 7:
            exposure = 1
            cx, cy, od, idia, gap = a[0] * u, a[1] * u, a[2] * u, a[3] * u, a[4] * u
            rot = a[5] if len(a) > 5 else 0.0
            ring = _circle(cx, cy, od).difference(_circle(cx, cy, idia))
            bars = unary_union(
                [
                    shp_box(cx - od, cy - gap / 2, cx + od, cy + gap / 2),
                    shp_box(cx - gap / 2, cy - od, cx + gap / 2, cy + od),
                ]
            )
            g = ring.difference(bars)
        else:
            raise CadFormatError(f"unsupported macro primitive {code}")
        g = _rotate(g, rot)
        dark = dark.union(g) if exposure == 1 else dark.difference(g)
    return dark


# --------------------------------------------------------------------------- parser


@dataclass(slots=True)
class _State:
    unit: float = MM
    n_int: int = 3
    n_dec: int = 6
    fs_set: bool = False
    incremental: bool = False
    trailing: bool = False
    x: float = 0.0
    y: float = 0.0
    interp: int = 1
    multi_quadrant: bool = True
    aperture: str | None = None
    dark: bool = True
    region: bool = False
    contour: list[tuple[float, float]] = field(default_factory=list)
    contours: list[list[tuple[float, float]]] = field(default_factory=list)


class _Image:
    """Polarity-aware accumulator with batching."""

    def __init__(self) -> None:
        self.acc: BaseGeometry = Polygon()
        self.batch: list[BaseGeometry] = []
        self.batch_dark = True

    def add(self, g: BaseGeometry, dark: bool) -> None:
        if g.is_empty:
            return
        if dark != self.batch_dark:
            self.flush()
            self.batch_dark = dark
        self.batch.append(g)

    def flush(self) -> None:
        if not self.batch:
            return
        merged = shapely.union_all(self.batch)
        self.acc = self.acc.union(merged) if self.batch_dark else self.acc.difference(merged)
        self.batch = []

    def result(self) -> BaseGeometry:
        self.flush()
        return self.acc


class _Sink:
    """Collects objects either into the layer image or into a block aperture / SR body."""

    def __init__(self) -> None:
        self.items: list[tuple[bool, BaseGeometry]] = []


def _arc_points(
    st: _State, x1: float, y1: float, i: float, j: float, cw: bool, warn: Callable[[str], None]
) -> tuple[list[tuple[float, float]], tuple[float, float], float]:
    x0, y0 = st.x, st.y
    if st.multi_quadrant:
        cx, cy = x0 + i, y0 + j
    else:
        best: tuple[float, float, float] | None = None
        for sx in (1, -1):
            for sy in (1, -1):
                cx_, cy_ = x0 + sx * abs(i), y0 + sy * abs(j)
                a0 = math.atan2(y0 - cy_, x0 - cx_)
                a1 = math.atan2(y1 - cy_, x1 - cx_)
                sweep = (a0 - a1) % (2 * math.pi) if cw else (a1 - a0) % (2 * math.pi)
                err = abs(math.hypot(x1 - cx_, y1 - cy_) - math.hypot(x0 - cx_, y0 - cy_))
                if sweep <= math.pi / 2 + 1e-9 and (best is None or err < best[2]):
                    best = (cx_, cy_, err)
        if best is None:
            warn("single-quadrant arc has no ≤ 90° solution; drawn as a line")
            return [(x0, y0), (x1, y1)], (x0, y0), 0.0
        cx, cy = best[0], best[1]
    r0 = math.hypot(x0 - cx, y0 - cy)
    r1 = math.hypot(x1 - cx, y1 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = (a0 - a1) % (2 * math.pi) if cw else (a1 - a0) % (2 * math.pi)
    if st.multi_quadrant and math.hypot(x1 - x0, y1 - y0) < 1e-12:
        sweep = 2 * math.pi
    if sweep == 0.0 and st.multi_quadrant:
        sweep = 2 * math.pi
    n = _n_seg(max(r0, r1), sweep)
    sign = -1.0 if cw else 1.0
    pts = []
    for k in range(n + 1):
        t = k / n
        a = a0 + sign * sweep * t
        r = r0 + (r1 - r0) * t
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts[0], pts[-1] = (x0, y0), (x1, y1)
    return pts, (cx, cy), max(r0, r1)


def parse_gerber(source: str | Path, *, text: str | None = None) -> GerberLayer:
    """Parse one Gerber file. ``text`` overrides reading ``source`` from disk."""
    path = Path(source)
    raw = text if text is not None else path.read_text("utf-8", errors="replace")
    layer = GerberLayer(path=path)
    return _Parser(layer, raw).run()


class _Parser:
    def __init__(self, layer: GerberLayer, raw: str) -> None:
        self.layer = layer
        self.raw = raw
        self.st = _State()
        self.apertures: dict[str, Aperture] = {}
        self.macros: dict[str, list[str]] = {}
        self.image = _Image()
        self.ta: Attrs = {}
        self.to: Attrs = {}
        self.block_stack: list[tuple[str, list[tuple[bool, BaseGeometry]], bool]] = []
        self.sr: tuple[int, int, float, float] | None = None
        self.sr_items: list[tuple[bool, BaseGeometry]] = []
        self.sr_flashes: list[Flash] = []
        self.sr_paths: list[LineString] = []
        self._warned: set[str] = set()

    def warn(self, msg: str) -> None:
        if msg not in self._warned:
            self._warned.add(msg)
            self.layer.warnings.append(msg)

    # ---------------------------------------------------------------- output sinks

    def emit(self, g: BaseGeometry) -> None:
        if self.block_stack:
            self.block_stack[-1][1].append((self.st.dark, g))
        elif self.sr is not None:
            self.sr_items.append((self.st.dark, g))
        else:
            self.image.add(g, self.st.dark)

    def emit_path(self, ls: LineString) -> None:
        if self.block_stack:
            return
        if self.sr is not None:
            self.sr_paths.append(ls)
        else:
            self.layer.paths.append(ls)

    def emit_flash(self, f: Flash) -> None:
        if self.block_stack:
            return
        if self.sr is not None:
            self.sr_flashes.append(f)
        else:
            self.layer.flashes.append(f)

    # ---------------------------------------------------------------- coordinates

    def coord(self, text: str) -> float:
        st = self.st
        if not st.fs_set:
            raise CadFormatError(f"{self.layer.path}: coordinate before %FS format statement")
        if "." in text:
            return float(text) * st.unit
        sign = -1.0 if text.startswith("-") else 1.0
        digits = text.lstrip("+-")
        if st.trailing:
            digits = digits.ljust(st.n_int + st.n_dec, "0")
        return sign * int(digits) / 10.0**st.n_dec * st.unit

    # ---------------------------------------------------------------- run

    def run(self) -> GerberLayer:
        cmds = re.findall(r"%[^%]*%|[^*%]+\*", self.raw)
        for c in cmds:
            c = c.strip()
            if not c:
                continue
            if c.startswith("%"):
                inner = c[1:-1].strip()
                if inner.startswith("AM"):
                    name, _, body = inner[2:].partition("*")
                    self.macros[name.strip()] = [s for s in body.split("*") if s.strip()]
                    continue
                for ext in inner.split("*"):
                    ext = ext.strip()
                    if ext:
                        self.extended(ext)
            else:
                if self.word(c.rstrip("*").strip()):
                    break
        if self.sr is not None:
            self.close_sr()
        self.layer.geometry = self.image.result()
        self.finish()
        return self.layer

    def finish(self) -> None:
        lay = self.layer
        if not lay.function:
            fn, side = guess_function(lay.path.name if lay.path else "")
            lay.function = fn
            lay.side = side
        elif lay.side is None:
            lay.side = _side_of(lay.function)
        if lay.kind.lower() == "component":
            side = lay.side or "top"
            for f in lay.flashes:
                fn = f.attributes.get("AperFunction", ())
                if not fn or fn[0] != "ComponentMain" or "C" not in f.attributes:
                    continue
                a = f.attributes
                hgt = a.get("CHgt")
                lay.components.append(
                    PlacedComponent(
                        ref=a["C"][0],
                        x=f.x,
                        y=f.y,
                        rotation=float(a["CRot"][0]) % 360.0 if "CRot" in a else 0.0,
                        side=side,
                        footprint=a.get("CFtp", ("",))[0],
                        value=a.get("CVal", ("",))[0],
                        height=float(hgt[0]) * self.st.unit if hgt else None,
                    )
                )

    # ---------------------------------------------------------------- extended

    def extended(self, ext: str) -> None:
        st = self.st
        if ext.startswith("FS"):
            m = re.fullmatch(r"FS([LTD]?)([AI])X(\d)(\d)Y(\d)(\d)", ext)
            if not m:
                raise CadFormatError(f"{self.layer.path}: bad format statement %{ext}%")
            st.trailing = m.group(1) == "T"
            st.incremental = m.group(2) == "I"
            st.n_int, st.n_dec = int(m.group(3)), int(m.group(4))
            st.fs_set = True
            if st.incremental:
                self.warn("incremental notation (deprecated) used")
        elif ext.startswith("MO"):
            st.unit = MM if ext[2:4] == "MM" else INCH
        elif ext.startswith("AD"):
            self.define_aperture(ext[2:])
        elif ext.startswith("LP"):
            st.dark = ext[2] == "D"
        elif ext.startswith(("LM", "LR", "LS")):
            if ext not in ("LMN", "LR0", "LS1", "LS1.0"):
                self.warn(f"aperture transformation %{ext}% ignored")
        elif ext.startswith("AB"):
            name = ext[2:]
            if name:
                self.block_stack.append((name, [], st.dark))
            elif self.block_stack:
                bname, items, prev_dark = self.block_stack.pop()
                st.dark = prev_dark
                self.apertures[bname] = Aperture(Polygon(), "B", 0.0, dict(self.ta), items)
        elif ext.startswith("SR"):
            if self.sr is not None:
                self.close_sr()
            m = re.fullmatch(r"SRX(\d+)Y(\d+)I([-\d.]+)J([-\d.]+)", ext)
            if m and (int(m.group(1)) > 1 or int(m.group(2)) > 1):
                self.image.flush()
                self.sr = (
                    int(m.group(1)),
                    int(m.group(2)),
                    float(m.group(3)) * st.unit,
                    float(m.group(4)) * st.unit,
                )
        elif ext.startswith("TF"):
            k, v = self.attr(ext[2:])
            self.layer.file_attributes[k] = v
            if k == "FileFunction":
                self.layer.function = v
                self.layer.side = _side_of(v)
        elif ext.startswith("TA"):
            k, v = self.attr(ext[2:])
            self.ta[k] = v
        elif ext.startswith("TO"):
            k, v = self.attr(ext[2:])
            self.to[k] = v
        elif ext.startswith("TD"):
            name = ext[2:].lstrip(".")
            if not name:
                self.ta.clear()
                self.to.clear()
            else:
                self.ta.pop(name, None)
                self.to.pop(name, None)
        elif ext.startswith(("IP", "IN", "LN", "OF", "AS", "MI", "SF", "IR")):
            if ext not in ("IPPOS", "OFA0B0", "ASAXBY", "MIA0B0", "SFA1B1", "IR0") and not (
                ext.startswith(("IN", "LN"))
            ):
                self.warn(f"deprecated image parameter %{ext}% ignored")
        else:
            self.warn(f"unknown extended command %{ext}% ignored")

    @staticmethod
    def attr(text: str) -> tuple[str, tuple[str, ...]]:
        parts = text.split(",")
        return parts[0].lstrip("."), tuple(p.strip() for p in parts[1:])

    def define_aperture(self, body: str) -> None:
        m = re.fullmatch(r"D(\d+)([^,]+)(?:,(.*))?", body)
        if not m:
            raise CadFormatError(f"{self.layer.path}: bad aperture definition %AD{body}%")
        code, kind, args = "D" + str(int(m.group(1))), m.group(2), m.group(3)
        params = [float(v) for v in args.split("X")] if args else []
        if kind in ("C", "R", "O", "P"):
            ap = _std_aperture(kind, params, self.st.unit)
        elif kind in self.macros:
            shape = _macro_shape(self.macros[kind], params, self.st.unit)
            minx, miny, maxx, maxy = shape.bounds if not shape.is_empty else (0, 0, 0, 0)
            ap = Aperture(shape, "M", min(maxx - minx, maxy - miny))
        else:
            raise CadFormatError(f"{self.layer.path}: aperture macro {kind!r} is not defined")
        ap.attributes = dict(self.ta)
        self.apertures[code] = ap

    # ---------------------------------------------------------------- words

    def word(self, w: str) -> bool:
        """Process one word command; returns True at end of file."""
        st = self.st
        if not w:
            return False
        if w.startswith("G04") or w.startswith("G4 "):
            return False
        if w in ("M02", "M2", "M00", "M0", "M01", "M1"):
            return True
        m = re.match(r"^G0?(\d+)", w)
        if m:
            g = int(m.group(1))
            rest = w[m.end() :]
            if g in (1, 2, 3):
                st.interp = g
            elif g == 36:
                st.region, st.contour, st.contours = True, [], []
            elif g == 37:
                self.close_contour()
                self.end_region()
            elif g == 74:
                st.multi_quadrant = False
                self.warn("single-quadrant arc mode G74 (deprecated) used")
            elif g == 75:
                st.multi_quadrant = True
            elif g == 70:
                st.unit = INCH
            elif g == 71:
                st.unit = MM
            elif g == 90:
                st.incremental = False
            elif g == 91:
                st.incremental = True
            elif g == 54 or g == 55:
                pass
            else:
                self.warn(f"G{g:02d} ignored")
            if not rest:
                return False
            w = rest
        if w.startswith("D") and re.fullmatch(r"D0*\d+", w):
            code = int(w[1:])
            if code >= 10:
                st.aperture = f"D{code}"
                return False
            self.operation(code, {})
            return False
        if w[0] in "XYIJ":
            coords = dict(re.findall(r"([XYIJ])([-+]?[\d.]+)", w))
            dm = re.search(r"D0*(\d+)$", w)
            code = int(dm.group(1)) if dm else 1
            self.operation(code, coords)
            return False
        if w.startswith("M"):
            return False
        self.warn(f"unknown command {w!r} ignored")
        return False

    def operation(self, code: int, coords: dict[str, str]) -> None:
        st = self.st
        x1 = self.coord(coords["X"]) if "X" in coords else (0.0 if st.incremental else st.x)
        y1 = self.coord(coords["Y"]) if "Y" in coords else (0.0 if st.incremental else st.y)
        if st.incremental:
            x1, y1 = st.x + x1, st.y + y1
        i = self.coord(coords["I"]) if "I" in coords else 0.0
        j = self.coord(coords["J"]) if "J" in coords else 0.0
        if code == 1:
            self.draw(x1, y1, i, j)
        elif code == 2:
            if st.region:
                self.close_contour()
        elif code == 3:
            self.flash(x1, y1)
        else:
            self.warn(f"operation D{code:02d} ignored")
        st.x, st.y = x1, y1

    def current(self) -> Aperture:
        st = self.st
        if st.aperture is None or st.aperture not in self.apertures:
            raise CadFormatError(
                f"{self.layer.path}: aperture {st.aperture or '(none)'} used but not defined"
            )
        return self.apertures[st.aperture]

    def draw(self, x1: float, y1: float, i: float, j: float) -> None:
        st = self.st
        if st.interp == 1:
            pts = [(st.x, st.y), (x1, y1)]
            arc = False
        else:
            pts, _, _ = _arc_points(st, x1, y1, i, j, st.interp == 2, self.warn)
            arc = True
        if st.region:
            if not st.contour:
                st.contour = [pts[0]]
            st.contour += pts[1:]
            return
        ap = self.current()
        line = LineString(pts)
        if line.length == 0:
            self.emit(affinity.translate(ap.shape, x1, y1))
            return
        self.emit_path(line)
        if ap.kind == "C":
            r = ap.diameter / 2
            if r <= 0:
                return
            self.emit(line.buffer(r, quad_segs=_buffer_res(r)))
        elif ap.kind == "R" and not arc:
            a = affinity.translate(ap.shape, *pts[0])
            b = affinity.translate(ap.shape, *pts[1])
            self.emit(unary_union([a, b]).convex_hull)
        else:
            self.warn(f"stroke with non-circular aperture {ap.kind} approximated as circular")
            r = ap.diameter / 2
            if r > 0:
                self.emit(line.buffer(r, quad_segs=_buffer_res(r)))

    def flash(self, x: float, y: float) -> None:
        ap = self.current()
        attrs: Attrs = {**ap.attributes, **self.to}
        self.emit_flash(Flash(x, y, self.st.aperture or "", attrs))
        if ap.block is not None:
            for dark, g in ap.block:
                prev = self.st.dark
                self.st.dark = dark if prev else not dark
                self.emit(affinity.translate(g, x, y))
                self.st.dark = prev
            return
        self.emit(affinity.translate(ap.shape, x, y))

    def close_contour(self) -> None:
        st = self.st
        if len(st.contour) >= 3:
            st.contours.append(st.contour)
        st.contour = []

    def end_region(self) -> None:
        st = self.st
        geom: BaseGeometry = Polygon()
        for c in st.contours:
            self.emit_path(LineString([*c, c[0]] if c[0] != c[-1] else c))
            poly = shapely.make_valid(Polygon(c))
            geom = geom.symmetric_difference(poly)
        st.region, st.contours = False, []
        if not geom.is_empty:
            self.emit(geom)

    def close_sr(self) -> None:
        assert self.sr is not None
        nx, ny, dx, dy = self.sr
        self.sr = None
        for ix in range(nx):
            for iy in range(ny):
                ox, oy = ix * dx, iy * dy
                for dark, g in self.sr_items:
                    self.image.add(affinity.translate(g, ox, oy), dark)
                for f in self.sr_flashes:
                    self.layer.flashes.append(Flash(f.x + ox, f.y + oy, f.aperture, f.attributes))
                for ls in self.sr_paths:
                    moved = affinity.translate(ls, ox, oy)
                    assert isinstance(moved, LineString)
                    self.layer.paths.append(moved)
        self.sr_items, self.sr_flashes, self.sr_paths = [], [], []


# --------------------------------------------------------------------------- helpers


def load_gerber_dir(directory: Path) -> list[GerberLayer]:
    """Parse every Gerber-like file in ``directory`` (sorted by name)."""
    files = sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and (p.suffix.lower() in GERBER_SUFFIXES or _INNER.search(p.name))
    )
    return [parse_gerber(p) for p in files]


def find_layer(
    layers: Sequence[GerberLayer], kind: str, side: str | None = None
) -> GerberLayer | None:
    for g in layers:
        if g.kind.lower() == kind.lower() and (side is None or g.side == side):
            return g
    return None


def outline_polygons(layer: GerberLayer, snap: float = 1e-6) -> list[Polygon]:
    """Board outlines from the profile's centre lines; nested rings become cutouts."""
    if not layer.paths:
        return []
    merged = unary_union(layer.paths)
    merged = shapely.set_precision(merged, snap) if snap > 0 else merged
    faces = sorted(
        (p for p in polygonize(merged) if p.area > 0), key=lambda p: p.area, reverse=True
    )
    boards: list[Polygon] = []
    for f in faces:
        outer = Polygon(f.exterior)
        if any(Polygon(b.exterior).contains(outer.representative_point()) for b in boards):
            continue
        holes = [
            Polygon(g.exterior)
            for g in faces
            if g is not f and outer.contains(g.representative_point()) and g.area < outer.area
        ]
        top_holes = [h for h in holes if not any(o is not h and o.contains(h) for o in holes)]
        boards.append(Polygon(outer.exterior, [h.exterior for h in top_holes]))
    return boards


def component_centroids(layer: GerberLayer) -> dict[str, tuple[float, float]]:
    """Mean flash position per ``TO.C`` reference designator."""
    acc: dict[str, list[tuple[float, float]]] = {}
    for f in layer.flashes:
        ref = f.attributes.get("C")
        if ref:
            acc.setdefault(ref[0], []).append((f.x, f.y))
    return {
        r: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for r, v in acc.items()
    }


def dark_area(layer: GerberLayer) -> float:
    g = layer.geometry
    return float(g.area) if g is not None else 0.0


__all__ = [
    "Aperture",
    "component_centroids",
    "dark_area",
    "eval_expr",
    "find_layer",
    "guess_function",
    "load_gerber_dir",
    "outline_polygons",
    "parse_gerber",
]
