from __future__ import annotations

import pytest

from pcbsim.model import CurrentDensityMethod
from pcbsim.standards import (
    allowed_current_density,
    ipc2152_current,
    ipc2152_width,
    ipc2221_current,
)
from pcbsim.units import MIL, OZ_CU


def test_ipc2221_reference_point() -> None:
    """IPC-2221B chart fit: 10 mil × 1.378 mil external, ΔT = 10 K → ≈ 0.88 A."""
    i = ipc2221_current(10 * MIL, 1.378 * MIL, 10.0, internal=False)
    expected = 0.048 * 10**0.44 * (10 * 1.378) ** 0.725
    assert i == pytest.approx(expected, rel=1e-12)
    assert i == pytest.approx(0.886, abs=0.01)
    assert ipc2221_current(10 * MIL, 1.378 * MIL, 10.0, internal=True) == pytest.approx(i / 2)


def test_ipc2152_brooks_adam_external_closed_form() -> None:
    w, th, dt = 100.0, 1.378, 10.0
    i = ipc2152_current(w * MIL, th * MIL, dt, internal=False)
    assert dt == pytest.approx(215.3 * i**2 * w**-1.15 * th**-1.0, rel=1e-12)


def test_ipc2152_internal_picks_nearest_weight() -> None:
    w, dt = 100.0, 10.0
    i = ipc2152_current(w * MIL, OZ_CU, dt, internal=True)
    th = OZ_CU / MIL
    assert dt == pytest.approx(200.0 * i**1.9 * w**-1.10 * th**-1.52, rel=1e-12)
    i_half = ipc2152_current(w * MIL, 0.55 * OZ_CU, dt, internal=True)
    th_h = 0.55 * OZ_CU / MIL
    assert dt == pytest.approx(120.0 * i_half**2.0 * w**-1.10 * th_h**-1.52, rel=1e-12)


def test_ipc2152_width_inverse() -> None:
    for internal in (False, True):
        w = ipc2152_width(3.0, OZ_CU, 20.0, internal)
        assert ipc2152_current(w, OZ_CU, 20.0, internal) == pytest.approx(3.0, rel=1e-10)


def test_ipc2152_monotonic() -> None:
    a = ipc2152_current(1e-3, OZ_CU, 10.0, False)
    assert ipc2152_current(2e-3, OZ_CU, 10.0, False) > a
    assert ipc2152_current(1e-3, OZ_CU, 20.0, False) > a
    assert ipc2152_current(1e-3, 2 * OZ_CU, 10.0, False) > a


def test_allowed_current_density() -> None:
    j = allowed_current_density(CurrentDensityMethod.IPC2152, OZ_CU, 10.0, False, 1e-3)
    assert j is not None
    assert j == pytest.approx(ipc2152_current(1e-3, OZ_CU, 10.0, False) / (1e-3 * OZ_CU))
    assert 20e6 < j < 200e6
    assert allowed_current_density(CurrentDensityMethod.NONE, OZ_CU, 10.0, False) is None
    j21 = allowed_current_density(CurrentDensityMethod.IPC2221, OZ_CU, 10.0, True)
    assert j21 is not None


@pytest.mark.parametrize(
    ("args", "fn"),
    [((0.0, OZ_CU, 10.0, False), ipc2152_current), ((1e-3, OZ_CU, 0.0, False), ipc2221_current)],
)
def test_invalid_inputs(args: tuple[float, float, float, bool], fn: object) -> None:
    with pytest.raises(ValueError, match="> 0"):
        fn(*args)  # type: ignore[operator]
