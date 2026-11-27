"""Tests for ``pcbsim report`` (pcbsim/post/report*.py, results_loader.py)."""

from __future__ import annotations

import base64
import copy
import io
import json
from pathlib import Path
from typing import Any

import pytest

from pcbsim.cli import EXIT_INVALID, EXIT_OK, EXIT_USAGE, EXIT_VIOLATIONS, main
from pcbsim.errors import ResultsError
from pcbsim.post.report import render_report
from pcbsim.post.results_loader import load_results

# 1×1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

PORTS = [
    {
        "name": "VRM",
        "kind": "voltage_source",
        "net": "VDD",
        "layer": "L1",
        "reference_net": "GND",
        "voltage": 1.0,
        "current": 2.0,
        "power": 2.0,
    },
    {
        "name": "SOC",
        "kind": "current_sink",
        "net": "VDD",
        "layer": "L1",
        "current": 2.0,
        "v_nominal": 1.0,
        "v_avg": 0.99,
        "v_min": 0.985,
        "drop_v": 0.015,
        "drop_pct": 1.5,
        "r_path": 0.0075,
        "limit_pct": 3.0,
        "passed": True,
    },
]
VIAS = [
    {
        "index": 0,
        "net": "VDD",
        "x": 0.001,
        "y": 0.002,
        "current": 0.5,
        "limit": 2.0,
        "passed": True,
    },
    {
        "index": 1,
        "net": "VDD",
        "x": 0.003,
        "y": 0.002,
        "current": 0.4,
        "limit": None,
        "passed": True,
    },
]
COMPS = [
    {
        "ref": "U1",
        "power": 1.0,
        "model": "two_resistor",
        "tj": 330.0,
        "tj_peak": 330.0,
        "t_board": 325.0,
        "tj_max": 378.15,
        "margin": 48.15,
        "passed": True,
    }
]


def _entry(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "passed": True,
        "scalars": {},
        "violations": [],
        "ports": [],
        "vias": [],
        "components": [],
        "history": {},
        "lines": [],
    }
    base.update(kw)
    return base


def _doc() -> dict[str, Any]:
    return {
        "pcbsim_version": "0.1.0",
        "board": "test<board>",
        "source": "C:/cfg/<script>.yaml",
        "units": {},
        "mesh": {"dx": 2.5e-4, "dy": 2.5e-4, "nx": 40, "ny": 20, "layers": ["L1", "L2"]},
        "passed": True,
        "solvers": {
            "dc_ir": _entry(
                ports=PORTS,
                vias=VIAS,
                scalars={"joule_power": 0.03, "L1.j_max": 2e7, "L1.j_limit": 5e7},
            ),
            "thermal": _entry(components=COMPS, scalars={"L1.t_max": 331.0, "t_max": 331.0}),
            "coupled": _entry(
                ports=PORTS,
                components=COMPS,
                scalars={
                    "iterations": 2.0,
                    "converged": 1.0,
                    "delta_t": 0.001,
                    "delta_v": 1e-7,
                    "SOC.drop_pct.uncoupled": 1.4,
                    "U1.tj.uncoupled": 329.9,
                },
                history={
                    "iteration": [0, 1, 2],
                    "delta_t": [None, 0.5, 0.001],
                    "delta_v": [None, 1e-4, 1e-7],
                    "t_max": [331.0, 331.1, 331.1],
                    "joule_power": [0.03, 0.031, 0.031],
                    "drop_pct_max": [1.4, 1.5, 1.5],
                },
            ),
            "si": _entry(
                lines=[
                    {
                        "name": "dq",
                        "topology": "microstrip",
                        "layer": "L1",
                        "quantity": "Z0",
                        "z_fem": 49.0,
                        "z_formula": 50.0,
                        "formula": "Hammerstad-Jensen",
                        "crosscheck_dev": -0.02,
                        "eps_eff_fem": 3.2,
                        "target": 50.0,
                        "tolerance_pct": 10.0,
                        "target_dev_pct": -2.0,
                        "passed": True,
                    }
                ]
            ),
        },
    }


def _write(tmp: Path, doc: dict[str, Any], images: bool = True) -> Path:
    d = tmp / "results"
    d.mkdir()
    (d / "results.json").write_text(json.dumps(doc), "utf-8")
    if images:
        (d / "thermal_temperature_L1.png").write_bytes(PNG)
        (d / "coupled_convergence.png").write_bytes(PNG)
        (d / "fake.png").write_bytes(b"not a png")
    return d


