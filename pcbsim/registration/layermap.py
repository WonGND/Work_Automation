"""Layer-map YAML: which drawing / Gerber layers carry which mechanical meaning.

Layer selectors are Python regular expressions matched with ``re.fullmatch``
(case-insensitive) against the DXF layer name, so ``"OUTLINE|BOARD_EDGE"`` or
``"COMP_(?P<ref>.+)"`` both work. A named group ``ref`` extracts the component
reference designator from the layer name; a named group ``h`` (or ``height``)
extracts a height limit from a keepout layer name, in ``units`` (e.g.
``KEEPOUT_H(?P<h>[0-9.]+)`` → ``KEEPOUT_H3.5`` = 3.5 mm).

Example::

    units: mm                    # DXF unit override; omit to use $INSUNITS
    mech:
      outline: "OUTLINE|PCB"
      holes: "HOLES?|MOUNT.*"
      fiducials: "FID.*"
      comp_3d: "COMP_(?P<ref>.+)"
      heatsink: "HEATSINK.*|HS_.*"
      keepout: "KEEPOUT_H(?P<h>[0-9.]+)"
      chassis: "CHASSIS.*"
      case: "CASE.*"
    ecad:
      ref_holes: npth            # npth | all — which drill holes act as reference holes
      ref_hole_min_diameter: 2.0
    registration:
      tol: 0.3                   # feature matching radius
      mirror: auto               # auto | true (bottom view) | false
      allow_scale: true          # detect inch/mm mix-ups
      use_outline_vertices: false
      use_fiducials: true
      anchors: [{mech: [x, y], board: [x, y]}]
    checks:
      hole_position_tol: 0.1
      hole_diameter_tol: 0.1
      mech_hole_min_diameter: 1.0  # ECAD holes this large must exist in the drawing
      outline_tol: 0.2             # Hausdorff
      cutout_tol: 0.2
      component_position_tol: 0.5
      component_rotation_tol: 2.0  # degrees
      case_height: 12              # default ceiling above board top
      min_clearance: 0.5
    heatsinks:                     # thermal models, first matching rule wins
      - { layers: "HS_U1", component: U1, resistance: 6.0 }
      - { layers: "HS_.*", fins: { count: 8, height: 10, thickness: 1.0, length: 20 },
          h: 10, k: 200 }
    chassis: { temperature: 45, contact_resistance: 0.5 }  # or h_contact (W/m²K)
    case: { temperature: 40 }                              # air gap conduction to the lid
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from pcbsim.errors import ConfigError
from pcbsim.units import Kind, to_si

_LEN_UNITS = {"mm", "mil", "um", "in", "m", "cm"}


def _len_mm(value: Any) -> float:
    """Lengths in the map are mm unless a unit string is given; returned in metres."""
    from pcbsim.units import parse_quantity

    if isinstance(value, bool):
        raise ValueError("expected a length")
    if isinstance(value, int | float):
        return to_si(float(value), "mm", Kind.LENGTH)
    if isinstance(value, str):
        return parse_quantity(value, Kind.LENGTH)
    raise ValueError(f"expected a length, got {value!r}")


def _temp(value: Any) -> float:
    from pcbsim.units import parse_quantity

    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"expected a temperature, got {value!r}")
    return parse_quantity(value, Kind.TEMPERATURE)


Length = Annotated[float, BeforeValidator(_len_mm)]
Temp = Annotated[float, BeforeValidator(_temp)]


def _regex(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("layer selector must be a regular-expression string")
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"invalid regular expression {value!r}: {exc}") from exc
    return value


Regex = Annotated[str, BeforeValidator(_regex)]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MechLayers(_M):
    outline: Regex = r"OUTLINE|BOARD|PCB|EDGE.*"
    holes: Regex = r"HOLES?|MOUNT.*|DRILL.*"
    fiducials: Regex | None = r"FID.*"
    comp_3d: Regex | None = r"COMP.*|3D.*"
    heatsink: Regex | None = r"HEATSINK.*|HS_.*"
    keepout: Regex | None = r"KEEPOUT.*"
    chassis: Regex | None = r"CHASSIS.*"
    case: Regex | None = r"CASE.*"


class EcadOptions(_M):
    ref_holes: Literal["npth", "all"] = "all"
    ref_hole_min_diameter: Length = 2.0e-3


class AnchorSpec(_M):
    mech: tuple[Length, Length]
    board: tuple[Length, Length]


class RegistrationMapOptions(_M):
    tol: Length = 0.3e-3
    diameter_tol: Length = 0.15e-3
    mirror: Literal["auto", "true", "false"] = "auto"
    allow_scale: bool = True
    use_outline_vertices: bool = False
    use_fiducials: bool = True
    use_outline_icp: bool = True
    anchors: list[AnchorSpec] = Field(default_factory=list)


class CheckOptions(_M):
    hole_position_tol: Length = 0.1e-3
    hole_diameter_tol: Length = 0.1e-3
    hole_search_radius: Length = 2.0e-3
    mech_hole_min_diameter: Length = 1.0e-3
    outline_tol: Length = 0.2e-3
    cutout_tol: Length = 0.2e-3
    component_position_tol: Length = 0.5e-3
    component_rotation_tol: Annotated[float, Field(ge=0.0)] = 2.0
    component_search_radius: Length = 3.0e-3
    case_height: Length | None = None
    min_clearance: Length = 0.0
    registration_rms_max: Length = 0.05e-3


class FinSpec(_M):
    count: Annotated[int, Field(ge=1)]
    height: Length
    thickness: Length
    length: Length | None = None


class HeatsinkRule(_M):
    layers: Regex = ".*"
    component: str | None = None
    resistance: Annotated[float, Field(gt=0.0)] | None = None
    fins: FinSpec | None = None
    h: Annotated[float, Field(gt=0.0)] = 10.0
    k: Annotated[float, Field(gt=0.0)] = 200.0
    ambient: Temp | None = None


class ChassisSpec(_M):
    temperature: Temp = 45.0 + 273.15
    contact_resistance: Annotated[float, Field(gt=0.0)] | None = None
    h_contact: Annotated[float, Field(gt=0.0)] | None = None
    side: Literal["top", "bottom"] = "bottom"


class CaseSpec(_M):
    temperature: Temp = 40.0 + 273.15
    k_air: Annotated[float, Field(gt=0.0)] = 0.0263
    side: Literal["top", "bottom"] = "top"


class LayerMap(_M):
    units: str | None = None
    mech: MechLayers = Field(default_factory=MechLayers)
    ecad: EcadOptions = Field(default_factory=EcadOptions)
    registration: RegistrationMapOptions = Field(default_factory=RegistrationMapOptions)
    checks: CheckOptions = Field(default_factory=CheckOptions)
    heatsinks: list[HeatsinkRule] = Field(default_factory=list)
    chassis: ChassisSpec | None = None
    case: CaseSpec | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.units is not None and self.units not in _LEN_UNITS:
            raise ValueError(f"units: expected one of {sorted(_LEN_UNITS)}")

    def heatsink_rule(self, layer: str) -> HeatsinkRule:
        for rule in self.heatsinks:
            if fullmatch(rule.layers, layer) is not None:
                return rule
        return HeatsinkRule()


def fullmatch(pattern: str | None, name: str) -> re.Match[str] | None:
    if pattern is None:
        return None
    return re.fullmatch(pattern, name, flags=re.IGNORECASE)


def load_layer_map(path: str | Path | None) -> LayerMap:
    """Load a layer-map YAML; ``None`` returns the defaults."""
    if path is None:
        return LayerMap()
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text("utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"layer map not found: {p}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{p}: YAML syntax error: {exc}") from None
    return layer_map_from_dict(data, str(p))


def layer_map_from_dict(data: Any, where: str = "layer map") -> LayerMap:
    from pcbsim.io.config import _format_validation_error

    try:
        return LayerMap.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{where}:\n{_format_validation_error(exc)}") from None
