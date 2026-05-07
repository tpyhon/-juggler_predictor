# setup_p3b_part2_7_fix.py
"""feature_cols を parquet サイドカー JSON で保存・読み込みする方式に変更。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

# ===== scripts/build_dataset.py 更新 (feature_cols を JSON で保存) =====
BUILD_DATASET = '''"""dataset 構築 CLI: R2 → 履歴特徴量 → split → parquet + meta JSON 保存。"""
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
'''

# ===== scripts/train.py 更新 (meta JSON から feature_cols 読み込み) =====
TRAIN_PY = '''"""学習 CLI: parquet + meta.json 読み込み → 学習 → bundle 保存。"""
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
    logger.info("train=%d valid=%d", len(train_df), len(valid_df))

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
'''


def main():
    files = {
        "scripts/build_dataset.py": BUILD_DATASET,
        "scripts/train.py": TRAIN_PY,
    }
    for rel, content in files.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"[WRITE] {p}")
    print()
    print(f"[SUCCESS] {len(files)} files updated")


if __name__ == "__main__":
    main()
