"""Match report: self-contained HTML (inline CSS + overlay SVG) and JSON.

The overlay draws, in board coordinates (y up, mm):

* ECAD outline + cutouts (solid) and the registered drawing outline (dashed),
* drill holes (circles) and registered drawing holes (crosses),
* component bodies, heat sinks, keepouts, chassis contacts,
* NG locations as red rings, numbered to match the NG table.
"""

from __future__ import annotations

import html
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from pcbsim.registration.checks import CheckItem, Status
from pcbsim.registration.pipeline import MatchResult, board_bbox, write_match

_CSS = """
:root{--fg:#18181b;--muted:#52525b;--faint:#a1a1aa;--line:rgba(0,0,0,.08);--well:#fafafa;
--accent:#0f766e;--ng:#b91c1c;--warn:#b45309;--ok:#15803d}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--fg);
background:#fff}
main{max-width:72rem;margin:0 auto;padding:2rem 1.25rem 4rem}
h1{font-size:1.75rem;font-weight:600;letter-spacing:-.01em;margin:0 0 .25rem}
h2{font-size:1.125rem;font-weight:600;margin:2.5rem 0 .75rem}
p.sub{color:var(--muted);margin:0 0 1.5rem;max-width:70ch}
.verdict{display:inline-flex;gap:.5rem;align-items:center;font-weight:600;padding:.25rem .625rem;
border-radius:6px;font-size:.875rem}
.verdict.ok{background:#f0fdf4;color:var(--ok)}.verdict.ng{background:#fef2f2;color:var(--ng)}
.stats{display:flex;flex-wrap:wrap;gap:0;border-block:1px solid var(--line);margin:1.5rem 0}
.stats div{padding:.875rem 1.5rem .875rem 0;margin-right:1.5rem;border-right:1px solid var(--line)}
.stats div:last-child{border-right:0}
.stats dt{font-size:.8125rem;color:var(--muted)}.stats dd{margin:0;font-size:1.25rem;
font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.875rem}
th{text-align:left;font-weight:500;color:var(--muted);white-space:nowrap;
padding:.5rem .75rem .5rem 0;border-bottom:1px solid var(--line)}
td{padding:.5rem .75rem .5rem 0;border-bottom:1px solid var(--line);vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{font-size:.75rem;font-weight:600;letter-spacing:.02em}
.tag.NG{color:var(--ng)}.tag.WARN{color:var(--warn)}.tag.OK{color:var(--ok)}
figure{margin:0;background:var(--well);border-radius:8px;padding:1rem}
figure svg{width:100%;height:auto;max-height:70vh;display:block}
figcaption{font-size:.8125rem;color:var(--muted);margin-top:.5rem}
.legend{display:flex;flex-wrap:wrap;gap:1rem;font-size:.8125rem;color:var(--muted);margin-top:.5rem}
.legend span::before{content:"";display:inline-block;width:.875rem;height:.125rem;
margin-right:.375rem;vertical-align:middle;background:currentColor}
ul.notes{padding-left:1.25rem;color:var(--muted);font-size:.875rem;max-width:80ch}
code{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
details summary{cursor:pointer;color:var(--accent);font-size:.875rem}
@media (min-width:640px){body{font-size:15px}}
"""


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "–"
    if unit == "deg":
        return f"{v:.2f}°"
    if unit == "mm":
        return f"{v:.3f}"
    return f"{v:.4g}"


def _rings(geom: BaseGeometry) -> list[list[tuple[float, float]]]:
    out: list[list[tuple[float, float]]] = []
    polys: list[Polygon] = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    elif isinstance(geom, LineString):
        return [[(float(x), float(y)) for x, y in geom.coords]]
    for p in polys:
        out.append([(float(x), float(y)) for x, y in p.exterior.coords])
        out += [[(float(x), float(y)) for x, y in r.coords] for r in p.interiors]
    return out


