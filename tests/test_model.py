from __future__ import annotations

import math

import pytest

from pcbsim.errors import ModelError
from pcbsim.model import (
    Board,
    Component,
    Layer,
    LayerKind,
    Net,
    NetKind,
    Polygon,
    Port,
    PortKind,
    Shape,
    Stackup,
    Via,
)

MM = 1e-3


def _stackup() -> Stackup:
    return Stackup(
        (
            Layer("L1", LayerKind.CONDUCTOR, 35e-6, "copper"),
            Layer("D1", LayerKind.DIELECTRIC, 1.0 * MM, "fr4"),
            Layer("L2", LayerKind.CONDUCTOR, 35e-6, "copper"),
        )
    )


def _board(**kw: object) -> Board:
    base: dict[str, object] = {
        "name": "t",
        "outline": Polygon.rectangle(0, 0, 10 * MM, 10 * MM),
        "stackup": _stackup(),
        "nets": (Net("VDD", NetKind.POWER, 1.0), Net("GND", NetKind.GROUND)),
    }
    base.update(kw)
    return Board(**base)  # type: ignore[arg-type]


def test_stackup_geometry() -> None:
    s = _stackup()
    assert s.total_thickness == pytest.approx(1.07 * MM)
    assert s.z_top("L1") == 0.0
    assert s.z_top("L2") == pytest.approx(1.035 * MM)
    assert s.z_bottom("L2") == pytest.approx(s.total_thickness)
    assert s.span("L1", "L2") == pytest.approx(1.035 * MM)
    assert [x.name for x in s.layers_between("L1", "L2")] == ["D1"]
    assert [x.name for x in s.conductor_layers()] == ["L1", "L2"]
    with pytest.raises(KeyError):
        s.index("nope")


def test_stackup_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Stackup((Layer("A", LayerKind.CONDUCTOR, 1e-5, "copper"),) * 2)


def test_via_barrel_area() -> None:
    v = Via(
        0, 0, drill=0.3 * MM, from_layer="L1", to_layer="L2", net="VDD", plating_thickness=25e-6
    )
    expected = math.pi / 4 * ((0.3e-3) ** 2 - (0.25e-3) ** 2)
    assert v.barrel_area == pytest.approx(expected)
    assert v.fill_area == 0.0
    vf = Via(0, 0, 0.3 * MM, "L1", "L2", "VDD", filled=True, filler="via_fill_epoxy")
    assert vf.fill_area == pytest.approx(math.pi / 4 * (0.25e-3) ** 2)


def test_valid_board_passes() -> None:
    b = _board(
        shapes=(Shape("VDD", "L1", Polygon.rectangle(0, 0, 5 * MM, 5 * MM)),),
        vias=(Via(1 * MM, 1 * MM, 0.3 * MM, "L1", "L2", "VDD"),),
        components=(Component("U1", Polygon.rectangle(1 * MM, 1 * MM, 3 * MM, 3 * MM), power=1.0),),
        ports=(
            Port("S", PortKind.VOLTAGE_SOURCE, "VDD", "L1", Polygon.rectangle(0, 0, MM, MM), 1.0),
        ),
    )
    b.validate()
    assert b.total_power == 1.0
    assert b.net("VDD").nominal_voltage == 1.0
    assert len(b.shapes_on("L1", "VDD")) == 1
    assert b.shapes_on("L2") == ()


def test_validate_collects_all_problems() -> None:
    b = _board(
        shapes=(
            Shape("NOPE", "L1", Polygon.rectangle(0, 0, MM, MM)),
            Shape("VDD", "D1", Polygon.rectangle(0, 0, MM, MM)),
            Shape("VDD", "LX", Polygon.rectangle(0, 0, MM, MM)),
        ),
        vias=(
            Via(20 * MM, 1 * MM, 0.3 * MM, "L2", "L1", "VDD"),
            Via(1 * MM, 1 * MM, 0.04 * MM, "L1", "L2", "VDD"),
        ),
        components=(
            Component("U1", Polygon.rectangle(8 * MM, 8 * MM, 12 * MM, 12 * MM)),
            Component("U1", Polygon.rectangle(1 * MM, 1 * MM, 2 * MM, 2 * MM), power=-1.0),
        ),
        ports=(
            Port("P", PortKind.CURRENT_SINK, "VDD", "L1", Polygon.rectangle(0, 0, MM, MM), -2.0),
            Port(
                "P", PortKind.CURRENT_SINK, "VDD", "L1", Polygon.rectangle(0, 0, MM, MM), 1.0, "XX"
            ),
        ),
    )
    with pytest.raises(ModelError) as ei:
        b.validate()
    text = "\n".join(ei.value.problems)
    for needle in (
        "unknown net 'NOPE'",
        "'D1' is not a conductor layer",
        "unknown layer 'LX'",
        "from_layer must be above to_layer",
        "outside the board outline",
        "plating thickness exceeds drill radius",
        "duplicate component ref 'U1'",
        "footprint extends outside",
        "power must be >= 0",
        "duplicate port name 'P'",
        "sink current must be >= 0",
        "unknown net 'XX'",
    ):
        assert needle in text, needle


def test_no_conductors() -> None:
    b = _board(stackup=Stackup((Layer("D", LayerKind.DIELECTRIC, 1e-3, "fr4"),)))
    with pytest.raises(ModelError, match="no conductor layers"):
        b.validate()


def test_component_tj_default() -> None:
    c = Component("U", Polygon.rectangle(0, 0, 1, 1))
    assert c.effective_tj_max(378.15) == 378.15
    assert (
        Component("U", Polygon.rectangle(0, 0, 1, 1), tj_max=400.0).effective_tj_max(1.0) == 400.0
    )
