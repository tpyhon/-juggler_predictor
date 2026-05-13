"""target_diff が翌日の diff になっていることを検証 (リーク防止)。"""
from __future__ import annotations

import pandas as pd
import pytest

from juggler_predictor.model import build_features


def _machines_cfg():
    return {
        "machines": [
            {"canonical": "マイジャグラーV", "aliases": []},
            {"canonical": "ファンキージャグラー2", "aliases": []},
        ]
    }


def _make_df():
    """同じ (shop, unit, machine) で 3 日分のデータ。"""
    rows = []
    for date, diff_val, bb, rb, g in [
        ("2026-05-01", 100, 20, 15, 6000),
        ("2026-05-02", 500, 25, 18, 6500),
        ("2026-05-03", -300, 18, 12, 5500),
    ]:
        rows.append({
            "shop_id": "shopA", "date": date,
            "machine_name": "マイジャグラーV", "unit_number": "100",
            "g_count": g, "bb": bb, "rb": rb, "diff": diff_val,
        })
    return pd.DataFrame(rows)


def test_target_diff_is_next_day_not_same_day():
    df = _make_df()
    feat, meta = build_features(df, machines_config=_machines_cfg())

    # 各行の target_diff が**翌日**の diff になっていること
    feat_sorted = feat.sort_values("date").reset_index(drop=True)
    # 2026-05-01 の target_diff は 2026-05-02 の diff = 500
    assert feat_sorted.iloc[0]["target_diff"] == 500.0
    # 2026-05-02 の target_diff は 2026-05-03 の diff = -300
    assert feat_sorted.iloc[1]["target_diff"] == -300.0
    # 2026-05-03 は翌日データなしで drop されているはず
    assert (feat_sorted["date"] == "2026-05-03").sum() == 0


def test_target_diff_not_equal_to_same_day_diff():
    """リーク確認: 当日 diff と target_diff が一致しないこと。"""
    df = _make_df()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # diff と target_diff の差が 0 の行は無いはず (3日のうち2日残るが値が違う)
    same = (feat["diff"] == feat["target_diff"]).sum()
    assert same == 0, f"target_diff が当日 diff と同じ行が {same} 件あります (リークの疑い)"


def test_last_day_per_unit_is_dropped():
    """各 (shop, unit, machine) の最終日が drop されていること。"""
    df = _make_df()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # 元 3 行 → 翌日のある 2 行のみ残る
    assert len(feat) == 2


def test_machine_change_is_dropped():
    """同じ unit で機種が変わった日は drop されること。"""
    rows = [
        {"shop_id": "shopA", "date": "2026-05-01", "machine_name": "マイジャグラーV",
         "unit_number": "100", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
        {"shop_id": "shopA", "date": "2026-05-02", "machine_name": "マイジャグラーV",
         "unit_number": "100", "g_count": 6500, "bb": 25, "rb": 18, "diff": 500},
        # 機種変更
        {"shop_id": "shopA", "date": "2026-05-03", "machine_name": "ファンキージャグラー2",
         "unit_number": "100", "g_count": 5500, "bb": 18, "rb": 12, "diff": -300},
    ]
    df = pd.DataFrame(rows)
    feat, _ = build_features(df, machines_config=_machines_cfg())

    # マイV の 5/1 → 5/2 で 1 行残る (5/1 の target=5/2 の diff=500)
    # マイV の 5/2 は target なし(機種変更で別 group)
    # ファンキー2 の 5/3 も target なし
    assert len(feat) == 1
    assert feat.iloc[0]["target_diff"] == 500.0
