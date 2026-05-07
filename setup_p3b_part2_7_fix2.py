# setup_p3b_part2_7_fix2.py
"""履歴特徴量を shift(1) で前日までに限定 (リーク防止強化)。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

HISTORY_PY = '''"""履歴特徴量の生成 (shift(1) で当日を除外、前日まで使用)。

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
'''

# テストも shift(1) 仕様に更新
TEST_HISTORY = '''"""履歴特徴量のリーク防止テスト (shift(1) 仕様)。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from juggler_predictor.model import HISTORY_FEATURE_COLS, add_history_features


def _make_df(n_days: int = 10):
    rows = []
    for i in range(n_days):
        date = f"2026-04-{i+1:02d}"
        rows.append({
            "shop_id": "shopA", "date": date, "machine_name": "マイV",
            "unit_number": "1", "g_count": 6000 + i * 100,
            "bb": 20 + i, "rb": 15, "diff": 100 * (i + 1),
        })
    return pd.DataFrame(rows)


def test_all_history_cols_added():
    df = _make_df(10)
    out = add_history_features(df)
    for col in HISTORY_FEATURE_COLS:
        assert col in out.columns, f"missing: {col}"


def test_first_day_unit_history_is_nan():
    """最初の日は前日データが無いので unit_diff_mean_7d は NaN。"""
    df = _make_df(10)
    out = add_history_features(df).sort_values("date").reset_index(drop=True)
    # 1日目: shift(1) で前日が無い → NaN
    assert pd.isna(out.iloc[0]["unit_diff_mean_7d"])


def test_unit_diff_mean_7d_is_previous_days_only():
    """t日の unit_diff_mean_7d は t-1 日までの平均 (当日含まない)。"""
    df = _make_df(10)
    out = add_history_features(df).sort_values("date").reset_index(drop=True)
    # 2日目: 前日 (1日目) の diff = 100 のみ
    assert out.iloc[1]["unit_diff_mean_7d"] == 100.0
    # 7日目: 1〜6日目の diff 平均 = (100+200+300+400+500+600)/6 = 350
    assert abs(out.iloc[6]["unit_diff_mean_7d"] - 350.0) < 1e-6
    # 8日目: 1〜7日目の平均 = (100+...+700)/7 = 400
    assert abs(out.iloc[7]["unit_diff_mean_7d"] - 400.0) < 1e-6


def test_no_today_in_history():
    """t日の履歴特徴量に t日の値が含まれないこと (重要)。"""
    df = _make_df(10)
    out = add_history_features(df).sort_values("date").reset_index(drop=True)
    # 10日目の unit_diff_mean_14d は 1〜9日目の平均、10日目の diff=1000 は含まない
    # 1〜9日目の平均 = (100+200+...+900)/9 = 500
    assert abs(out.iloc[9]["unit_diff_mean_14d"] - 500.0) < 1e-6


def test_dow_and_weekend_flags():
    df = pd.DataFrame([{
        "shop_id": "shopA", "date": "2026-05-02",
        "machine_name": "マイV", "unit_number": "1",
        "g_count": 6000, "bb": 20, "rb": 15, "diff": 100,
    }])
    out = add_history_features(df)
    assert int(out.iloc[0]["dow"]) == 5
    assert int(out.iloc[0]["is_weekend"]) == 1


def test_day_has_5_or_8_flag():
    df = pd.DataFrame([
        {"shop_id": "shopA", "date": "2026-05-05", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
        {"shop_id": "shopA", "date": "2026-05-06", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
    ])
    out = add_history_features(df).sort_values("date").reset_index(drop=True)
    assert int(out.iloc[0]["day_has_5_or_8"]) == 1
    assert int(out.iloc[1]["day_has_5_or_8"]) == 0


def test_groupby_isolates_shops():
    """別店舗のデータが混ざらないこと。"""
    rows = [
        {"shop_id": "shopA", "date": "2026-05-01", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 1000},
        {"shop_id": "shopB", "date": "2026-05-01", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": -2000},
        {"shop_id": "shopA", "date": "2026-05-02", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 500},
    ]
    df = pd.DataFrame(rows)
    out = add_history_features(df)
    # shopA の 5/02 の unit_diff_mean_7d = 前日 (5/01 shopA) の diff = 1000
    a_row = out[(out["shop_id"] == "shopA") & (out["date"] == "2026-05-02")].iloc[0]
    assert a_row["unit_diff_mean_7d"] == 1000.0  # shopB の -2000 は混ざらない


def test_row_count_preserved():
    df = _make_df(10)
    out = add_history_features(df)
    assert len(out) == len(df)
'''


def main():
    files = {
        "src/juggler_predictor/model/history.py": HISTORY_PY,
        "tests/test_history_features.py": TEST_HISTORY,
    }
    for rel, content in files.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"[WRITE] {p}")
    print()
    print(f"[SUCCESS] {len(files)} files updated")
    print()
    print("次:")
    print("  uv run pytest tests/test_history_features.py -v")
    print("  uv run pytest -v")
    print("  uv run python scripts/build_dataset.py")
    print("  uv run python scripts/train.py")


if __name__ == "__main__":
    main()
