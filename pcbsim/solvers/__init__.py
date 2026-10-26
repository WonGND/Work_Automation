"""Physics solvers (plugin architecture — see :mod:`pcbsim.solvers.base`).

Planned built-ins: ``dc_ir`` (stage 2), ``thermal`` (3), ``coupled`` (4), ``si`` (5),
``em_openems`` (8, optional).
"""

from __future__ import annotations

from pcbsim.solvers.base import (
    FieldData,
    ResultSet,
    Severity,
    Solver,
    SolverContext,
    Violation,
    available_solvers,
    get_solver,
    register,
)

__all__ = [
    "FieldData",
    "ResultSet",
    "Severity",
    "Solver",
    "SolverContext",
    "Violation",
    "available_solvers",
    "get_solver",
    "register",
]
