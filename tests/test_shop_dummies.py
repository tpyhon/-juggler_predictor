"""shop_id one-hot ダミーが正しく生成されることを検証。"""
from __future__ import annotations

import pandas as pd

from juggler_predictor.model import build_features


def _machines_cfg():
    return {"machines": [{"canonical": "マイジャグラーV", "aliases": []}]}


def _make_df():
    """3 店舗 × 各 2 日分。"""
    rows = []
    for shop in ("shopA", "shopB", "shopC"):
        for i, date in enumerate(["2026-05-01", "2026-05-02", "2026-05-03"]):
            rows.append({
                "shop_id": shop, "date": date,
                "machine_name": "マイジャグラーV", "unit_number": "100",
                "g_count": 6000 + i * 100, "bb": 20, "rb": 15, "diff": 100 + i * 50,
            })
    return pd.DataFrame(rows)


def test_shop_dummies_count_equals_n_minus_1():
    """3 店舗なら shop dummy は 2 列 (ベース 1 つを除く)。"""
    df = _make_df()
    _, meta = build_features(df, machines_config=_machines_cfg())
    assert len(meta.shop_dummy_cols) == 2  # 3 - 1


def test_shop_dummy_columns_in_feature_cols():
    """is_shop_* が feature_cols に含まれること。"""
    df = _make_df()
    _, meta = build_features(df, machines_config=_machines_cfg())
    shop_cols_in_features = [c for c in meta.feature_cols if c.startswith("is_shop_")]
    assert len(shop_cols_in_features) == len(meta.shop_dummy_cols)


def test_shop_ids_param_overrides_auto_detection():
    """shop_ids を明示渡すと、その順序でダミーが作られる (予測時の整合性)。"""
    df = _make_df()
    _, meta = build_features(
        df, machines_config=_machines_cfg(),
        shop_ids=["shopX", "shopA", "shopB", "shopC"],  # 学習時は4店舗あった想定
    )
    # shopX がベース、残り 3 つが dummy
    assert "is_shop_shopA" in meta.shop_dummy_cols
    assert "is_shop_shopB" in meta.shop_dummy_cols
    assert "is_shop_shopC" in meta.shop_dummy_cols


def test_shop_dummy_values_are_binary():
    """各行の shop dummy が 0/1 のみであること。"""
    df = _make_df()
    feat, meta = build_features(df, machines_config=_machines_cfg())
    for col in meta.shop_dummy_cols:
        unique_vals = set(feat[col].unique().tolist())
        assert unique_vals.issubset({0, 1}), f"{col} に 0/1 以外の値: {unique_vals}"
