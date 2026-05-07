"""time_split のテスト (P3b Part 2.5 の新仕様: target=翌日 diff 対応)。"""
from __future__ import annotations

import pandas as pd
import pytest

from juggler_predictor.model import build_features, time_split


def _machines_cfg():
    return {"machines": [{"canonical": "マイジャグラーV", "aliases": []}]}


def _make_df_for_split():
    """split テスト用: 4/29-5/06 の 8日分、target 計算可能にする。"""
    rows = []
    for date, diff in [
        ("2026-04-29", 100), ("2026-04-30", 200), ("2026-05-01", 300),
        ("2026-05-02", 400), ("2026-05-03", 500), ("2026-05-04", 600),
        ("2026-05-05", 700), ("2026-05-06", 800),  # 5/6 は target=NaN で drop されるが、5/5 の target 計算用に必要
    ]:
        rows.append({
            "shop_id": "shopA", "date": date, "machine_name": "マイジャグラーV",
            "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": diff,
        })
    return pd.DataFrame(rows)


def test_time_split_train_before_valid():
    """train の最大日付 < valid の最小日付。"""
    df = _make_df_for_split()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # feat には 4/29〜5/05 の 7 行 (5/06 は target NaN で drop)
    train, valid = time_split(feat, valid_days=2)
    # valid_days=2 なので最終 2 日 (5/04, 5/05) が valid
    assert "2026-05-05" in valid["date"].unique()
    assert "2026-05-04" in valid["date"].unique()
    # train の最大日付 < valid の最小日付
    train_max = pd.to_datetime(train["date"]).max()
    valid_min = pd.to_datetime(valid["date"]).min()
    assert train_max < valid_min


def test_time_split_with_valid_days_2_only_recent():
    df = _make_df_for_split()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    train, valid = time_split(feat, valid_days=2)
    valid_dates = set(valid["date"].unique())
    # 最終 2 日が valid に含まれる
    assert "2026-05-05" in valid_dates
    assert "2026-05-04" in valid_dates
    # 古い日付は train
    assert "2026-04-29" not in valid_dates


def test_time_split_returns_two_dataframes():
    df = _make_df_for_split()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    result = time_split(feat, valid_days=2)
    assert len(result) == 2
    train, valid = result
    assert isinstance(train, pd.DataFrame)
    assert isinstance(valid, pd.DataFrame)
    assert len(train) + len(valid) == len(feat)
