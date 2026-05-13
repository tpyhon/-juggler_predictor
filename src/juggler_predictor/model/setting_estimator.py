"""合成確率 → 設定 1〜6 のヒューリスティック推定。

既存 SlotPrediction prod/JugAnalyzer_universal._estimate_setting と互換。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# fallback の差枚閾値
_FALLBACK_THRESHOLDS = [
    (1500, 6),
    (500, 5),
    (0, 4),
    (-500, 3),
    (-1000, 2),
]


@lru_cache(maxsize=1)
def load_juggler_specs(path: str | None = None) -> dict[str, dict[str, list[float]]]:
    """機種スペック表を YAML から読み込む。"""
    if path is None:
        # repo root / config / juggler_specs.yaml を自動解決
        root = Path(__file__).resolve().parents[3]
        path = str(root / "config" / "juggler_specs.yaml")
    p = Path(path)
    if not p.exists():
        logger.warning("juggler_specs.yaml not found at %s", p)
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def parse_composite_prob(value: Any) -> float:
    """"1/156.3" 形式の文字列 / 数値を float に変換。失敗時は 0.0。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "nan", "NaN"):
        return 0.0
    if "/" in s:
        try:
            num, den = s.split("/", 1)
            num_f = float(num.strip())
            den_f = float(den.strip())
            if den_f <= 0:
                return 0.0
            return num_f / den_f
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def estimate_setting(
    composite_prob: float | str | None,
    diff: float,
    machine_name: str,
    *,
    specs: dict[str, dict[str, list[float]]] | None = None,
) -> int:
    """合成確率と機種名から設定 1〜6 を推定。

    1. 機種スペックがあり composite_prob > 0 なら、合成確率を 6 段階の公称値と
       比較して最近傍の設定を返す。
    2. それ以外は diff の閾値で fallback。
    """
    if specs is None:
        specs = load_juggler_specs()

    cp = parse_composite_prob(composite_prob)
    if machine_name in specs and cp > 0:
        spec = specs[machine_name].get("合成") or specs[machine_name].get("composite")
        if spec:
            distances = [(i + 1, abs(cp - sp)) for i, sp in enumerate(spec)]
            return min(distances, key=lambda x: x[1])[0]

    # fallback
    d = float(diff) if diff is not None else 0.0
    for threshold, setting in _FALLBACK_THRESHOLDS:
        if d > threshold:
            return setting
    return 1
