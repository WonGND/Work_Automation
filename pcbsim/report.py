"""Simulation report: one self-contained HTML file built from a results directory.

Inputs are only what :func:`pcbsim.runner.write_results` writes — ``results.json``
and ``<solver>_fields.npz`` — so a report can be rebuilt later, on another machine,
without re-running the solvers. Heat maps and the convergence plot are rendered
with matplotlib and embedded as base64 PNG; CSS and the small layer/field picker
script are inline, so the file opens offline and can be mailed as is.

Sections: verdict and key numbers, findings (all violations and warnings, worst
first), IR drop per sink (the text form of a power tree), via currents, component
temperatures and heat paths, coupled-iteration history, transmission lines,
field maps, model notes.
"""

from __future__ import annotations

import base64
import html
import io
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from pcbsim.errors import PcbsimError

T0 = 273.15

_SCALE: dict[str, tuple[float, float, str, str]] = {
    "voltage": (1.0, 0.0, "V", "viridis"),
    "current_density": (1e-6, 0.0, "A/mm²", "inferno"),
    "power_density": (1e-4, 0.0, "W/cm²", "magma"),
    "temperature": (1.0, -T0, "°C", "plasma"),
}
_FIELD_LABEL = {
    "voltage": "Voltage",
    "current_density": "Current density",
    "temperature": "Temperature",
    "power_density": "Power density",
}
_SEVERITY_ORDER = {"violation": 0, "warning": 1, "info": 2}

_CSS = """
:root{--fg:#18181b;--muted:#52525b;--faint:#a1a1aa;--line:rgba(0,0,0,.08);--well:#fafafa;
--accent:#0f766e;--ng:#b91c1c;--warn:#b45309;--ok:#15803d}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI","Malgun Gothic",Roboto,sans-serif;
color:var(--fg);background:#fff}
main{max-width:72rem;margin:0 auto;padding:2rem 1.25rem 4rem}
h1{font-size:1.75rem;font-weight:600;letter-spacing:-.01em;margin:0 0 .25rem}
h2{font-size:1.125rem;font-weight:600;margin:2.75rem 0 .75rem}
h3{font-size:1rem;font-weight:500;margin:1.5rem 0 .5rem;color:var(--muted)}
p.sub{color:var(--muted);margin:0 0 1.25rem;max-width:72ch}
nav{display:flex;flex-wrap:wrap;gap:.25rem 1rem;font-size:.875rem;margin:1rem 0 0}
nav a{color:var(--accent);text-decoration:none}nav a:hover{text-decoration:underline}
.verdict{display:inline-flex;gap:.5rem;align-items:center;font-weight:600;padding:.25rem .625rem;
border-radius:6px;font-size:.875rem}
.verdict.ok{background:#f0fdf4;color:var(--ok)}.verdict.ng{background:#fef2f2;color:var(--ng)}
.stats{display:flex;flex-wrap:wrap;border-block:1px solid var(--line);margin:1.25rem 0}
.stats div{padding:.875rem 1.5rem .875rem 0;margin-right:1.5rem;border-right:1px solid var(--line)}
.stats div:last-child{border-right:0}
.stats dt{font-size:.8125rem;color:var(--muted)}
.stats dd{margin:0;font-size:1.25rem;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.875rem}
th{text-align:left;font-weight:500;color:var(--muted);white-space:nowrap;
padding:.5rem .75rem .5rem 0;border-bottom:1px solid var(--line)}
td{padding:.5rem .75rem .5rem 0;border-bottom:1px solid var(--line);vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{font-size:.75rem;font-weight:600;letter-spacing:.02em;white-space:nowrap}
.tag.violation,.tag.FAIL{color:var(--ng)}.tag.warning{color:var(--warn)}
.tag.info{color:var(--muted)}.tag.PASS{color:var(--ok)}
.bar{display:inline-block;height:.375rem;border-radius:3px;background:var(--accent);
vertical-align:middle}.bar.over{background:var(--ng)}
figure{margin:0;background:var(--well);border-radius:8px;padding:1rem}
figure img{width:100%;height:auto;display:block}
figcaption{font-size:.8125rem;color:var(--muted);margin-top:.5rem}
.picker{display:flex;flex-wrap:wrap;gap:.75rem;align-items:end;margin-bottom:.75rem}
.picker label{display:flex;flex-direction:column;font-size:.8125rem;color:var(--muted);gap:.25rem}
select{font:inherit;font-size:.875rem;padding:.375rem .5rem;border-radius:6px;
border:1px solid rgba(0,0,0,.15);background:#fff;color:var(--fg)}
select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.map{display:none}.map.on{display:block}
ul.notes{padding-left:1.25rem;color:var(--muted);font-size:.875rem;max-width:80ch}
code{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
details summary{cursor:pointer;color:var(--accent);font-size:.875rem;margin:.5rem 0}
.empty{color:var(--muted);font-size:.875rem}
@media (min-width:640px){body{font-size:15px}}
@media print{nav,.picker{display:none}.map{display:block;break-inside:avoid;margin-bottom:1rem}}
"""

