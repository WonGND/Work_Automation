"""KiCad ``.kicad_pcb`` import: S-expressions, geometry mapping, overlay config, physics parity."""

from __future__ import annotations

import dataclasses
import io
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from pcbsim.cli import main
from pcbsim.errors import ConfigError
from pcbsim.io import load_config, load_config_dict
from pcbsim.io.config import MeshOptions
from pcbsim.io.kicad import ARC_TOL, _arc_points, read_kicad
from pcbsim.io.sexpr import parse
from pcbsim.model import LayerKind, NetKind, Side
from pcbsim.runner import run_analysis
from tests import kicad_fixtures as kf

ROOT = Path(__file__).resolve().parents[1]
YAML_EXAMPLE = ROOT / "examples" / "soc_4layer.yaml"
MM2 = 1e-6


def _write(tmp_path: Path, text: str, name: str = "b.kicad_pcb") -> Path:
    p = tmp_path / name
    p.write_text(text, "utf-8")
    return p


def _board(*items: str, stackup: bool = True) -> str:
    return "\n".join([kf.header("t", stackup=stackup), *items]) + "\n)\n"


def test_sexpr_parse_quotes_and_nesting() -> None:
    n = parse('(kicad_pcb (version 20240108) (net 1 "A \\"x\\" B") (layers (0 "F.Cu" signal)))')
    assert n.tag == "kicad_pcb"
    assert n.number("version") == 20240108
    net = n.find("net")
    assert net is not None
    assert net.atoms == ["1", 'A "x" B']
    layers = n.find("layers")
    assert layers is not None
    assert layers.children[0].tag == "0"
    assert layers.children[0].atoms == ["F.Cu", "signal"]


