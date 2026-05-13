"""スコアリング関連: scoreA / base100 / 星評価 (Phase 1.5)。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_diff01(diff: pd.Series | np.ndarray, lo: float = -3000, hi: float = 5000) -> pd.Series:
    """差枚を 0.0〜1.0 にクリップ正規化。"""
    s = pd.Series(diff, dtype=float)
    s = s.clip(lower=lo, upper=hi)
    return (s - lo) / (hi - lo)


def compute_p4(setting: pd.Series | np.ndarray) -> pd.Series:
    """設定4以上ダミー。当日推定設定 >= 4 なら 1.0、それ未満なら 0.0。"""
    s = pd.Series(setting, dtype=float)
    return (s >= 4).astype(float)


def compute_score_a(
    p_high: pd.Series | np.ndarray,
    p_top: pd.Series | np.ndarray,
    diff01_prev: pd.Series | np.ndarray,
    w_high: float = 0.50,
    w_top: float = 0.30,
    w_prev: float = 0.20,
) -> pd.Series:
    """Phase 1.5 の scoreA = 0.50 * p_high + 0.30 * p_top + 0.20 * diff01_prev。"""
    ph = pd.Series(p_high, dtype=float)
    pt = pd.Series(p_top, dtype=float)
    dp = pd.Series(diff01_prev, dtype=float)
    return w_high * ph + w_top * pt + w_prev * dp


def compute_base100(
    p_win: pd.Series | np.ndarray,
    diff01: pd.Series | np.ndarray,
    p4: pd.Series | np.ndarray,
    w_pwin: float = 0.72,
    w_diff: float = 0.22,
    w_p4: float = 0.06,
) -> pd.Series:
    """既存指標 base100 = 100 * (0.72 p_win + 0.22 diff01 + 0.06 p4) (互換用)。"""
    pw = pd.Series(p_win, dtype=float)
    d = pd.Series(diff01, dtype=float)
    p = pd.Series(p4, dtype=float)
    return 100.0 * (w_pwin * pw + w_diff * d + w_p4 * p)


def base100_to_stars(base100_max: float) -> int:
    """[非推奨] base100 ベースの ★ 評価。互換のため残置。"""
    if base100_max >= 50:
        return 5
    if base100_max >= 42:
        return 4
    if base100_max >= 36:
        return 3
    if base100_max >= 30:
        return 2
    return 1