_JS = """
(function(){
  var s=document.getElementById('mapsel'); if(!s) return;
  var sels=s.querySelectorAll('select');
  function upd(){
    var key=Array.prototype.map.call(sels,function(x){return x.value}).join('|');
    document.querySelectorAll('.map').forEach(function(m){
      m.classList.toggle('on', m.dataset.key===key);
    });
  }
  sels.forEach(function(x){x.addEventListener('change',upd)}); upd();
})();
"""


def _e(x: object) -> str:
    return html.escape(str(x))


def _num(v: Any, fmt: str = ".4g", scale: float = 1.0, offset: float = 0.0) -> str:
    if v is None:
        return "–"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _e(v)
    if not math.isfinite(f):
        return "–"
    val = f * scale + offset
    if fmt == "d":
        return str(round(val))
    return format(val, fmt)


def _c(v: Any) -> str:
    return _num(v, ".1f", offset=-T0)


def _table(
    head: Sequence[str], rows: Iterable[Sequence[str]], numeric: set[int] | None = None
) -> str:
    numeric = numeric or set()
    th = "".join(
        f'<th class="n">{_e(h)}</th>' if i in numeric else f"<th>{_e(h)}</th>"
        for i, h in enumerate(head)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="n">{c}</td>' if i in numeric else f"<td>{c}</td>" for i, c in enumerate(r)
        )
        + "</tr>"
        for r in rows
    )
    return (
        f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'
    )


def _pass(ok: Any) -> str:
    return '<span class="tag PASS">PASS</span>' if ok else '<span class="tag FAIL">FAIL</span>'


