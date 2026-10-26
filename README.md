# pcbsim

Open-source PCB multiphysics simulator, written in Python 3.11+.

pcbsim reads a board description (a YAML config now, KiCad `.kicad_pcb` later), meshes the copper layers, and runs physics solvers through a plugin interface:

| solver      | physics                                                         | status   |
| ----------- | --------------------------------------------------------------- | -------- |
| `dc_ir`     | multi-layer PDN IR drop, via resistance, VRM / load ports       | stage 2  |
| `thermal`   | steady-state and transient 2.5D conduction, convection, radiation | stage 3  |
| `coupled`   | electro-thermal iteration with ρ(T) and Joule heating           | stage 4  |
| `si`        | microstrip, stripline and differential Z0; 2D FEM cross-check   | stage 5  |
| `em_openems`| S-parameters via openEMS (optional)                             | stage 8  |

The physics comes only from public sources: textbooks, papers, IPC standards, and open-source project documentation. Each formula is listed with its reference in [`docs/theory.md`](docs/theory.md).

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```bash
pcbsim check examples/soc_4layer.yaml   # validate the config and print a board summary
pcbsim solvers                          # list registered solver plugins
pcbsim run examples/soc_4layer.yaml     # stage 2+
pcbsim report results/                  # stage 7
```

## Config format

See [`examples/soc_4layer.yaml`](examples/soc_4layer.yaml) for a complete example and [`docs/config.md`](docs/config.md) for the schema reference. Lengths accept `mm`, `mil`, `um`, `in`, and copper weight `oz` (1 oz = 34.79 µm, IPC nominal). Bare numbers use `units.length`, which defaults to mm. Temperatures default to °C. Internally every quantity is SI.

## Layout

```
pcbsim/
  model/      Board, Stackup, Layer, Net, Shape(Polygon), Via, Component, Port, Criteria
  io/         YAML config loader (pydantic v2); KiCad parser in stage 6
  materials/  YAML material DB (σ, α, εr, tanδ, k, ρ, cp, ε)
  mesh/       2.5D per-layer grids
  solvers/    Solver ABC + registry (entry-point group "pcbsim.solvers")
  post/       heat maps, reports
  cli.py      `pcbsim` command
```

## Development

```bash
pytest
ruff check . && ruff format --check .
mypy
```

## Solver plugins

```python
from pcbsim.solvers import Solver, ResultSet, register


@register("my_solver")
class MySolver(Solver):
    description = "does something useful"

    def assemble(self) -> None: ...
    def solve(self) -> None: ...
    def results(self) -> ResultSet:
        return ResultSet(self.name)
```

External packages can expose solvers through the `pcbsim.solvers` entry-point group instead of importing pcbsim's registry.

## License

Apache-2.0
