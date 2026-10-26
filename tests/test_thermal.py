from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from pcbsim.errors import SolverError
from pcbsim.io import load_config_dict
from pcbsim.io.config import LoadedConfig
from pcbsim.solvers import ResultSet, SolverContext, get_solver
from pcbsim.solvers.thermal import ThermalSolver

K_CU = 398.0
T0 = 273.15


def _run(cfg: LoadedConfig, cell: float, **opts: Any) -> ResultSet:
    return ThermalSolver({"cell": cell, **opts}).run(SolverContext(cfg.board, cfg.materials))


def _fin_cfg(length: float = 45.0, width: float = 2.0, t: float = 1.0) -> dict[str, Any]:
    return {
        "board": {
            "outline": {"rect": [0, 0, length, width]},
            "stackup": [{"name": "P", "kind": "conductor", "thickness": t, "material": "copper"}],
        },
        "nets": [{"name": "N"}],
        "shapes": [{"net": "N", "layer": "P", "fill": True}],
        "thermal_boundaries": [
            {
                "name": "base",
                "kind": "fixed_temperature",
                "side": "top",
                "rect": [0, 0, 1, width],
                "temperature": 125,
            }
        ],
    }


def test_registered() -> None:
    assert get_solver("thermal") is ThermalSolver


@pytest.mark.parametrize("cell_mm", [1.0, 0.5, 0.25])
def test_fin_matches_analytic_within_2pct(cell_mm: float) -> None:
    """Convecting fin, clamped base, adiabatic tip:
    θ(x)/θ_b = cosh(m(L−x))/cosh(mL),  m = √(2 h_eff /(k t))."""
    length, width, t, h = 45.0, 2.0, 1.0, 100.0
    cfg = load_config_dict(_fin_cfg(length, width, t))
    rs = _run(cfg, cell_mm * 1e-3, h_top=h, h_bottom=h, radiation=False, ambient=25)
    grid = rs.meta["grid"]
    temp = rs.meta["temperature"][0][0] - T0
    x_base = (1.0 - cell_mm / 2) * 1e-3
    l_fin = length * 1e-3 - x_base
    h_eff = 1.0 / (1.0 / h + t * 1e-3 / (2 * K_CU))
    m = math.sqrt(2 * h_eff / (K_CU * t * 1e-3))
    x = grid.xc()
    sel = x > x_base + 1e-12
    theta = 100.0 * np.cosh(m * (l_fin - (x[sel] - x_base))) / np.cosh(m * l_fin)
    rel = np.abs((temp[sel] - 25.0) - theta) / theta
    assert float(rel.max()) < 0.02
    assert abs(rs.scalars["heat_balance_error"]) < 1e-9


def test_fin_mesh_convergence() -> None:
    cfg = load_config_dict(_fin_cfg())
    tips = []
    for cell in (2.0, 1.0, 0.5, 0.25):
        rs = _run(cfg, cell * 1e-3, h_top=100, h_bottom=100, radiation=False)
        tips.append(rs.scalars["t_min"])
    diffs = [abs(tips[i + 1] - tips[i]) for i in range(len(tips) - 1)]
    assert diffs[1] < diffs[0]
    assert diffs[2] < diffs[1]


def _bar_cfg() -> dict[str, Any]:
    d = _fin_cfg(20.0, 1.0, 1.0)
    d["thermal_boundaries"].append(
        {
            "name": "tip",
            "kind": "fixed_temperature",
            "side": "top",
            "rect": [19, 0, 20, 1],
            "temperature": 125,
        }
    )
    d["components"] = [{"ref": "H", "rect": [1, 0, 19, 1], "power": 2.0}]
    return d


def test_bar_uniform_generation_parabolic() -> None:
    """Insulated bar, uniform q', ends at T_b: T(x) = T_b + q'/(2kA)·x(L−x), exact at nodes."""
    cfg = load_config_dict(_bar_cfg())
    cell = 0.5e-3
    rs = _run(cfg, cell, h_top=0.0, h_bottom=0.0, radiation=False)
    grid = rs.meta["grid"]
    temp = rs.meta["temperature"][0][0] - T0
    x = grid.xc()
    x_a, x_b = 1.0e-3 - cell / 2, 19.0e-3 + cell / 2
    length = x_b - x_a
    area = 1e-3 * 1e-3
    q_per_len = 2.0 / (18e-3)
    sel = (x > x_a + 1e-12) & (x < x_b - 1e-12)
    xs = x[sel] - x_a
    expected = 125.0 + q_per_len / (2 * K_CU * area) * xs * (length - xs)
    assert np.allclose(temp[sel], expected, rtol=0, atol=0.02 * (expected.max() - 125))
    assert rs.scalars["heat_out.fixed_temperature"] == pytest.approx(2.0, rel=1e-9)


