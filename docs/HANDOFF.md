# pcbsim — handoff for the next session

This file lets a new conversation (or another engineer) continue the work without the chat history. Last updated: 2026-10-26 (stage 4).

## Repository

* GitHub: `WonGND/Work_Automation`, default branch `main`.
* Branches:
  * `feat/ecad-mcad-registration`, PR #5: stages 1–3 (imported from the ZIP) plus the ECAD–MCAD registration module.
  * `feat/si-impedance`, PR #6, branched from the branch above: stage 5 (signal integrity). Stacked on #5 (base = `feat/ecad-mcad-registration`).
  * `feat/coupled-electrothermal`, branched from `feat/si-impedance`: stage 4 (electro-thermal coupling). Its PR is stacked on #6 (base = `feat/si-impedance`).
* Merge order: #5 → #6 → the stage-4 PR. After each merge, retarget the next PR's base to `main`.
* #5 and #6 contain `wip` commits because the workspace was restored several times. Squash on merge.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # or: pip install -r requirements-lock.txt shapely ezdxf types-shapely && pip install -e . --no-deps
pytest && ruff check . && ruff format --check . && mypy     # 373 passed, 1 skipped (STEP: cadquery not installed)
```

## Original requirements (summary of the user's prompt)

Open-source PCB multiphysics simulator `pcbsim`, Python 3.11+:

* Only public sources (textbooks, papers, IPC-2141/2152, KiCad/openEMS/scikit-fem/Elmer docs). No reverse engineering of commercial tools. Every formula and its source goes in `docs/theory.md`.
* Pipeline: preprocess → mesh → solver (plugins) → postprocess. SI units internally; mm/mil/oz only at I/O.
* Quality: type hints, ruff + mypy (strict) clean, every module docstring states its formulas.
* Violation criteria configurable: IR drop > 3 % of supply, T > Tj_max (105 °C default), current density > IPC-2152 limit, Z0 outside target ±10 %.
* Required verification: sheet resistance R = Rs·L/W < 1 %; 1D fin/bar conduction < 2 %; microstrip Z0 FEM vs formula < 2 %; mesh refinement converges; coupled solver converges, and α = 0 matches the uncoupled result.
* Stages, with a stop for user confirmation after each:
  1. skeleton, data model, material DB, YAML loader — done
  2. `dc_ir` — done
  3. `thermal` — done
  4. `coupled` electro-thermal — **done (`feat/coupled-electrothermal`)**
  5. `si` closed forms + 2D FEM — done (`feat/si-impedance`)
  6. KiCad `.kicad_pcb` input — **next**
  7. HTML/JSON report + CLI `pcbsim report` — not started (`report` is a stub, exit 3)
  8. optional Streamlit GUI, openEMS — not started
* Extra request (done, PR #5): ECAD–MCAD registration module — Gerber X2/X3, Excellon, DXF, DWG via converters, STEP optional; RANSAC → Umeyama → ICP; checks; HTML/JSON report; thermal BCs from heat sinks, chassis, and case; `pcbsim match`; `pcbsim run` refuses an NG match unless `--force`.

## Code map

```
pcbsim/
  model/        Board, Stackup, Layer, Net, Shape, Via, Component, Port, ThermalBoundary,
                TransmissionLine, Criteria (all SI, frozen dataclasses; Board.validate())
  io/config.py  pydantic v2 schema → Board; units parsed at the boundary; `mechanical:` link
  io/           gerber.py excellon.py pnp.py dxf.py dwg.py step.py mech.py cad.py (types)
  materials/    YAML DB (σ, α, εr, tanδ, k, ρ, cp, ε)
  mesh/         2.5D structured grid per conductor layer
  solvers/      base.py (Solver ABC, registry, _BUILTINS), dc_ir.py, thermal.py, coupled.py, si.py
  si/           analytic.py (HJ, IPC-2141, Cohn, Wheeler), fem2d.py (scikit-fem P2),
                xsection.py (stack-up → cross-section, formula choice + accuracy)
  registration/ transform, solve (RANSAC/Umeyama/ICP), features, checks, thermal_bc,
                pipeline (match.json), report (HTML+SVG), layermap
  post/         heatmap.py (per-layer PNG), convergence.py (coupled ΔT/ΔV plot)
  runner.py     config → mesh → solvers → results.json/npz/png
  cli.py        check | run [--solver --force] | match | z0 | report (stub) | solvers
