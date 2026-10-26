"""Synthetic ``.kicad_pcb`` boards in the KiCad 8 board-file format.

:func:`soc_board` writes the 4-layer SoC example of ``examples/soc_4layer.yaml`` as a
KiCad board, so that the KiCad import can be compared with the hand-written YAML
model on the same physics. The file uses what real KiCad 8 output contains:

* the stack-up in ``setup/stackup`` (solder mask, copper, dielectrics with εr and
  loss tangent; the ``L1_TOP`` … user layer names in ``layers``)
* the board placed at (100, 50) mm on the page with y pointing down
* ``Edge.Cuts`` as four ``gr_line`` items
* filled zones (``filled_polygon``) for the planes, including the slotted
  ``VDD_1V0`` plane on ``In2.Cu``
* footprints with properties, courtyards and pads (``(net N "NAME")``)
* blind vias ``F.Cu → In2.Cu`` and through vias, plus one routed signal with a
  segment and a track arc

Run ``python -m tests.kicad_fixtures out/`` to write the files.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

OX, OY = 100.0, 50.0
W, H = 60.0, 40.0
NETS = ("", "VDD_1V0", "GND", "SIG_CLK")
CU = (
    ("F.Cu", "L1_TOP", "mixed"),
    ("In1.Cu", "L2_GND", "power"),
    ("In2.Cu", "L3_PWR", "power"),
    ("B.Cu", "L4_BOT", "mixed"),
)

VDD_PLANE = [(1, 1), (25, 1), (25, 30), (26.5, 30), (26.5, 1), (59, 1), (59, 39), (1, 39)]


def fx(x: float) -> float:
    """pcbsim x (mm, origin lower-left) → KiCad file x."""
    return round(OX + x, 6)


def fy(y: float) -> float:
    """pcbsim y (mm, y up) → KiCad file y (y down)."""
    return round(OY + H - y, 6)


def _u() -> str:
    return str(uuid.uuid4())


def _net(name: str) -> str:
    return f'(net {NETS.index(name)} "{name}")' if name else '(net 0 "")'


def _pts(points: Iterable[tuple[float, float]]) -> str:
    return "(pts " + " ".join(f"(xy {fx(x)} {fy(y)})" for x, y in points) + ")"


@dataclass
class Pad:
    num: str
    x: float
    y: float
    w: float
    h: float
    net: str = ""
    shape: str = "rect"
    kind: str = "smd"
    drill: float | None = None
    angle: float = 0.0
    layers: str = '"F.Cu" "F.Paste" "F.Mask"'


@dataclass
class Fp:
    ref: str
    x: float
    y: float
    court: tuple[float, float]
    pads: list[Pad] = field(default_factory=list)
    angle: float = 0.0
    side: str = "F"
    value: str = ""
    lib: str = "Package:Generic"


def footprint(fp: Fp) -> str:
    """A placed footprint; pad/courtyard coordinates are local (y down)."""
    cw, ch = fp.court
    at = f"(at {fx(fp.x)} {fy(fp.y)}{f' {fp.angle:g}' if fp.angle else ''})"
    crt = f"{fp.side}.CrtYd"
    s = [f'  (footprint "{fp.lib}" (layer "{fp.side}.Cu") (uuid "{_u()}") {at}']
    s.append(
        f'    (property "Reference" "{fp.ref}" (at 0 {-ch / 2 - 1:g} 0) (layer "{fp.side}.SilkS"))'
    )
    val = fp.value or fp.ref
    s.append(f'    (property "Value" "{val}" (at 0 {ch / 2 + 1:g} 0) (layer "{fp.side}.Fab"))')
    s.append("    (attr smd)")
    s.append(
        f"    (fp_rect (start {-cw / 2:g} {-ch / 2:g}) (end {cw / 2:g} {ch / 2:g}) "
        f'(stroke (width 0.05) (type default)) (fill none) (layer "{crt}") (uuid "{_u()}"))'
    )
    for p in fp.pads:
        ang = fp.angle + p.angle
        drill = f" (drill {p.drill:g})" if p.drill else ""
        net = f" {_net(p.net)}" if p.net else ""
        rot = f" {ang:g}" if ang else ""
        s.append(
            f'    (pad "{p.num}" {p.kind} {p.shape} (at {p.x:g} {p.y:g}{rot}) '
            f'(size {p.w:g} {p.h:g}){drill} (layers {p.layers}){net} (uuid "{_u()}"))'
        )
    s.append("  )")
    return "\n".join(s)


def _dielectric(name: str, typ: str, t: float) -> str:
    return (
        f'      (layer "{name}" (type "{typ}") (thickness {t:g}) (material "FR4") '
        "(epsilon_r 4.2) (loss_tangent 0.02))"
    )


def header(title: str, stackup: bool = True, user_names: bool = True) -> str:
    lines = [
        "(kicad_pcb",
        "  (version 20240108)",
        '  (generator "pcbnew")',
        '  (generator_version "8.0")',
    ]
    lines.append('  (general (thickness 1.5)) (paper "A4")')
    lines.append(f'  (title_block (title "{title}") (rev "A"))')
    lines.append("  (layers")
    for i, (canon, user, typ) in enumerate(CU):
        ordinal = 31 if canon == "B.Cu" else i
        uname = f' "{user}"' if user_names else ""
        lines.append(f'    ({ordinal} "{canon}" {typ}{uname})')
    for ordinal, name in (
        (38, "B.Mask"),
        (39, "F.Mask"),
        (44, "Edge.Cuts"),
        (45, "Margin"),
        (46, "B.CrtYd"),
        (47, "F.CrtYd"),
        (36, "B.SilkS"),
        (37, "F.SilkS"),
        (48, "B.Fab"),
        (49, "F.Fab"),
        (34, "B.Paste"),
        (35, "F.Paste"),
    ):
        lines.append(f'    ({ordinal} "{name}" user)')
    lines.append("  )")
    lines.append("  (setup")
    if stackup:
        lines.append("    (stackup")
        lines.append('      (layer "F.SilkS" (type "Top Silk Screen"))')
        lines.append('      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.02))')
        lines.append('      (layer "F.Cu" (type "copper") (thickness 0.03479))')
        lines.append(_dielectric("dielectric 1", "prepreg", 0.2))
        lines.append('      (layer "In1.Cu" (type "copper") (thickness 0.03479))')
        lines.append(_dielectric("dielectric 2", "core", 1.02))
        lines.append('      (layer "In2.Cu" (type "copper") (thickness 0.03479))')
        lines.append(_dielectric("dielectric 3", "prepreg", 0.2))
        lines.append('      (layer "B.Cu" (type "copper") (thickness 0.03479))')
        lines.append('      (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.02))')
        lines.append('      (layer "B.SilkS" (type "Bottom Silk Screen"))')
        lines.append('      (copper_finish "ENIG") (dielectric_constraints no)')
        lines.append("    )")
    lines.append("    (pad_to_mask_clearance 0)")
    lines.append(f"    (aux_axis_origin {fx(0)} {fy(0)})")
    lines.append("  )")
    for i, n in enumerate(NETS):
        lines.append(f'  (net {i} "{n}")')
    return "\n".join(lines)


def edge_rect(x0: float, y0: float, x1: float, y1: float) -> str:
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    out = []
    for a, b in zip(c, c[1:] + c[:1], strict=True):
        out.append(
            f"  (gr_line (start {fx(a[0])} {fy(a[1])}) (end {fx(b[0])} {fy(b[1])}) "
            f'(stroke (width 0.05) (type default)) (layer "Edge.Cuts") (uuid "{_u()}"))'
        )
    return "\n".join(out)


def zone(
    net: str,
    layer: str,
    outline: Sequence[tuple[float, float]],
    filled: bool = True,
    clearance: float = 0.3,
    name: str = "",
) -> str:
    s = [
        f'  (zone {_net(net)} (net_name "{net}") (layer "{layer}") (uuid "{_u()}")'
        + (f' (name "{name}")' if name else "")
        + " (hatch edge 0.5)"
    ]
    s.append(f"    (connect_pads yes (clearance {clearance:g})) (min_thickness 0.25)")
    s.append("    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))")
    s.append(f"    (polygon {_pts(outline)})")
    if filled:
        s.append(f'    (filled_polygon (layer "{layer}") {_pts(outline)})')
    s.append("  )")
    return "\n".join(s)


def via(
    x: float,
    y: float,
    drill: float,
    size: float,
    net: str,
    layers: tuple[str, str] = ("F.Cu", "B.Cu"),
) -> str:
    kind = "" if layers == ("F.Cu", "B.Cu") else "blind "
    return (
        f"  (via {kind}(at {fx(x)} {fy(y)}) (size {size:g}) (drill {drill:g}) "
        f'(layers "{layers[0]}" "{layers[1]}") {_net(net)} (uuid "{_u()}"))'
    )


def segment(
    a: tuple[float, float], b: tuple[float, float], width: float, layer: str, net: str
) -> str:
    return (
        f"  (segment (start {fx(a[0])} {fy(a[1])}) (end {fx(b[0])} {fy(b[1])}) (width {width:g}) "
        f'(layer "{layer}") {_net(net)} (uuid "{_u()}"))'
    )


def track_arc(
    a: tuple[float, float],
    m: tuple[float, float],
    b: tuple[float, float],
    width: float,
    layer: str,
    net: str,
) -> str:
    return (
        f"  (arc (start {fx(a[0])} {fy(a[1])}) (mid {fx(m[0])} {fy(m[1])}) "
        f"(end {fx(b[0])} {fy(b[1])}) "
        f'(width {width:g}) (layer "{layer}") {_net(net)} (uuid "{_u()}"))'
    )


def soc_footprints() -> list[Fp]:
    return [
        Fp(
            "U1",
            45,
            20,
            (14, 14),
            [Pad("VDD", 0, 0, 8, 8, "VDD_1V0")],
            value="SoC",
            lib="Package_BGA:BGA-196",
        ),
        Fp(
            "U2",
            11,
            20,
            (10, 10),
            [Pad("OUT", 0, 0, 6, 6, "VDD_1V0")],
            angle=90,
            value="VRM",
            lib="Package_DFN_QFN:QFN-48",
        ),
        Fp(
            "L1",
            19.5,
            32.5,
            (5, 5),
            [Pad("1", -1.5, 0, 1.2, 3.0), Pad("2", 1.5, 0, 1.2, 3.0)],
            value="0.47uH",
        ),
        Fp(
            "U3",
            22,
            7,
            (4, 4),
            [
                Pad("1", -0.95, 1.1, 0.6, 1.0),
                Pad("2", 0.95, 1.1, 0.6, 1.0),
                Pad("3", 0, -1.1, 0.6, 1.0),
            ],
            value="LDO",
        ),
    ]


def soc_board(filled: bool = True, stackup: bool = True, signal: bool = True) -> str:
    """The examples/soc_4layer.yaml board as a KiCad 8 file."""
    parts = [header("soc_4layer_1v0 (KiCad)", stackup=stackup), edge_rect(0, 0, W, H)]
    parts += [footprint(fp) for fp in soc_footprints()]
    if signal:
        parts.append(segment((30, 36), (34, 36), 0.36, "F.Cu", "SIG_CLK"))
        parts.append(track_arc((34, 36), (35.414, 35.414), (36, 34), 0.36, "F.Cu", "SIG_CLK"))
        parts.append(segment((36, 34), (36, 31), 0.36, "F.Cu", "SIG_CLK"))
    for i in range(5):
        for j in range(5):
            parts.append(via(9 + i, 18 + j, 0.3, 0.6, "VDD_1V0", ("F.Cu", "In2.Cu")))
            parts.append(via(42 + 1.5 * i, 17 + 1.5 * j, 0.3, 0.6, "VDD_1V0", ("F.Cu", "In2.Cu")))
    for i in range(2):
        for j in range(7):
            parts.append(via(39.5 + 11 * i, 14 + 2 * j, 0.3, 0.6, "GND"))
    for x, y in ((3, 3), (57, 3), (3, 37), (57, 37)):
        parts.append(via(x, y, 0.4, 0.8, "GND"))
    full = [(0, 0), (W, 0), (W, H), (0, H)]
    parts.append(zone("GND", "In1.Cu", full, filled, name="gnd_plane"))
    parts.append(zone("VDD_1V0", "In2.Cu", VDD_PLANE, filled, name="vdd_plane"))
    parts.append(zone("GND", "B.Cu", full, filled, name="bot_gnd_pour"))
    return "\n".join(parts) + "\n)\n"


OVERLAY = """\
# Electrical intent for examples/kicad/soc_4layer.kicad_pcb (KiCad stores the geometry,
# not sources, loads, power or thermal data). Layers may be given by their KiCad user
# names (L1_TOP …) or canonical names (F.Cu …); components by reference designator.
version: 1
name: soc_4layer_kicad
kicad:
  file: soc_4layer.kicad_pcb
  vias:                                 # KiCad has no via fill: mark the thermal vias
    - { net: GND, drill: 0.3, filled: true, filler: via_fill_epoxy }

