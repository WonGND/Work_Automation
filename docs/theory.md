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

## 7. Signal integrity — characteristic impedance (stage 5) — `pcbsim/si/`, `pcbsim/solvers/si.py`

Quasi-TEM, lossless, non-magnetic lines. Every configured line is solved twice: by a 2D field solver (the reported value) and by the best closed form for its topology (a cross-check).

### 7.1 Closed forms (`pcbsim/si/analytic.py`)

η₀ = μ₀c₀ ≈ 376.73 Ω.

**Microstrip, Hammerstad–Jensen** [Hammerstad-Jensen], [Wadell] §3.5, u = w/h:

    f(u)   = 6 + (2π − 6)·exp(−(30.666/u)^0.7528)
    Z01(u) = η₀/(2π) · ln(f/u + √(1 + (2/u)²))                       (air, < 0.01 %)
    a = 1 + ln((u⁴ + (u/52)²)/(u⁴ + 0.432))/49 + ln(1 + (u/18.1)³)/18.7
    b = 0.564·((εr − 0.9)/(εr + 3))^0.053
    εe(u)  = (εr + 1)/2 + (εr − 1)/2 · (1 + 10/u)^(−ab)                (< 0.2 %)
    Z0 = Z01(u)/√εe(u)

Thickness correction: Δu₁ = (t/h)/π·ln(1 + 4e/((t/h)·coth²√(6.517u))), Δu_r = ½(1 + sech√(εr − 1))·Δu₁, then Z0 = Z01(u + Δu_r)/√εe(u + Δu_r) and εe = εe(u + Δu_r)·(Z01(u + Δu₁)/Z01(u + Δu_r))².

**IPC-2141A** [IPC-2141A] (approximate, ±5–10 %, documented ranges noted in results):

    microstrip            Z0 = 87/√(εr + 1.41) · ln(5.98h/(0.8w + t))         0.1 < w/h < 2
    centred stripline     Z0 = 60/√εr · ln(1.9b/(0.8w + t))                   w/(b − t) < 0.35
    offset stripline      Z0 = 80/√εr · ln(1.9(2h₁ + t)/(0.8w + t)) · (1 − h₁/(4(h₁ + h₂ + t)))
    diff. microstrip      Zdiff = 2Z0 (1 − 0.48 e^(−0.96 s/h))
    diff. stripline       Zdiff = 2Z0 (1 − 0.347 e^(−2.9 s/b))

**Stripline, exact for t = 0** — Cohn, conformal mapping [Cohn-1954], [Pozar] §3.7:

    k = sech(πw/2b),  Z0 = η₀/(4√εr) · K(k)/K(k′)

**Stripline with thickness** — Wheeler [Wheeler-1978], [Wadell] §4.2.2.2 (≤ 0.5 %):

    x = t/b,  m = 6/(3 + 2x/(1 − x))
    Δw/(b − t) = x/(π(1 − x)) · (1 − ½ln[(x/(2 − x))² + (0.0796x/(w/b + 1.1x))^m])
    W = w/(b − t) + Δw/(b − t)
    Z0 = 30/√εr · ln(1 + 4/(πW)·[8/(πW) + √((8/(πW))² + 6.27)])

**Edge-coupled stripline, exact for t = 0** — Cohn [Cohn-1955]:

    k_e = tanh(πw/2b)·tanh(π(w + s)/2b),   k_o = tanh(πw/2b)·coth(π(w + s)/2b)
    Z_{e,o} = η₀/(4√εr) · K(k′_{e,o})/K(k_{e,o}),   Zdiff = 2Z_o,   Zcomm = Z_e/2

### 7.2 2D electrostatic field solver (`pcbsim/si/fem2d.py`)

The cross-section potential satisfies ∇·(εr∇φ) = 0 with φ = 1 V on one signal conductor, 0 on all other conductors, the reference planes, and a distant rectangular shield. With φᵢ the solution for conductor i, the Maxwell capacitance matrix per unit length is the energy form

    C_ij = ε₀ ∫ εr ∇φᵢ·∇φⱼ dA = ε₀ φᵢᵀ K φⱼ

It is computed twice: with the dielectrics (C) and in vacuum (C⁽⁰⁾). For quasi-TEM lines [Pozar] §3.8, [Wadell] §1.4:

    L = μ₀ε₀ (C⁽⁰⁾)⁻¹,   Z0 = 1/(c₀√(C·C⁽⁰⁾)),   εeff = C/C⁽⁰⁾

