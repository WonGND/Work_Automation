# pcbsim — Theory and References

This document collects every formula pcbsim uses and where it comes from. Only public sources are used: textbooks, peer-reviewed papers, published standards, and open-source project documentation. No commercial binaries were disassembled, decompiled, or reverse-engineered.

Sections marked *(stage N)* describe formulas that later stages will implement; they are recorded here early so that the data model and material DB carry the parameters those solvers need.

---

## 1. Units and conventions (stage 1)

All internal quantities are SI. Conversion happens only in `pcbsim/units.py` at the I/O boundary.

| quantity            | conversion                                   | source |
| ------------------- | -------------------------------------------- | ------ |
| mil                 | 1 mil = 25.4 µm (exact)                      | [NIST SP 811] |
| copper weight       | 1 oz/ft² ≡ 1.37 mil = **34.79 µm** (nominal) | [IPC-4562], [IPC-2152] |
| temperature         | T[K] = T[°C] + 273.15                        | [NIST SP 811] |

The physical thickness of 1 oz/ft² of pure copper is t = m / (ρ_m·A) = 28.3495 g / (8.96 g/cm³ × 929.03 cm²) ≈ 34.05 µm. The industry nominal value of 34.79 µm (1.37 mil) is used because it is what fabricators quote and what IPC-2152 charts are based on.

Stack-up z coordinate: layers are ordered top to bottom, z_top(i) = Σ_{j<i} t_j (z grows downward).

---

## 2. Materials (stage 1)

### 2.1 Temperature-dependent resistivity

Linear model, valid for copper roughly over −50…+200 °C:

    ρ(T) = ρ₀ · [1 + α·(T − T_ref)],    σ(T) = 1/ρ(T)

* Annealed copper (100 % IACS): σ₂₀ = 58.0 MS/m (ρ₂₀ = 1.7241×10⁻⁸ Ω·m), α₂₀ = 0.00393 K⁻¹ [IEC 60028].
* Electrodeposited PCB copper is slightly more resistive; pcbsim's `copper_ed` uses σ = 57.5 MS/m [IPC-4562].
* Ansys' public SIwave documentation states that SIwave uses the same linear law with α = 0.004 K⁻¹ and T_ref = 20 °C [Ansys-SIwave-DCIR]. pcbsim's default α = 0.00393 K⁻¹ is the IEC value; set `alpha_r: 0.004` to match that convention for a comparison.

### 2.2 Sheet resistance

For a uniform conductor of thickness t:

    R_s = ρ / t = 1 / (σ·t)    [Ω/□],   R = R_s · L / W   (rectangular strip)

For 1 oz ED copper: R_s = 1 / (5.75×10⁷ × 34.79×10⁻⁶) ≈ 0.500 mΩ/□ at 20 °C (printed by `pcbsim check`).

### 2.3 Thermal diffusivity

    a = k / (ρ_m · c_p)    [m²/s]

### 2.4 Material values

| material         | σ [S/m]  | α [1/K] | εr   | tanδ   | k_xy / k_z [W/m·K] | ρ_m [kg/m³] | c_p [J/kg·K] | ε_rad | sources |
| ---------------- | -------- | ------- | ---- | ------ | ------------------ | ----------- | ------------ | ----- | ------- |
| copper           | 5.80e7   | 0.00393 | –    | –      | 398 / 398          | 8933        | 385          | 0.05  | [IEC 60028], [Incropera] A.1 |
| copper_ed        | 5.75e7   | 0.00393 | –    | –      | 385 / 385          | 8933        | 385          | 0.05  | [IPC-4562], [Incropera] |
| fr4              | –        | –       | 4.3  | 0.02   | 0.81 / 0.29        | 1850        | 1100         | 0.9   | [IPC-4101], [Azar-Graebner] |
| ro4350b          | –        | –       | 3.48 | 0.0037 | 0.69 / 0.69        | 1860        | 920          | 0.9   | [Rogers-RO4000] |
| soldermask       | –        | –       | 3.8  | 0.025  | 0.2 / 0.2          | 1500        | 1000         | 0.9   | [IPC-SM-840], [Incropera] A.11 |
| air              | –        | –       | 1.0006 | 0    | 0.0263             | 1.1614      | 1007         | –     | [Incropera] A.4 |
| sac305           | 7.6e6    | 0.0046  | –    | –      | 58                 | 7380        | 232          | 0.1   | [NIST-Solder] |
| via_fill_epoxy   | 0        | –       | 4.0  | 0.02   | 0.6                | 1600        | 1000         | –     | [IPC-4761] typical |
| via_fill_conductive | 1e6   | 0       | –    | –      | 4                  | 3500        | 500          | –     | vendor-typical (override!) |

