"""split.time_split のテスト。"""
from __future__ import annotations

from pathlib import Path

import yaml

from juggler_predictor.model import (
    build_features,
    load_dataset_from_local,
    time_split,
)

ROOT = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"
MACHINES_YAML = (
    Path(__file__).resolve().parents[1] / "config" / "machines.yaml"
)


def test_time_split_train_before_valid() -> None:
    df = load_dataset_from_local(ROOT)
    feat, _ = build_features(
        df,
        machines_config=yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8")),
    )
    train, valid = time_split(feat, valid_days=7)

    # valid は最新日 (2026-05-05) を含む 7 日
    assert "2026-05-05" in valid["date"].unique()
    if not train.empty:
        # train の全日付は valid の最小日付より前
        assert train["date_dt"].max() < valid["date_dt"].min()


def test_time_split_with_valid_days_2_only_recent() -> None:
    df = load_dataset_from_local(ROOT)
    feat, _ = build_features(
        df,
        machines_config=yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8")),
    )
    # サンプルは 04-29, 04-30, 05-05 → valid_days=2 なら valid は 05-05 と前日 (05-04 はデータなし) のみ
    train, valid = time_split(feat, valid_days=2)
    valid_dates = set(valid["date"].unique())
    assert "2026-05-05" in valid_dates
    assert "2026-04-29" not in valid_dates
    assert "2026-04-30" not in valid_dates


def test_empty_input_returns_empty() -> None:
    import pandas as pd
    train, valid = time_split(pd.DataFrame())
    assert train.empty
    assert valid.empty
