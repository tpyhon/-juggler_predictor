"""モデルバンドル保存/ロード (joblib)。"""
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
