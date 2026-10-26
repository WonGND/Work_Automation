from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from pcbsim.errors import ConfigError
from pcbsim.io import load_config, load_config_dict
from pcbsim.io.config import format_loc
from pcbsim.model import LayerKind, PortKind
from pcbsim.units import OZ_CU

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "soc_4layer.yaml"


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return data


def test_example_loads() -> None:
    cfg = load_config(EXAMPLE)
    b = cfg.board
    assert len(b.stackup.conductor_layers()) == 4
    assert b.stackup.total_thickness == pytest.approx(4 * OZ_CU + 2 * 20e-6 + 0.2e-3 * 2 + 1.02e-3)
    assert b.outline.bbox() == pytest.approx((0, 0, 0.06, 0.04))
    assert b.total_power == pytest.approx(5.0)
    assert {p.kind for p in b.ports} == {PortKind.VOLTAGE_SOURCE, PortKind.CURRENT_SINK}
    sink = next(p for p in b.ports if p.kind is PortKind.CURRENT_SINK)
    assert sink.value == pytest.approx(6.0)
    src = next(p for p in b.ports if p.kind is PortKind.VOLTAGE_SOURCE)
    assert src.value == pytest.approx(1.0)
    assert cfg.source == EXAMPLE
    assert cfg.analysis.mesh.cell == pytest.approx(0.25e-3)
    assert cfg.analysis.output_dir == EXAMPLE.parent / "results"


def test_example_has_power_plane_slot() -> None:
    b = load_config(EXAMPLE).board
    plane = next(s for s in b.shapes if s.name == "vdd_plane")
    assert plane.polygon.area() == pytest.approx(58e-3 * 38e-3 - 1.5e-3 * 29e-3)
    assert not plane.polygon.contains([(25.75e-3, 10e-3)])[0]
    assert plane.polygon.contains([(25.75e-3, 35e-3)])[0]


def test_example_vias_expand_arrays() -> None:
    b = load_config(EXAMPLE).board
    assert len(b.vias) == 25 + 25 + 14 + 4
    gnd = [v for v in b.vias if v.net == "GND" and v.filled]
    assert all(v.from_layer == "L1_TOP" and v.to_layer == "L4_BOT" for v in gnd)
    assert gnd[0].drill == pytest.approx(0.3e-3)


def test_inline_material_override_applied() -> None:
    cfg = load_config(EXAMPLE)
    assert cfg.materials["fr4"].eps_r == pytest.approx(4.2)


def test_tj_max_celsius_to_kelvin() -> None:
    b = load_config(EXAMPLE).board
    u2 = next(c for c in b.components if c.ref == "U2")
    assert u2.tj_max == pytest.approx(125 + 273.15)
    assert b.criteria.tj_max_default == pytest.approx(378.15)


def test_mil_length_unit(raw: dict[str, Any]) -> None:
    raw["units"] = {"length": "mil"}
    raw["board"]["outline"] = {"rect": [0, 0, 2000, 1000]}
    raw["shapes"] = raw["shapes"][:1]
    raw["vias"] = []
    raw["components"] = []
    raw["ports"] = []
    raw["thermal_boundaries"] = []
    cfg = load_config_dict(raw)
    assert cfg.board.outline.bbox()[2] == pytest.approx(2000 * 25.4e-6)
    assert cfg.board.stackup.get("PP1").thickness == pytest.approx(0.2 * 25.4e-6)


def _err(raw: dict[str, Any]) -> str:
    with pytest.raises(ConfigError) as ei:
        load_config_dict(raw)
    return str(ei.value)


def test_bad_unit_reports_path(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][2]["thickness"] = "1.5 mll"
    msg = _err(raw)
    assert "board.stackup[2].thickness" in msg
    assert "mll" in msg


def test_unknown_key_rejected(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][1]["thicknes"] = 1
    assert "board.stackup[1].thicknes" in _err(raw)


def test_negative_thickness(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][2]["thickness"] = -0.1
    assert "board.stackup[2].thickness" in _err(raw)


