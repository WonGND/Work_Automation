"""Unit handling — SI internally, engineering units only at I/O boundaries.

Conversion constants
--------------------
* 1 mil = 25.4 µm = 2.54e-5 m (exact, from 1 in = 25.4 mm).
* Copper weight: 1 oz/ft² of copper spread over 1 ft² has thickness

      t = m / (ρ_Cu · A) = 28.3495 g / (8.96 g/cm³ · 929.0304 cm²) ≈ 34.05 µm

  but the PCB industry (IPC-4562, IPC-2152) uses the nominal value
  **1 oz = 1.37 mil = 34.79 µm**; pcbsim uses the IPC nominal value.
* Temperature: T[K] = T[°C] + 273.15.

Quantity strings
----------------
:func:`parse_quantity` accepts ``"10 mil"``, ``"1.6mm"``, ``"0.5 oz"``, ``"25 C"``,
``"6 A"`` … and returns a plain ``float`` in SI. Bare numbers use the default
unit of the requested *kind* (``mm`` for lengths, ``degC`` for temperature, SI
otherwise), which is the convention used in config files.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from pcbsim.errors import UnitError

MM: Final = 1e-3
UM: Final = 1e-6
MIL: Final = 25.4e-6
INCH: Final = 25.4e-3
OZ_CU: Final = 34.79e-6  # IPC-4562 nominal copper thickness per 1 oz/ft²
ZERO_CELSIUS: Final = 273.15


class Kind(StrEnum):
    """Physical dimension of a quantity."""

    LENGTH = "length"
    TEMPERATURE = "temperature"
    VOLTAGE = "voltage"
    CURRENT = "current"
    POWER = "power"
    RESISTANCE = "resistance"
    CONDUCTIVITY = "conductivity"
    FREQUENCY = "frequency"
    TIME = "time"
    HTC = "htc"
    CURRENT_DENSITY = "current_density"
    DIMENSIONLESS = "dimensionless"


# unit symbol -> (scale, offset); SI = value * scale + offset
_UNITS: Final[dict[Kind, dict[str, tuple[float, float]]]] = {
    Kind.LENGTH: {
        "m": (1.0, 0.0),
        "cm": (1e-2, 0.0),
        "mm": (MM, 0.0),
        "um": (UM, 0.0),
        "µm": (UM, 0.0),
        "μm": (UM, 0.0),
        "mil": (MIL, 0.0),
        "mils": (MIL, 0.0),
        "thou": (MIL, 0.0),
        "in": (INCH, 0.0),
        "inch": (INCH, 0.0),
        "oz": (OZ_CU, 0.0),
    },
    Kind.TEMPERATURE: {
        "k": (1.0, 0.0),
        "c": (1.0, ZERO_CELSIUS),
        "degc": (1.0, ZERO_CELSIUS),
        "°c": (1.0, ZERO_CELSIUS),
    },
    Kind.VOLTAGE: {"v": (1.0, 0.0), "mv": (1e-3, 0.0), "uv": (1e-6, 0.0)},
    Kind.CURRENT: {"a": (1.0, 0.0), "ma": (1e-3, 0.0), "ua": (1e-6, 0.0)},
    Kind.POWER: {"w": (1.0, 0.0), "mw": (1e-3, 0.0)},
    Kind.RESISTANCE: {
        "ohm": (1.0, 0.0),
        "ω": (1.0, 0.0),
        "mohm": (1e-3, 0.0),
        "mω": (1e-3, 0.0),
        "uohm": (1e-6, 0.0),
        "kohm": (1e3, 0.0),
    },
    Kind.CONDUCTIVITY: {"s/m": (1.0, 0.0), "ms/m": (1e6, 0.0)},  # MS/m (mega)
    Kind.FREQUENCY: {
        "hz": (1.0, 0.0),
        "khz": (1e3, 0.0),
        "mhz": (1e6, 0.0),
        "ghz": (1e9, 0.0),
    },
    Kind.TIME: {
        "s": (1.0, 0.0),
        "ms": (1e-3, 0.0),
        "us": (1e-6, 0.0),
        "ns": (1e-9, 0.0),
        "min": (60.0, 0.0),
        "h": (3600.0, 0.0),
    },
    Kind.HTC: {"w/m2k": (1.0, 0.0), "w/(m2k)": (1.0, 0.0), "w/m^2k": (1.0, 0.0)},
    Kind.CURRENT_DENSITY: {
        "a/m2": (1.0, 0.0),
        "a/m^2": (1.0, 0.0),
        "a/mm2": (1e6, 0.0),
        "a/mm^2": (1e6, 0.0),
        "a/mil2": (1.0 / MIL**2, 0.0),
        "a/mil^2": (1.0 / MIL**2, 0.0),
    },
    Kind.DIMENSIONLESS: {"": (1.0, 0.0), "%": (0.01, 0.0)},
}

# Default unit for bare numbers in config files.
DEFAULT_UNIT: Final[dict[Kind, str]] = {
    Kind.LENGTH: "mm",
    Kind.TEMPERATURE: "degc",
    Kind.CURRENT_DENSITY: "a/mm2",
}

_QTY_RE: Final = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$")


def _lookup(kind: Kind, unit: str) -> tuple[float, float]:
    table = _UNITS[kind]
    key = unit.strip()
    # MS/m (mega) vs mS/m (milli) is the only case-sensitive pair we need.
    if kind is Kind.CONDUCTIVITY and key == "mS/m":
        return (1e-3, 0.0)
    key = key.lower().replace(" ", "").replace("·", "")
    if key not in table:
        known = ", ".join(sorted(k for k in table if k)) or "(none)"
        raise UnitError(f"unknown {kind.value} unit {unit!r}; expected one of: {known}")
    return table[key]


def to_si(value: float, unit: str, kind: Kind | str) -> float:
    """Convert ``value`` expressed in ``unit`` to SI."""
    k = Kind(kind)
    scale, offset = _lookup(k, unit)
    return float(value) * scale + offset


def from_si(value: float, unit: str, kind: Kind | str) -> float:
    """Convert an SI ``value`` to ``unit``."""
    k = Kind(kind)
    scale, offset = _lookup(k, unit)
    return (float(value) - offset) / scale


def parse_quantity(text: str | float | int, kind: Kind | str) -> float:
    """Parse a quantity like ``"10 mil"`` or ``1.6`` into an SI float.

    Bare numbers are interpreted in :data:`DEFAULT_UNIT` for the kind (mm for
    lengths, °C for temperatures) or SI if no default is defined.

    Raises:
        UnitError: if the string is malformed or the unit is unknown for ``kind``.
    """
    k = Kind(kind)
    if isinstance(text, bool):
        raise UnitError(f"boolean is not a valid {k.value}: {text!r}")
    if isinstance(text, int | float):
        return to_si(float(text), DEFAULT_UNIT.get(k, ""), k) if k in DEFAULT_UNIT else float(text)
    m = _QTY_RE.match(text)
    if m is None:
        raise UnitError(f"cannot parse {k.value} quantity {text!r}")
    number, unit = float(m.group(1)), m.group(2)
    if not unit:
        return parse_quantity(number, k)
    return to_si(number, unit, k)


def celsius_to_kelvin(t_c: float) -> float:
    """°C → K."""
    return t_c + ZERO_CELSIUS


def kelvin_to_celsius(t_k: float) -> float:
    """K → °C."""
    return t_k - ZERO_CELSIUS