def _slab_cfg(with_via: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "board": {
            "outline": {"rect": [0, 0, 10, 10]},
            "stackup": [
                {"name": "T", "kind": "conductor", "thickness": "35 um", "material": "copper"},
                {"name": "D", "kind": "dielectric", "thickness": 1.0, "material": "fr4"},
                {"name": "B", "kind": "conductor", "thickness": "35 um", "material": "copper"},
            ],
        },
        "nets": [{"name": "N"}],
        "shapes": [
            {"net": "N", "layer": "T", "fill": True},
            {"net": "N", "layer": "B", "fill": True},
        ],
        "components": [{"ref": "H", "rect": [0, 0, 10, 10], "power": 1.0}],
        "thermal_boundaries": [
            {
                "name": "sink",
                "kind": "fixed_temperature",
                "side": "bottom",
                "rect": [0, 0, 10, 10],
                "temperature": 25,
            }
        ],
    }
    if with_via:
        d["vias"] = [{"net": "N", "at": [5, 5], "drill": 0.3, "material": "copper"}]
    return d


def test_slab_through_thickness_resistance() -> None:
    cfg = load_config_dict(_slab_cfg())
    rs = _run(cfg, 1e-3, h_top=0, h_bottom=0, radiation=False)
    area = 1e-4
    r_expected = (35e-6 / (2 * K_CU) + 1e-3 / 0.29 + 35e-6 / (2 * K_CU)) / area
    dt = rs.scalars["T.t_max"] - (25 + T0)
    assert dt == pytest.approx(1.0 * r_expected, rel=1e-9)
    assert rs.meta["temperature"][0].std() < 1e-9


def test_thermal_via_conductance() -> None:
    cfg_no = load_config_dict(_slab_cfg(False))
    cfg_via = load_config_dict(_slab_cfg(True))
    opts = {"h_top": 0.0, "h_bottom": 0.0, "radiation": False}
    dt_no = _run(cfg_no, 1e-3, **opts).scalars["T.t_max"] - (25 + T0)
    rs = _run(cfg_via, 1e-3, **opts)
    v = cfg_via.board.vias[0]
    g_via = K_CU * v.barrel_area / cfg_via.board.stackup.span("T", "B")
    g_slab = 1.0 / dt_no
    t_top = rs.meta["temperature"][0]
    mean_dt = float(np.mean(t_top)) - (25 + T0)
    assert mean_dt < dt_no
    assert 1.0 / mean_dt == pytest.approx(g_slab + g_via, rel=0.1)


def _plate_cfg(power: float = 1.0) -> dict[str, Any]:
    return {
        "board": {
            "outline": {"rect": [0, 0, 20, 20]},
            "stackup": [{"name": "P", "kind": "conductor", "thickness": 1.0, "material": "copper"}],
        },
        "nets": [{"name": "N"}],
        "shapes": [{"net": "N", "layer": "P", "fill": True}],
        "components": [{"ref": "H", "rect": [0, 0, 20, 20], "power": power}],
    }


def test_isothermal_plate_convection_only() -> None:
    """Uniform heating of a thick copper plate: ΔT = P / (2·h_eff·A)."""
    cfg = load_config_dict(_plate_cfg(1.0))
    h = 10.0
    rs = _run(cfg, 1e-3, h_top=h, h_bottom=h, radiation=False)
    h_eff = 1.0 / (1.0 / h + 1e-3 / (2 * 398.0))
    dt_expected = 1.0 / (2 * h_eff * 4e-4)
    assert rs.scalars["t_max"] - (25 + T0) == pytest.approx(dt_expected, rel=1e-9)


def test_radiation_exact_at_convergence() -> None:
    d = _plate_cfg(2.0)
    d["materials"] = {
        "black_cu": {"sigma": 5.8e7, "k": 398, "density": 8933, "cp": 385, "emissivity": 0.9}
    }
    d["board"]["stackup"][0]["material"] = "black_cu"
    cfg = load_config_dict(d)
    rs = _run(cfg, 2e-3, h_top=5.0, h_bottom=5.0, radiation=True, picard_tol=1e-7)
    t = rs.scalars["t_max"]
    t_inf = 25 + T0
    area = 4e-4
    q = 2 * area * (5.0 * (t - t_inf) + 0.9 * 5.670374419e-8 * (t**4 - t_inf**4))
    assert q == pytest.approx(2.0, rel=1e-3)
    assert 2 < rs.meta["iterations"] < 10
    rs_no = _run(cfg, 2e-3, h_top=5.0, h_bottom=5.0, radiation=False)
    assert rs_no.scalars["t_max"] > t