class _Svg:
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = bbox
        pad = 0.06 * max(x1 - x0, y1 - y0, 1e-3)
        self.x0, self.y0, self.x1, self.y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        self.k = 1000.0  # m → mm (SVG user units)
        self.parts: list[str] = []
        self.sw = max(self.x1 - self.x0, self.y1 - self.y0) * self.k / 400.0

    def pt(self, x: float, y: float) -> str:
        return f"{(x - self.x0) * self.k:.4f},{(self.y1 - y) * self.k:.4f}"

    def path(self, geom: BaseGeometry, cls: str) -> None:
        d = " ".join(
            "M" + " L".join(self.pt(x, y) for x, y in ring) + (" Z" if ring[0] == ring[-1] else "")
            for ring in _rings(geom)
            if ring
        )
        if d:
            self.parts.append(f'<path class="{cls}" d="{d}"/>')

    def circle(self, x: float, y: float, r: float, cls: str, title: str = "") -> None:
        cx, cy = self.pt(x, y).split(",")
        t = f"<title>{html.escape(title)}</title>" if title else ""
        self.parts.append(
            f'<circle class="{cls}" cx="{cx}" cy="{cy}" r="{r * self.k:.4f}">{t}</circle>'
        )

    def cross(self, x: float, y: float, r: float, cls: str) -> None:
        a, b = self.pt(x - r, y - r), self.pt(x + r, y + r)
        c, d = self.pt(x - r, y + r), self.pt(x + r, y - r)
        self.parts.append(f'<path class="{cls}" d="M{a} L{b} M{c} L{d}"/>')

    def label(self, x: float, y: float, text: str, cls: str) -> None:
        px, py = self.pt(x, y).split(",")
        self.parts.append(f'<text class="{cls}" x="{px}" y="{py}">{html.escape(text)}</text>')

    def render(self) -> str:
        w = (self.x1 - self.x0) * self.k
        h = (self.y1 - self.y0) * self.k
        sw = self.sw
        style = (
            f".eo{{fill:#fff;stroke:#18181b;stroke-width:{sw:.4f};fill-rule:evenodd}}"
            f".mo{{fill:none;stroke:#0f766e;stroke-width:{sw:.4f};stroke-dasharray:{4 * sw:.4f}}}"
            f".eh{{fill:none;stroke:#52525b;stroke-width:{sw:.4f}}}"
            f".mh{{fill:none;stroke:#0f766e;stroke-width:{1.2 * sw:.4f}}}"
            f".comp_3d{{fill:rgba(15,118,110,.08);stroke:#0f766e;stroke-width:{0.6 * sw:.4f}}}"
            f".heatsink{{fill:rgba(180,83,9,.10);stroke:#b45309;stroke-width:{0.6 * sw:.4f}}}"
            f".keepout{{fill:rgba(82,82,91,.06);stroke:#71717a;stroke-width:{0.6 * sw:.4f};"
            f"stroke-dasharray:{2 * sw:.4f}}}"
            f".chassis{{fill:rgba(37,99,235,.10);stroke:#2563eb;stroke-width:{0.6 * sw:.4f}}}"
            f".case{{fill:none;stroke:#a1a1aa;stroke-width:{0.4 * sw:.4f}}}"
            f".ng{{fill:none;stroke:#b91c1c;stroke-width:{1.5 * sw:.4f}}}"
            f".ngt{{fill:#b91c1c;font:600 {9 * sw:.3f}px system-ui,sans-serif}}"
            f".cref{{fill:#52525b;font:{7 * sw:.3f}px system-ui,sans-serif}}"
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.3f} {h:.3f}" '
            f'role="img" aria-label="ECAD/MCAD overlay"><style>{style}</style>'
            + "".join(self.parts)
            + "</svg>"
        )


def overlay_svg(m: MatchResult, ng: list[CheckItem]) -> str:
    b = board_bbox(m)
    svg = _Svg(b.bounds)
    if m.ecad.outline is not None:
        svg.path(m.ecad.outline, "eo")
    for body in sorted(m.bodies, key=lambda x: ["keepout", "case", "chassis"].count(x.role) * -1):
        svg.path(body.geometry, body.role)
    for h in m.ecad.holes:
        svg.circle(h.x, h.y, h.diameter / 2, "eh", f"drill ⌀{h.diameter * 1e3:.3f} mm")
    if m.mech_outline is not None:
        svg.path(m.mech_outline, "mo")
    for f in m.mech_holes:
        svg.circle(f.x, f.y, f.diameter / 2, "mh")
        svg.cross(f.x, f.y, f.diameter / 4, "mh")
    for c in m.ecad.components:
        svg.label(c.x, c.y, c.ref, "cref")
    r_ng = 0.025 * max(b.bounds[2] - b.bounds[0], b.bounds[3] - b.bounds[1])
    for k, item in enumerate(ng, 1):
        if item.location is None:
            continue
        x, y = item.location
        svg.circle(x, y, r_ng, "ng", f"{k}. {item.subject}")
        svg.label(x + r_ng, y + r_ng, str(k), "ngt")
    return svg.render()


