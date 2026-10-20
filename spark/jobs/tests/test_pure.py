"""Pure unit tests for the shared modules (no Spark needed)."""

import pytest

from catalog import TIER_BOUNDS, match_generation
from curves import curve_points, predicted_fps, required_score, resolution_factor


def test_resolution_factors():
    assert resolution_factor('1080p') == pytest.approx(1.0)
    assert resolution_factor('1440p') == pytest.approx(1.5396, abs=1e-3)
    assert resolution_factor('4k') == pytest.approx(2.8284, abs=1e-3)
    assert resolution_factor('1080p') < resolution_factor('1440p') < resolution_factor('4k')

CYBERPUNK = (-5.699266, 1.014642)
PRIOR = (-2.438777, 0.775582)


def test_curve_roundtrip():
    a, b = CYBERPUNK
    assert predicted_fps(required_score(60, a, b), a, b) == pytest.approx(60.0)


def test_cyberpunk_60_fps():
    assert required_score(60, *CYBERPUNK) == pytest.approx(15557.2, abs=1.0)


def test_prior_60_fps():
    assert required_score(60, *PRIOR) == pytest.approx(4552.8, abs=1.0)


def test_curve_points_shape():
    points = curve_points(*CYBERPUNK)
    assert len(points) == 67
    assert points[0] == {'fps': 30.0, 'required': pytest.approx(points[0]['required'])}
    assert points[-1]['fps'] == 360.0
    assert all(p['required'] > 0 for p in points)


@pytest.mark.parametrize(
    'name,family',
    [
        ('GeForce GTX 1080', 'GTX 10 (Pascal)'),
        ('Radeon RX 6800S', 'RX 6000 (RDNA 2)'),
        ('Radeon RX 7600S', 'RX 7000 (RDNA 3)'),
        ('GeForce RTX 3060', 'RTX 30 (Ampere)'),
        ('Radeon RX 9070 XT', 'RX 9000 (RDNA 4)'),
        ('Intel Arc A770M', 'Intel Arc'),
        ('RTX PRO 5000 72GB Blackwell', 'RTX Pro'),
        ('RTX 2000E Ada Generation', 'RTX Ada workstation'),
    ],
)
def test_generation_match(name, family):
    found, year = match_generation(name)
    assert found == family
    assert isinstance(year, int)


def test_unknown_name():
    assert match_generation('Some Unknown Display Adapter 9000') == (None, None)


def test_tier_bounds():
    assert TIER_BOUNDS == (2610, 6866, 17008, 26918)
