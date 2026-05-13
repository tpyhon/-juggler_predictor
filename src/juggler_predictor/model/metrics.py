"""評価メトリクス補助関数。"""
from __future__ import annotations

import numpy as np


def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int = 5) -> float:
    """スコア上位 K 件の的中率。

    勝ち台ランキングの実用評価指標。
    K件未満なら NaN を返す。
    """
    y_true = np.asarray(y_true)
    scores = np.asarray(scores)
    if len(scores) < k or k <= 0:
        return float("nan")
    top_k_idx = np.argsort(scores)[::-1][:k]
    return float(np.mean(y_true[top_k_idx]))


def expected_topk_diff(y_diff: np.ndarray, scores: np.ndarray, k: int = 5) -> float:
    """スコア上位 K 件の実際の平均 diff。期待ROIの近似。"""
    y_diff = np.asarray(y_diff)
    scores = np.asarray(scores)
    if len(scores) < k or k <= 0:
        return float("nan")
    top_k_idx = np.argsort(scores)[::-1][:k]
    return float(np.mean(y_diff[top_k_idx]))
