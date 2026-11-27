"""Input readers.

* YAML config (:mod:`pcbsim.io.config`)
* ECAD: Gerber RS-274X/X2/X3 (:mod:`~pcbsim.io.gerber`), Excellon (:mod:`~pcbsim.io.excellon`),
  pick-and-place CSV (:mod:`~pcbsim.io.pnp`)
* MCAD: DXF (:mod:`~pcbsim.io.dxf`), DWG via external converters (:mod:`~pcbsim.io.dwg`),
  STEP via optional cadquery (:mod:`~pcbsim.io.step`); dispatcher :mod:`~pcbsim.io.mech`
* KiCad ``.kicad_pcb`` (:mod:`~pcbsim.io.kicad`, S-expressions in :mod:`~pcbsim.io.sexpr`),
  used through the config's ``kicad:`` section
"""

from __future__ import annotations

from pcbsim.io.config import (
    AnalysisConfig,
    LoadedConfig,
    MechanicalLink,
    MeshOptions,
    load_config,
    load_config_dict,
)

__all__ = [
    "AnalysisConfig",
    "LoadedConfig",
    "MechanicalLink",
    "MeshOptions",
    "load_config",
    "load_config_dict",
]
