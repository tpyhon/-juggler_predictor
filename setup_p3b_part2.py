# setup_p3b_part2.py
"""P3b Part 2: LightGBM 回帰＋分類モデル学習＆joblibバンドル"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ===== src/juggler_predictor/model/train.py =====
FILES["src/juggler_predictor/model/train.py"] = '''"""LightGBM 回帰＋分類モデル学習。

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
'''

# ===== src/juggler_predictor/model/bundle.py =====
FILES["src/juggler_predictor/model/bundle.py"] = '''"""モデルバンドル保存/ロード (joblib)。"""
from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass
from typing import Any

import joblib

logger = logging.getLogger(__name__)

BUNDLE_VERSION = "1.0"


@dataclass
class ModelBundle:
    regressor: Any
    classifier_calibrated: Any
    feature_cols: list[str]
    metrics: dict[str, Any]
    trained_at: str
    version: str = BUNDLE_VERSION
    extra: dict[str, Any] | None = None


def save_bundle(bundle: ModelBundle, path: str | pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "regressor": bundle.regressor,
        "classifier_calibrated": bundle.classifier_calibrated,
        "feature_cols": bundle.feature_cols,
        "metrics": bundle.metrics,
        "trained_at": bundle.trained_at,
        "version": bundle.version,
        "extra": bundle.extra or {},
    }
    joblib.dump(payload, p)
    logger.info("model bundle saved: %s", p)
    return p


def load_bundle(path: str | pathlib.Path) -> ModelBundle:
    p = pathlib.Path(path)
    payload = joblib.load(p)
    return ModelBundle(
        regressor=payload["regressor"],
        classifier_calibrated=payload["classifier_calibrated"],
        feature_cols=payload["feature_cols"],
        metrics=payload.get("metrics", {}),
        trained_at=payload.get("trained_at", ""),
        version=payload.get("version", BUNDLE_VERSION),
        extra=payload.get("extra", {}),
    )
'''

# ===== src/juggler_predictor/model/__init__.py 更新 =====
FILES["src/juggler_predictor/model/__init__.py"] = '''"""ML モデル層。"""
from .dataset import load_dataset_from_local, load_dataset_from_r2
from .features import FeatureMeta, TARGET_DIFF_THRESHOLD, build_features
from .split import time_split
from .train import TrainResult, train_models
from .bundle import ModelBundle, load_bundle, save_bundle