tests/          one file per module; cad_fixtures.py generates KiCad/FreeCAD-style files
examples/       soc_4layer.yaml; mech/ (gerber, mech.dxf, layers.yaml, match.json, report)
docs/           theory.md (§1–8 + references), config.md, registration.md, HANDOFF.md
```

## Stage 5 (SI): what was built

* Config: `transmission_lines: [{name, layer, width, spacing?, target?, references?, tolerance_pct?}]`. `target` is Z0 for a single trace and Zdiff for a pair.
* Solver `si`, with options `mesh: coarse|normal|fine` and `box_factor`. It reports the FEM value and cross-checks it against the best closed form:
  * `z0` violation when the value is outside target ±tol.
  * `z0_crosscheck` warning when FEM vs formula differs by more than the formula's expected accuracy.
* `pcbsim z0 microstrip|stripline -w -H [-t] [-s] --er` is a standalone calculator.
* Accuracy measured in tests: FEM vs HJ microstrip 0.1–0.4 % (requirement < 2 %); FEM vs Cohn exact stripline/coupled < 1 %; mesh refinement monotone to < 0.2 %.
* Example board: L1/L4 microstrips with solder mask. The FEM including the mask is about 3 % below HJ, which ignores the mask; this is expected and inside the 6 % cross-check band.

## Known limitations / follow-ups

* SI: no conductor loss, frequency dependence, or surface roughness (DC/quasi-TEM only); coplanar waveguide is not modelled; an offset differential stripline is checked only against IPC (±10 %).
* Registration: IPC-2581/ODB++ not implemented; STEP gives bounding boxes only; one drawing = one board side. E2E tests use generated KiCad/FreeCAD-format files, not real exports.
* Coupled: steady state only (a transient thermal option is forced to steady with an info note). Current sinks are fixed-current loads, so the coupling always converges unless αK ≥ 1 (runaway, reported). Constant-power loads (I = P/V) are not modelled.

## Stage 4 (coupled): what was built

* Solver `coupled` (`pcbsim/solvers/coupled.py`), `uses = (dc_ir, thermal)`. It drives its own `DcIrSolver` and `ThermalSolver` on the shared grid, using `analysis.options.dc_ir` / `.thermal` plus its own `dc_ir:` / `thermal:` overrides. Options: `tol_t` (K, default 0.01), `tol_v` (V, default 1e-5), `max_iter` (50), `relaxation` ω (1.0).
* Pass 0 is exactly the uncoupled run. Its values are kept as `*.uncoupled` scalars (`SOC_CORE.drop_pct.uncoupled`, `U1.tj.uncoupled`, `t_max.uncoupled`, `joule_power.uncoupled`).
* Hooks added for this:
  * `DcIrSolver.resolve(T_field)` re-assembles with per-cell ρ(T).
  * `ThermalSolver.resolve(joule)` changes only the RHS, reuses the cached LU (`ThermalSystem.lu`), and warm-starts the radiation Newton loop.
  * `SolverContext.options` carries every solver's options.
  * The config accepts `dc_ir`/`thermal` options when only `coupled` is listed.
* Checks: all `dc_ir` and `thermal` checks evaluated on the coupled fields, plus `thermal_runaway` (ΔT grows for 3 passes) and `convergence` (max_iter used up). The `contraction` scalar is the estimated ratio κ = ΔTₖ/ΔTₖ₋₁.
* Output: a CLI per-pass table (ΔT, ΔV, T_max, Joule, worst drop) and coupled-vs-uncoupled lines; `history` in results.json; `coupled_convergence.png`; heat maps of V, J, and T at the fixed point.
* Example board: converges in 2 passes (κ ≈ 0.002). SOC_CORE drop goes from 1.146 % to 1.272 %, Joule loss from 67.5 to 74.9 mW, and T_max rises by +0.06 K.
* Tests (`tests/test_coupled.py`): lumped analytic fixed point T* = T_a + K[1+α(T_a−T_ref)]/(1−αK) to 1e-3 K; κ = αK to 1 %; α = 0 equals the uncoupled result; the hotter case gives a higher drop; self-consistency of the fixed point; relaxation; runaway; non-convergence; CLI.

## Next step (stage 6: KiCad `.kicad_pcb` input)

Parse the KiCad S-expression board file (public format docs: <https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/>) into the same `Board` the YAML loader produces:

* stack-up from `(setup (stackup ...))`
* outline from `Edge.Cuts`
* nets
* zones (filled polygons) and tracks/arcs (buffered to polygons with shapely)
* vias with drill and layer pair
* footprints with pads, giving component footprints and port regions

Electrical intent that KiCad does not store (sources, sinks, power, θ values, criteria, analysis) comes from a small YAML overlay that references KiCad refs and nets. Tests should use generated `.kicad_pcb` fixtures in the style of `tests/cad_fixtures.py`.

Working conventions used so far: module docstrings with formulas and sources, a theory.md section per stage, tests against analytic solutions, the example config updated, and a stop for user confirmation after each stage.
