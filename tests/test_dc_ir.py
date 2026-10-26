from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from pcbsim.errors import SolverError
from pcbsim.io import load_config_dict
from pcbsim.io.config import LoadedConfig
from pcbsim.solvers import ResultSet, SolverContext, get_solver
from pcbsim.solvers.dc_ir import DcIrSolver, stiffness

SIGMA = 5.8e7
T_CU = 35e-6
RS = 1.0 / (SIGMA * T_CU)


def _sheet_cfg(
    length: float = 20.0,
    width: float = 5.0,
    port: float = 0.5,
    distribution: str = "equipotential",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "board": {
            "outline": {"rect": [0, 0, length, width]},
            "stackup": [
                {"name": "L1", "kind": "conductor", "thickness": "35 um", "material": "copper"}
            ],
        },
        "nets": [{"name": "N", "kind": "power", "voltage": 1.0}],
        "shapes": [{"net": "N", "layer": "L1", "fill": True}],
        "ports": [
            {
                "name": "SRC",
                "kind": "voltage_source",
                "net": "N",
                "layer": "L1",
                "rect": [0, 0, port, width],
                "voltage": 1.0,
            },
            {
                "name": "LOAD",
                "kind": "current_sink",
                "net": "N",
                "layer": "L1",
                "rect": [length - port, 0, length, width],
                "current": 1.0,
                "distribution": distribution,
            },
        ],
    }
    if extra:
        cfg.update(extra)
    return cfg


def _run(cfg: LoadedConfig, cell: float, **opts: Any) -> ResultSet:
    return DcIrSolver({"cell": cell, **opts}).run(SolverContext(cfg.board, cfg.materials))


def _r_load(rs: ResultSet) -> float:
    return (1.0 - rs.scalars["LOAD.v_avg"]) / 1.0


def test_registered() -> None:
    assert get_solver("dc_ir") is DcIrSolver


@pytest.mark.parametrize("cell_mm", [0.5, 0.25, 0.1])
def test_uniform_sheet_resistance_within_1pct(cell_mm: float) -> None:
    length, width, port = 20.0, 5.0, 0.5
    cfg = load_config_dict(_sheet_cfg(length, width, port))
    rs = _run(cfg, cell_mm * 1e-3)
    r_exact = RS * (length - 2 * port) / width
    assert _r_load(rs) == pytest.approx(r_exact, rel=0.01)
    assert _r_load(rs) == pytest.approx(r_exact, rel=1e-9)


def test_sheet_resistance_square_count_invariant() -> None:
    a = load_config_dict(_sheet_cfg(10.5, 2.5, 0.25))
    b = load_config_dict(_sheet_cfg(40.5, 10.0, 0.25))
    r_a = _r_load(_run(a, 0.25e-3))
    r_b = _r_load(_run(b, 0.25e-3))
    assert r_a == pytest.approx(RS * 4.0, rel=1e-9)
    assert r_b == pytest.approx(RS * 4.0, rel=1e-9)


