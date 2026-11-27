"""Small HTML building blocks shared by the results report.

Same house style as :mod:`pcbsim.registration.report`: one inline stylesheet,
no external fonts, scripts or images. Every piece of text that comes from a
file (names, messages, paths) goes through :func:`esc`; numbers are formatted
here so ``None`` (JSON ``null`` = non-finite or missing) always shows as "–".
Tables can be sorted by clicking a header (a few lines of inline JS); they
remain plain, readable tables without JavaScript.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass

DASH = "–"

CSS = """
:root{--fg:#18181b;--muted:#52525b;--line:rgba(0,0,0,.12);--well:#f4f4f5;
--accent:#0f766e;--fail:#b91c1c;--fail-bg:#fef2f2;--warn:#92400e;--warn-bg:#fffbeb;
--ok:#166534;--ok-bg:#f0fdf4;--info:#1e40af;--info-bg:#eff6ff}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--fg);
background:#fff}
main{max-width:76rem;margin:0 auto;padding:1.5rem 1rem 4rem}
h1{font-size:1.6rem;font-weight:650;letter-spacing:-.01em;margin:0 0 .25rem;overflow-wrap:anywhere}
h2{font-size:1.2rem;font-weight:650;margin:2.75rem 0 .75rem;padding-top:.5rem;
border-top:1px solid var(--line)}
h3{font-size:1rem;font-weight:600;margin:1.75rem 0 .5rem}
p{max-width:75ch}p.sub,p.note{color:var(--muted)}p.note{font-size:.875rem}
nav.toc{font-size:.875rem;margin:1rem 0}nav.toc a{color:var(--accent);margin-right:1rem;
white-space:nowrap}
.verdict{display:inline-block;font-weight:700;padding:.3rem .75rem;border-radius:6px;
font-size:1rem;margin:.5rem 0}
.verdict.pass{background:var(--ok-bg);color:var(--ok);border:1px solid var(--ok)}
.verdict.fail{background:var(--fail-bg);color:var(--fail);border:1px solid var(--fail)}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(11rem,1fr));gap:.75rem 1.5rem;
border-block:1px solid var(--line);margin:1rem 0;padding:.875rem 0}
.stats dt{font-size:.8125rem;color:var(--muted)}
.stats dd{margin:0;font-size:1.05rem;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:.875rem}
caption{text-align:left;color:var(--muted);font-size:.8125rem;padding-bottom:.25rem}
th{text-align:left;font-weight:600;color:var(--muted);white-space:nowrap;
padding:.45rem .75rem .45rem 0;border-bottom:2px solid var(--line)}
th.n{text-align:right}
th[data-sort]{cursor:pointer}th[data-sort]:hover{color:var(--fg)}
th[aria-sort=ascending]::after{content:" ▲"}th[aria-sort=descending]::after{content:" ▼"}
td{padding:.45rem .75rem .45rem 0;border-bottom:1px solid var(--line);vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.msg{min-width:16rem}
.badge{display:inline-block;font-size:.75rem;font-weight:700;letter-spacing:.03em;
padding:.05rem .45rem;border-radius:4px;border:1px solid currentColor;white-space:nowrap}
.badge.pass{color:var(--ok);background:var(--ok-bg)}
.badge.fail{color:var(--fail);background:var(--fail-bg)}
.badge.warn{color:var(--warn);background:var(--warn-bg)}
.badge.info{color:var(--info);background:var(--info-bg)}
.badge.na{color:var(--muted);background:var(--well)}
.empty{color:var(--muted);font-style:italic}
.figs{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,22rem),1fr));gap:1rem}
figure{margin:0;background:var(--well);border-radius:8px;padding:.75rem}
figure img{width:100%;height:auto;display:block;background:#fff}
figcaption{font-size:.8125rem;color:var(--muted);margin-top:.4rem;overflow-wrap:anywhere}
.filters{display:flex;flex-wrap:wrap;gap:1rem;margin:.5rem 0 1rem;font-size:.875rem}
.filters select{font:inherit;padding:.2rem .4rem}
ul.notes{padding-left:1.25rem;color:var(--muted);font-size:.875rem;max-width:90ch}
code{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
details summary{cursor:pointer;color:var(--accent);font-size:.875rem;margin:.5rem 0}
svg.chart{width:100%;max-width:40rem;height:auto;display:block;background:var(--well);
border-radius:8px}
@media print{nav.toc,.filters{display:none}h2{break-before:auto}}
"""

SORT_JS = """
document.querySelectorAll('table.sortable').forEach(function(t){
 t.querySelectorAll('th[data-sort]').forEach(function(th,i){
  th.tabIndex=0;
  function go(){var b=t.tBodies[0],r=Array.from(b.rows),n=th.dataset.sort==='n',
   d=th.getAttribute('aria-sort')==='ascending'?-1:1;
   t.querySelectorAll('th').forEach(function(h){h.removeAttribute('aria-sort')});
   th.setAttribute('aria-sort',d>0?'ascending':'descending');
   r.sort(function(x,y){var a=x.cells[i].dataset.v,c=y.cells[i].dataset.v;
    if(n){a=a===''?NaN:+a;c=c===''?NaN:+c;if(isNaN(a))return 1;if(isNaN(c))return -1;
     return d*(a-c)}return d*String(a).localeCompare(String(c))});
   r.forEach(function(x){b.appendChild(x)})}
  th.addEventListener('click',go);
  th.addEventListener('keydown',function(e){
   if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}});
 })});
var fq=document.getElementById('fq'),fl=document.getElementById('fl');
function ff(){document.querySelectorAll('figure[data-q]').forEach(function(f){
 var ok=(!fq||fq.value===''||f.dataset.q===fq.value)&&(!fl||fl.value===''||f.dataset.l===fl.value);
 f.hidden=!ok})}
if(fq)fq.addEventListener('change',ff);if(fl)fl.addEventListener('change',ff);
"""


def esc(value: object) -> str:
    """HTML-escape any value (quotes included, safe in attributes)."""
    return html.escape(str(value), quote=True)


def fmt(value: float | None, nd: int = 3, scale: float = 1.0, offset: float = 0.0) -> str:
    """Fixed-point number; ``None`` → "–"."""
    if value is None:
        return DASH
    return f"{value * scale + offset:.{nd}f}"


def fmt_g(value: float | None, sig: int = 4) -> str:
    """Significant-digit number; ``None`` → "–"."""
    if value is None:
        return DASH
    return f"{value:.{sig}g}"


def badge(kind: str, text: str | None = None) -> str:
    """``kind`` ∈ pass, fail, warn, info, na."""
    label = text if text is not None else {"pass": "PASS", "fail": "FAIL"}.get(kind, kind.upper())
    return f'<span class="badge {esc(kind)}">{esc(label)}</span>'


def pass_badge(passed: object) -> str:
    if passed is True:
        return badge("pass")
    if passed is False:
        return badge("fail")
    return badge("na", "n/a")


@dataclass(frozen=True, slots=True)
class Col:
    """A table column. ``numeric`` right-aligns and sorts numerically."""

    title: str
    numeric: bool = False


@dataclass(frozen=True, slots=True)
class Cell:
    """A cell: ``html`` is already-escaped markup, ``sort`` the sort key (raw value)."""

    html: str
    sort: str = ""
    cls: str = ""


def text(value: object) -> Cell:
    s = "" if value is None else str(value)
    return Cell(esc(s) if s else DASH, s)


def number(value: float | None, shown: str) -> Cell:
    return Cell(esc(shown), "" if value is None else repr(value), "n")


def table(
    cols: Sequence[Col], rows: Sequence[Sequence[Cell]], caption: str = "", sortable: bool = True
) -> str:
    head = "".join(
        f'<th scope="col"{" class=n" if c.numeric else ""}'
        + (f' data-sort="{"n" if c.numeric else "s"}"' if sortable else "")
        + f">{esc(c.title)}</th>"
        for c in cols
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td{f" class={x.cls}" if x.cls else ""} data-v="{esc(x.sort)}">{x.html}</td>'
            for x in r
        )
        + "</tr>"
        for r in rows
    )
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    cls = ' class="sortable"' if sortable else ""
    return (
        f'<div class="wrap"><table{cls}>{cap}<thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def empty(message: str) -> str:
    return f'<p class="empty">{esc(message)}</p>'


def notes_list(items: Sequence[str]) -> str:
    if not items:
        return ""
    return '<ul class="notes">' + "".join(f"<li>{esc(n)}</li>" for n in items) + "</ul>"
