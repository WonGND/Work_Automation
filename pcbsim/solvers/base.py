"""Solver plugin interface and registry.

Every physics solver follows the same four-phase life cycle::

    solver = get_solver("dc_ir")(options)
    solver.setup(context)      # bind board, materials, mesh; validate options
    solver.assemble()          # build the discrete system (e.g. sparse K·x = f)
    solver.solve()             # solve it
    results = solver.results() # → ResultSet (fields + scalars + violations)

Built-in solvers register with :func:`register`. External packages can expose
solvers through the ``pcbsim.solvers`` entry-point group (see ``pyproject.toml``);
they are discovered lazily by :func:`available_solvers`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import entry_points
from typing import Any, ClassVar, TypeVar

import numpy as np
from numpy.typing import NDArray

from pcbsim.errors import SolverError
from pcbsim.materials import MaterialDB
from pcbsim.model import Board


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    VIOLATION = "violation"


@dataclass(frozen=True, slots=True)
class Violation:
    """One failed (or near-failing) design check, e.g. IR drop at a sink port."""

    check: str
    subject: str
    value: float
    limit: float
    unit: str
    severity: Severity = Severity.VIOLATION
    location: tuple[float, float] | None = None
    message: str = ""


@dataclass(slots=True)
class FieldData:
    """A sampled field on one layer of a structured grid (SI units)."""

    name: str
    unit: str
    layer: str
    values: NDArray[np.float64]
    extent: tuple[float, float, float, float]


@dataclass(slots=True)
class ResultSet:
    solver: str
    scalars: dict[str, float] = field(default_factory=dict)
    fields: list[FieldData] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(v.severity is Severity.VIOLATION for v in self.violations)


@dataclass(frozen=True, slots=True)
class SolverContext:
    """Everything a solver may need; ``mesh``, ``upstream`` and ``options`` come from the runner.

    ``options`` holds the options of *every* solver in the analysis (keyed by
    solver name), so a composite solver such as ``coupled`` can configure the
    solvers it drives the same way the user configured them.
    """

    board: Board
    materials: MaterialDB
    mesh: Any = None
    upstream: Mapping[str, ResultSet] = field(default_factory=dict)
    options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


class Solver(ABC):
    """Base class of all physics solvers."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    uses: ClassVar[tuple[str, ...]] = ()

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self.options: dict[str, Any] = dict(options or {})
        self._ctx: SolverContext | None = None
        self._phase = "new"

    @property
    def ctx(self) -> SolverContext:
        if self._ctx is None:
            raise SolverError(f"{self.name}: setup() has not been called")
        return self._ctx

    def setup(self, ctx: SolverContext) -> None:
        self._ctx = ctx
        self.validate_options()
        self._phase = "setup"

    def validate_options(self) -> None:  # noqa: B027 - optional hook
        """Override to validate ``self.options``; raise :class:`SolverError` on bad input."""

    def _require_phase(self, *allowed: str) -> None:
        if self._phase not in allowed:
            raise SolverError(f"{self.name}: invalid call order (phase is {self._phase!r})")

    def run(self, ctx: SolverContext) -> ResultSet:
        """Convenience: setup → assemble → solve → results.

        Subclasses may track ``_phase`` themselves; the base only sets it when
        the subclass did not advance it.
        """
        self.setup(ctx)
        self.assemble()
        if self._phase == "setup":
            self._phase = "assembled"
        self.solve()
        if self._phase == "assembled":
            self._phase = "solved"
        return self.results()

    @abstractmethod
    def assemble(self) -> None: ...

    @abstractmethod
    def solve(self) -> None: ...

    @abstractmethod
    def results(self) -> ResultSet: ...


S = TypeVar("S", bound=type[Solver])

_REGISTRY: dict[str, type[Solver]] = {}
_ENTRY_POINTS_LOADED = False
_BUILTINS = (
    "pcbsim.solvers.dc_ir",
    "pcbsim.solvers.thermal",
    "pcbsim.solvers.coupled",
    "pcbsim.solvers.si",
)


def _load_entry_points() -> None:
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    _ENTRY_POINTS_LOADED = True
    import importlib

    for mod in _BUILTINS:
        importlib.import_module(mod)
    for ep in entry_points(group="pcbsim.solvers"):
        if ep.name in _REGISTRY:
            continue
        cls = ep.load()
        if isinstance(cls, type) and issubclass(cls, Solver):
            cls.name = ep.name
            _REGISTRY[ep.name] = cls


def register(name: str) -> Callable[[S], S]:
    """Class decorator registering a solver under ``name``."""

    def deco(cls: S) -> S:
        if not (isinstance(cls, type) and issubclass(cls, Solver)):
            raise TypeError("@register can only decorate Solver subclasses")
        existing = _REGISTRY.get(name)
        if existing is not None and existing is not cls:
            raise SolverError(f"solver name {name!r} already registered by {existing.__qualname__}")
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def available_solvers() -> dict[str, type[Solver]]:
    _load_entry_points()
    return dict(sorted(_REGISTRY.items()))


def get_solver(name: str) -> type[Solver]:
    solvers = available_solvers()
    try:
        return solvers[name]
    except KeyError:
        known = ", ".join(solvers) or "(none registered yet)"
        raise SolverError(f"unknown solver {name!r}; available: {known}") from None
