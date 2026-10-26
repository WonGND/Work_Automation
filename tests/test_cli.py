from __future__ import annotations

import io
from pathlib import Path

import pytest

from pcbsim.cli import EXIT_INVALID, EXIT_NOT_IMPLEMENTED, EXIT_OK, EXIT_USAGE, main

EXAMPLE = str(Path(__file__).resolve().parents[1] / "examples" / "soc_4layer.yaml")


def test_check_example() -> None:
    buf = io.StringIO()
    assert main(["check", EXAMPLE], out=buf) == EXIT_OK
    text = buf.getvalue()
    assert "4 copper layers" in text
    assert "60.00 × 40.00 mm" in text
    assert "Rs 0.500 mΩ/□" in text
    assert "SOC_CORE" in text
    assert "196.0" in text
    assert "total" in text


def test_check_strict_fails_on_warnings() -> None:
    assert main(["check", "--strict", EXAMPLE], out=io.StringIO()) == EXIT_INVALID


def test_check_invalid_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text("board: {outline: {rect: [0, 0, 1, 1]}, stackup: []}\n")
    assert main(["check", str(f)], out=io.StringIO()) == EXIT_INVALID
    assert "board.stackup" in capsys.readouterr().err


def test_report_not_implemented() -> None:
    assert main(["report", "results"], out=io.StringIO()) == EXIT_NOT_IMPLEMENTED


def test_solvers_list() -> None:
    buf = io.StringIO()
    assert main(["solvers"], out=buf) == EXIT_OK
    assert "dc_ir" in buf.getvalue()


def test_usage_error() -> None:
    assert main([]) == EXIT_USAGE
