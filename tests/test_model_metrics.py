"""precision_at_k, expected_topk_diff のテスト。"""
from __future__ import annotations

import numpy as np

from juggler_predictor.model import expected_topk_diff, precision_at_k


def test_precision_at_k_perfect():
    """スコア上位 K が全部 1 なら precision=1.0。"""
    y_true = np.array([1, 1, 0, 0, 0])
    scores = np.array([0.9, 0.8, 0.1, 0.2, 0.3])
    assert precision_at_k(y_true, scores, k=2) == 1.0


def test_precision_at_k_zero():
    """スコア上位 K が全部 0 なら precision=0.0。"""
    y_true = np.array([0, 0, 1, 1, 1])
    scores = np.array([0.9, 0.8, 0.1, 0.2, 0.3])
    assert precision_at_k(y_true, scores, k=2) == 0.0


def test_precision_at_k_returns_nan_when_too_few():
    """K より要素が少ない場合は NaN。"""
    y_true = np.array([1])
    scores = np.array([0.9])
    assert np.isnan(precision_at_k(y_true, scores, k=5))


def test_expected_topk_diff_picks_top():
    """スコア最高の diff を取れること。"""
    y_diff = np.array([1000.0, 500.0, -200.0])
    scores = np.array([0.9, 0.5, 0.1])
    # k=1 ならスコア最大の y_diff = 1000
    assert expected_topk_diff(y_diff, scores, k=1) == 1000.0
