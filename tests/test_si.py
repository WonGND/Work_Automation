"""Signal integrity: closed forms vs published values, 2D FEM vs closed forms."""

from __future__ import annotations

import io
import itertools
import math
from pathlib import Path
from typing import Any

import pytest
import yaml

from pcbsim.cli import EXIT_OK, EXIT_VIOLATIONS, main
from pcbsim.errors import ConfigError, SolverError
from pcbsim.io import load_config, load_config_dict
from pcbsim.si import analytic
from pcbsim.si.fem2d import CrossSection, FemOptions, Rect, solve
from pcbsim.si.xsection import analytic_for, resolve
from pcbsim.solvers import SolverContext, get_solver

MM = 1e-3
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "soc_4layer.yaml"


def _ms(w: float, h: float, er: float, t: float = 0.0) -> CrossSection:
    return CrossSection([Rect(-w / 2, w / 2, h, h + t)], [(0.0, h, er)])


def _sl(w: float, b: float, er: float, t: float = 0.0) -> CrossSection:
    y0 = (b - t) / 2
    return CrossSection([Rect(-w / 2, w / 2, y0, y0 + t)], [(0.0, b, er)], top_plane=b)


def _csl(w: float, s: float, b: float, er: float) -> CrossSection:
    y = b / 2
    return CrossSection(
        [Rect(-s / 2 - w, -s / 2, y, y), Rect(s / 2, s / 2 + w, y, y)], [(0.0, b, er)], b
    )


# --------------------------------------------------------------------------- closed forms


def test_hj_published_values() -> None:
    """Pozar Ex. 3.7: εr = 2.2, 50 Ω needs w/h = 3.081 (εeff 1.87) — HJ within 1 %."""
    z = analytic.microstrip_hj(3.081e-3, 1e-3, 2.2)
    assert z.z0 == pytest.approx(50.0, rel=0.01)
    assert z.eps_eff == pytest.approx(1.87, rel=0.01)


def test_hj_limits() -> None:
    z = analytic.microstrip_hj(1e-3, 0.5e-3, 1.0)
    assert z.eps_eff == pytest.approx(1.0)
    wide = analytic.microstrip_hj(100e-3, 1e-3, 4.0)
    assert wide.eps_eff == pytest.approx(4.0, rel=0.05)
    thick = analytic.microstrip_hj(1e-3, 0.5e-3, 4.3, 35e-6)
    assert thick.z0 < analytic.microstrip_hj(1e-3, 0.5e-3, 4.3).z0
    assert not analytic.microstrip_hj(1e-3, 1.0, 4.3).valid


def test_cohn_stripline_published_value() -> None:
    """Pozar Ex. 3.5: εr = 2.2, b = 0.32 cm, w = 0.266 cm → 50 Ω."""
    assert analytic.stripline_cohn(0.266e-2, 0.32e-2, 2.2).z0 == pytest.approx(50.0, rel=0.005)


def test_wheeler_reduces_to_cohn() -> None:
    for w in (0.2e-3, 0.4e-3, 1.0e-3):
        cohn = analytic.stripline_cohn(w, 1e-3, 4.3).z0
        assert analytic.stripline_wheeler(w, 1e-3, 0.0, 4.3).z0 == pytest.approx(cohn, rel=0.005)


def test_coupled_cohn_limits() -> None:
    w, b, er = 0.3e-3, 1e-3, 4.0
    single = analytic.stripline_cohn(w, b, er).z0
    far = analytic.coupled_stripline_cohn(w, 20e-3, b, er)
    assert far.z_odd == pytest.approx(single, rel=1e-6)
    assert far.z_even == pytest.approx(single, rel=1e-6)
    near = analytic.coupled_stripline_cohn(w, 0.1e-3, b, er)
    assert near.z_odd is not None
    assert near.z_even is not None
    assert near.z_odd < single < near.z_even


def test_ipc_formulas_and_validity() -> None:
    assert analytic.microstrip_ipc(0.3e-3, 0.2e-3, 4.2, 35e-6).valid
    assert not analytic.microstrip_ipc(1e-3, 0.2e-3, 4.2).valid
    d = analytic.diff_microstrip_ipc(0.15e-3, 50e-3, 0.2e-3, 4.2)
    assert d.z_diff == pytest.approx(2 * d.z0, rel=1e-6)
    with pytest.raises(SolverError):
        analytic.microstrip_ipc(10e-3, 0.1e-3, 4.2)


# --------------------------------------------------------------------------- FEM


@pytest.mark.parametrize(("w", "h", "er"), [(1.0, 0.5, 4.3), (0.3, 0.2, 4.2), (3.0, 1.0, 2.2),
                                             (0.15, 0.1, 3.5)])  # fmt: skip
