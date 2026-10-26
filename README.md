# pcbsim

Open-source PCB multiphysics simulator, written in Python 3.11+.

pcbsim reads a board description (a YAML config, or a KiCad `.kicad_pcb` plus a small YAML overlay), meshes the copper layers, and runs physics solvers through a plugin interface:

| solver      | physics                                                         | status   |
| ----------- | --------------------------------------------------------------- | -------- |
| `dc_ir`     | multi-layer PDN IR drop, via resistance, VRM / load ports       | done     |
| `thermal`   | steady-state and transient 2.5D conduction, convection, radiation | done     |
| `coupled`   | electro-thermal iteration with ρ(T) and Joule heating           | done     |
| `si`        | microstrip, stripline and differential Z0; 2D FEM cross-check   | done     |
| `em_openems`| S-parameters via openEMS (optional)                             | stage 8  |

**ECAD–MCAD registration** (`pcbsim match`): aligns a DXF/DWG/STEP mechanical drawing with the Gerber X2/X3 + Excellon board (RANSAC → Umeyama → outline ICP). It checks holes, outline, cutouts, component placement, and height clearance, and turns heat sinks, chassis contacts, and the case air gap into thermal boundaries for `pcbsim run`. See [`docs/registration.md`](docs/registration.md).

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
pcbsim run examples/soc_4layer.yaml     # dc_ir + thermal + coupled + si → results/ (JSON, NPZ, PNG)
pcbsim run examples/soc_4layer.yaml --solver si   # one solver only

# KiCad board + electrical overlay (sources, loads, power) — examples/kicad
pcbsim check examples/kicad/soc_4layer.kicad_pcb     # inspect the geometry import
pcbsim run   examples/kicad/soc_kicad.yaml

# impedance calculator, no config needed (lengths in mm, or with units)
pcbsim z0 microstrip -w 0.36 -H 0.2 -t 35um --er 4.2
pcbsim z0 stripline  -w 0.15 -H 0.5 -s 0.2 --er 4.0     # -s → differential pair

# ECAD–MCAD match (examples/mech)
pcbsim match --gerber examples/mech/gerber --mech examples/mech/mech.dxf \
             --map examples/mech/layers.yaml --report out/match.html --json out/match.json
pcbsim run examples/mech/soc_with_mech.yaml   # add --force to simulate despite an NG match
```

`coupled` iterates `dc_ir` with ρ(T) and `thermal` with the resulting Joule heat until both fields stop changing. It prints the per-pass ΔT/ΔV history and the coupled-vs-uncoupled IR drop and Tj, and writes `coupled_convergence.png`. `pcbsim report` (stage 7) is a placeholder that exits with code 3, so use the files in `results/` for now.

Exit codes: 0 pass, 1 invalid input, 2 usage, 3 not implemented, 4 design violations / NG, 5 run refused because the linked ECAD–MCAD match is NG.

## Config format

See [`examples/soc_4layer.yaml`](examples/soc_4layer.yaml) for a complete example and [`docs/config.md`](docs/config.md) for the schema reference. Lengths accept `mm`, `mil`, `um`, `in`, and copper weight `oz` (1 oz = 34.79 µm, IPC nominal). Bare numbers use `units.length`, which defaults to mm. Temperatures default to °C. Internally every quantity is SI.

## Layout

```
pcbsim/
  model/      Board, Stackup, Layer, Net, Shape(Polygon), Via, Component, Port, Criteria
  io/         YAML config loader (pydantic v2); Gerber X2/X3, Excellon, PnP CSV;
              DXF (ezdxf), DWG via ODA/LibreDWG, STEP via cadquery (optional);
              KiCad .kicad_pcb (sexpr.py, kicad.py)
  registration/  ECAD–MCAD registration, checks, report, thermal boundaries
  materials/  YAML material DB (σ, α, εr, tanδ, k, ρ, cp, ε)
  mesh/       2.5D per-layer grids
  si/         transmission lines: closed forms, 2D FEM cross-section, stack-up mapping
  solvers/    Solver ABC + registry (entry-point group "pcbsim.solvers"): dc_ir, thermal, coupled, si
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