def test_unknown_material(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][2]["material"] = "unobtainium"
    assert "board.stackup[2].material" in _err(raw)


def test_conductor_with_dielectric_material(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][1]["material"] = "fr4"
    assert "non-conductive" in _err(raw)


def test_unknown_net_reference(raw: dict[str, Any]) -> None:
    raw["shapes"][0]["net"] = "VCC_NOPE"
    assert "unknown net 'VCC_NOPE'" in _err(raw)


def test_shape_on_dielectric_layer(raw: dict[str, Any]) -> None:
    raw["shapes"][0]["layer"] = "CORE"
    assert "not a conductor layer" in _err(raw)


def test_via_outside_board(raw: dict[str, Any]) -> None:
    raw["vias"].append({"net": "GND", "at": [100, 100], "drill": 0.3})
    assert "outside the board outline" in _err(raw)


def test_via_layer_order(raw: dict[str, Any]) -> None:
    raw["vias"][0]["from"], raw["vias"][0]["to"] = "L3_PWR", "L1_TOP"
    assert "from_layer must be above to_layer" in _err(raw)


def test_port_value_kind_mismatch(raw: dict[str, Any]) -> None:
    raw["ports"][1]["voltage"] = 1.0
    assert "current_sink port needs 'current'" in _err(raw)


def test_port_component_reference(raw: dict[str, Any]) -> None:
    p = raw["ports"][1]
    del p["rect"]
    p["component"] = "U1"
    cfg = load_config_dict(raw)
    sink = next(x for x in cfg.board.ports if x.name == "SOC_CORE")
    assert sink.region.area() == pytest.approx(14e-3 * 14e-3)

    p["component"] = "U99"
    assert "unknown component 'U99'" in _err(copy.deepcopy(raw))


def test_geometry_needs_exactly_one_kind(raw: dict[str, Any]) -> None:
    raw["board"]["outline"] = {"rect": [0, 0, 60, 40], "circle": {"center": [0, 0], "r": 1}}
    assert "exactly one of rect / polygon / circle" in _err(raw)


def test_shape_fill_xor_geometry(raw: dict[str, Any]) -> None:
    raw["shapes"][0]["rect"] = [0, 0, 1, 1]
    assert "either a geometry" in _err(raw)


def test_options_for_unlisted_solver(raw: dict[str, Any]) -> None:
    raw["analysis"]["options"]["em_openems"] = {}
    assert "analysis" in _err(raw)


def test_duplicate_layer_names(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][3]["name"] = "L1_TOP"
    with pytest.raises((ConfigError, ValueError)):
        load_config_dict(raw)


def test_multiple_errors_reported_together(raw: dict[str, Any]) -> None:
    raw["board"]["stackup"][2]["thickness"] = "x"
    raw["criteria"]["ir_drop_pct"] = -1
    msg = _err(raw)
    assert "board.stackup[2].thickness" in msg
    assert "criteria.ir_drop_pct" in msg


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/x.yaml")


def test_yaml_syntax_error(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text("board: [unclosed\n")
    with pytest.raises(ConfigError, match="YAML syntax"):
        load_config(f)


def test_material_files_relative_to_config(tmp_path: Path, raw: dict[str, Any]) -> None:
    (tmp_path / "lam.yaml").write_text("materials:\n  mylam: {eps_r: 3.3, k: 0.5}\n")
    raw["material_files"] = ["lam.yaml"]
    raw["board"]["stackup"][4]["material"] = "mylam"
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(raw))
    cfg = load_config(cfg_path)
    assert cfg.board.stackup.get("CORE").material == "mylam"
    assert cfg.materials["mylam"].eps_r == pytest.approx(3.3)
    assert cfg.board.stackup.get("CORE").kind is LayerKind.DIELECTRIC


def test_format_loc() -> None:
    assert format_loc(("board", "stackup", 2, "thickness")) == "board.stackup[2].thickness"
    assert format_loc(()) == "<root>"
