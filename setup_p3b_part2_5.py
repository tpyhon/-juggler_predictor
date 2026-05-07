# setup_p3b_part2_5.py
"""P3b Part 2.5: リーク修正(target=翌日diff) + 店舗ダミー追加 + per-shopメトリクス"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ===== src/juggler_predictor/model/features.py =====
FILES["src/juggler_predictor/model/features.py"] = '''"""dataset DataFrame を学習用特徴量に変換する。

設計 (P3b Part 2.5 リーク修正版):
    - target_diff: **翌日**同じ台 (shop_id, unit_number, machine_name) の diff
    - target_win:  翌日 diff > TARGET_DIFF_THRESHOLD なら 1, else 0
    - shop dummy: 18店舗のうち先頭1つをベースに残り17列を one-hot
    - machine dummy: machines.yaml の canonical で one-hot
    - 履歴特徴量は P4 で追加
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TARGET_DIFF_THRESHOLD = 1000  # diff > 1000 で勝ち扱い


@dataclass(frozen=True)
class FeatureMeta:
    feature_cols: list[str]
    target_diff_col: str
    target_win_col: str
    machine_dummy_cols: list[str]
    shop_dummy_cols: list[str]
    shop_ids: list[str]  # 学習時の店舗リスト (予測時の整合性のため)


def _canonical_set(machines_config: dict) -> list[str]:
    return [m["canonical"] for m in machines_config.get("machines", []) if "canonical" in m]


def build_features(
    df: pd.DataFrame,
    *,
    machines_config: dict,
    shop_ids: list[str] | None = None,
    drop_na_target: bool = True,
) -> tuple[pd.DataFrame, FeatureMeta]:
    """dataset DataFrame に特徴量列とターゲット列を追加して返す。

    引数:
        df: dataset DataFrame (shop_id, date, machine_name, unit_number, g_count, diff, bb, rb)
        machines_config: machines.yaml をパースした dict
        shop_ids: 学習時に存在した店舗ID一覧 (予測時に渡すと欠損列を 0 で埋める)。
                  None なら df から自動抽出。
        drop_na_target: target_diff が NaN の行を除外するか
    """
    if df.empty:
        meta = FeatureMeta(
            feature_cols=[], target_diff_col="target_diff", target_win_col="target_win",
            machine_dummy_cols=[], shop_dummy_cols=[], shop_ids=[],
        )
        return df.copy(), meta

    out = df.copy()

    # 数値整形
    for col in ("g_count", "diff", "bb", "rb", "art"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 派生特徴量 (当日)
    g = out["g_count"].astype("Float64")
    bb = out["bb"].astype("Float64")
    rb = out["rb"].astype("Float64")
    out["bb_rate"] = (bb / g).where(g > 0)
    out["rb_rate"] = (rb / g).where(g > 0)
    out["total_rate"] = ((bb + rb) / g).where(g > 0)
    out["bb_per_rb"] = (bb / rb).where(rb > 0)

    # 機種 one-hot
    canonicals = _canonical_set(machines_config)
    for name in canonicals:
        col = _machine_dummy_col(name)
        out[col] = (out["machine_name"] == name).astype(np.int8)
    machine_dummy_cols = [_machine_dummy_col(n) for n in canonicals]

    # 店舗 one-hot (ベースカテゴリは先頭店舗、残り 17 列を one-hot)
    if shop_ids is None:
        shop_ids_used = sorted(out["shop_id"].dropna().unique().tolist())
    else:
        shop_ids_used = list(shop_ids)
    shop_dummy_cols: list[str] = []
    if len(shop_ids_used) >= 2:
        for sid in shop_ids_used[1:]:  # 先頭をベースカテゴリにする
            col = _shop_dummy_col(sid)
            out[col] = (out["shop_id"] == sid).astype(np.int8)
            shop_dummy_cols.append(col)

    # date 列を datetime 化
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")

    # ===== ターゲット (翌日 diff) =====
    # (shop_id, unit_number, machine_name) でグループ化し、日付昇順で shift(-1)
    out = out.sort_values(["shop_id", "unit_number", "machine_name", "date_dt"]).reset_index(drop=True)
    out["target_diff"] = (
        out.groupby(["shop_id", "unit_number", "machine_name"])["diff"]
        .shift(-1)
        .astype("Float64")
    )

    # 翌日 target が NaN の行を除外 (各台の最終日 + 機種入替日)
    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除外 (各台の最終日/機種入替)", dropped)

    out["target_win"] = (
        (out["target_diff"] > TARGET_DIFF_THRESHOLD).fillna(False).astype(np.int8)
    )

    feature_cols: list[str] = [
        "g_count", "bb", "rb",
        "bb_rate", "rb_rate", "total_rate", "bb_per_rb",
        *machine_dummy_cols,
        *shop_dummy_cols,
    ]

    meta = FeatureMeta(
        feature_cols=feature_cols,
        target_diff_col="target_diff",
        target_win_col="target_win",
        machine_dummy_cols=machine_dummy_cols,
        shop_dummy_cols=shop_dummy_cols,
        shop_ids=shop_ids_used,
    )
    return out, meta


def _machine_dummy_col(name: str) -> str:
    return f"is_{name}"


def _shop_dummy_col(shop_id: str) -> str:
    return f"is_shop_{shop_id}"
'''

# ===== src/juggler_predictor/model/metrics.py (新規: per-shop メトリクス用) =====
FILES["src/juggler_predictor/model/metrics.py"] = '''"""評価メトリクス補助関数。"""
from __future__ import annotations

import numpy as np


def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int = 5) -> float:
    """スコア上位 K 件の的中率。

    勝ち台ランキングの実用評価指標。
    K件未満なら NaN を返す。
    """
    y_true = np.asarray(y_true)
    scores = np.asarray(scores)
    if len(scores) < k or k <= 0:
        return float("nan")
    top_k_idx = np.argsort(scores)[::-1][:k]
    return float(np.mean(y_true[top_k_idx]))


