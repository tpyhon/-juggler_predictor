"""features.build_features のテスト。"""
from __future__ import annotations

from pathlib import Path

import yaml

from juggler_predictor.model import (
    TARGET_DIFF_THRESHOLD,
    build_features,
    load_dataset_from_local,
)

ROOT = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"
MACHINES_YAML = (
    Path(__file__).resolve().parents[1] / "config" / "machines.yaml"
)


def _machines_cfg() -> dict:
    return yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8"))


def test_build_features_adds_rate_columns() -> None:
    df = load_dataset_from_local(ROOT)
    feat, meta = build_features(df, machines_config=_machines_cfg())
    for col in ("bb_rate", "rb_rate", "total_rate", "bb_per_rb"):
        assert col in feat.columns
    assert meta.target_diff_col == "target_diff"
    assert meta.target_win_col == "target_win"


def test_target_win_threshold() -> None:
    df = load_dataset_from_local(ROOT)
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # diff>1000 の行は target_win=1
    for _, row in feat.iterrows():
        expected = int(row["diff"] > TARGET_DIFF_THRESHOLD)
        assert int(row["target_win"]) == expected


def test_machine_dummy_columns_present() -> None:
    df = load_dataset_from_local(ROOT)
    feat, meta = build_features(df, machines_config=_machines_cfg())
    canonicals = [m["canonical"] for m in _machines_cfg()["machines"]]
    for name in canonicals:
        col = f"is_{name}"
        assert col in feat.columns
    # 「マイジャグラーV」フラグが立っている行が 4 行 (合計 4 ファイルの先頭行)
    assert int(feat["is_マイジャグラーV"].sum()) == 4


def test_feature_cols_meta() -> None:
    df = load_dataset_from_local(ROOT)
    _, meta = build_features(df, machines_config=_machines_cfg())
    # 主要派生 + 機種 dummy が含まれる
    assert "bb_rate" in meta.feature_cols
    assert "rb_rate" in meta.feature_cols
    assert "total_rate" in meta.feature_cols
    assert any(c.startswith("is_") for c in meta.feature_cols)


def test_drops_na_target_rows() -> None:
    import pandas as pd
    df = load_dataset_from_local(ROOT)
    # diff を NaN にした行を追加
    extra = df.iloc[0].to_dict()
    extra["diff"] = None
    extra["unit_number"] = "999"
    df2 = pd.concat([df, pd.DataFrame([extra])], ignore_index=True)
    feat, _ = build_features(df2, machines_config=_machines_cfg())
    assert len(feat) == len(df)  # NaN 行は除外される