def test_fem_microstrip_vs_hammerstad_jensen_within_2pct(w: float, h: float, er: float) -> None:
    fem = solve(_ms(w * MM, h * MM, er)).single()
    hj = analytic.microstrip_hj(w * MM, h * MM, er)
    assert fem.z0 == pytest.approx(hj.z0, rel=0.02)
    assert fem.eps_eff == pytest.approx(hj.eps_eff, rel=0.01)


def test_fem_thick_microstrip_vs_hj_within_2pct() -> None:
    fem = solve(_ms(0.36 * MM, 0.2 * MM, 4.2, 35e-6)).single()
    hj = analytic.microstrip_hj(0.36 * MM, 0.2 * MM, 4.2, 35e-6)
    assert fem.z0 == pytest.approx(hj.z0, rel=0.02)


@pytest.mark.parametrize("w", [0.2, 0.4, 1.0])
def test_fem_stripline_vs_cohn_exact(w: float) -> None:
    fem = solve(_sl(w * MM, 1 * MM, 4.3)).single()
    assert fem.z0 == pytest.approx(analytic.stripline_cohn(w * MM, 1 * MM, 4.3).z0, rel=0.01)
    assert fem.eps_eff == pytest.approx(4.3, rel=1e-9)


def test_fem_thick_stripline_vs_wheeler() -> None:
    fem = solve(_sl(0.3 * MM, 1 * MM, 4.0, 35e-6)).single()
    wh = analytic.stripline_wheeler(0.3 * MM, 1 * MM, 35e-6, 4.0)
    assert fem.z0 == pytest.approx(wh.z0, rel=0.01)


def test_fem_coupled_stripline_vs_cohn_exact() -> None:
    w, s, b, er = 0.2 * MM, 0.15 * MM, 0.8 * MM, 4.0
    fem = solve(_csl(w, s, b, er)).pair()
    ex = analytic.coupled_stripline_cohn(w, s, b, er)
    assert fem.z_odd == pytest.approx(ex.z_odd, rel=0.01)
    assert fem.z_even == pytest.approx(ex.z_even, rel=0.01)
    assert fem.z_diff == pytest.approx(ex.z_diff, rel=0.01)


def test_mesh_refinement_converges() -> None:
    """Halving the minimum element size shrinks the error vs Cohn's exact value."""
    exact = analytic.stripline_cohn(0.4 * MM, 1 * MM, 4.3).z0
    errs = [
        abs(solve(_sl(0.4 * MM, 1 * MM, 4.3), FemOptions(h_min_frac=f)).single().z0 / exact - 1)
        for f in (1 / 16, 1 / 32, 1 / 64, 1 / 128)
    ]
    assert all(b < a for a, b in itertools.pairwise(errs))
    assert errs[-1] < 0.002
    assert errs[-1] < errs[0] / 3


def test_box_size_effect_small() -> None:
    z30 = solve(_ms(1 * MM, 0.5 * MM, 4.3)).single().z0
    z60 = solve(_ms(1 * MM, 0.5 * MM, 4.3), FemOptions(box_factor=60)).single().z0
    assert z30 == pytest.approx(z60, rel=1e-3)


def test_capacitance_matrix_properties() -> None:
    r = solve(_csl(0.2 * MM, 0.15 * MM, 0.8 * MM, 4.0))
    assert r.c[0, 1] == pytest.approx(r.c[1, 0])
    assert r.c[0, 1] < 0
    assert r.c[0, 0] == pytest.approx(r.c[1, 1], rel=1e-6)
    assert r.c[0, 0] == pytest.approx(4.0 * r.c0[0, 0], rel=1e-9)


def test_fem_rejects_conductor_on_plane() -> None:
    with pytest.raises(SolverError, match="touches"):
        solve(CrossSection([Rect(-1e-4, 1e-4, 0.0, 1e-5)], [(0.0, 1e-4, 4.0)]))


# --------------------------------------------------------------------------- stack-up


def test_resolve_example_stackup() -> None:
    cfg = load_config(EXAMPLE)
    st, db = cfg.board.stackup, cfg.materials
    top = resolve(st, db, "L1_TOP", 0.36 * MM)
    assert top.topology == "microstrip"
    assert top.references == ("L2_GND",)
    assert top.h == pytest.approx(0.2 * MM)
    assert top.soldermask
    bot = resolve(st, db, "L4_BOT", 0.3 * MM)
    assert bot.references == ("L3_PWR",)
    inner = resolve(st, db, "L2_GND", 0.2 * MM, references=("L1_TOP", "L3_PWR"))
    assert inner.topology == "stripline"
    assert inner.b == pytest.approx(0.2 * MM + 34.79e-6 + 1.02 * MM)


def test_soldermask_lowers_z0() -> None:
    cfg = load_config(EXAMPLE)
    g = resolve(cfg.board.stackup, cfg.materials, "L1_TOP", 0.36 * MM)
    with_mask = solve(g.xs).single().z0
    bare = solve(_ms(0.36 * MM, 0.2 * MM, 4.2, g.t)).single().z0
    assert 0.9 * bare < with_mask < bare
    z, acc = analytic_for(g)
    assert "solder mask" in z.note
    assert acc >= 0.06


