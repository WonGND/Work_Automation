"""Signal integrity: transmission-line impedance from closed forms and a 2D FEM solver.

* :mod:`pcbsim.si.analytic` — Hammerstad–Jensen, Wheeler, Cohn, IPC-2141A
* :mod:`pcbsim.si.fem2d` — electrostatic cross-section solver (scikit-fem, P2)
* :mod:`pcbsim.si.xsection` — stack-up → cross-section, formula selection
"""

from __future__ import annotations

from pcbsim.si.analytic import LineZ
from pcbsim.si.fem2d import CrossSection, FemOptions, FemResult, Rect
from pcbsim.si.xsection import LineGeometry, analytic_for, resolve

__all__ = [
    "CrossSection",
    "FemOptions",
    "FemResult",
    "LineGeometry",
    "LineZ",
    "Rect",
    "analytic_for",
    "resolve",
]
