"""build_features のテスト (P3b Part 2.5: target=翌日 diff 仕様)。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from juggler_predictor.model import FeatureMeta, TARGET_DIFF_THRESHOLD, build_features


def _machines_cfg():
    return {
        "machines": [
            {"canonical": "マイジャグラーV", "aliases": []},
            {"canonical": "ネオアイムジャグラーEX", "aliases": []},
        ]
    }


def _make_df():
    """同じ shop, machine, unit で 2 日分 (target 計算可能な最小構成)。"""
    rows = [
        # マイV unit=1: 4/29(diff=100) → 4/30(diff=2200, target_win=1)
        {"shop_id": "kingsetagaya", "date": "2026-04-29", "machine_name": "マイジャグラーV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
        {"shop_id": "kingsetagaya", "date": "2026-04-30", "machine_name": "マイジャグラーV",
         "unit_number": "1", "g_count": 6500, "bb": 25, "rb": 18, "diff": 2200},
        # マイV unit=1 の 5/1 (target 計算用に必要)
        {"shop_id": "kingsetagaya", "date": "2026-05-01", "machine_name": "マイジャグラーV",
         "unit_number": "1", "g_count": 6300, "bb": 22, "rb": 17, "diff": -500},
        # ネオEX unit=2: 4/29 → 4/30(target=300)
        {"shop_id": "kingsetagaya", "date": "2026-04-29", "machine_name": "ネオアイムジャグラーEX",
         "unit_number": "2", "g_count": 5500, "bb": 18, "rb": 14, "diff": -200},
        {"shop_id": "kingsetagaya", "date": "2026-04-30", "machine_name": "ネオアイムジャグラーEX",
         "unit_number": "2", "g_count": 5800, "bb": 20, "rb": 15, "diff": 300},
        # 別店舗: target 計算可能にするため 2 日分
        {"shop_id": "messekichijoji", "date": "2026-04-29", "machine_name": "マイジャグラーV",
         "unit_number": "10", "g_count": 7000, "bb": 28, "rb": 20, "diff": 1500},
        {"shop_id": "messekichijoji", "date": "2026-04-30", "machine_name": "マイジャグラーV",
         "unit_number": "10", "g_count": 7200, "bb": 30, "rb": 22, "diff": 800},
    ]
    return pd.DataFrame(rows)


def test_build_features_adds_rate_columns():
    df = _make_df()
    feat, meta = build_features(df, machines_config=_machines_cfg())
    for col in ("bb_rate", "rb_rate", "total_rate", "bb_per_rb"):
        assert col in feat.columns
    assert isinstance(meta, FeatureMeta)


def test_target_win_threshold():
    """target_win = (翌日 diff > TARGET_DIFF_THRESHOLD) で計算されること。"""
    df = _make_df()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    feat = feat.sort_values(["shop_id", "unit_number", "date"]).reset_index(drop=True)

    # マイV unit=1 の 4/29 行: target_diff=2200 (>1000) → target_win=1
    row1 = feat[(feat["shop_id"] == "kingsetagaya") & (feat["unit_number"] == "1") &
                (feat["date"] == "2026-04-29")].iloc[0]
    assert row1["target_diff"] == 2200.0
    assert int(row1["target_win"]) == 1

    # マイV unit=1 の 4/30 行: target_diff=-500 (≤1000) → target_win=0
    row2 = feat[(feat["shop_id"] == "kingsetagaya") & (feat["unit_number"] == "1") &
                (feat["date"] == "2026-04-30")].iloc[0]
    assert row2["target_diff"] == -500.0
    assert int(row2["target_win"]) == 0


def test_machine_dummy_columns_present():
    """機種ダミーが正しく付与されること。"""
    df = _make_df()
    feat, meta = build_features(df, machines_config=_machines_cfg())
    assert "is_マイジャグラーV" in feat.columns
    assert "is_ネオアイムジャグラーEX" in feat.columns

    # マイV の行数: 元データ 5 行 (3+2) → 各台の最終日が drop
    # マイV unit=1 (kingsetagaya): 3 行 → 2 行残 (5/1 が最終日で drop)
    # マイV unit=10 (messekichijoji): 2 行 → 1 行残 (4/30 が最終日で drop)
    # 計 3 行
    assert int(feat["is_マイジャグラーV"].sum()) == 3


def test_feature_cols_meta():
    df = _make_df()
    _, meta = build_features(df, machines_config=_machines_cfg())
    # base 7 + machine_dummy 2 + shop_dummy 1 (2店舗-1) = 10
    assert "g_count" in meta.feature_cols
    assert "bb_rate" in meta.feature_cols
    assert any(c.startswith("is_") for c in meta.feature_cols)


def test_drops_na_target_rows():
    """翌日データのない行 (各台の最終日) が除外されること。"""
    df = _make_df()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # 元 7 行 → 各台 (3グループ) の最終日が drop → 7 - 3 = 4 行残
    assert len(feat) == 4
