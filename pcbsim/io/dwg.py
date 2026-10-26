"""DWG input via external converters (DWG → DXF), then :func:`pcbsim.io.dxf.read_dxf`.

DWG is Autodesk's closed binary format. pcbsim never parses DWG bytes itself; it
shells out to one of two public command-line converters:

* **ODA File Converter** (free, Open Design Alliance). Public CLI::

      ODAFileConverter <in_dir> <out_dir> <out_version> <out_type> <recurse> <audit> [filter]

  e.g. ``ODAFileConverter in out ACAD2018 DXF 0 1 board.dwg``. It converts whole
  directories, so the DWG is copied alone into a temporary input directory.
* **LibreDWG** ``dwg2dxf`` (GNU). Public CLI: ``dwg2dxf -y -o out.dxf in.dwg``
  (``-y`` overwrites an existing output).

Converter discovery (:func:`find_converters`): environment variables ``PCBSIM_ODA`` /
``PCBSIM_DWG2DXF`` (path to the executable) first, else ``PATH`` lookup.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import MechDrawing
from pcbsim.io.dxf import read_dxf

__all__ = ["dwg_to_dxf", "find_converters", "read_dwg"]

_TIMEOUT_S = 120.0

_NO_CONVERTER = """\
cannot read {path}: DWG is a closed binary format that pcbsim does not parse directly.
Install one of these free DWG -> DXF converters and try again:
  - ODA File Converter (free): https://www.opendesign.com/guestfiles/oda_file_converter
  - LibreDWG: `apt install libredwg-tools` (provides dwg2dxf), https://www.gnu.org/software/libredwg/
or point pcbsim at an executable with PCBSIM_ODA=/path/to/ODAFileConverter or
PCBSIM_DWG2DXF=/path/to/dwg2dxf,
or export DXF from your CAD tool (FreeCAD: File -> Export -> AutoDesk DXF)."""


def find_converters() -> dict[str, Path]:
    """Available converters: keys ``"oda"`` and/or ``"libredwg"`` → executable path."""
    found: dict[str, Path] = {}
    env_oda = os.environ.get("PCBSIM_ODA")
    if env_oda:
        found["oda"] = Path(env_oda)
    else:
        exe = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
        if exe:
            found["oda"] = Path(exe)
    env_lib = os.environ.get("PCBSIM_DWG2DXF")
    if env_lib:
        found["libredwg"] = Path(env_lib)
    else:
        exe = shutil.which("dwg2dxf")
        if exe:
            found["libredwg"] = Path(exe)
    return found


def _tail(text: str | bytes | None, n: int = 800) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.strip()
    return text[-n:]


def _run(cmd: list[str], tool: str, src: Path) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CadFormatError(
            f"{src}: {tool} timed out after {_TIMEOUT_S:.0f} s\n{_tail(exc.stderr)}"
        ) from exc
    except OSError as exc:
        raise CadFormatError(f"{src}: cannot run {tool} ({cmd[0]}): {exc}") from exc
    if proc.returncode != 0:
        detail = _tail(proc.stderr) or _tail(proc.stdout)
        raise CadFormatError(f"{src}: {tool} failed with exit code {proc.returncode}\n{detail}")


def dwg_to_dxf(path: Path, out_dir: Path, converter: str | None = None) -> Path:
    """Convert ``path`` (DWG) to a DXF in ``out_dir`` and return the DXF path.

    ``converter`` is ``"oda"`` or ``"libredwg"``; ``None`` picks ODA first.
    """
    path = Path(path)
    out_dir = Path(out_dir)
    if not path.is_file():
        raise CadFormatError(f"{path}: DWG file not found")
    convs = find_converters()
    if converter is not None:
        if converter not in ("oda", "libredwg"):
            raise CadFormatError(f"unknown DWG converter {converter!r} (use 'oda' or 'libredwg')")
        if converter not in convs:
            raise CadFormatError(_NO_CONVERTER.format(path=path))
        name = converter
    elif "oda" in convs:
        name = "oda"
    elif "libredwg" in convs:
        name = "libredwg"
    else:
        raise CadFormatError(_NO_CONVERTER.format(path=path))
    exe = convs[name]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (path.stem + ".dxf")

    if name == "oda":
        with tempfile.TemporaryDirectory(prefix="pcbsim_dwg_in_") as tmp:
            in_dir = Path(tmp)
            shutil.copy2(path, in_dir / path.name)
            cmd = [str(exe), str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1", path.name]
            _run(cmd, "ODA File Converter", path)
        if not out.is_file():
            cands = sorted(out_dir.glob("*.dxf")) + sorted(out_dir.glob("*.DXF"))
            if len(cands) == 1:
                out = cands[0]
    else:
        cmd = [str(exe), "-y", "-o", str(out), str(path)]
        _run(cmd, "LibreDWG dwg2dxf", path)

    if not out.is_file() or out.stat().st_size == 0:
        raise CadFormatError(f"{path}: {name} converter produced no DXF output ({out})")
    return out


def read_dwg(path: str | Path, **dxf_kwargs: Any) -> MechDrawing:
    """Read a DWG file by converting it to DXF in a temporary directory."""
    src = Path(path)
    requested = dxf_kwargs.pop("converter", None)
    convs = find_converters()
    if not convs:
        raise CadFormatError(_NO_CONVERTER.format(path=src))
    tool = str(requested) if requested else ("oda" if "oda" in convs else "libredwg")
    with tempfile.TemporaryDirectory(prefix="pcbsim_dwg_") as tmp:
        dxf_path = dwg_to_dxf(src, Path(tmp), converter=tool)
        drawing = read_dxf(dxf_path, **dxf_kwargs)
    drawing.path = src
    label = "ODA File Converter" if tool == "oda" else "LibreDWG dwg2dxf"
    drawing.warnings.append(f"converted from DWG with {label}")
    return drawing
