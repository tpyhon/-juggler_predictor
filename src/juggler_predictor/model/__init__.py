"""ML モデル層。"""
from .dataset import load_dataset_from_local, load_dataset_from_r2
from .features import FeatureMeta, TARGET_DIFF_THRESHOLD, build_features
from .history import HISTORY_FEATURE_COLS, add_history_features
from .split import time_split
from .train import TrainResult, train_models
from .bundle import ModelBundle, load_bundle, save_bundle
from .metrics import expected_topk_diff, precision_at_k

__all__ = [
    "load_dataset_from_r2", "load_dataset_from_local",
    "build_features", "FeatureMeta", "TARGET_DIFF_THRESHOLD",
    "add_history_features", "HISTORY_FEATURE_COLS",
    "time_split",
    "TrainResult", "train_models",
    "ModelBundle", "save_bundle", "load_bundle",
    "precision_at_k", "expected_topk_diff",
]


# Phase 1: Note 記事生成パイプライン
from juggler_predictor.model.setting_estimator import (  # noqa: F401,E402
    estimate_setting,
    load_juggler_specs,
    parse_composite_prob,
)
from juggler_predictor.model.score import (  # noqa: F401,E402
    base100_to_stars,
    compute_base100,
    compute_diff01,
    compute_p4,
    compute_score_a,
)
