from __future__ import annotations

from pathlib import Path

import pytest

from pcbsim.errors import CadFormatError
from pcbsim.io.excellon import load_drills, parse_excellon

KICAD_PTH = """M48
; DRILL file {KiCad 8.0} date 2026-10-26
; FORMAT={-:-/ absolute / metric / decimal}
; #@! TF.FileFunction,Plated,1,4,PTH
FMAT,2
METRIC
; #@! TA.AperFunction,Plated,PTH,ViaDrill
T1C0.300
; #@! TA.AperFunction,Plated,PTH,ComponentDrill
T2C1.000
%
G90
G05
T1
X10.0Y5.0
X12.5Y5.0
T2
X30.0Y20.0
T0
M30
"""

KICAD_NPTH = """M48
; #@! TF.FileFunction,NonPlated,1,4,NPTH
FMAT,2
METRIC
T1C3.200
%
G90
G05
T1
X3.5Y3.5
X56.5Y36.5
T0
M30
"""


def test_kicad_decimal_metric() -> None:
    d = parse_excellon("b-PTH.drl", text=KICAD_PTH)
    assert len(d.holes) == 3
    assert d.holes[0].x == pytest.approx(10e-3)
    assert d.holes[0].diameter == pytest.approx(0.3e-3)
    assert all(h.plated for h in d.holes)
    assert d.unit == "mm"
    n = parse_excellon("b-NPTH.drl", text=KICAD_NPTH)
    assert [h.plated for h in n.holes] == [False, False]
    assert n.holes[1].y == pytest.approx(36.5e-3)


def test_inch_leading_zeros_kept() -> None:
    text = "M48\nINCH,LZ\nT1C0.125\n%\nT1\nX01Y0015\nM30\n"
    (h,) = parse_excellon("x.drl", text=text).holes
    assert h.x == pytest.approx(1.0 * 25.4e-3)
    assert h.y == pytest.approx(0.15 * 25.4e-3)
    assert h.diameter == pytest.approx(0.125 * 25.4e-3)


def test_inch_trailing_zeros_kept() -> None:
    text = "M48\nINCH,TZ\nT1C0.040\n%\nT1\nX10000Y1500\nM30\n"
    (h,) = parse_excellon("x.drl", text=text).holes
    assert h.x == pytest.approx(1.0 * 25.4e-3)
    assert h.y == pytest.approx(0.15 * 25.4e-3)


def test_metric_digit_format() -> None:
    text = "M48\nMETRIC,LZ,000.000\nT1C1.0\n%\nT1\nX012345Y0005\nM30\n"
    (h,) = parse_excellon("x.drl", text=text).holes
    assert h.x == pytest.approx(12.345e-3)
    assert h.y == pytest.approx(0.5e-3)


def test_modal_coordinates() -> None:
    text = "M48\nMETRIC\nT1C1.0\n%\nT1\nX1.0Y2.0\nX3.0\nY4.0\nM30\n"
    holes = parse_excellon("x.drl", text=text).holes
    assert [(h.x, h.y) for h in holes] == pytest.approx([(1e-3, 2e-3), (3e-3, 2e-3), (3e-3, 4e-3)])


def test_g85_slot() -> None:
    text = "M48\nMETRIC\nT1C0.8\n%\nT1\nX1.0Y1.0G85X5.0Y1.0\nM30\n"
    d = parse_excellon("x.drl", text=text)
    assert d.holes == []
    (s,) = d.slots
    assert (s.x0, s.x1, s.diameter) == pytest.approx((1e-3, 5e-3, 0.8e-3))


def test_route_mode_slot() -> None:
    text = "M48\nMETRIC\nT1C1.0\n%\nT1\nG00X1.0Y1.0\nM15\nG01X1.0Y6.0\nM16\nG05\nM30\n"
    d = parse_excellon("NPTH.drl", text=text)
    (s,) = d.slots
    assert (s.y0, s.y1) == pytest.approx((1e-3, 6e-3))
    assert s.plated is False


def test_plating_from_filename_and_override() -> None:
    text = "M48\nMETRIC\nT1C1.0\n%\nT1\nX0Y0\nM30\n"
    assert parse_excellon("board-NPTH.drl", text=text).holes[0].plated is False
    assert parse_excellon("board-PTH.drl", text=text).holes[0].plated is True
    assert parse_excellon("board.drl", text=text).holes[0].plated is None
    assert parse_excellon("board-NPTH.drl", text=text, plated=True).holes[0].plated is True


def test_hit_without_tool_raises() -> None:
    with pytest.raises(CadFormatError, match="tool"):
        parse_excellon("x.drl", text="M48\nMETRIC\n%\nX1.0Y1.0\nM30\n")


def test_load_drills_merges(tmp_path: Path) -> None:
    a = tmp_path / "b-PTH.drl"
    b = tmp_path / "b-NPTH.drl"
    a.write_text(KICAD_PTH)
    b.write_text(KICAD_NPTH)
    d = load_drills([a, b])
    assert len(d.holes) == 5
    assert sum(1 for h in d.holes if h.plated is False) == 2


def test_leading_zero_tool_numbers() -> None:
    text = "M48\nMETRIC\nT01C0.300\nT02C3.000\n%\nT01\nX1.0Y1.0\nT02\nX2.0Y2.0\nT0\nM30\n"
    holes = parse_excellon("x.drl", text=text).holes
    assert [h.diameter for h in holes] == pytest.approx([0.3e-3, 3e-3])
    assert [h.tool for h in holes] == ["T1", "T2"]


def test_tool_select_with_feed_and_speed() -> None:
    text = (
        "M48\nINCH,TZ\nT1C0.0400\nT2C0.1250\n%\n"
        "T1F200S65\nX10000Y10000\nT2F100S40\nX20000Y10000\nM30\n"
    )
    holes = parse_excellon("x.drl", text=text).holes
    assert [h.diameter for h in holes] == pytest.approx([0.04 * 25.4e-3, 0.125 * 25.4e-3])


def test_drill_mode_after_route_g05() -> None:
    text = (
        "M48\nMETRIC\nT1C1.0\nT2C0.5\n%\nT1\nG00X1.0Y1.0\nM15\nG01X5.0Y1.0\nM16\nG05\n"
        "T2\nX10.0Y10.0\nX11.0Y10.0\nM30\n"
    )
    d = parse_excellon("x.drl", text=text)
    assert len(d.slots) == 1
    assert [(h.x, h.diameter) for h in d.holes] == pytest.approx([(10e-3, 0.5e-3), (11e-3, 0.5e-3)])