For a symmetric pair the modal capacitances are C_o = C₁₁ − C₁₂ and C_e = C₁₁ + C₁₂, giving Z_odd, Z_even, Zdiff = 2Z_odd and Zcomm = Z_even/2.

Discretisation: quadratic Lagrange triangles (P2, scikit-fem [scikit-fem]) on a tensor grid that contains every conductor edge and dielectric interface. Spacing grows geometrically (ratio 1.25) from h_min = (smallest feature)/24 at conductor edges, where the field is singular (φ ∝ r^(2/3) at a 90° corner [Williams-1952]). εr is constant per element. The shield sits 30 × the feature size away. Its effect on an open microstrip is < 0.1 % (test `test_box_size_effect_small`).

### 7.3 Stack-up → cross-section (`pcbsim/si/xsection.py`)

The ground-side reference is the nearest conductor layer below the trace (for a bottom-side microstrip, the one above it, with the stack flipped). A stripline has a second reference on the other side. `references:` overrides both. Dielectric layers between them become bands. The trace's own layer is filled with the dielectric on its far side: prepreg flows around inner traces, and an outer layer sees solder mask or air. A solder mask over a microstrip is modelled as conformal, i.e. the mask thickness on bare laminate and as a coating on the trace top and sides. Multiple dielectrics are reduced to one εr for the closed forms by the series (thickness-weighted harmonic) mean.

### 7.4 Checks

* `z0`: |Z − Z_target|/Z_target > tolerance (line `tolerance_pct`, else `criteria.z0_tol_pct`, default 10 %) → violation. Z is Z0 for a single trace and Zdiff for a pair.
* `z0_crosscheck`: |Z_FEM − Z_formula|/Z_formula above the formula's expected accuracy → warning. The expected accuracy is 1 % for HJ/Wheeler, 0.5 % for Cohn, 8–10 % for IPC-2141, ≥ 6 % when solder mask is present, ≥ 3 % for layered dielectrics, and ≥ 15 % outside a formula's validity range.

### 7.5 Verification (`tests/test_si.py`)

* HJ against Pozar Ex. 3.7 (50 Ω on εr = 2.2) and Cohn against Pozar Ex. 3.5, both within 1 % / 0.5 %.
* FEM vs Hammerstad–Jensen microstrip: < 2 % for w/h = 0.5…3, εr = 2.2…4.3, with and without trace thickness. In practice the difference is 0.1–0.4 %.
* FEM vs Cohn exact stripline and coupled stripline: < 1 %. FEM vs Wheeler thick stripline: < 1 %.
* Mesh convergence: halving h_min (1/16 → 1/128 of the feature) strictly lowers the error against Cohn's exact value, down to < 0.2 %.
* Capacitance matrix: symmetric, C₁₂ < 0, and C = εr·C⁽⁰⁾ in a homogeneous dielectric.

---

## 8. ECAD–MCAD registration — `pcbsim/io/{gerber,excellon,dxf,dwg,step}.py`, `pcbsim/registration/`

Only public format specifications are used: the Ucamco Gerber Layer Format Specification (RS-274X, X2, X3) [Gerber], the Excellon NC drill format [Excellon], the Autodesk DXF Reference [DXF], and the public command-line documentation of ODA File Converter and LibreDWG for DWG → DXF conversion [ODA], [LibreDWG]. DWG binaries are never parsed by pcbsim. IPC-2581 and ODB++ are public too; they are listed as future inputs and are not implemented yet. No CAD or CAM software was disassembled or reverse-engineered.

### 8.1 Input geometry

