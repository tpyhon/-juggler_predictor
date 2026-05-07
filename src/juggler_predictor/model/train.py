"""LightGBM 回帰＋分類モデル学習。

設計:
    - regressor: LightGBM Regressor で target_diff を予測
    - classifier: LightGBM Classifier で target_win を予測 → CalibratedClassifierCV で較正
    - early stopping は LightGBM の callback で valid set 指定
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor, early_stopping, log_evaluation
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

logger = logging.getLogger(__name__)

DEFAULT_LGBM_PARAMS: dict[str, Any] = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 20,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}

EARLY_STOPPING_ROUNDS = 30


@dataclass
class TrainResult:
    regressor: LGBMRegressor
    classifier_calibrated: CalibratedClassifierCV
    classifier_raw: LGBMClassifier
    feature_cols: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)
    trained_at: str = ""


def train_models(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    target_diff_col: str = "target_diff",
    target_win_col: str = "target_win",
    lgbm_params: dict[str, Any] | None = None,
    calibration_cv: int = 5,
) -> TrainResult:
    """train/valid DataFrame から回帰＋較正済み分類モデルを学習。"""
    params = {**DEFAULT_LGBM_PARAMS, **(lgbm_params or {})}

    X_train = train_df[feature_cols].astype(float).to_numpy()
    X_valid = valid_df[feature_cols].astype(float).to_numpy()

    y_train_diff = train_df[target_diff_col].astype(float).to_numpy()
    y_valid_diff = valid_df[target_diff_col].astype(float).to_numpy()
    y_train_win = train_df[target_win_col].astype(int).to_numpy()
    y_valid_win = valid_df[target_win_col].astype(int).to_numpy()

    # ----- 回帰モデル -----
    logger.info("[train] regressor learning rows=%d features=%d", len(X_train), len(feature_cols))
    regressor = LGBMRegressor(**params)
    regressor.fit(
        X_train,
        y_train_diff,
        eval_set=[(X_valid, y_valid_diff)],
        callbacks=[
            early_stopping(EARLY_STOPPING_ROUNDS, verbose=False),
            log_evaluation(0),
        ],
    )

    # ----- 分類モデル (raw) -----
    logger.info("[train] classifier raw learning")
    clf_raw = LGBMClassifier(**params)
    clf_raw.fit(
        X_train,
        y_train_win,
        eval_set=[(X_valid, y_valid_win)],
        callbacks=[
            early_stopping(EARLY_STOPPING_ROUNDS, verbose=False),
            log_evaluation(0),
        ],
    )

    # ----- 較正 (CalibratedClassifierCV) -----
    # 較正は train データのみで cv 分割して学習
    cv = min(calibration_cv, max(2, int(min(np.bincount(y_train_win))) // 2))
    logger.info("[train] calibrating classifier with cv=%d", cv)
    base_clf = LGBMClassifier(**{**params, "n_estimators": clf_raw.best_iteration_ or params["n_estimators"]})
    clf_calibrated = CalibratedClassifierCV(base_clf, method="isotonic", cv=cv)
    clf_calibrated.fit(X_train, y_train_win)

    # ----- メトリクス -----
    metrics = _compute_metrics(
        regressor=regressor,
        clf_raw=clf_raw,
        clf_calibrated=clf_calibrated,
        X_valid=X_valid,
        y_valid_diff=y_valid_diff,
        y_valid_win=y_valid_win,
    )

    return TrainResult(
        regressor=regressor,
        classifier_calibrated=clf_calibrated,
        classifier_raw=clf_raw,
        feature_cols=list(feature_cols),
        metrics=metrics,
        trained_at=datetime.now(timezone.utc).isoformat(),
    )


def _compute_metrics(
    *,
    regressor: LGBMRegressor,
    clf_raw: LGBMClassifier,
    clf_calibrated: CalibratedClassifierCV,
    X_valid: np.ndarray,
    y_valid_diff: np.ndarray,
    y_valid_win: np.ndarray,
) -> dict[str, Any]:
    pred_diff = regressor.predict(X_valid)
    proba_raw = clf_raw.predict_proba(X_valid)[:, 1]
    proba_cal = clf_calibrated.predict_proba(X_valid)[:, 1]

    rmse = float(np.sqrt(mean_squared_error(y_valid_diff, pred_diff)))
    mae = float(mean_absolute_error(y_valid_diff, pred_diff))
    r2 = float(r2_score(y_valid_diff, pred_diff))

    metrics: dict[str, Any] = {
        "regression": {
            "rmse": rmse,
            "mae": mae,
            "r2": r2,
            "best_iteration": int(getattr(regressor, "best_iteration_", 0) or 0),
        },
        "classification_raw": {
            "auc": _safe_auc(y_valid_win, proba_raw),
            "logloss": _safe_logloss(y_valid_win, proba_raw),
            "brier": float(brier_score_loss(y_valid_win, proba_raw)),
            "best_iteration": int(getattr(clf_raw, "best_iteration_", 0) or 0),
        },
        "classification_calibrated": {
            "auc": _safe_auc(y_valid_win, proba_cal),
            "logloss": _safe_logloss(y_valid_win, proba_cal),
            "brier": float(brier_score_loss(y_valid_win, proba_cal)),
        },
        "valid_rows": int(len(y_valid_win)),
        "valid_win_rate": float(np.mean(y_valid_win)),
    }
    return metrics


def _safe_auc(y_true: np.ndarray, proba: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, proba))


def _safe_logloss(y_true: np.ndarray, proba: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return float("nan")
    eps = 1e-7
    proba_clipped = np.clip(proba, eps, 1 - eps)
    return float(log_loss(y_true, proba_clipped, labels=[0, 1]))
