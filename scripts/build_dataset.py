"""R2 から dataset を全件読み込み、サマリと parquet を出力する確認用スクリプト。

使い方:
    uv run python scripts/build_dataset.py
    uv run python scripts/build_dataset.py --shops kingsetagaya,messekichijoji
    uv run python scripts/build_dataset.py --output data/dataset.parquet
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR, DATA_DIR
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.model import (
    build_features,
    load_dataset_from_r2,
    time_split,
)
from juggler_predictor.storage import build_r2_client_from_env

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--shops", default="", help="カンマ区切りの店舗 id (空なら全店)")
    ap.add_argument("--output", default=str(DATA_DIR / "dataset.parquet"))
    ap.add_argument("--valid-days", type=int, default=7)
    args = ap.parse_args()

    shop_ids = [s.strip() for s in args.shops.split(",") if s.strip()] or None

    logger.info("[1] R2 から dataset 読み込み")
    r2 = build_r2_client_from_env()
    df = load_dataset_from_r2(r2, shop_ids=shop_ids)
    logger.info("rows=%d shops=%d dates=%d",
                len(df),
                df["shop_id"].nunique() if not df.empty else 0,
                df["date"].nunique() if not df.empty else 0)
    if df.empty:
        logger.error("dataset が空です。bootstrap を先に実行してください。")
        return 1

    logger.info("[2] 特徴量生成")
    machines_cfg = yaml.safe_load((CONFIG_DIR / "machines.yaml").read_text(encoding="utf-8"))
    feat_df, meta = build_features(df, machines_config=machines_cfg)
    logger.info("feature_cols=%d", len(meta.feature_cols))
    logger.info("juggler 行 (machine_dummy のいずれかが 1): %d / 全 %d",
                int(feat_df[meta.machine_dummy_cols].sum(axis=1).gt(0).sum()),
                len(feat_df))

    logger.info("[3] 時系列 split")
    train, valid = time_split(feat_df, valid_days=args.valid_days)

    print()
    print("=" * 60)
    print("[DATASET SUMMARY]")
    print("=" * 60)
    print(f"  全行数        : {len(feat_df)}")
    print(f"  店舗数        : {feat_df['shop_id'].nunique()}")
    print(f"  日付範囲      : {feat_df['date'].min()} 〜 {feat_df['date'].max()}")
    print(f"  特徴量列数    : {len(meta.feature_cols)}")
    print(f"  train rows    : {len(train)}")
    print(f"  valid rows    : {len(valid)}")
    if not train.empty:
        print(f"  train target_win 率: {train['target_win'].mean():.3f}")
    if not valid.empty:
        print(f"  valid target_win 率: {valid['target_win'].mean():.3f}")
    print()
    print("=== 機種別 行数 (上位 10) ===")
    counts = feat_df["machine_name"].value_counts().head(10)
    for name, n in counts.items():
        print(f"  {name:30s}  {n}")
    print()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    feat_df.to_parquet(out_path, index=False)
    logger.info("[OK] parquet 保存: %s (%d MB)",
                out_path, out_path.stat().st_size // (1024 * 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
