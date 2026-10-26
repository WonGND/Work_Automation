"""Electro-thermal ``coupled`` solver: analytic lumped case, α = 0 regression, runaway."""

from __future__ import annotations

import copy
import dataclasses
import io
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from pcbsim.cli import main
from pcbsim.errors import SolverError
from pcbsim.io import load_config, load_config_dict
from pcbsim.io.config import LoadedConfig
from pcbsim.runner import order_solvers, run_analysis
from pcbsim.solvers import ResultSet, SolverContext, get_solver
from pcbsim.solvers.coupled import CoupledSolver
from pcbsim.solvers.dc_ir import DcIrSolver
from pcbsim.solvers.thermal import ThermalSolver

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "soc_4layer.yaml"
T0 = 273.15

SIGMA = 5.8e7
ALPHA = 0.00393
T_REF = 293.15
T_CU = 35e-6
L_MM, W_MM, PORT_MM = 10.5, 10.0, 0.25
H = 10.0
T_AMB_C = 25.0


def _sheet(current: float, alpha: float = ALPHA, k: float = 1e6) -> dict[str, Any]:
    """One copper sheet, ports one cell wide at each end, convection on both faces.

    ``k`` is made huge so the sheet is isothermal and the lumped model is exact.
    """
    return {
        "materials": {"copper": {"alpha_r": alpha, "k": k}},
        "board": {
            "outline": {"rect": [0, 0, L_MM, W_MM]},
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
                "rect": [0, 0, PORT_MM, W_MM],
                "voltage": 1.0,
            },
            {
                "name": "LOAD",
                "kind": "current_sink",
                "net": "N",
                "layer": "L1",
                "rect": [L_MM - PORT_MM, 0, L_MM, W_MM],
                "current": current,
                "distribution": "equipotential",
            },
        ],
    }


_TH = {"ambient": T_AMB_C, "h_top": H, "h_bottom": H, "radiation": False}


def _coupled(cfg: LoadedConfig, **opts: Any) -> ResultSet:
    ctx = SolverContext(cfg.board, cfg.materials, options={"thermal": _TH})
    return CoupledSolver({"cell": PORT_MM * 1e-3, **opts}).run(ctx)


def _lumped(current: float) -> tuple[float, float]:
    """(K, T*) of the lumped model R(T) = R0[1 + α(T − T_ref)], G = 2hA."""
    r0 = (L_MM - 2 * PORT_MM) / W_MM / (SIGMA * T_CU)
    g = 2.0 * H * (L_MM * W_MM * 1e-6)
    k = current**2 * r0 / g
    ta = T_AMB_C + T0
    return k, ta + k * (1.0 + ALPHA * (ta - T_REF)) / (1.0 - ALPHA * k)


def test_registered_and_ordered() -> None:
    assert get_solver("coupled") is CoupledSolver
    assert order_solvers(["coupled", "thermal", "dc_ir", "si"]) == [
        "dc_ir",
        "thermal",
        "coupled",
        "si",
    ]


@pytest.mark.parametrize("current", [10.0, 20.0])
def test_lumped_fixed_point_and_contraction(current: float) -> None:
    k, t_star = _lumped(current)
    rs = _coupled(load_config_dict(_sheet(current)), tol_t=1e-6, tol_v=1e-10, max_iter=200)
    assert rs.meta["converged"]
    assert rs.scalars["t_max"] == pytest.approx(t_star, abs=1e-3)
    assert rs.scalars["t_min"] == pytest.approx(t_star, abs=1e-3)
    r0 = (L_MM - 2 * PORT_MM) / W_MM / (SIGMA * T_CU)
    r_hot = r0 * (1.0 + ALPHA * (t_star - T_REF))
    assert rs.scalars["LOAD.r_path"] == pytest.approx(r_hot, rel=1e-6)
    assert rs.scalars["joule_power"] == pytest.approx(current**2 * r_hot, rel=1e-6)
    assert rs.scalars["contraction"] == pytest.approx(ALPHA * k, rel=1e-2)


def test_relaxation_reaches_same_fixed_point() -> None:
    cfg = load_config_dict(_sheet(20.0))
    full = _coupled(cfg, tol_t=1e-6, tol_v=1e-10, max_iter=200)
    half = _coupled(cfg, tol_t=1e-6, tol_v=1e-10, max_iter=200, relaxation=0.5)
    assert half.meta["converged"]
    assert half.scalars["t_max"] == pytest.approx(full.scalars["t_max"], abs=1e-4)
    assert half.scalars["LOAD.drop_pct"] == pytest.approx(full.scalars["LOAD.drop_pct"], rel=1e-6)
    assert half.meta["iterations"] > full.meta["iterations"]


def test_thermal_runaway_detected() -> None:
    k, _ = _lumped(40.0)
    assert ALPHA * k > 1.0
    rs = _coupled(load_config_dict(_sheet(40.0)), max_iter=60)
    assert not rs.meta["converged"]
    checks = {v.check for v in rs.violations}
    assert "thermal_runaway" in checks
    assert not rs.passed
    assert rs.meta["iterations"] < 60


def test_not_converged_reports_violation() -> None:
    rs = _coupled(load_config_dict(_sheet(20.0)), tol_t=1e-12, tol_v=1e-15, max_iter=2)
    assert not rs.meta["converged"]
    assert any(v.check == "convergence" for v in rs.violations)