def _png(fig: Any) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def load_results(results_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """``results.json`` and the field arrays ``{solver: {"name__layer": array}}``."""
    rj = results_dir / "results.json"
    if not rj.is_file():
        raise PcbsimError(f"{results_dir}: no results.json (run 'pcbsim run' first)")
    try:
        doc: dict[str, Any] = json.loads(rj.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise PcbsimError(f"{rj}: not valid JSON ({exc})") from None
    if "solvers" not in doc:
        raise PcbsimError(f"{rj}: not a pcbsim results file")
    fields: dict[str, dict[str, Any]] = {}
    for name in doc["solvers"]:
        npz = results_dir / f"{name}_fields.npz"
        if npz.is_file():
            with np.load(npz) as z:
                fields[name] = {k: np.asarray(z[k]) for k in z.files}
    return doc, fields


def draw_field(
    fig: Any,
    values: Any,
    extent: Sequence[float],
    name: str,
    title: str,
    geometry: Mapping[str, Any] | None = None,
    layer: str | None = None,
) -> None:
    """Draw one field on one layer into an empty matplotlib ``Figure`` (board mm, y up).

    Shared by the HTML report and the desktop viewer, so both show the same map.
    """
    scale, offset, unit, cmap = _SCALE.get(name, (1.0, 0.0, "", "viridis"))
    data = np.asarray(values, dtype=np.float64) * scale + offset
    ax = fig.add_subplot(111)
    x0, x1, y0, y1 = (float(v) * 1e3 for v in extent)
    finite = np.isfinite(data)
    if finite.any():
        im = ax.imshow(
            np.ma.masked_invalid(data),
            origin="lower",
            extent=(x0, x1, y0, y1),
            cmap=cmap,
            interpolation="nearest",
        )
        cb = fig.colorbar(im, ax=ax, shrink=0.85)
        cb.set_label(f"{_FIELD_LABEL.get(name, name)} [{unit}]")
        lo, hi = float(np.nanmin(data)), float(np.nanmax(data))
        title = f"{title}   min {lo:.4g}  max {hi:.4g} {unit}"
    if geometry:
        ring = np.asarray(geometry.get("outline") or [], dtype=np.float64)
        if ring.size:
            ring = np.vstack([ring, ring[:1]]) * 1e3
            ax.plot(ring[:, 0], ring[:, 1], color="0.35", lw=0.8)
        for p in geometry.get("ports", []):
            if layer is not None and p.get("layer") != layer:
                continue
            r = np.asarray(p["ring"], dtype=np.float64)
            r = np.vstack([r, r[:1]]) * 1e3
            ax.plot(r[:, 0], r[:, 1], color="white", lw=1.0, ls="--")
            cx, cy = r[:-1].mean(axis=0)
            ax.annotate(p["name"], (cx, cy), color="white", fontsize=7, ha="center", va="center")
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9, loc="left")
    fig.tight_layout()


def field_figure(
    values: Any,
    extent: Sequence[float],
    name: str,
    title: str,
    geometry: Mapping[str, Any] | None = None,
    layer: str | None = None,
    dpi: int = 100,
) -> Any:
    fig = plt.figure(figsize=(7.2, 4.6), dpi=dpi)
    draw_field(fig, values, extent, name, title, geometry, layer)
    return fig


def draw_convergence(fig: Any, hist: Mapping[str, Sequence[Any]]) -> None:
    ax = fig.add_subplot(111)
    it = list(hist.get("iteration", []))
    for key, label, color in (
        ("delta_t", "max |ΔT| [K]", "#b91c1c"),
        ("delta_v", "max |ΔV| [V]", "#0f766e"),
    ):
        pts = [
            (k, float(v))
            for k, v in zip(it, hist.get(key, []), strict=False)
            if v is not None and math.isfinite(float(v)) and float(v) > 0
        ]
        if pts:
            ax.semilogy([p[0] for p in pts], [p[1] for p in pts], "o-", color=color, label=label)
    ax.set_xlabel("pass")
    ax.grid(True, which="both", lw=0.3)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8)
    fig.tight_layout()


def convergence_figure(hist: Mapping[str, Sequence[Any]], dpi: int = 100) -> Any:
    fig = plt.figure(figsize=(6.4, 3.4), dpi=dpi)
    draw_convergence(fig, hist)
    return fig


