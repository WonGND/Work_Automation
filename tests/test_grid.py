from __future__ import annotations

import numpy as np
import pytest

from pcbsim.errors import SolverError
from pcbsim.mesh import build_grid
from pcbsim.model import Board, Layer, LayerKind, Net, Polygon, Shape, Stackup

MM = 1e-3


def _board(shapes: tuple[Shape, ...], nets: tuple[str, ...] = ("A",)) -> Board:
    return Board(
        "g",
        Polygon.rectangle(0, 0, 10 * MM, 4 * MM),
        Stackup(
            (
                Layer("L1", LayerKind.CONDUCTOR, 35e-6, "copper"),
                Layer("D", LayerKind.DIELECTRIC, 1e-3, "fr4"),
                Layer("L2", LayerKind.CONDUCTOR, 35e-6, "copper"),
            )
        ),
        nets=tuple(Net(n) for n in nets),
        shapes=shapes,
    )


def test_grid_dimensions_and_extent() -> None:
    g = build_grid(_board(()), 0.5 * MM)
    assert (g.nx, g.ny) == (20, 8)
    assert g.dx == pytest.approx(0.5 * MM)
    assert g.extent == pytest.approx((0, 10 * MM, 0, 4 * MM))
    assert g.layers == ("L1", "L2")
    assert g.copper_cells() == 0
    assert g.xc()[0] == pytest.approx(0.25 * MM)


def test_non_divisible_cell_rounds_up() -> None:
    g = build_grid(_board(()), 0.3 * MM)
    assert g.nx == 34
    assert g.dx == pytest.approx(10 * MM / 34)


def test_rasterisation_area_converges() -> None:
    circle = Polygon.circle(5 * MM, 2 * MM, 1.5 * MM, 256)
    errs = []
    for h in (0.4, 0.2, 0.1, 0.05):
        g = build_grid(_board((Shape("A", "L1", circle),)), h * MM)
        area = g.copper_cells() * g.cell_area
        errs.append(abs(area - circle.area()) / circle.area())
    assert errs[-1] < 0.01
    assert errs[-1] < errs[0]


def test_region_cells_and_fallback() -> None:
    b = _board((Shape("A", "L1", Polygon.rectangle(0, 0, 10 * MM, 4 * MM)),))
    g = build_grid(b, 1 * MM)
    sel = g.region_cells(Polygon.rectangle(0, 0, 2 * MM, 4 * MM), "L1", "A")
    assert int(sel.sum()) == 8
    tiny = g.region_cells(Polygon.rectangle(5.1 * MM, 1.1 * MM, 5.2 * MM, 1.2 * MM), "L1", "A")
    assert int(tiny.sum()) == 1
    assert not g.region_cells(Polygon.rectangle(0, 0, 1, 1), "L2", "A").any()
    assert not g.region_cells(Polygon.rectangle(0, 0, 1, 1), "L1", "nope").any()
    with pytest.raises(SolverError):
        g.layer_index("D")


def test_short_detected() -> None:
    b = _board(
        (
            Shape("A", "L1", Polygon.rectangle(0, 0, 6 * MM, 4 * MM)),
            Shape("B", "L1", Polygon.rectangle(5 * MM, 0, 10 * MM, 4 * MM)),
        ),
        nets=("A", "B"),
    )
    with pytest.raises(SolverError, match="short circuit"):
        build_grid(b, 0.5 * MM)


def test_same_net_overlap_ok_and_holes_respected() -> None:
    ring = Polygon.from_points(
        [[0, 0], [10 * MM, 0], [10 * MM, 4 * MM], [0, 4 * MM]],
        holes=[[[4 * MM, 1 * MM], [6 * MM, 1 * MM], [6 * MM, 3 * MM], [4 * MM, 3 * MM]]],
    )
    b = _board((Shape("A", "L2", ring), Shape("A", "L2", Polygon.rectangle(0, 0, 2 * MM, 2 * MM))))
    g = build_grid(b, 0.5 * MM)
    assert g.copper_cells() == 20 * 8 - 4 * 4
    assert np.all(g.net_map[0] == -1)


def test_bad_cell() -> None:
    with pytest.raises(SolverError):
        build_grid(_board(()), 0.0)
    with pytest.raises(SolverError, match="too fine"):
        build_grid(_board(()), 1e-6)
