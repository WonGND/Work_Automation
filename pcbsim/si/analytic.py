"""Closed-form characteristic impedance of PCB transmission lines.

All inputs SI (metres), quasi-TEM, lossless, non-magnetic.

Microstrip — Hammerstad & Jensen (1980), with the thickness correction
    u = w/h. Effective width for a strip of thickness t (HJ eq. 4–6)::

        Δu₁ = (t/h)/π · ln(1 + 4e / ((t/h)·coth²(√(6.517 u))))
        Δu_r = ½ (1 + 1/cosh √(εr − 1)) · Δu₁

    Zero-thickness impedance in air (HJ eq. 1, error < 0.01 % for u ≤ 1000)::

        f(u)  = 6 + (2π − 6)·exp(−(30.666/u)^0.7528)
        Z01(u) = η₀/(2π) · ln( f/u + √(1 + (2/u)²) )

    Effective permittivity (HJ eq. 2–3, error < 0.2 % for εr ≤ 128, 0.01 ≤ u ≤ 100)::

        a = 1 + ln((u⁴ + (u/52)²)/(u⁴ + 0.432))/49 + ln(1 + (u/18.1)³)/18.7
        b = 0.564·((εr − 0.9)/(εr + 3))^0.053
        εe(u) = (εr+1)/2 + (εr−1)/2 · (1 + 10/u)^(−a·b)

    With thickness: Z0 = Z01(u_r)/√εe(u_r) and εe = εe(u_r)·(Z01(u₁)/Z01(u_r))²,
    u₁ = u + Δu₁, u_r = u + Δu_r [Hammerstad-Jensen], [Wadell] §3.5.

IPC-2141A (approximate, documented validity 0.1 < w/h < 2.0, 1 < εr < 15)
    Microstrip:      Z0 = 87/√(εr + 1.41) · ln(5.98 h / (0.8 w + t))
    Stripline:       Z0 = 60/√εr · ln(1.9 b / (0.8 w + t))      (b = plane spacing)
    Edge-coupled differential microstrip:
                     Zdiff = 2 Z0 (1 − 0.48 exp(−0.96 s/h))
    Edge-coupled differential stripline:
                     Zdiff = 2 Z0 (1 − 0.347 exp(−2.9 s/b))

    Offset (dual / asymmetric) stripline, trace thickness t, h₁ to the nearer
    and h₂ to the farther plane:
                     Z0 = 80/√εr · ln(1.9 (2h₁ + t)/(0.8 w + t)) · (1 − h₁/(4 (h₁ + h₂ + t)))

Thick centred stripline — Wheeler (1978), [Wadell] §4.2.2.2, error ≤ 0.5 % for w′/(b − t) < 10
    x = t/b,  m = 6 / (3 + 2x/(1 − x))
    Δw/(b − t) = x/(π(1 − x)) · (1 − ½ ln[(x/(2 − x))² + (0.0796 x/(w/b + 1.1 x))^m])
    W = w/(b − t) + Δw/(b − t)
    Z0 = 30/√εr · ln(1 + 4/(π W) · [8/(π W) + √((8/(π W))² + 6.27)])

Exact zero-thickness centred stripline — Cohn (1954), conformal mapping
    k = sech(π w / (2 b)),  k' = tanh(π w / (2 b))
    Z0 = η₀/(4√εr) · K(k)/K(k')        (K = complete elliptic integral)

Exact zero-thickness edge-coupled centred stripline — Cohn (1955)
    k_e = tanh(π w/(2b)) · tanh(π (w + s)/(2b))
    k_o = tanh(π w/(2b)) · coth(π (w + s)/(2b))
    Z_{e,o} = η₀/(4√εr) · K(k'_{e,o})/K(k_{e,o}),   Zdiff = 2 Z_o

η₀ = μ₀ c₀ (≈ 376.73 Ω). The elliptic integrals use :func:`scipy.special.ellipk`,
whose argument is the parameter m = k².
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.special import ellipk

from pcbsim.errors import SolverError

C0 = 299_792_458.0
MU0 = 1.25663706212e-6
ETA0 = MU0 * C0


@dataclass(frozen=True, slots=True)
class LineZ:
    """Impedance result. ``z_diff``/``z_odd``/``z_even`` only for coupled lines."""

    z0: float
    eps_eff: float
    z_odd: float | None = None
    z_even: float | None = None
    z_diff: float | None = None
    method: str = ""
    valid: bool = True
    note: str = ""


def _check_pos(**kw: float) -> None:
    for k, v in kw.items():
        if not (v > 0 and math.isfinite(v)):
            raise SolverError(f"{k} must be > 0, got {v!r}")


def _k_ratio(k: float) -> float:
    """K(k)/K(k') with k' = √(1 − k²)."""
    return float(ellipk(k * k) / ellipk(1.0 - k * k))


# --------------------------------------------------------------------------- microstrip


def _hj_z01(u: float) -> float:
    f = 6.0 + (2.0 * math.pi - 6.0) * math.exp(-((30.666 / u) ** 0.7528))
    return ETA0 / (2.0 * math.pi) * math.log(f / u + math.sqrt(1.0 + (2.0 / u) ** 2))


def _hj_eps(u: float, er: float) -> float:
    a = (
        1.0
        + math.log((u**4 + (u / 52.0) ** 2) / (u**4 + 0.432)) / 49.0
        + math.log(1.0 + (u / 18.1) ** 3) / 18.7
    )
    b = 0.564 * ((er - 0.9) / (er + 3.0)) ** 0.053
    return float((er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 10.0 / u) ** (-a * b))


def microstrip_hj(w: float, h: float, er: float, t: float = 0.0) -> LineZ:
    """Hammerstad–Jensen microstrip Z0 and εeff (thickness-corrected if t > 0)."""
    _check_pos(w=w, h=h, er=er)
    u = w / h
    if t > 0:
        tn = t / h
        coth2 = 1.0 / math.tanh(math.sqrt(6.517 * u)) ** 2
        du1 = tn / math.pi * math.log(1.0 + 4.0 * math.e / (tn * coth2))
        dur = 0.5 * (1.0 + 1.0 / math.cosh(math.sqrt(er - 1.0))) * du1
        u1, ur = u + du1, u + dur
        z01_r = _hj_z01(ur)
        eps = _hj_eps(ur, er) * (_hj_z01(u1) / z01_r) ** 2
        z0 = z01_r / math.sqrt(_hj_eps(ur, er))
    else:
        eps = _hj_eps(u, er)
        z0 = _hj_z01(u) / math.sqrt(eps)
    valid = 0.01 <= u <= 100.0 and er <= 128.0
    return LineZ(
        z0,
        eps,
        method="hammerstad-jensen",
        valid=valid,
        note="" if valid else "outside HJ validity (0.01 ≤ w/h ≤ 100)",
    )


def microstrip_ipc(w: float, h: float, er: float, t: float = 0.0) -> LineZ:
    """IPC-2141A microstrip approximation."""
    _check_pos(w=w, h=h, er=er)
    arg = 5.98 * h / (0.8 * w + t)
    if arg <= 1.0:
        raise SolverError("IPC-2141 microstrip formula undefined for 0.8w + t ≥ 5.98h")
    z0 = 87.0 / math.sqrt(er + 1.41) * math.log(arg)
    valid = 0.1 < w / h < 2.0 and 1.0 < er < 15.0
    return LineZ(
        z0,
        math.nan,
        method="ipc-2141",
        valid=valid,
        note="" if valid else "outside IPC-2141 validity (0.1 < w/h < 2)",
    )


def diff_microstrip_ipc(w: float, s: float, h: float, er: float, t: float = 0.0) -> LineZ:
    single = microstrip_ipc(w, h, er, t)
    zd = 2.0 * single.z0 * (1.0 - 0.48 * math.exp(-0.96 * s / h))
    return LineZ(
        single.z0,
        math.nan,
        z_odd=zd / 2,
        z_diff=zd,
        method="ipc-2141",
        valid=single.valid,
        note=single.note,
    )


# --------------------------------------------------------------------------- stripline


def stripline_cohn(w: float, b: float, er: float) -> LineZ:
    """Exact zero-thickness centred stripline (Cohn)."""
    _check_pos(w=w, b=b, er=er)
    x = math.pi * w / (2.0 * b)
    k = 1.0 / math.cosh(x)
    z0 = ETA0 / (4.0 * math.sqrt(er)) * _k_ratio(k)
    return LineZ(z0, er, method="cohn-exact")


def stripline_ipc(w: float, b: float, er: float, t: float = 0.0) -> LineZ:
    """IPC-2141A centred stripline approximation (b = plane-to-plane spacing)."""
    _check_pos(w=w, b=b, er=er)
    arg = 1.9 * b / (0.8 * w + t)
    if arg <= 1.0:
        raise SolverError("IPC-2141 stripline formula undefined for 0.8w + t ≥ 1.9b")
    z0 = 60.0 / math.sqrt(er) * math.log(arg)
    valid = w / (b - t) < 0.35 and t / b < 0.25 if b > t else False
    return LineZ(
        z0,
        er,
        method="ipc-2141",
        valid=valid,
        note="" if valid else "outside IPC-2141 validity (w/(b−t) < 0.35, t/b < 0.25)",
    )


def stripline_wheeler(w: float, b: float, t: float, er: float) -> LineZ:
    """Wheeler's thick centred stripline (reduces to ≈ Cohn for t → 0)."""
    _check_pos(w=w, b=b, er=er)
    if not 0.0 <= t < b:
        raise SolverError("stripline needs 0 ≤ t < b")
    x = t / b
    if x > 0:
        m = 6.0 / (3.0 + 2.0 * x / (1.0 - x))
        dw = (
            x
            / (math.pi * (1.0 - x))
            * (1.0 - 0.5 * math.log((x / (2.0 - x)) ** 2 + (0.0796 * x / (w / b + 1.1 * x)) ** m))
        )
    else:
        dw = 0.0
    big_w = w / (b - t) + dw
    a = 8.0 / (math.pi * big_w)
    z0 = (
        30.0
        / math.sqrt(er)
        * math.log(1.0 + 4.0 / (math.pi * big_w) * (a + math.sqrt(a * a + 6.27)))
    )
    valid = big_w < 10.0
    return LineZ(
        z0,
        er,
        method="wheeler",
        valid=valid,
        note="" if valid else "outside Wheeler validity (w'/(b−t) < 10)",
    )


def stripline_dual_ipc(w: float, t: float, h1: float, h2: float, er: float) -> LineZ:
    """IPC-2141A offset stripline; ``h1`` = dielectric to the nearer plane."""
    _check_pos(w=w, h1=h1, h2=h2, er=er)
    arg = 1.9 * (2.0 * h1 + t) / (0.8 * w + t)
    if arg <= 1.0:
        raise SolverError("IPC-2141 dual stripline formula undefined for this geometry")
    z0 = 80.0 / math.sqrt(er) * math.log(arg) * (1.0 - h1 / (4.0 * (h1 + h2 + t)))
    return LineZ(z0, er, method="ipc-2141-dual")


def coupled_stripline_cohn(w: float, s: float, b: float, er: float) -> LineZ:
    """Exact zero-thickness edge-coupled centred stripline (Cohn)."""
    _check_pos(w=w, s=s, b=b, er=er)
    a = math.tanh(math.pi * w / (2.0 * b))
    c = math.tanh(math.pi * (w + s) / (2.0 * b))
    ke, ko = a * c, a / c
    pref = ETA0 / (4.0 * math.sqrt(er))
    ze = pref / _k_ratio(ke)
    zo = pref / _k_ratio(ko)
    single = stripline_cohn(w, b, er).z0
    return LineZ(single, er, z_odd=zo, z_even=ze, z_diff=2.0 * zo, method="cohn-exact")


def diff_stripline_ipc(w: float, s: float, b: float, er: float, t: float = 0.0) -> LineZ:
    single = stripline_ipc(w, b, er, t)
    zd = 2.0 * single.z0 * (1.0 - 0.347 * math.exp(-2.9 * s / b))
    return LineZ(
        single.z0,
        er,
        z_odd=zd / 2,
        z_diff=zd,
        method="ipc-2141",
        valid=single.valid,
        note=single.note,
    )
