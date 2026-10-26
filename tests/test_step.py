"""Tests for the optional STEP reader (pcbsim.io.step)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import Box3D
from pcbsim.io.mech import read_mech
from pcbsim.io.step import boxes_to_drawing, read_step, read_step_boxes, step_available


def test_missing_cadquery_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "cadquery", None)
    assert step_available() is False
    p = tmp_path / "part.step"
    p.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    with pytest.raises(CadFormatError, match=r"pcbsim\[step\]"):
        read_step(p)
    with pytest.raises(CadFormatError, match="cadquery"):
        read_mech(tmp_path / "part.stp")


def test_boxes_to_drawing() -> None:
    b = Box3D("heatsink", 0.0, 0.0, 1.6e-3, 0.02, 0.01, 0.0116)
    d = boxes_to_drawing([b])
    assert d.unit_scale == pytest.approx(1e-3)
    (item,) = d.items
    assert item.layer == "STEP"
    assert item.kind == "STEP"
    assert item.z_base == pytest.approx(1.6e-3)
    assert item.height == pytest.approx(0.01)
    assert item.geometry.area == pytest.approx(2e-4)


@pytest.mark.skipif(not step_available(), reason="cadquery not installed")
def test_real_step_roundtrip(tmp_path: Path) -> None:  # pragma: no cover - optional dep
    import cadquery as cq

    p = tmp_path / "box.step"
    cq.exporters.export(cq.Workplane("XY").box(10, 20, 5, centered=False), str(p))
    (b,) = read_step_boxes(p)
    assert b.xmax - b.xmin == pytest.approx(0.010, abs=1e-6)
    assert b.ymax - b.ymin == pytest.approx(0.020, abs=1e-6)
    assert b.zmax - b.zmin == pytest.approx(0.005, abs=1e-6)
    d = read_mech(p)
    assert len(d.boxes) == 1