FR-4 is strongly anisotropic because of the glass weave. The in-plane and through-plane values follow the measurements of Azar & Graebner [Azar-Graebner]. All values are nominal and should be overridden with laminate data-sheet values when available.

---

## 3. DC IR drop (stage 2) — `pcbsim/solvers/dc_ir.py`, `pcbsim/mesh/grid.py`

### 3.1 Governing equation

Each conductor layer is a thin sheet (thickness t ≪ lateral size), so the current flows in-plane and the 3D conduction equation ∇·(σ∇V) = 0 reduces, after integrating over the thickness, to the 2D Poisson equation

    ∇·(σ t ∇V) = −i_s          i_s = injected current per unit area [A/m²]

This is the "static current conduction" model of [Elmer-Models], specialised to a sheet. The same thin-sheet approximation underlies the planar DC solvers described in the public PDN literature [Swaminathan-Engin].

### 3.2 Discretisation — cell-centred finite volume

All conductor layers share one structured grid of cells Δx × Δy covering the board bounding box (`build_grid`). A cell belongs to a net when its **centre** lies inside a copper polygon of that net (a staircase approximation whose error vanishes as h → 0). Overlapping copper of two different nets on the same layer is reported as a short circuit.

The conductance between two neighbouring same-net cells i, j (x-direction; swap Δx ↔ Δy for y) is two half-cells in series:

    G_ij = 1 / (ρ_i Δx/(2 t Δy) + ρ_j Δx/(2 t Δy))          (harmonic mean of σ)

For a uniform sheet this reproduces R = R_s · L / W exactly (to round-off) as long as the port edges fall on cell faces, which is verified in `tests/test_dc_ir.py`. Assembly gives the symmetric positive-definite system K·V = b with K = Σ G (e_i − e_j)(e_i − e_j)ᵀ, which is solved directly (`scipy.sparse.linalg.spsolve`, SuperLU) or with Jacobi-preconditioned CG.

### 3.3 Vias — 1D inter-layer resistors

A via connects the cell containing (x, y) on every conductor layer of its span that carries copper of the via's net. Consecutive pierced layers a, b are joined by

    G_via = (σ_barrel · A_barrel + σ_fill · A_fill) / L
    A_barrel = (π/4) · [d² − (d − 2 t_p)²],    A_fill = (π/4) · (d − 2 t_p)²  (filled vias only)
    L = |z_c(a) − z_c(b)|   (centre-to-centre distance, `Stackup.span`)

A via that touches fewer than two layers with its own net's copper is reported and ignored. Antipad clearances are not modelled; plane copper is assumed continuous around the barrel.

### 3.4 Ports (boundary conditions)

| port | model |
| --- | --- |
| voltage source (VRM) | all cells in the region merge into one node with Dirichlet V = V_set; the merged region is a perfect conductor, so a link from it to a neighbour is only the neighbour's half-cell |
| current sink, `distribution: uniform` | −I/n drawn from each of its n cells (a current source per pin) |
| current sink, `distribution: equipotential` | the cells merge into one node drawing −I (pins shorted by the die) |
| `reference_net` | return terminal on the reference net: 0 V Dirichlet for sources, +I injection for sinks. Layer = `reference_layer`, or the nearest conductor layer with reference-net copper under the region |

The voltage *seen* by a sink is the worst pin pair, V_seen = min V_net − max V_ref, and

    drop % = (V_nom − V_seen) / V_nom × 100,      R_path = (V_nom − mean V_net + mean V_ref) / I

These follow the "sink voltage vs expected value / pass-fail" and "path resistance" conventions documented in the public SIwave help (see `docs/ui_ux.md`). Floating copper (islands without a source) is reported, and a current sink in an island without a source is an error.

### 3.5 Temperature dependence

Per cell, ρ(T) = ρ₀ [1 + α (T − T_ref)] (§2.1), from a uniform `temperature` option (°C) or a `temperature_field` array (K) that the stage-4 coupled solver will supply.

### 3.6 Post-processing

