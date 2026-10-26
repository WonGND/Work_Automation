# Config file reference (version 1)

A config is one YAML document. Every length may be a bare number in `units.length` (default `mm`) or a string with a unit: `"10 mil"`, `"35 um"`, `"1 oz"`, `"0.2 mm"`. Bare temperature numbers are °C, or append a unit, e.g. `"378 K"`. Voltage, current, and power accept `"500 mV"`, `"6 A"`, and `"4 W"`.

Unknown keys are errors, so typos never pass silently. Every error is reported with its path, e.g. `board.stackup[2].thickness: unknown length unit 'mll'`.

```yaml
version: 1
name: my_board
units: { length: mm }            # mm | mil | um | in | m

material_files: [my_laminates.yaml]   # optional, relative to the config file
materials:                            # optional inline overrides / new materials
  fr4: { eps_r: 4.2 }
  my_core: { eps_r: 3.9, tan_d: 0.01, k_inplane: 0.6, k_through: 0.3, density: 1900, cp: 1000 }

board:
  outline: { rect: [x0, y0, x1, y1] }  # or polygon: [[x,y],...] / circle: {center, r}
  stackup:                              # top → bottom
    - { name: L1, kind: conductor, thickness: 1 oz, material: copper_ed, role: signal }
    - { name: PP1, kind: dielectric, thickness: 0.2, material: fr4 }

nets:
  - { name: VDD, kind: power, voltage: 1.0 }    # kind: power | ground | signal

shapes:                                 # copper regions
  - { net: GND, layer: L2, fill: true }         # fill = whole board outline
  - { net: VDD, layer: L3, rect: [...], holes: [ { rect: [...] } ] }

vias:
  - { net: VDD, at: [x, y], drill: 0.3, from: L1, to: L3 }   # from/to default: outermost copper
  - { net: GND, drill: 0.3, array: { origin: [x, y], pitch: [px, py], count: [nx, ny] },
      filled: true, filler: via_fill_epoxy, plating: 25 um }

components:
  - { ref: U1, rect: [...], side: top, power: 4 W, tj_max: 105, theta_jc: 0.5, theta_jb: 3 }

ports:
  - { name: VRM, kind: voltage_source, net: VDD, layer: L1, rect: [...], voltage: 1.0, reference_net: GND }
  - { name: LOAD, kind: current_sink, net: VDD, layer: L1, component: U1, current: 6 A,
      distribution: uniform,          # uniform (per-pin) | equipotential (pins shorted)
      reference_net: GND, reference_layer: L2 }   # reference_layer optional: nearest GND copper

thermal_boundaries:
  - { name: sink, kind: convection, component: U1, resistance: 6 }     # heat sink on U1, K/W
  - { name: fan, kind: convection, side: top, rect: [...], h: 40, ambient: 30 }
  - { name: standoff, kind: fixed_temperature, side: bottom, rect: [...], temperature: 45 }

transmission_lines:                     # solver "si"
  - { name: ddr_dq, layer: L1_TOP, width: 0.36, target: 50 }            # single: target = Z0
  - { name: usb_dp, layer: L1_TOP, width: 0.25, spacing: 0.18, target: 90,  # pair: target = Zdiff
      tolerance_pct: 10, references: [L2_GND] }   # references optional: nearest planes

criteria:
  ir_drop_pct: 3.0
  tj_max_default: 105            # °C, used when a component has no tj_max
  current_density: ipc2152       # ipc2152 | ipc2221 | none
  current_density_temp_rise: 10  # K
  current_density_ref_width: 1   # reference conductor width for the sheet limit (length)
  current_density_limit: null    # fixed override, A/mm² if bare number ("50 A/mm2")
  z0_tol_pct: 10

analysis:
  solvers: [dc_ir, thermal]
  mesh: { cell: 0.25, refine: 1 }
  output_dir: results            # relative to the config file
  options:                       # per-solver, validated by each solver
    dc_ir: { temperature: 25, method: direct }   # °C; method: direct | cg
    si: { mesh: normal, box_factor: 30 }   # mesh: coarse | normal | fine
    thermal:
      ambient: 25              # °C
      h_top: 10                # W/(m²K), default 10
      h_bottom: 10
      h_edge: 0
      radiation: true          # emissivity from the outer layer material unless set:
      emissivity_top: null
      joule: true              # add I²R heat from dc_ir (same mesh)
      mode: steady             # steady | transient
      transient: { t_end: 600, dt: 5, initial: ambient, power_steps: [[0, 1.0], [300, 0.2]] }
```

Material properties (SI): `sigma`, `alpha_r`, `t_ref` [K], `eps_r`, `tan_d`, `k_inplane`, `k_through` (or the shorthand `k`), `density`, `cp`, `emissivity`, `description`, `source`.

### `mechanical` (optional)

Links a `pcbsim match --json` result (see [registration.md](registration.md)):

```yaml
mechanical:
  match: match.json        # relative to this config
  offset: [0, 0]           # config origin − Gerber origin (length)
  apply_boundaries: true   # append heat sink / chassis / case boundaries
  require_ok: true         # an NG match stops `pcbsim run` (exit 5) unless --force
```