def _run(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    return main(["report", *args], out=buf), buf.getvalue()


def test_success_writes_default_report(tmp_path: Path) -> None:
    d = _write(tmp_path, _doc())
    before = (d / "results.json").read_bytes()
    code, out = _run(str(d))
    assert code == EXIT_OK
    assert "PASS" in out
    html = (d / "report.html").read_text("utf-8")
    assert (d / "results.json").read_bytes() == before
    for section in ("summary", "findings", "power", "vias", "coupled", "si", "maps"):
        assert f'id="{section}"' in html
    assert "PASS — no design violations" in html
    assert "data:image/png;base64," in html  # heat map embedded
    assert "thermal_temperature_L1.png" in html
    assert "fake.png: skipped (not a PNG file)" in html
    assert "Hammerstad-Jensen" in html
    assert "CONVERGED" in html
    assert "not checked" in html  # via without a limit
    # no external resources
    assert "http://" not in html
    assert "https://" not in html


def test_text_is_escaped(tmp_path: Path) -> None:
    html = render_report(load_results(_write(tmp_path, _doc())))
    assert "<script>.yaml" not in html
    assert "&lt;script&gt;.yaml" in html
    assert "test&lt;board&gt;" in html


def test_custom_out_and_results_json_path(tmp_path: Path) -> None:
    d = _write(tmp_path, _doc())
    target = tmp_path / "sub" / "r.html"
    code, _ = _run(str(d / "results.json"), "--out", str(target))
    assert code == EXIT_OK
    assert target.is_file()
    assert not (d / "report.html").exists()


@pytest.mark.parametrize("name", ["results.json", "x.txt"])
def test_bad_out_is_usage_error(tmp_path: Path, name: str) -> None:
    d = _write(tmp_path, _doc())
    before = (d / "results.json").read_bytes()
    code, _ = _run(str(d), "--out", str(d / name))
    assert code == EXIT_USAGE
    assert (d / "results.json").read_bytes() == before


def test_violations_exit_4(tmp_path: Path) -> None:
    doc = _doc()
    doc["passed"] = False
    doc["solvers"]["dc_ir"]["passed"] = False
    doc["solvers"]["dc_ir"]["violations"] = [
        {
            "check": "ir_drop",
            "subject": "SOC",
            "severity": "violation",
            "value": 4.2,
            "limit": 3.0,
            "unit": "%",
            "location": None,
            "message": "SOC drop 4.2 % > 3 %",
        },
        {
            "check": "via_current",
            "subject": "VDD via 1",
            "severity": "warning",
            "value": 2.5,
            "limit": 2.0,
            "unit": "A",
            "location": None,
            "message": "via over limit",
        },
    ]
    d = _write(tmp_path, doc)
    code, out = _run(str(d))
    assert code == EXIT_VIOLATIONS
    assert "1 violation(s), 1 warning(s)" in out
    html = (d / "report.html").read_text("utf-8")
    assert "FAIL — 1 violation(s)" in html
    assert "SOC drop 4.2 % &gt; 3 %" in html
    assert 'class="badge warn"' in html


def test_warnings_only_still_pass(tmp_path: Path) -> None:
    doc = _doc()
    doc["solvers"]["si"]["violations"] = [
        {"check": "z0_crosscheck", "subject": "dq", "severity": "warning", "value": 7.0,
         "limit": 6.0, "unit": "%", "message": "crosscheck"}
    ]  # fmt: skip
    code, _ = _run(str(_write(tmp_path, doc)))
    assert code == EXIT_OK


def test_partial_solvers_and_nulls(tmp_path: Path) -> None:
    doc = _doc()
    doc["solvers"] = {"dc_ir": copy.deepcopy(doc["solvers"]["dc_ir"])}
    sink = doc["solvers"]["dc_ir"]["ports"][1]
    sink["r_path"] = None
    sink["v_min"] = float("nan")
    d = _write(tmp_path, doc, images=False)
    (d / "results.json").write_text(json.dumps(doc), "utf-8")  # NaN literal
    code, _ = _run(str(d))
    assert code == EXIT_OK
    html = (d / "report.html").read_text("utf-8")
    assert "Not run — results.json has no coupled solver results." in html
    assert "Not run — results.json has no si solver results." in html
    assert "Not run — results.json has no thermal / coupled solver results." in html
    assert "No heat-map PNGs" in html
    assert "has no value for v_min, r_path" in html


def test_missing_dir_and_file(tmp_path: Path) -> None:
    assert _run(str(tmp_path / "nope"))[0] == EXIT_INVALID
    assert _run(str(tmp_path))[0] == EXIT_INVALID  # no results.json
    with pytest.raises(ResultsError, match=r"no results\.json"):
        load_results(tmp_path)


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ('{"pcbsim_version": "0.1.0", "solv', "invalid JSON at line 1"),
        ("[1, 2]", "JSON object"),
        ('{"board": "x"}', "not a pcbsim results file"),
        ('{"pcbsim_version": "9.0.0", "solvers": {}}', "major version"),
        ('{"pcbsim_version": "0.1.0", "solvers": []}', "'solvers' must be an object"),
        (
            '{"pcbsim_version": "0.1.0", "solvers": {"dc_ir": {"ports": {}}}}',
            r"solvers\.dc_ir\.ports must be a list",
        ),
    ],
)
def test_broken_results_json(tmp_path: Path, content: str, match: str) -> None:
    (tmp_path / "results.json").write_text(content, "utf-8")
    with pytest.raises(ResultsError, match=match):
        load_results(tmp_path)
    assert _run(str(tmp_path))[0] == EXIT_INVALID