def test_transient_lumped_capacitance() -> None:
    """Thick plate, Biot ≪ 1: T(t) = T∞ + P/G (1 − e^(−t/τ)), τ = C/G."""
    cfg = load_config_dict(_plate_cfg(1.0))
    h = 50.0
    area = 4e-4
    h_eff = 1.0 / (1.0 / h + 1e-3 / (2 * 398.0))
    g = 2 * h_eff * area
    c = 8933.0 * 385.0 * area * 1e-3
    tau = c / g
    errs = []
    for steps in (20, 80):
        rs = _run(
            cfg,
            2e-3,
            h_top=h,
            h_bottom=h,
            radiation=False,
            mode="transient",
            transient={"t_end": tau, "dt": tau / steps},
        )
        t_end = rs.scalars["t_max"] - (25 + T0)
        exact = 1.0 / g * (1 - math.exp(-1.0))
        errs.append(abs(t_end - exact) / exact)
        hist = rs.meta["history"]
        assert len(hist["time"]) == steps + 1
        assert np.all(np.diff(hist["t_max"]) > 0)
    assert errs[1] < errs[0] / 3
    assert errs[1] < 0.01


def test_transient_converges_to_steady() -> None:
    cfg = load_config_dict(_slab_cfg())
    steady = _run(cfg, 2e-3, h_top=10, radiation=False)
    tr = _run(
        cfg,
        2e-3,
        h_top=10,
        radiation=False,
        mode="transient",
        transient={"t_end": 200.0, "dt": 5.0},
    )
    assert tr.scalars["t_max"] == pytest.approx(steady.scalars["t_max"], abs=1e-6)


def test_transient_power_steps_and_initial_steady() -> None:
    cfg = load_config_dict(_plate_cfg(1.0))
    opts: dict[str, Any] = {"h_top": 50.0, "h_bottom": 50.0, "radiation": False}
    steady = _run(cfg, 2e-3, **opts).scalars["t_max"]
    rs = _run(
        cfg,
        2e-3,
        mode="transient",
        transient={
            "t_end": 50.0,
            "dt": 1.0,
            "initial": "steady",
            "power_steps": [[0.0, 1.0], [10.0, 0.0]],
        },
        **opts,
    )
    hist = rs.meta["history"]
    assert hist["t_max"][0] == pytest.approx(steady)
    assert hist["t_max"][5] == pytest.approx(steady, abs=1e-9)
    assert hist["t_max"][-1] < hist["t_max"][10] < steady


def test_bad_options() -> None:
    cfg = load_config_dict(_plate_cfg())
    with pytest.raises(SolverError, match="transient"):
        _run(cfg, 2e-3, mode="transient")
    with pytest.raises(SolverError, match="mode"):
        _run(cfg, 2e-3, mode="quantum")
    with pytest.raises(SolverError, match="power_steps"):
        _run(
            cfg,
            2e-3,
            mode="transient",
            transient={"t_end": 1, "dt": 0.1, "power_steps": [[1, 1], [0, 1]]},
        )


def test_no_path_to_ambient_errors() -> None:
    cfg = load_config_dict(_plate_cfg())
    with pytest.raises(SolverError, match="no path to ambient"):
        _run(cfg, 2e-3, h_top=0, h_bottom=0, radiation=False)


def _two_resistor_cfg(heatsink: dict[str, Any] | None = None) -> dict[str, Any]:
    d = _plate_cfg(0.0)
    d["components"] = [
        {"ref": "U", "rect": [8, 8, 12, 12], "power": 2.0, "theta_jb": 5.0, "theta_jc": 1.0}
    ]
    d["thermal_boundaries"] = [
        {
            "name": "clamp",
            "kind": "fixed_temperature",
            "side": "bottom",
            "rect": [0, 0, 20, 20],
            "temperature": 40,
        }
    ]
    if heatsink is not None:
        d["thermal_boundaries"].append(heatsink)
    return d


def test_two_resistor_network() -> None:
    """Board clamped ~isothermal at 40 °C: Tj solves the 2-branch network."""
    hs = {"name": "hs", "kind": "convection", "component": "U", "resistance": 4.0, "ambient": 25}
    cfg = load_config_dict(_two_resistor_cfg(hs))
    rs = _run(cfg, 1e-3, h_top=0, h_bottom=0, radiation=False)
    row = rs.meta["components"][0]
    assert row["model"] == "two_resistor"
    t_b = row["t_board"] - T0
    tj = row["tj"] - T0
    q_board = (tj - t_b) / 5.0
    q_top = (tj - 25.0) / (1.0 + 4.0)
    assert q_board + q_top == pytest.approx(2.0, rel=1e-6)
    assert t_b == pytest.approx(40.0, abs=0.5)
    assert rs.scalars["heat_out.edges+packages"] == pytest.approx(q_top, rel=1e-6)


