"""dataset.load_dataset_from_local のテスト。"""
from __future__ import annotations

from pathlib import Path

from juggler_predictor.model import load_dataset_from_local

ROOT = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"


def test_load_local_returns_dataframe() -> None:
    df = load_dataset_from_local(ROOT)
    assert not df.empty
    assert "shop_id" in df.columns
    assert "date" in df.columns
    assert "machine_name" in df.columns


def test_load_local_unique_shops_and_dates() -> None:
    df = load_dataset_from_local(ROOT)
    assert set(df["shop_id"].unique()) == {"kingsetagaya", "messekichijoji"}
    assert "2026-04-29" in df["date"].unique()
    assert "2026-05-05" in df["date"].unique()


def test_load_local_row_counts() -> None:
    df = load_dataset_from_local(ROOT)
    # kingsetagaya: 2 + 2 + 1 = 5
    # messekichijoji: 1
    assert (df["shop_id"] == "kingsetagaya").sum() == 5
    assert (df["shop_id"] == "messekichijoji").sum() == 1


def test_load_empty_returns_empty_df() -> None:
    df = load_dataset_from_local(Path("tests/fixtures/__not_exist__"))
    assert df.empty