def test_sheet_voltage_profile_linear() -> None:
    cfg = load_config_dict(_sheet_cfg(20.0, 5.0, 0.5))
    rs = _run(cfg, 0.5e-3)
    v = rs.meta["voltage"][0]
    row = v[v.shape[0] // 2, 1:-1]
    assert np.allclose(np.diff(row), np.diff(row)[0], rtol=1e-9)
    assert np.allclose(v[:, 1:-1], v[0:1, 1:-1], rtol=1e-12)


def test_current_density_uniform_strip() -> None:
    width = 5.0
    cfg = load_config_dict(_sheet_cfg(20.0, width, 0.5))
    rs = _run(cfg, 0.25e-3)
    j = rs.meta["current_density"][0]
    j_exact = 1.0 / (width * 1e-3 * T_CU)
    inner = j[:, 4:-4]
    assert np.allclose(inner, j_exact, rtol=1e-9)


def test_joule_power_equals_i2r_and_energy_balance() -> None:
    cfg = load_config_dict(_sheet_cfg(20.0, 5.0, 0.5))
    rs = _run(cfg, 0.25e-3)
    r = _r_load(rs)
    assert rs.scalars["joule_power"] == pytest.approx(1.0 * 1.0 * r, rel=1e-9)
    src = next(p for p in rs.meta["ports"] if p["name"] == "SRC")
    sink_power = 1.0 * rs.scalars["LOAD.v_avg"]
    assert src["power"] == pytest.approx(rs.scalars["joule_power"] + sink_power, rel=1e-9)
    assert src["current"] == pytest.approx(1.0, rel=1e-9)


def test_uniform_vs_equipotential_sink() -> None:
    eq = _run(load_config_dict(_sheet_cfg(distribution="equipotential")), 0.25e-3)
    un = _run(load_config_dict(_sheet_cfg(distribution="uniform")), 0.25e-3)
    for rs in (eq, un):
        src = next(p for p in rs.meta["ports"] if p["name"] == "SRC")
        assert src["current"] == pytest.approx(1.0, rel=1e-9)
    assert un.scalars["LOAD.v_min"] < eq.scalars["LOAD.v_min"]


def test_uniform_sink_internal_drop_analytic() -> None:
    """Uniform draw over a region of length p: V(x) is parabolic inside it, so
    V_avg − V_min = I·R_s·p / (6·W) in the continuum limit."""
    p_mm, w_mm = 0.5, 5.0
    rs = _run(load_config_dict(_sheet_cfg(20.0, w_mm, p_mm, "uniform")), 0.025e-3)
    dv = rs.scalars["LOAD.v_avg"] - rs.scalars["LOAD.v_min"]
    assert dv == pytest.approx(RS * p_mm / (6.0 * w_mm), rel=0.01)


def test_temperature_scales_resistance() -> None:
    cfg = load_config_dict(_sheet_cfg())
    r20 = _r_load(_run(cfg, 0.5e-3))
    r100 = _r_load(_run(cfg, 0.5e-3, temperature=100.0))
    assert r100 / r20 == pytest.approx(1 + 0.00393 * 80.0, rel=1e-9)


def test_temperature_field_matches_uniform() -> None:
    cfg = load_config_dict(_sheet_cfg())
    a = _run(cfg, 0.5e-3, temperature=75.0)
    grid = a.meta["grid"]
    tf = np.full((1, grid.ny, grid.nx), 75.0 + 273.15)
    b = _run(cfg, 0.5e-3, temperature_field=tf)
    assert _r_load(b) == pytest.approx(_r_load(a), rel=1e-12)
    with pytest.raises(SolverError, match="shape"):
        _run(cfg, 0.5e-3, temperature_field=np.zeros((2, 2, 2)))


def test_cg_matches_direct() -> None:
    cfg = load_config_dict(_sheet_cfg())
    d = _run(cfg, 0.25e-3, method="direct")
    c = _run(cfg, 0.25e-3, method="cg", cg_rtol=1e-12)
    assert _r_load(c) == pytest.approx(_r_load(d), rel=1e-6)


def test_bad_options() -> None:
    cfg = load_config_dict(_sheet_cfg())
    with pytest.raises(SolverError, match="method"):
        _run(cfg, 0.5e-3, method="magic")
    with pytest.raises(SolverError, match="bogus"):
        _run(cfg, 0.5e-3, bogus=1)


def test_stiffness_is_symmetric_with_zero_row_sums() -> None:
    cfg = load_config_dict(_sheet_cfg(10.0, 4.0, 1.0))
    solver = DcIrSolver({"cell": 1e-3})
    solver.setup(SolverContext(cfg.board, cfg.materials))
    solver.assemble()
    k = stiffness(solver.system)
    assert abs(k - k.T).max() < 1e-9 * abs(k).max()
    assert np.allclose(np.asarray(k.sum(axis=1)).ravel(), 0.0, atol=1e-6 * abs(k).max())


def _hole_cfg() -> dict[str, Any]:
    cfg = _sheet_cfg(20.0, 10.0, 1.0)
    cfg["shapes"] = [
        {
            "net": "N",
            "layer": "L1",
            "rect": [0, 0, 20, 10],
            "holes": [{"circle": {"center": [10, 5], "r": 3, "segments": 128}}],
        }
    ]
    return cfg


def test_mesh_convergence_plate_with_hole() -> None:
    cfg = load_config_dict(_hole_cfg())
    cells = [0.5e-3, 0.25e-3, 0.125e-3, 0.0625e-3]
    r = [_r_load(_run(cfg, h)) for h in cells]
    d = [abs(r[i + 1] - r[i]) for i in range(len(r) - 1)]
    assert d[1] < d[0]
    assert d[2] < d[1]
    r_no_hole = RS * 18.0 / 10.0
    assert all(x > r_no_hole for x in r)
    assert abs(r[-1] - r[-2]) / r[-1] < 0.01


def _two_layer_cfg(drill: float = 0.3, n_vias: int = 1) -> dict[str, Any]:
    vias = [
        {"net": "N", "at": [10.0, 1.0 + 1.0 * k], "drill": drill, "material": "copper"}
        for k in range(n_vias)
    ]
    return {
        "board": {
            "outline": {"rect": [0, 0, 20, 10]},
            "stackup": [
                {"name": "L1", "kind": "conductor", "thickness": "35 um", "material": "copper"},
                {"name": "D", "kind": "dielectric", "thickness": 1.0, "material": "fr4"},
                {"name": "L2", "kind": "conductor", "thickness": "35 um", "material": "copper"},
            ],
        },
        "nets": [{"name": "N", "kind": "power", "voltage": 1.0}],
        "shapes": [
            {"net": "N", "layer": "L1", "rect": [0, 0, 10.5, 10]},
            {"net": "N", "layer": "L2", "rect": [9.5, 0, 20, 10]},
        ],
        "vias": vias,
        "ports": [
            {
                "name": "SRC",
                "kind": "voltage_source",
                "net": "N",
                "layer": "L1",
                "rect": [0, 0, 0.5, 10],
                "voltage": 1.0,
            },
            {
                "name": "LOAD",
                "kind": "current_sink",
                "net": "N",
                "layer": "L2",
                "rect": [19.5, 0, 20, 10],
                "current": 1.0,
                "distribution": "equipotential",
            },
        ],
    }


def _with_via_material(d: dict[str, Any], sigma: float) -> dict[str, Any]:
    d["materials"] = {"via_cu": {"sigma": sigma, "k": 390.0}}
    for v in d["vias"]:
        v["material"] = "via_cu"
    return d


def test_via_resistance_is_rho_l_over_a() -> None:
    """A single via is a series element: ΔR(σ_barrel → ∞) isolates exactly ρL/A."""
    normal = load_config_dict(_with_via_material(_two_layer_cfg(n_vias=1), SIGMA))
    ideal = load_config_dict(_with_via_material(_two_layer_cfg(n_vias=1), SIGMA * 1e6))
    v = normal.board.vias[0]
    span = normal.board.stackup.span("L1", "L2")
    assert span == pytest.approx(1.035e-3)
    r_via = (1.0 / SIGMA) * span / v.barrel_area
    assert r_via == pytest.approx(
        (1 / SIGMA) * 1.035e-3 / (math.pi / 4 * (0.3e-3**2 - 0.25e-3**2)), rel=1e-12
    )
    rs = _run(normal, 0.25e-3)
    dr = _r_load(rs) - _r_load(_run(ideal, 0.25e-3))
    assert dr == pytest.approx(r_via * (1 - 1e-6), rel=1e-6)
    assert rs.scalars["via.i_max"] == pytest.approx(1.0, rel=1e-9)


def test_parallel_vias_reduce_resistance() -> None:
    r = {}
    for n in (1, 2, 4):
        r[n] = _r_load(_run(load_config_dict(_two_layer_cfg(n_vias=n)), 0.25e-3))
    assert r[1] > r[2] > r[4]
    rs4 = _run(load_config_dict(_two_layer_cfg(n_vias=4)), 0.25e-3)
    currents = [row["current"] for row in rs4.meta["vias"]]
    assert sum(currents) == pytest.approx(1.0, rel=1e-9)
    assert max(currents) < 0.5


def test_via_series_two_strips_analytic() -> None:
    cfg_dict = _two_layer_cfg()
    cfg_dict["board"]["outline"] = {"rect": [0, 0, 20, 1]}
    cfg_dict["shapes"] = [
        {"net": "N", "layer": "L1", "rect": [0, 0, 10.5, 1]},
        {"net": "N", "layer": "L2", "rect": [9.5, 0, 20, 1]},
    ]
    cfg_dict["vias"] = [{"net": "N", "at": [10.0, 0.5], "drill": 0.3, "material": "copper"}]
    cfg_dict["ports"][0]["rect"] = [0, 0, 0.5, 1]
    cfg_dict["ports"][1]["rect"] = [19.5, 0, 20, 1]
    cfg = load_config_dict(cfg_dict)
    cell = 0.0625e-3
    rs = _run(cfg, cell)
    v = cfg.board.vias[0]
    r_via = (1.0 / SIGMA) * 1.035e-3 / v.barrel_area
    r_strip_1 = RS * (10.0 - 0.5) / 1.0
    r_strip_2 = RS * (19.5 - 10.0) / 1.0
    r_spread = 2 * RS * (1.0 / math.pi) * math.log(1.0 / (cell * 1e3 * math.pi / 2))
    r_expected = r_strip_1 + r_strip_2 + r_via
    assert _r_load(rs) == pytest.approx(r_expected, rel=0.02, abs=abs(r_spread) * 0.5)


def test_via_without_copper_ignored_with_warning() -> None:
    d = _two_layer_cfg()
    d["vias"].append({"net": "N", "at": [2.0, 2.0], "drill": 0.3})
    rs = _run(load_config_dict(d), 0.5e-3)
    assert any("ignored" in w for w in rs.meta["warnings"])


def _return_path_cfg() -> dict[str, Any]:
    return {
        "board": {
            "outline": {"rect": [0, 0, 20.5, 5]},
            "stackup": [
                {"name": "L1", "kind": "conductor", "thickness": "35 um", "material": "copper"},
                {"name": "D", "kind": "dielectric", "thickness": 0.2, "material": "fr4"},
                {"name": "L2", "kind": "conductor", "thickness": "17.5 um", "material": "copper"},
            ],
        },
        "nets": [
            {"name": "VDD", "kind": "power", "voltage": 1.0},
            {"name": "GND", "kind": "ground"},
        ],
        "shapes": [
            {"net": "VDD", "layer": "L1", "fill": True},
            {"net": "GND", "layer": "L2", "fill": True},
        ],
        "ports": [
            {
                "name": "VRM",
                "kind": "voltage_source",
                "net": "VDD",
                "layer": "L1",
                "rect": [0, 0, 0.25, 5],
                "voltage": 1.0,
                "reference_net": "GND",
            },
            {
                "name": "LOAD",
                "kind": "current_sink",
                "net": "VDD",
                "layer": "L1",
                "rect": [20.25, 0, 20.5, 5],
                "current": 2.0,
                "reference_net": "GND",
                "distribution": "equipotential",
            },
        ],
    }


def test_return_path_adds_ground_resistance() -> None:
    cfg = load_config_dict(_return_path_cfg())
    rs = _run(cfg, 0.25e-3)
    r_pwr = RS * 20.0 / 5.0
    r_gnd = (1 / (SIGMA * 17.5e-6)) * 20.0 / 5.0
    load = next(p for p in rs.meta["ports"] if p["name"] == "LOAD")
    assert load["reference_layer"] == "L2"
    assert load["drop_v"] == pytest.approx(2.0 * (r_pwr + r_gnd), rel=1e-6)
    assert rs.scalars["GND.v_max"] == pytest.approx(2.0 * r_gnd, rel=1e-6)
    assert rs.scalars["GND.v_min"] == pytest.approx(0.0, abs=1e-12)


def test_ir_drop_violation_reported() -> None:
    d = _return_path_cfg()
    d["ports"][1]["current"] = 60.0
    d["ports"][1]["distribution"] = "uniform"
    d["ports"][1]["rect"] = [19.5, 0, 20.5, 5]
    d["criteria"] = {"current_density": "none"}
    rs = _run(load_config_dict(d), 0.25e-3)
    assert not rs.passed
    v = next(v for v in rs.violations if v.check == "ir_drop")
    assert v.subject == "LOAD"
    assert v.value > 3.0
    assert v.location is not None
    assert v.location[0] == pytest.approx(20.375e-3)


def test_phase_order_enforced() -> None:
    cfg = load_config_dict(_sheet_cfg())
    s = DcIrSolver({"cell": 1e-3})
    s.setup(SolverContext(cfg.board, cfg.materials))
    with pytest.raises(SolverError, match="call order"):
        s.solve()


def test_current_density_violation_and_override() -> None:
    d = _sheet_cfg()
    d["criteria"] = {"current_density_limit": "1 A/mm2"}
    rs = _run(load_config_dict(d), 0.5e-3)
    v = next(v for v in rs.violations if v.check == "current_density")
    assert v.limit == pytest.approx(1.0)
    assert v.value == pytest.approx(1.0 / (5.0 * 0.035), rel=1e-6)
    d["criteria"] = {"current_density": "none"}
    rs = _run(load_config_dict(d), 0.5e-3)
    assert not any(v.check == "current_density" for v in rs.violations)


def test_sink_without_source_errors() -> None:
    d = _sheet_cfg()
    d["shapes"] = [
        {"net": "N", "layer": "L1", "rect": [0, 0, 9, 5]},
        {"net": "N", "layer": "L1", "rect": [11, 0, 20, 5]},
    ]
    with pytest.raises(SolverError, match="LOAD"):
        _run(load_config_dict(d), 0.5e-3)


def test_floating_island_is_warning() -> None:
    d = _sheet_cfg()
    d["shapes"].append({"net": "N", "layer": "L1", "rect": [8, 1, 9, 2]})
    d["shapes"][0] = {"net": "N", "layer": "L1", "rect": [0, 3, 20, 5]}
    d["ports"][0]["rect"] = [0, 3, 0.5, 5]
    d["ports"][1]["rect"] = [19.5, 3, 20, 5]
    rs = _run(load_config_dict(d), 0.5e-3)
    assert any("floating" in w for w in rs.meta["warnings"])


def test_port_without_copper_errors() -> None:
    d = _sheet_cfg()
    d["shapes"] = [{"net": "N", "layer": "L1", "rect": [1, 0, 19, 5]}]
    with pytest.raises(SolverError, match="no N copper"):
        _run(load_config_dict(d), 0.5e-3)


def test_shorted_sources_error() -> None:
    d = _sheet_cfg()
    d["ports"][1] = {
        "name": "SRC2",
        "kind": "voltage_source",
        "net": "N",
        "layer": "L1",
        "rect": [19.5, 0, 20, 5],
        "voltage": 1.0,
    }
    d["ports"].append(
        {
            "name": "SRC3",
            "kind": "voltage_source",
            "net": "N",
            "layer": "L1",
            "rect": [19.5, 0, 20, 5],
            "voltage": 0.9,
        }
    )
    with pytest.raises(SolverError, match=r"overlap|shorted"):
        _run(load_config_dict(d), 0.5e-3)


def test_two_sources_share_load() -> None:
    d = _sheet_cfg(20.0, 5.0, 0.5)
    d["ports"][1]["rect"] = [9.75, 0, 10.25, 5]
    d["ports"].append(
        {
            "name": "SRC_R",
            "kind": "voltage_source",
            "net": "N",
            "layer": "L1",
            "rect": [19.5, 0, 20, 5],
            "voltage": 1.0,
        }
    )
    rs = _run(load_config_dict(d), 0.25e-3)
    cur = {p["name"]: p["current"] for p in rs.meta["ports"] if p["kind"] == "voltage_source"}
    assert cur["SRC"] == pytest.approx(0.5, rel=1e-9)
    assert cur["SRC_R"] == pytest.approx(0.5, rel=1e-9)


def test_short_between_nets_on_same_layer() -> None:
    d = _sheet_cfg()
    d["nets"].append({"name": "G", "kind": "ground"})
    d["shapes"].append({"net": "G", "layer": "L1", "rect": [5, 0, 6, 5]})
    with pytest.raises(SolverError, match="short circuit"):
        _run(load_config_dict(d), 0.5e-3)


def test_fields_exported_per_layer() -> None:
    cfg = load_config_dict(_two_layer_cfg())
    rs = _run(cfg, 0.5e-3)
    names = {(f.name, f.layer) for f in rs.fields}
    for layer in ("L1", "L2"):
        assert ("voltage", layer) in names
        assert ("current_density", layer) in names
    grid = rs.meta["grid"]
    assert all(f.values.shape == grid.shape for f in rs.fields)
