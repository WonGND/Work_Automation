"""Read-only loader for a ``pcbsim run`` results directory.

``pcbsim run`` writes (see :func:`pcbsim.runner.write_results`):

* ``results.json`` — board, source config, mesh, and per solver ``passed``,
  ``scalars``, ``violations``, ``ports``, ``vias``, ``components``,
  ``history`` and ``lines``; all SI units, non-finite floats stored as ``null``;
* ``<solver>_fields.npz`` — the raw fields (not needed by the report);
* ``<solver>_<quantity>_<layer>.png`` heat maps and
  ``<solver>_convergence.png`` for iterative solvers.

This module validates the JSON envelope (so a damaged or foreign file gives a
clear :class:`~pcbsim.errors.ResultsError` instead of a ``KeyError`` deep in
the renderer) and collects the PNG files as base64 ``data:`` URIs so the HTML
report is self-contained. Nothing in the directory is modified.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pcbsim import __version__
from pcbsim.errors import ResultsError

RESULTS_FILE = "results.json"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 80 * 1024 * 1024
FIELD_QUANTITIES = ("voltage", "current_density", "power_density", "temperature")

# Per-solver entries the renderer reads, with the JSON type each must have.
_SOLVER_KEYS: dict[str, type] = {
    "scalars": dict,
    "violations": list,
    "ports": list,
    "vias": list,
    "components": list,
    "history": dict,
    "lines": list,
}


@dataclass(frozen=True, slots=True)
class ImageAsset:
    """One PNG from the results directory, embedded as a ``data:`` URI.

    ``kind`` is ``"field"`` (heat map), ``"convergence"`` or ``"other"``.
    ``solver``/``quantity``/``layer`` are empty when the file name does not
    follow the ``<solver>_<quantity>_<layer>.png`` convention.
    """

    file_name: str
    kind: str
    solver: str
    quantity: str
    layer: str
    data_uri: str


@dataclass(frozen=True, slots=True)
class LoadedResults:
    directory: Path
    doc: dict[str, Any]
    images: tuple[ImageAsset, ...]
    notes: tuple[str, ...]

    @property
    def solvers(self) -> dict[str, dict[str, Any]]:
        solvers: dict[str, dict[str, Any]] = self.doc["solvers"]
        return solvers


def num(value: Any) -> float | None:
    """A finite float, or ``None`` for null / NaN / ±inf / non-numbers (bools excluded)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def _check_envelope(doc: Any, path: Path) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ResultsError(f"{path}: expected a JSON object at the top level")
    version = doc.get("pcbsim_version")
    if not isinstance(version, str) or "solvers" not in doc:
        raise ResultsError(
            f"{path}: not a pcbsim results file (needs 'pcbsim_version' and 'solvers'); "
            "create one with `pcbsim run <config.yaml>`"
        )
    if _major(version) != _major(__version__):
        raise ResultsError(
            f"{path}: written by pcbsim {version}, which this pcbsim {__version__} "
            "cannot read (different major version); re-run the analysis"
        )
    solvers = doc["solvers"]
    if not isinstance(solvers, dict):
        raise ResultsError(f"{path}: 'solvers' must be an object keyed by solver name")
    for name, entry in solvers.items():
        if not isinstance(entry, dict):
            raise ResultsError(f"{path}: solvers.{name} must be an object")
        for key, typ in _SOLVER_KEYS.items():
            if key in entry and entry[key] is not None and not isinstance(entry[key], typ):
                kind = "an object" if typ is dict else "a list"
                raise ResultsError(f"{path}: solvers.{name}.{key} must be {kind}")
        for key in ("violations", "ports", "vias", "components", "lines"):
            rows = entry.get(key) or []
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ResultsError(f"{path}: solvers.{name}.{key}[{i}] must be an object")
    for key in ("mesh", "units"):
        if doc.get(key) is not None and not isinstance(doc[key], dict):
            raise ResultsError(f"{path}: '{key}' must be an object")
    return doc


def read_results_json(path: Path) -> dict[str, Any]:
    """Parse and validate ``results.json``; raise :class:`ResultsError` with the cause."""
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        raise ResultsError(
            f"no {RESULTS_FILE} in {path.parent} — run `pcbsim run <config.yaml> "
            f"--out {path.parent}` first"
        ) from None
    except UnicodeDecodeError as exc:
        raise ResultsError(f"{path}: not UTF-8 text ({exc.reason})") from None
    except OSError as exc:
        raise ResultsError(f"{path}: cannot read ({exc.strerror or exc})") from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResultsError(
            f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg} "
            "(the file may be truncated; re-run the analysis)"
        ) from None
    return _check_envelope(doc, path)


def _classify(stem: str, solvers: list[str], layers: list[str]) -> tuple[str, str, str, str]:
    """``(kind, solver, quantity, layer)`` from a PNG file stem."""
    for solver in sorted(solvers, key=len, reverse=True):
        if not stem.startswith(solver + "_"):
            continue
        rest = stem[len(solver) + 1 :]
        if rest == "convergence":
            return "convergence", solver, "", ""
        for q in FIELD_QUANTITIES:
            if rest.startswith(q + "_"):
                layer = rest[len(q) + 1 :]
                if not layers or layer in layers:
                    return "field", solver, q, layer
    return "other", "", "", ""


def collect_images(directory: Path, doc: dict[str, Any]) -> tuple[list[ImageAsset], list[str]]:
    """Embed the PNG files directly in ``directory`` (no recursion, no links outside it)."""
    root = directory.resolve()
    solvers = [str(s) for s in doc.get("solvers", {})]
    mesh = doc.get("mesh") or {}
    layers = [str(x) for x in mesh.get("layers") or []]
    images: list[ImageAsset] = []
    notes: list[str] = []
    total = 0
    for p in sorted(directory.glob("*.png")):
        try:
            real = p.resolve()
            if real.parent != root or not real.is_file():
                notes.append(f"{p.name}: skipped (links outside the results directory)")
                continue
            size = real.stat().st_size
            if size > MAX_IMAGE_BYTES:
                notes.append(f"{p.name}: skipped ({size / 2**20:.1f} MB is too large to embed)")
                continue
            if total + size > MAX_TOTAL_IMAGE_BYTES:
                notes.append(f"{p.name}: skipped (embedded images exceed the size budget)")
                continue
            data = real.read_bytes()
        except OSError as exc:
            notes.append(f"{p.name}: skipped (cannot read: {exc.strerror or exc})")
            continue
        if not data.startswith(PNG_MAGIC):
            notes.append(f"{p.name}: skipped (not a PNG file)")
            continue
        total += len(data)
        kind, solver, quantity, layer = _classify(p.stem, solvers, layers)
        uri = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        images.append(ImageAsset(p.name, kind, solver, quantity, layer, uri))
    return images, notes


def load_results(path: Path) -> LoadedResults:
    """Load a results directory (or a ``results.json`` path) for reporting."""
    if path.is_file() and path.name == RESULTS_FILE:
        path = path.parent
    if not path.exists():
        raise ResultsError(f"results directory not found: {path}")
    if not path.is_dir():
        raise ResultsError(f"{path} is not a directory; pass the folder `pcbsim run` wrote")
    doc = read_results_json(path / RESULTS_FILE)
    images, notes = collect_images(path, doc)
    return LoadedResults(path, doc, tuple(images), tuple(notes))
