from __future__ import annotations

from pathlib import Path

import pytest

from pcbsim.errors import MaterialError
from pcbsim.materials import Material, MaterialDB

REQUIRED = {"copper", "copper_ed", "fr4", "soldermask", "air", "sac305", "via_fill_epoxy"}


def test_default_db_contents() -> None:
    db = MaterialDB.default()
    assert set(db) >= REQUIRED
    for m in db.values():
        assert m.source, f"{m.name} has no source citation"


def test_copper_values() -> None:
    cu = MaterialDB.default()["copper"]
    assert cu.sigma == pytest.approx(5.8e7)
    assert cu.alpha_r == pytest.approx(0.00393)
    assert cu.resistivity() == pytest.approx(1.7241e-8, rel=1e-3)


def test_resistivity_temperature_law() -> None:
    cu = MaterialDB.default()["copper"]
    rho0 = cu.resistivity()
    t = cu.t_ref + 80.0
    assert cu.resistivity(t) == pytest.approx(rho0 * (1 + 0.00393 * 80.0))
    assert cu.conductivity(t) == pytest.approx(1.0 / cu.resistivity(t))


def test_alpha_zero_is_temperature_independent() -> None:
    m = Material("x", sigma=1e7, alpha_r=0.0)
    assert m.resistivity(400.0) == m.resistivity(250.0) == pytest.approx(1e-7)


def test_fr4_anisotropic() -> None:
    fr4 = MaterialDB.default()["fr4"]
    assert fr4.k_inplane is not None
    assert fr4.k_through is not None
    assert fr4.k_inplane > fr4.k_through
    assert not fr4.is_conductor
    with pytest.raises(MaterialError):
        fr4.resistivity()
    assert fr4.diffusivity() == pytest.approx(0.81 / (1850 * 1100))


def test_merge_partial_override_keeps_other_fields() -> None:
    db = MaterialDB.default().merged({"fr4": {"eps_r": 4.0}})
    fr4 = db["fr4"]
    assert fr4.eps_r == 4.0
    assert fr4.tan_d == pytest.approx(0.02)
    assert MaterialDB.default()["fr4"].eps_r == pytest.approx(4.3)


def test_k_shorthand_and_new_material() -> None:
    db = MaterialDB.default().merged({"mycore": {"eps_r": 3.9, "k": 0.5}})
    m = db["mycore"]
    assert m.k_inplane == m.k_through == 0.5


def test_k_inplane_only_fills_through() -> None:
    db = MaterialDB().merged({"m": {"k_inplane": 2.0}})
    assert db["m"].k_through == 2.0


def test_load_user_file(tmp_path: Path) -> None:
    f = tmp_path / "mats.yaml"
    f.write_text("materials:\n  copper: {alpha_r: 0.004}\n  mylam: {eps_r: 3.5, k: 0.4}\n")
    db = MaterialDB.load(f)
    assert db["copper"].alpha_r == 0.004
    assert db["copper"].sigma == pytest.approx(5.8e7)
    assert "mylam" in db
    assert "mylam" in MaterialDB.load(f, include_default=False)
    assert "fr4" not in MaterialDB.load(f, include_default=False)


@pytest.mark.parametrize(
    ("props", "match"),
    [
        ({"sigma": -1.0}, "sigma"),
        ({"emissivity": 1.5}, "emissivity"),
        ({"eps_r": 0.5}, "eps_r"),
        ({"bogus": 1.0}, "unknown properties"),
        ({"sigma": float("nan")}, "finite"),
    ],
)
def test_invalid_material(props: dict[str, float], match: str) -> None:
    with pytest.raises(MaterialError, match=match):
        MaterialDB().merged({"bad": props})


def test_unknown_material_message() -> None:
    with pytest.raises(MaterialError, match="unknown material 'unobtainium'"):
        MaterialDB.default()["unobtainium"]


def test_bad_file_structure(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text("copper: {sigma: 1}\n")
    with pytest.raises(MaterialError, match="materials"):
        MaterialDB.load(f)


def test_linear_model_breakdown() -> None:
    m = Material("x", sigma=1.0, alpha_r=0.01, t_ref=300.0)
    with pytest.raises(MaterialError, match="invalid"):
        m.resistivity(100.0)


def test_require() -> None:
    air = MaterialDB.default()["air"]
    air.require("k_inplane", "cp")
    with pytest.raises(MaterialError, match="sigma"):
        air.require("sigma")
