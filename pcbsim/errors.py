"""Exception hierarchy for pcbsim."""

from __future__ import annotations


class PcbsimError(Exception):
    """Base class of every error raised intentionally by pcbsim."""


class UnitError(PcbsimError, ValueError):
    """A quantity string could not be parsed or has an incompatible unit."""


class ConfigError(PcbsimError):
    """A configuration file is invalid.

    The message is prefixed with a dotted path into the YAML document
    (e.g. ``board.stackup[2].thickness``) so the user can locate the problem.
    """


class ModelError(PcbsimError):
    """The board model is internally inconsistent (dangling references, etc.)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("invalid board model:\n  - " + "\n  - ".join(self.problems))


class MaterialError(PcbsimError, KeyError):
    """A material is missing from the database or has invalid properties."""

    def __str__(self) -> str:  # KeyError would otherwise repr() the message
        return str(self.args[0]) if self.args else ""


class SolverError(PcbsimError):
    """A solver could not be found, configured, or failed to converge."""
