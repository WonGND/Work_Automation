"""Stack-up → transmission-line cross-section (geometry + analytic cross-check).

Geometry
    y = 0 is the face of the *ground-side reference* plane that looks at the
    signal layer: the nearest conductor layer below the signal (or the one named
    in ``references``); for a bottom-side microstrip the stack is flipped so its
    reference is still at y = 0. A stripline also has a top plane at the face of
    the reference on the other side. Dielectric layers between the references
    become horizontal bands with their material's ε_r.

    The trace is a ``w × t`` rectangle (pair: two of them, ``s`` apart edge to
    edge) on the far face of its own layer, i.e. sitting on the dielectric
    towards the ground-side reference. The rest of the signal layer's band is
    filled with the neighbouring dielectric on the far side (prepreg flows
    around inner traces; solder mask or air on an outer layer). A solder mask
    layer over an outer trace is conformal: its band starts at the layer
    surface, plus a ``t_sm`` coating on top of the trace. Any other conductor
    layer between the signal and its reference (a skipped layer) gets the ε_r
    of the dielectric next to it.

Analytic reference chosen per topology (see :mod:`pcbsim.si.analytic`)
    ========================  ===================================  ============
    topology                  formula                              accuracy
    ========================  ===================================  ============
    microstrip, single        Hammerstad–Jensen (+ thickness)      ~1 %
    stripline, centred        Wheeler thick stripline              ~1 %
    stripline, t = 0          Cohn (exact)                         exact
    stripline, offset         IPC-2141A dual stripline             ~5–10 %
    differential microstrip   IPC-2141A                            ~5–10 %
    differential stripline    Cohn coupled (t = 0) / IPC-2141A     exact / 5–10 %
    ========================  ===================================  ============

    Several dielectric bands under a microstrip are reduced to one ε_r by the
    series-capacitor (thickness-weighted harmonic) mean; solder mask is not in
    any closed form, so the analytic value then carries a note and a larger
    expected deviation.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcbsim.errors import SolverError
from pcbsim.materials import MaterialDB
from pcbsim.model import Stackup
from pcbsim.model.stackup import Layer, LayerKind
from pcbsim.si import analytic
from pcbsim.si.analytic import LineZ
from pcbsim.si.fem2d import CrossSection, DielectricRegion, Rect


@dataclass(frozen=True, slots=True)
class LineGeometry:
    """Resolved line: cross-section for FEM plus the scalars the formulas need (SI)."""

    xs: CrossSection
    topology: str  # microstrip | stripline
    differential: bool
    w: float
    t: float
    s: float | None
    h: float  # trace bottom above the ground-side reference
    b: float | None  # plane spacing (stripline)
    er: float  # effective single ε_r used by the formulas
    references: tuple[str, ...]
    soldermask: bool
    uniform_dielectric: bool

    @property
    def offset(self) -> float:
        """Trace-centre offset from mid-plane, as a fraction of b (stripline)."""
        if self.b is None:
            return 0.0
        return abs((self.h + self.t / 2.0) - self.b / 2.0) / self.b


def _eps(db: MaterialDB, layer: Layer) -> float:
    er = db[layer.material].eps_r
    if er is None:
        raise SolverError(f"layer {layer.name}: material {layer.material!r} has no eps_r")
    return er


def _pick_references(
    layers: list[Layer], i_sig: int, references: tuple[str, ...] | None
) -> tuple[int | None, int | None]:
    names = [lay.name for lay in layers]
    cond = [k for k, lay in enumerate(layers) if lay.kind is LayerKind.CONDUCTOR]
    if not references:
        above = max((k for k in cond if k < i_sig), default=None)
        below = min((k for k in cond if k > i_sig), default=None)
    else:
        idx: list[int] = []
        for r in references:
            if r not in names or layers[names.index(r)].kind is not LayerKind.CONDUCTOR:
                raise SolverError(f"reference {r!r} is not a conductor layer")
            if names.index(r) == i_sig:
                raise SolverError("a line cannot reference its own layer")
            idx.append(names.index(r))
        ab = [k for k in idx if k < i_sig]
        be = [k for k in idx if k > i_sig]
        if len(ab) > 1 or len(be) > 1:
            raise SolverError("give at most one reference above and one below the line")
        above = ab[0] if ab else None
        below = be[0] if be else None
    if above is None and below is None:
        raise SolverError(f"layer {names[i_sig]!r}: no reference plane in the stack-up")
    return above, below


def resolve(
    stackup: Stackup,
    db: MaterialDB,
    layer: str,
    width: float,
    spacing: float | None = None,
    references: tuple[str, ...] | None = None,
) -> LineGeometry:
    """Cross-section of a trace (or edge-coupled pair) on ``layer``; see module docstring."""
    layers = list(stackup.layers)
    names = [lay.name for lay in layers]
    if layer not in names:
        raise SolverError(f"unknown layer {layer!r}")
    i_sig = names.index(layer)
    if layers[i_sig].kind is not LayerKind.CONDUCTOR:
        raise SolverError(f"layer {layer!r} is not a conductor layer")
    if not width > 0:
        raise SolverError("trace width must be > 0")
    if spacing is not None and not spacing > 0:
        raise SolverError("pair spacing must be > 0")
    above, below = _pick_references(layers, i_sig, references)

    # Order layers from the ground-side reference outward (y up). The ground side is
    # the reference below the trace, or — for a bottom-layer microstrip — the one
    # above it, with the stack flipped.
    if below is not None:
        ground, far = below, above
        seq = list(range(below - 1, (above if above is not None else -1), -1))
    else:
        assert above is not None
        ground, far = above, None
        seq = list(range(above + 1, len(layers)))

    y = 0.0
    spans: dict[int, tuple[float, float]] = {}
    for k in seq:
        spans[k] = (y, y + layers[k].thickness)
        y += layers[k].thickness
    top_plane = y if far is not None else None

    def diel_next_to(k: int, step: int) -> float:
        j = k + step
        while 0 <= j < len(seq):
            lay = layers[seq[j]]
            if lay.kind is not LayerKind.CONDUCTOR:
                return _eps(db, lay)
            j += step
        return 1.0

    bands: list[tuple[float, float, float]] = []
    soldermask: Layer | None = None
    for pos, k in enumerate(seq):
        lay = layers[k]
        lo, hi = spans[k]
        if lay.kind is LayerKind.CONDUCTOR:
            # Copper layers (the signal layer and any skipped layer) are filled with
            # the dielectric on their far side (prepreg flows into inner layers;
            # solder mask or air on an outer layer).
            bands.append((lo, hi, diel_next_to(pos, +1)))
            continue
        if lay.kind is LayerKind.SOLDERMASK and far is None:
            soldermask = lay
        bands.append((lo, hi, _eps(db, lay)))

    sig_lo, sig_hi = spans[i_sig]
    t = sig_hi - sig_lo
    if soldermask is not None:
        # The mask is conformal: on bare dielectric it starts at the copper surface
        # (the band above it is air), and it coats the trace sides and top.
        tm = soldermask.thickness
        bands = [bd for bd in bands if bd[0] < sig_lo] + [
            (sig_lo, sig_lo + tm, _eps(db, soldermask))
        ]

    w = width
    s = spacing
    if s is None:
        conductors = [Rect(-w / 2, w / 2, sig_lo, sig_hi)]
    else:
        conductors = [
            Rect(-s / 2 - w, -s / 2, sig_lo, sig_hi),
            Rect(s / 2, s / 2 + w, sig_lo, sig_hi),
        ]
    regions: list[DielectricRegion] = []
    if soldermask is not None:
        er_sm = _eps(db, soldermask)
        tm = soldermask.thickness
        for c in conductors:
            regions.append(DielectricRegion(Rect(c.x0 - tm, c.x1 + tm, sig_lo, c.y1 + tm), er_sm))

    under = [(hi - lo, e) for lo, hi, e in bands if hi <= sig_lo + 1e-15]
    if top_plane is not None:
        under = [(hi - lo, e) for lo, hi, e in bands]
    total = sum(d for d, _ in under)
    er_eff = total / sum(d / e for d, e in under) if total > 0 else 1.0
    er_values = {round(e, 9) for d, e in under}

    xs = CrossSection(conductors, bands, top_plane, regions)
    refs = tuple(names[k] for k in (ground, far) if k is not None)
    return LineGeometry(
        xs=xs,
        topology="stripline" if top_plane is not None else "microstrip",
        differential=s is not None,
        w=w,
        t=t,
        s=s,
        h=sig_lo,
        b=top_plane,
        er=er_eff,
        references=refs,
        soldermask=soldermask is not None,
        uniform_dielectric=len(er_values) <= 1,
    )


#: Expected accuracy of each closed form (fraction) — sets the cross-check warning level.
ACCURACY = {
    "hammerstad-jensen": 0.01,
    "wheeler": 0.01,
    "cohn-exact": 0.005,
    "ipc-2141": 0.08,
    "ipc-2141-dual": 0.10,
}


def analytic_for(g: LineGeometry) -> tuple[LineZ, float]:
    """Best closed form for ``g`` and its expected accuracy (fraction)."""
    notes: list[str] = []
    centred = g.offset < 0.01
    if g.topology == "microstrip":
        if g.differential:
            assert g.s is not None
            z = analytic.diff_microstrip_ipc(g.w, g.s, g.h, g.er, g.t)
        else:
            z = analytic.microstrip_hj(g.w, g.h, g.er, g.t)
        acc = ACCURACY[z.method]
        if g.soldermask:
            notes.append("closed form ignores solder mask (it lowers Z0 by a few %)")
            acc = max(acc, 0.06)
    else:
        assert g.b is not None
        if g.differential:
            assert g.s is not None
            if g.t == 0 and centred:
                z = analytic.coupled_stripline_cohn(g.w, g.s, g.b, g.er)
            else:
                z = analytic.diff_stripline_ipc(g.w, g.s, g.b, g.er, g.t)
        elif g.t == 0 and centred:
            z = analytic.stripline_cohn(g.w, g.b, g.er)
        elif centred:
            z = analytic.stripline_wheeler(g.w, g.b, g.t, g.er)
        else:
            h1 = g.h
            h2 = g.b - g.h - g.t
            z = analytic.stripline_dual_ipc(g.w, g.t, min(h1, h2), max(h1, h2), g.er)
        acc = ACCURACY[z.method]
        if g.differential and not centred:
            notes.append("offset pair: the IPC formula assumes a centred pair")
            acc = max(acc, 0.10)
    if not g.uniform_dielectric:
        notes.append("layered dielectric reduced to one εr (series mean)")
        acc = max(acc, 0.03)
    if not z.valid:
        acc = max(acc, 0.15)
    if notes:
        note = "; ".join(n for n in (z.note, *notes) if n)
        z = LineZ(z.z0, z.eps_eff, z.z_odd, z.z_even, z.z_diff, z.method, z.valid, note)
    return z, acc
