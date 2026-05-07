"""履歴特徴量の生成 (shift(1) で当日を除外、前日まで使用)。

リーク防止:
    - target は翌日の diff
    - 特徴量は前日までの過去 N 日 (.shift(1).rolling())
    - これにより t 日の予測に t 日のデータは使わない
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


HISTORY_FEATURE_COLS = [
    "unit_bb_rate_mean_7d",
    "unit_bb_rate_mean_14d",
    "unit_diff_mean_7d",
    "unit_diff_mean_14d",
    "unit_diff_sum_7d",
    "unit_observed_days_14d",
    "sm_bb_rate_mean_14d",
    "sm_diff_mean_14d",
    "sm_win_rate_14d",
    "sm_top_diff_14d",
    "sm_diff_std_14d",
    "shop_total_diff_7d",
    "shop_total_diff_14d",
    "shop_win_rate_7d",
    "dow",
    "is_weekend",
    "is_month_start",
    "is_month_end",
    "day_has_5_or_8",
]


def _shift_rolling(series: pd.Series, window: int, agg: str = "mean") -> pd.Series:
    """前日までの rolling 集計。当日を除外する。"""
    shifted = series.shift(1)
    rolling = shifted.rolling(window, min_periods=1)
    if agg == "mean":
        return rolling.mean()
    elif agg == "sum":
        return rolling.sum()
    elif agg == "std":
        return rolling.std()
    elif agg == "max":
        return rolling.max()
    elif agg == "count":
        return rolling.count()
    else:
        raise ValueError(f"unsupported agg: {agg}")


def add_history_features(df: pd.DataFrame) -> pd.DataFrame:
    """履歴特徴量を追加 (前日までを使用、当日含めない)。"""
    if df.empty:
        return df.copy()

    out = df.copy()
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")
    out = out.sort_values(["shop_id", "machine_name", "unit_number", "date_dt"]).reset_index(drop=True)

    g = out["g_count"].astype("Float64")
    bb = out["bb"].astype("Float64")
    out["_bb_rate_today"] = (bb / g).where(g > 0).astype(float)
    out["_diff_today"] = out["diff"].astype(float)
    out["_win_today"] = (out["_diff_today"] > 1000).astype(float)

    # ===== A. 台レベル履歴 (shift(1) で前日まで) =====
    grp_unit = out.groupby(["shop_id", "machine_name", "unit_number"], sort=False)
    out["unit_bb_rate_mean_7d"] = grp_unit["_bb_rate_today"].transform(
        lambda s: _shift_rolling(s, 7, "mean")
    )
    out["unit_bb_rate_mean_14d"] = grp_unit["_bb_rate_today"].transform(
        lambda s: _shift_rolling(s, 14, "mean")
    )
    out["unit_diff_mean_7d"] = grp_unit["_diff_today"].transform(
        lambda s: _shift_rolling(s, 7, "mean")
    )
    out["unit_diff_mean_14d"] = grp_unit["_diff_today"].transform(
        lambda s: _shift_rolling(s, 14, "mean")
    )
    out["unit_diff_sum_7d"] = grp_unit["_diff_today"].transform(
        lambda s: _shift_rolling(s, 7, "sum")
    )
    out["unit_observed_days_14d"] = grp_unit["_diff_today"].transform(
        lambda s: _shift_rolling(s, 14, "count")
    )

    # ===== B. 店舗 × 機種レベル =====
    sm_daily = (
        out.groupby(["shop_id", "machine_name", "date_dt"], sort=False)
        .agg(
            sm_bb_rate_today=("_bb_rate_today", "mean"),
            sm_diff_today=("_diff_today", "mean"),
            sm_win_today=("_win_today", "mean"),
            sm_top_diff_today=("_diff_today", "max"),
            sm_diff_std_today=("_diff_today", "std"),
        )
        .reset_index()
        .sort_values(["shop_id", "machine_name", "date_dt"])
    )
    grp_sm = sm_daily.groupby(["shop_id", "machine_name"], sort=False)
    sm_daily["sm_bb_rate_mean_14d"] = grp_sm["sm_bb_rate_today"].transform(
        lambda s: _shift_rolling(s, 14, "mean")
    )
    sm_daily["sm_diff_mean_14d"] = grp_sm["sm_diff_today"].transform(
        lambda s: _shift_rolling(s, 14, "mean")
    )
    sm_daily["sm_win_rate_14d"] = grp_sm["sm_win_today"].transform(
        lambda s: _shift_rolling(s, 14, "mean")
    )
    sm_daily["sm_top_diff_14d"] = grp_sm["sm_top_diff_today"].transform(
        lambda s: _shift_rolling(s, 14, "max")
    )
    sm_daily["sm_diff_std_14d"] = grp_sm["sm_diff_today"].transform(
        lambda s: _shift_rolling(s, 14, "std")
    )
    sm_cols = ["sm_bb_rate_mean_14d", "sm_diff_mean_14d", "sm_win_rate_14d",
               "sm_top_diff_14d", "sm_diff_std_14d"]
    out = out.merge(
        sm_daily[["shop_id", "machine_name", "date_dt", *sm_cols]],
        on=["shop_id", "machine_name", "date_dt"],
        how="left",
    )

    # ===== C. 店舗レベル =====
    shop_daily = (
        out.groupby(["shop_id", "date_dt"], sort=False)
        .agg(
            shop_total_diff_today=("_diff_today", "sum"),
            shop_win_today=("_win_today", "mean"),
        )
        .reset_index()
        .sort_values(["shop_id", "date_dt"])
    )
    grp_shop = shop_daily.groupby(["shop_id"], sort=False)
    shop_daily["shop_total_diff_7d"] = grp_shop["shop_total_diff_today"].transform(
        lambda s: _shift_rolling(s, 7, "sum")
    )
    shop_daily["shop_total_diff_14d"] = grp_shop["shop_total_diff_today"].transform(
        lambda s: _shift_rolling(s, 14, "sum")
    )
    shop_daily["shop_win_rate_7d"] = grp_shop["shop_win_today"].transform(
        lambda s: _shift_rolling(s, 7, "mean")
    )
    shop_cols = ["shop_total_diff_7d", "shop_total_diff_14d", "shop_win_rate_7d"]
    out = out.merge(
        shop_daily[["shop_id", "date_dt", *shop_cols]],
        on=["shop_id", "date_dt"],
        how="left",
    )

    # ===== D. 日付特徴量 =====
    out["dow"] = out["date_dt"].dt.dayofweek.astype("Int64")
    out["is_weekend"] = out["dow"].isin([5, 6]).astype(np.int8)
    day_of_month = out["date_dt"].dt.day
    out["is_month_start"] = (day_of_month <= 1).astype(np.int8)
    days_in_month = out["date_dt"].dt.days_in_month
    out["is_month_end"] = (day_of_month >= days_in_month - 2).astype(np.int8)
    out["day_has_5_or_8"] = day_of_month.isin([5, 8, 15, 18, 25, 28]).astype(np.int8)

    out = out.drop(columns=["_bb_rate_today", "_diff_today", "_win_today"])

    n_added = len(HISTORY_FEATURE_COLS)
    logger.info("履歴特徴量 %d 列を追加 (shift(1) 適用、rows=%d)", n_added, len(out))
    return out
