# pcbsim — handoff for the next session

This file lets a new conversation (or another engineer) continue the work without the chat history. Last updated: 2026-11-27 (stage 7).

## Repository

* GitHub: `WonGND/Work_Automation`, default branch `main`.
* Branches:
  * `feat/ecad-mcad-registration`, PR #5: stages 1–3 (imported from the ZIP) plus the ECAD–MCAD registration module.
  * `feat/si-impedance`, PR #6, branched from the branch above: stage 5 (signal integrity). Stacked on #5 (base = `feat/ecad-mcad-registration`).
  * `feat/coupled-electrothermal`, PR #7, branched from `feat/si-impedance`: stage 4 (electro-thermal coupling). Stacked on #6.
  * `feat/kicad-input`, branched from `feat/coupled-electrothermal`: stage 6 (KiCad input). Its PR is stacked on #7 (base = `feat/coupled-electrothermal`). Stage 7 (report) is also on this branch.
* Merge order: #5 → #6 → #7 → the stage-6 PR. After each merge, retarget the next PR's base to `main`.
* #5 and #6 contain `wip` commits because the workspace was restored several times. Squash on merge.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # or: pip install -r requirements-lock.txt shapely ezdxf types-shapely && pip install -e . --no-deps
pytest && ruff check . && ruff format --check . && mypy     # 417 passed, 3 skipped (STEP: cadquery not installed); on Windows set PYTHONUTF8=1
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
  4. `coupled` electro-thermal — done (`feat/coupled-electrothermal`)
  5. `si` closed forms + 2D FEM — done (`feat/si-impedance`)
  6. KiCad `.kicad_pcb` input — **done (`feat/kicad-input`)**
  7. HTML report + CLI `pcbsim report` — **done (`feat/kicad-input`)**; `results.json` stays the JSON output
  8. optional Streamlit GUI, openEMS — **next**, not started
