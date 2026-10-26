"""Tests for DWG input via external converters (pcbsim.io.dwg)."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from pcbsim.errors import CadFormatError
from pcbsim.io.dwg import dwg_to_dxf, find_converters, read_dwg
from pcbsim.io.mech import read_mech

_FAKE_DWG2DXF = """#!{python}
import sys

import ezdxf

args = sys.argv[1:]
out = args[args.index("-o") + 1]
src = args[-1]
assert open(src, "rb").read().startswith(b"AC10")
doc = ezdxf.new("R2010", units=4)
doc.modelspace().add_circle((3, 4), 1.5, dxfattribs={{"layer": "HOLES"}})
doc.saveas(out)
"""

_FAILING = """#!{python}
import sys
sys.stderr.write("boom: corrupt file\\n")
sys.exit(3)
"""


def _no_converters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PCBSIM_ODA", raising=False)
    monkeypatch.delenv("PCBSIM_DWG2DXF", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)


def _script(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body.format(python=sys.executable))
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _fake_dwg(tmp_path: Path) -> Path:
    p = tmp_path / "board.dwg"
    p.write_bytes(b"AC1032" + bytes(64))
    return p


def test_no_converter_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_converters(monkeypatch)
    assert find_converters() == {}
    with pytest.raises(CadFormatError) as info:
        read_dwg(_fake_dwg(tmp_path))
    msg = str(info.value)
    assert "ODA" in msg
    assert "LibreDWG" in msg
    assert "PCBSIM_ODA" in msg
    assert "DXF" in msg


def test_find_converters_path_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PCBSIM_ODA", raising=False)
    monkeypatch.delenv("PCBSIM_DWG2DXF", raising=False)
    table = {"ODAFileConverter.exe": "/opt/oda/ODAFileConverter.exe", "dwg2dxf": "/usr/bin/dwg2dxf"}
    monkeypatch.setattr(shutil, "which", table.get)
    found = find_converters()
    assert found == {
        "oda": Path("/opt/oda/ODAFileConverter.exe"),
        "libredwg": Path("/usr/bin/dwg2dxf"),
    }


@pytest.mark.skipif(os.name == "nt", reason="shebang scripts need POSIX")
def test_fake_libredwg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_converters(monkeypatch)
    conv = _script(tmp_path, "dwg2dxf", _FAKE_DWG2DXF)
    monkeypatch.setenv("PCBSIM_DWG2DXF", str(conv))
    assert find_converters() == {"libredwg": conv}
    src = _fake_dwg(tmp_path)
    d = read_dwg(src)
    assert d.path == src
    (c,) = d.circles
    assert c.x == pytest.approx(3e-3)
    assert c.diameter == pytest.approx(3e-3)
    assert any("converted from DWG with" in w and "LibreDWG" in w for w in d.warnings)
    # dispatcher
    d2 = read_mech(src, unit_override="inch")
    assert d2.circles[0].x == pytest.approx(3 * 0.0254)


@pytest.mark.skipif(os.name == "nt", reason="shebang scripts need POSIX")
def test_converter_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_converters(monkeypatch)
    conv = _script(tmp_path, "dwg2dxf", _FAILING)
    monkeypatch.setenv("PCBSIM_DWG2DXF", str(conv))
    out = tmp_path / "out"
    with pytest.raises(CadFormatError, match="boom: corrupt file"):
        dwg_to_dxf(_fake_dwg(tmp_path), out)


def test_requested_converter_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_converters(monkeypatch)
    with pytest.raises(CadFormatError, match="ODA"):
        dwg_to_dxf(_fake_dwg(tmp_path), tmp_path / "out", converter="oda")