| item | formula / rule | source |
| --- | --- | --- |
| Gerber coordinate | `v = n · 10^−d` (format `%FSLAXidYid%`), unit `%MOMM%` / `%MOIN%` | [Gerber] §4.2, §4.9 |
| arc centre (G75) | `c = p_start + (I, J)`; start = end ⇒ full circle | [Gerber] §4.7.2 |
| arc centre (G74) | candidate `p_start + (±I, ±J)` whose sweep is ≤ 90° | [Gerber] §8.2.3 |
| arc flattening | `n = ⌈θ / (2 acos(1 − s/r))⌉`, sagitta `s` ≤ 1 µm, n ≥ 64 per full turn (area error ≤ 0.16 %) | geometry |
| stroke, circular aperture | Minkowski sum of the centre line and a disc = buffer by d/2 | [Gerber] §4.8 |
| stroke, rectangular aperture | convex hull of the rectangle at both end points | [Gerber] §4.8 |
| macro expressions | `+ − x /` with precedence, unary minus, `$n` variables | [Gerber] §4.5.4 |
| region | each G36/G37 contour is a dark object; contours are united | [Gerber] §4.10 |
| polarity | image = (((D₁ ∪ D₂) ∖ C₁) ∪ D₃) … in file order | [Gerber] §4.9.2 |
| Excellon `LZ` | leading zeros kept ⇒ `v = int(digits) / 10^(len − n_int)` | [Excellon] |
| Excellon `TZ` | trailing zeros kept ⇒ `v = int(digits) / 10^n_dec` | [Excellon] |
| DXF units | `$INSUNITS` code → metres (1 in, 4 mm, 5 cm, 6 m, 9 mil, 13 µm …) | [DXF] HEADER |
| DXF bulge | arc angle `θ = 4 atan(bulge)` (group code 42) | [DXF] LWPOLYLINE |
| DXF OCS | arbitrary axis algorithm: `Ax = Wy × N` if \|Nx\|,\|Ny\| < 1/64 else `Wz × N`; `Ay = N × Ax` | [DXF] "Object Coordinate Systems" |
| DXF 2.5D | item spans `[elevation, elevation + thickness]` (group codes 38, 39) | [DXF] |

### 8.2 Registration

The unknown transform maps drawing points `x` to board points `y`:

    y = s · R(θ) · M · x + t,    M = diag(−1, 1) for a bottom-view drawing, else I

1. **Hypotheses (RANSAC, 2-point minimal sets)** [Fischler-Bolles]. Each drawing pair (a, b) is paired with each board pair (a′, b′) of equal length (`|s·|ab| − |a′b′|| ≤ tol`, binary search in the sorted pair lengths) and compatible diameters. θ follows from the pair directions. Mirror and each candidate scale (1, 25.4, 1/25.4, 10, 0.1, 1000, 1/1000 when unit detection is enabled) are tested as separate hypotheses.
2. **Consensus.** Features are inliers if the nearest compatible board feature (k-d tree) is within `tol`; matching is one-to-one, closest first.
3. **Refinement — weighted Umeyama / Kabsch** [Umeyama-1991], [Kabsch-1976]:

        μx = Σwx/Σw,  μy = Σwy/Σw,  Σxy = Σ w (y−μy)(x−μx)ᵀ / Σw
        U D Vᵀ = svd(Σxy),  S = diag(1, sign(det U · det V))
        R = U S Vᵀ,  s = tr(D S)/σx²  (or fixed),  t = μy − s R μx

   `S` forces a proper rotation, so a reflection is only ever introduced through `M`. Re-match → re-fit until the correspondence set is stable.
4. **Ambiguity.** Refined hypotheses that tie on inlier count and RMS are clustered (two transforms are the same if they move every point of the board-sized square by less than `tol`). More than one cluster means the reference pattern is symmetric, e.g. four holes in a rectangle. pcbsim reports NG and asks for an asymmetric reference hole or an `anchors` entry instead of guessing.
5. **Outline ICP** [Besl-McKay-1992]. Drawing outline samples (even spacing plus every vertex) are projected onto the exact nearest point of the board outline segments. Hole pairs and outline samples are refitted jointly with step 3 (outline weight 0.2 per hole-equivalent) until the update moves no point by more than 1e-12 m. The ICP result is accepted only if it improves the outline RMS by more than 1 %, loses no hole match, and keeps the hole RMS within max(2×, tol/10). Otherwise the hole-only transform is kept, so a wrong drawing outline (the very thing the outline check must report) cannot drag the fit. Feature RMS, maximum residual, and outline RMS before and after ICP are reported.

Transforms are compared on a square around the drawing's features, not around the file origin, so a board placed far from (0, 0) does not inflate rotation differences. Anchors are enforced after refinement.

With exact data the true transform is a fixed point of every step, which is what the 1e-6 mm recovery tests rely on.

### 8.3 Checks

