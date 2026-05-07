# setup_p3b_part2_7.py
"""P3b Part 2.7: 履歴特徴量 (unit/shop_machine/shop/date) を追加。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ===== src/juggler_predictor/model/history.py (新規) =====
FILES["src/juggler_predictor/model/history.py"] = '''"""履歴特徴量の生成。

リーク防止:
    - target は翌日の diff (build_features で shift(-1) 済み)
    - 履歴は当日含む過去 N 日 (= t 日の終値まで使う)
    - rolling は groupby ごとに行い、他店舗/他機種の値が混ざらないようにする
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


HISTORY_FEATURE_COLS = [
    # 台レベル
    "unit_bb_rate_mean_7d",
    "unit_bb_rate_mean_14d",
    "unit_diff_mean_7d",
    "unit_diff_mean_14d",
    "unit_diff_sum_7d",
    "unit_observed_days_14d",
    # 店舗 × 機種レベル
    "sm_bb_rate_mean_14d",
    "sm_diff_mean_14d",
    "sm_win_rate_14d",
    "sm_top_diff_14d",
    "sm_diff_std_14d",
    # 店舗レベル
    "shop_total_diff_7d",
    "shop_total_diff_14d",
    "shop_win_rate_7d",
    # 日付特徴量
    "dow",
    "is_weekend",
    "is_month_start",
    "is_month_end",
    "day_has_5_or_8",
]


