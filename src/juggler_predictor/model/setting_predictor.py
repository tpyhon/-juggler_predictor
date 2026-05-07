"""設定期待度モデルの推論ヘルパー。"""
from __future__ import annotations

import numpy as np


def validate_proba(proba: np.ndarray) -> None:
    """proba shape チェック。(n, 6) であること。"""
    if proba.ndim != 2 or proba.shape[1] != 6:
        raise ValueError(f"proba must be shape (n, 6), got {proba.shape}")


def compute_p_high(proba: np.ndarray) -> np.ndarray:
    """設定4以上の確率 P[setting >= 4]。proba は 0-indexed (列0=設定1)。"""
    validate_proba(proba)
    return proba[:, 3:].sum(axis=1)


def compute_p_top(proba: np.ndarray) -> np.ndarray:
    """設定5以上の確率 P[setting >= 5]。"""
    validate_proba(proba)
    return proba[:, 4:].sum(axis=1)


def compute_p_setting6(proba: np.ndarray) -> np.ndarray:
    """設定6 の確率 P[setting == 6]。"""
    validate_proba(proba)
    return proba[:, 5]


def compute_expected_setting(proba: np.ndarray) -> np.ndarray:
    """期待設定値 = Σ k * P(setting=k), k=1..6。"""
    validate_proba(proba)
    weights = np.arange(1, 7, dtype=float)
    return proba @ weights


def p_high_to_stars(p_high_max: float) -> int:
    """店内最大 p_high から ★ 評価 (1〜5) を算出。"""
    if p_high_max >= 0.70:
        return 5
    if p_high_max >= 0.55:
        return 4
    if p_high_max >= 0.40:
        return 3
    if p_high_max >= 0.25:
        return 2
    return 1
