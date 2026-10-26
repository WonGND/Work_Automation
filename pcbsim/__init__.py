"""pcbsim — open-source PCB multiphysics simulator.

Pipeline: pre-processing (``io``/``model``) → mesh (``mesh``) → solver (``solvers``)
→ post-processing (``post``). All internal quantities are SI (m, K, Ω, A, V, W, S/m).
Unit conversion (mm, mil, oz, °C …) happens only at the I/O boundary — see
:mod:`pcbsim.units`.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
