"""Self-contained HTML report of a ``pcbsim run`` results directory (``pcbsim report``).

Input: ``results.json`` and the PNG heat maps written by
:func:`pcbsim.runner.write_results`; nothing is recomputed and no file in the
results directory is changed. Output: one HTML file with inline CSS, a few
lines of inline JS (table sorting, heat-map filter) and every image embedded
as a base64 ``data:`` URI, so it opens offline and can be mailed on its own.

Sections: summary → violations & warnings → power / IR drop → vias &
components → electro-thermal coupling → signal integrity → heat maps → notes.
The overall verdict is FAIL when any check has severity ``violation`` (the
same rule as ``pcbsim run``'s exit code 4) or ``results.json`` says
``passed: false``; warnings never turn a PASS into a FAIL.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pcbsim.post.html_kit import (
    CSS,
    SORT_JS,
    Cell,
    Col,
    badge,
    empty,
    esc,
    fmt,
    fmt_g,
    notes_list,
    number,
    table,
    text,
)
from pcbsim.post.report_sections import (
    coupled_section,
    power_section,
    si_section,
    via_component_section,
)
from pcbsim.post.results_loader import ImageAsset, LoadedResults, num

REPORT_FILE = "report.html"
SEVERITY_ORDER = ("violation", "warning", "info")
_SEV_BADGE = {"violation": ("fail", "FAIL"), "warning": ("warn", "WARN"), "info": ("info", "INFO")}
QUANTITY_LABEL = {
    "voltage": "Voltage",
    "current_density": "Current density",
    "power_density": "Power density",
    "temperature": "Temperature",
}


@dataclass(frozen=True, slots=True)
class Finding:
    solver: str
    check: str
    subject: str
    severity: str
    value: float | None
    limit: float | None
    unit: str
    message: str


@dataclass(frozen=True, slots=True)
class Verdict:
    passed: bool
    violations: int
    warnings: int
    infos: int


def findings(solvers: Mapping[str, Mapping[str, Any]]) -> list[Finding]:
    out: list[Finding] = []
    for name, entry in solvers.items():
        for v in entry.get("violations") or []:
            if not isinstance(v, dict):
                continue
            sev = str(v.get("severity") or "violation")
            out.append(
                Finding(
                    solver=str(name),
                    check=str(v.get("check") or ""),
                    subject=str(v.get("subject") or ""),
                    severity=sev if sev in SEVERITY_ORDER else "violation",
                    value=num(v.get("value")),
                    limit=num(v.get("limit")),
                    unit=str(v.get("unit") or ""),
                    message=str(v.get("message") or ""),
                )
            )
    return out


def verdict(res: LoadedResults) -> Verdict:
    items = findings(res.solvers)
    n = {s: sum(1 for f in items if f.severity == s) for s in SEVERITY_ORDER}
    passed = n["violation"] == 0 and res.doc.get("passed") is not False
    return Verdict(passed, n["violation"], n["warning"], n["info"])


# --------------------------------------------------------------------------- sections


def _summary(res: LoadedResults, v: Verdict) -> str:
    d = res.doc
    mesh = d.get("mesh") or {}
    nx, ny = num(mesh.get("nx")), num(mesh.get("ny"))
    dx, dy = num(mesh.get("dx")), num(mesh.get("dy"))
    layers = [str(x) for x in mesh.get("layers") or []]
    if nx is not None and ny is not None:
        per_layer = int(nx) * int(ny)
        cells = f"{int(nx)} × {int(ny)} = {per_layer:,} per layer"
        if layers:
            cells += f" ({per_layer * len(layers):,} total, {len(layers)} layers)"
    else:
        cells = "–"
    cell_size = f"{fmt(dx, 3, 1e3)} × {fmt(dy, 3, 1e3)} mm" if dx is not None else "–"
    source = d.get("source")
    stats = [
        ("Board", esc(d.get("board") or "–")),
        ("Config", f"<code>{esc(source)}</code>" if source else "– (not recorded)"),
        ("Mesh cell", esc(cell_size)),
        ("Mesh cells", esc(cells)),
        ("Layers", esc(", ".join(layers) or "–")),
        ("Solvers run", esc(", ".join(res.solvers) or "none")),
        ("Violations", str(v.violations)),
        ("Warnings", str(v.warnings)),
        ("pcbsim", esc(d.get("pcbsim_version"))),
    ]
    head = (
        '<p class="verdict pass">PASS — no design violations</p>'
        if v.passed
        else f'<p class="verdict fail">FAIL — {v.violations} violation(s)</p>'
    )
    if v.passed and v.warnings:
        head += (
            f'<p class="note">{v.warnings} warning(s) to review; they do not fail the design.</p>'
        )
    if not v.passed and v.violations == 0:
        head += '<p class="note">results.json is marked as not passed.</p>'
    dl = "".join(f"<div><dt>{esc(a)}</dt><dd>{b}</dd></div>" for a, b in stats)
    return head + f'<dl class="stats">{dl}</dl>'


def _finding_table(items: Sequence[Finding]) -> str:
    cols = [
        Col("Severity"),
        Col("Solver"),
        Col("Check"),
        Col("Target"),
        Col("Value", True),
        Col("Limit", True),
        Col("Unit"),
        Col("Message"),
    ]
    rows = []
    for f in items:
        kind, label = _SEV_BADGE[f.severity]
        rows.append(
            [
                Cell(badge(kind, label), f.severity),
                text(f.solver),
                text(f.check),
                text(f.subject),
                number(f.value, fmt_g(f.value)),
                number(f.limit, fmt_g(f.limit)),
                text(f.unit),
                Cell(esc(f.message) or "–", f.message, "msg"),
            ]
        )
    return table(cols, rows)


def _findings_section(solvers: Mapping[str, Mapping[str, Any]]) -> str:
    items = findings(solvers)
    fails = [f for f in items if f.severity == "violation"]
    warns = [f for f in items if f.severity == "warning"]
    parts = ["<h3>Violations (fail the design)</h3>"]
    parts.append(_finding_table(fails) if fails else empty("None — every limit check passed."))
    parts.append("<h3>Warnings (review; do not fail the design)</h3>")
    parts.append(_finding_table(warns) if warns else empty("None."))
    if any(f.solver == "coupled" for f in items) and any(f.solver != "coupled" for f in items):
        parts.append(
            '<p class="note">coupled re-evaluates the dc_ir and thermal checks at the '
            "electro-thermal fixed point, so the same target can appear once per solver.</p>"
        )
    return "".join(parts)


def _figure(img: ImageAsset, alt: str, caption: str) -> str:
    return (
        f'<figure data-q="{esc(img.quantity)}" data-l="{esc(img.layer)}">'
        f'<img src="{img.data_uri}" alt="{esc(alt)}" loading="lazy">'
        f"<figcaption>{esc(caption)} · <code>{esc(img.file_name)}</code></figcaption></figure>"
    )


def _select(ident: str, label: str, values: Sequence[tuple[str, str]]) -> str:
    opts = "".join(f'<option value="{esc(v)}">{esc(t)}</option>' for v, t in values)
    return (
        f'<label>{esc(label)} <select id="{ident}"><option value="">all</option>{opts}'
        "</select></label>"
    )


def _heatmap_section(images: Sequence[ImageAsset], layers: Sequence[str]) -> str:
    fields = [i for i in images if i.kind == "field"]
    other = [i for i in images if i.kind == "other"]
    if not fields and not other:
        return empty(
            "No heat-map PNGs in the results directory (the run may have used --no-plots)."
        )
    parts: list[str] = []
    if fields:
        qs = list(dict.fromkeys(i.quantity for i in fields))
        ls = [x for x in layers if any(i.layer == x for i in fields)]
        ls += [x for x in dict.fromkeys(i.layer for i in fields) if x not in ls]
        parts.append(
            '<div class="filters">'
            + _select("fq", "Quantity", [(q, QUANTITY_LABEL.get(q, q)) for q in qs])
            + _select("fl", "Layer", [(x, x) for x in ls])
            + "</div>"
        )
        order = {x: k for k, x in enumerate(ls)}
        for solver in dict.fromkeys(i.solver for i in fields):
            for q in qs:
                group = sorted(
                    (i for i in fields if i.solver == solver and i.quantity == q),
                    key=lambda i: order.get(i.layer, len(order)),
                )
                if not group:
                    continue
                title = f"{solver} · {QUANTITY_LABEL.get(q, q)}"
                parts.append(f"<h3>{esc(title)}</h3><div class=figs>")
                parts += [
                    _figure(i, f"{title} heat map, layer {i.layer}", f"Layer {i.layer}")
                    for i in group
                ]
                parts.append("</div>")
    if other:
        parts.append("<h3>Other figures</h3><div class=figs>")
        parts += [_figure(i, i.file_name, "Figure") for i in other]
        parts.append("</div>")
    return "".join(parts)


def _scalars_appendix(solvers: Mapping[str, Mapping[str, Any]]) -> str:
    parts = []
    for name, entry in solvers.items():
        sc = entry.get("scalars") or {}
        if not isinstance(sc, dict) or not sc:
            continue
        rows = [[text(k), number(num(v), fmt_g(num(v), 6))] for k, v in sc.items()]
        parts.append(
            f"<details><summary>{esc(name)}: {len(rows)} scalars (SI units)</summary>"
            + table([Col("Key"), Col("Value", True)], rows)
            + "</details>"
        )
    return "".join(parts)


# --------------------------------------------------------------------------- assembly

_SECTIONS = (
    ("summary", "Summary"),
    ("findings", "Violations & warnings"),
    ("power", "Power / IR drop"),
    ("vias", "Vias & components"),
    ("coupled", "Electro-thermal coupling"),
    ("si", "Signal integrity"),
    ("maps", "Heat maps"),
    ("notes", "Notes & data"),
)


def render_report(res: LoadedResults) -> str:
    """The whole report as one HTML string."""
    solvers = res.solvers
    v = verdict(res)
    mesh = res.doc.get("mesh") or {}
    layers = [str(x) for x in mesh.get("layers") or []]
    conv = [i for i in res.images if i.kind == "convergence" and i.solver == "coupled"]
    conv_html = (
        "<div class=figs>"
        + _figure(conv[0], "Convergence plot written by pcbsim run", "Plot from pcbsim run")
        + "</div>"
        if conv
        else ""
    )
    infos = [
        f"[{f.solver}] {f.message or f.check}" for f in findings(solvers) if f.severity == "info"
    ]
    body = {
        "summary": _summary(res, v),
        "findings": _findings_section(solvers),
        "power": power_section(solvers, layers),
        "vias": via_component_section(solvers, layers),
        "coupled": coupled_section(solvers, conv_html),
        "si": si_section(solvers),
        "maps": _heatmap_section(res.images, layers),
        "notes": notes_list(infos + list(res.notes))
        + _scalars_appendix(solvers)
        + f'<p class="note">Results directory: <code>{esc(res.directory)}</code></p>',
    }
    title = f"pcbsim report — {res.doc.get('board') or 'board'}"
    toc = "".join(f'<a href="#{k}">{esc(t)}</a>' for k, t in _SECTIONS)
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width,initial-scale=1">',
        f"<title>{esc(title)}</title><style>{CSS}</style></head><body><main>",
        f"<h1>{esc(title)}</h1>",
        '<p class="sub">Generated by <code>pcbsim report</code> from the stored results '
        "(no re-simulation). Units as labelled; temperatures in °C.</p>",
        f'<nav class="toc" aria-label="Sections">{toc}</nav>',
    ]
    for key, heading in _SECTIONS:
        parts.append(f'<section id="{key}"><h2>{esc(heading)}</h2>{body[key]}</section>')
    parts.append(f"</main><script>{SORT_JS}</script></body></html>")
    return "".join(parts)


def default_report_path(results_dir: Path) -> Path:
    return results_dir / REPORT_FILE


def write_report(res: LoadedResults, out: Path) -> Path:
    """Write the report; the parent directory is created if needed."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(res), "utf-8")
    return out
