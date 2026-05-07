"""履歴特徴量のリーク防止テスト (shift(1) 仕様)。"""
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