@pytest.mark.parametrize(
    ("text", "match"),
    [("(a (b)", "unbalanced"), ("(a))", "unbalanced"), ("", "empty"), ("(a) (b)", "after")],
)
def test_sexpr_errors(text: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        parse(text)


@pytest.mark.parametrize("ccw", [True, False])
def test_arc_points_on_circle_within_tolerance(ccw: bool) -> None:
    r = 5.0
    s, e = (r, 0.0), (0.0, r) if ccw else (0.0, -r)
    m = (r / math.sqrt(2), r / math.sqrt(2) * (1 if ccw else -1))
    pts = np.asarray(_arc_points(s, m, e))
    assert np.allclose(np.hypot(pts[:, 0], pts[:, 1]), r)
    chord = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    sagitta = r - np.sqrt(r * r - (chord / 2) ** 2)
    assert float(np.max(sagitta)) <= ARC_TOL * 1.0001
    assert np.sign(pts[len(pts) // 2, 1]) == (1 if ccw else -1)


@pytest.fixture(scope="module")
def soc_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write(tmp_path_factory.mktemp("k"), kf.soc_board())


def test_example_matches_generator() -> None:
    assert (ROOT / "examples" / "kicad" / "soc_4layer.kicad_pcb").exists()
    kb = read_kicad(ROOT / "examples" / "kicad" / "soc_4layer.kicad_pcb")
    assert kb.counts["vias"] == 68


def test_outline_stackup_and_layer_names(soc_file: Path) -> None:
    kb = read_kicad(soc_file)
    assert kb.outline.bbox() == pytest.approx((0.0, 0.0, 0.06, 0.04), abs=1e-12)
    names = [la.name for la in kb.stackup]
    assert names == [
        "F.Mask",
        "L1_TOP",
        "dielectric 1",
        "L2_GND",
        "dielectric 2",
        "L3_PWR",
        "dielectric 3",
        "L4_BOT",
        "B.Mask",
    ]
    by = {la.name: la for la in kb.stackup}
    assert by["L1_TOP"].kind is LayerKind.CONDUCTOR
    assert by["L1_TOP"].thickness == pytest.approx(34.79e-6)
    assert by["dielectric 2"].thickness == pytest.approx(1.02e-3)
    assert kb.materials["kicad:dielectric 1"] == {"base": "fr4", "eps_r": 4.2, "tan_d": 0.02}
    assert by["F.Mask"].kind is LayerKind.SOLDERMASK
    assert kb.resolve_layer("In2.Cu") == "L3_PWR"
    assert {n.name: n.kind for n in kb.nets}["GND"] is NetKind.GROUND


def test_zones_vias_and_tracks(soc_file: Path) -> None:
    kb = read_kicad(soc_file)
    area: dict[tuple[str, str], float] = {}
    for s in kb.shapes:
        area[(s.layer, s.net)] = area.get((s.layer, s.net), 0.0) + s.polygon.area()
    assert area[("L2_GND", "GND")] == pytest.approx(2400 * MM2, rel=1e-9)
    assert area[("L3_PWR", "VDD_1V0")] == pytest.approx((58 * 38 - 1.5 * 29) * MM2, rel=1e-9)
    w, r = 0.36, 2.0
    assert area[("L1_TOP", "SIG_CLK")] == pytest.approx(
        (4 + 3 + 0.5 * math.pi * r) * w * MM2 + math.pi * (w / 2) ** 2 * MM2, rel=2e-3
    )
    assert kb.min_width["SIG_CLK"] == pytest.approx(0.36e-3)
    blind = [v for v in kb.vias if v.net == "VDD_1V0"]
    assert len(blind) == 50
    assert {(v.from_layer, v.to_layer) for v in blind} == {("L1_TOP", "L3_PWR")}
    thru = [v for v in kb.vias if v.net == "GND"]
    assert {(v.from_layer, v.to_layer) for v in thru} == {("L1_TOP", "L4_BOT")}
    v0 = min(blind, key=lambda v: (v.x, v.y))
    assert (v0.x, v0.y, v0.drill) == pytest.approx((9e-3, 18e-3, 0.3e-3))


def test_footprints(soc_file: Path) -> None:
    fps = read_kicad(soc_file).footprints
    assert fps["U1"].outline.bbox() == pytest.approx((38e-3, 13e-3, 52e-3, 27e-3), abs=1e-9)
    assert fps["U2"].outline.bbox() == pytest.approx((6e-3, 15e-3, 16e-3, 25e-3), abs=1e-9)
    assert fps["U1"].side is Side.TOP
    assert fps["U1"].pad_nets == ("VDD_1V0",)
    assert fps["U1"].value == "SoC"


@pytest.mark.parametrize(
    ("origin", "x0", "y0"), [("board", 0.0, 0.0), ("aux", 0.0, 0.0), ("file", 0.1, -0.09)]
)
def test_origin_modes(soc_file: Path, origin: str, x0: float, y0: float) -> None:
    kb = read_kicad(soc_file, origin=origin)
    bb = kb.outline.bbox()
    assert bb[:2] == pytest.approx((x0, y0), abs=1e-12)
    assert bb[2] - bb[0] == pytest.approx(0.06)


def test_rotated_and_bottom_footprints(tmp_path: Path) -> None:
    rot = kf.Fp("R1", 30, 20, (4, 2), [kf.Pad("1", 2, 0, 1, 1, "GND")], angle=90)
    bot = kf.Fp(
        "B1",
        10,
        10,
        (2, 2),
        [kf.Pad("1", 0, 0, 1, 1, "GND", layers='"B.Cu" "B.Mask"')],
        side="B",
    )
    kb = read_kicad(
        _write(tmp_path, _board(kf.edge_rect(0, 0, 60, 40), kf.footprint(rot), kf.footprint(bot)))
    )
    pad = next(s for s in kb.shapes if s.layer == "L1_TOP" and s.net == "GND")
    cx, cy = pad.polygon.outer.mean(axis=0)
    assert (cx, cy) == pytest.approx((30e-3, 22e-3), abs=1e-9)
    assert kb.footprints["R1"].outline.bbox() == pytest.approx(
        (29e-3, 18e-3, 31e-3, 22e-3), abs=1e-9
    )
    assert kb.footprints["B1"].side is Side.BOTTOM
    assert any(s.layer == "L4_BOT" for s in kb.shapes)


@pytest.mark.parametrize(
    ("shape", "w", "h", "extra", "area"),
    [
        ("rect", 2.0, 1.0, "", 2.0),
        ("circle", 1.0, 1.0, "", math.pi * 0.25),
        ("oval", 3.0, 1.0, "", 2.0 + math.pi * 0.25),
        ("roundrect", 2.0, 1.0, " (roundrect_rratio 0.25)", 2.0 - (4 - math.pi) * 0.25**2),
    ],
)
def test_pad_shapes(
    tmp_path: Path, shape: str, w: float, h: float, extra: str, area: float
) -> None:
    fp = kf.footprint(kf.Fp("P1", 30, 20, (5, 5), [kf.Pad("1", 0, 0, w, h, "GND", shape=shape)]))
    fp = fp.replace(f"(size {w:g} {h:g})", f"(size {w:g} {h:g}){extra}")
    kb = read_kicad(_write(tmp_path, _board(kf.edge_rect(0, 0, 60, 40), fp)))
    (s,) = [s for s in kb.shapes if s.net == "GND"]
    assert s.polygon.area() == pytest.approx(area * MM2, rel=4e-3)


def test_thru_hole_pad_becomes_via(tmp_path: Path) -> None:
    pad = kf.Pad(
        "1",
        0,
        0,
        1.7,
        1.7,
        "GND",
        shape="circle",
        kind="thru_hole",
        drill=1.0,
        layers='"*.Cu" "*.Mask"',
    )
    fp = kf.footprint(kf.Fp("J1", 20, 20, (3, 3), [pad]))
    kb = read_kicad(_write(tmp_path, _board(kf.edge_rect(0, 0, 60, 40), fp)))
    (v,) = kb.vias
    assert (v.x, v.y, v.drill) == pytest.approx((20e-3, 20e-3, 1e-3))
    assert (v.from_layer, v.to_layer) == ("L1_TOP", "L4_BOT")
    assert {s.layer for s in kb.shapes} == {"L1_TOP", "L2_GND", "L3_PWR", "L4_BOT"}
    assert kb.counts["plated_holes"] == 1


def test_edge_cuts_arcs_and_cutout(tmp_path: Path) -> None:
    r = 2.0
    lines = []

    def seg(a: tuple[float, float], b: tuple[float, float]) -> str:
        return (
            f"  (gr_line (start {kf.fx(a[0])} {kf.fy(a[1])}) (end {kf.fx(b[0])} {kf.fy(b[1])}) "
            '(layer "Edge.Cuts") (stroke (width 0.05) (type default)))'
        )

    def arc(a: tuple[float, float], m: tuple[float, float], b: tuple[float, float]) -> str:
        return (
            f"  (gr_arc (start {kf.fx(a[0])} {kf.fy(a[1])}) (mid {kf.fx(m[0])} {kf.fy(m[1])}) "
            f'(end {kf.fx(b[0])} {kf.fy(b[1])}) (layer "Edge.Cuts") (stroke (width 0.05)))'
        )

    k = r * (1 - 1 / math.sqrt(2))
    lines += [seg((r, 0), (60 - r, 0)), arc((60 - r, 0), (60 - k, k), (60, r))]
    lines += [seg((60, r), (60, 40 - r)), arc((60, 40 - r), (60 - k, 40 - k), (60 - r, 40))]
    lines += [seg((60 - r, 40), (r, 40)), arc((r, 40), (k, 40 - k), (0, 40 - r))]
    lines += [seg((0, 40 - r), (0, r)), arc((0, r), (k, k), (r, 0))]
    cut = (
        f"  (gr_rect (start {kf.fx(28)} {kf.fy(36)}) (end {kf.fx(34)} {kf.fy(32)}) "
        '(layer "Edge.Cuts") (stroke (width 0.05)) (fill none))'
    )
    kb = read_kicad(_write(tmp_path, _board(*lines, cut)))
    expected = 60 * 40 - (4 - math.pi) * r * r - 6 * 4
    assert kb.outline.area() == pytest.approx(expected * MM2, rel=1e-5)
    assert len(kb.outline.holes) == 1


def test_unfilled_zone_is_approximated(tmp_path: Path) -> None:
    kb = read_kicad(_write(tmp_path, kf.soc_board(filled=False)))
    assert any("not filled" in n for n in kb.notes)
    area = sum(s.polygon.area() for s in kb.shapes if s.layer == "L2_GND" and s.net == "GND")
    antipads = 50 * math.pi * (0.15 + 0.3) ** 2
    assert area == pytest.approx((2400 - antipads) * MM2, rel=2e-3)
    vdd = sum(s.polygon.area() for s in kb.shapes if s.layer == "L3_PWR")
    assert vdd < (58 * 38 - 1.5 * 29) * MM2


def test_no_stackup_defaults(tmp_path: Path) -> None:
    kb = read_kicad(_write(tmp_path, _board(kf.edge_rect(0, 0, 10, 10), stackup=False)))
    assert any("no stack-up" in n for n in kb.notes)
    cu = [la for la in kb.stackup if la.kind is LayerKind.CONDUCTOR]
    assert len(cu) == 4
    assert sum(la.thickness for la in kb.stackup) == pytest.approx(1.5e-3)


def test_kicad9_net_by_name(tmp_path: Path) -> None:
    text = _board(
        kf.edge_rect(0, 0, 10, 10),
        f"  (segment (start {kf.fx(1)} {kf.fy(5)}) (end {kf.fx(9)} {kf.fy(5)}) (width 1) "
        '(layer "F.Cu") (net "GND"))',
    )
    kb = read_kicad(_write(tmp_path, text))
    assert [s.net for s in kb.shapes] == ["GND"]


def test_bad_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a KiCad board"):
        read_kicad(_write(tmp_path, "(kicad_sch (version 1))"))
    with pytest.raises(ConfigError, match="no closed board outline"):
        read_kicad(_write(tmp_path, _board()))
    with pytest.raises(ConfigError, match="not found"):
        read_kicad(tmp_path / "missing.kicad_pcb")


def _overlay(tmp_path: Path, **patch: Any) -> Path:
    (tmp_path / "soc_4layer.kicad_pcb").write_text(kf.soc_board(), "utf-8")
    d: dict[str, Any] = yaml.safe_load(kf.OVERLAY)
    d["analysis"]["mesh"] = {"cell": 0.5}
    d.update(patch)
    p = tmp_path / "o.yaml"
    p.write_text(yaml.safe_dump(d, sort_keys=False), "utf-8")
    return p


def test_overlay_builds_board(tmp_path: Path) -> None:
    cfg = load_config(_overlay(tmp_path))
    b = cfg.board
    assert cfg.kicad is not None
    assert {n.name: n.nominal_voltage for n in b.nets}["VDD_1V0"] == 1.0
    u1 = next(c for c in b.components if c.ref == "U1")
    assert u1.power == 4.0
    assert u1.footprint.bbox() == pytest.approx((38e-3, 13e-3, 52e-3, 27e-3), abs=1e-9)
    gnd_vias = [v for v in b.vias if v.net == "GND"]
    assert sum(v.filled for v in gnd_vias) == 14
    assert cfg.materials["kicad:dielectric 1"].eps_r == 4.2
    assert cfg.materials["kicad:dielectric 1"].k_through == cfg.materials["fr4"].k_through
    hs = next(t for t in b.thermal_boundaries if t.name == "U1_heatsink")
    assert hs.region.bbox() == u1.footprint.bbox()


def test_overlay_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no footprint 'U9'"):
        load_config(_overlay(tmp_path, components=[{"ref": "U9", "power": 1}]))
    with pytest.raises(ConfigError, match=r"kicad\.nets: not in the KiCad file"):
        load_config(_overlay(tmp_path, kicad={"file": "soc_4layer.kicad_pcb", "nets": ["XX"]}))
    with pytest.raises(ConfigError, match="board needs outline and stackup"):
        load_config_dict({"nets": []})


def test_overlay_net_filter_and_board_override(tmp_path: Path) -> None:
    p = _overlay(
        tmp_path,
        kicad={"file": "soc_4layer.kicad_pcb", "nets": ["VDD_1V0", "GND"], "components": "all"},
        transmission_lines=[],
    )
    cfg = load_config(p)
    assert "SIG_CLK" not in {s.net for s in cfg.board.shapes}
    assert {c.ref for c in cfg.board.components} == {"U1", "U2", "L1", "U3"}


def _results(cfg: Any, solvers: list[str]) -> dict[str, Any]:
    cfg = dataclasses.replace(
        cfg, analysis=dataclasses.replace(cfg.analysis, mesh=MeshOptions(cell=0.5e-3))
    )
    return run_analysis(cfg, solvers).results


def test_kicad_import_reproduces_yaml_model(tmp_path: Path) -> None:
    """Same board via KiCad and via hand-written YAML: identical DC result, Tj within 0.1 K."""
    k = _results(load_config(_overlay(tmp_path)), ["dc_ir", "thermal"])
    y = _results(load_config(YAML_EXAMPLE), ["dc_ir", "thermal"])
    for key in ("SOC_CORE.drop_pct", "joule_power", "VRM_OUT.current"):
        assert k["dc_ir"].scalars[key] == pytest.approx(y["dc_ir"].scalars[key], rel=1e-9)
    for key in ("U1.tj", "U2.tj", "t_max"):
        assert k["thermal"].scalars[key] == pytest.approx(y["thermal"].scalars[key], abs=0.1)


def test_cli_check_and_run(tmp_path: Path) -> None:
    buf = io.StringIO()
    assert main(["check", str(ROOT / "examples" / "kicad" / "soc_4layer.kicad_pcb")], out=buf) == 0
    assert "KiCad   soc_4layer.kicad_pcb: 3 tracks, 68 vias" in buf.getvalue()

    p = _overlay(tmp_path)
    buf = io.StringIO()
    assert main(["check", str(p)], out=buf) == 0
    assert "SIG_CLK" in buf.getvalue()

    buf = io.StringIO()
    code = main(
        ["run", str(p), "--solver", "dc_ir", "--no-plots", "--out", str(tmp_path / "r")], out=buf
    )
    assert code == 0, buf.getvalue()
    assert "SOC_CORE" in buf.getvalue()


def test_thin_track_warning(tmp_path: Path) -> None:
    text = kf.soc_board().replace("(width 0.36)", "(width 0.1)")
    (tmp_path / "soc_4layer.kicad_pcb").write_text(text, "utf-8")
    d: dict[str, Any] = yaml.safe_load(kf.OVERLAY)
    d["ports"].append(
        {
            "name": "CLK",
            "kind": "current_sink",
            "net": "SIG_CLK",
            "layer": "L1_TOP",
            "rect": [35.5, 31, 36.5, 32],
            "current": 0.01,
        }
    )
    d["nets"].append({"name": "SIG_CLK", "kind": "signal"})
    p = tmp_path / "o.yaml"
    p.write_text(yaml.safe_dump(d), "utf-8")
    buf = io.StringIO()
    main(["check", str(p)], out=buf)
    assert "SIG_CLK has 0.100 mm tracks, narrower than the mesh cell" in buf.getvalue()
