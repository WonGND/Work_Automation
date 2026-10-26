from __future__ import annotations

import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from pcbsim.errors import CadFormatError
from pcbsim.io.gerber import (
    component_centroids,
    eval_expr,
    find_layer,
    guess_function,
    load_gerber_dir,
    outline_polygons,
    parse_gerber,
)

MM = 1e-3
HDR = "%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\n"


def _g(body: str, name: str = "t.gbr", hdr: str = HDR) -> str:
    return hdr + body + "\nM02*\n"


def _area(text: str, name: str = "t.gbr") -> float:
    layer = parse_gerber(name, text=text)
    assert layer.geometry is not None
    return float(layer.geometry.area)


def test_circle_flash_area_mm_and_inch() -> None:
    a = _area(_g("%ADD10C,2.0*%\nD10*\nX1000000Y1000000D03*"))
    assert a == pytest.approx(math.pi * 1e-6, rel=2e-3)
    inch = "%FSLAX24Y24*%\n%MOIN*%\n"
    a_in = _area(_g("%ADD10C,0.1*%\nD10*\nX10000Y10000D03*", hdr=inch))
    assert a_in == pytest.approx(math.pi * (0.05 * 25.4e-3) ** 2, rel=2e-3)
    layer = parse_gerber("t.gbr", text=_g("%ADD10C,0.1*%\nD10*\nX10000Y20000D03*", hdr=inch))
    assert layer.flashes[0].x == pytest.approx(25.4e-3)
    assert layer.flashes[0].y == pytest.approx(2 * 25.4e-3)


def test_standard_apertures() -> None:
    assert _area(_g("%ADD11R,2X1*%\nD11*\nX0Y0D03*")) == pytest.approx(2e-6)
    obround = math.pi * 0.5e-3**2 + 1e-3 * 1e-3
    assert _area(_g("%ADD12O,2X1*%\nD12*\nX0Y0D03*")) == pytest.approx(obround, rel=2e-3)
    hexagon = 1.5 * math.sqrt(3) * 1e-3**2
    assert _area(_g("%ADD13P,2X6*%\nD13*\nX0Y0D03*")) == pytest.approx(hexagon, rel=1e-9)
    holed = 4e-6 - math.pi * 0.5e-3**2
    assert _area(_g("%ADD14R,2X2X1*%\nD14*\nX0Y0D03*")) == pytest.approx(holed, rel=2e-3)


def test_stroke_circle_and_rect() -> None:
    stroke = 10e-3 * 1e-3 + math.pi * 0.5e-3**2
    a = _area(_g("%ADD10C,1*%\nD10*\nX0Y0D02*\nG01*\nX10000000Y0D01*"))
    assert a == pytest.approx(stroke, rel=2e-3)
    a = _area(_g("%ADD11R,1X1*%\nD11*\nX0Y0D02*\nX10000000Y0D01*"))
    assert a == pytest.approx(11e-3 * 1e-3, rel=1e-9)


def test_region_with_arc_corner() -> None:
    body = (
        "G75*\nG36*\nX0Y0D02*\nG01*\nX10000000Y0D01*\nX10000000Y8000000D01*\n"
        "G03*\nX8000000Y10000000I-2000000J0D01*\nG01*\nX0Y10000000D01*\nX0Y0D01*\nG37*"
    )
    expected = 100e-6 - (4e-6 - math.pi * 4e-6 / 4)
    assert _area(_g(body)) == pytest.approx(expected, rel=2e-3)


def test_region_two_contours_even_odd() -> None:
    body = (
        "G36*\nX0Y0D02*\nG01*\nX10000000Y0D01*\nX10000000Y10000000D01*\nX0Y10000000D01*\n"
        "X0Y0D01*\nX2000000Y2000000D02*\nX4000000Y2000000D01*\nX4000000Y4000000D01*\n"
        "X2000000Y4000000D01*\nX2000000Y2000000D01*\nG37*"
    )
    assert _area(_g(body)) == pytest.approx(96e-6)


def test_g75_full_circle_stroke() -> None:
    body = "%ADD10C,0.2*%\nD10*\nG75*\nX5000000Y0D02*\nG02*\nX5000000Y0I-5000000J0D01*"
    layer = parse_gerber("t.gbr", text=_g(body))
    assert layer.geometry is not None
    ring = math.pi * ((5.1e-3) ** 2 - (4.9e-3) ** 2)
    assert layer.geometry.area == pytest.approx(ring, rel=2e-3)
    assert layer.paths[0].length == pytest.approx(2 * math.pi * 5e-3, rel=2e-3)


