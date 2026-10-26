"""Excellon drill / route reader (NC drill files written by KiCad, Altium, Eagle …).

Source: the public Excellon format description (Excellon Automation Co. CNC-7
programming manual, "XNC" subset as documented in the Ucamco/KiCad Excellon
writer notes). No vendor software was inspected.

Header (``M48`` … ``%`` or ``M95``)
    ``METRIC`` / ``INCH`` optionally followed by ``,LZ`` / ``,TZ`` and a digit
    format such as ``,000.000``; ``M71`` (metric) / ``M72`` (inch); ``FMAT,2``;
    tool definitions ``T1C0.300`` or ``T01F00S00C0.0300`` (C = diameter).

Zero suppression for coordinates without a decimal point
    Excellon names the zeros that are *kept*:

    * ``LZ`` — leading zeros included, trailing zeros suppressed → pad on the
      right to the full digit count, i.e. value = int(digits) / 10^(n_digits − n_int)
    * ``TZ`` — trailing zeros included, leading zeros suppressed → the last
      ``n_dec`` digits are decimals, i.e. value = int(digits) / 10^n_dec

    Default digit format 2:4 for inch, 3:3 for metric, unless ``,000.000`` or a
    ``;FILE_FORMAT=a:b`` comment (KiCad) says otherwise. Coordinates with a
    decimal point are taken literally.

Body
    ``Tn`` selects a tool (``T0`` unloads); ``X…Y…`` drills (missing axis =
    modal previous value); ``X…Y…G85X…Y…`` is a slot; route mode ``G00X…Y…``
    then ``M15`` (tool down), ``G01X…Y…`` segments become slots, ``M16``/``M17``
    lifts; ``M30`` ends. Arcs (``G02``/``G03``) in route mode are reduced to a
    straight slot with a warning.

Plating
    KiCad writes X2-style comments: ``; #@! TF.FileFunction,Plated,1,4,PTH`` /
    ``NonPlated,1,2,NPTH`` (file level) and ``; #@! TA.AperFunction,Plated,PTH,…``
    before tool definitions (per tool). Without these, a file name containing
    ``NPTH`` means non-plated and ``PTH`` plated. An explicit ``plated``
    argument overrides everything.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import DrillData, Hole, Slot
from pcbsim.units import INCH, MM

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)"
_COORD = re.compile(rf"([XY])({_NUM})")
_TOOL_DEF = re.compile(r"^T(\d+)((?:[A-Z][-+]?[\d.]+)*)$")
_TOOL_PARAM = re.compile(r"([A-Z])([-+]?[\d.]+)")


@dataclass(slots=True)
class _Fmt:
    unit: float = INCH
    zeros: str = "LZ"  # which zeros are kept
    n_int: int = 2
    n_dec: int = 4
    explicit_digits: bool = False

    def set_unit(self, metric: bool) -> None:
        self.unit = MM if metric else INCH
        if not self.explicit_digits:
            self.n_int, self.n_dec = (3, 3) if metric else (2, 4)


def _value(text: str, fmt: _Fmt) -> float:
    if "." in text:
        return float(text) * fmt.unit
    sign = -1.0 if text.startswith("-") else 1.0
    digits = text.lstrip("+-")
    if not digits:
        raise ValueError("empty coordinate")
    if fmt.zeros == "LZ":
        total = fmt.n_int + fmt.n_dec
        digits = digits.ljust(total, "0")
        v = int(digits) / 10.0 ** (len(digits) - fmt.n_int)
    else:
        v = int(digits) / 10.0**fmt.n_dec
    return sign * v * fmt.unit


def _plating_from_attr(text: str) -> bool | None:
    t = text.lower()
    if "nonplated" in t or "npth" in t:
        return False
    if "plated" in t or "pth" in t:
        return True
    return None


def parse_excellon(
    source: str | Path, *, text: str | None = None, plated: bool | None = None
) -> DrillData:
    """Parse one Excellon file into holes and slots (metres)."""
    path = Path(source)
    raw = text if text is not None else path.read_text("utf-8", errors="replace")
    data = DrillData(path=path)
    fmt = _Fmt()
    file_plated: bool | None = None
    name = path.name.upper()
    if "NPTH" in name:
        name_plated: bool | None = False
    elif "PTH" in name:
        name_plated = True
    else:
        name_plated = None
    pending_tool_plated: bool | None = None
    tools: dict[int, tuple[float, bool | None]] = {}
    tool: int | None = None
    x = y = 0.0
    in_header = False
    route = False
    tool_down = False
    unit_seen = False
    unknown: set[str] = set()

    def tool_info() -> tuple[float, bool | None, str]:
        if tool is None or tool not in tools:
            raise CadFormatError(f"{path.name}: drill hit before any tool was selected")
        d, p = tools[tool]
        resolved = plated if plated is not None else (p if p is not None else file_plated)
        if resolved is None:
            resolved = name_plated
        return d, resolved, f"T{tool}"

    for lineno, line_raw in enumerate(raw.splitlines(), 1):
        line = line_raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            body = line[1:].strip()
            if body.startswith("#@!"):
                attr = body[3:].strip()
                if attr.startswith("TF.FileFunction"):
                    file_plated = _plating_from_attr(attr.split(",", 1)[1] if "," in attr else "")
                elif attr.startswith("TA.AperFunction"):
                    pending_tool_plated = _plating_from_attr(attr.split(",", 1)[-1].split(",")[0])
            m = re.search(r"FORMAT\s*=\s*\{?\s*(\d)\s*:\s*(\d)", body, re.IGNORECASE)
            if m:
                fmt.n_int, fmt.n_dec = int(m.group(1)), int(m.group(2))
                fmt.explicit_digits = True
            continue
        line = line.upper().replace(" ", "")
        if line == "M48":
            in_header = True
            continue
        if line in ("%", "M95"):
            in_header = False
            continue
        if line.startswith(("METRIC", "INCH")):
            parts = line.split(",")
            fmt.set_unit(parts[0] == "METRIC")
            unit_seen = True
            for p in parts[1:]:
                if p in ("LZ", "TZ"):
                    fmt.zeros = p
                elif re.fullmatch(r"0*\.0*", p):
                    a, b = p.split(".")
                    fmt.n_int, fmt.n_dec = len(a), len(b)
                    fmt.explicit_digits = True
            continue
        if line in ("M71", "M72"):
            fmt.set_unit(line == "M71")
            unit_seen = True
            continue
        if line == "M30" or line == "M00":
            break
        if line.startswith(("FMAT", "VER", "ICI", "ATC", "G90", "G05", "DETECT", "OF", "T0")):
            if line.startswith("ICI,ON") or line == "ICI":
                data.warnings.append(f"{path.name}: incremental input (ICI) is not supported")
            if line == "T0" or re.fullmatch(r"T0+", line):
                tool = None
            continue
        if line.startswith("G91"):
            data.warnings.append(f"{path.name}:{lineno}: incremental mode G91 not supported")
            continue
        m = _TOOL_DEF.match(line)
        if m and (in_header or "C" in m.group(2)) and m.group(2):
            params = dict(_TOOL_PARAM.findall(m.group(2)))
            if "C" in params:
                tools[int(m.group(1))] = (float(params["C"]) * fmt.unit, pending_tool_plated)
                pending_tool_plated = None
                if not in_header:
                    tool = int(m.group(1))
            continue
        if m and not m.group(2):
            t = int(m.group(1))
            tool = t if t != 0 else None
            if tool is not None and tool not in tools:
                data.warnings.append(f"{path.name}:{lineno}: tool T{t} used but not defined")
            continue
        if in_header:
            continue
        if line.startswith("M15"):
            tool_down = True
            continue
        if line.startswith(("M16", "M17")):
            tool_down = False
            continue
        g = re.match(r"^G0?([0-3])(?=[XY]|$)", line)
        if g:
            code = int(g.group(1))
            rest = line[g.end() :]
            if code == 0:
                route, tool_down = True, False
            elif code in (2, 3):
                data.warnings.append(
                    f"{path.name}:{lineno}: routed arc G0{code} approximated by a straight slot"
                )
            line = rest
            if not line:
                continue
            if code in (1, 2, 3) and route and tool_down:
                nx, ny = _coords(line, x, y, fmt)
                d, pl, tname = tool_info()
                data.slots.append(Slot(x, y, nx, ny, d, pl, tname))
                x, y = nx, ny
                continue
            if code == 0:
                x, y = _coords(line, x, y, fmt)
                continue
        if "G85" in line:
            a, b = line.split("G85", 1)
            x0, y0 = _coords(a, x, y, fmt)
            x1, y1 = _coords(b, x0, y0, fmt)
            d, pl, tname = tool_info()
            data.slots.append(Slot(x0, y0, x1, y1, d, pl, tname))
            x, y = x1, y1
            continue
        if line[0] in "XY":
            try:
                x, y = _coords(line, x, y, fmt)
            except ValueError as exc:
                raise CadFormatError(f"{path.name}:{lineno}: bad coordinate {line!r}") from exc
            if route:
                continue
            d, pl, tname = tool_info()
            data.holes.append(Hole(x, y, d, pl, tname))
            continue
        key = re.match(r"^[A-Z]+\d*", line)
        unknown.add(key.group(0) if key else line[:8])
    if unknown:
        data.warnings.append(f"{path.name}: ignored commands {sorted(unknown)}")
    if not unit_seen:
        data.warnings.append(f"{path.name}: no METRIC/INCH header; assumed inch")
    data.unit = "mm" if fmt.unit == MM else "in"
    return data


def _coords(text: str, x: float, y: float, fmt: _Fmt) -> tuple[float, float]:
    found = dict(_COORD.findall(text))
    if not found:
        raise ValueError(f"no coordinate in {text!r}")
    nx = _value(found["X"], fmt) if "X" in found else x
    ny = _value(found["Y"], fmt) if "Y" in found else y
    return nx, ny


def load_drills(paths: Sequence[Path]) -> DrillData:
    """Parse and merge several drill files (e.g. KiCad ``-PTH.drl`` + ``-NPTH.drl``)."""
    out = DrillData(path=None)
    for p in paths:
        d = parse_excellon(p)
        out.holes += d.holes
        out.slots += d.slots
        out.warnings += d.warnings
        out.unit = d.unit
    return out
