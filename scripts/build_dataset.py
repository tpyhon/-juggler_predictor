"""dataset 構築 CLI: R2 → 履歴特徴量 → split → parquet + meta JSON 保存。"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

import pandas as pd
import yaml
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CONFIG_DIR = ROOT / "config"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from juggler_predictor.common.logging import setup_logging  # noqa: E402
from juggler_predictor.model import (  # noqa: E402
    build_features,
    load_dataset_from_r2,
    time_split,
)
from juggler_predictor.model.dataset import add_prev_setting_features  # noqa: E402
from juggler_predictor.storage import build_r2_client_from_env  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "dataset.parquet"))
    parser.add_argument("--valid-days", type=int, default=7)
    args = parser.parse_args()

    load_dotenv()
    setup_logging()

    machines_cfg = yaml.safe_load((CONFIG_DIR / "machines.yaml").read_text(encoding="utf-8"))

    logger.info("[1] R2 から dataset 読み込み")
    r2 = build_r2_client_from_env()
    df = load_dataset_from_r2(r2)
    df = add_prev_setting_features(df)
    logger.info("prev_setting/prev_p_high/y_setting_next added rows=%d", len(df))
    logger.info("rows=%d shops=%d dates=%d", len(df), df["shop_id"].nunique(), df["date"].nunique())

    logger.info("[2] 特徴量生成 (履歴特徴量含む)")
    feat_df, meta = build_features(df, machines_config=machines_cfg)
    logger.info("feature_cols=%d", len(meta.feature_cols))

    logger.info("[3] 時系列 split")
    train_df, valid_df = time_split(feat_df, valid_days=args.valid_days)
    train_df = train_df.assign(split="train")
    valid_df = valid_df.assign(split="valid")
    full = pd.concat([train_df, valid_df], ignore_index=True)

    _print_summary(full, train_df, valid_df, meta)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1024 / 1024
    logger.info("[OK] parquet 保存: %s (%.1f MB)", out_path, size_mb)

    # === 重要: feature_cols とメタ情報を JSON サイドカーで保存 ===
    meta_path = out_path.with_suffix(".meta.json")
    meta_payload = {
        "feature_cols": meta.feature_cols,
        "target_diff_col": meta.target_diff_col,
        "target_win_col": meta.target_win_col,
        "machine_dummy_cols": meta.machine_dummy_cols,
        "shop_dummy_cols": meta.shop_dummy_cols,
        "history_cols": meta.history_cols,
        "shop_ids": meta.shop_ids,
        "n_features": len(meta.feature_cols),
    }
    meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[OK] meta 保存: %s (feature_cols=%d)", meta_path, len(meta.feature_cols))
    return 0


def _print_summary(full, train_df, valid_df, meta) -> None:
    print()
    print("=" * 60)
    print("[DATASET SUMMARY]")
    print("=" * 60)
    print(f"  全行数        : {len(full)}")
    print(f"  店舗数        : {full['shop_id'].nunique()}")
    print(f"  日付範囲      : {full['date'].min()} 〜 {full['date'].max()}")
    print(f"  特徴量列数    : {len(meta.feature_cols)}")
    print(f"    内訳        : 当日派生7 + 機種dummy{len(meta.machine_dummy_cols)} + 店舗dummy{len(meta.shop_dummy_cols)} + 履歴{len(meta.history_cols)}")
    print(f"  train rows    : {len(train_df)}")
    print(f"  valid rows    : {len(valid_df)}")
    print(f"  train target_win 率: {train_df['target_win'].mean():.3f}")
    print(f"  valid target_win 率: {valid_df['target_win'].mean():.3f}")
    print()
    print("=== 機種別 行数 (上位 10) ===")
    counts = full["machine_name"].value_counts().head(10)
    for name, n in counts.items():
        print(f"  {name:30s} {n}")
    print()


if __name__ == "__main__":
    sys.exit(main())