def test_g74_single_quadrant_arc() -> None:
    body = "%ADD10C,0.1*%\nD10*\nG74*\nX5000000Y0D02*\nG03*\nX0Y5000000I5000000J0D01*"
    layer = parse_gerber("t.gbr", text=_g(body))
    assert layer.paths[0].length == pytest.approx(math.pi / 2 * 5e-3, rel=2e-3)
    assert any("G74" in w for w in layer.warnings)


def test_polarity_clear() -> None:
    body = "%ADD10R,10X10*%\n%ADD11C,4*%\nD10*\nX0Y0D03*\n%LPC*%\nD11*\nX0Y0D03*\n%LPD*%"
    expected = 100e-6 - math.pi * 4e-6
    assert _area(_g(body)) == pytest.approx(expected, rel=2e-3)


def test_polarity_order_matters() -> None:
    body = "%ADD10R,10X10*%\n%ADD11C,4*%\n%LPC*%\nD11*\nX0Y0D03*\n%LPD*%\nD10*\nX0Y0D03*"
    assert _area(_g(body)) == pytest.approx(100e-6)


def test_aperture_macro() -> None:
    macro = (
        "%AMTEST*\n0 comment*\n$3=$1x2*\n1,1,$3,0,0*\n"
        "4,1,4,3,-0.5,4,-0.5,4,0.5,3,0.5,3,-0.5,0*\n"
        "20,1,0.2,-5,0,-3,0,0*\n1,0,1,0,0*%\n"
    )
    body = macro + "%ADD20TEST,1.0*%\nD20*\nX0Y0D03*"
    expected = math.pi * 1e-6 - math.pi * 0.25e-6 + 1e-6 + 2e-3 * 0.2e-3
    assert _area(_g(body)) == pytest.approx(expected, rel=1e-3)


def test_macro_rotation_and_polygon() -> None:
    macro = "%AMROT*\n21,1,4,1,0,0,90*%\n"
    layer = parse_gerber("t.gbr", text=_g(macro + "%ADD20ROT*%\nD20*\nX0Y0D03*"))
    assert layer.geometry is not None
    minx, miny, maxx, maxy = layer.geometry.bounds
    assert maxx - minx == pytest.approx(1e-3)
    assert maxy - miny == pytest.approx(4e-3)


def test_eval_expr() -> None:
    assert eval_expr("1+2x3", {}) == 7
    assert eval_expr("(1+2)x3", {}) == 9
    assert eval_expr("-$1/2", {1: 3.0}) == -1.5
    assert eval_expr("$1X$2-1", {1: 2.0, 2: 4.0}) == 7


def test_step_repeat() -> None:
    body = "%SRX3Y2I5.0J5.0*%\n%ADD10R,1X1*%\nD10*\nX0Y0D03*\n%SR*%"
    layer = parse_gerber("t.gbr", text=_g(body))
    assert len(layer.flashes) == 6
    assert layer.geometry is not None
    assert layer.geometry.area == pytest.approx(6e-6)


def test_block_aperture() -> None:
    body = "%ADD10C,1*%\n%ABD20*%\nD10*\nX0Y0D03*\nX2000000Y0D03*\n%AB*%\nD20*\nX10000000Y0D03*"
    layer = parse_gerber("t.gbr", text=_g(body))
    assert layer.geometry is not None
    assert layer.geometry.area == pytest.approx(2 * math.pi * 0.25e-6, rel=2e-3)
    assert layer.geometry.bounds[0] == pytest.approx(9.5e-3)


def test_x2_file_function_and_side() -> None:
    layer = parse_gerber("x.gbr", text=_g("", hdr="%TF.FileFunction,Copper,L4,Bot*%\n" + HDR))
    assert layer.function == ("Copper", "L4", "Bot")
    assert layer.side == "bottom"
    assert layer.file_attributes["FileFunction"] == ("Copper", "L4", "Bot")


