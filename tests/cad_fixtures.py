"""Synthetic ECAD/MCAD project in the formats KiCad 8 and FreeCAD write.

Used by the E2E tests and by ``examples/mech/`` (``python -m tests.cad_fixtures out/``).

ECAD (board frame, mm, origin = lower-left board corner), KiCad 8 conventions:

* ``board-Edge_Cuts.gm1`` — X2 ``Profile,NP``; 60 × 40 mm outline with R1 corner
  arcs (``G75`` + ``G03``) and a 6 × 4 mm rectangular cutout.
* ``board-F_Cu.gtl`` — X2 copper with ``TO.C``/``TO.P`` pad attributes.
* ``board-top-pos.gbr`` — X3 component layer (``ComponentMain`` flashes,
  ``CRot``/``CFtp``/``CVal``/``CHgt``).
* ``board-PTH.drl`` / ``board-NPTH.drl`` — Excellon with KiCad ``#@!`` comments.

MCAD, FreeCAD "Export → AutoDesk DXF" style (R2000, outline exploded into
LINE + ARC entities, holes as CIRCLE, 2.5D heights via elevation/thickness),
drawn in its own frame: the board frame mapped through ``drawing_transform``.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf.filemanagement

from pcbsim.registration.transform import Similarity2D

W, H, R = 60.0, 40.0, 1.0
CUTOUT = (28.0, 32.0, 34.0, 36.0)
NPTH = [(3.5, 3.5, 3.2), (56.5, 3.5, 3.2), (56.5, 36.5, 3.2), (3.5, 36.5, 3.2), (21.0, 27.0, 2.0)]
PTH_VIAS = [(9.0 + i, 18.0 + j, 0.3) for i in range(3) for j in range(3)]
PTH_PINS = [(17.5, 32.5, 1.0), (21.5, 32.5, 1.0)]


@dataclass(frozen=True)
class Part:
    ref: str
    x: float
    y: float
    w: float
    h: float
    rot: float
    height: float
    footprint: str
    value: str


PARTS = [
    Part("U1", 45.0, 20.0, 14.0, 14.0, 0.0, 2.0, "BGA-196", "SoC"),
    Part("U2", 11.0, 20.0, 10.0, 10.0, 90.0, 1.5, "QFN-48", "VRM"),
    Part("L1", 19.5, 32.5, 5.0, 5.0, 0.0, 3.0, "IND-5050", "0.47uH"),
    Part("U3", 22.0, 7.0, 4.0, 4.0, 0.0, 1.0, "SOT-23-5", "LDO"),
]


@dataclass
class Defects:
    """Faults injected into the drawing (all mm / degrees)."""

    hole_shift: dict[int, tuple[float, float]] = field(default_factory=dict)
    hole_diameter: dict[int, float] = field(default_factory=dict)
    drop_hole: int | None = None
    extra_hole: tuple[float, float, float] | None = None
    part_shift: dict[str, tuple[float, float]] = field(default_factory=dict)
    part_rot: dict[str, float] = field(default_factory=dict)
    heatsink_height: float = 10.0
    no_cutout: bool = False


def drawing_transform(rot_deg: float = 30.0, mirror: bool = False) -> Similarity2D:
    """Board → drawing frame (mm). The registration must find its inverse."""
    return Similarity2D(math.radians(rot_deg), 120.0, 80.0, 1.0, mirror)


# --------------------------------------------------------------------------- Gerber


def _c(v: float) -> str:
    return str(round(v * 1e6))


def _header(function: str) -> str:
    return (
        "%TF.GenerationSoftware,KiCad,Pcbnew,8.0.5*%\n"
        "%TF.SameCoordinates,Original*%\n"
        f"%TF.FileFunction,{function}*%\n"
        "%FSLAX46Y46*%\nG04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*\n"
        "%MOMM*%\n%LPD*%\nG01*\n"
    )


def gerber_profile() -> str:
    x0, y0, x1, y1 = 0.0, 0.0, W, H
    s = _header("Profile,NP") + "%TA.AperFunction,Profile*%\n%ADD10C,0.050000*%\n%TD*%\nD10*\nG75*\n"
    s += f"X{_c(x0 + R)}Y{_c(y0)}D02*\nG01*\nX{_c(x1 - R)}Y{_c(y0)}D01*\n"
    s += f"G03*\nX{_c(x1)}Y{_c(y0 + R)}I0J{_c(R)}D01*\nG01*\nX{_c(x1)}Y{_c(y1 - R)}D01*\n"
    s += f"G03*\nX{_c(x1 - R)}Y{_c(y1)}I-{_c(R)}J0D01*\nG01*\nX{_c(x0 + R)}Y{_c(y1)}D01*\n"
    s += f"G03*\nX{_c(x0)}Y{_c(y1 - R)}I0J-{_c(R)}D01*\nG01*\nX{_c(x0)}Y{_c(y0 + R)}D01*\n"
    s += f"G03*\nX{_c(x0 + R)}Y{_c(y0)}I{_c(R)}J0D01*\nG01*\n"
    a, b, c, d = CUTOUT
    s += f"X{_c(a)}Y{_c(b)}D02*\nX{_c(c)}Y{_c(b)}D01*\nX{_c(c)}Y{_c(d)}D01*\n"
    s += f"X{_c(a)}Y{_c(d)}D01*\nX{_c(a)}Y{_c(b)}D01*\nM02*\n"
    return s


def gerber_copper() -> str:
    s = _header("Copper,L1,Top") + "%TA.AperFunction,SMDPad,CuDef*%\n%ADD11R,1.000000X1.000000*%\n"
    s += "%TD*%\nD11*\n"
    for p in PARTS:
        for k, dx in enumerate((-p.w / 2 + 0.5, p.w / 2 - 0.5), 1):
            s += f"%TO.P,{p.ref},{k}*%\n%TO.C,{p.ref}*%\nX{_c(p.x + dx)}Y{_c(p.y)}D03*\n%TD*%\n"
    return s + "M02*\n"


def gerber_components() -> str:
    s = _header("Component,L1,Top") + "%TA.AperFunction,ComponentMain*%\n%ADD10C,0.300000*%\n%TD*%\n"
    s += "D10*\n"
    for p in PARTS:
        s += (
            f"%TO.C,{p.ref}*%\n%TO.CFtp,{p.footprint}*%\n%TO.CVal,{p.value}*%\n"
            f"%TO.CMnt,SMD*%\n%TO.CRot,{p.rot:g}*%\n%TO.CHgt,{p.height:g}*%\n"
            f"X{_c(p.x)}Y{_c(p.y)}D03*\n%TD*%\n"
        )
    return s + "M02*\n"


def _excellon(holes: list[tuple[float, float, float]], plated: bool) -> str:
    fn = "Plated,1,4,PTH" if plated else "NonPlated,1,4,NPTH"
    func = "Plated,PTH,ComponentDrill" if plated else "NonPlated,NPTH,ComponentDrill"
    tools = sorted({d for _, _, d in holes})
    s = (
        "M48\n; DRILL file {KiCad 8.0.5} date 2026-10-26\n"
        "; FORMAT={-:-/ absolute / metric / decimal}\n"
        f"; #@! TF.FileFunction,{fn}\nFMAT,2\nMETRIC\n"
    )
    for k, d in enumerate(tools, 1):
        s += f"; #@! TA.AperFunction,{func}\nT{k}C{d:.3f}\n"
    s += "%\nG90\nG05\n"
    for k, d in enumerate(tools, 1):
        s += f"T{k}\n" + "".join(f"X{x:g}Y{y:g}\n" for x, y, dd in holes if dd == d)
    return s + "M30\n"


def write_ecad(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "board-Edge_Cuts.gm1").write_text(gerber_profile())
    (out / "board-F_Cu.gtl").write_text(gerber_copper())
    (out / "board-top-pos.gbr").write_text(gerber_components())
    (out / "board-PTH.drl").write_text(_excellon(PTH_VIAS + PTH_PINS, True))
    (out / "board-NPTH.drl").write_text(_excellon(NPTH, False))
    return out


# --------------------------------------------------------------------------- DXF


def write_dxf(
    path: Path,
    t: Similarity2D | None = None,
    defects: Defects | None = None,
    unit: str = "mm",
    insunits: int | None = None,
) -> Path:
    """FreeCAD-style DXF of the same board in the drawing frame ``t`` (board → drawing)."""
    t = t or drawing_transform()
    df = defects or Defects()
    k = 1.0 / 25.4 if unit == "in" else 1.0
    doc = ezdxf.filemanagement.new("R2000")
    doc.header["$INSUNITS"] = (1 if unit == "in" else 4) if insunits is None else insunits
    msp = doc.modelspace()

    def p(x: float, y: float) -> tuple[float, float]:
        q = t.apply([(x, y)])[0]
        return float(q[0]) * k, float(q[1]) * k

    def ang(a: float) -> float:
        return t.apply_angle(a)

    def line(a: tuple[float, float], b: tuple[float, float], layer: str) -> None:
        msp.add_line(p(*a), p(*b), dxfattribs={"layer": layer})

    def arc(cx: float, cy: float, a0: float, a1: float) -> None:
        s, e = ang(a0), ang(a1)
        if t.mirror:
            s, e = e, s
        msp.add_arc(p(cx, cy), R * k, s, e, dxfattribs={"layer": "OUTLINE"})

    line((R, 0), (W - R, 0), "OUTLINE")
    arc(W - R, R, 270, 360)
    line((W, R), (W, H - R), "OUTLINE")
    arc(W - R, H - R, 0, 90)
    line((W - R, H), (R, H), "OUTLINE")
    arc(R, H - R, 90, 180)
    line((0, H - R), (0, R), "OUTLINE")
    arc(R, R, 180, 270)
    if not df.no_cutout:
        a, b, c, d = CUTOUT
        for u, v in (((a, b), (c, b)), ((c, b), (c, d)), ((c, d), (a, d)), ((a, d), (a, b))):
            line(u, v, "OUTLINE")

    holes = list(NPTH)
    if df.extra_hole is not None:
        holes.append(df.extra_hole)
    for i, (x, y, dia) in enumerate(holes):
        if i == df.drop_hole:
            continue
        sx, sy = df.hole_shift.get(i, (0.0, 0.0))
        dia = df.hole_diameter.get(i, dia)
        msp.add_circle(p(x + sx, y + sy), dia / 2 * k, dxfattribs={"layer": "HOLES"})

    def box3d(
        layer: str, cx: float, cy: float, w: float, h: float, rot: float, z0: float, dz: float
    ) -> None:
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        pts = [
            (cx + c * u - s * v, cy + s * u + c * v)
            for u, v in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
        ]
        pl = msp.add_lwpolyline([p(*q) for q in pts], close=True, dxfattribs={"layer": layer})
        pl.dxf.elevation = z0 * k
        pl.dxf.thickness = dz * k

    for part in PARTS:
        sx, sy = df.part_shift.get(part.ref, (0.0, 0.0))
        rot = part.rot + df.part_rot.get(part.ref, 0.0)
        box3d(f"COMP_{part.ref}", part.x + sx, part.y + sy, part.w, part.h, rot, 0.0, part.height)
    box3d("HS_U1", 45.0, 20.0, 20.0, 20.0, 0.0, 2.0, df.heatsink_height)
    box3d("CHASSIS_BL", 3.0, 3.0, 4.0, 4.0, 0.0, -1.6, 0.0)
    box3d("CHASSIS_TR", 57.0, 37.0, 4.0, 4.0, 0.0, -1.6, 0.0)
    box3d("KEEPOUT_H2", 22.0, 7.0, 8.0, 8.0, 0.0, 0.0, 0.0)
    box3d("CASE_LID", W / 2, H / 2, W + 4.0, H + 4.0, 0.0, 15.0, 2.0)
    msp.add_text("FreeCAD export", dxfattribs={"layer": "NOTES", "height": 2.0})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


LAYER_MAP_YAML = """\
# Layer map for the FreeCAD-style example drawing (examples/mech/mech.dxf)
mech:
  outline: "OUTLINE"
  holes: "HOLES"
  comp_3d: "COMP_(?P<ref>.+)"
  heatsink: "HS_.*"
  keepout: "KEEPOUT_H(?P<h>[0-9.]+)"
  chassis: "CHASSIS.*"
  case: "CASE.*"
ecad:
  ref_holes: npth
  ref_hole_min_diameter: 1.5
registration:
  tol: 0.3
  mirror: auto
  allow_scale: true
checks:
  hole_position_tol: 0.1
  hole_diameter_tol: 0.1
  mech_hole_min_diameter: 1.5
  outline_tol: 0.2
  cutout_tol: 0.2
  component_position_tol: 0.5
  component_rotation_tol: 2.0
  min_clearance: 0.5
heatsinks:
  - { layers: "HS_U1", component: U1, resistance: 6.0 }
chassis: { temperature: 45 }
case: { temperature: 40 }
"""


def write_project(out: Path, **dxf_kw: object) -> tuple[Path, Path, Path]:
    """ECAD dir, DXF path and layer map under ``out``."""
    ecad = write_ecad(out / "gerber")
    dxf = write_dxf(out / "mech.dxf", **dxf_kw)  # type: ignore[arg-type]
    lmap = out / "layers.yaml"
    lmap.write_text(LAYER_MAP_YAML)
    return ecad, dxf, lmap


if __name__ == "__main__":
    write_project(Path(sys.argv[1] if len(sys.argv) > 1 else "examples/mech"))
