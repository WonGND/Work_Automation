"""Registration math: synthetic data with random rotation/translation/mirror/unit errors."""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import Polygon

from pcbsim.registration import (
    Anchor,
    Feature,
    RegistrationError,
    RegistrationOptions,
    Similarity2D,
    register,
    umeyama,
)
from pcbsim.registration.solve import icp_refine, outline_rms

MM = 1e-3
# 60 × 40 mm board, 4 M3 mounting holes + one asymmetric ⌀2 tooling hole, an
# L-shaped notch so the outline itself is asymmetric too.
BOARD_HOLES = [
    (3.5, 3.5, 3.2),
    (56.5, 3.5, 3.2),
    (56.5, 36.5, 3.2),
    (3.5, 36.5, 3.2),
    (21.0, 27.0, 2.0),
]
OUTLINE = Polygon(
    [
        (0, 0),
        (60 * MM, 0),
        (60 * MM, 30 * MM),
        (50 * MM, 30 * MM),
        (50 * MM, 40 * MM),
        (0, 40 * MM),
    ],
    [[(10 * MM, 10 * MM), (14 * MM, 10 * MM), (14 * MM, 16 * MM), (10 * MM, 16 * MM)]],
)
TOL_RECOVERY = 1e-9  # m  (= 1e-6 mm)


def _dst() -> list[Feature]:
    return [Feature(x * MM, y * MM, d * MM) for x, y, d in BOARD_HOLES]


def _drawing_of(t: Similarity2D) -> tuple[list[Feature], Polygon]:
    """Features/outline as they would appear in a drawing that ``t`` maps onto the board."""
    inv = t.inverse()
    pts = inv.apply([(x * MM, y * MM) for x, y, _ in BOARD_HOLES])
    src = [
        Feature(float(p[0]), float(p[1]), d * MM / t.scale)
        for p, (_, _, d) in zip(pts, BOARD_HOLES, strict=True)
    ]
    outline = inv.apply_geometry(OUTLINE)
    assert isinstance(outline, Polygon)
    return src, outline


def test_similarity_inverse_roundtrip() -> None:
    t = Similarity2D(0.7, 0.01, -0.02, 25.4, True)
    p = np.array([[0.001, 0.002], [0.03, -0.01]])
    assert np.allclose(t.inverse().apply(t.apply(p)), p, atol=1e-15)
    assert t.inverse().inverse().distance_to(t, 0.1) < 1e-14


def test_similarity_dict_roundtrip() -> None:
    t = Similarity2D(-1.2, 0.5, 0.25, 1.0, True)
    assert Similarity2D.from_dict(t.to_dict()).distance_to(t, 0.1) < 1e-12


def test_apply_angle_mirror() -> None:
    t = Similarity2D(math.radians(90), 0, 0, 1, True)
    assert t.apply_angle(30.0) == pytest.approx(240.0)  # (180 − 30) + 90
    d = np.array([math.cos(math.radians(30.0)), math.sin(math.radians(30.0))])
    v = t.apply([d])[0] - t.apply([(0.0, 0.0)])[0]
    assert math.degrees(math.atan2(v[1], v[0])) % 360.0 == pytest.approx(240.0)


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("with_scale", [False, True])
def test_umeyama_exact(mirror: bool, with_scale: bool) -> None:
    rng = np.random.default_rng(3)
    src = rng.uniform(-0.05, 0.05, (8, 2))
    t = Similarity2D(1.1, 0.02, -0.03, 2.5 if with_scale else 1.0, mirror)
    got = umeyama(src, t.apply(src), mirror=mirror, with_scale=with_scale)
    assert got.distance_to(t, 0.05) < 1e-12


def test_umeyama_never_reflects_on_its_own() -> None:
    src = np.array([[0, 0], [1, 0], [0, 2.0]])
    dst = src * np.array([-1.0, 1.0])
    t = umeyama(src, dst)  # mirror not allowed: best proper rotation, residual > 0
    assert not t.mirror
    assert np.abs(t.apply(src) - dst).max() > 0.1