def test_x3_component_layer() -> None:
    body = (
        "%TF.FileFunction,Component,L1,Top*%\n" + HDR + "%TA.AperFunction,ComponentMain*%\n"
        "%ADD10C,0.3*%\n%TA.AperFunction,ComponentPin*%\n%ADD11P,0.36X4X0.0*%\n%TD*%\n"
        "%TO.C,U1*%\n%TO.CRot,90*%\n%TO.CFtp,QFN-32*%\n%TO.CVal,MCU*%\n%TO.CHgt,1.2*%\n"
        "D10*\nX45000000Y20000000D03*\nD11*\nX44000000Y20000000D03*\n%TD*%\n"
        "%TO.C,R1*%\nD10*\nX10000000Y5000000D03*\n%TD*%\nM02*\n"
    )
    layer = parse_gerber("c.gbr", text=body)
    assert layer.kind == "Component"
    assert [c.ref for c in layer.components] == ["U1", "R1"]
    u1 = layer.components[0]
    assert (u1.x, u1.y) == pytest.approx((45e-3, 20e-3))
    assert u1.rotation == 90.0
    assert u1.height == pytest.approx(1.2e-3)
    assert u1.footprint == "QFN-32"
    assert u1.side == "top"
    assert layer.components[1].height is None


def test_to_c_on_copper_pads() -> None:
    body = (
        "%TF.FileFunction,Copper,L1,Top*%\n" + HDR + "%ADD10R,1X1*%\nD10*\n"
        "%TO.C,R5*%\n%TO.P,R5,1*%\nX0Y0D03*\n%TO.P,R5,2*%\nX2000000Y0D03*\n%TD*%\n"
        "X9000000Y9000000D03*\nM02*\n"
    )
    layer = parse_gerber("cu.gbr", text=body)
    assert component_centroids(layer) == {"R5": pytest.approx((1e-3, 0.0))}
    assert layer.flashes[-1].attributes == {}


def test_profile_outline_with_cutout() -> None:
    body = (
        "%TF.FileFunction,Profile,NP*%\n" + HDR + "%ADD10C,0.1*%\nD10*\nG75*\nG01*\n"
        "X0Y0D02*\nX60000000Y0D01*\nX60000000Y40000000D01*\nX0Y40000000D01*\nX0Y0D01*\n"
        "X33000000Y20000000D02*\nG03*\nX33000000Y20000000I-3000000J0D01*\n"
    )
    layer = parse_gerber("p.gbr", text=_g(body, hdr=""))
    (board,) = outline_polygons(layer)
    assert isinstance(board, Polygon)
    assert len(board.interiors) == 1
    assert board.area == pytest.approx(2400e-6 - math.pi * 9e-6, rel=2e-3)
    assert board.bounds == pytest.approx((0, 0, 60e-3, 40e-3))


def test_incremental_notation() -> None:
    hdr = "%FSLIX46Y46*%\n%MOMM*%\n"
    layer = parse_gerber(
        "t.gbr", text=_g("%ADD10C,1*%\nD10*\nX1000000Y0D03*\nX1000000Y0D03*", hdr=hdr)
    )
    assert [f.x for f in layer.flashes] == pytest.approx([1e-3, 2e-3])


def test_malformed_raises() -> None:
    with pytest.raises(CadFormatError, match="before %FS"):
        parse_gerber("t.gbr", text="%MOMM*%\nX0Y0D03*\nM02*")
    with pytest.raises(CadFormatError, match="not defined"):
        parse_gerber("t.gbr", text=_g("D33*\nX0Y0D03*"))


def test_unknown_command_warns() -> None:
    layer = parse_gerber("t.gbr", text=_g("%XYZ1*%\nG99*"))
    assert len(layer.warnings) == 2


def test_guess_function() -> None:
    assert guess_function("board-Edge_Cuts.gm1")[0] == ("Profile", "NP")
    assert guess_function("board-F_Cu.gtl") == (("Copper", "L1", "Top"), "top")
    assert guess_function("board.gbl")[1] == "bottom"
    assert guess_function("board-In1_Cu.g2")[0][0] == "Copper"
    assert guess_function("readme.txt") == ((), None)


def test_load_dir_and_find(tmp_path: Path) -> None:
    (tmp_path / "b-Edge_Cuts.gm1").write_text(_g("%ADD10C,0.1*%\nD10*\nX0Y0D02*\nX1000000Y0D01*"))
    (tmp_path / "b-F_Cu.gtl").write_text(_g(""))
    (tmp_path / "b.drl").write_text("M48\n%\nM30\n")
    layers = load_gerber_dir(tmp_path)
    assert len(layers) == 2
    prof = find_layer(layers, "profile")
    assert prof is not None
    assert prof.path is not None
    assert prof.path.name == "b-Edge_Cuts.gm1"
    assert find_layer(layers, "Copper", "top") is not None
    assert find_layer(layers, "Copper", "bottom") is None