nets:
  - { name: VDD_1V0, kind: power, voltage: 1.0 }
  - { name: GND, kind: ground }

components:                             # footprints come from the board file
  - { ref: U1, power: 4.0 W, tj_max: 105, theta_jc: 0.5, theta_jb: 3.0 }
  - { ref: U2, power: 0.6 W, tj_max: 125, theta_jc: 2.0, theta_jb: 8.0 }
  - { ref: L1, power: 0.25 W, tj_max: 125 }
  - { ref: U3, power: 0.15 W }

ports:
  - { name: VRM_OUT, kind: voltage_source, net: VDD_1V0, layer: L1_TOP, reference_net: GND,
      rect: [8, 17, 14, 23], voltage: 1.0 V }
  - { name: SOC_CORE, kind: current_sink, net: VDD_1V0, layer: L1_TOP, reference_net: GND,
      rect: [41, 16, 49, 24], current: 6 A }

thermal_boundaries:
  - { name: U1_heatsink, kind: convection, component: U1, resistance: 6.0 }
  - { name: chassis_standoffs, kind: fixed_temperature, side: bottom, temperature: 45,
      polygon: [[1, 1], [5, 1], [5, 5], [1, 5]] }
  - { name: chassis_standoff_tr, kind: fixed_temperature, side: bottom, temperature: 45,
      rect: [55, 35, 59, 39] }

transmission_lines:
  - { name: clk, layer: L1_TOP, width: 0.36, target: 50 }

criteria:
  ir_drop_pct: 3.0
  tj_max_default: 105
  current_density: ipc2152
  current_density_temp_rise: 10
  z0_tol_pct: 10

analysis:
  solvers: [dc_ir, thermal, coupled, si]
  mesh: { cell: 0.25 }
  output_dir: results
  options:
    thermal: { ambient: 25, h_top: 10, h_bottom: 5 }
"""


def write_example(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    pcb = out / "soc_4layer.kicad_pcb"
    pcb.write_text(soc_board(), "utf-8")
    cfg = out / "soc_kicad.yaml"
    cfg.write_text(OVERLAY, "utf-8")
    return [pcb, cfg]


if __name__ == "__main__":
    for p in write_example(Path(sys.argv[1] if len(sys.argv) > 1 else "examples/kicad")):
        print(p)
