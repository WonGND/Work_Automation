"""End-to-end thermal on the example board, plus thermal-boundary config validation."""

from __future__ import annotations

import copy
import dataclasses
import io
from pathlib import Path
from typing import Any

import pytest
import yaml

from pcbsim.cli import main
from pcbsim.errors import ConfigError
from pcbsim.io import load_config, load_config_dict
from pcbsim.io.config import MeshOptions
from pcbsim.model import ThermalBoundaryKind
from pcbsim.runner import RunResult, order_solvers, run_analysis

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "soc_4layer.yaml"
T0 = 273.15


@pytest.fixture(scope="module")
def run() -> RunResult:
    return run_analysis(load_config(EXAMPLE), ["dc_ir", "thermal"])


def test_example_energy_balance_includes_joule(run: RunResult) -> None:
    th = run.results["thermal"]
    dc = run.results["dc_ir"]
    assert th.scalars["power_components"] == pytest.approx(5.0)
    assert th.scalars["power_joule"] == pytest.approx(dc.scalars["joule_power"], rel=1e-9)
    assert abs(th.scalars["heat_balance_error"]) < 1e-9


def test_example_temperatures_plausible(run: RunResult) -> None:
    th = run.results["thermal"]
    rows = {r["ref"]: r for r in th.meta["components"]}
    assert rows["U1"]["model"] == "two_resistor"
    assert rows["U3"]["model"] == "board"
    for r in rows.values():
        assert 45 + T0 < r["tj"] < 105 + T0
        assert r["passed"]
    assert rows["U1"]["tj"] > rows["U1"]["t_board"]
    assert th.scalars["L1_TOP.t_max"] >= th.scalars["L4_BOT.t_max"]
    assert th.scalars["t_min"] >= 25 + T0 - 1e-9
    assert th.passed


def test_example_heatsink_matters() -> None:
    cfg = load_config(EXAMPLE)
    no_hs = dataclasses.replace(
        cfg,
        board=dataclasses.replace(
            cfg.board,
            thermal_boundaries=tuple(
                t for t in cfg.board.thermal_boundaries if t.component is None
            ),
        ),
    )
    with_hs = run_analysis(cfg, ["thermal"]).results["thermal"]
    without = run_analysis(no_hs, ["thermal"]).results["thermal"]
    assert without.scalars["U1.tj"] > with_hs.scalars["U1.tj"] + 20
    assert not without.passed


def test_example_thermal_mesh_convergence() -> None:
    cfg = load_config(EXAMPLE)
    tj = []
    for cell in (1.0e-3, 0.5e-3, 0.25e-3):
        c = dataclasses.replace(
            cfg, analysis=dataclasses.replace(cfg.analysis, mesh=MeshOptions(cell=cell))
        )
        tj.append(run_analysis(c, ["thermal"]).results["thermal"].scalars["U1.tj"])
    d1, d2 = abs(tj[1] - tj[0]), abs(tj[2] - tj[1])
    assert d2 < d1
    assert d2 < 0.5


def test_solver_order_dependencies() -> None:
    assert order_solvers(["thermal", "dc_ir"]) == ["dc_ir", "thermal"]
    assert order_solvers(["thermal"]) == ["thermal"]
    assert order_solvers(["dc_ir", "thermal", "dc_ir"]) == ["dc_ir", "thermal"]


def test_cli_thermal_output(tmp_path: Path) -> None:
    buf = io.StringIO()
    code = main(
        [
            "run",
            str(EXAMPLE),
            "--solver",
            "thermal",
            "--solver",
            "dc_ir",
            "--no-plots",
            "--out",
            str(tmp_path),
        ],
        out=buf,
    )
    text = buf.getvalue()
    assert code == 0
    assert text.index("[dc_ir]") < text.index("[thermal]")
    assert "Tj [°C]" in text
    assert "heat out" in text


def test_cli_transient(tmp_path: Path) -> None:
    d = yaml.safe_load(EXAMPLE.read_text())
    d["analysis"]["solvers"] = ["thermal"]
    d["analysis"]["mesh"] = {"cell": 1.0}
    d["analysis"]["options"] = {
        "thermal": {"mode": "transient", "transient": {"t_end": 60, "dt": 10}}
    }
    f = tmp_path / "t.yaml"
    f.write_text(yaml.safe_dump(d))
    buf = io.StringIO()
    assert main(["run", str(f), "--out", str(tmp_path / "o")], out=buf) == 0
    assert "transient: 6 steps" in buf.getvalue()
    assert (tmp_path / "o" / "thermal_temperature_L1_TOP.png").exists()


def _raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return data


def test_example_boundaries_loaded() -> None:
    b = load_config(EXAMPLE).board
    kinds = {t.name: t.kind for t in b.thermal_boundaries}
    assert kinds["U1_heatsink"] is ThermalBoundaryKind.CONVECTION
    assert kinds["chassis_standoffs"] is ThermalBoundaryKind.FIXED_TEMPERATURE
    hs = next(t for t in b.thermal_boundaries if t.name == "U1_heatsink")
    assert hs.resistance == 6.0
    assert hs.region.area() == pytest.approx(196e-6)
    fx = next(t for t in b.thermal_boundaries if t.name == "chassis_standoffs")
    assert fx.temperature == pytest.approx(45 + T0)


@pytest.mark.parametrize(
    ("patch", "match"),
    [
        ({"kind": "convection", "component": "U1"}, "exactly one of 'h' or 'resistance'"),
        ({"kind": "convection", "component": "U1", "h": 10, "resistance": 1}, "exactly one of"),
        ({"kind": "fixed_temperature", "rect": [0, 0, 1, 1]}, "needs 'temperature'"),
        (
            {"kind": "fixed_temperature", "rect": [0, 0, 1, 1], "temperature": 40, "h": 3},
            "takes no h",
        ),
        ({"kind": "convection", "h": 10}, "either a region"),
        ({"kind": "convection", "component": "U9", "h": 10}, "unknown component 'U9'"),
        (
            {"kind": "fixed_temperature", "rect": [0, 0, 100, 1], "temperature": 40},
            "outside the board",
        ),
    ],
)
def test_thermal_boundary_validation(patch: dict[str, Any], match: str) -> None:
    raw = copy.deepcopy(_raw())
    raw["thermal_boundaries"] = [{"name": "x", **patch}]
    with pytest.raises(ConfigError, match=match):
        load_config_dict(raw)
