"""数値ユーティリティ."""
from __future__ import annotations

from typing import Iterable, Sequence

# 全角数字 -> 半角数字の変換テーブル
_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def safe_float(x: object, default: float = 0.0) -> float:
    """カンマ・全角・空文字・None 対応の float 変換."""
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace(" ", "").replace("　", "")
    s = s.translate(_FW_DIGITS)
    if s in ("", "-", "--", "N/A", "n/a", "null", "None"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def safe_int(x: object, default: int = 0) -> int:
    """float 経由で int に."""
    f = safe_float(x, default=float(default))
    try:
        return int(f)
    except (ValueError, OverflowError):
        return default


def clip(v: float, lo: float, hi: float) -> float:
    """値を [lo, hi] に丸める."""
    if lo > hi:
        raise ValueError(f"lo > hi: {lo} > {hi}")
    return max(lo, min(hi, v))


def minmax_normalize(values: Sequence[float]) -> list[float]:
    """min-max 正規化. 全部同じ値なら 0.5 で埋める."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def mean(values: Iterable[float]) -> float:
    vs = list(values)
    return sum(vs) / len(vs) if vs else 0.0
