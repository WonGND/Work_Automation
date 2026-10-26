"""Internal data model (SI units throughout)."""

from __future__ import annotations

from pcbsim.model.board import (
    Board,
    Component,
    Criteria,
    CurrentDensityMethod,
    Net,
    NetKind,
    Port,
    PortKind,
    Shape,
    Side,
    SinkDistribution,
    ThermalBoundary,
    ThermalBoundaryKind,
    Via,
)
from pcbsim.model.geometry import Polygon
from pcbsim.model.stackup import Layer, LayerKind, LayerRole, Stackup

__all__ = [
    "Board",
    "Component",
    "Criteria",
    "CurrentDensityMethod",
    "Layer",
    "LayerKind",
    "LayerRole",
    "Net",
    "NetKind",
    "Polygon",
    "Port",
    "PortKind",
    "Shape",
    "Side",
    "SinkDistribution",
    "Stackup",
    "ThermalBoundary",
    "ThermalBoundaryKind",
    "Via",
]