def _table(items: list[CheckItem], numbered: bool = False) -> str:
    rows = []
    for k, i in enumerate(items, 1):
        rows.append(
            "<tr>"
            + (f'<td class="n">{k}</td>' if numbered else "")
            + f'<td><span class="tag {i.status.value}">{i.status.value}</span></td>'
            f"<td>{html.escape(i.category)}</td><td>{html.escape(i.subject)}</td>"
            f'<td class="n">{_fmt(i.value, i.unit)}</td><td class="n">{_fmt(i.limit, i.unit)}</td>'
            f"<td>{html.escape(i.unit)}</td><td>{html.escape(i.message)}</td></tr>"
        )
    head = (
        "<tr>"
        + ("<th>#</th>" if numbered else "")
        + "<th>Result</th><th>Check</th><th>Item</th><th>Value</th><th>Limit</th>"
        "<th>Unit</th><th>Detail</th></tr>"
    )
    body = "".join(rows)
    return f'<div class="wrap"><table><thead>{head}</thead><tbody>{body}</tbody></table></div>'


def render_html(m: MatchResult, title: str = "ECAD–MCAD match report") -> str:
    r = m.registration
    t = r.transform
    ng = m.report.ng()
    warn = [i for i in m.report.items if i.status is Status.WARN]
    verdict = (
        '<span class="verdict ok">PASS</span>'
        if m.ok
        else f'<span class="verdict ng">NG · {len(ng)} item(s)</span>'
    )
    stats = [
        ("Rotation", f"{t.angle_deg:.4f}°"),
        ("Translation", f"{t.tx * 1e3:.3f}, {t.ty * 1e3:.3f} mm"),
        ("Mirror", "yes (bottom view)" if t.mirror else "no"),
        ("Scale", f"{t.scale:.6g}"),
        ("Feature RMS", f"{r.rms * 1e3:.4f} mm"),
        ("Matched", f"{len(r.matches)} / {r.n_src}"),
    ]
    if r.outline_rms is not None:
        stats.append(("Outline RMS", f"{r.outline_rms * 1e3:.4f} mm"))
    stat_html = "".join(f"<div><dt>{a}</dt><dd>{html.escape(b)}</dd></div>" for a, b in stats)
    bcs = "".join(
        f"<tr><td>{html.escape(b.name)}</td><td>{b.kind}</td>"
        f"<td>{html.escape(b.component or b.side)}</td><td>{html.escape(b.note)}</td></tr>"
        for b in m.boundaries
    )
    notes = r.warnings + m.notes + m.ecad.warnings + m.mech.warnings
    inputs = "".join(
        f"<li><code>{html.escape(k)}</code>: {html.escape(str(v))}</li>"
        for k, v in m.inputs.items()
        if v
    )
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width,initial-scale=1">',
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main>",
        f"<h1>{html.escape(title)}</h1>",
        '<p class="sub">Electrical geometry from Gerber/Excellon; mechanical geometry from the '
        "drawing, mapped into board coordinates (mm, y up, Gerber origin).</p>",
        verdict,
        f'<dl class="stats">{stat_html}</dl>',
        "<h2>Overlay</h2><figure>",
        overlay_svg(m, ng),
        '<div class="legend"><span style="color:#18181b">Gerber outline / drills</span>'
        '<span style="color:#0f766e">Drawing (registered)</span>'
        '<span style="color:#b45309">Heat sink</span><span style="color:#2563eb">Chassis</span>'
        '<span style="color:#b91c1c">NG location</span></div>',
        "<figcaption>Numbers on red rings refer to the NG table.</figcaption></figure>",
    ]
    if ng:
        parts += ["<h2>NG items</h2>", _table(ng, numbered=True)]
    if warn:
        parts += ["<h2>Warnings</h2>", _table(warn)]
    if bcs:
        parts += [
            "<h2>Derived thermal boundaries</h2>",
            '<div class="wrap"><table><thead><tr><th>Name</th><th>Kind</th><th>Target</th>'
            f"<th>Model</th></tr></thead><tbody>{bcs}</tbody></table></div>",
        ]
    parts += [
        f"<h2>All checks</h2><details><summary>Show {len(m.report.items)} checks</summary>",
        _table(m.report.items),
        "</details>",
    ]
    if notes:
        parts += ["<h2>Notes</h2><ul class=notes>"]
        parts += [f"<li>{html.escape(n)}</li>" for n in notes]
        parts += ["</ul>"]
    if inputs:
        parts += ["<h2>Inputs</h2><ul class=notes>", inputs, "</ul>"]
    parts.append("</main></body></html>")
    return "".join(parts)


def write_report(m: MatchResult, html_path: Path, json_path: Path | None = None) -> list[Path]:
    """Write ``out.html`` and ``out.json`` (or ``json_path``)."""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(m), "utf-8")
    jp = json_path or html_path.with_suffix(".json")
    write_match(m, jp)
    return [html_path, jp]
