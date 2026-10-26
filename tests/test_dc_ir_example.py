"""End-to-end: example board, multi-layer mesh convergence, runner output files."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from pcbsim.cli import EXIT_OK, EXIT_VIOLATIONS, main
from pcbsim.io import load_config
from pcbsim.runner import run_analysis, write_results

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "soc_4layer.yaml"


@pytest.fixture(scope="module")
def example_run() -> object:
    return run_analysis(load_config(EXAMPLE), ["dc_ir"])


def test_example_dc_ir_physics(example_run: object) -> None:
    from pcbsim.runner import RunResult

    assert isinstance(example_run, RunResult)
    rs = example_run.results["dc_ir"]
    load = next(p for p in rs.meta["ports"] if p["name"] == "SOC_CORE")
    src = next(p for p in rs.meta["ports"] if p["name"] == "VRM_OUT")
    assert src["current"] == pytest.approx(6.0, rel=1e-9)
    assert 0.1 < load["drop_pct"] < 3.0
    assert load["reference_layer"] == "L2_GND"
    p_sink = 6.0 * load["v_avg"]
    assert src["power"] == pytest.approx(p_sink + rs.scalars["joule_power"], rel=1e-6)
    assert rs.scalars["VDD_1V0.v_max"] == pytest.approx(1.0)
    assert rs.scalars["GND.v_min"] == pytest.approx(0.0, abs=1e-12)
    assert rs.scalars["L3_PWR.j_max"] > rs.scalars["L1_TOP.j_max"]


def test_example_slot_forces_detour() -> None:
    cfg = load_config(EXAMPLE)
    rs_slot = run_analysis(cfg, ["dc_ir"]).results["dc_ir"]
    import dataclasses

    from pcbsim.model import Polygon

    shapes = tuple(
        dataclasses.replace(s, polygon=Polygon.rectangle(1e-3, 1e-3, 59e-3, 39e-3))
        if s.name == "vdd_plane"
        else s
        for s in cfg.board.shapes
    )
    no_slot = dataclasses.replace(cfg, board=dataclasses.replace(cfg.board, shapes=shapes))
    rs_flat = run_analysis(no_slot, ["dc_ir"]).results["dc_ir"]
    assert rs_slot.scalars["SOC_CORE.drop_pct"] > rs_flat.scalars["SOC_CORE.drop_pct"]


def test_multilayer_mesh_convergence() -> None:
    import dataclasses

    from pcbsim.io.config import MeshOptions

    cfg = load_config(EXAMPLE)
    drops = []
    for cell in (1.0e-3, 0.5e-3, 0.25e-3):
        c = dataclasses.replace(
            cfg, analysis=dataclasses.replace(cfg.analysis, mesh=MeshOptions(cell=cell))
        )
        drops.append(run_analysis(c, ["dc_ir"]).results["dc_ir"].scalars["SOC_CORE.drop_pct"])
    d1, d2 = abs(drops[1] - drops[0]), abs(drops[2] - drops[1])
    assert d2 < d1
    assert d2 / drops[2] < 0.05


def test_write_results(tmp_path: Path, example_run: object) -> None:
    from pcbsim.runner import RunResult

    assert isinstance(example_run, RunResult)
    files = write_results(example_run, tmp_path, plots=True)
    names = {f.name for f in files}
    assert "results.json" in names
    assert "dc_ir_fields.npz" in names
    assert "dc_ir_voltage_L3_PWR.png" in names
    doc = json.loads((tmp_path / "results.json").read_text())
    assert doc["solvers"]["dc_ir"]["scalars"]["VRM_OUT.current"] == pytest.approx(6.0)
    assert doc["mesh"]["layers"] == ["L1_TOP", "L2_GND", "L3_PWR", "L4_BOT"]
    assert isinstance(doc["passed"], bool)


def test_cli_run(tmp_path: Path) -> None:
    buf = io.StringIO()
    code = main(
        ["run", str(EXAMPLE), "--solver", "dc_ir", "--out", str(tmp_path), "--no-plots"], out=buf
    )
    text = buf.getvalue()
    assert code in (EXIT_OK, EXIT_VIOLATIONS)
    assert "SOC_CORE" in text
    assert (tmp_path / "results.json").exists()


def test_cli_run_violation_exit(tmp_path: Path) -> None:
    import yaml

    d = yaml.safe_load(EXAMPLE.read_text())
    d["criteria"]["ir_drop_pct"] = 0.1
    d["analysis"]["solvers"] = ["dc_ir"]
    d["analysis"]["options"] = {}
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump(d))
    buf = io.StringIO()
    assert main(["run", str(f), "--no-plots", "--out", str(tmp_path / "o")], out=buf) == (
        EXIT_VIOLATIONS
    )
    assert "FAIL" in buf.getvalue()


def test_cli_unknown_solver(tmp_path: Path) -> None:
    assert main(["run", str(EXAMPLE), "--solver", "nope", "--out", str(tmp_path)]) == 1
