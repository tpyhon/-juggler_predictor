"""学習 CLI: parquet + meta.json 読み込み → 学習 → bundle 保存。"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import mean_squared_error, roc_auc_score

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from juggler_predictor.common.logging import setup_logging  # noqa: E402
from juggler_predictor.model import (  # noqa: E402
    ModelBundle, expected_topk_diff, precision_at_k, save_bundle, train_models,
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default=str(ROOT / "data" / "dataset.parquet"))
    parser.add_argument("--out", default=str(ROOT / "models" / "model_bundle.joblib"))
    args = parser.parse_args()

    load_dotenv()
    setup_logging()

    parquet_path = pathlib.Path(args.parquet)
    meta_path = parquet_path.with_suffix(".meta.json")

    if not parquet_path.exists():
        logger.error("parquet not found: %s", parquet_path)
        return 1
    if not meta_path.exists():
        logger.error("meta not found: %s (build_dataset.py を再実行してください)", meta_path)
        return 1

    logger.info("[1] parquet + meta 読み込み")
    df = pd.read_parquet(parquet_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    feature_cols: list[str] = meta["feature_cols"]
    logger.info("rows=%d feature_cols=%d", len(df), len(feature_cols))

    if "split" not in df.columns:
        logger.error("split 列が parquet にありません。")
        return 1

    train_df = df[df["split"] == "train"].reset_index(drop=True)
    valid_df = df[df["split"] == "valid"].reset_index(drop=True)
    logger.info("train=%d valid=%d (NaN 除外前)", len(train_df), len(valid_df))

    # target_diff / target_win が NaN の行を除外（推論専用行が混ざっているため）
    before_train = len(train_df)
    before_valid = len(valid_df)
    train_df = train_df.dropna(subset=["target_diff", "target_win"]).reset_index(drop=True)
    valid_df = valid_df.dropna(subset=["target_diff", "target_win"]).reset_index(drop=True)
    logger.info(
        "NaN 除外後: train=%d (-%d) valid=%d (-%d)",
        len(train_df), before_train - len(train_df),
        len(valid_df), before_valid - len(valid_df),
    )


    # 欠損特徴量チェック
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        logger.error("parquet に存在しない feature_cols: %s", missing)
        return 1

    logger.info("[2] 学習")
    # 履歴特徴量に NaN があると LightGBM が落ちるので前処理
    for col in feature_cols:
        if df[col].dtype.kind in "fc":  # float, complex
            train_df[col] = train_df[col].astype(float)
            valid_df[col] = valid_df[col].astype(float)

    result = train_models(train_df, valid_df, feature_cols)

    logger.info("[3] バンドル保存")
    bundle = ModelBundle(
        regressor=result.regressor,
        classifier_calibrated=result.classifier_calibrated,
        feature_cols=result.feature_cols,
        metrics=result.metrics,
        trained_at=result.trained_at,
        extra={
            "shop_ids": meta.get("shop_ids", []),
            "machine_dummy_cols": meta.get("machine_dummy_cols", []),
            "shop_dummy_cols": meta.get("shop_dummy_cols", []),
            "history_cols": meta.get("history_cols", []),
        },
    )
    out_path = save_bundle(bundle, args.out)

    _print_summary(result, out_path, meta)
    _print_per_shop(result, valid_df, feature_cols)
    _print_feature_importance(result, feature_cols)
    return 0


def _print_summary(result, out_path, meta) -> None:
    m = result.metrics
    print()
    print("=" * 60)
    print("[TRAIN SUMMARY]")
    print("=" * 60)
    print(f"  trained_at        : {result.trained_at}")
    print(f"  feature_cols      : {len(result.feature_cols)}")
    print(f"    内訳            : 当日7 + 機種{len(meta.get('machine_dummy_cols', []))} "
          f"+ 店舗{len(meta.get('shop_dummy_cols', []))} + 履歴{len(meta.get('history_cols', []))}")
    print(f"  valid_rows        : {m['valid_rows']}")
    print(f"  valid_win_rate    : {m['valid_win_rate']:.3f}")
    print()
    print("  [Regression (next-day diff)]")
    r = m["regression"]
    print(f"    RMSE            : {r['rmse']:.1f}")
    print(f"    MAE             : {r['mae']:.1f}")
    print(f"    R^2             : {r['r2']:.4f}")
    print(f"    best_iteration  : {r['best_iteration']}")
    print()
    print("  [Classification raw]")
    c = m["classification_raw"]
    print(f"    AUC             : {c['auc']:.4f}")
    print(f"    LogLoss         : {c['logloss']:.4f}")
    print(f"    Brier           : {c['brier']:.4f}")
    print()
    print("  [Classification calibrated]")
    c2 = m["classification_calibrated"]
    print(f"    AUC             : {c2['auc']:.4f}")
    print(f"    LogLoss         : {c2['logloss']:.4f}")
    print(f"    Brier           : {c2['brier']:.4f}")
    print()
    print(f"  bundle saved      : {out_path}")
    print("=" * 60)


def _print_per_shop(result, valid_df, feature_cols) -> None:
    if "shop_id" not in valid_df.columns:
        return
    X = valid_df[feature_cols].astype(float).to_numpy()
    pred_diff = result.regressor.predict(X)
    proba = result.classifier_calibrated.predict_proba(X)[:, 1]
    y_diff = valid_df["target_diff"].astype(float).to_numpy()
    y_win = valid_df["target_win"].astype(int).to_numpy()

    print()
    print("=" * 60)
    print("[Per-shop validation metrics]")
    print("=" * 60)
    print(f"  {'shop_id':<25s} {'n':>5s} {'RMSE':>7s} {'AUC':>6s} {'P@5':>6s} {'TopDiff':>8s}")
    print("  " + "-" * 60)

    for sid in sorted(valid_df["shop_id"].unique()):
        mask = (valid_df["shop_id"] == sid).to_numpy()
        n = int(mask.sum())
        if n < 30:
            print(f"  {sid:<25s} {n:>5d} (skipped: n<30)")
            continue
        rmse = float(np.sqrt(mean_squared_error(y_diff[mask], pred_diff[mask])))
        try:
            auc = float(roc_auc_score(y_win[mask], proba[mask]))
        except ValueError:
            auc = float("nan")
        p5 = precision_at_k(y_win[mask], proba[mask], k=5)
        top_diff = expected_topk_diff(y_diff[mask], proba[mask], k=5)
        print(f"  {sid:<25s} {n:>5d} {rmse:>7.0f} {auc:>6.3f} {p5:>6.3f} {top_diff:>8.0f}")
    print("=" * 60)


def _print_feature_importance(result, feature_cols) -> None:
    """LightGBM Classifier (raw) の feature_importance を表示。"""
    clf = result.classifier_raw
    importances = clf.feature_importances_  # gain ベース
    pairs = sorted(zip(feature_cols, importances), key=lambda x: -x[1])
    print()
    print("=" * 60)
    print("[Feature Importance Top 20 (classifier_raw)]")
    print("=" * 60)
    for name, imp in pairs[:20]:
        print(f"  {name:<35s} {imp:>8.0f}")
    print()
    # 履歴特徴量がトップ20に入った数
    history_in_top20 = sum(
        1 for name, _ in pairs[:20]
        if name.startswith(("unit_", "sm_", "shop_total_", "shop_win_", "dow", "is_weekend",
                            "is_month_", "day_has_"))
    )
    print(f"  ※ 履歴系特徴量が Top20 に占める数: {history_in_top20}/20")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
