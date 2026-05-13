"""設定期待度分類器 (multiclass) の学習スクリプト。

既存 model_bundle.joblib に setting_classifier キーを追加して保存する。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping, log_evaluation
from sklearn.metrics import accuracy_score, roc_auc_score

from juggler_predictor.model import time_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dataset.parquet"
BUNDLE = ROOT / "models" / "model_bundle.joblib"
META = ROOT / "models" / "setting_classifier_meta.json"


def main() -> None:
    if not DATA.exists():
        raise FileNotFoundError(f"dataset.parquet not found: {DATA}")
    if not BUNDLE.exists():
        raise FileNotFoundError(f"model_bundle.joblib not found: {BUNDLE}")

    df = pd.read_parquet(DATA)
    logger.info("dataset rows=%d cols=%d", len(df), len(df.columns))

    if "y_setting_next" not in df.columns:
        raise KeyError(
            "y_setting_next 列がありません。build_dataset.py を再実行してください。"
        )

    bundle = joblib.load(BUNDLE)
    feature_cols = list(bundle["feature_cols"])
    # prev_setting, prev_p_high を追加
    extra = [c for c in ("prev_setting", "prev_p_high") if c in df.columns and c not in feature_cols]
    feat_setting = feature_cols + extra
    logger.info("setting features = %d (base %d + extra %d)", len(feat_setting), len(feature_cols), len(extra))

    df_train, df_valid = time_split(df)
    df_train = df_train.dropna(subset=["y_setting_next"]).copy()
    df_valid = df_valid.dropna(subset=["y_setting_next"]).copy()

    X_train = df_train[feat_setting].astype(float).values
    X_valid = df_valid[feat_setting].astype(float).values
    y_train = df_train["y_setting_next"].astype(int).values
    y_valid = df_valid["y_setting_next"].astype(int).values

    logger.info("train rows=%d valid rows=%d", len(y_train), len(y_valid))
    logger.info("train class dist: %s", np.bincount(y_train, minlength=7)[1:].tolist())
    logger.info("valid class dist: %s", np.bincount(y_valid, minlength=7)[1:].tolist())

    # LightGBM は 0-indexed クラスを期待
    y_train0 = y_train - 1
    y_valid0 = y_valid - 1

    clf = LGBMClassifier(
        objective="multiclass",
        num_class=6,
        class_weight="balanced",
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=20,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        n_jobs=-1,
    )

    clf.fit(
        X_train,
        y_train0,
        eval_set=[(X_valid, y_valid0)],
        callbacks=[early_stopping(30), log_evaluation(50)],
    )

    proba = clf.predict_proba(X_valid)
    pred0 = proba.argmax(axis=1)
    acc = accuracy_score(y_valid0, pred0)

    # one-vs-rest macro AUC
    aucs = []
    for k in range(6):
        y_bin = (y_valid0 == k).astype(int)
        if y_bin.sum() == 0 or y_bin.sum() == len(y_bin):
            continue
        aucs.append(roc_auc_score(y_bin, proba[:, k]))
    macro_auc = float(np.mean(aucs)) if aucs else float("nan")

    p_high = proba[:, 3:].sum(axis=1)
    p_top = proba[:, 4:].sum(axis=1)
    high_actual = (y_valid >= 4).astype(int)
    auc_high = roc_auc_score(high_actual, p_high) if high_actual.sum() > 0 else float("nan")

    # P@5 per shop-date
    p5_list = []
    df_valid = df_valid.assign(p_high=p_high, high_actual=high_actual)
    for (sid, d), g in df_valid.groupby(["shop_id", "date"]):
        if len(g) < 5:
            continue
        top5 = g.nlargest(5, "p_high")
        p5_list.append(top5["high_actual"].mean())
    p_at_5 = float(np.mean(p5_list)) if p5_list else float("nan")

    logger.info("=== SETTING CLASSIFIER METRICS ===")
    logger.info("Top-1 accuracy : %.4f (random=0.1667)", acc)
    logger.info("Macro AUC (OvR): %.4f", macro_auc)
    logger.info("AUC (p_high)   : %.4f", auc_high)
    logger.info("P@5 (high)     : %.4f", p_at_5)
    logger.info("best iteration : %s", clf.best_iteration_)

    if macro_auc < 0.55:
        logger.warning("Macro AUC < 0.55: 設定予測の精度が低いため Phase 5 で特徴量改善検討。")

    bundle["setting_classifier"] = clf
    bundle["setting_features"] = feat_setting
    joblib.dump(bundle, BUNDLE)
    logger.info("setting_classifier saved into %s", BUNDLE)

    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(
        json.dumps(
            {
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "n_train": int(len(y_train)),
                "n_valid": int(len(y_valid)),
                "best_iteration": int(clf.best_iteration_ or 0),
                "top1_accuracy": float(acc),
                "macro_auc_ovr": float(macro_auc),
                "auc_p_high": float(auc_high),
                "p_at_5_high": float(p_at_5),
                "features": feat_setting,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("meta saved: %s", META)


if __name__ == "__main__":
    main()
