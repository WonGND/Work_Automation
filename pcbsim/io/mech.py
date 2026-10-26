"""Mechanical-drawing dispatcher: DXF, DWG (via converter) or STEP by file suffix."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import MechDrawing

__all__ = ["merge_drawings", "read_mech"]


def read_mech(path: str | Path, **kw: Any) -> MechDrawing:
    """Read ``.dxf`` / ``.dwg`` / ``.step`` / ``.stp``; ``kw`` go to the DXF reader."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".dxf":
        from pcbsim.io.dxf import read_dxf

        return read_dxf(p, **kw)
    if suffix == ".dwg":
        from pcbsim.io.dwg import read_dwg

        return read_dwg(p, **kw)
    if suffix in (".step", ".stp"):
        from pcbsim.io.step import read_step

        return read_step(p)
    raise CadFormatError(
        f"{p}: unsupported mechanical file type {p.suffix!r} (use .dxf, .dwg, .step or .stp)"
    )


def merge_drawings(a: MechDrawing, b: MechDrawing) -> MechDrawing:
    """Concatenate two drawings (both already in metres); metadata from ``a``."""
    return MechDrawing(
        path=a.path if a.path is not None else b.path,
        unit_scale=a.unit_scale,
        insunits=a.insunits,
        items=[*a.items, *b.items],
        circles=[*a.circles, *b.circles],
        meshes=[*a.meshes, *b.meshes],
        boxes=[*a.boxes, *b.boxes],
        warnings=[*a.warnings, *b.warnings],
    )