def _example_small() -> LoadedConfig:
    d: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    d["analysis"]["mesh"] = {"cell": 1.0}
    d["analysis"]["solvers"] = ["dc_ir", "thermal", "coupled"]
    d["analysis"]["options"].pop("si", None)
    return load_config_dict(d)


@pytest.fixture(scope="module")
def example() -> LoadedConfig:
    return _example_small()


def test_alpha_zero_equals_uncoupled(example: LoadedConfig) -> None:
    db = example.materials.merged(
        {m: {"alpha_r": 0.0} for m in example.materials if example.materials[m].is_conductor}
    )
    run = run_analysis(dataclasses.replace(example, materials=db))
    cp, dc, th = run.results["coupled"], run.results["dc_ir"], run.results["thermal"]
    assert cp.meta["converged"]
    assert cp.meta["iterations"] == 1
    assert cp.scalars["delta_v"] < 1e-12
    np.testing.assert_allclose(cp.meta["voltage"], dc.meta["voltage"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(cp.meta["temperature"], th.meta["temperature"], rtol=0, atol=1e-6)
    for key in ("SOC_CORE.drop_pct", "joule_power"):
        assert cp.scalars[key] == pytest.approx(dc.scalars[key], rel=1e-10)
    for key in ("t_max", "U1.tj"):
        assert cp.scalars[key] == pytest.approx(th.scalars[key], abs=1e-6)


def test_example_hotter_board_has_higher_drop(example: LoadedConfig) -> None:
    run = run_analysis(example, ["dc_ir", "thermal", "coupled"])
    cp, dc, th = run.results["coupled"], run.results["dc_ir"], run.results["thermal"]
    assert cp.meta["converged"]
    assert cp.scalars["SOC_CORE.drop_pct.uncoupled"] == pytest.approx(
        dc.scalars["SOC_CORE.drop_pct"], rel=1e-12
    )
    assert cp.scalars["t_max.uncoupled"] == pytest.approx(th.scalars["t_max"], abs=1e-9)
    assert cp.scalars["SOC_CORE.drop_pct"] > dc.scalars["SOC_CORE.drop_pct"] * 1.05
    assert cp.scalars["joule_power"] > dc.scalars["joule_power"]
    assert cp.scalars["t_max"] > th.scalars["t_max"]
    hist = cp.meta["history"]
    assert hist["delta_t"][-1] < hist["delta_t"][1]

    hot = copy.deepcopy(dict(example.analysis.options))
    hot["coupled"] = {"thermal": {"ambient": 60}}
    cfg = dataclasses.replace(example, analysis=dataclasses.replace(example.analysis, options=hot))
    hot_rs = run_analysis(cfg, ["coupled"]).results["coupled"]
    assert hot_rs.scalars["SOC_CORE.drop_pct"] > cp.scalars["SOC_CORE.drop_pct"]


def test_fixed_point_is_self_consistent(example: LoadedConfig) -> None:
    cp = run_analysis(example, ["coupled"]).results["coupled"]
    ctx = SolverContext(example.board, example.materials, cp.meta["grid"])
    t_field = np.where(np.isfinite(cp.meta["temperature"]), cp.meta["temperature"], T0 + 25)
    dc = DcIrSolver({"temperature_field": t_field}).run(ctx)
    th_opts = {**example.analysis.options.get("thermal", {}), "joule_field": dc.meta["joule_cell"]}
    th = ThermalSolver(th_opts).run(ctx)
    assert dc.scalars["SOC_CORE.drop_pct"] == pytest.approx(cp.scalars["SOC_CORE.drop_pct"], 1e-5)
    assert float(np.nanmax(np.abs(th.meta["temperature"] - cp.meta["temperature"]))) < 0.01


def test_options_validation() -> None:
    cfg = load_config_dict(_sheet(1.0))
    with pytest.raises(SolverError, match="joule: false"):
        CoupledSolver({"thermal": {"joule": False}}).setup(SolverContext(cfg.board, cfg.materials))
    with pytest.raises(SolverError, match="relaxation"):
        CoupledSolver({"relaxation": 1.5}).setup(SolverContext(cfg.board, cfg.materials))
    ctx = SolverContext(
        cfg.board,
        cfg.materials,
        options={"thermal": {**_TH, "mode": "transient", "transient": {"t_end": 1, "dt": 1}}},
    )
    rs = CoupledSolver({"cell": PORT_MM * 1e-3}).run(ctx)
    assert any("forced to 'steady'" in v.message for v in rs.violations)
    assert math.isfinite(rs.scalars["t_max"])


def test_cli_coupled(tmp_path: Path) -> None:
    d: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    d["analysis"]["mesh"] = {"cell": 1.0}
    d["analysis"]["solvers"] = ["coupled"]
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump(d))
    buf = io.StringIO()
    code = main(["run", str(f), "--out", str(tmp_path / "o")], out=buf)
    text = buf.getvalue()
    assert code == 0, text
    assert "[coupled]" in text
    assert "converged after" in text
    assert "coupled vs uncoupled" in text
    assert "SOC_CORE" in text
    assert (tmp_path / "o" / "coupled_convergence.png").exists()
    assert (tmp_path / "o" / "coupled_temperature_L1_TOP.png").exists()
    doc = yaml.safe_load((tmp_path / "o" / "results.json").read_text())
    hist = doc["solvers"]["coupled"]["history"]
    assert hist["iteration"][0] == 0
    assert hist["delta_t"][0] is None


def test_example_config_lists_coupled() -> None:
    assert "coupled" in load_config(EXAMPLE).analysis.solvers
