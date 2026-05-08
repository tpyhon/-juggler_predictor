"""dataset DataFrame を学習用特徴量に変換する。

設計 (P3b Part 2.7 履歴特徴量版):
    - target_diff: 翌日の同じ台の diff
    - target_win:  翌日 diff > TARGET_DIFF_THRESHOLD なら 1
    - 当日特徴量: g_count, bb, rb, *_rate (7列)
    - 機種ダミー: machines.yaml の canonical (9列)
    - 店舗ダミー: 18店舗中17列
    - 履歴特徴量: 台/店舗×機種/店舗/日付 (19列)
    合計: 7 + 9 + 17 + 19 = 52列
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .history import HISTORY_FEATURE_COLS, add_history_features

logger = logging.getLogger(__name__)

TARGET_DIFF_THRESHOLD = 1000


@dataclass(frozen=True)
class FeatureMeta:
    feature_cols: list[str]
    target_diff_col: str
    target_win_col: str
    machine_dummy_cols: list[str]
    shop_dummy_cols: list[str]
    history_cols: list[str]
    shop_ids: list[str]


def _canonical_set(machines_config: dict) -> list[str]:
    return [m["canonical"] for m in machines_config.get("machines", []) if "canonical" in m]


def build_features(
    df: pd.DataFrame,
    *,
    machines_config: dict,
    shop_ids: list[str] | None = None,
    drop_na_target: bool = True,
    add_history: bool = True,
) -> tuple[pd.DataFrame, FeatureMeta]:
    if df.empty:
        meta = FeatureMeta(
            feature_cols=[], target_diff_col="target_diff", target_win_col="target_win",
            machine_dummy_cols=[], shop_dummy_cols=[], history_cols=[], shop_ids=[],
        )
        return df.copy(), meta

    out = df.copy()

    # 数値整形
    for col in ("g_count", "diff", "bb", "rb", "art"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 履歴特徴量 (target shift より前に計算: 履歴は当日含む過去)
    if add_history:
        out = add_history_features(out)
        history_cols = list(HISTORY_FEATURE_COLS)
    else:
        history_cols = []
        out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")

    # 当日派生特徴量
    g = out["g_count"].astype("Float64")
    bb = out["bb"].astype("Float64")
    rb = out["rb"].astype("Float64")
    out["bb_rate"] = (bb / g).where(g > 0)
    out["rb_rate"] = (rb / g).where(g > 0)
    out["total_rate"] = ((bb + rb) / g).where(g > 0)
    out["bb_per_rb"] = (bb / rb).where(rb > 0)

    # 機種 one-hot
    canonicals = _canonical_set(machines_config)
    for name in canonicals:
        col = _machine_dummy_col(name)
        out[col] = (out["machine_name"] == name).astype(np.int8)
    machine_dummy_cols = [_machine_dummy_col(n) for n in canonicals]

    # 店舗 one-hot
    if shop_ids is None:
        shop_ids_used = sorted(out["shop_id"].dropna().unique().tolist())
    else:
        shop_ids_used = list(shop_ids)
    shop_dummy_cols: list[str] = []
    if len(shop_ids_used) >= 2:
        for sid in shop_ids_used[1:]:
            col = _shop_dummy_col(sid)
            out[col] = (out["shop_id"] == sid).astype(np.int8)
            shop_dummy_cols.append(col)

    # ターゲット (翌日 diff)
    out = out.sort_values(["shop_id", "unit_number", "machine_name", "date_dt"]).reset_index(drop=True)
    out["target_diff"] = (
        out.groupby(["shop_id", "unit_number", "machine_name"])["diff"]
        .shift(-1)
        .astype("Float64")
    )

    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除外", dropped)

    out["target_win"] = (
        (out["target_diff"] > TARGET_DIFF_THRESHOLD).fillna(False).astype(np.int8)
    )

    feature_cols: list[str] = [
        "g_count", "bb", "rb",
        "bb_rate", "rb_rate", "total_rate", "bb_per_rb",
        *machine_dummy_cols,
        *shop_dummy_cols,
        *history_cols,
    ]

    meta = FeatureMeta(
        feature_cols=feature_cols,
        target_diff_col="target_diff",
        target_win_col="target_win",
        machine_dummy_cols=machine_dummy_cols,
        shop_dummy_cols=shop_dummy_cols,
        history_cols=history_cols,
        shop_ids=shop_ids_used,
    )
    return out, meta


def _machine_dummy_col(name: str) -> str:
    return f"is_{name}"


def _shop_dummy_col(shop_id: str) -> str:
    return f"is_shop_{shop_id}"
