"""Conductor current-carrying capacity (IPC-2221 and IPC-2152).

IPC-2221B legacy chart fit (Fig. 6-4, from 1956 NBS data)::

    I = k · ΔT^0.44 · A^0.725         A in mil², I in A, ΔT in K
    k = 0.048 (external), 0.024 (internal)

IPC-2152 (2009) publishes charts only. pcbsim uses the closed-form fit by
Brooks & Adam ("Trace Currents and Temperatures Revisited", 2015, Table 3-1),
the same fit KiCad's track-width calculator uses::

    ΔT = K · I^a · W^b · Th^c          W, Th in mil

    external (all weights): K = 215.3, a = 2.0, b = −1.15, c = −1.0
    internal 0.5 oz:        K = 120,   a = 2.0, b = −1.10, c = −1.52
    internal 1 oz:          K = 200,   a = 1.9, b = −1.10, c = −1.52
    internal 2 oz:          K = 300,   a = 2.0, b = −1.15, c = −1.52
    internal 3 oz:          K = 262.5, a = 1.9, b = −1.15, c = −1.52

Solved for current: ``I = (ΔT / (K · W^b · Th^c))^(1/a)``. Internal coefficients
are picked from the copper weight nearest to the given thickness.

Allowed *current density* for a 2.5D sheet is derived from a reference
conductor of width ``W_ref`` and the layer thickness: ``J = I(W_ref, t) / (W_ref·t)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcbsim.model import CurrentDensityMethod
from pcbsim.units import MIL, OZ_CU


@dataclass(frozen=True, slots=True)
class _Fit:
    k: float
    a: float
    b: float
    c: float


_EXTERNAL = _Fit(215.3, 2.0, -1.15, -1.0)
_INTERNAL: tuple[tuple[float, _Fit], ...] = (
    (0.5, _Fit(120.0, 2.0, -1.10, -1.52)),
    (1.0, _Fit(200.0, 1.9, -1.10, -1.52)),
    (2.0, _Fit(300.0, 2.0, -1.15, -1.52)),
    (3.0, _Fit(262.5, 1.9, -1.15, -1.52)),
)


def _fit(thickness: float, internal: bool) -> _Fit:
    if not internal:
        return _EXTERNAL
    oz = thickness / OZ_CU
    return min(_INTERNAL, key=lambda item: abs(item[0] - oz))[1]


def _check(width: float, thickness: float, temp_rise: float) -> None:
    if width <= 0.0 or thickness <= 0.0 or temp_rise <= 0.0:
        raise ValueError("width, thickness and temperature rise must be > 0")


def ipc2152_current(width: float, thickness: float, temp_rise: float, internal: bool) -> float:
    """Max current [A] of a conductor (SI width/thickness [m]) for a rise ΔT [K]."""
    _check(width, thickness, temp_rise)
    f = _fit(thickness, internal)
    w, th = width / MIL, thickness / MIL
    return float((temp_rise / (f.k * w**f.b * th**f.c)) ** (1.0 / f.a))


def ipc2152_width(current: float, thickness: float, temp_rise: float, internal: bool) -> float:
    """Required conductor width [m] to carry ``current`` [A] with rise ΔT [K]."""
    if current <= 0.0:
        raise ValueError("current must be > 0")
    _check(1.0, thickness, temp_rise)
    f = _fit(thickness, internal)
    th = thickness / MIL
    w_mil = (temp_rise / (f.k * current**f.a * th**f.c)) ** (1.0 / f.b)
    return float(w_mil * MIL)


def ipc2221_current(width: float, thickness: float, temp_rise: float, internal: bool) -> float:
    """Legacy IPC-2221B chart: I = k·ΔT^0.44·A^0.725 (A in mil²)."""
    _check(width, thickness, temp_rise)
    k = 0.024 if internal else 0.048
    area_mil2 = (width / MIL) * (thickness / MIL)
    return float(k * temp_rise**0.44 * area_mil2**0.725)


def allowed_current_density(
    method: CurrentDensityMethod,
    thickness: float,
    temp_rise: float,
    internal: bool,
    ref_width: float = 1e-3,
) -> float | None:
    """Allowed current density [A/m²] for a sheet of ``thickness``; ``None`` = no limit."""
    if method is CurrentDensityMethod.NONE:
        return None
    fn = ipc2152_current if method is CurrentDensityMethod.IPC2152 else ipc2221_current
    return fn(ref_width, thickness, temp_rise, internal) / (ref_width * thickness)