def expected_topk_diff(y_diff: np.ndarray, scores: np.ndarray, k: int = 5) -> float:
    """スコア上位 K 件の実際の平均 diff。期待ROIの近似。"""
    y_diff = np.asarray(y_diff)
    scores = np.asarray(scores)
    if len(scores) < k or k <= 0:
        return float("nan")
    top_k_idx = np.argsort(scores)[::-1][:k]
    return float(np.mean(y_diff[top_k_idx]))
'''

# ===== src/juggler_predictor/model/__init__.py 更新 =====
FILES["src/juggler_predictor/model/__init__.py"] = '''"""ML モデル層。"""
from .dataset import load_dataset_from_local, load_dataset_from_r2
from .features import FeatureMeta, TARGET_DIFF_THRESHOLD, build_features
from .split import time_split
from .train import TrainResult, train_models
from .bundle import ModelBundle, load_bundle, save_bundle
from .metrics import expected_topk_diff, precision_at_k

__all__ = [
    "load_dataset_from_r2", "load_dataset_from_local",
    "build_features", "FeatureMeta", "TARGET_DIFF_THRESHOLD",
    "time_split",
    "TrainResult", "train_models",
    "ModelBundle", "save_bundle", "load_bundle",
    "precision_at_k", "expected_topk_diff",
]
'''

# ===== scripts/train.py (per-shop メトリクス追加) =====
FILES["scripts/train.py"] = '''"""学習 CLI: parquet 読み込み → train/valid 分割 → 学習 → bundle 保存。

Part 2.5: per-shop メトリクスと Precision@K を追加。
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import mean_absolute_error, mean_squared_error, roc_auc_score

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
    if not parquet_path.exists():
        logger.error("parquet not found: %s (先に build_dataset.py を実行してください)", parquet_path)
        return 1

    logger.info("[1] parquet 読み込み: %s", parquet_path)
    df = pd.read_parquet(parquet_path)
    logger.info("rows=%d cols=%d", len(df), len(df.columns))

    if "split" not in df.columns:
        logger.error("split 列が parquet にありません。build_dataset.py で split 列を保存してください。")
        return 1

    train_df = df[df["split"] == "train"].reset_index(drop=True)
    valid_df = df[df["split"] == "valid"].reset_index(drop=True)
    logger.info("train=%d valid=%d", len(train_df), len(valid_df))

    feature_cols = _infer_feature_cols(df)
    logger.info("feature_cols=%d (machine_dummy + shop_dummy 含む)", len(feature_cols))

    logger.info("[2] 学習")
    result = train_models(train_df, valid_df, feature_cols)

    logger.info("[3] バンドル保存")
    bundle = ModelBundle(
        regressor=result.regressor,
        classifier_calibrated=result.classifier_calibrated,
        feature_cols=result.feature_cols,
        metrics=result.metrics,
        trained_at=result.trained_at,
        extra={"shop_ids": sorted(df["shop_id"].unique().tolist())},
    )
    out_path = save_bundle(bundle, args.out)

    _print_summary(result, out_path)
    _print_per_shop(result, valid_df, feature_cols)
    return 0


def _infer_feature_cols(df: pd.DataFrame) -> list[str]:
    base = [c for c in ("g_count", "bb", "rb", "bb_rate", "rb_rate", "total_rate", "bb_per_rb") if c in df.columns]
    machine_dummies = [c for c in df.columns if c.startswith("is_") and not c.startswith("is_shop_")]
    shop_dummies = [c for c in df.columns if c.startswith("is_shop_")]
    return base + machine_dummies + shop_dummies


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


def _print_per_shop(result, valid_df: pd.DataFrame, feature_cols: list[str]) -> None:
    """店舗別メトリクス + Precision@5。"""
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

    shops = sorted(valid_df["shop_id"].unique())
    for sid in shops:
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
    print()
    print("メトリクス読み方:")
    print("  P@5    : スコア上位5台の的中率 (ランダム=0.20、0.30以上で実用域)")
    print("  TopDiff: スコア上位5台の実際の平均diff (+1000以上が理想)")


if __name__ == "__main__":
    sys.exit(main())
'''

# ===== tests/test_no_target_leakage.py =====
FILES["tests/test_no_target_leakage.py"] = '''"""target_diff が翌日の diff になっていることを検証 (リーク防止)。"""
from __future__ import annotations

import pandas as pd
import pytest

from juggler_predictor.model import build_features


def _machines_cfg():
    return {
        "machines": [
            {"canonical": "マイジャグラーV", "aliases": []},
            {"canonical": "ファンキージャグラー2", "aliases": []},
        ]
    }


def _make_df():
    """同じ (shop, unit, machine) で 3 日分のデータ。"""
    rows = []
    for date, diff_val, bb, rb, g in [
        ("2026-05-01", 100, 20, 15, 6000),
        ("2026-05-02", 500, 25, 18, 6500),
        ("2026-05-03", -300, 18, 12, 5500),
    ]:
        rows.append({
            "shop_id": "shopA", "date": date,
            "machine_name": "マイジャグラーV", "unit_number": "100",
            "g_count": g, "bb": bb, "rb": rb, "diff": diff_val,
        })
    return pd.DataFrame(rows)


def test_target_diff_is_next_day_not_same_day():
    df = _make_df()
    feat, meta = build_features(df, machines_config=_machines_cfg())

    # 各行の target_diff が**翌日**の diff になっていること
    feat_sorted = feat.sort_values("date").reset_index(drop=True)
    # 2026-05-01 の target_diff は 2026-05-02 の diff = 500
    assert feat_sorted.iloc[0]["target_diff"] == 500.0
    # 2026-05-02 の target_diff は 2026-05-03 の diff = -300
    assert feat_sorted.iloc[1]["target_diff"] == -300.0
    # 2026-05-03 は翌日データなしで drop されているはず
    assert (feat_sorted["date"] == "2026-05-03").sum() == 0


def test_target_diff_not_equal_to_same_day_diff():
    """リーク確認: 当日 diff と target_diff が一致しないこと。"""
    df = _make_df()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # diff と target_diff の差が 0 の行は無いはず (3日のうち2日残るが値が違う)
    same = (feat["diff"] == feat["target_diff"]).sum()
    assert same == 0, f"target_diff が当日 diff と同じ行が {same} 件あります (リークの疑い)"


def test_last_day_per_unit_is_dropped():
    """各 (shop, unit, machine) の最終日が drop されていること。"""
    df = _make_df()
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # 元 3 行 → 翌日のある 2 行のみ残る
    assert len(feat) == 2


def test_machine_change_is_dropped():
    """同じ unit で機種が変わった日は drop されること。"""
    rows = [
        {"shop_id": "shopA", "date": "2026-05-01", "machine_name": "マイジャグラーV",
         "unit_number": "100", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
        {"shop_id": "shopA", "date": "2026-05-02", "machine_name": "マイジャグラーV",
         "unit_number": "100", "g_count": 6500, "bb": 25, "rb": 18, "diff": 500},
        # 機種変更
        {"shop_id": "shopA", "date": "2026-05-03", "machine_name": "ファンキージャグラー2",
         "unit_number": "100", "g_count": 5500, "bb": 18, "rb": 12, "diff": -300},
    ]
    df = pd.DataFrame(rows)
    feat, _ = build_features(df, machines_config=_machines_cfg())

    # マイV の 5/1 → 5/2 で 1 行残る (5/1 の target=5/2 の diff=500)
    # マイV の 5/2 は target なし(機種変更で別 group)
    # ファンキー2 の 5/3 も target なし
    assert len(feat) == 1
    assert feat.iloc[0]["target_diff"] == 500.0
'''

# ===== tests/test_shop_dummies.py =====
FILES["tests/test_shop_dummies.py"] = '''"""shop_id one-hot ダミーが正しく生成されることを検証。"""
from __future__ import annotations

import pandas as pd

from juggler_predictor.model import build_features


def _machines_cfg():
    return {"machines": [{"canonical": "マイジャグラーV", "aliases": []}]}


def _make_df():
    """3 店舗 × 各 2 日分。"""
    rows = []
    for shop in ("shopA", "shopB", "shopC"):
        for i, date in enumerate(["2026-05-01", "2026-05-02", "2026-05-03"]):
            rows.append({
                "shop_id": shop, "date": date,
                "machine_name": "マイジャグラーV", "unit_number": "100",
                "g_count": 6000 + i * 100, "bb": 20, "rb": 15, "diff": 100 + i * 50,
            })
    return pd.DataFrame(rows)


def test_shop_dummies_count_equals_n_minus_1():
    """3 店舗なら shop dummy は 2 列 (ベース 1 つを除く)。"""
    df = _make_df()
    _, meta = build_features(df, machines_config=_machines_cfg())
    assert len(meta.shop_dummy_cols) == 2  # 3 - 1


def test_shop_dummy_columns_in_feature_cols():
    """is_shop_* が feature_cols に含まれること。"""
    df = _make_df()
    _, meta = build_features(df, machines_config=_machines_cfg())
    shop_cols_in_features = [c for c in meta.feature_cols if c.startswith("is_shop_")]
    assert len(shop_cols_in_features) == len(meta.shop_dummy_cols)


def test_shop_ids_param_overrides_auto_detection():
    """shop_ids を明示渡すと、その順序でダミーが作られる (予測時の整合性)。"""
    df = _make_df()
    _, meta = build_features(
        df, machines_config=_machines_cfg(),
        shop_ids=["shopX", "shopA", "shopB", "shopC"],  # 学習時は4店舗あった想定
    )
    # shopX がベース、残り 3 つが dummy
    assert "is_shop_shopA" in meta.shop_dummy_cols
    assert "is_shop_shopB" in meta.shop_dummy_cols
    assert "is_shop_shopC" in meta.shop_dummy_cols


def test_shop_dummy_values_are_binary():
    """各行の shop dummy が 0/1 のみであること。"""
    df = _make_df()
    feat, meta = build_features(df, machines_config=_machines_cfg())
    for col in meta.shop_dummy_cols:
        unique_vals = set(feat[col].unique().tolist())
        assert unique_vals.issubset({0, 1}), f"{col} に 0/1 以外の値: {unique_vals}"
'''

# ===== tests/test_model_metrics.py =====
FILES["tests/test_model_metrics.py"] = '''"""precision_at_k, expected_topk_diff のテスト。"""
from __future__ import annotations

import numpy as np

from juggler_predictor.model import expected_topk_diff, precision_at_k


def test_precision_at_k_perfect():
    """スコア上位 K が全部 1 なら precision=1.0。"""
    y_true = np.array([1, 1, 0, 0, 0])
    scores = np.array([0.9, 0.8, 0.1, 0.2, 0.3])
    assert precision_at_k(y_true, scores, k=2) == 1.0


def test_precision_at_k_zero():
    """スコア上位 K が全部 0 なら precision=0.0。"""
    y_true = np.array([0, 0, 1, 1, 1])
    scores = np.array([0.9, 0.8, 0.1, 0.2, 0.3])
    assert precision_at_k(y_true, scores, k=2) == 0.0


def test_precision_at_k_returns_nan_when_too_few():
    """K より要素が少ない場合は NaN。"""
    y_true = np.array([1])
    scores = np.array([0.9])
    assert np.isnan(precision_at_k(y_true, scores, k=5))


def test_expected_topk_diff_picks_top():
    """スコア最高の diff を取れること。"""
    y_diff = np.array([1000.0, 500.0, -200.0])
    scores = np.array([0.9, 0.5, 0.1])
    # k=1 ならスコア最大の y_diff = 1000
    assert expected_topk_diff(y_diff, scores, k=1) == 1000.0
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
    print("  uv run pytest -v   # 期待: 既存 64 + 新規 11 = 75 passed (ただし test_model_features.py の旧テスト2件が落ちる可能性あり、後述)")
    print("  uv run python scripts/build_dataset.py  # parquet 再生成")
    print("  uv run python scripts/train.py          # 学習やり直し")


if __name__ == "__main__":
    write_all()
