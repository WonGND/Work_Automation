"""Shared result types of the ECAD (Gerber / Excellon) and MCAD (DXF / DWG / STEP) readers.

Every coordinate and length is SI (metres); readers convert from the file's
unit (inch, mm, DXF ``$INSUNITS``) at the I/O boundary. Angles are degrees,
counter-clockwise positive, as in the Gerber and DXF specifications.

2D geometry is :mod:`shapely` (polygons, line strings, points) so that the
registration and check code can use exact set operations (union, difference,
Hausdorff distance) instead of rasterising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

FloatArray = NDArray[np.float64]


# --------------------------------------------------------------------------- ECAD


@dataclass(frozen=True, slots=True)
class Hole:
    """A round drilled hole. ``plated`` is ``None`` when the file does not say."""

    x: float
    y: float
    diameter: float
    plated: bool | None = None
    tool: str = ""


@dataclass(frozen=True, slots=True)
class Slot:
    """A routed / G85 slot of width ``diameter`` from (x0, y0) to (x1, y1)."""

    x0: float
    y0: float
    x1: float
    y1: float
    diameter: float
    plated: bool | None = None
    tool: str = ""


@dataclass(frozen=True, slots=True)
class PlacedComponent:
    """A component placement (Gerber X3 component layer or pick-and-place CSV).

    ``x, y`` is the component reference point (centroid) in board coordinates,
    ``rotation`` in degrees CCW, ``side`` is ``"top"`` or ``"bottom"``.
    ``height`` (m) is filled from X3 ``TO.CHgt`` or the CSV when present.
    """

    ref: str
    x: float
    y: float
    rotation: float = 0.0
    side: str = "top"
    footprint: str = ""
    value: str = ""
    height: float | None = None


@dataclass(frozen=True, slots=True)
class Flash:
    """A flashed aperture (D03): pad, via pad, fiducial, component reference point."""

    x: float
    y: float
    aperture: str
    attributes: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(slots=True)
class GerberLayer:
    """One parsed Gerber file.

    ``function`` is the X2 ``.FileFunction`` value split on commas, e.g.
    ``("Copper", "L1", "Top")``, ``("Profile", "NP")``, ``("Component", "L1", "Top")``;
    empty when the file carries no X2 attributes (then guessed from the file
    name, see :func:`pcbsim.io.gerber.guess_function`).
    ``geometry`` is the dark image after applying LPD/LPC in order.
    ``paths`` holds the centre lines of every D01 stroke / arc and every region
    contour (closed) — used to rebuild board outlines independent of line width.
    """

    path: Path | None
    function: tuple[str, ...] = ()
    side: str | None = None
    geometry: BaseGeometry | None = None
    flashes: list[Flash] = field(default_factory=list)
    components: list[PlacedComponent] = field(default_factory=list)
    file_attributes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    paths: list[LineString] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return self.function[0] if self.function else ""


@dataclass(slots=True)
class DrillData:
    path: Path | None
    holes: list[Hole] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    unit: str = "mm"
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- MCAD


@dataclass(frozen=True, slots=True)
class MechCircle:
    """A full circle in the drawing (hole candidate)."""

    layer: str
    x: float
    y: float
    diameter: float


@dataclass(frozen=True, slots=True)
class MechItem:
    """A 2D / 2.5D drawing item.

    ``geometry`` is the XY footprint (closed shapes → ``Polygon``, open ones →
    ``LineString``). ``z_base`` is the DXF elevation and ``height`` the
    extrusion thickness, so the item occupies ``[z_base, z_base + height]``
    (``height`` 0 when the drawing is purely 2D).
    """

    layer: str
    kind: str
    geometry: BaseGeometry
    z_base: float = 0.0
    height: float = 0.0
    handle: str = ""

    @property
    def z_top(self) -> float:
        return self.z_base + self.height


@dataclass(frozen=True, slots=True)
class Mesh3D:
    """Triangle / quad mesh (3DFACE, POLYFACE, MESH). ``vertices`` (N, 3) in metres."""

    layer: str
    vertices: FloatArray
    faces: tuple[tuple[int, ...], ...]
    kind: str = "MESH"

    @property
    def z_min(self) -> float:
        return float(np.min(self.vertices[:, 2])) if len(self.vertices) else 0.0

    @property
    def z_max(self) -> float:
        return float(np.max(self.vertices[:, 2])) if len(self.vertices) else 0.0


@dataclass(frozen=True, slots=True)
class Box3D:
    """Axis-aligned bounding box of a 3D part (STEP), metres."""

    name: str
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float


@dataclass(slots=True)
class MechDrawing:
    """A parsed mechanical drawing. ``unit_scale`` converts drawing units to metres."""

    path: Path | None
    unit_scale: float = 1e-3
    insunits: int = 0
    items: list[MechItem] = field(default_factory=list)
    circles: list[MechCircle] = field(default_factory=list)
    meshes: list[Mesh3D] = field(default_factory=list)
    boxes: list[Box3D] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def layers(self) -> set[str]:
        return (
            {i.layer for i in self.items}
            | {c.layer for c in self.circles}
            | {m.layer for m in self.meshes}
        )