| check | measure | default limit |
| --- | --- | --- |
| hole position | `|p_mech − p_drill|` of nearest pairs (one-to-one within 2 mm) | 0.1 mm |
| hole diameter | `d_mech − d_drill` | ±0.1 mm |
| hole missing / extra | unpaired drill ≥ 1 mm / unpaired drawing hole | NG |
| outline | symmetric Hausdorff `d_H(A,B) = max(sup_a d(a,B), sup_b d(b,A))` of the exterior rings (densified to 5 % of each segment) | 0.2 mm |
| cutouts | interior rings paired by centroid, Hausdorff per pair; unpaired = NG | 0.2 mm |
| component position | body footprint centroid vs. placement point (X3 `ComponentMain`, `TO.C` pad centroid, or PnP CSV) | 0.5 mm |
| component rotation | orientation of the minimum rotated rectangle vs. placement rotation, modulo 90° (a box cannot tell 0° from 90°); skipped for square/round bodies (aspect ≤ 1.05) | 2° |
| height | clearance = ceiling − z_top; ceiling = min(case height, keepout limit over the footprint, underside of case items above it), using only items on the same board side (a mirrored drawing shows the bottom side) | ≥ 0.5 mm |

### 8.4 Thermal boundary conditions from the mechanical model

Electrical geometry (copper, pads, vias) always comes from the ECAD side. The mechanical drawing contributes only boundary conditions:

* **Heat sink with a given resistance** `R_sa` [K/W]: if it lies on a component, it becomes that component's case-to-ambient path in the JEDEC two-resistor model (§4.4); otherwise it is a convection patch with `h = 1/(R_sa · A)`.
* **Plate-fin heat sink** [Incropera] §3.6.4–3.6.5, adiabatic tip with corrected length `L_c = H + t/2`:

        m = √(2h/(k t)),   η_f = tanh(m L_c)/(m L_c)
        A_f = 2 L_c ℓ,   A_b = A_base − N t ℓ,   A_t = N A_f + A_b
        η_o = 1 − (N A_f / A_t)(1 − η_f),   R_sa = 1/(η_o h A_t)

* **Chassis contact**: an ideal contact is a fixed temperature. With a contact resistance `R_c` (or conductance `h_c`), a series resistance to a fixed temperature is exactly a Robin condition with `h = 1/(R_c A)`.
* **Case air gap**: `h_gap = k_air / g` (pure conduction across a gap `g`). This holds while the Rayleigh number stays below the onset of convection, Ra < 1708 [Incropera] §9.8, which covers typical enclosure gaps of a few millimetres.

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
* **[Pozar]** D. M. Pozar, *Microwave Engineering*, 4th ed., Wiley, 2012, §3.7–3.8.
* **[Cohn-1954]** S. B. Cohn, "Characteristic impedance of the shielded-strip transmission line," *IRE Trans. MTT* 2(2), 1954.
* **[Cohn-1955]** S. B. Cohn, "Shielded coupled-strip transmission line," *IRE Trans. MTT* 3(5), 1955.
* **[Wheeler-1978]** H. A. Wheeler, "Transmission-line properties of a stripline between parallel planes," *IEEE Trans. MTT* 26(11), 1978.
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
* **[Gerber]** Ucamco, *The Gerber Layer Format Specification*, revision 2023.08 (public), <https://www.ucamco.com/en/gerber>.
* **[Excellon]** Excellon Automation, *CNC-7 Programming Manual* (format description), and the KiCad Excellon writer documentation <https://dev-docs.kicad.org/>.
* **[DXF]** Autodesk, *DXF Reference* (AutoCAD 2012+), public online documentation; ezdxf documentation <https://ezdxf.readthedocs.io/>.
* **[ODA]** Open Design Alliance, *ODA File Converter* command-line usage (public download page).
* **[LibreDWG]** GNU LibreDWG manual, `dwg2dxf(1)`, <https://www.gnu.org/software/libredwg/>.
* **[IPC-2581]** IPC-2581C, *Generic Requirements for Printed Board Assembly Products Manufacturing Description Data* (future input).
* **[ODB++]** Siemens, *ODB++ Format Specification* v8.1 (public; future input).
* **[Fischler-Bolles]** M. A. Fischler, R. C. Bolles, "Random sample consensus," *Commun. ACM* 24(6), 1981.
* **[Umeyama-1991]** S. Umeyama, "Least-squares estimation of transformation parameters between two point patterns," *IEEE TPAMI* 13(4), 1991.
* **[Kabsch-1976]** W. Kabsch, "A solution for the best rotation to relate two sets of vectors," *Acta Cryst.* A32, 1976.
* **[Besl-McKay-1992]** P. J. Besl, N. D. McKay, "A method for registration of 3-D shapes," *IEEE TPAMI* 14(2), 1992.