@pytest.mark.parametrize("seed", range(12))
def test_recovers_random_transform_exactly(seed: int) -> None:
    """Random rotation, translation, mirror and (every 3rd case) an inch/mm unit error."""
    rng = np.random.default_rng(seed)
    t = Similarity2D(
        float(rng.uniform(-math.pi, math.pi)),
        float(rng.uniform(-0.5, 0.5)),
        float(rng.uniform(-0.5, 0.5)),
        25.4 if seed % 3 == 0 else 1.0,
        bool(seed % 2),
    )
    src, src_outline = _drawing_of(t)
    res = register(
        src,
        _dst(),
        RegistrationOptions(allow_scale=True),
        src_outline=src_outline,
        dst_outline=OUTLINE,
    )
    assert res.ok
    assert res.transform.mirror == t.mirror
    assert res.transform.scale == pytest.approx(t.scale, rel=1e-12)
    assert res.transform.distance_to(t, 0.06) < TOL_RECOVERY
    assert len(res.matches) == len(BOARD_HOLES)
    assert res.rms < TOL_RECOVERY
    assert res.outline_rms is not None
    assert res.outline_rms < TOL_RECOVERY
    if t.scale != 1.0:
        assert res.unit_warning is not None
        assert "inch" in res.unit_warning


def test_scale_not_searched_unless_enabled() -> None:
    src, _ = _drawing_of(Similarity2D(0.3, 0.01, 0.0, 25.4, False))
    with pytest.raises(RegistrationError, match="units"):
        register(src, _dst())


def test_symmetric_pattern_is_ambiguous_and_anchor_resolves_it() -> None:
    corners = _dst()[:4]
    t = Similarity2D(0.4, 0.1, 0.2, 1.0, False)
    inv = t.inverse()
    pts = inv.apply([(f.x, f.y) for f in corners])
    src = [Feature(float(p[0]), float(p[1]), f.diameter) for p, f in zip(pts, corners, strict=True)]
    res = register(src, corners)
    assert res.ambiguous
    assert not res.ok
    assert len(res.alternatives) >= 2
    assert "asymmetric" in res.warnings[0]

    a = Anchor((src[0].x, src[0].y), (corners[0].x, corners[0].y))
    res2 = register(src, corners, RegistrationOptions(anchors=(a,)))
    assert not res2.ambiguous
    assert res2.transform.distance_to(t, 0.06) < TOL_RECOVERY


def test_mirror_forced_off_rejects_bottom_view() -> None:
    t = Similarity2D(0.2, 0.0, 0.0, 1.0, True)
    src, _ = _drawing_of(t)
    res = register(src, _dst(), RegistrationOptions(mirror="false"))
    # without the mirror at most a subset can line up
    assert len(res.matches) < len(BOARD_HOLES)


def test_outliers_and_missing_features_tolerated() -> None:
    t = Similarity2D(2.0, 0.05, 0.07, 1.0, False)
    src, _ = _drawing_of(t)
    src = [*src[1:], Feature(0.3, 0.3, 3.2e-3), Feature(-0.2, 0.1, 3.2e-3)]  # 1 missing, 2 junk
    res = register(src, _dst())
    assert len(res.matches) == 4
    assert res.transform.distance_to(t, 0.06) < TOL_RECOVERY


def test_noise_rms_reported() -> None:
    t = Similarity2D(-0.8, 0.0, 0.01, 1.0, True)
    src, _ = _drawing_of(t)
    rng = np.random.default_rng(0)
    noisy = [
        Feature(f.x + rng.normal(0, 20e-6), f.y + rng.normal(0, 20e-6), f.diameter) for f in src
    ]
    res = register(noisy, _dst())
    assert 1e-6 < res.rms < 60e-6
    assert res.transform.distance_to(t, 0.03) < 100e-6


def test_icp_refines_small_offset() -> None:
    t = Similarity2D(0.0, 0.0, 0.0, 1.0, False)
    src_outline = OUTLINE
    start = Similarity2D(math.radians(0.3), 0.2e-3, -0.1e-3, 1.0, False)
    opts = RegistrationOptions()
    empty = np.zeros((0, 2))
    before = outline_rms(start, src_outline, OUTLINE, 400)
    got = icp_refine(start, empty, empty, src_outline, OUTLINE, opts)
    after = outline_rms(got, src_outline, OUTLINE, 400)
    assert after < before / 100
    assert got.distance_to(t, 0.06) < 1e-6


def test_too_few_features() -> None:
    with pytest.raises(RegistrationError, match="at least 2"):
        register([Feature(0, 0, 1e-3)], _dst())


def test_icp_rejected_when_drawing_outline_is_wrong() -> None:
    """A wrong drawing outline must not pull an exact hole fit (the check reports it)."""
    t = Similarity2D(0.6, 0.02, -0.01, 1.0, False)
    src, src_outline = _drawing_of(t)
    from shapely import affinity

    bad = affinity.translate(src_outline, 0.4e-3, 0.0)
    assert isinstance(bad, Polygon)
    res = register(src, _dst(), src_outline=bad, dst_outline=OUTLINE)
    assert res.transform.distance_to(t, 0.06) < TOL_RECOVERY
    assert res.outline_rms is not None
    assert res.outline_rms > 1e-4
