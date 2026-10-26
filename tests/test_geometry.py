from __future__ import annotations

import numpy as np
import pytest

from pcbsim.model import Polygon


def test_rectangle_area_bbox() -> None:
    p = Polygon.rectangle(0.0, 0.0, 0.06, 0.04)
    assert p.area() == pytest.approx(0.06 * 0.04)
    assert p.bbox() == (0.0, 0.0, 0.06, 0.04)


def test_reversed_corners_and_orientation_independent() -> None:
    a = Polygon.rectangle(3.0, 2.0, 0.0, 0.0)
    b = Polygon.from_points([[0, 0], [0, 2], [3, 2], [3, 0]])  # clockwise
    assert a.area() == pytest.approx(6.0)
    assert b.area() == pytest.approx(6.0)


def test_closed_ring_accepted() -> None:
    p = Polygon.from_points([[0, 0], [1, 0], [1, 1], [0, 0]])
    assert len(p.outer) == 3
    assert p.area() == pytest.approx(0.5)


def test_polygon_with_hole() -> None:
    p = Polygon.from_points(
        [[0, 0], [10, 0], [10, 10], [0, 10]], holes=[[[4, 4], [6, 4], [6, 6], [4, 6]]]
    )
    assert p.area() == pytest.approx(96.0)
    inside = p.contains([[1, 1], [5, 5], [11, 5], [9.5, 9.5]])
    assert inside.tolist() == [True, False, False, True]


def test_circle_area_converges() -> None:
    r = 1.0
    err_coarse = abs(Polygon.circle(0, 0, r, 16).area() - np.pi)
    err_fine = abs(Polygon.circle(0, 0, r, 256).area() - np.pi)
    assert err_fine < err_coarse
    assert err_fine / np.pi < 1e-3


def test_path_is_compound() -> None:
    p = Polygon.from_points([[0, 0], [4, 0], [4, 4], [0, 4]], holes=[[[1, 1], [2, 1], [2, 2]]])
    assert np.asarray(p.path().vertices).shape == (5 + 4, 2)


def test_translated() -> None:
    p = Polygon.rectangle(0, 0, 1, 1).translated(2, 3)
    assert p.bbox() == (2, 3, 3, 4)


def test_boundary_points_covered_but_not_contained() -> None:
    p = Polygon.rectangle(0, 0, 1, 1)
    edge = [[0.0, 0.5], [1.0, 1.0], [0.5, 0.0]]
    assert p.covers(edge).all()
    assert p.distance_to_boundary([[0.5, 0.5], [2.0, 0.5]]) == pytest.approx([0.5, 1.0])
    assert not p.covers([[1.01, 0.5]])[0]
    assert p.contains_polygon_bbox(Polygon.rectangle(0, 0, 1, 1))
    assert not p.contains_polygon_bbox(Polygon.rectangle(0.5, 0.5, 1.5, 1.0))


@pytest.mark.parametrize("pts", [[[0, 0], [1, 1]], [[0, 0, 0], [1, 0, 0], [1, 1, 0]]])
def test_invalid_rings(pts: list[list[float]]) -> None:
    with pytest.raises(ValueError, match="ring"):
        Polygon.from_points(pts)
