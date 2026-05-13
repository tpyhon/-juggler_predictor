"""LightGBM 学習 + bundle 保存/ロード test (小サンプル)。"""
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
    """片方のクラスが極端に少ない不均衡データでもエラーで落ちないこと。

    train/valid ともに両クラスを含むようにシャッフルしてから分割する。
    """
    import numpy as np

    df = _make_synthetic_df(400, seed=7)
    # 強制的に不均衡にする (約 95% を win=0、5% を win=1)
    df["target_win"] = 0
    rng = np.random.default_rng(42)
    win_idx = rng.choice(df.index, size=20, replace=False)
    df.loc[win_idx, "target_win"] = 1

    # シャッフルして両クラスが train/valid 両方に入るようにする
    df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
    train_df = df.iloc[:300].copy()
    valid_df = df.iloc[300:].copy()

    # 両方に両クラスが存在することを確認 (テスト前提)
    assert train_df["target_win"].nunique() == 2
    assert valid_df["target_win"].nunique() == 2

    # cv=2 で学習が走り、エラーで落ちないこと
    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)
    assert result.classifier_calibrated is not None