def test_resolve_errors() -> None:
    cfg = load_config(EXAMPLE)
    st, db = cfg.board.stackup, cfg.materials
    with pytest.raises(SolverError, match="not a conductor"):
        resolve(st, db, "PP1", 0.2 * MM)
    with pytest.raises(SolverError, match="own layer"):
        resolve(st, db, "L1_TOP", 0.2 * MM, references=("L1_TOP",))
    with pytest.raises(SolverError, match="at most one"):
        resolve(st, db, "L4_BOT", 0.2 * MM, references=("L1_TOP", "L2_GND"))


# --------------------------------------------------------------------------- solver / config / CLI


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(EXAMPLE.read_text())
    return raw


def test_si_solver_targets_and_crosscheck() -> None:
    raw = _raw()
    raw["transmission_lines"] = [
        {"name": "ok", "layer": "L1_TOP", "width": 0.36, "target": 50},
        {"name": "off", "layer": "L1_TOP", "width": 0.36, "target": 75, "tolerance_pct": 5},
        {"name": "pair", "layer": "L1_TOP", "width": 0.25, "spacing": 0.18, "target": 90},
    ]
    cfg = load_config_dict(raw)
    rs = get_solver("si")().run(SolverContext(cfg.board, cfg.materials))
    rows = {r["name"]: r for r in rs.meta["lines"]}
    assert rows["ok"]["passed"]
    assert not rows["off"]["passed"]
    assert rows["pair"]["quantity"] == "Zdiff"
    assert [v.subject for v in rs.violations if v.check == "z0"] == ["off"]
    assert not [v for v in rs.violations if v.check == "z0_crosscheck"]
    assert rs.scalars["ok.Z0"] == pytest.approx(rows["ok"]["z_fem"])


def test_si_needs_lines_and_valid_options() -> None:
    cfg = load_config_dict(_raw())
    board = cfg.board
    from dataclasses import replace

    empty = replace(board, transmission_lines=())
    with pytest.raises(SolverError, match="transmission_lines"):
        get_solver("si")().run(SolverContext(empty, cfg.materials))
    with pytest.raises(SolverError, match="si options"):
        get_solver("si")({"mesh": "ultra"}).run(SolverContext(board, cfg.materials))


def test_config_validation() -> None:
    raw = _raw()
    raw["transmission_lines"] = [{"name": "x", "layer": "NOPE", "width": 0.2}]
    with pytest.raises(ConfigError, match="NOPE"):
        load_config_dict(raw)
    raw["transmission_lines"] = [{"name": "x", "layer": "L1_TOP", "width": -1}]
    with pytest.raises(ConfigError, match="width"):
        load_config_dict(raw)


def test_cli_run_si(tmp_path: Path) -> None:
    buf = io.StringIO()
    code = main(["run", str(EXAMPLE), "--solver", "si", "--no-plots", "--out", str(tmp_path)],
                out=buf)  # fmt: skip
    assert code == EXIT_OK, buf.getvalue()
    text = buf.getvalue()
    assert "ddr_dq" in text
    assert "Zdiff" in text
    import json

    doc = json.loads((tmp_path / "results.json").read_text())
    assert len(doc["solvers"]["si"]["lines"]) == 3


def test_cli_run_si_violation(tmp_path: Path) -> None:
    raw = _raw()
    raw["transmission_lines"] = [{"name": "bad", "layer": "L1_TOP", "width": 0.1, "target": 50}]
    raw["analysis"]["solvers"] = ["si"]
    raw["analysis"]["options"] = {}
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(raw))
    buf = io.StringIO()
    assert main(["run", str(cfg), "--no-plots", "--out", str(tmp_path / "o")], out=buf) == (
        EXIT_VIOLATIONS
    )
    assert "from target 50" in buf.getvalue()


def test_cli_z0_calculator() -> None:
    buf = io.StringIO()
    assert main(["z0", "microstrip", "-w", "0.36", "-H", "0.2", "-t", "35um", "--er", "4.2"],
                out=buf) == EXIT_OK  # fmt: skip
    lines = buf.getvalue().splitlines()
    fem = next(ln for ln in lines if ln.strip().startswith("fem-2d"))
    hj = next(ln for ln in lines if "hammerstad" in ln)
    z_fem, z_hj = float(fem.split()[1]), float(hj.split()[1])
    assert math.isclose(z_fem, z_hj, rel_tol=0.02)
    buf = io.StringIO()
    assert main(["z0", "stripline", "-w", "0.15", "-H", "0.5", "-s", "0.2", "--er", "4"],
                out=buf) == EXIT_OK  # fmt: skip
    assert "cohn-exact" in buf.getvalue()
    assert "Zdiff" in buf.getvalue()
