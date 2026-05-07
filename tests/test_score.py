"""score.py のユニットテスト (Phase 1.5 仕様)。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from juggler_predictor.model.score import (
    base100_to_stars,
    compute_base100,
    compute_diff01,
    compute_p4,
    compute_score_a,
)


def test_compute_diff01_clip():
    s = pd.Series([-5000, -3000, 0, 5000, 10000])
    out = compute_diff01(s)
    assert out.iloc[0] == pytest.approx(0.0)
    assert out.iloc[1] == pytest.approx(0.0)
    assert out.iloc[3] == pytest.approx(1.0)
    assert out.iloc[4] == pytest.approx(1.0)
    # 0 は (0 - (-3000))/(5000 - (-3000)) = 0.375
    assert out.iloc[2] == pytest.approx(0.375, rel=1e-6)


def test_compute_p4():
    s = pd.Series([1, 2, 3, 4, 5, 6])
    out = compute_p4(s)
    assert list(out) == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]


def test_compute_score_a_weights():
    p_high = pd.Series([1.0, 0.0])
    p_top = pd.Series([0.0, 1.0])
    diff01 = pd.Series([0.0, 0.0])
    out = compute_score_a(p_high, p_top, diff01)
    # row0: 0.50*1 + 0.30*0 + 0.20*0 = 0.50
    # row1: 0.50*0 + 0.30*1 + 0.20*0 = 0.30
    assert out.iloc[0] == pytest.approx(0.50)
    assert out.iloc[1] == pytest.approx(0.30)


def test_compute_score_a_full():
    p_high = pd.Series([1.0])
    p_top = pd.Series([1.0])
    diff01 = pd.Series([1.0])
    out = compute_score_a(p_high, p_top, diff01)
    assert out.iloc[0] == pytest.approx(1.0)


def test_compute_base100_legacy():
    p_win = pd.Series([0.5])
    diff01 = pd.Series([0.5])
    p4 = pd.Series([1.0])
    out = compute_base100(p_win, diff01, p4)
    # 100 * (0.72*0.5 + 0.22*0.5 + 0.06*1) = 100 * (0.36 + 0.11 + 0.06) = 53.0
    assert out.iloc[0] == pytest.approx(53.0)


def test_stars_thresholds():
    # Phase 1 暫定閾値 (50/42/36/30) 互換
    assert base100_to_stars(70.0) == 5
    assert base100_to_stars(50.0) == 5
    assert base100_to_stars(45.0) == 4
    assert base100_to_stars(42.0) == 4
    assert base100_to_stars(38.0) == 3
    assert base100_to_stars(33.0) == 2
    assert base100_to_stars(25.0) == 1
