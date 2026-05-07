"""setting_predictor のユニットテスト。"""
from __future__ import annotations

import numpy as np
import pytest

from juggler_predictor.model.setting_predictor import (
    compute_expected_setting,
    compute_p_high,
    compute_p_setting6,
    compute_p_top,
    p_high_to_stars,
    validate_proba,
)


def test_validate_proba_ok():
    proba = np.full((3, 6), 1 / 6)
    validate_proba(proba)  # no raise


def test_validate_proba_bad_shape():
    with pytest.raises(ValueError):
        validate_proba(np.zeros((3, 5)))
    with pytest.raises(ValueError):
        validate_proba(np.zeros(6))


def test_compute_p_high_uniform():
    proba = np.full((1, 6), 1 / 6)
    assert compute_p_high(proba)[0] == pytest.approx(0.5, rel=1e-6)


def test_compute_p_top_uniform():
    proba = np.full((1, 6), 1 / 6)
    assert compute_p_top(proba)[0] == pytest.approx(2 / 6, rel=1e-6)


def test_compute_p_setting6():
    proba = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 1.0]])
    assert compute_p_setting6(proba)[0] == pytest.approx(1.0)


def test_compute_expected_setting_uniform():
    proba = np.full((1, 6), 1 / 6)
    # E[setting] = (1+2+3+4+5+6)/6 = 3.5
    assert compute_expected_setting(proba)[0] == pytest.approx(3.5, rel=1e-6)


def test_compute_expected_setting_concentrated():
    # 設定6 確率 1.0 → E = 6.0
    proba = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 1.0]])
    assert compute_expected_setting(proba)[0] == pytest.approx(6.0)


def test_p_high_to_stars_thresholds():
    assert p_high_to_stars(0.80) == 5
    assert p_high_to_stars(0.70) == 5
    assert p_high_to_stars(0.60) == 4
    assert p_high_to_stars(0.55) == 4
    assert p_high_to_stars(0.45) == 3
    assert p_high_to_stars(0.40) == 3
    assert p_high_to_stars(0.30) == 2
    assert p_high_to_stars(0.25) == 2
    assert p_high_to_stars(0.10) == 1
    assert p_high_to_stars(0.00) == 1
