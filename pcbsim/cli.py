"""Command-line interface.

    pcbsim check  config.yaml           validate a config and print a board summary
    pcbsim run    config.yaml           run the configured solvers, write results/
    pcbsim report results/              build HTML/JSON reports (stage 7)
    pcbsim solvers                      list registered solver plugins

The ``check`` output mirrors the pre-simulation validation step of common PDN
tools: stack-up table, per-net source/sink table, heat sources, then a
pass/fail list of model checks. ``run`` prints a per-sink IR-drop table (the
text form of a power tree), per-layer peak current density and the violation
list. Exit codes: 0 ok, 1 invalid input, 2 usage error, 3 not implemented yet,
4 design violations found.
"""

from __future__ import annotations

import argparse
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


def _mm(x: float, nd: int = 3) -> str:
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


def cmd_run(args: argparse.Namespace, out: TextIO) -> int:
    cfg = load_config(args.config)
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
        for v in rs.violations:
            tag = {"violation": "FAIL", "warning": "warn", "info": "info"}[v.severity.value]
            print(f"  [{tag}] {v.message or v.check}", file=out)

    out_dir = Path(args.out) if args.out else cfg.analysis.output_dir
    files = write_results(run, out_dir, plots=not args.no_plots)
    print(f"\nWrote {len(files)} file(s) to {out_dir}", file=out)
    counts = violation_counts(run)
    n_fail = counts[Severity.VIOLATION]
    print("PASS" if n_fail == 0 else f"FAIL ({n_fail} violation(s))", file=out)
    return EXIT_OK if n_fail == 0 else EXIT_VIOLATIONS


def cmd_report(args: argparse.Namespace, out: TextIO) -> int:
    print("pcbsim report: not implemented yet (arrives in stage 7).", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


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
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="build HTML/JSON reports from a results directory")
    rep.add_argument("results")
    rep.set_defaults(func=cmd_report)

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