__all__ = [
    "load_dataset_from_r2",
    "load_dataset_from_local",
    "build_features",
    "FeatureMeta",
    "TARGET_DIFF_THRESHOLD",
    "time_split",
    "TrainResult",
    "train_models",
    "ModelBundle",
    "save_bundle",
    "load_bundle",
]
'''

# ===== scripts/train.py =====
FILES["scripts/train.py"] = '''"""学習 CLI: parquet 読み込み → train/valid 分割 → 学習 → bundle 保存。"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import pandas as pd
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from juggler_predictor.common.logging import setup_logging  # noqa: E402
from juggler_predictor.model import (  # noqa: E402
    ModelBundle,
    save_bundle,
    train_models,
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default=str(ROOT / "data" / "dataset.parquet"))
    parser.add_argument("--out", default=str(ROOT / "models" / "model_bundle.joblib"))
    parser.add_argument("--valid-days", type=int, default=7)
    args = parser.parse_args()

    load_dotenv()
    setup_logging()

    parquet_path = pathlib.Path(args.parquet)
    if not parquet_path.exists():
        logger.error("parquet not found: %s (先に build_dataset.py を実行してください)", parquet_path)
        return 1

    logger.info("[1] parquet 読み込み: %s", parquet_path)
    df = pd.read_parquet(parquet_path)
    logger.info("rows=%d cols=%d", len(df), len(df.columns))

    # split 列の存在確認
    if "split" not in df.columns:
        logger.error("split 列が parquet にありません。build_dataset.py で split 列を保存してください。")
        return 1

    train_df = df[df["split"] == "train"].reset_index(drop=True)
    valid_df = df[df["split"] == "valid"].reset_index(drop=True)
    logger.info("train=%d valid=%d", len(train_df), len(valid_df))

    # feature_cols は parquet の attrs 経由ではなく、保存時に列リストとして埋め込む or 推定
    # ここでは命名規則で抽出: g_count, bb, rb, *_rate, bb_per_rb, is_*
    feature_cols = _infer_feature_cols(df)
    logger.info("feature_cols=%d", len(feature_cols))

    logger.info("[2] 学習")
    result = train_models(train_df, valid_df, feature_cols)

    logger.info("[3] バンドル保存")
    bundle = ModelBundle(
        regressor=result.regressor,
        classifier_calibrated=result.classifier_calibrated,
        feature_cols=result.feature_cols,
        metrics=result.metrics,
        trained_at=result.trained_at,
    )
    out_path = save_bundle(bundle, args.out)

    _print_summary(result, out_path)
    return 0


def _infer_feature_cols(df: pd.DataFrame) -> list[str]:
    base = [c for c in ("g_count", "bb", "rb", "bb_rate", "rb_rate", "total_rate", "bb_per_rb") if c in df.columns]
    dummies = [c for c in df.columns if c.startswith("is_")]
    return base + dummies


def _print_summary(result, out_path: pathlib.Path) -> None:
    m = result.metrics
    print()
    print("=" * 60)
    print("[TRAIN SUMMARY]")
    print("=" * 60)
    print(f"  trained_at        : {result.trained_at}")
    print(f"  feature_cols      : {len(result.feature_cols)}")
    print(f"  valid_rows        : {m['valid_rows']}")
    print(f"  valid_win_rate    : {m['valid_win_rate']:.3f}")
    print()
    print("  [Regression]")
    r = m["regression"]
    print(f"    RMSE            : {r['rmse']:.1f}")
    print(f"    MAE             : {r['mae']:.1f}")
    print(f"    R^2             : {r['r2']:.4f}")
    print(f"    best_iteration  : {r['best_iteration']}")
    print()
    print("  [Classification (raw)]")
    c = m["classification_raw"]
    print(f"    AUC             : {c['auc']:.4f}")
    print(f"    LogLoss         : {c['logloss']:.4f}")
    print(f"    Brier           : {c['brier']:.4f}")
    print(f"    best_iteration  : {c['best_iteration']}")
    print()
    print("  [Classification (calibrated)]")
    c2 = m["classification_calibrated"]
    print(f"    AUC             : {c2['auc']:.4f}")
    print(f"    LogLoss         : {c2['logloss']:.4f}")
    print(f"    Brier           : {c2['brier']:.4f}")
    print()
    print(f"  bundle saved      : {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
'''

# ===== scripts/build_dataset.py 更新 (split 列を parquet に書き込む) =====
FILES["scripts/build_dataset.py"] = '''"""dataset 構築 CLI: R2 から読み込み → 特徴量 → split → parquet 保存。"""
from __future__ import annotations

import argparse
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

    logger.info("[2] 特徴量生成")
    feat_df, meta = build_features(df, machines_config=machines_cfg)
    logger.info("feature_cols=%d", len(meta.feature_cols))
    juggler_mask = feat_df[meta.machine_dummy_cols].sum(axis=1) > 0
    logger.info("juggler 行 (machine_dummy のいずれかが 1): %d / 全 %d", int(juggler_mask.sum()), len(feat_df))

    logger.info("[3] 時系列 split")
    train_df, valid_df = time_split(feat_df, valid_days=args.valid_days)
    train_df = train_df.assign(split="train")
    valid_df = valid_df.assign(split="valid")
    full = pd.concat([train_df, valid_df], ignore_index=True)

    _print_summary(full, train_df, valid_df, meta)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # date_dt は parquet で datetime64 になるので OK。Float64 などは pyarrow で扱える
    full.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1024 / 1024
    logger.info("[OK] parquet 保存: %s (%.0f MB)", out_path, size_mb)
    return 0


def _print_summary(full: pd.DataFrame, train_df: pd.DataFrame, valid_df: pd.DataFrame, meta) -> None:
    print()
    print("=" * 60)
    print("[DATASET SUMMARY]")
    print("=" * 60)
    print(f"  全行数        : {len(full)}")
    print(f"  店舗数        : {full['shop_id'].nunique()}")
    print(f"  日付範囲      : {full['date'].min()} 〜 {full['date'].max()}")
    print(f"  特徴量列数    : {len(meta.feature_cols)}")
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

# ===== tests/test_model_train.py =====
FILES["tests/test_model_train.py"] = '''"""LightGBM 学習 + bundle 保存/ロード test (小サンプル)。"""
from __future__ import annotations

import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest

from juggler_predictor.model import (
    ModelBundle,
    load_bundle,
    save_bundle,
    train_models,
)


def _make_synthetic_df(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    g = rng.integers(3000, 9000, size=n)
    bb = rng.integers(5, 50, size=n)
    rb = rng.integers(5, 50, size=n)
    # diff は g, bb, rb に依存 + ノイズ
    diff = (bb * 250 + rb * 100 - g * 0.3 + rng.normal(0, 500, size=n)).astype(int)
    df = pd.DataFrame({
        "g_count": g,
        "bb": bb,
        "rb": rb,
        "bb_rate": bb / g,
        "rb_rate": rb / g,
        "total_rate": (bb + rb) / g,
        "bb_per_rb": bb / np.where(rb > 0, rb, 1),
        "is_machine_a": rng.integers(0, 2, size=n).astype(np.int8),
        "is_machine_b": rng.integers(0, 2, size=n).astype(np.int8),
        "target_diff": diff.astype(float),
        "target_win": (diff > 1000).astype(int),
    })
    return df


FEATURE_COLS = [
    "g_count", "bb", "rb", "bb_rate", "rb_rate", "total_rate", "bb_per_rb",
    "is_machine_a", "is_machine_b",
]


def test_train_models_runs_and_returns_metrics():
    train_df = _make_synthetic_df(800, seed=1)
    valid_df = _make_synthetic_df(200, seed=2)

    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)

    assert result.regressor is not None
    assert result.classifier_calibrated is not None
    assert "regression" in result.metrics
    assert "classification_raw" in result.metrics
    assert "classification_calibrated" in result.metrics

    # メトリクスが妥当な範囲
    r = result.metrics["regression"]
    assert r["rmse"] > 0
    assert r["mae"] > 0
    # diff は ±数千のレンジ → RMSE は 100〜5000
    assert 50 < r["rmse"] < 10000


def test_train_classifier_predict_proba_in_range():
    train_df = _make_synthetic_df(800, seed=3)
    valid_df = _make_synthetic_df(200, seed=4)
    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)

    X = valid_df[FEATURE_COLS].astype(float).to_numpy()
    proba = result.classifier_calibrated.predict_proba(X)[:, 1]
    assert proba.shape == (len(valid_df),)
    assert (proba >= 0).all() and (proba <= 1).all()


def test_bundle_save_and_load_roundtrip():
    train_df = _make_synthetic_df(400, seed=5)
    valid_df = _make_synthetic_df(100, seed=6)
    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)

    bundle = ModelBundle(
        regressor=result.regressor,
        classifier_calibrated=result.classifier_calibrated,
        feature_cols=result.feature_cols,
        metrics=result.metrics,
        trained_at=result.trained_at,
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "bundle.joblib"
        save_bundle(bundle, path)
        assert path.exists()

        loaded = load_bundle(path)
        assert loaded.feature_cols == bundle.feature_cols
        assert loaded.version == "1.0"
        assert "regression" in loaded.metrics

        # 同じ予測が得られるか
        X = valid_df[FEATURE_COLS].astype(float).to_numpy()
        p1 = result.classifier_calibrated.predict_proba(X)[:, 1]
        p2 = loaded.classifier_calibrated.predict_proba(X)[:, 1]
        np.testing.assert_allclose(p1, p2)


def test_train_handles_small_classes():
    """片方のクラスがほとんど無い場合でもエラーで落ちないこと。"""
    df = _make_synthetic_df(400, seed=7)
    # 強制的に win=0 を多くする
    df.loc[df.index[:380], "target_win"] = 0
    df.loc[df.index[380:], "target_win"] = 1
    train_df = df.iloc[:300].copy()
    valid_df = df.iloc[300:].copy()
    # cv=2 で OK
    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)
    assert result.classifier_calibrated is not None
'''


def write_all() -> None:
    for rel, content in FILES.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"[WRITE] {p}")
    print()
    print(f"[SUCCESS] {len(FILES)} files written")
    print()
    print("次のコマンド:")
    print("  uv add lightgbm scikit-learn joblib")
    print("  uv run pytest -v")
    print("  uv run python scripts/build_dataset.py   # split 列付き parquet を再生成")
    print("  uv run python scripts/train.py           # 学習＆ bundle 保存")


if __name__ == "__main__":
    write_all()
