"""Physics sections of the results report: power/IR drop, vias, components, coupled, SI.

Each function takes the per-solver entries of ``results.json`` (see
:mod:`pcbsim.post.results_loader`) and returns an HTML fragment. Values are
shown exactly as stored, converted only for display:

* V, A, Ω as stored; drop in mV = ``drop_v``·10³, R_path in mΩ;
* temperatures stored in K are shown in °C (T[°C] = T[K] − 273.15);
* margins and ΔT are differences, so K = °C.

When a field the table needs is absent (older or partial results), the cell
shows "–" and the section says which data is missing — nothing is estimated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from pcbsim.post.html_kit import (
    DASH,
    Cell,
    Col,
    badge,
    empty,
    esc,
    fmt,
    fmt_g,
    notes_list,
    number,
    pass_badge,
    table,
    text,
)
from pcbsim.post.results_loader import num

K0 = 273.15
SOURCE = "voltage_source"
SINK = "current_sink"
ELECTRICAL = ("dc_ir", "coupled")
THERMAL = ("thermal", "coupled")
VIA_ROWS_SHOWN = 25

Solvers = Mapping[str, Mapping[str, Any]]


def _rows(entry: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in entry.get(key) or [] if isinstance(r, dict)]


def _scalars(entry: Mapping[str, Any]) -> dict[str, Any]:
    s = entry.get("scalars")
    return s if isinstance(s, dict) else {}


def _celsius(k: float | None) -> float | None:
    return None if k is None else k - K0


def _c(value: float | None, nd: int = 3, scale: float = 1.0, offset: float = 0.0) -> Cell:
    return number(None if value is None else value * scale + offset, fmt(value, nd, scale, offset))


def _missing_note(rows: Sequence[Mapping[str, Any]], keys: Sequence[str], what: str) -> list[str]:
    absent = [k for k in keys if rows and all(num(r.get(k)) is None for r in rows)]
    if not absent:
        return []
    return [f"{what}: results.json has no value for {', '.join(absent)} (shown as –)."]


def _not_run(names: Sequence[str]) -> str:
    return empty(f"Not run — results.json has no {' / '.join(names)} solver results.")


# --------------------------------------------------------------------------- power / IR drop


def _sink_table(sinks: list[dict[str, Any]]) -> str:
    cols = [
        Col("Sink"),
        Col("Layer"),
        Col("I [A]", True),
        Col("V_nom [V]", True),
        Col("V_avg [V]", True),
        Col("V_min [V]", True),
        Col("Drop [mV]", True),
        Col("Drop [%]", True),
        Col("Limit [%]", True),
        Col("R_path [mΩ]", True),
        Col("Result"),
    ]
    rows = []
    for r in sorted(sinks, key=lambda r: -(num(r.get("drop_pct")) or -math.inf)):
        rows.append(
            [
                text(r.get("name")),
                text(r.get("layer")),
                _c(num(r.get("current")), 4),
                _c(num(r.get("v_nominal")), 4),
                _c(num(r.get("v_avg")), 4),
                _c(num(r.get("v_min")), 4),
                _c(num(r.get("drop_v")), 2, 1e3),
                _c(num(r.get("drop_pct")), 3),
                _c(num(r.get("limit_pct")), 2),
                _c(num(r.get("r_path")), 3, 1e3),
                Cell(pass_badge(r.get("passed")), str(r.get("passed"))),
            ]
        )
    return table(cols, rows, "Current sinks, worst drop first")


def _source_table(sources: list[dict[str, Any]]) -> str:
    cols = [
        Col("Source"),
        Col("Layer"),
        Col("Reference"),
        Col("V [V]", True),
        Col("I [A]", True),
        Col("P [W]", True),
    ]
    rows = [
        [
            text(r.get("name")),
            text(r.get("layer")),
            text(r.get("reference_net")),
            _c(num(r.get("voltage")), 4),
            _c(num(r.get("current")), 4),
            _c(num(r.get("power")), 4),
        ]
        for r in sources
    ]
    return table(cols, rows, "Voltage sources")


def _density_table(sc: Mapping[str, Any], layers: Sequence[str]) -> str:
    rows = []
    for lname in layers:
        jm, jl = num(sc.get(f"{lname}.j_max")), num(sc.get(f"{lname}.j_limit"))
        if jm is None and jl is None:
            continue
        ok: bool | None = None if jl is None or jm is None else jm <= jl
        rows.append(
            [
                text(lname),
                _c(jm, 2, 1e-6),
                _c(jl, 2, 1e-6),
                Cell(pass_badge(ok) if jl is not None else badge("na", "no limit"), str(ok)),
            ]
        )
    if not rows:
        return ""
    cols = [Col("Layer"), Col("J_max [A/mm²]", True), Col("Limit [A/mm²]", True), Col("Result")]
    return table(cols, rows, "Peak current density per layer (IPC-2152 limit)")


def _power_one(name: str, entry: Mapping[str, Any], layers: Sequence[str]) -> str:
    ports = _rows(entry, "ports")
    sc = _scalars(entry)
    parts = [f"<h3>{esc(name)}</h3>"]
    if name == "coupled":
        parts.append('<p class="note">At the electro-thermal fixed point (ρ(T) applied).</p>')
    if not ports:
        parts.append(empty("No source/sink ports recorded for this solver."))
        return "".join(parts)
    nets: dict[str, list[dict[str, Any]]] = {}
    for r in ports:
        nets.setdefault(str(r.get("net") or "?"), []).append(r)
    notes: list[str] = []
    for net, rows in nets.items():
        sources = [r for r in rows if r.get("kind") == SOURCE]
        sinks = [r for r in rows if r.get("kind") == SINK]
        lo, hi = num(sc.get(f"{net}.v_min")), num(sc.get(f"{net}.v_max"))
        rng = f" · copper V {fmt(lo, 4)} … {fmt(hi, 4)} V" if lo is not None else ""
        parts.append(f'<p><strong>Net {esc(net)}</strong><span class="note">{esc(rng)}</span></p>')
        parts.append(_source_table(sources) if sources else empty("No voltage source on this net."))
        parts.append(_sink_table(sinks) if sinks else empty("No current sinks on this net."))
        if len(sources) > 1 and sinks:
            notes.append(
                f"Net {net} has {len(sources)} sources: results.json gives each sink's drop "
                "against the net's nominal voltage, not which source feeds it."
            )
        notes += _missing_note(sinks, ("v_min", "drop_pct", "r_path"), f"Net {net} sinks")
        notes += _missing_note(sources, ("current", "power"), f"Net {net} sources")
    joule = num(sc.get("joule_power"))
    if joule is not None:
        parts.append(f'<p class="note">Conduction (Joule) loss {joule * 1e3:.2f} mW.</p>')
    parts.append(_density_table(sc, layers))
    parts.append(notes_list(notes))
    return "".join(parts)


def power_section(solvers: Solvers, layers: Sequence[str]) -> str:
    present = [n for n in ELECTRICAL if n in solvers]
    if not present:
        return _not_run(ELECTRICAL)
    return "".join(_power_one(n, solvers[n], layers) for n in present)


# --------------------------------------------------------------------------- vias / components


def _via_table(vias: list[dict[str, Any]]) -> str:
    def use(r: Mapping[str, Any]) -> float | None:
        i, lim = num(r.get("current")), num(r.get("limit"))
        return None if i is None or lim is None or lim <= 0 else i / lim * 100.0

    ordered = sorted(vias, key=lambda r: -(u if (u := use(r)) is not None else -1.0))
    cols = [
        Col("Via #", True),
        Col("Net"),
        Col("x [mm]", True),
        Col("y [mm]", True),
        Col("I [A]", True),
        Col("Limit [A]", True),
        Col("Use [%]", True),
        Col("Result"),
    ]

    def row(r: Mapping[str, Any]) -> list[Cell]:
        lim = num(r.get("limit"))
        idx = num(r.get("index"))
        checked = lim is not None
        res = pass_badge(r.get("passed")) if checked else badge("na", "not checked")
        return [
            number(idx, DASH if idx is None else str(int(idx))),
            text(r.get("net")),
            _c(num(r.get("x")), 3, 1e3),
            _c(num(r.get("y")), 3, 1e3),
            _c(num(r.get("current")), 3),
            _c(lim, 3) if checked else Cell("not checked", ""),
            _c(use(r), 1),
            Cell(res, str(r.get("passed")) if checked else ""),
        ]

    head = ordered[:VIA_ROWS_SHOWN]
    out = table(cols, [row(r) for r in head], "Highest barrel-current utilisation first")
    rest = ordered[VIA_ROWS_SHOWN:]
    if rest:
        out += (
            f"<details><summary>Show the other {len(rest)} vias</summary>"
            + table(cols, [row(r) for r in rest])
            + "</details>"
        )
    return out


def _component_table(comps: list[dict[str, Any]]) -> str:
    cols = [
        Col("Ref"),
        Col("P [W]", True),
        Col("Thermal model"),
        Col("Tj [°C]", True),
        Col("Tj peak [°C]", True),
        Col("T_board [°C]", True),
        Col("Tj_max [°C]", True),
        Col("Margin [K]", True),
        Col("Result"),
    ]
    model = {"two_resistor": "two-resistor (θJC/θJB)", "board": "board temperature"}
    rows = [
        [
            text(r.get("ref")),
            _c(num(r.get("power")), 3),
            text(model.get(str(r.get("model")), r.get("model"))),
            _c(_celsius(num(r.get("tj"))), 1),
            _c(_celsius(num(r.get("tj_peak"))), 1),
            _c(_celsius(num(r.get("t_board"))), 1),
            _c(_celsius(num(r.get("tj_max"))), 1),
            _c(num(r.get("margin")), 1),
            Cell(pass_badge(r.get("passed")), str(r.get("passed"))),
        ]
        for r in sorted(comps, key=lambda r: num(r.get("margin")) or math.inf)
    ]
    return table(cols, rows, "Smallest margin first")


def _thermal_summary(sc: Mapping[str, Any], layers: Sequence[str]) -> str:
    items = [f"{n} T_max {fmt(_celsius(num(sc.get(f'{n}.t_max'))), 1)} °C" for n in layers]
    pc, pj = num(sc.get("power_components")), num(sc.get("power_joule"))
    if pc is not None:
        items.append(f"heat in: components {pc:.3f} W, Joule {fmt(pj, 1, 1e3)} mW")
    flows = [
        f"{k.removeprefix('heat_out.')} {fmt(num(v), 3)} W"
        for k, v in sc.items()
        if k.startswith("heat_out.")
    ]
    if flows:
        items.append("heat out: " + ", ".join(flows))
    return notes_list(items)


def via_component_section(solvers: Solvers, layers: Sequence[str]) -> str:
    parts = ["<h3>Vias</h3>"]
    elec = [n for n in ELECTRICAL if n in solvers]
    if not elec:
        parts.append(_not_run(ELECTRICAL))
    for n in elec:
        vias = _rows(solvers[n], "vias")
        parts.append(f'<p class="note">From <code>{esc(n)}</code>.</p>')
        parts.append(_via_table(vias) if vias else empty("No via currents recorded."))
    parts.append("<h3>Components</h3>")
    therm = [n for n in THERMAL if n in solvers]
    if not therm:
        parts.append(_not_run(THERMAL))
    for n in therm:
        comps = _rows(solvers[n], "components")
        parts.append(f'<p class="note">From <code>{esc(n)}</code>.</p>')
        parts.append(_component_table(comps) if comps else empty("No components recorded."))
        parts.append(_thermal_summary(_scalars(solvers[n]), layers))
    return "".join(parts)


# --------------------------------------------------------------------------- coupled


def _series(hist: Mapping[str, Any], key: str) -> list[float | None]:
    v = hist.get(key)
    return [num(x) for x in v] if isinstance(v, list) else []


def convergence_svg(hist: Mapping[str, Any]) -> str:
    """Semilog plot of max|ΔT| [K] and max|ΔV| [V] per pass (inline SVG)."""
    it = _series(hist, "iteration")
    series = [
        ("max |ΔT| [K]", "#b91c1c", _series(hist, "delta_t")),
        ("max |ΔV| [V]", "#1d4ed8", _series(hist, "delta_v")),
    ]
    pts = [
        [(k, v) for k, v in zip(it, ys, strict=False) if k is not None and v is not None and v > 0]
        for _, _, ys in series
    ]
    flat = [p for s in pts for p in s]
    if not flat:
        return ""
    w, h, ml, mr, mt, mb = 560.0, 260.0, 56.0, 16.0, 16.0, 40.0
    kx0, kx1 = min(p[0] for p in flat), max(p[0] for p in flat)
    ly = [math.log10(p[1]) for p in flat]
    y0, y1 = math.floor(min(ly)), math.ceil(max(ly))
    if y1 == y0:
        y1 += 1

    def sx(k: float) -> float:
        return ml + (k - kx0) / ((kx1 - kx0) or 1.0) * (w - ml - mr)

    def sy(v: float) -> float:
        return mt + (y1 - math.log10(v)) / (y1 - y0) * (h - mt - mb)

    g = [f'<rect x="{ml}" y="{mt}" width="{w - ml - mr}" height="{h - mt - mb}" fill="#fff"/>']
    for e in range(y0, y1 + 1):
        y = sy(10.0**e)
        g.append(f'<line x1="{ml}" x2="{w - mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="#d4d4d8"/>')
        g.append(
            f'<text x="{ml - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11">1e{e}</text>'
        )
    for k in sorted({int(p[0]) for p in flat}):
        g.append(
            f'<text x="{sx(k):.1f}" y="{h - mb + 16}" text-anchor="middle" font-size="11">'
            f"{k}</text>"
        )
    g.append(
        f'<text x="{(ml + w - mr) / 2}" y="{h - 6}" text-anchor="middle" font-size="12">pass</text>'
    )
    for (label, color, _), s in zip(series, pts, strict=True):
        if not s:
            continue
        line = " ".join(f"{sx(k):.1f},{sy(v):.1f}" for k, v in s)
        g.append(f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2"/>')
        g += [
            f'<circle cx="{sx(k):.1f}" cy="{sy(v):.1f}" r="3.5" fill="{color}">'
            f"<title>{esc(label)} pass {int(k)}: {v:.3g}</title></circle>"
            for k, v in s
        ]
    legend = [
        f'<text x="{ml + 8}" y="{mt + 16 + 16 * i}" font-size="12" fill="{c}">{esc(lbl)}</text>'
        for i, (lbl, c, _) in enumerate(series)
    ]
    return (
        f'<svg class="chart" viewBox="0 0 {w:.0f} {h:.0f}" role="img" '
        'aria-label="Change between passes of the electro-thermal iteration (log scale)" '
        f'font-family="system-ui,sans-serif" fill="#18181b">{"".join(g + legend)}</svg>'
    )


def _history_table(hist: Mapping[str, Any]) -> str:
    it = _series(hist, "iteration")
    cols_keys = [
        ("ΔT [K]", "delta_t", 3, 1.0, 0.0),
        ("ΔV [mV]", "delta_v", 3, 1e3, 0.0),
        ("T_max [°C]", "t_max", 2, 1.0, -K0),
        ("Joule [mW]", "joule_power", 2, 1e3, 0.0),
        ("Worst drop [%]", "drop_pct_max", 3, 1.0, 0.0),
    ]
    data = {k: _series(hist, k) for _, k, *_ in cols_keys}
    rows = []
    for i, k in enumerate(it):
        row = [number(k, "–" if k is None else str(int(k)))]
        for _, key, nd, scale, off in cols_keys:
            v = data[key][i] if i < len(data[key]) else None
            row.append(_c(v, nd, scale, off))
        rows.append(row)
    cols = [Col("Pass", True)] + [Col(t, True) for t, *_ in cols_keys]
    return table(
        cols, rows, "Pass 0 is the uncoupled solution; ΔT/ΔV are changes vs the previous pass"
    )


def _comparison(entry: Mapping[str, Any]) -> str:
    sc = _scalars(entry)
    rows: list[list[Cell]] = []

    def add(item: str, qty: str, before: float | None, after: float | None, unit: str) -> None:
        delta = None if before is None or after is None else after - before
        rows.append([text(item), text(qty), _c(before, 3), _c(after, 3), _c(delta, 3), text(unit)])

    for r in _rows(entry, "ports"):
        if r.get("kind") == SINK:
            name = str(r.get("name"))
            add(
                name,
                "IR drop",
                num(sc.get(f"{name}.drop_pct.uncoupled")),
                num(r.get("drop_pct")),
                "%",
            )
    for r in _rows(entry, "components"):
        ref = str(r.get("ref"))
        before = _celsius(num(sc.get(f"{ref}.tj.uncoupled")))
        add(ref, "Tj", before, _celsius(num(r.get("tj"))), "°C")
    add(
        "board",
        "T_max",
        _celsius(num(sc.get("t_max.uncoupled"))),
        _celsius(num(sc.get("t_max"))),
        "°C",
    )
    jb, ja = num(sc.get("joule_power.uncoupled")), num(sc.get("joule_power"))
    add(
        "board",
        "Joule loss",
        None if jb is None else jb * 1e3,
        None if ja is None else ja * 1e3,
        "mW",
    )
    if all(r[2].sort == "" for r in rows):
        return empty("results.json holds no uncoupled reference values.")
    cols = [
        Col("Item"),
        Col("Quantity"),
        Col("Uncoupled", True),
        Col("Coupled", True),
        Col("Δ", True),
        Col("Unit"),
    ]
    return table(cols, rows, "Uncoupled = pass 0 (no ρ(T)); coupled = fixed point")


def coupled_section(solvers: Solvers, convergence_img: str = "") -> str:
    entry = solvers.get("coupled")
    if entry is None:
        return _not_run(["coupled"])
    sc = _scalars(entry)
    conv = num(sc.get("converged"))
    iters = num(sc.get("iterations"))
    if conv is None:
        state = badge("na", "unknown")
    elif conv >= 0.5:
        state = badge("pass", "CONVERGED")
    else:
        state = badge("fail", "NOT CONVERGED")
    stats = [
        ("Status", state),
        ("Passes", esc("–" if iters is None else str(int(iters)))),
        ("Final ΔT", esc(f"{fmt_g(num(sc.get('delta_t')), 3)} K")),
        ("Final ΔV", esc(f"{fmt_g(num(sc.get('delta_v')), 3)} V")),
        ("Contraction κ", esc(fmt_g(num(sc.get("contraction")), 3))),
    ]
    parts = ['<dl class="stats">']
    parts += [f"<div><dt>{esc(a)}</dt><dd>{b}</dd></div>" for a, b in stats]
    parts.append("</dl>")
    hist = entry.get("history") or {}
    parts.append("<h3>Convergence history</h3>")
    if _series(hist, "iteration"):
        parts.append(convergence_svg(hist))
        parts.append(_history_table(hist))
    else:
        parts.append(empty("results.json has no iteration history for coupled."))
    if convergence_img:
        parts.append(convergence_img)
    parts.append(
        '<p class="note">The tolerances tol_t / tol_v are not stored in results.json; '
        "see <code>analysis.options.coupled</code> in the config.</p>"
    )
    parts.append("<h3>Coupled vs uncoupled</h3>")
    parts.append(_comparison(entry))
    return "".join(parts)


# --------------------------------------------------------------------------- SI


def si_section(solvers: Solvers) -> str:
    entry = solvers.get("si")
    if entry is None:
        return _not_run(["si"])
    lines = _rows(entry, "lines")
    if not lines:
        return empty("The si solver ran but recorded no transmission lines.")
    cols = [
        Col("Line"),
        Col("Topology"),
        Col("Layer"),
        Col("Z"),
        Col("FEM [Ω]", True),
        Col("Closed form [Ω]", True),
        Col("Formula"),
        Col("FEM vs formula [%]", True),
        Col("εeff (FEM)", True),
        Col("Target [Ω]", True),
        Col("Tol. [%]", True),
        Col("Deviation [%]", True),
        Col("Result"),
    ]
    rows = []
    for r in lines:
        dev = num(r.get("crosscheck_dev"))
        target = num(r.get("target"))
        if target is None:
            res = Cell(badge("na", "no target"), "")
        else:
            res = Cell(pass_badge(r.get("passed")), str(r.get("passed")))
        rows.append(
            [
                text(r.get("name")),
                text(r.get("topology")),
                text(r.get("layer")),
                text(r.get("quantity")),
                _c(num(r.get("z_fem")), 2),
                _c(num(r.get("z_formula")), 2),
                text(r.get("formula")),
                _c(None if dev is None else dev * 100.0, 2),
                _c(num(r.get("eps_eff_fem")), 3),
                _c(target, 1),
                _c(num(r.get("tolerance_pct")) if target is not None else None, 1),
                _c(num(r.get("target_dev_pct")), 2),
                res,
            ]
        )
    note = (
        '<p class="note">FEM is the 2D quasi-static cross-section solution; the closed form is '
        "the best formula for the geometry (theory.md §7). Z is Z0 for a single trace and "
        "Zdiff for a pair.</p>"
    )
    return table(cols, rows) + note
