from __future__ import annotations

from collections.abc import Iterator

import pytest

from pcbsim.errors import SolverError
from pcbsim.materials import MaterialDB
from pcbsim.model import Board, Layer, LayerKind, Polygon, Stackup
from pcbsim.solvers import (
    ResultSet,
    Severity,
    Solver,
    SolverContext,
    Violation,
    available_solvers,
    get_solver,
    register,
)
from pcbsim.solvers.base import unregister


class _Dummy(Solver):
    description = "test dummy"

    def assemble(self) -> None:
        self.assembled = True

    def solve(self) -> None:
        self.solution = self.options.get("value", 1.0)

    def results(self) -> ResultSet:
        rs = ResultSet(self.name, scalars={"value": self.solution})
        if self.solution > 2.0:
            rs.violations.append(Violation("limit", "x", self.solution, 2.0, "V"))
        return rs


@pytest.fixture
def dummy() -> Iterator[type[Solver]]:
    cls = register("_dummy")(_Dummy)
    yield cls
    unregister("_dummy")


@pytest.fixture
def ctx() -> SolverContext:
    board = Board(
        "b",
        Polygon.rectangle(0, 0, 1e-2, 1e-2),
        Stackup((Layer("L1", LayerKind.CONDUCTOR, 35e-6, "copper"),)),
    )
    return SolverContext(board=board, materials=MaterialDB.default())


def test_register_and_lookup(dummy: type[Solver]) -> None:
    assert get_solver("_dummy") is dummy
    assert "_dummy" in available_solvers()
    assert dummy.name == "_dummy"


def test_lifecycle(dummy: type[Solver], ctx: SolverContext) -> None:
    rs = dummy({"value": 1.5}).run(ctx)
    assert rs.solver == "_dummy"
    assert rs.scalars["value"] == 1.5
    assert rs.passed


def test_violations_fail(dummy: type[Solver], ctx: SolverContext) -> None:
    rs = dummy({"value": 3.0}).run(ctx)
    assert not rs.passed
    assert rs.violations[0].severity is Severity.VIOLATION


def test_warning_does_not_fail() -> None:
    rs = ResultSet("x", violations=[Violation("c", "s", 1, 1, "V", Severity.WARNING)])
    assert rs.passed


def test_ctx_before_setup(dummy: type[Solver]) -> None:
    with pytest.raises(SolverError, match="setup"):
        _ = dummy().ctx


def test_unknown_solver() -> None:
    with pytest.raises(SolverError, match="unknown solver 'nope'"):
        get_solver("nope")


def test_name_collision(dummy: type[Solver]) -> None:
    class Other(_Dummy):
        pass

    with pytest.raises(SolverError, match="already registered"):
        register("_dummy")(Other)


def test_register_non_solver() -> None:
    with pytest.raises(TypeError):
        register("bad")(int)  # type: ignore[type-var]
