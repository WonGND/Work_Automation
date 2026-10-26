"""Checks + thermal BCs on synthetic, already-registered data (fault injection)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from shapely.geometry import Point, Polygon, box

from pcbsim.io.cad import Hole, PlacedComponent
from pcbsim.registration.checks import (
    Status,
    assign_refs,
    body_orientation,
    check_components,
    check_heights,
    check_holes,
    check_outline,
)
from pcbsim.registration.features import MechBody, corner_features
from pcbsim.registration.layermap import (
    CheckOptions,
    FinSpec,
    LayerMap,
    layer_map_from_dict,
)
from pcbsim.registration.solve import Feature
from pcbsim.registration.thermal_bc import (
    derive_boundaries,
    fin_efficiency,
    finned_resistance,
)

MM = 1e-3
# layer-map models take bare numbers as mm (converted to SI on validation)
OPTS = CheckOptions(case_height=10, min_clearance=0.5)
HOLES = [Hole(3.5 * MM, 3.5 * MM, 3.2 * MM, False), Hole(56.5 * MM, 36.5 * MM, 3.2 * MM, False)]


def _rot_box(cx: float, cy: float, w: float, h: float, deg: float) -> Polygon:
    from shapely import affinity

    b = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    p = affinity.rotate(b, deg, origin=(cx, cy))
    assert isinstance(p, Polygon)
    return p


def _ng(items: list, cat: str) -> list:  # type: ignore[type-arg]
    return [i for i in items if i.category == cat and i.status is Status.NG]


# --------------------------------------------------------------------------- holes


def test_holes_ok() -> None:
    mech = [Feature(h.x + 0.02 * MM, h.y, h.diameter + 0.05 * MM) for h in HOLES]
    items = check_holes(HOLES, mech, OPTS)
    assert all(i.status is Status.OK for i in items)
    assert len(items) == 4


def test_hole_position_deviation_detected() -> None:
    mech = [
        Feature(HOLES[0].x + 0.3 * MM, HOLES[0].y, HOLES[0].diameter),
        Feature(HOLES[1].x, HOLES[1].y, HOLES[1].diameter),
    ]
    items = check_holes(HOLES, mech, OPTS)
    (ng,) = _ng(items, "hole_position")
    assert ng.value == pytest.approx(0.3)
    assert ng.location == (HOLES[0].x, HOLES[0].y)


def test_hole_diameter_deviation_detected() -> None:
    mech = [Feature(h.x, h.y, 3.5 * MM) for h in HOLES]
    items = check_holes(HOLES, mech, OPTS)
    ng = _ng(items, "hole_diameter")
    assert len(ng) == 2
    assert ng[0].value == pytest.approx(0.3)


def test_hole_missing_and_extra_detected() -> None:
    mech = [Feature(HOLES[0].x, HOLES[0].y, HOLES[0].diameter), Feature(30 * MM, 20 * MM, 3.2 * MM)]
    items = check_holes(HOLES, mech, OPTS)
    assert len(_ng(items, "hole_missing")) == 1
    assert len(_ng(items, "hole_extra")) == 1


def test_small_drills_ignored() -> None:
    vias = [Hole(10 * MM, 10 * MM, 0.3 * MM, True)]
    assert check_holes(vias, [], OPTS) == []


# --------------------------------------------------------------------------- outline


def _board(cut: bool = True, notch: float = 0.0) -> Polygon:
    outer = [(0, 0), (60 * MM, 0), (60 * MM, 40 * MM + notch), (0, 40 * MM)]
    holes = [[(10 * MM, 10 * MM), (14 * MM, 10 * MM), (14 * MM, 16 * MM), (10 * MM, 16 * MM)]]
    return Polygon(outer, holes if cut else [])


def test_outline_match() -> None:
    items = check_outline(_board(), _board(), OPTS)
    assert all(i.status is Status.OK for i in items)
    assert {i.category for i in items} == {"outline", "cutout"}


def test_outline_deviation_hausdorff() -> None:
    items = check_outline(_board(), _board(notch=0.5 * MM), OPTS)
    (ng,) = _ng(items, "outline")
    assert ng.value == pytest.approx(0.5, rel=1e-6)


def test_cutout_missing_in_drawing() -> None:
    items = check_outline(_board(), _board(cut=False), OPTS)
    (ng,) = _ng(items, "cutout")
    assert "missing in the drawing" in ng.message


def test_cutout_extra_in_drawing() -> None:
    items = check_outline(_board(cut=False), _board(), OPTS)
    assert "missing on the board" in _ng(items, "cutout")[0].message


def test_outline_missing_is_warning() -> None:
    (item,) = check_outline(_board(), None, OPTS)
    assert item.status is Status.WARN


def test_corner_features_skip_arc_chords() -> None:
    p = box(0, 0, 0.06, 0.04).union(Polygon.from_bounds(0, 0, 0, 0).buffer(0))
    assert len(corner_features(box(0, 0, 0.06, 0.04))) == 4
    rounded = box(0.002, 0.002, 0.058, 0.038).buffer(0.002, quad_segs=16)
    assert len(corner_features(rounded)) == 0
    assert p.area > 0


# --------------------------------------------------------------------------- components


COMPS = [
    PlacedComponent("U1", 45 * MM, 20 * MM, 0.0, height=2.0 * MM),
    PlacedComponent("U2", 11 * MM, 20 * MM, 90.0),
    PlacedComponent("C1", 30 * MM, 5 * MM, 0.0, height=1.0 * MM),
]


def _body(ref: str | None, x: float, y: float, rot: float, z_top: float = 2 * MM) -> MechBody:
    return MechBody(
        f"COMP_{ref}" if ref else "COMP",
        "comp_3d",
        _rot_box(x, y, 8 * MM, 6 * MM, rot),
        0.0,
        z_top,
        ref,
    )


def test_components_ok() -> None:
    bodies = [_body("U1", 45 * MM, 20 * MM, 0.0), _body("U2", 11 * MM, 20 * MM, 90.0)]
    items = check_components(bodies, COMPS, OPTS)
    assert [i.status for i in items] == [Status.OK] * 4


def test_component_position_deviation_detected() -> None:
    bodies = [_body("U1", 46 * MM, 20 * MM, 0.0)]
    (ng,) = _ng(check_components(bodies, COMPS, OPTS), "component_position")
    assert ng.subject == "U1"
    assert ng.value == pytest.approx(1.0)


def test_component_rotation_deviation_detected() -> None:
    bodies = [_body("U1", 45 * MM, 20 * MM, 7.0)]
    (ng,) = _ng(check_components(bodies, COMPS, OPTS), "component_rotation")
    assert ng.value == pytest.approx(7.0, abs=1e-6)


def test_component_rotation_from_layer_name() -> None:
    bodies = [_body("U2", 11 * MM, 20 * MM, 90.0)]
    (ng,) = _ng(check_components(bodies, COMPS, OPTS, {"U2": 270.0}), "component_rotation")
    assert ng.value == pytest.approx(180.0)


def test_unknown_ref_is_ng() -> None:
    items = check_components([_body("U9", 30 * MM, 30 * MM, 0.0)], COMPS, OPTS)
    assert _ng(items, "component_unmatched")


def test_assign_refs_by_proximity() -> None:
    bodies = assign_refs([_body(None, 45.3 * MM, 20 * MM, 0.0)], COMPS, 3 * MM)
    assert bodies[0].ref == "U1"
    far = assign_refs([_body(None, 30 * MM, 30 * MM, 0.0)], COMPS, 3 * MM)
    assert far[0].ref is None


def test_body_orientation() -> None:
    assert body_orientation(_rot_box(0, 0, 4, 2, 33.0)) == pytest.approx(33.0, abs=1e-6)
    assert body_orientation(_rot_box(0, 0, 4, 4, 33.0)) is None
    assert body_orientation(Point(0, 0).buffer(1.0, quad_segs=16)) is None


def test_square_body_rotation_not_flagged() -> None:
    sq = MechBody("COMP_U1", "comp_3d", _rot_box(45 * MM, 20 * MM, 6 * MM, 6 * MM, 3.0), 0, 0, "U1")
    (rot,) = [i for i in check_components([sq], COMPS, OPTS) if i.category == "component_rotation"]
    assert rot.status is Status.OK
    assert rot.value is None


def test_bottom_side_items_use_bottom_ceilings() -> None:
    lid = MechBody("CASE", "case", box(0, 0, 60 * MM, 40 * MM), 3 * MM, 4 * MM, side="top")
    bot = PlacedComponent("C9", 30 * MM, 20 * MM, side="bottom", height=5 * MM)
    top_body = MechBody(
        "COMP_X", "comp_3d", box(29 * MM, 19 * MM, 31 * MM, 21 * MM), 0, 1 * MM, "X"
    )
    items = check_heights([lid, top_body], [bot], CheckOptions(min_clearance=0.5))
    assert not [i for i in items if "C9" in i.subject]


def test_assign_refs_respects_side() -> None:
    b = replace(_body(None, 45 * MM, 20 * MM, 0.0), side="bottom")
    assert assign_refs([b], COMPS, 3 * MM)[0].ref is None


# --------------------------------------------------------------------------- heights


def test_height_ok_under_case() -> None:
    items = check_heights([_body("U1", 45 * MM, 20 * MM, 0.0, 5 * MM)], COMPS, OPTS)
    u1 = next(i for i in items if i.subject == "U1")
    assert u1.status is Status.OK
    assert u1.value == pytest.approx(5.0)


def test_height_exceeds_case_detected() -> None:
    items = check_heights([_body("U1", 45 * MM, 20 * MM, 0.0, 9.8 * MM)], COMPS, OPTS)
    (ng,) = _ng(items, "height")
    assert ng.value == pytest.approx(0.2)


def test_height_keepout_region() -> None:
    keep = MechBody(
        "KEEPOUT_H3", "keepout", box(40 * MM, 15 * MM, 50 * MM, 25 * MM), 0, 0, None, 3.0 * MM
    )
    body = _body("U1", 45 * MM, 20 * MM, 0.0, 4 * MM)
    (ng,) = _ng(check_heights([keep, body], COMPS, OPTS), "height")
    assert "ceiling 3.00 mm" in ng.message
    # the same keepout elsewhere does not limit U1
    keep2 = MechBody("K", "keepout", box(0, 0, 5 * MM, 5 * MM), 0, 0, None, 1.0 * MM)
    assert not _ng(check_heights([keep2, body], COMPS, OPTS), "height")


def test_height_case_underside() -> None:
    lid = MechBody("CASE_RIB", "case", box(40 * MM, 0, 50 * MM, 40 * MM), 4.2 * MM, 5 * MM)
    body = _body("U1", 45 * MM, 20 * MM, 0.0, 4 * MM)
    (ng,) = _ng(check_heights([lid, body], COMPS, OPTS), "height")
    assert ng.value == pytest.approx(0.2)


def test_ecad_height_used_when_no_body() -> None:
    opts = CheckOptions(case_height=1.2, min_clearance=0.5)
    items = check_heights([], COMPS, opts)
    ng = _ng(items, "height")
    assert {i.subject for i in ng} == {"U1 (ECAD height)", "C1 (ECAD height)"}


# --------------------------------------------------------------------------- thermal BCs


def test_fin_efficiency_limits() -> None:
    assert fin_efficiency(1e-6, 200, 1e-3, 10e-3) == pytest.approx(1.0, abs=1e-6)
    # Incropera Ex. 3.9-style check: m L_c = 1 → tanh(1)/1
    k, t = 200.0, 1e-3
    h = k * t / 2  # m = 1/m → choose H so that L_c = 1 m
    assert fin_efficiency(h, k, t, 1.0 - t / 2) == pytest.approx(math.tanh(1.0))


def test_finned_resistance_matches_hand_calc() -> None:
    fins = FinSpec(count=8, height=10, thickness=1, length=20)
    base = 20 * MM * 20 * MM
    h, k = 10.0, 200.0
    lc = 10.5 * MM
    af = 2 * lc * 20 * MM
    ab = base - 8 * 1 * MM * 20 * MM
    at = 8 * af + ab
    m = math.sqrt(2 * h / (k * 1 * MM))
    eta = math.tanh(m * lc) / (m * lc)
    eta_o = 1 - 8 * af / at * (1 - eta)
    assert finned_resistance(base, fins, 20 * MM, h, k) == pytest.approx(1 / (eta_o * h * at))


def _lmap(**extra: object) -> LayerMap:
    return layer_map_from_dict(
        {
            "heatsinks": [
                {"layers": "HS_U1", "resistance": 6.0},
                {"layers": "HS_.*", "fins": {"count": 6, "height": 8, "thickness": 1}, "h": 12},
            ],
            "chassis": {"temperature": 45},
            "case": {"temperature": 40},
            **extra,
        }
    )


def test_derive_boundaries() -> None:
    outline = box(0, 0, 60 * MM, 40 * MM)
    fp = {"U1": box(41 * MM, 16 * MM, 49 * MM, 24 * MM)}
    bodies = [
        MechBody("HS_U1", "heatsink", box(40 * MM, 15 * MM, 50 * MM, 25 * MM), 2 * MM, 12 * MM),
        MechBody("HS_VRM", "heatsink", box(20 * MM, 25 * MM, 30 * MM, 35 * MM), 0, 8 * MM),
        MechBody("CHASSIS_A", "chassis", box(0, 0, 5 * MM, 5 * MM), 0, 0),
        MechBody("CASE_LID", "case", box(0, 0, 60 * MM, 40 * MM), 8 * MM, 9 * MM),
    ]
    bcs, notes = derive_boundaries(bodies, COMPS, _lmap(), outline, fp)
    by = {b.name: b for b in bcs}
    assert by["hs_U1"].component == "U1"
    assert by["hs_U1"].resistance == pytest.approx(6.0)
    vrm = by["hs_HS_VRM"]
    assert vrm.component is None
    assert vrm.h is not None
    assert vrm.h > 5 * 12.0  # fins: effective h on the base area ≫ flat-plate h
    ch = by["chassis_CHASSIS_A"]
    assert ch.kind == "fixed_temperature"
    assert ch.temperature == pytest.approx(318.15)
    case = by["case_CASE_LID"]
    assert case.h == pytest.approx(0.0263 / (8 * MM))
    assert notes == []


def test_chassis_contact_resistance_becomes_robin() -> None:
    lm = layer_map_from_dict({"chassis": {"temperature": 45, "contact_resistance": 2.0}})
    body = MechBody("CHASSIS_A", "chassis", box(0, 0, 5 * MM, 5 * MM), 0, 0)
    (bc,), _ = derive_boundaries([body], [], lm, box(0, 0, 0.06, 0.04))
    assert bc.kind == "convection"
    assert bc.h == pytest.approx(1 / (2.0 * 25 * MM * MM))
    assert bc.ambient == pytest.approx(318.15)


def test_layer_map_regex_validation() -> None:
    from pcbsim.errors import ConfigError

    with pytest.raises(ConfigError, match="regular expression"):
        layer_map_from_dict({"mech": {"outline": "OUT("}})
    lm = layer_map_from_dict({"checks": {"hole_position_tol": "4 mil"}})
    assert lm.checks.hole_position_tol == pytest.approx(4 * 25.4e-6)
