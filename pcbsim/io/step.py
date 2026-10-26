"""Optional STEP (ISO 10303-21) support: per-solid axis-aligned bounding boxes.

STEP B-rep geometry needs a real CAD kernel; pcbsim uses the optional
``cadquery`` package (which bundles the OpenCascade ``OCP`` bindings) and is
imported lazily so the rest of pcbsim works without it::

    pip install 'pcbsim[step]'

OpenCascade works in millimetres (STEP files are converted to mm on import), so
lengths are scaled by 1e-3 to SI metres. Each solid of the file becomes one
:class:`~pcbsim.io.cad.Box3D` and a footprint rectangle :class:`~pcbsim.io.cad.MechItem`
on layer ``"STEP"`` occupying ``[zmin, zmax]``.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from shapely.geometry import box as shapely_box

from pcbsim.errors import CadFormatError
from pcbsim.io.cad import Box3D, MechDrawing, MechItem

__all__ = ["read_step", "read_step_boxes", "step_available"]

_MM = 1e-3
_MISSING = "STEP support needs the optional dependency: pip install 'pcbsim[step]' (cadquery)"


def _cadquery() -> Any:
    try:
        return importlib.import_module("cadquery")
    except Exception as exc:  # ImportError, or broken native OCP libraries
        raise CadFormatError(_MISSING) from exc


def step_available() -> bool:
    """True when ``cadquery`` (and therefore OCP) can be imported."""
    try:
        _cadquery()
    except CadFormatError:
        return False
    return True


def _solid_label(solid: Any) -> str:
    label = getattr(solid, "label", None)
    if isinstance(label, str) and label.strip():
        return label.strip()
    return ""


def read_step_boxes(path: str | Path) -> list[Box3D]:
    """One bounding box (metres) per solid in the STEP file."""
    p = Path(path)
    cq = _cadquery()
    if not p.is_file():
        raise CadFormatError(f"{p}: STEP file not found")
    try:
        wp = cq.importers.importStep(str(p))
    except Exception as exc:
        raise CadFormatError(f"{p}: cannot read STEP file: {exc}") from exc
    solids: list[Any] = []
    for obj in wp.vals():
        if hasattr(obj, "Solids"):
            solids.extend(obj.Solids())
    if not solids:
        raise CadFormatError(f"{p}: STEP file contains no solids")
    boxes: list[Box3D] = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        boxes.append(
            Box3D(
                name=_solid_label(solid) or f"solid_{i}",
                xmin=float(bb.xmin) * _MM,
                ymin=float(bb.ymin) * _MM,
                zmin=float(bb.zmin) * _MM,
                xmax=float(bb.xmax) * _MM,
                ymax=float(bb.ymax) * _MM,
                zmax=float(bb.zmax) * _MM,
            )
        )
    return boxes


def boxes_to_drawing(boxes: list[Box3D], path: Path | None = None) -> MechDrawing:
    """Wrap boxes in a :class:`MechDrawing` with one footprint item per box."""
    drawing = MechDrawing(path=path, unit_scale=_MM, boxes=list(boxes))
    for b in boxes:
        drawing.items.append(
            MechItem(
                layer="STEP",
                kind="STEP",
                geometry=shapely_box(b.xmin, b.ymin, b.xmax, b.ymax),
                z_base=b.zmin,
                height=b.zmax - b.zmin,
                handle=b.name,
            )
        )
    return drawing


def read_step(path: str | Path) -> MechDrawing:
    """Read a STEP file as a :class:`MechDrawing` of per-solid boxes."""
    p = Path(path)
    return boxes_to_drawing(read_step_boxes(p), p)
