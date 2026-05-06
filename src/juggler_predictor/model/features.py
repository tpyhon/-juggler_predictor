"""dataset DataFrame を学習用特徴量に変換する。

設計:
    - 当日特徴量のみ (履歴は P4 以降で拡張する)
    - target_diff: 当日 diff (回帰ターゲット)
    - target_win:  diff > TARGET_DIFF_THRESHOLD なら 1, else 0
    - 機種は one-hot (machines.yaml の canonical を列にする)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TARGET_DIFF_THRESHOLD = 1000  # diff > 1000 で勝ち扱い


@dataclass(frozen=True)
class FeatureMeta:
    """学習・予測時の特徴量メタ情報。"""

    feature_cols: list[str]
    target_diff_col: str
    target_win_col: str
    machine_dummy_cols: list[str]


def _canonical_set(machines_config: dict) -> list[str]:
    return [m["canonical"] for m in machines_config.get("machines", []) if "canonical" in m]


def build_features(
    df: pd.DataFrame,
    *,
    machines_config: dict,
    drop_na_target: bool = True,
) -> tuple[pd.DataFrame, FeatureMeta]:
    """dataset DataFrame に特徴量列とターゲット列を追加して返す。

    入力:
        必要列: shop_id, date, machine_name, unit_number,
               g_count, diff, bb, rb (art は欠損可)
    出力:
        (拡張済み DataFrame, FeatureMeta)
    """
    if df.empty:
        meta = FeatureMeta(
            feature_cols=[],
            target_diff_col="target_diff",
            target_win_col="target_win",
            machine_dummy_cols=[],
        )
        return df.copy(), meta

    out = df.copy()

    # 数値整形
    for col in ("g_count", "diff", "bb", "rb", "art"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 派生特徴量
    g = out["g_count"].astype("Float64")
    bb = out["bb"].astype("Float64")
    rb = out["rb"].astype("Float64")
    out["bb_rate"] = (bb / g).where(g > 0)
    out["rb_rate"] = (rb / g).where(g > 0)
    out["total_rate"] = ((bb + rb) / g).where(g > 0)
    out["bb_per_rb"] = (bb / rb).where(rb > 0)

    # 機種 one-hot (machines.yaml に列挙された canonical のみ)
    canonicals = _canonical_set(machines_config)
    for name in canonicals:
        col = _machine_dummy_col(name)
        out[col] = (out["machine_name"] == name).astype(np.int8)
    machine_dummy_cols = [_machine_dummy_col(n) for n in canonicals]

    # ターゲット
    out["target_diff"] = out["diff"].astype("Float64")

    # target_diff が NaN の行は target_win 計算前に除去 (Float64 -> int8 変換のため)
    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除去", dropped)

    # target_win: NaN は False として扱う (drop_na_target=False の場合の保険)
    out["target_win"] = (
        (out["target_diff"] > TARGET_DIFF_THRESHOLD).fillna(False).astype(np.int8)
    )

    # date 列を datetime 化 (split のため)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")

    feature_cols: list[str] = [
        "g_count",
        "bb",
        "rb",
        "bb_rate",
        "rb_rate",
        "total_rate",
        "bb_per_rb",
        *machine_dummy_cols,
    ]

    meta = FeatureMeta(
        feature_cols=feature_cols,
        target_diff_col="target_diff",
        target_win_col="target_win",
        machine_dummy_cols=machine_dummy_cols,
    )
    return out, meta


def _machine_dummy_col(name: str) -> str:
    return f"is_{name}"