def add_history_features(df: pd.DataFrame) -> pd.DataFrame:
    """dataset DataFrame に履歴特徴量を追加する。

    必須列: shop_id, date, machine_name, unit_number, g_count, bb, rb, diff
    出力: 履歴特徴量列を追加した DataFrame (元の行数を維持)
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")
    out = out.sort_values(["shop_id", "machine_name", "unit_number", "date_dt"]).reset_index(drop=True)

    # 当日の bb_rate (rolling のソース)
    g = out["g_count"].astype("Float64")
    bb = out["bb"].astype("Float64")
    out["_bb_rate_today"] = (bb / g).where(g > 0).astype(float)
    out["_diff_today"] = out["diff"].astype(float)
    out["_win_today"] = (out["_diff_today"] > 1000).astype(float)

    # ===== A. 台レベル履歴 =====
    grp_unit = out.groupby(["shop_id", "machine_name", "unit_number"], sort=False)
    out["unit_bb_rate_mean_7d"] = grp_unit["_bb_rate_today"].transform(
        lambda s: s.rolling(7, min_periods=1).mean()
    )
    out["unit_bb_rate_mean_14d"] = grp_unit["_bb_rate_today"].transform(
        lambda s: s.rolling(14, min_periods=1).mean()
    )
    out["unit_diff_mean_7d"] = grp_unit["_diff_today"].transform(
        lambda s: s.rolling(7, min_periods=1).mean()
    )
    out["unit_diff_mean_14d"] = grp_unit["_diff_today"].transform(
        lambda s: s.rolling(14, min_periods=1).mean()
    )
    out["unit_diff_sum_7d"] = grp_unit["_diff_today"].transform(
        lambda s: s.rolling(7, min_periods=1).sum()
    )
    out["unit_observed_days_14d"] = grp_unit["_diff_today"].transform(
        lambda s: s.rolling(14, min_periods=1).count()
    )

    # ===== B. 店舗 × 機種レベル =====
    # 同日の店舗×機種で集約 → 日付に対して rolling
    sm_daily = (
        out.groupby(["shop_id", "machine_name", "date_dt"], sort=False)
        .agg(
            sm_bb_rate_today=("_bb_rate_today", "mean"),
            sm_diff_today=("_diff_today", "mean"),
            sm_win_today=("_win_today", "mean"),
            sm_top_diff_today=("_diff_today", "max"),
            sm_diff_std_today=("_diff_today", "std"),
        )
        .reset_index()
        .sort_values(["shop_id", "machine_name", "date_dt"])
    )
    grp_sm = sm_daily.groupby(["shop_id", "machine_name"], sort=False)
    sm_daily["sm_bb_rate_mean_14d"] = grp_sm["sm_bb_rate_today"].transform(
        lambda s: s.rolling(14, min_periods=1).mean()
    )
    sm_daily["sm_diff_mean_14d"] = grp_sm["sm_diff_today"].transform(
        lambda s: s.rolling(14, min_periods=1).mean()
    )
    sm_daily["sm_win_rate_14d"] = grp_sm["sm_win_today"].transform(
        lambda s: s.rolling(14, min_periods=1).mean()
    )
    sm_daily["sm_top_diff_14d"] = grp_sm["sm_top_diff_today"].transform(
        lambda s: s.rolling(14, min_periods=1).max()
    )
    sm_daily["sm_diff_std_14d"] = grp_sm["sm_diff_today"].transform(
        lambda s: s.rolling(14, min_periods=1).std()
    )
    sm_cols = ["sm_bb_rate_mean_14d", "sm_diff_mean_14d", "sm_win_rate_14d",
               "sm_top_diff_14d", "sm_diff_std_14d"]
    out = out.merge(
        sm_daily[["shop_id", "machine_name", "date_dt", *sm_cols]],
        on=["shop_id", "machine_name", "date_dt"],
        how="left",
    )

    # ===== C. 店舗レベル =====
    shop_daily = (
        out.groupby(["shop_id", "date_dt"], sort=False)
        .agg(
            shop_total_diff_today=("_diff_today", "sum"),
            shop_win_today=("_win_today", "mean"),
        )
        .reset_index()
        .sort_values(["shop_id", "date_dt"])
    )
    grp_shop = shop_daily.groupby(["shop_id"], sort=False)
    shop_daily["shop_total_diff_7d"] = grp_shop["shop_total_diff_today"].transform(
        lambda s: s.rolling(7, min_periods=1).sum()
    )
    shop_daily["shop_total_diff_14d"] = grp_shop["shop_total_diff_today"].transform(
        lambda s: s.rolling(14, min_periods=1).sum()
    )
    shop_daily["shop_win_rate_7d"] = grp_shop["shop_win_today"].transform(
        lambda s: s.rolling(7, min_periods=1).mean()
    )
    shop_cols = ["shop_total_diff_7d", "shop_total_diff_14d", "shop_win_rate_7d"]
    out = out.merge(
        shop_daily[["shop_id", "date_dt", *shop_cols]],
        on=["shop_id", "date_dt"],
        how="left",
    )

    # ===== D. 日付特徴量 =====
    out["dow"] = out["date_dt"].dt.dayofweek.astype("Int64")
    out["is_weekend"] = out["dow"].isin([5, 6]).astype(np.int8)
    day_of_month = out["date_dt"].dt.day
    out["is_month_start"] = (day_of_month <= 1).astype(np.int8)
    days_in_month = out["date_dt"].dt.days_in_month
    out["is_month_end"] = (day_of_month >= days_in_month - 2).astype(np.int8)
    out["day_has_5_or_8"] = day_of_month.isin([5, 8, 15, 18, 25, 28]).astype(np.int8)

    # 補助列を削除
    out = out.drop(columns=["_bb_rate_today", "_diff_today", "_win_today"])

    n_added = len(HISTORY_FEATURE_COLS)
    logger.info("履歴特徴量 %d 列を追加 (rows=%d)", n_added, len(out))
    return out
'''

# ===== src/juggler_predictor/model/features.py 更新 (履歴特徴量を統合) =====
FILES["src/juggler_predictor/model/features.py"] = '''"""dataset DataFrame を学習用特徴量に変換する。

設計 (P3b Part 2.7 履歴特徴量版):
    - target_diff: 翌日の同じ台の diff
    - target_win:  翌日 diff > TARGET_DIFF_THRESHOLD なら 1
    - 当日特徴量: g_count, bb, rb, *_rate (7列)
    - 機種ダミー: machines.yaml の canonical (9列)
    - 店舗ダミー: 18店舗中17列
    - 履歴特徴量: 台/店舗×機種/店舗/日付 (19列)
    合計: 7 + 9 + 17 + 19 = 52列
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .history import HISTORY_FEATURE_COLS, add_history_features

