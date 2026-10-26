"""ECAD–MCAD registration: align a mechanical drawing (DXF/DWG/STEP) to the board
(Gerber/Excellon), check holes, outline, components and heights, and derive
thermal boundary conditions from heat sinks, chassis contacts and the case.

Pipeline: :mod:`~pcbsim.registration.features` (extract) →
:mod:`~pcbsim.registration.solve` (RANSAC → Umeyama → ICP) →
:mod:`~pcbsim.registration.checks` → :mod:`~pcbsim.registration.thermal_bc` →
:mod:`~pcbsim.registration.report`.
"""

from __future__ import annotations

from pcbsim.registration.layermap import LayerMap, load_layer_map
from pcbsim.registration.solve import (
    Anchor,
    Feature,
    RegistrationError,
    RegistrationOptions,
    RegistrationResult,
    register,
    umeyama,
)
from pcbsim.registration.transform import Similarity2D

__all__ = [
    "Anchor",
    "Feature",
    "LayerMap",
    "RegistrationError",
    "RegistrationOptions",
    "RegistrationResult",
    "Similarity2D",
    "load_layer_map",
    "register",
    "umeyama",
]
