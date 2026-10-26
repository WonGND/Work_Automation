# UI/UX reference notes

pcbsim's user-facing workflow follows the conventions of established PCB power-integrity and thermal tools. These notes were taken **only from publicly available vendor online help and training material**; no software was installed, disassembled, or inspected. Each item records the public convention and how pcbsim maps it.

Sources: Ansys public online help, "Computing DC IR Simulations", "Viewing DC IR Results", and "Exporting DC IR Information" (SIwave, 2024 R2 / 2025 R2), plus "Adding Sources, Probes, and Terminals" (Circuit/3D Layout).

## 1. Workflow shape

| public convention (SIwave DC IR wizard) | pcbsim equivalent |
| --- | --- |
| Pick a net, then assign each component a role: voltage source, current source, probe | `ports:` with `kind: voltage_source / current_sink`, bound to a `net` and either a region or a `component:` ref |
| "Distributed current" spreads current over every pin; "constant" uses one lumped element | Stage 2: a `distribution: uniform \| lumped` port option (uniform is the default) |
| **Validate** before simulating; a validation-check report lists problems | `pcbsim check` prints a summary and a `[ok]/[warn]` checklist; `--strict` turns warnings into a non-zero exit |
| A uniform design temperature can be set, or a temperature map imported from the thermal tool | Stage 4: `coupled` passes the thermal map back; `dc_ir` also accepts `temperature: <°C>` |
| Pick an ideal ground node so every voltage has a reference | `ports[].reference_net`; stage 2 solves the power and return nets separately, each referenced to its own source |

## 2. Results views to provide

| public convention | pcbsim plan |
| --- | --- |
| Per-layer overlays of V, J, via current Iv, and power density P; one quantity at a time, any set of layers | `post/` heat maps: one PNG per (quantity, layer); the HTML report has a layer/quantity selector |
| Element tables (vias, sources, sinks) with sortable columns and a **Pass/Fail** column against a current limit | JSON `elements.vias[]` / `ports[]` records, plus HTML sortable tables with pass/fail badges |
| Metallization search for areas over a voltage/current-density/power-density threshold | `violations[]` with `check`, `subject`, `value`, `limit`, and `location`, so a reviewer can jump to the hotspot |
| **Power tree**: current and drop per branch, compared with expected values per load | Stage 7: a per-net source → sink table with V_min, drop %, and pass/fail |
| Loop and path resistance between terminals | Stage 2 scalar: `R_path[source→sink]` = (V_src − V̄_sink) / I_sink |
| Solver convergence plot | Stage 4: coupled-iteration history (ΔT, ΔV per iteration) in JSON and as a plot |
| HTML report export | `pcbsim report results/` → `report.html` + `results.json` |

## 3. Text output conventions (CLI)

* Lead with a summary: board size, copper layer count, total thickness.
* Stack-up table, top → bottom, with a derived property per row (sheet resistance for copper, εr for dielectrics), so unit or thickness mistakes show up before solving.
* A per-net table: shape, via, source, and sink counts, plus the total load current.
* Heat source table with total power, so it can be checked against the expected budget (5 W in the example).
* Criteria are echoed back in user units (%, °C).
* Exit codes: 0 ok, 1 invalid input, 2 usage error, 3 not implemented.