logger = logging.getLogger(__name__)

TARGET_DIFF_THRESHOLD = 1000


@dataclass(frozen=True)
class FeatureMeta:
    feature_cols: list[str]
    target_diff_col: str
    target_win_col: str
    machine_dummy_cols: list[str]
    shop_dummy_cols: list[str]
    history_cols: list[str]
    shop_ids: list[str]


def _canonical_set(machines_config: dict) -> list[str]:
    return [m["canonical"] for m in machines_config.get("machines", []) if "canonical" in m]


def build_features(
    df: pd.DataFrame,
    *,
    machines_config: dict,
    shop_ids: list[str] | None = None,
    drop_na_target: bool = True,
    add_history: bool = True,
) -> tuple[pd.DataFrame, FeatureMeta]:
    if df.empty:
        meta = FeatureMeta(
            feature_cols=[], target_diff_col="target_diff", target_win_col="target_win",
            machine_dummy_cols=[], shop_dummy_cols=[], history_cols=[], shop_ids=[],
        )
        return df.copy(), meta

    out = df.copy()

    # 数値整形
    for col in ("g_count", "diff", "bb", "rb", "art"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 履歴特徴量 (target shift より前に計算: 履歴は当日含む過去)
    if add_history:
        out = add_history_features(out)
        history_cols = list(HISTORY_FEATURE_COLS)
    else:
        history_cols = []
        out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")

    # 当日派生特徴量
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

    # 店舗 one-hot
    if shop_ids is None:
        shop_ids_used = sorted(out["shop_id"].dropna().unique().tolist())
    else:
        shop_ids_used = list(shop_ids)
    shop_dummy_cols: list[str] = []
    if len(shop_ids_used) >= 2:
        for sid in shop_ids_used[1:]:
            col = _shop_dummy_col(sid)
            out[col] = (out["shop_id"] == sid).astype(np.int8)
            shop_dummy_cols.append(col)

    # ターゲット (翌日 diff)
    out = out.sort_values(["shop_id", "unit_number", "machine_name", "date_dt"]).reset_index(drop=True)
    out["target_diff"] = (
        out.groupby(["shop_id", "unit_number", "machine_name"])["diff"]
        .shift(-1)
        .astype("Float64")
    )

    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除外", dropped)

    out["target_win"] = (
        (out["target_diff"] > TARGET_DIFF_THRESHOLD).fillna(False).astype(np.int8)
    )

    feature_cols: list[str] = [
        "g_count", "bb", "rb",
        "bb_rate", "rb_rate", "total_rate", "bb_per_rb",
        *machine_dummy_cols,
        *shop_dummy_cols,
        *history_cols,
    ]

    meta = FeatureMeta(
        feature_cols=feature_cols,
        target_diff_col="target_diff",
        target_win_col="target_win",
        machine_dummy_cols=machine_dummy_cols,
        shop_dummy_cols=shop_dummy_cols,
        history_cols=history_cols,
        shop_ids=shop_ids_used,
    )
    return out, meta


def _machine_dummy_col(name: str) -> str:
    return f"is_{name}"


def _shop_dummy_col(shop_id: str) -> str:
    return f"is_shop_{shop_id}"
'''

# ===== src/juggler_predictor/model/__init__.py 更新 =====
FILES["src/juggler_predictor/model/__init__.py"] = '''"""ML モデル層。"""
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
'''

# ===== tests/test_history_features.py (新規) =====
FILES["tests/test_history_features.py"] = '''"""履歴特徴量のリーク防止 & 計算正確性テスト。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from juggler_predictor.model import HISTORY_FEATURE_COLS, add_history_features


def _make_df(n_days: int = 10):
    rows = []
    for i in range(n_days):
        date = f"2026-04-{i+1:02d}" if i < 30 else f"2026-05-{i-29:02d}"
        rows.append({
            "shop_id": "shopA", "date": date, "machine_name": "マイV",
            "unit_number": "1", "g_count": 6000 + i * 100,
            "bb": 20 + i, "rb": 15, "diff": 100 * (i + 1),
        })
    return pd.DataFrame(rows)


def test_all_history_cols_added():
    df = _make_df(10)
    out = add_history_features(df)
    for col in HISTORY_FEATURE_COLS:
        assert col in out.columns, f"missing: {col}"


def test_unit_diff_mean_7d_calculated_correctly():
    """過去7日 (当日含む) の diff 平均が正しいこと。"""
    df = _make_df(10)
    out = add_history_features(df).sort_values("date").reset_index(drop=True)
    # 7日目の unit_diff_mean_7d = (1〜7日目の diff) の平均 = (100+200+...+700)/7 = 400
    assert abs(out.iloc[6]["unit_diff_mean_7d"] - 400.0) < 1e-6


def test_no_future_leak_in_history():
    """t日の履歴特徴量が t+1 日以降のデータを含まないこと。"""
    df = _make_df(10)
    out = add_history_features(df).sort_values("date").reset_index(drop=True)
    # 1日目の unit_diff_mean_7d は 1日目の diff (=100) のみ
    assert out.iloc[0]["unit_diff_mean_7d"] == 100.0
    # 2日目の unit_diff_mean_7d は (1+2日目)/2 = 150
    assert out.iloc[1]["unit_diff_mean_7d"] == 150.0


def test_dow_and_weekend_flags():
    """曜日・週末フラグが正しいこと。"""
    df = pd.DataFrame([{
        "shop_id": "shopA", "date": "2026-05-02",  # 土曜日
        "machine_name": "マイV", "unit_number": "1",
        "g_count": 6000, "bb": 20, "rb": 15, "diff": 100,
    }])
    out = add_history_features(df)
    assert int(out.iloc[0]["dow"]) == 5  # 土曜
    assert int(out.iloc[0]["is_weekend"]) == 1


def test_day_has_5_or_8_flag():
    """5/8/15/18/25/28日フラグが立つこと。"""
    df = pd.DataFrame([
        {"shop_id": "shopA", "date": "2026-05-05", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
        {"shop_id": "shopA", "date": "2026-05-06", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 100},
    ])
    out = add_history_features(df)
    out = out.sort_values("date").reset_index(drop=True)
    assert int(out.iloc[0]["day_has_5_or_8"]) == 1  # 5日
    assert int(out.iloc[1]["day_has_5_or_8"]) == 0  # 6日


def test_groupby_isolates_shops():
    """別店舗のデータが履歴に混ざらないこと。"""
    rows = [
        {"shop_id": "shopA", "date": "2026-05-01", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 1000},
        {"shop_id": "shopB", "date": "2026-05-01", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": -2000},
        {"shop_id": "shopA", "date": "2026-05-02", "machine_name": "マイV",
         "unit_number": "1", "g_count": 6000, "bb": 20, "rb": 15, "diff": 500},
    ]
    df = pd.DataFrame(rows)
    out = add_history_features(df)
    # shopA の 5/02 の unit_diff_mean_7d = (1000+500)/2 = 750 (shopB の -2000 は混ざらない)
    a_row = out[(out["shop_id"] == "shopA") & (out["date"] == "2026-05-02")].iloc[0]
    assert abs(a_row["unit_diff_mean_7d"] - 750.0) < 1e-6


def test_row_count_preserved():
    """行数が変わらないこと (履歴特徴量は drop しない)。"""
    df = _make_df(10)
    out = add_history_features(df)
    assert len(out) == len(df)
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
    print("  uv run pytest -v   # 期待: 75 + 7 = 82 passed")
    print("  uv run python scripts/build_dataset.py   # 履歴特徴量を含む parquet 再生成")
    print("  uv run python scripts/train.py           # 学習やり直し")


if __name__ == "__main__":
    write_all()