* Link current I_ij = G_ij (V_i − V_j). Joule power P_ij = G_ij (V_i − V_j)² is split between the two end cells in proportion to their half-cell resistances; vias split 50/50. Energy conservation Σ P = Σ V_src I_src + Σ V_k b_k is checked in the tests.
* Cell current density: for each axis, the mean of the signed currents on the two faces of the cell, divided by t·Δy (or t·Δx); J = √(J_x² + J_y²). At re-entrant copper corners (for example the end of a plane slot) the exact J is singular (∝ r^(−1/3) for a 270° corner [Williams-1952]), so the peak cell value grows slowly with refinement. Corner hot spots mean "add a radius or widen the neck"; they are not mesh errors.

### 3.7 Current-density and via limits (`pcbsim/standards/ipc.py`)

IPC-2152 publishes charts only. pcbsim uses the closed-form fit to the IPC-2152 data by Brooks & Adam [Brooks-Adam], the same fit KiCad's track-width calculator uses [KiCad-TW]:

    ΔT = K · I^a · W^b · Th^c         (W, Th in mil, ΔT in K)
    external: K = 215.3, a = 2.0, b = −1.15, c = −1.0
    internal: 0.5 oz K = 120, a = 2.0, b = −1.10;  1 oz K = 200, a = 1.9, b = −1.10;
              2 oz K = 300, a = 2.0, b = −1.15;  3 oz K = 262.5, a = 1.9, b = −1.15;  c = −1.52

Solved for I, this gives the allowed current of a reference conductor of width W_ref (`criteria.current_density_ref_width`, default 1 mm) on each layer; the sheet limit is J_allow = I(W_ref, t) / (W_ref · t). Outer layers use the external fit; inner layers use the internal fit for the nearest copper weight. `criteria.current_density_limit` overrides this with a fixed value. The legacy IPC-2221B chart fit I = k ΔT^0.44 A^0.725 (k = 0.048 external, 0.024 internal; A in mil²) [IPC-2221] is available as `current_density: ipc2221`.

Via barrels are checked as an internal conductor of width π·d and thickness t_p (the unrolled barrel wall) with the same fit. This is a heuristic warning, not a pass/fail criterion.

## 4. Thermal (stage 3) — `pcbsim/solvers/thermal.py`

### 4.1 Governing equation and the 2.5D compact model

