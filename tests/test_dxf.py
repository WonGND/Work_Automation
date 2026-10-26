"""Tests for the DXF reader (pcbsim.io.dxf) and the mech dispatcher."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from ezdxf.document import Drawing
from ezdxf.filemanagement import new as ezdxf_new
from ezdxf.render.mesh import MeshBuilder
from shapely.geometry import LineString, Polygon

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import MechDrawing
from pcbsim.io.dxf import (
    INSUNITS_TO_M,
    UNIT_NAMES_TO_M,
    layer_polygons,
    match_layers,
    outline_with_cutouts,
    read_dxf,
    read_dxf_doc,
)
from pcbsim.io.mech import merge_drawings, read_mech


def _doc(units: int = 4) -> Drawing:
    doc = ezdxf_new("R2010", units=units)
    return doc


def _save(doc: Drawing, tmp_path: Path, name: str = "t.dxf") -> Path:
    p = tmp_path / name
    doc.saveas(p)
    return p


def test_unit_tables() -> None:
    assert INSUNITS_TO_M[1] == pytest.approx(0.0254)
    assert INSUNITS_TO_M[4] == pytest.approx(1e-3)
    assert INSUNITS_TO_M[9] == pytest.approx(25.4e-6)
    assert INSUNITS_TO_M[13] == pytest.approx(1e-6)
    assert INSUNITS_TO_M[21] == pytest.approx(0.3048006096)
    assert set(INSUNITS_TO_M) == set(range(22))
    assert UNIT_NAMES_TO_M["mil"] == pytest.approx(25.4e-6)


def test_insunits_inch_scaling(tmp_path: Path) -> None:
    doc = _doc(units=1)
    doc.modelspace().add_circle((1, 2), 0.5, dxfattribs={"layer": "HOLES"})
    d = read_dxf(_save(doc, tmp_path))
    assert d.insunits == 1
    assert d.unit_scale == pytest.approx(0.0254)
    (c,) = d.circles
    assert c.x == pytest.approx(0.0254)
    assert c.y == pytest.approx(0.0508)
    assert c.diameter == pytest.approx(0.0254)
    assert not d.warnings


def test_circle_gives_circle_and_polygon() -> None:
    doc = _doc()
    doc.modelspace().add_circle((10, 5), 1.6, dxfattribs={"layer": "HOLES"})
    d = read_dxf_doc(doc)
    (c,) = d.circles
    assert c.diameter == pytest.approx(3.2e-3)
    (item,) = d.items
    assert isinstance(item.geometry, Polygon)
    assert item.kind == "CIRCLE"
    assert item.geometry.area == pytest.approx(math.pi * 1.6e-3**2, rel=1e-3)


def test_lwpolyline_bulge_rounded_rectangle() -> None:
    # 10 x 6 mm rectangle with r = 1 mm rounded corners; quarter arcs → bulge tan(90°/4)
    b = math.tan(math.radians(90) / 4)
    w, h, r = 10.0, 6.0, 1.0
    pts = [
        (r, 0, 0),
        (w - r, 0, b),
        (w, r, 0),
        (w, h - r, b),
        (w - r, h, 0),
        (r, h, b),
        (0, h - r, 0),
        (0, r, b),
    ]
    doc = _doc()
    doc.modelspace().add_lwpolyline(pts, format="xyb", close=True, dxfattribs={"layer": "OUT"})
    d = read_dxf_doc(doc)
    (item,) = d.items
    assert isinstance(item.geometry, Polygon)
    expected = (w * h - (4 - math.pi) * r * r) * 1e-6
    assert item.geometry.area == pytest.approx(expected, rel=1e-5)


def test_lines_and_arc_joined_to_chain() -> None:
    # D-shape: 3 lines + 1 line + an arc closing the right side
    doc = _doc()
    msp = doc.modelspace()
    a = {"layer": "Outline"}
    msp.add_line((0, 0), (10, 0), dxfattribs=a)
    msp.add_line((0, 10), (0, 0), dxfattribs=a)
    msp.add_line((10, 10), (0, 10), dxfattribs=a)
    msp.add_line((10, 0), (10, 2), dxfattribs=a)
    # semicircle bulging right from (10, 2) to (10, 10)? use arc centre (10, 6) r 4 from -90..90
    msp.add_arc((10, 6), 4, -90, 90, dxfattribs=a)
    d = read_dxf_doc(doc)
    chains = [i for i in d.items if i.kind == "CHAIN"]
    assert len(chains) == 1
    poly = chains[0].geometry
    assert isinstance(poly, Polygon)
    expected = (100 + math.pi * 16 / 2) * 1e-6
    assert poly.area == pytest.approx(expected, rel=1e-4)
    assert not [i for i in d.items if isinstance(i.geometry, LineString)]


def test_leftover_open_pieces_stay_linestrings() -> None:
    doc = _doc()
    msp = doc.modelspace()
    msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "L"})
    msp.add_line((20, 0), (25, 5), dxfattribs={"layer": "L"})
    d = read_dxf_doc(doc)
    assert len(d.items) == 2
    assert all(isinstance(i.geometry, LineString) for i in d.items)


def test_nested_insert_rotation_scale_mirror() -> None:
    doc = _doc()
    inner = doc.blocks.new("INNER")
    inner.add_circle((1, 0), 0.5, dxfattribs={"layer": "HOLES"})
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", (2, 0), dxfattribs={"rotation": 90})
    msp = doc.modelspace()
    msp.add_blockref(
        "OUTER", (100, 50), dxfattribs={"xscale": -2, "yscale": 2, "zscale": 2, "layer": "X"}
    )
    d = read_dxf_doc(doc)
    (c,) = d.circles
    # INNER at (2,0) rot 90: (1,0) → (0,1) + (2,0) = (2,1); OUTER scale (-2,2): (-4,2) + (100,50)
    assert c.x == pytest.approx(96e-3)
    assert c.y == pytest.approx(52e-3)
    assert c.diameter == pytest.approx(2e-3)
    assert c.layer == "HOLES"


def test_layer_zero_inherits_insert_layer() -> None:
    doc = _doc()
    blk = doc.blocks.new("B")
    blk.add_circle((0, 0), 1, dxfattribs={"layer": "0"})
    blk.add_circle((5, 0), 1, dxfattribs={"layer": "KEEP"})
    doc.modelspace().add_blockref("B", (0, 0), dxfattribs={"layer": "MOUNT"})
    d = read_dxf_doc(doc)
    assert sorted(c.layer for c in d.circles) == ["KEEP", "MOUNT"]


def test_elevation_and_thickness() -> None:
    doc = _doc()
    msp = doc.modelspace()
    pl = msp.add_lwpolyline(
        [(0, 0), (4, 0), (4, 3), (0, 3)], close=True, dxfattribs={"layer": "HS"}
    )
    pl.dxf.elevation = 1.6
    pl.dxf.thickness = 12.0
    msp.add_circle((10, 10, 2.0), 1, dxfattribs={"layer": "NEG", "thickness": -3.0})
    d = read_dxf_doc(doc)
    hs = next(i for i in d.items if i.layer == "HS")
    assert hs.z_base == pytest.approx(1.6e-3)
    assert hs.height == pytest.approx(12e-3)
    assert hs.z_top == pytest.approx(13.6e-3)
    neg = next(i for i in d.items if i.layer == "NEG")
    assert neg.z_base == pytest.approx(-1e-3)
    assert neg.height == pytest.approx(3e-3)


def test_extrusion_minus_z_mirrors_x() -> None:
    doc = _doc()
    doc.modelspace().add_circle((5, 3), 1, dxfattribs={"extrusion": (0, 0, -1)})
    d = read_dxf_doc(doc)
    (c,) = d.circles
    assert c.x == pytest.approx(-5e-3)
    assert c.y == pytest.approx(3e-3)
    (item,) = d.items
    assert item.geometry.centroid.x == pytest.approx(-5e-3, abs=1e-8)


def test_3dface_mesh_and_footprint() -> None:
    doc = _doc()
    msp = doc.modelspace()
    a = {"layer": "BODY"}
    msp.add_3dface([(0, 0, 1), (2, 0, 1), (2, 2, 1), (0, 2, 1)], dxfattribs=a)
    msp.add_3dface([(0, 0, 1), (2, 0, 1), (2, 0, 5), (0, 0, 5)], dxfattribs=a)
    msp.add_3dface([(0, 0, 5), (2, 0, 5), (2, 2, 5), (0, 2, 5)], dxfattribs=a)
    d = read_dxf_doc(doc)
    (mesh,) = d.meshes  # merged per layer
    assert mesh.kind == "3DFACE"
    assert len(mesh.faces) == 3
    assert mesh.z_min == pytest.approx(1e-3)
    assert mesh.z_max == pytest.approx(5e-3)
    (fp,) = [i for i in d.items if i.kind == "3DFACE"]
    assert fp.z_base == pytest.approx(1e-3)
    assert fp.height == pytest.approx(4e-3)
    assert fp.geometry.area == pytest.approx(4e-6)


def test_polyface_mesh() -> None:
    doc = _doc()
    pf = doc.modelspace().add_polyface(dxfattribs={"layer": "PF"})
    pf.append_face([(0, 0, 0), (3, 0, 0), (3, 3, 0), (0, 3, 0)])
    pf.append_face([(0, 0, 0), (3, 0, 0), (3, 0, 7)])
    d = read_dxf_doc(doc)
    (mesh,) = d.meshes
    assert mesh.kind == "POLYFACE"
    assert mesh.z_max == pytest.approx(7e-3)
    (fp,) = [i for i in d.items if i.kind == "POLYFACE"]
    assert fp.height == pytest.approx(7e-3)
    assert fp.geometry.area == pytest.approx(9e-6)


def test_mesh_entity() -> None:
    doc = _doc()
    mb = MeshBuilder()
    mb.add_face([(0, 0, 2), (1, 0, 2), (1, 1, 2), (0, 1, 2)])
    mb.add_face([(0, 0, 4), (1, 0, 4), (1, 1, 4), (0, 1, 4)])
    mb.render_mesh(doc.modelspace(), dxfattribs={"layer": "M"})
    d = read_dxf_doc(doc)
    (mesh,) = d.meshes
    assert mesh.kind == "MESH"
    assert mesh.layer == "M"
    assert mesh.vertices.shape == (8, 3)
    (fp,) = [i for i in d.items if i.kind == "MESH"]
    assert fp.z_base == pytest.approx(2e-3)
    assert fp.height == pytest.approx(2e-3)


def test_3dsolid_warning() -> None:
    doc = _doc()
    doc.modelspace().add_3dsolid(dxfattribs={"layer": "CHASSIS"})
    d = read_dxf_doc(doc)
    assert any("3DSOLID" in w and "STEP" in w and "CHASSIS" in w for w in d.warnings)


def test_ignored_and_unknown_entities() -> None:
    doc = _doc()
    msp = doc.modelspace()
    msp.add_text("hello")
    msp.add_point((1, 1))
    msp.add_xline((0, 0), (1, 0))
    d = read_dxf_doc(doc)
    assert d.items == []
    assert d.warnings == []


def test_no_insunits_warns_and_assumes_mm(tmp_path: Path) -> None:
    doc = _doc(units=0)
    doc.modelspace().add_circle((1, 0), 1)
    d = read_dxf(_save(doc, tmp_path))
    assert d.unit_scale == pytest.approx(1e-3)
    assert "drawing has no $INSUNITS; assuming mm" in d.warnings


def test_unit_override(tmp_path: Path) -> None:
    doc = _doc(units=4)
    doc.modelspace().add_circle((1, 0), 1)
    d = read_dxf(_save(doc, tmp_path), unit_override="inch")
    assert d.unit_scale == pytest.approx(0.0254)
    assert d.circles[0].diameter == pytest.approx(2 * 0.0254)
    with pytest.raises(CadFormatError):
        read_dxf_doc(doc, unit_override="furlong")


def test_solid_and_hatch() -> None:
    doc = _doc()
    msp = doc.modelspace()
    msp.add_solid([(0, 0), (2, 0), (0, 2), (2, 2)], dxfattribs={"layer": "S"})
    hatch = msp.add_hatch(dxfattribs={"layer": "H"})
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    d = read_dxf_doc(doc)
    s = next(i for i in d.items if i.layer == "S")
    assert s.geometry.area == pytest.approx(4e-6)
    h = next(i for i in d.items if i.layer == "H")
    assert h.geometry.area == pytest.approx(100e-6)


def test_outline_with_cutouts_and_match_layers() -> None:
    doc = _doc()
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (50, 0), (50, 30), (0, 30)], close=True, dxfattribs={"layer": "Board_Outline"}
    )
    msp.add_lwpolyline(
        [(10, 10), (20, 10), (20, 20), (10, 20)], close=True, dxfattribs={"layer": "board_cut"}
    )
    # nested inside the cutout → not subtracted again
    msp.add_circle((15, 15), 1, dxfattribs={"layer": "BOARD_CUT"})
    msp.add_circle((40, 15), 2, dxfattribs={"layer": "HOLES"})
    d = read_dxf_doc(doc)
    assert match_layers(d, r"board.*") == ["BOARD_CUT", "Board_Outline", "board_cut"]
    assert match_layers(d, r"holes") == ["HOLES"]
    assert match_layers(d, r"board") == []
    assert len(layer_polygons(d, r"board.*")) == 3
    poly = outline_with_cutouts(d, r"board.*")
    assert poly is not None
    assert len(poly.interiors) == 1
    assert poly.area == pytest.approx((1500 - 100) * 1e-6)
    assert outline_with_cutouts(d, r"nothing") is None


def test_read_mech_dispatch(tmp_path: Path) -> None:
    doc = _doc()
    doc.modelspace().add_circle((0, 0), 1)
    p = _save(doc, tmp_path, "board.DXF")
    d = read_mech(p)
    assert len(d.circles) == 1
    bad = tmp_path / "x.iges"
    bad.write_text("x")
    with pytest.raises(CadFormatError, match="unsupported"):
        read_mech(bad)


def test_merge_drawings() -> None:
    doc = _doc()
    doc.modelspace().add_circle((0, 0), 1)
    a = read_dxf_doc(doc)
    b = MechDrawing(path=None, warnings=["w"])
    m = merge_drawings(a, b)
    assert len(m.circles) == 1
    assert m.warnings == ["w"]


def test_bad_file(tmp_path: Path) -> None:
    p = tmp_path / "bad.dxf"
    p.write_text("this is not a dxf")
    with pytest.raises(CadFormatError):
        read_dxf(p)
    with pytest.raises(CadFormatError):
        read_dxf(tmp_path / "missing.dxf")
