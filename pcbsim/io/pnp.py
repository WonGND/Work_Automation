"""Pick-and-place / centroid CSV reader (KiCad ``*-pos.csv``, generic CSV).

Columns are found by header name (case-insensitive, first match wins):

=========  ==================================================================
ref        ``Ref``, ``Designator``, ``RefDes``, ``Reference``, ``Part``
x / y      ``PosX``/``PosY``, ``Mid X``/``Mid Y``, ``Center-X(mm)``, ``X``/``Y``
rotation   ``Rot``, ``Rotation``, ``Angle``
side       ``Side``, ``Layer``, ``TB`` (``top``/``T``/``F.Cu`` vs ``bottom``/``B``)
height     ``Height``, ``Hgt``, ``Z`` (optional)
=========  ==================================================================

Values may carry a unit suffix (``"12.5mm"``, ``"500mil"``); otherwise the
``unit`` argument applies, or the unit found in the header (``X(mm)``, ``PosX
[in]``). KiCad writes ``# Unit = mm`` / ``# Unit = in`` comment lines, which
are honoured as well. Lines starting with ``#`` are comments.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import PlacedComponent
from pcbsim.units import Kind, parse_quantity, to_si

_COLS: dict[str, tuple[str, ...]] = {
    "ref": ("ref", "designator", "refdes", "reference", "part", "name"),
    "x": ("posx", "midx", "centerx", "x", "locationx", "refx"),
    "y": ("posy", "midy", "centery", "y", "locationy", "refy"),
    "rot": ("rot", "rotation", "angle", "orientation"),
    "side": ("side", "layer", "tb", "mount"),
    "height": ("height", "hgt", "z", "compheight"),
    "footprint": ("package", "footprint", "pattern"),
    "value": ("val", "value", "comment"),
}
_UNIT_RE = re.compile(r"[\(\[]\s*(mm|in|inch|mil|mils|um)\s*[\)\]]", re.IGNORECASE)


def _norm(h: str) -> str:
    return re.sub(r"[^a-z]", "", _UNIT_RE.sub("", h).lower())


def _side(text: str) -> str:
    t = text.strip().lower()
    if t in {"bottom", "bot", "b", "b.cu", "bottomlayer", "back"}:
        return "bottom"
    return "top"


def parse_pnp(
    source: str | Path, *, text: str | None = None, unit: str = "mm"
) -> list[PlacedComponent]:
    """Parse a centroid CSV into :class:`PlacedComponent` (SI, degrees)."""
    raw = text if text is not None else Path(source).read_text("utf-8", errors="replace")
    file_unit = unit
    rows: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.search(r"unit\s*=\s*(mm|in|inch|mil)", s, re.IGNORECASE)
            if m:
                file_unit = m.group(1).lower()
            continue
        rows.append(line)
    if not rows:
        raise CadFormatError(f"{source}: empty pick-and-place file")
    dialect: type[csv.Dialect] | csv.Dialect = csv.excel
    try:
        dialect = csv.Sniffer().sniff(rows[0], delimiters=",;\t")
    except csv.Error:
        if "," not in rows[0] and ";" not in rows[0] and "\t" not in rows[0]:
            dialect = _Spaces
    table = list(csv.reader(io.StringIO("\n".join(rows)), dialect))
    header = [h.strip() for h in table[0]]
    norm = [_norm(h) for h in header]
    col: dict[str, int] = {}
    for key, names in _COLS.items():
        for n in names:
            if n in norm:
                col[key] = norm.index(n)
                break
    missing = [k for k in ("ref", "x", "y") if k not in col]
    if missing:
        raise CadFormatError(
            f"{source}: pick-and-place header {header} lacks column(s) {missing} "
            "(expected e.g. Ref, PosX, PosY, Rot, Side)"
        )
    col_unit: dict[str, str] = {}
    for key in ("x", "y", "height"):
        if key in col:
            m = _UNIT_RE.search(header[col[key]])
            if m:
                col_unit[key] = m.group(1).lower()

    def length(cell: str, key: str) -> float:
        c = cell.strip()
        if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", c):
            u = col_unit.get(key, file_unit)
            return to_si(float(c), "in" if u == "inch" else u, Kind.LENGTH)
        return parse_quantity(c, Kind.LENGTH)

    out: list[PlacedComponent] = []
    for r in table[1:]:
        if len(r) <= max(col["ref"], col["x"], col["y"]):
            continue
        try:
            rot = float(r[col["rot"]]) if "rot" in col and r[col["rot"]].strip() else 0.0
            hgt = (
                length(r[col["height"]], "height")
                if "height" in col and r[col["height"]].strip()
                else None
            )
            out.append(
                PlacedComponent(
                    ref=r[col["ref"]].strip(),
                    x=length(r[col["x"]], "x"),
                    y=length(r[col["y"]], "y"),
                    rotation=rot % 360.0,
                    side=_side(r[col["side"]]) if "side" in col else "top",
                    footprint=r[col["footprint"]].strip() if "footprint" in col else "",
                    value=r[col["value"]].strip() if "value" in col else "",
                    height=hgt,
                )
            )
        except (ValueError, IndexError) as exc:
            raise CadFormatError(f"{source}: bad pick-and-place row {r}: {exc}") from None
    return out


class _Spaces(csv.Dialect):
    delimiter = " "
    quotechar = '"'
    skipinitialspace = True
    lineterminator = "\n"
    quoting = csv.QUOTE_MINIMAL