Heat conduction with internal sources [Incropera, ch. 2]:

    ρ_m c_p ∂T/∂t = ∇·(k ∇T) + q'''

A PCB is a stack of thin, strongly anisotropic layers: copper k ≈ 390 W/m·K and FR-4 k_z ≈ 0.3 W/m·K. The standard compact treatment, a "layer-lumped" network, keeps one temperature sheet per copper layer and lets the dielectrics act as in-plane spreaders and through-plane resistances [Lemczyk-1992], [Graebner-AN]. pcbsim uses this model on the shared grid of §3.2:

* Each conductor layer is a sheet of nodes, one per board cell (cells inside the outline, with or without copper).
* An **inner dielectric** is split half and half between the two copper sheets around it, adding to their in-plane conductance k·t and heat capacity ρ c_p t A, and contributes t/k_z to the through-plane resistance between them.
* An **outer layer** (solder mask, or a dielectric outside the outer copper) is lumped entirely into the outer sheet and adds t/k_z in series with the surface.
* Where a conductor layer has no copper, its thickness is filled with the adjacent dielectric (`fill_material` overrides this).

### 4.2 Discretisation

In-plane conductance between neighbours i, j (x-direction; swap Δx ↔ Δy for y):

    G_ij = 1 / [ (Δx/2)/((kt)_i Δy) + (Δx/2)/((kt)_j Δy) ],    (kt) = k_cell t_cu + Σ_lumped k_xy,d t_d

Through-plane conductance between consecutive sheets a, b per cell (series):

    G_ab = A / [ t_a/(2 k_z,a) + Σ_d t_d / k_z,d + t_b/(2 k_z,b) ]

Thermal vias run parallel to that path, between consecutive pierced sheets:

    G_via = (k_barrel A_barrel + k_fill A_fill) / L     (A as in §3.3; L = Stackup.span)

A via pierces its `from` and `to` layers (pads) and every layer in between that carries copper of its own net at the via location; elsewhere it passes through an antipad.

### 4.3 Boundary conditions

Surface convection plus radiation, per face cell, in series with the outer-layer resistance R_s:

    G_face = A / ( R_s + 1/(h + h_rad) ),     R_s = t_cu/(2 k_z,cu) + Σ_outer t/k_z
    q_rad  = ε σ_SB (T_s⁴ − T_∞⁴) = h_rad (T_s − T_∞),    h_rad = ε σ_SB (T_s² + T_∞²)(T_s + T_∞)

The linearised h_rad is exact at the converged surface temperature T_s. pcbsim updates it by Picard iteration in steady state (tolerance `picard_tol`, K) and from the previous step in transient runs. The emissivity defaults to the outermost layer's material (solder mask ε = 0.9). Board edges use `h_edge` (default 0, adiabatic).

Typical h values: natural convection from a horizontal board in still air is 5–15 W/m²·K [Incropera, ch. 9]; forced air at 1–3 m/s is roughly 20–60 W/m²·K.

`thermal_boundaries`:

* `fixed_temperature`: Dirichlet T = T_set on the outer-sheet cells under the region (chassis standoff, cold plate).
* `convection`: replaces h on that face under the region by `h` or by 1/(R·A), towards its own `ambient`, with radiation off there. With `component:` it instead defines the case-to-ambient path of that package (a heat sink).

### 4.4 Components (JEDEC two-resistor model)

If a component has `theta_jb`, it gets a junction node (JEDEC JESD15-3 two-resistor compact model [JESD15-3]):

    junction ──θ_jb── board (outer-sheet cells under the footprint, split by area)
    junction ──θ_jc + R_ca── ambient,   R_ca = 1/(h_face A_fp)  or a heat-sink boundary

The board face under the package does not convect. Without `theta_jc` and without a heat sink, the top path is open (conservative). Without `theta_jb`, the power is spread uniformly over the footprint cells of the outer sheet and Tj is reported as the hottest board cell under the footprint, which underestimates Tj by P·θ_jb.

### 4.5 Heat sources

* Component power `power` (W).
* Joule heat from an upstream `dc_ir` result on the same mesh (§3.6), injected cell by cell into each copper layer's sheet (option `joule`, default on). Alternatively an explicit `joule_field` array, as used by the coupled solver.

The runner orders solvers by their declared dependencies, so `thermal` always runs after `dc_ir` when both are requested.

### 4.6 Transient

Implicit (backward) Euler [Patankar, ch. 4]:

    (C/Δt + K) Tⁿ⁺¹ = (C/Δt) Tⁿ + G_amb T_∞ + s(tⁿ⁺¹) P

This scheme is unconditionally stable and first-order accurate in Δt. C is the lumped heat capacity of each node; junction nodes have C = 0, so they follow the board instantly. `power_steps` sets a piecewise-constant power scale s(t). The initial state is `ambient`, `steady` (steady solution at s(0)), or a uniform temperature. Without radiation the matrix is factorised once; with radiation it is re-factorised every step.

### 4.7 Verification (tests/test_thermal.py)

* 1D fin with convection from both faces, base clamped: T(x) − T_∞ = θ_b cosh m(L−x) / cosh mL, with m = √(2 h_eff/(k t)) and h_eff = 1/(1/h + t/(2k)) [Incropera §3.6]. Error < 2 % (in practice ~1e-5).
* Insulated bar with uniform generation q and both ends clamped: parabolic profile, exact at nodes.
* Two-layer slab through-thickness resistance; thermal via ΔT·G = P.
* Lumped-capacitance transient T(t) = T_∞ + P/G (1 − e^(−t/τ)), τ = C/G [Incropera §5.2]: backward-Euler error shrinks with Δt.
* Global energy balance: Σ heat out = P_in in steady state, to round-off.

## 5. Electro-thermal coupling *(stage 4)*

Picard iteration:

1. Solve DC IR with σ(T_k).
2. Joule heating density q = J²/σ = σ |∇V|² → heat source in each layer.
3. Solve thermal → T_{k+1}.
4. Stop when max|ΔT| < tol_T and max|ΔV| < tol_V.

With α = 0, ρ(T) = ρ₀ and the result must equal the uncoupled solution (regression test).

---

## 6. Current-density limits

Implemented in stage 2; see §3.7.

---

## 7. Signal integrity — characteristic impedance *(stage 5)*

* Microstrip: Hammerstad & Jensen closed-form equations for ε_eff and Z0, with the thickness correction [Hammerstad-Jensen], [Wadell].
* Stripline and differential pairs: IPC-2141A equations [IPC-2141A], [Wadell].
* Cross-check: a 2D electrostatic FEM cross-section solve (scikit-fem) of ∇·(ε∇φ) = 0 gives per-unit-length capacitance C (with dielectric) and C₀ (in air), from which Z0 = 1 / (c₀ √(C C₀)) and ε_eff = C / C₀.

---

## References

* **[NIST SP 811]** A. Thompson, B. N. Taylor, *Guide for the Use of the International System of Units (SI)*, NIST SP 811, 2008.
* **[IEC 60028]** IEC 60028:1925, *International standard of resistance for copper*.
* **[IPC-4562]** IPC-4562A, *Metal Foil for Printed Board Applications*, 2008.
* **[IPC-4101]** IPC-4101E, *Specification for Base Materials for Rigid and Multilayer Printed Boards*.
* **[IPC-SM-840]** IPC-SM-840E, *Qualification and Performance Specification of Permanent Solder Mask*.
* **[IPC-4761]** IPC-4761, *Design Guide for Protection of Printed Board Via Structures*, 2006.
* **[IPC-2152]** IPC-2152, *Standard for Determining Current Carrying Capacity in Printed Board Design*, 2009.
* **[IPC-2221]** IPC-2221B, *Generic Standard on Printed Board Design*, 2012.
* **[IPC-2141A]** IPC-2141A, *Design Guide for High-Speed Controlled Impedance Circuit Boards*, 2004.
* **[Incropera]** F. P. Incropera, D. P. DeWitt, T. L. Bergman, A. S. Lavine, *Fundamentals of Heat and Mass Transfer*, 7th ed., Wiley, 2011.
* **[Azar-Graebner]** K. Azar, J. E. Graebner, "Experimental determination of thermal conductivity of printed wiring boards," *Proc. IEEE SEMI-THERM*, 1996.
* **[Hammerstad-Jensen]** E. Hammerstad, Ø. Jensen, "Accurate models for microstrip computer-aided design," *IEEE MTT-S Int. Microwave Symp. Dig.*, 1980, pp. 407–409.
* **[Wadell]** B. C. Wadell, *Transmission Line Design Handbook*, Artech House, 1991.
* **[Rogers-RO4000]** Rogers Corp., *RO4000® Series High Frequency Circuit Materials* data sheet (public).
* **[NIST-Solder]** NIST, *Database for Solder Properties with Emphasis on New Lead-free Solders*, 2002.
* **[Elmer-Models]** CSC, *Elmer Models Manual* (open-source documentation).
* **[scikit-fem]** T. Gustafsson, G. D. McBain, "scikit-fem: A Python package for finite element assembly," *JOSS* 5(52), 2369, 2020.
* **[openEMS]** T. Liebig, openEMS documentation, <https://openems.de>.
* **[KiCad]** KiCad file format documentation, <https://dev-docs.kicad.org/en/file-formats/>.
* **[Lemczyk-1992]** T. F. Lemczyk, B. L. Mack, J. R. Culham, M. M. Yovanovich, "PCB trace thermal analysis and effective conductivity," *J. Electronic Packaging* 114(4), 1992.
* **[Graebner-AN]** J. E. Graebner, "Thermal conductivity of printed wiring boards," Electronics Cooling, 1995.
* **[JESD15-3]** JEDEC JESD15-3, *Two-Resistor Compact Thermal Model Guideline*, 2008.
* **[Patankar]** S. V. Patankar, *Numerical Heat Transfer and Fluid Flow*, Hemisphere, 1980.
* **[Brooks-Adam]** D. G. Brooks, J. Adam, "Trace Currents and Temperatures Revisited," UltraCAD Design / ADAM Research, 2015 (fit to IPC-2152 data, Table 3-1).
* **[KiCad-TW]** KiCad source documentation, `TRACK_WIDTH_CALCULATIONS` namespace (pcb_calculator), <https://docs.kicad.org/doxygen/namespaceTRACK__WIDTH__CALCULATIONS.html>.
* **[Swaminathan-Engin]** M. Swaminathan, A. E. Engin, *Power Integrity Modeling and Design for Semiconductors and Systems*, Prentice Hall, 2007.
* **[Williams-1952]** M. L. Williams, "Stress singularities resulting from various boundary conditions in angular corners of plates in extension," *J. Appl. Mech.* 19, 1952 (corner singularity exponents for the Laplace/elasticity problems).
* **[Ansys-SIwave-DCIR]** Ansys public online help: "Computing DC IR Simulations" and "Viewing DC IR Results" (SIwave 2025 R2). These pages were consulted only for workflow and UX conventions and for the publicly stated ρ(T) law; see `docs/ui_ux.md`.