* Extra request (done, PR #5): ECAD–MCAD registration module — Gerber X2/X3, Excellon, DXF, DWG via converters, STEP optional; RANSAC → Umeyama → ICP; checks; HTML/JSON report; thermal BCs from heat sinks, chassis, and case; `pcbsim match`; `pcbsim run` refuses an NG match unless `--force`.

## Code map

```
pcbsim/
  model/        Board, Stackup, Layer, Net, Shape, Via, Component, Port, ThermalBoundary,
                TransmissionLine, Criteria (all SI, frozen dataclasses; Board.validate())
  io/config.py  pydantic v2 schema → Board; units parsed at the boundary; `mechanical:` link;
                `kicad:` section (KiCad geometry + YAML electrical overlay)
  io/sexpr.py   S-expression reader;  io/kicad.py  .kicad_pcb → stack-up, outline, copper, vias, footprints
  io/           gerber.py excellon.py pnp.py dxf.py dwg.py step.py mech.py cad.py (types)
  materials/    YAML DB (σ, α, εr, tanδ, k, ρ, cp, ε)
  mesh/         2.5D structured grid per conductor layer
  solvers/      base.py (Solver ABC, registry, _BUILTINS), dc_ir.py, thermal.py, coupled.py, si.py
  si/           analytic.py (HJ, IPC-2141, Cohn, Wheeler), fem2d.py (scikit-fem P2),
                xsection.py (stack-up → cross-section, formula choice + accuracy)
  registration/ transform, solve (RANSAC/Umeyama/ICP), features, checks, thermal_bc,
                pipeline (match.json), report (HTML+SVG), layermap
  post/         heatmap.py (per-layer PNG), convergence.py (coupled ΔT/ΔV plot),
                results_loader.py + report.py + report_sections.py + html_kit.py (`pcbsim report`)
  runner.py     config → mesh → solvers → results.json/npz/png
  cli.py        check | run [--solver --force] | match | z0 | report [--out] | solvers
tests/          one file per module; cad_fixtures.py generates KiCad/FreeCAD-style Gerber/DXF,
                kicad_fixtures.py generates .kicad_pcb boards (examples/kicad/)
examples/       soc_4layer.yaml; mech/ (gerber, mech.dxf, layers.yaml, match.json, report);
                kicad/ (soc_4layer.kicad_pcb + soc_kicad.yaml overlay)
docs/           theory.md (§1–9 + references), config.md, registration.md, HANDOFF.md
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
* KiCad: tested on generated KiCad-8-format files, not yet on boards saved by a real KiCad install. Footprint graphics, text, dimensions and keep-outs are ignored. Trapezoid pads use their bounding box, and the barrel inside a through-hole pad is not removed from the copper. Thermal properties of KiCad dielectrics come from fr4/ro4350b. Via plating and fill come from `kicad.vias` because the file doesn't store them.
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

## Stage 6 (KiCad input): what was built

* `pcbsim/io/sexpr.py`: S-expression reader (quoted/bare atoms, escapes, errors with context).
* `pcbsim/io/kicad.py`: `read_kicad(path, origin)` → `KicadBoard`. It reads:
  * stack-up incl. dielectric sub-layers, εr and tanδ (into `kicad:<layer>` materials)
  * user layer names (`L1_TOP` instead of `F.Cu`)
  * Edge.Cuts outline with arcs and cutouts
  * nets (GND-like names become ground)
  * tracks and track arcs, buffered
  * pads: rect, circle, oval, roundrect, custom; plated holes become vias
  * filled zones; unfilled zones are approximated with a note
  * blind and through vias with annular rings
  * footprints: courtyard (else pad hull), side, pad nets

  Coordinates are flipped to y-up, with the board's lower-left corner at (0, 0) by default.
* Config: a new `kicad:` section with `file`, `origin`, `nets` filter, `components: listed|all`, and `vias` plating/fill rules.
  * `board.outline` / `board.stackup` become optional and act as overrides.
  * `components` may omit geometry (it comes from the footprint).
  * Nets, layers, and refs in ports, boundaries, and lines resolve against the file.
  * A bare `.kicad_pcb` passed to `check` or `run` is loaded geometry-only.
* `pcbsim check` prints import counts and notes, and warns about tracks narrower than the mesh on nets that carry ports.
* Example `examples/kicad/` (generated by `python -m tests.kicad_fixtures examples/kicad`): the SoC board as a KiCad 8 file plus an overlay. It reproduces the YAML example's DC result to 1e-9, with Tj within 0.1 K (the extra annular rings and pads are the only difference).
* Tests (`tests/test_kicad.py`, 31): parser, arc tolerance, pad areas vs closed forms, outline with arcs and cutout, rotation and bottom side, origins, through-hole pads, unfilled zones, missing stack-up, KiCad 9 net syntax, overlay merging and errors, physics parity, CLI.

## Stage 7 (report): what was built

* `pcbsim report <results-dir|results.json> [--out file.html]`, default `<results-dir>/report.html`. Read-only: it never re-runs solvers or changes `results.json`.
* `pcbsim/post/results_loader.py` validates the envelope (`pcbsim_version` with the same major version, `solvers` object, per-solver list/object types). It raises `ResultsError` (exit 1) with the file, line and column for broken JSON, and a hint to run `pcbsim run` when the file is missing. PNGs directly in the folder are embedded as data URIs after a magic-byte, size (15 MB each, 80 MB total) and no-symlink-escape check; skipped files are listed in the report.
* `pcbsim/post/report.py` + `report_sections.py`, `html_kit.py`: summary, violations vs warnings (separate tables, badges with text), per-net source/sink IR-drop tables + per-layer J_max, vias (top 25 by utilisation, rest collapsed), components (Tj in °C, margin), coupled status/history table + inline SVG semilog chart + `coupled_convergence.png` + coupled-vs-uncoupled table, SI line table, heat maps with a quantity/layer filter, info notes and a raw scalars appendix. All text is escaped; null/non-finite values show as "–". Inline CSS + ~20 lines of JS (sorting, filter); no network resources.
* Verdict: FAIL when any `violation` severity exists or `passed` is false (exit 4); warnings alone PASS (exit 0). `--out` must end in `.html` and must not be `results.json` (exit 2).
* Tests: `tests/test_report.py` (15) — success path, escaping, `--out`, violations, warnings-only, partial solvers + nulls/NaN, missing dir/file, six kinds of broken JSON.
* Limits: coupled tolerances (tol_t/tol_v) are not in `results.json`, so the report points to the config. With several sources on one net, `results.json` does not say which source feeds which sink, and the report says so. No separate `report.json` was added. Visual check on a phone-width browser not done yet (the layout uses a responsive grid and horizontally scrolling tables).
* On Windows, run the test suite with `PYTHONUTF8=1`: some older tests read files with the locale codec (cp949 here).

## Next step (stage 8: optional Streamlit GUI, openEMS)

Not started. Note: `origin/feat/report-gui-tool` holds an earlier unreviewed automated draft (`pcbsim/report.py`, `pcbsim/gui/theme.py`); it was not used for stage 7.

Working conventions used so far: module docstrings with formulas and sources, a theory.md section per stage, tests against analytic solutions, the example config updated, and a stop for user confirmation after each stage.
