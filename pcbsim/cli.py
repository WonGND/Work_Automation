"""Command-line interface.

    pcbsim check  config.yaml           validate a config (or a bare .kicad_pcb) and print a summary
    pcbsim run    config.yaml           run the configured solvers, write results/
    pcbsim report results/              self-contained HTML report (results/report.html)
    pcbsim match  --gerber dir/ --drill x.drl --mech mech.dwg --map layers.yaml --report out.html
                                        ECAD–MCAD registration + checks (+ match.json)
    pcbsim solvers                      list registered solver plugins

The ``check`` output mirrors the pre-simulation validation step of common PDN
tools: stack-up table, per-net source/sink table, heat sources, then a
pass/fail list of model checks. ``run`` prints a per-sink IR-drop table (the
text form of a power tree), per-layer peak current density and the violation
list. Exit codes: 0 ok, 1 invalid input, 2 usage error, 3 not implemented yet,
4 design violations found (``match``: NG items), 5 simulation refused because the
linked ECAD–MCAD match is NG (override with ``run --force``).
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from pcbsim import __version__
from pcbsim.errors import PcbsimError
from pcbsim.io import LoadedConfig, load_config
from pcbsim.model import Board, PortKind
from pcbsim.runner import run_analysis, violation_counts, write_results
from pcbsim.solvers import ResultSet, available_solvers
from pcbsim.solvers.base import Severity
from pcbsim.solvers.dc_ir import summarize_ports
from pcbsim.units import MM, from_si, kelvin_to_celsius

MM2 = MM * MM

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_VIOLATIONS = 4
EXIT_MECH_NG = 5


def _table(
    rows: Sequence[Sequence[str]], header: Sequence[str], right: set[int] | None = None
) -> str:
    right = right or set()
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]

    def fmt(r: Sequence[str]) -> str:
        cells = [
            str(c).rjust(widths[i]) if i in right else str(c).ljust(widths[i])
            for i, c in enumerate(r)
        ]
        return "  " + "  ".join(cells).rstrip()

    rule = "  " + "  ".join("-" * w for w in widths)
    return "\n".join([fmt(header), rule, *(fmt(r) for r in rows)])


def _mm(x: float | None, nd: int = 3) -> str:
    if x is None:
        return "-"
    return f"{from_si(x, 'mm', 'length'):.{nd}f}"


def _um(x: float) -> str:
    return f"{from_si(x, 'um', 'length'):.1f}"


def summarize(cfg: LoadedConfig) -> str:
    b: Board = cfg.board
    out: list[str] = []
    xmin, ymin, xmax, ymax = b.outline.bbox()
    n_cu = len(b.stackup.conductor_layers())
    out.append(f"Board  {b.name}")
    out.append(
        f"  outline {_mm(xmax - xmin, 2)} × {_mm(ymax - ymin, 2)} mm   "
        f"{n_cu} copper layers   thickness {_mm(b.stackup.total_thickness)} mm"
    )
    if cfg.source is not None:
        out.append(f"  source  {cfg.source}")
    if cfg.kicad is not None:
        kc = cfg.kicad.counts
        out.append(
            f"  KiCad   {cfg.kicad.path.name}: {kc.get('tracks', 0)} tracks, "
            f"{kc.get('vias', 0)} vias (+{kc.get('plated_holes', 0)} plated holes), "
            f"{kc.get('pads', 0)} pads, {kc.get('zones', 0)} zones, "
            f"{kc.get('footprints', 0)} footprints"
        )

    out.append("\nStack-up (top → bottom)")
    rows = []
    for layer in b.stackup.layers:
        m = cfg.materials[layer.material]
        if layer.is_conductor:
            prop = f"Rs {1.0 / (m.conductivity() * layer.thickness) * 1e3:.3f} mΩ/□"
        else:
            prop = f"εr {m.eps_r:g}" if m.eps_r is not None else ""
        rows.append(
            [
                layer.name,
                layer.kind.value,
                layer.role.value if layer.is_conductor else "",
                _um(layer.thickness),
                layer.material,
                prop,
            ]
        )
    out.append(_table(rows, ["layer", "kind", "role", "t [µm]", "material", "property"], {3}))

    out.append("\nNets")
    rows = []
    for n in b.nets:
        n_shapes = sum(1 for s in b.shapes if s.net == n.name)
        n_vias = sum(1 for v in b.vias if v.net == n.name)
        src = [p for p in b.ports if p.net == n.name and p.kind is PortKind.VOLTAGE_SOURCE]
        snk = [p for p in b.ports if p.net == n.name and p.kind is PortKind.CURRENT_SINK]
        v = f"{n.nominal_voltage:g}" if n.nominal_voltage is not None else "-"
        i_load = sum(p.value for p in snk)
        rows.append(
            [
                n.name,
                n.kind.value,
                v,
                str(n_shapes),
                str(n_vias),
                str(len(src)),
                str(len(snk)),
                f"{i_load:g}" if snk else "-",
            ]
        )
    out.append(
        _table(
            rows,
            ["net", "kind", "V", "shapes", "vias", "sources", "sinks", "I_load [A]"],
            {2, 3, 4, 5, 6, 7},
        )
    )

    if b.ports:
        out.append("\nDC sources / sinks")
        rows = []
        for p in b.ports:
            val = f"{p.value:g} V" if p.kind is PortKind.VOLTAGE_SOURCE else f"{p.value:g} A"
            rows.append([p.name, p.kind.value, p.net, p.layer, val, p.reference_net or "-"])
        out.append(_table(rows, ["port", "type", "net", "layer", "magnitude", "reference"], {4}))

    if b.components:
        out.append("\nHeat sources")
        rows = []
        tj_def = b.criteria.tj_max_default
        for c in b.components:
            rows.append(
                [
                    c.ref,
                    c.side.value,
                    f"{c.power:g}",
                    f"{kelvin_to_celsius(c.effective_tj_max(tj_def)):g}",
                    f"{c.footprint.area() / MM2:.1f}",
                ]
            )
        rows.append(["total", "", f"{b.total_power:g}", "", ""])
        out.append(_table(rows, ["ref", "side", "P [W]", "Tj_max [°C]", "area [mm²]"], {2, 3, 4}))

    cr = b.criteria
    out.append("\nCriteria")
    tj_c = kelvin_to_celsius(cr.tj_max_default)
    out.append(
        f"  IR drop ≤ {cr.ir_drop_pct:g} %   Tj ≤ {tj_c:g} °C (default)   "
        f"J ≤ {cr.current_density} (ΔT {cr.current_density_temp_rise:g} K)   "
        f"Z0 ±{cr.z0_tol_pct:g} %"
    )
    a = cfg.analysis
    out.append("\nAnalysis")
    out.append(
        f"  solvers: {', '.join(a.solvers) or '(none)'}   mesh cell {_mm(a.mesh.cell)} mm"
        f"   output {a.output_dir}"
    )
    return "\n".join(out)


def _model_checks(cfg: LoadedConfig) -> list[tuple[bool, str]]:
    b = cfg.board
    checks: list[tuple[bool, str]] = [(True, "schema, units and references valid")]
    for n in b.nets:
        sinks = [p for p in b.ports if p.net == n.name and p.kind is PortKind.CURRENT_SINK]
        srcs = [p for p in b.ports if p.net == n.name and p.kind is PortKind.VOLTAGE_SOURCE]
        if sinks and not srcs:
            checks.append((False, f"net {n.name}: has current sinks but no voltage source"))
        for s in srcs:
            if n.nominal_voltage is not None and abs(s.value - n.nominal_voltage) > 1e-9:
                msg = (
                    f"net {n.name}: source {s.name} = {s.value:g} V "
                    f"≠ nominal {n.nominal_voltage:g} V"
                )
                checks.append((False, msg))
    known = available_solvers()
    for name in cfg.analysis.solvers:
        if name not in known:
            checks.append((False, f"solver {name!r} is not available yet"))
    if cfg.kicad is not None:
        for note in cfg.kicad.notes:
            checks.append((False, f"KiCad: {note}"))
        cell = cfg.analysis.mesh.cell / cfg.analysis.mesh.refine
        thin = {n: w for n, w in cfg.kicad.min_width.items() if w < cell}
        modelled = {s.net for s in b.shapes} & {p.net for p in b.ports}
        for net_name, w in sorted(thin.items()):
            if net_name in modelled:
                checks.append(
                    (
                        False,
                        f"KiCad: net {net_name} has {_mm(w)} mm tracks, narrower than the mesh "
                        "cell "
                        f"{_mm(cell)} mm — they may vanish; refine analysis.mesh",
                    )
                )
    return checks


def cmd_check(args: argparse.Namespace, out: TextIO) -> int:
    cfg = load_config(args.config)
    print(summarize(cfg), file=out)
    checks = _model_checks(cfg)
    print("\nChecks", file=out)
    for ok, msg in checks:
        print(f"  [{'ok' if ok else 'warn'}] {msg}", file=out)
    n_warn = sum(1 for ok, _ in checks if not ok)
    print(f"\n{'OK' if n_warn == 0 else f'OK with {n_warn} warning(s)'}", file=out)
    return EXIT_INVALID if (args.strict and n_warn) else EXIT_OK


def _fmt_ports(rows: list[dict[str, Any]]) -> str:
    table = []
    for r in summarize_ports(rows):
        table.append(
            [
                r["name"],
                r["net"],
                f"{r['current']:g}",
                f"{r['v_nominal']:.4g}",
                f"{r['v_avg']:.4f}",
                f"{r['v_min']:.4f}",
                f"{r['drop_v'] * 1e3:.2f}",
                f"{r['drop_pct']:.2f}",
                f"{r['r_path'] * 1e3:.3f}",
                "PASS" if r["passed"] else "FAIL",
            ]
        )
    return _table(
        table,
        [
            "sink",
            "net",
            "I [A]",
            "V_nom",
            "V_avg",
            "V_min",
            "drop [mV]",
            "drop [%]",
            "R_path [mΩ]",
            "result",
        ],
        {2, 3, 4, 5, 6, 7, 8},
    )


def _c(t_k: float) -> str:
    return f"{kelvin_to_celsius(t_k):.1f}"


def _print_thermal(rs: ResultSet, layers: Sequence[str], out: TextIO) -> None:
    rows = [
        [
            r["ref"],
            f"{r['power']:g}",
            "2R" if r["model"] == "two_resistor" else "board",
            _c(r["tj_peak"]),
            _c(r["t_board"]),
            _c(r["tj_max"]),
            f"{r['margin']:.1f}",
            "PASS" if r["passed"] else "FAIL",
        ]
        for r in sorted(rs.meta["components"], key=lambda r: r["margin"])
    ]
    if rows:
        print(
            _table(
                rows,
                [
                    "ref",
                    "P [W]",
                    "model",
                    "Tj [°C]",
                    "T_board [°C]",
                    "Tj_max",
                    "margin [K]",
                    "result",
                ],
                {1, 3, 4, 5, 6},
            ),
            file=out,
        )
    for lname in layers:
        print(f"  {lname:8s} T_max {_c(rs.scalars[f'{lname}.t_max'])} °C", file=out)
    p_in = rs.scalars["power_components"] + rs.scalars["power_joule"]
    print(
        f"  heat in {p_in:.3f} W (components {rs.scalars['power_components']:.3f} W, "
        f"Joule {rs.scalars['power_joule'] * 1e3:.1f} mW)",
        file=out,
    )
    flows = {
        k.removeprefix("heat_out."): v for k, v in rs.scalars.items() if k.startswith("heat_out.")
    }
    print("  heat out " + ", ".join(f"{k} {v:.3f} W" for k, v in flows.items()), file=out)
    hist = rs.meta.get("history") or {}
    if hist:
        print(
            f"  transient: {len(hist['time']) - 1} steps to t = {hist['time'][-1]:g} s, "
            f"peak T {_c(max(hist['t_max']))} °C",
            file=out,
        )


def _print_coupled(rs: ResultSet, layers: Sequence[str], out: TextIO) -> None:
    hist = rs.meta["history"]
    state = "converged" if rs.meta["converged"] else "NOT converged"
    print(
        f"  {state} after {rs.meta['iterations']} pass(es): "
        f"ΔT {rs.scalars['delta_t']:.2g} K, ΔV {rs.scalars['delta_v']:.2g} V",
        file=out,
    )
    rows = [
        [
            f"{int(k)}",
            "-" if not math.isfinite(dt) else f"{dt:.3g}",
            "-" if not math.isfinite(dv) else f"{dv * 1e3:.3g}",
            _c(tm),
            f"{pj * 1e3:.2f}",
            f"{dp:.3f}",
        ]
        for k, dt, dv, tm, pj, dp in zip(
            hist["iteration"],
            hist["delta_t"],
            hist["delta_v"],
            hist["t_max"],
            hist["joule_power"],
            hist["drop_pct_max"],
            strict=True,
        )
    ]
    head = ["pass", "ΔT [K]", "ΔV [mV]", "T_max [°C]", "Joule [mW]", "worst drop [%]"]
    print(_table(rows, head, {1, 2, 3, 4, 5}), file=out)
    print("  coupled vs uncoupled (pass 0):", file=out)
    for r in summarize_ports(rs.meta["ports"]):
        before = rs.scalars.get(f"{r['name']}.drop_pct.uncoupled")
        if before is not None:
            print(
                f"    {r['name']:12s} drop {before:.3f} % → {r['drop_pct']:.3f} %"
                f"  ({'PASS' if r['passed'] else 'FAIL'})",
                file=out,
            )
    for r in sorted(rs.meta["components"], key=lambda r: r["margin"]):
        before = rs.scalars.get(f"{r['ref']}.tj.uncoupled")
        if before is not None:
            print(
                f"    {r['ref']:12s} Tj {_c(before)} → {_c(r['tj'])} °C"
                f"  ({'PASS' if r['passed'] else 'FAIL'})",
                file=out,
            )
    print(
        f"    T_max {_c(rs.scalars['t_max.uncoupled'])} → {_c(rs.scalars['t_max'])} °C, "
        f"Joule {rs.scalars['joule_power.uncoupled'] * 1e3:.2f} → "
        f"{rs.scalars['joule_power'] * 1e3:.2f} mW",
        file=out,
    )


def _mech_gate(cfg: LoadedConfig, force: bool, out: TextIO) -> bool:
    """Print the linked match status; return False if the run must stop."""
    m = cfg.mechanical
    if m is None:
        return True
    applied = ", ".join(m.applied_boundaries) or "none"
    print(f"Mechanical match {m.match_path}  ({'OK' if m.ok else 'NG'})", file=out)
    print(f"  thermal boundaries from MCAD: {applied}", file=out)
    if m.ok or not m.require_ok:
        return True
    print(f"  [warn] ECAD–MCAD match has {len(m.ng_items)} NG item(s):", file=out)
    for item in m.ng_items[:20]:
        print(f"    {item}", file=out)
    if force:
        print("  [warn] --force given: simulating anyway", file=out)
        return True
    print(
        "error: ECAD–MCAD match is NG; fix the drawing/board or rerun with --force",
        file=sys.stderr,
    )
    return False


def cmd_run(args: argparse.Namespace, out: TextIO) -> int:
    cfg = load_config(args.config)
    if not _mech_gate(cfg, args.force, out):
        return EXIT_MECH_NG
    known = available_solvers()
    requested = list(args.solver) if args.solver else list(cfg.analysis.solvers)
    if args.solver:
        missing = [n for n in requested if n not in known]
        if missing:
            print(f"error: unknown solver(s): {', '.join(missing)}", file=sys.stderr)
            return EXIT_INVALID
        names = requested
    else:
        names = [n for n in requested if n in known]
        for n in requested:
            if n not in known:
                print(f"  [skip] solver {n!r} is not available yet", file=out)
    if not names:
        print("error: no runnable solvers (set analysis.solvers or pass --solver)", file=sys.stderr)
        return EXIT_INVALID

    run = run_analysis(cfg, names)
    g = run.grid
    print(
        f"Mesh  {g.nx} × {g.ny} cells  ({_mm(g.dx)} × {_mm(g.dy)} mm), "
        f"{len(g.layers)} layers, {g.copper_cells()} copper cells",
        file=out,
    )
    for name, rs in run.results.items():
        print(f"\n[{name}]", file=out)
        if name == "dc_ir":
            print(_fmt_ports(rs.meta["ports"]), file=out)
            srcs = [r for r in rs.meta["ports"] if r["kind"] == PortKind.VOLTAGE_SOURCE.value]
            for r in srcs:
                print(f"  source {r['name']}: {r['current']:.4g} A, {r['power']:.4g} W", file=out)
            print(f"  conduction loss {rs.scalars['joule_power'] * 1e3:.2f} mW", file=out)
            for lname in g.layers:
                jm = rs.scalars.get(f"{lname}.j_max")
                jl = rs.scalars.get(f"{lname}.j_limit")
                if jm is not None:
                    lim = f" / limit {jl * 1e-6:.1f}" if jl else ""
                    print(f"  {lname:8s} J_max {jm * 1e-6:7.2f}{lim} A/mm²", file=out)
            if "via.i_max" in rs.scalars:
                print(f"  via I_max {rs.scalars['via.i_max']:.3f} A", file=out)
        elif name == "thermal":
            _print_thermal(rs, g.layers, out)
        elif name == "coupled":
            _print_coupled(rs, g.layers, out)
        elif name == "si":
            _print_si(rs, out)
        for v in rs.violations:
            tag = {"violation": "FAIL", "warning": "warn", "info": "info"}[v.severity.value]
            print(f"  [{tag}] {v.message or v.check}", file=out)

    out_dir = Path(args.out) if args.out else cfg.analysis.output_dir
    files = write_results(run, out_dir, plots=not args.no_plots, report=args.report)
    print(f"\nWrote {len(files)} file(s) to {out_dir}", file=out)
    counts = violation_counts(run)
    n_fail = counts[Severity.VIOLATION]
    print("PASS" if n_fail == 0 else f"FAIL ({n_fail} violation(s))", file=out)
    return EXIT_OK if n_fail == 0 else EXIT_VIOLATIONS


def _print_si(rs: ResultSet, out: TextIO) -> None:
    rows = []
    for r in rs.meta["lines"]:
        target = "-" if r["target"] is None else f"{r['target']:g} ±{r['tolerance_pct']:g}%"
        ok = "" if r["target"] is None else ("ok" if r["passed"] else "FAIL")
        rows.append(
            [
                r["name"],
                r["topology"],
                r["layer"],
                f"{r['quantity']}",
                f"{r['z_fem']:.2f}",
                f"{r['z_formula']:.2f}",
                f"{r['crosscheck_dev'] * 100:+.1f}%",
                f"{r['eps_eff_fem']:.3f}",
                target,
                ok,
            ]
        )
    head = ["line", "topology", "layer", "Z", "FEM [Ω]", "formula [Ω]", "Δ", "εeff", "target", ""]
    print(_table(rows, head, {4, 5, 6, 7}), file=out)


def cmd_z0(args: argparse.Namespace, out: TextIO) -> int:
    """Stand-alone impedance calculator (no config needed)."""
    from pcbsim.si.analytic import (
        LineZ,
        coupled_stripline_cohn,
        diff_microstrip_ipc,
        diff_stripline_ipc,
        microstrip_hj,
        microstrip_ipc,
        stripline_cohn,
        stripline_ipc,
        stripline_wheeler,
    )
    from pcbsim.si.fem2d import CrossSection, FemOptions, Rect
    from pcbsim.si.fem2d import solve as fem_solve
    from pcbsim.units import parse_quantity

    def ln(v: str) -> float:
        try:
            return float(v) * 1e-3
        except ValueError:
            return parse_quantity(v, "length")

    w = ln(args.w)
    h = ln(args.h)
    t = ln(args.t)
    s = ln(args.s) if args.s else None
    er = float(args.er)

    def num(v: float | None, nd: int = 2) -> str:
        return "-" if v is None or not math.isfinite(v) else f"{v:.{nd}f}"

    zs: list[LineZ] = []
    if args.kind == "microstrip":
        y0, top = h, None
        bands = [(0.0, h, er)]
        if s is None:
            zs = [microstrip_hj(w, h, er, t), microstrip_ipc(w, h, er, t)]
        else:
            zs = [diff_microstrip_ipc(w, s, h, er, t)]
    else:
        b = h
        y0, top = (b - t) / 2.0, b
        bands = [(0.0, b, er)]
        if s is None:
            zs = [stripline_wheeler(w, b, t, er), stripline_ipc(w, b, er, t)]
            if t == 0:
                zs.insert(0, stripline_cohn(w, b, er))
        else:
            zs = [diff_stripline_ipc(w, s, b, er, t)]
            if t == 0:
                zs.insert(0, coupled_stripline_cohn(w, s, b, er))
    if s is None:
        conductors = [Rect(-w / 2, w / 2, y0, y0 + t)]
    else:
        conductors = [Rect(-s / 2 - w, -s / 2, y0, y0 + t), Rect(s / 2, s / 2 + w, y0, y0 + t)]
    fem = fem_solve(CrossSection(conductors, bands, top), FemOptions())
    zf = fem.single() if s is None else fem.pair()
    geom = f"w={_mm(w)} h={_mm(h)} t={_mm(t)}" + (f" s={_mm(s)}" if s else "") + " mm"
    print(f"{args.kind}  {geom}  εr={er:g}  (FEM: {fem.n_dofs} dofs)", file=out)
    rows: list[list[str]] = []
    if s is None:
        for z in [zf, *zs]:
            rows.append([z.method, num(z.z0), num(z.eps_eff, 3), z.note])
        print(_table(rows, ["method", "Z0 [Ω]", "εeff", "note"], {1, 2}), file=out)
    else:
        for z in [zf, *zs]:
            rows.append([z.method, num(z.z_odd), num(z.z_even), num(z.z_diff), z.note])
        head = ["method", "Zodd [Ω]", "Zeven [Ω]", "Zdiff [Ω]", "note"]
        print(_table(rows, head, {1, 2, 3}), file=out)
    return EXIT_OK


def cmd_report(args: argparse.Namespace, out: TextIO) -> int:
    from pcbsim.report import has_violations, write_report

    path = write_report(args.results, args.out, args.title)
    print(f"Wrote {path}", file=out)
    return EXIT_VIOLATIONS if has_violations(args.results) else EXIT_OK


def cmd_match(args: argparse.Namespace, out: TextIO) -> int:
    from pcbsim.registration.layermap import load_layer_map
    from pcbsim.registration.pipeline import run_match, write_match
    from pcbsim.registration.report import write_report

    if args.gerber is None and not args.drill:
        print("error: give --gerber and/or --drill", file=sys.stderr)
        return EXIT_USAGE
    lmap = load_layer_map(args.map)
    mech = [Path(p) for p in args.mech] + [Path(p) for p in (args.step or [])]
    # A previous result must not survive a failed match: `pcbsim run` would trust it.
    targets = [Path(args.json)] if args.json else []
    if args.report:
        targets.append(Path(args.report).with_suffix(".json"))
    for stale in targets:
        stale.unlink(missing_ok=True)
    m = run_match(
        Path(args.gerber) if args.gerber else None,
        [Path(p) for p in args.drill or []],
        mech,
        lmap,
        Path(args.pnp) if args.pnp else None,
    )
    r = m.registration
    t = r.transform
    print("Registration (drawing → board)", file=out)
    print(
        f"  rotation {t.angle_deg:.4f}°   translation ({_mm(t.tx)}, {_mm(t.ty)}) mm   "
        f"mirror {'yes' if t.mirror else 'no'}   scale {t.scale:.6g}",
        file=out,
    )
    o = f"   outline RMS {_mm(r.outline_rms, 4)} mm" if r.outline_rms is not None else ""
    print(
        f"  matched {len(r.matches)}/{r.n_src} features   RMS {_mm(r.rms, 4)} mm{o}",
        file=out,
    )
    for w in r.warnings:
        print(f"  [warn] {w}", file=out)
    rows = [
        [
            i.status.value,
            i.category,
            i.subject,
            "-" if i.value is None else f"{i.value:.3f}",
            "-" if i.limit is None else f"{i.limit:.3f}",
            i.unit,
        ]
        for i in m.report.items
        if i.status.value != "OK" or args.verbose
    ]
    if rows:
        print("\nChecks" + ("" if args.verbose else " (NG / WARN only)"), file=out)
        print(_table(rows, ["result", "check", "item", "value", "limit", "unit"], {3, 4}), file=out)
    if m.boundaries:
        print("\nThermal boundaries from MCAD", file=out)
        for b in m.boundaries:
            print(f"  {b.name:20s} {b.kind:18s} {b.note}", file=out)
    written: list[Path] = []
    if args.report:
        written += write_report(m, Path(args.report), Path(args.json) if args.json else None)
    elif args.json:
        written.append(write_match(m, Path(args.json)))
    for p in written:
        print(f"Wrote {p}", file=out)
    print("PASS" if m.ok else f"NG ({m.report.n_ng} item(s))", file=out)
    return EXIT_OK if m.ok else EXIT_VIOLATIONS


def cmd_solvers(args: argparse.Namespace, out: TextIO) -> int:
    solvers = available_solvers()
    if not solvers:
        print("no solvers registered", file=out)
    for name, cls in solvers.items():
        print(f"{name:12s} {cls.description}", file=out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcbsim", description="Open-source PCB multiphysics simulator")
    p.add_argument("--version", action="version", version=f"pcbsim {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    c = sub.add_parser("check", help="validate a config and print a board summary")
    c.add_argument("config")
    c.add_argument("--strict", action="store_true", help="treat warnings as errors (exit 1)")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="run the configured solvers")
    r.add_argument("config")
    r.add_argument("--solver", action="append", help="run only this solver (repeatable)")
    r.add_argument("--out", help="output directory (default: analysis.output_dir)")
    r.add_argument("--no-plots", action="store_true", help="skip PNG heat maps")
    r.add_argument("--report", action="store_true", help="also write report.html")
    r.add_argument(
        "--force", action="store_true", help="simulate even if the linked ECAD–MCAD match is NG"
    )
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="build a self-contained HTML report from a results dir")
    rep.add_argument("results", help="directory written by 'pcbsim run' (has results.json)")
    rep.add_argument("--out", help="HTML file (default: <results>/report.html)")
    rep.add_argument("--title", help="report title")
    rep.set_defaults(func=cmd_report)

    m = sub.add_parser("match", help="register a mechanical drawing to Gerber/Excellon and check")
    m.add_argument("--gerber", help="directory with Gerber (X2) files")
    m.add_argument("--drill", action="append", help="Excellon drill file (repeatable)")
    m.add_argument(
        "--mech", action="append", required=True, help="DXF / DWG / STEP file (repeatable)"
    )
    m.add_argument("--step", action="append", help="extra STEP file(s) for 3D parts")
    m.add_argument("--pnp", help="pick-and-place / centroid CSV (overrides Gerber X3)")
    m.add_argument("--map", help="layer-map YAML (layer names, tolerances, thermal models)")
    m.add_argument("--report", help="write the HTML report here (JSON next to it)")
    m.add_argument("--json", help="write the match JSON here (for config 'mechanical.match')")
    m.add_argument("-v", "--verbose", action="store_true", help="list OK checks too")
    m.set_defaults(func=cmd_match)

    z = sub.add_parser(
        "z0",
        help="impedance calculator: closed forms vs 2D FEM (lengths in mm or with units)",
    )
    z.add_argument("kind", choices=["microstrip", "stripline"])
    z.add_argument("-w", required=True, help="trace width")
    z.add_argument(
        "--h",
        "-H",
        dest="h",
        required=True,
        help="microstrip: dielectric height; stripline: plane-to-plane spacing b",
    )
    z.add_argument("-t", default="0", help="trace thickness (default 0)")
    z.add_argument("-s", help="edge-to-edge spacing → differential pair")
    z.add_argument("--er", required=True, help="dielectric constant")
    z.set_defaults(func=cmd_z0)

    s = sub.add_parser("solvers", help="list available solver plugins")
    s.set_defaults(func=cmd_solvers)
    return p


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    stream = out if out is not None else sys.stdout
    try:
        code: int = args.func(args, stream)
    except PcbsimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INVALID
    return code


if __name__ == "__main__":
    raise SystemExit(main())