def _findings(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for solver, sd in doc["solvers"].items():
        for v in sd.get("violations", []):
            out.append({**v, "solver": solver})
    out.sort(key=lambda v: (_SEVERITY_ORDER.get(v["severity"], 3), v["solver"]))
    return out


def _dc_source(doc: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    for name in ("coupled", "dc_ir"):
        sd = doc["solvers"].get(name)
        if sd and sd.get("ports"):
            return name, sd
    return None


def _sec_findings(doc: Mapping[str, Any]) -> str:
    items = [f for f in _findings(doc) if f["severity"] != "info"]
    if not items:
        return '<p class="empty">No violations or warnings.</p>'
    rows = [
        [
            f'<span class="tag {_e(f["severity"])}">{_e(f["severity"].upper())}</span>',
            _e(f["solver"]),
            _e(f["check"]),
            _e(f["subject"]),
            _num(f["value"]),
            _num(f["limit"]),
            _e(f["unit"]),
            _e(f["message"]),
        ]
        for f in items
    ]
    return _table(
        ["Result", "Solver", "Check", "Item", "Value", "Limit", "Unit", "Detail"], rows, {4, 5}
    )


def _sec_irdrop(doc: Mapping[str, Any]) -> str:
    src = _dc_source(doc)
    if src is None:
        return ""
    name, sd = src
    sinks = sorted(
        (p for p in sd["ports"] if p.get("kind") == "current_sink"),
        key=lambda p: -(p.get("drop_pct") or 0.0),
    )
    sources = [p for p in sd["ports"] if p.get("kind") == "voltage_source"]
    unc = doc["solvers"].get("coupled", {}).get("scalars", {}) if name == "coupled" else {}
    rows = []
    for p in sinks:
        lim = p.get("limit_pct") or 3.0
        frac = min((p.get("drop_pct") or 0.0) / lim, 1.5) if lim else 0.0
        bar = (
            f'<span class="bar{" over" if frac > 1 else ""}" '
            f'style="width:{max(frac, 0.02) * 4:.2f}rem" aria-hidden="true"></span>'
        )
        before = unc.get(f"{p['name']}.drop_pct.uncoupled")
        rows.append(
            [
                _e(p["name"]),
                _e(p["net"]),
                _num(p.get("current"), "g"),
                _num(p.get("v_nominal"), ".4g"),
                _num(p.get("v_min"), ".4f"),
                _num(p.get("drop_v"), ".2f", 1e3),
                (f"{_num(before, '.3f')} → " if before is not None else "")
                + _num(p.get("drop_pct"), ".3f"),
                f"{bar} {_num(lim, 'g')} %",
                _num(p.get("r_path"), ".3f", 1e3),
                _pass(p.get("passed")),
            ]
        )
    head = [
        "Sink",
        "Net",
        "I [A]",
        "V nom",
        "V min",
        "Drop [mV]",
        "Drop [%]" + (" (uncoupled → coupled)" if unc else ""),
        "Limit",
        "R path [mΩ]",
        "Result",
    ]
    parts = [
        f'<p class="sub">From the <code>{_e(name)}</code> solver. V min is the worst pin pair '
        "(lowest net voltage minus highest return voltage) under the sink.</p>",
        _table(head, rows, {2, 3, 4, 5, 6, 8}),
    ]
    if sources:
        parts.append(
            _table(
                ["Source", "Net", "V", "I [A]", "P [W]"],
                [
                    [
                        _e(p["name"]),
                        _e(p["net"]),
                        _num(p.get("voltage"), "g"),
                        _num(p.get("current"), ".4g"),
                        _num(p.get("power"), ".4g"),
                    ]
                    for p in sources
                ],
                {2, 3, 4},
            )
        )
    sc = sd.get("scalars", {})
    layers = doc.get("mesh", {}).get("layers", [])
    jrows = [
        [
            _e(ln),
            _num(sc.get(f"{ln}.j_max"), ".2f", 1e-6),
            _num(sc.get(f"{ln}.j_limit"), ".1f", 1e-6),
        ]
        for ln in layers
        if sc.get(f"{ln}.j_max") is not None
    ]
    if jrows:
        parts += [
            "<h3>Peak current density per layer</h3>",
            _table(["Layer", "J max [A/mm²]", "Limit [A/mm²]"], jrows, {1, 2}),
        ]
    parts.append(
        f'<p class="sub">Conduction loss {_num(sc.get("joule_power"), ".2f", 1e3)} mW.</p>'
    )
    return "".join(parts)


def _sec_vias(doc: Mapping[str, Any]) -> str:
    src = _dc_source(doc)
    if src is None or not src[1].get("vias"):
        return ""
    vias = sorted(
        src[1]["vias"],
        key=lambda v: -(v["current"] / v["limit"] if v.get("limit") else v["current"]),
    )

    def row(v: Mapping[str, Any]) -> list[str]:
        ratio = v["current"] / v["limit"] if v.get("limit") else float("nan")
        return [
            _num(v["index"], "d"),
            _e(v["net"]),
            f"{_num(v['x'], '.2f', 1e3)}, {_num(v['y'], '.2f', 1e3)}",
            _num(v["current"], ".3f"),
            _num(v.get("limit"), ".2f"),
            _num(ratio * 100, ".0f") + " %",
            _pass(v.get("passed")),
        ]

    head = ["#", "Net", "x, y [mm]", "I [A]", "IPC-2152 limit [A]", "Load", "Result"]
    top = _table(head, [row(v) for v in vias[:10]], {0, 3, 4, 5})
    rest = ""
    if len(vias) > 10:
        rest = (
            f"<details><summary>Show all {len(vias)} vias</summary>"
            + _table(head, [row(v) for v in vias], {0, 3, 4, 5})
            + "</details>"
        )
    return '<p class="sub">Highest load first (current ÷ barrel limit).</p>' + top + rest


def _sec_thermal(doc: Mapping[str, Any]) -> str:
    name = "coupled" if doc["solvers"].get("coupled", {}).get("components") else "thermal"
    sd = doc["solvers"].get(name)
    if not sd or not sd.get("components"):
        return ""
    unc = doc["solvers"]["coupled"]["scalars"] if name == "coupled" else {}
    rows = []
    for r in sorted(sd["components"], key=lambda r: r["margin"]):
        before = unc.get(f"{r['ref']}.tj.uncoupled")
        rows.append(
            [
                _e(r["ref"]),
                _num(r["power"], "g"),
                "two-resistor" if r["model"] == "two_resistor" else "board",
                (f"{_c(before)} → " if before is not None else "") + _c(r["tj_peak"]),
                _c(r["t_board"]),
                _c(r["tj_max"]),
                _num(r["margin"], ".1f"),
                _pass(r["passed"]),
            ]
        )
    head = ["Ref", "P [W]", "Model", "Tj [°C]", "Board [°C]", "Tj max [°C]", "Margin [K]", "Result"]
    sc = sd["scalars"]
    flows = {k.removeprefix("heat_out."): v for k, v in sc.items() if k.startswith("heat_out.")}
    flow_rows = [[_e(k), _num(v, ".3f")] for k, v in flows.items()]
    p_in = (sc.get("power_components") or 0.0) + (sc.get("power_joule") or 0.0)
    hist = sd.get("history") or {}
    trans = ""
    if hist.get("time"):
        trans = (
            f'<p class="sub">Transient: {len(hist["time"]) - 1} steps to '
            f"t = {_num(hist['time'][-1], 'g')} s, peak board temperature "
            f"{_c(max(hist['t_max']))} °C.</p>"
        )
    return "".join(
        [
            f'<p class="sub">From the <code>{_e(name)}</code> solver. Board T max '
            f"{_c(sc.get('t_max'))} °C; heat in {_num(p_in, '.3f')} W "
            f"(Joule {_num(sc.get('power_joule'), '.1f', 1e3)} mW).</p>",
            _table(head, rows, {1, 3, 4, 5, 6}),
            trans,
            "<h3>Where the heat goes</h3>",
            _table(["Path", "Heat [W]"], flow_rows, {1}) if flow_rows else "",
        ]
    )


def _sec_coupled(doc: Mapping[str, Any]) -> str:
    sd = doc["solvers"].get("coupled")
    if not sd or not sd.get("history"):
        return ""
    h = sd["history"]
    sc = sd["scalars"]
    rows = [
        [
            _num(k, "d"),
            _num(dt, ".3g"),
            _num(dv, ".3g", 1e3),
            _c(tm),
            _num(pj, ".2f", 1e3),
            _num(dp, ".3f"),
        ]
        for k, dt, dv, tm, pj, dp in zip(
            h["iteration"],
            h["delta_t"],
            h["delta_v"],
            h["t_max"],
            h["joule_power"],
            h["drop_pct_max"],
            strict=False,
        )
    ]
    state = "converged" if sc.get("converged") else "did not converge"
    img = _png(convergence_figure(h))
    return "".join(
        [
            f'<p class="sub">ρ(T) ⇄ Joule-heat iteration {state} after '
            f"{_num(sc.get('iterations'), '.0f')} pass(es); contraction ratio "
            f"{_num(sc.get('contraction'), '.3g')} (must stay below 1). Pass 0 is the "
            "uncoupled result.</p>",
            _table(
                ["Pass", "ΔT [K]", "ΔV [mV]", "T max [°C]", "Joule [mW]", "Worst drop [%]"],
                rows,
                {0, 1, 2, 3, 4, 5},
            ),
            f'<figure style="margin-top:1rem"><img alt="Convergence of ΔT and ΔV per pass" '
            f'src="data:image/png;base64,{img}"></figure>',
        ]
    )


def _sec_si(doc: Mapping[str, Any]) -> str:
    sd = doc["solvers"].get("si")
    if not sd or not sd.get("lines"):
        return ""
    rows = []
    for r in sd["lines"]:
        tgt = "–" if r.get("target") is None else f"{r['target']:g} ±{r['tolerance_pct']:g} %"
        rows.append(
            [
                _e(r["name"]),
                _e(r["topology"]),
                _e(r["layer"]),
                _e(r["quantity"]),
                _num(r["z_fem"], ".2f"),
                _num(r["z_formula"], ".2f") + f" <small>({_e(r['formula'])})</small>",
                _num(r["crosscheck_dev"] * 100, "+.1f") + " %",
                _num(r["eps_eff_fem"], ".3f"),
                tgt,
                "–" if r.get("target") is None else _pass(r.get("passed")),
            ]
        )
    return _table(
        ["Line", "Topology", "Layer", "Z", "FEM [Ω]", "Formula [Ω]", "Δ", "ε eff", "Target", ""],
        rows,
        {4, 5, 6, 7},
    )


def _sec_maps(doc: Mapping[str, Any], fields: Mapping[str, Mapping[str, Any]], dpi: int) -> str:
    extent = doc.get("mesh", {}).get("extent")
    if not fields or extent is None:
        return '<p class="empty">No field data in this results directory.</p>'
    geo = doc.get("geometry")
    solvers = [s for s in ("coupled", "dc_ir", "thermal") if s in fields]
    solvers += [s for s in fields if s not in solvers]
    maps: list[str] = []
    seen_fields: list[str] = []
    seen_layers: list[str] = []
    for solver in solvers:
        for key, arr in fields[solver].items():
            name, _, layer = key.partition("__")
            if name == "power_density":
                continue
            if name not in seen_fields:
                seen_fields.append(name)
            if layer not in seen_layers:
                seen_layers.append(layer)
            title = f"{solver} · {layer} · {_FIELD_LABEL.get(name, name)}"
            img = _png(field_figure(arr, extent, name, title, geo, layer, dpi))
            maps.append(
                f'<figure class="map" data-key="{_e(solver)}|{_e(name)}|{_e(layer)}">'
                f'<img alt="{_e(title)}" src="data:image/png;base64,{img}">'
                f"<figcaption>{_e(title)}</figcaption></figure>"
            )

    def sel(label: str, ident: str, opts: Sequence[str], names: Mapping[str, str]) -> str:
        o = "".join(f'<option value="{_e(v)}">{_e(names.get(v, v))}</option>' for v in opts)
        return f'<label for="{ident}">{label}<select id="{ident}">{o}</select></label>'

    picker = (
        '<div class="picker" id="mapsel">'
        + sel("Solver", "sel-solver", solvers, {})
        + sel("Field", "sel-field", seen_fields, _FIELD_LABEL)
        + sel("Layer", "sel-layer", seen_layers, {})
        + "</div>"
    )
    return (
        picker
        + "".join(maps)
        + '<p class="empty" id="nomap" hidden>No map for this combination.</p>'
    )


def _sec_notes(doc: Mapping[str, Any]) -> str:
    notes = [f for f in _findings(doc) if f["severity"] == "info"]
    if not notes:
        return ""
    items = "".join(f"<li><code>{_e(n['solver'])}</code> {_e(n['message'])}</li>" for n in notes)
    return f'<h2 id="notes">Model notes</h2><ul class="notes">{items}</ul>'


def render_report(results_dir: str | Path, title: str | None = None, dpi: int = 100) -> str:
    """HTML text of the report for ``results_dir``."""
    rd = Path(results_dir)
    doc, fields = load_results(rd)
    board = doc.get("board") or "board"
    title = title or f"pcbsim report — {board}"
    findings = _findings(doc)
    n_fail = sum(1 for f in findings if f["severity"] == "violation")
    n_warn = sum(1 for f in findings if f["severity"] == "warning")
    verdict = (
        '<span class="verdict ok">PASS</span>'
        if n_fail == 0
        else f'<span class="verdict ng">FAIL · {n_fail} violation(s)</span>'
    )
    mesh = doc.get("mesh", {})
    stats: list[tuple[str, str]] = [
        ("Solvers", ", ".join(doc["solvers"]) or "–"),
        ("Violations", str(n_fail)),
        ("Warnings", str(n_warn)),
    ]
    src = _dc_source(doc)
    if src is not None:
        drops = [p.get("drop_pct") for p in src[1]["ports"] if p.get("drop_pct") is not None]
        if drops:
            stats.append(("Worst IR drop", f"{max(drops):.2f} %"))
    th = doc["solvers"].get("coupled") or doc["solvers"].get("thermal")
    if th and th["scalars"].get("t_max") is not None:
        stats.append(("Board T max", f"{_c(th['scalars']['t_max'])} °C"))
    if mesh:
        stats.append(
            ("Mesh", f"{mesh.get('nx')} × {mesh.get('ny')} · {_num(mesh.get('dx'), '.3g', 1e3)} mm")
        )
    stat_html = "".join(f"<div><dt>{_e(a)}</dt><dd>{_e(b)}</dd></div>" for a, b in stats)

    sections: list[tuple[str, str, str]] = [
        ("findings", "Findings", _sec_findings(doc)),
        ("irdrop", "IR drop", _sec_irdrop(doc)),
        ("vias", "Via currents", _sec_vias(doc)),
        ("thermal", "Temperatures", _sec_thermal(doc)),
        ("coupled", "Electro-thermal coupling", _sec_coupled(doc)),
        ("si", "Transmission lines", _sec_si(doc)),
        ("maps", "Field maps", _sec_maps(doc, fields, dpi)),
    ]
    sections = [s for s in sections if s[2]]
    nav = "".join(f'<a href="#{i}">{_e(t)}</a>' for i, t, _ in sections)
    body = "".join(f'<h2 id="{i}">{_e(t)}</h2>{c}' for i, t, c in sections)
    meta = f"pcbsim {_e(doc.get('pcbsim_version', ''))}"
    if doc.get("source"):
        meta += f" · <code>{_e(doc['source'])}</code>"
    return "".join(
        [
            "<!doctype html><html lang=en><head><meta charset=utf-8>",
            '<meta name=viewport content="width=device-width,initial-scale=1">',
            f"<title>{_e(title)}</title><style>{_CSS}</style></head><body><main>",
            f"<h1>{_e(title)}</h1>",
            f'<p class="sub">{meta}</p>',
            verdict,
            f'<dl class="stats">{stat_html}</dl>',
            f"<nav aria-label=Sections>{nav}</nav>",
            body,
            _sec_notes(doc),
            f"</main><script>{_JS}</script></body></html>",
        ]
    )


def write_report(
    results_dir: str | Path, out: str | Path | None = None, title: str | None = None
) -> Path:
    """Write ``report.html`` (default: inside ``results_dir``) and return its path."""
    rd = Path(results_dir)
    path = Path(out) if out is not None else rd / "report.html"
    text = render_report(rd, title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


def has_violations(results_dir: str | Path) -> bool:
    doc, _ = load_results(Path(results_dir))
    return any(f["severity"] == "violation" for f in _findings(doc))
