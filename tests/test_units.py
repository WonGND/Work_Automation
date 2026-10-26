from __future__ import annotations

import math

import pytest

from pcbsim.errors import UnitError
from pcbsim.units import (
    MIL,
    OZ_CU,
    Kind,
    celsius_to_kelvin,
    from_si,
    kelvin_to_celsius,
    parse_quantity,
    to_si,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 mm", 1e-3),
        ("1.6mm", 1.6e-3),
        ("10 mil", 254e-6),
        ("1 in", 25.4e-3),
        ("35 um", 35e-6),
        ("35 µm", 35e-6),
        ("1 oz", 34.79e-6),
        ("0.5 oz", 17.395e-6),
        ("2e-3 m", 2e-3),
        (1.6, 1.6e-3),
        ("1.6", 1.6e-3),
    ],
)
def test_parse_length(text: str | float, expected: float) -> None:
    assert parse_quantity(text, Kind.LENGTH) == pytest.approx(expected, rel=1e-12)


def test_oz_matches_ipc_nominal() -> None:
    assert from_si(OZ_CU, "mil", "length") == pytest.approx(1.37, abs=0.001)
    assert pytest.approx(34.79e-6) == OZ_CU


@pytest.mark.parametrize("unit", ["mm", "mil", "um", "in", "oz", "m"])
def test_length_roundtrip(unit: str) -> None:
    for v in (0.0, 1.0, 12.345, 1e-3):
        assert from_si(to_si(v, unit, "length"), unit, "length") == pytest.approx(v, rel=1e-12)


def test_mil_exact() -> None:
    assert pytest.approx(25.4e-3, rel=1e-15) == MIL * 1000


def test_temperature() -> None:
    assert parse_quantity(25, "temperature") == pytest.approx(298.15)
    assert parse_quantity("85 C", "temperature") == pytest.approx(358.15)
    assert parse_quantity("300 K", "temperature") == pytest.approx(300.0)
    assert kelvin_to_celsius(celsius_to_kelvin(105.0)) == pytest.approx(105.0)
    assert from_si(373.15, "degC", "temperature") == pytest.approx(100.0)


def test_electrical_units() -> None:
    assert parse_quantity("500 mV", "voltage") == pytest.approx(0.5)
    assert parse_quantity("6 A", "current") == pytest.approx(6.0)
    assert parse_quantity(6, "current") == 6.0
    assert parse_quantity("250 mW", "power") == pytest.approx(0.25)
    assert parse_quantity("5 mohm", "resistance") == pytest.approx(5e-3)
    assert parse_quantity("10 GHz", "frequency") == pytest.approx(1e10)


def test_conductivity_mega_vs_milli() -> None:
    assert parse_quantity("58 MS/m", "conductivity") == pytest.approx(5.8e7)
    assert parse_quantity("5 mS/m", "conductivity") == pytest.approx(5e-3)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("1.5 mll", "length"),
        ("abc", "length"),
        ("3 V", "length"),
        ("1 mm", "temperature"),
        ("", "length"),
    ],
)
def test_bad_units(text: str, kind: str) -> None:
    with pytest.raises(UnitError):
        parse_quantity(text, kind)


def test_bool_rejected() -> None:
    with pytest.raises(UnitError):
        parse_quantity(True, "length")


def test_unknown_kind() -> None:
    with pytest.raises(ValueError, match="nope"):
        parse_quantity("1", "nope")


def test_nan_is_parsed_but_not_finite() -> None:
    assert not math.isfinite(parse_quantity(float("inf"), "voltage"))