def test_two_resistor_without_heatsink_uses_face_h() -> None:
    cfg = load_config_dict(_two_resistor_cfg())
    rs_h0 = _run(cfg, 1e-3, h_top=0, h_bottom=0, radiation=False)
    rs_h = _run(cfg, 1e-3, h_top=50, h_bottom=0, radiation=False)
    assert rs_h.scalars["U.tj"] < rs_h0.scalars["U.tj"]
    assert rs_h0.scalars["heat_out.edges+packages"] == pytest.approx(0.0, abs=1e-12)


def test_tj_violation() -> None:
    d = _plate_cfg(0.0)
    d["components"] = [{"ref": "U", "rect": [8, 8, 12, 12], "power": 30.0, "tj_max": 60}]
    rs = _run(load_config_dict(d), 1e-3, h_top=10, h_bottom=10)
    v = next(v for v in rs.violations if v.check == "temperature")
    assert v.subject == "U"
    assert v.value > 60
    assert v.limit == pytest.approx(60.0)
    assert not rs.passed


def test_convection_boundary_region() -> None:
    d = _plate_cfg(1.0)
    base = _run(load_config_dict(d), 1e-3, h_top=10, h_bottom=10, radiation=False)
    d["thermal_boundaries"] = [
        {"name": "fan", "kind": "convection", "side": "top", "rect": [0, 0, 20, 20], "h": 30.0}
    ]
    rs = _run(load_config_dict(d), 1e-3, h_top=10, h_bottom=10, radiation=False)
    assert rs.scalars["t_max"] < base.scalars["t_max"]
    assert "heat_out.fan" in rs.scalars
    assert rs.scalars["heat_out.fan"] == pytest.approx(0.75, rel=1e-3)


def test_joule_field_adds_heat_and_shape_checked() -> None:
    cfg = load_config_dict(_plate_cfg(0.0))
    probe = _run(cfg, 2e-3, h_top=10, h_bottom=10, radiation=False)
    grid = probe.meta["grid"]
    jf = np.zeros((1, grid.ny, grid.nx))
    jf[0, 5, 5] = 0.5
    rs = _run(cfg, 2e-3, h_top=10, h_bottom=10, radiation=False, joule_field=jf)
    assert rs.scalars["power_joule"] == pytest.approx(0.5)
    assert abs(rs.scalars["heat_balance_error"]) < 1e-9
    with pytest.raises(SolverError, match="shape"):
        _run(cfg, 2e-3, joule_field=np.zeros((1, 2, 2)))


def test_components_reported_with_margin() -> None:
    d = _plate_cfg(0.0)
    d["components"] = [{"ref": "A", "rect": [2, 2, 4, 4], "power": 0.5}]
    rs = _run(load_config_dict(d), 1e-3)
    row = rs.meta["components"][0]
    assert row["model"] == "board"
    assert row["tj"] == row["t_board"]
    assert row["margin"] == pytest.approx(row["tj_max"] - row["tj_peak"])


def test_radiation_preconditioned_cg_matches_exact_solve() -> None:
    """Picard updates use CG preconditioned by the first LU; result must equal a
    direct solve of the final linearised system."""
    from scipy.sparse.linalg import spsolve

    from pcbsim.solvers.thermal import _apply_dirichlet, _system_matrix

    d = _two_resistor_cfg()
    d["components"][0]["power"] = 5.0
    d["thermal_boundaries"] = []
    cfg = load_config_dict(d)
    solver = ThermalSolver({"cell": 1e-3, "h_top": 5.0, "h_bottom": 5.0, "picard_tol": 1e-7})
    rs = solver.run(SolverContext(cfg.board, cfg.materials))
    t = rs.meta["t_node"]
    s = solver.system
    k, rhs, _ = _system_matrix(s, t)
    kff, r, f_idx, _, _ = _apply_dirichlet(k, rhs + s.power, s)
    t_exact = spsolve(kff, r)
    assert np.max(np.abs(t_exact - t[f_idx])) < 1e-6
    assert abs(rs.scalars["heat_balance_error"]) < 1e-6


def test_transient_with_radiation_reaches_steady() -> None:
    cfg = load_config_dict(_plate_cfg(2.0))
    opts: dict[str, Any] = {
        "h_top": 5.0,
        "h_bottom": 5.0,
        "radiation": True,
        "emissivity_top": 0.9,
        "emissivity_bottom": 0.9,
    }
    steady = _run(cfg, 2e-3, **opts).scalars["t_max"]
    tr = _run(cfg, 2e-3, mode="transient", transient={"t_end": 20000.0, "dt": 200.0}, **opts)
    assert tr.scalars["t_max"] == pytest.approx(steady, abs=0.05)
