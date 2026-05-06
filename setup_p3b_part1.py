"""P3b Part 1: dataset loader + features + time split."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/__init__.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/model/__init__.py"] = '''"""ML 学習・予測層。"""
from juggler_predictor.model.dataset import (
    load_dataset_from_local,
    load_dataset_from_r2,
)
from juggler_predictor.model.features import (
    FeatureMeta,
    TARGET_DIFF_THRESHOLD,
    build_features,
)
from juggler_predictor.model.split import time_split

__all__ = [
    "FeatureMeta",
    "TARGET_DIFF_THRESHOLD",
    "build_features",
    "load_dataset_from_local",
    "load_dataset_from_r2",
    "time_split",
]
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/dataset.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/model/dataset.py"] = '''"""R2 / ローカルから dataset JSON を一括ロードして DataFrame にまとめる。

ファイル構造:
    dataset/{shop_id}/{YYYY-MM-DD}.json.gz
    内容: ParsedPage.to_dict() の出力 (rows + shop_display_name + date_str)

DataFrame 列:
    shop_id, date, machine_name, unit_number,
    g_count, diff, bb, rb, art,
    composite_prob, bb_prob, rb_prob, art_prob (生文字列)
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Iterable

import pandas as pd

from juggler_predictor.storage import R2Client, R2Paths

logger = logging.getLogger(__name__)


def _row_dict(shop_id: str, date_str: str, page: dict) -> list[dict]:
    """ParsedPage.to_dict() の出力を行単位の辞書リストに展開する。"""
    out: list[dict] = []
    for r in page.get("rows", []) or []:
        out.append(
            {
                "shop_id": shop_id,
                "date": date_str,
                "machine_name": r.get("machine_name"),
                "unit_number": r.get("unit_number"),
                "g_count": r.get("g_count"),
                "diff": r.get("diff"),
                "bb": r.get("bb"),
                "rb": r.get("rb"),
                "art": r.get("art"),
                "composite_prob": r.get("composite_prob"),
                "bb_prob": r.get("bb_prob"),
                "rb_prob": r.get("rb_prob"),
                "art_prob": r.get("art_prob"),
            }
        )
    return out


def load_dataset_from_r2(
    r2: R2Client,
    *,
    shop_ids: list[str] | None = None,
) -> pd.DataFrame:
    """R2 dataset/ 以下の json.gz を全て読み込んで DataFrame を返す。

    Parameters
    ----------
    shop_ids:
        ``None`` なら全店舗。指定すれば該当店舗のみ読み込む。
    """
    rows: list[dict] = []
    keys: Iterable[str] = r2.list_keys("dataset/")
    n = 0
    for key in keys:
        # 期待: dataset/<shop_id>/<date>.json.gz
        parts = key.split("/")
        if len(parts) != 3:
            continue
        _, shop_id, fname = parts
        if shop_ids is not None and shop_id not in shop_ids:
            continue
        if not fname.endswith(".json.gz"):
            continue
        date_str = fname.rsplit(".", 2)[0]

        try:
            page = r2.get_json(key, gzipped=True)
        except Exception as e:  # gzip 破損などは飛ばす
            logger.warning("R2 read 失敗: key=%s err=%s", key, e)
            continue
        rows.extend(_row_dict(shop_id, date_str, page))
        n += 1
        if n % 100 == 0:
            logger.info("R2 dataset loaded: %d files, %d rows", n, len(rows))

    logger.info("R2 dataset 全 %d files, %d rows", n, len(rows))
    return pd.DataFrame(rows)


def load_dataset_from_local(root: Path) -> pd.DataFrame:
    """ローカル ``root/<shop_id>/<date>.json`` を全て読み込む (テスト用)。

    .json.gz / .json の両方に対応する。
    """
    rows: list[dict] = []
    if not root.exists():
        return pd.DataFrame(rows)

    for shop_dir in sorted(root.iterdir()):
        if not shop_dir.is_dir():
            continue
        shop_id = shop_dir.name
        for f in sorted(shop_dir.iterdir()):
            name = f.name
            if name.endswith(".json.gz"):
                date_str = name[:-len(".json.gz")]
                with gzip.open(f, "rt", encoding="utf-8") as fp:
                    page = json.load(fp)
            elif name.endswith(".json"):
                date_str = name[:-len(".json")]
                page = json.loads(f.read_text(encoding="utf-8"))
            else:
                continue
            rows.extend(_row_dict(shop_id, date_str, page))
    return pd.DataFrame(rows)
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/features.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/model/features.py"] = '''"""dataset DataFrame を学習用特徴量に変換する。

設計:
    - 当日特徴量のみ (履歴は P4 以降で拡張する)
    - target_diff: 当日 diff (回帰ターゲット)
    - target_win:  diff > TARGET_DIFF_THRESHOLD なら 1, else 0
    - 機種は one-hot (machines.yaml の canonical を列にする)
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
    """学習・予測時の特徴量メタ情報。"""

    feature_cols: list[str]
    target_diff_col: str
    target_win_col: str
    machine_dummy_cols: list[str]


def _canonical_set(machines_config: dict) -> list[str]:
    return [m["canonical"] for m in machines_config.get("machines", []) if "canonical" in m]


def build_features(
    df: pd.DataFrame,
    *,
    machines_config: dict,
    drop_na_target: bool = True,
) -> tuple[pd.DataFrame, FeatureMeta]:
    """dataset DataFrame に特徴量列とターゲット列を追加して返す。

    入力:
        必要列: shop_id, date, machine_name, unit_number,
               g_count, diff, bb, rb (art は欠損可)
    出力:
        (拡張済み DataFrame, FeatureMeta)
    """
    if df.empty:
        meta = FeatureMeta(
            feature_cols=[],
            target_diff_col="target_diff",
            target_win_col="target_win",
            machine_dummy_cols=[],
        )
        return df.copy(), meta

    out = df.copy()

    # 数値整形
    for col in ("g_count", "diff", "bb", "rb", "art"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 派生特徴量
    g = out["g_count"].astype("Float64")
    bb = out["bb"].astype("Float64")
    rb = out["rb"].astype("Float64")
    out["bb_rate"] = (bb / g).where(g > 0)
    out["rb_rate"] = (rb / g).where(g > 0)
    out["total_rate"] = ((bb + rb) / g).where(g > 0)
    out["bb_per_rb"] = (bb / rb).where(rb > 0)

    # 機種 one-hot (machines.yaml に列挙された canonical のみ)
    canonicals = _canonical_set(machines_config)
    for name in canonicals:
        col = _machine_dummy_col(name)
        out[col] = (out["machine_name"] == name).astype(np.int8)
    machine_dummy_cols = [_machine_dummy_col(n) for n in canonicals]

    # ターゲット
    out["target_diff"] = out["diff"].astype("Float64")
    out["target_win"] = (out["target_diff"] > TARGET_DIFF_THRESHOLD).astype(np.int8)

    # date 列を datetime 化 (split のため)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")

    feature_cols: list[str] = [
        "g_count",
        "bb",
        "rb",
        "bb_rate",
        "rb_rate",
        "total_rate",
        "bb_per_rb",
        *machine_dummy_cols,
    ]

    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除去", dropped)

    meta = FeatureMeta(
        feature_cols=feature_cols,
        target_diff_col="target_diff",
        target_win_col="target_win",
        machine_dummy_cols=machine_dummy_cols,
    )
    return out, meta


def _machine_dummy_col(name: str) -> str:
    return f"is_{name}"
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/split.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/model/split.py"] = '''"""時系列 split: 直近 ``valid_days`` 日を valid に、それ以前を train に。

ML パイプラインのデータリークを構造的に防ぐため、ランダム split は使わない。
"""
from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def time_split(
    df: pd.DataFrame,
    *,
    valid_days: int = 7,
    date_col: str = "date_dt",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """train / valid に時系列 split する。

    valid_days = 7 なら、最大日付 d_max を含めて [d_max-6 .. d_max] が valid。
    train は date_dt < (d_max - 6) の行。
    """
    if df.empty or date_col not in df.columns:
        return df.copy(), df.iloc[0:0].copy()

    dates = pd.to_datetime(df[date_col], errors="coerce")
    valid_max = dates.max()
    if pd.isna(valid_max):
        return df.copy(), df.iloc[0:0].copy()
    valid_min = valid_max - timedelta(days=valid_days - 1)

    valid_mask = dates >= valid_min
    train_mask = dates < valid_min

    train = df.loc[train_mask].copy()
    valid = df.loc[valid_mask].copy()

    logger.info(
        "time_split: train=%d (date<%s), valid=%d (date>=%s, max=%s)",
        len(train), valid_min.date(), len(valid), valid_min.date(), valid_max.date(),
    )
    return train, valid
'''

# ---------------------------------------------------------------------------
# scripts/build_dataset.py
# ---------------------------------------------------------------------------
FILES["scripts/build_dataset.py"] = '''"""R2 から dataset を全件読み込み、サマリと parquet を出力する確認用スクリプト。

使い方:
    uv run python scripts/build_dataset.py
    uv run python scripts/build_dataset.py --shops kingsetagaya,messekichijoji
    uv run python scripts/build_dataset.py --output data/dataset.parquet
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR, DATA_DIR
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.model import (
    build_features,
    load_dataset_from_r2,
    time_split,
)
from juggler_predictor.storage import build_r2_client_from_env

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--shops", default="", help="カンマ区切りの店舗 id (空なら全店)")
    ap.add_argument("--output", default=str(DATA_DIR / "dataset.parquet"))
    ap.add_argument("--valid-days", type=int, default=7)
    args = ap.parse_args()

    shop_ids = [s.strip() for s in args.shops.split(",") if s.strip()] or None

    logger.info("[1] R2 から dataset 読み込み")
    r2 = build_r2_client_from_env()
    df = load_dataset_from_r2(r2, shop_ids=shop_ids)
    logger.info("rows=%d shops=%d dates=%d",
                len(df),
                df["shop_id"].nunique() if not df.empty else 0,
                df["date"].nunique() if not df.empty else 0)
    if df.empty:
        logger.error("dataset が空です。bootstrap を先に実行してください。")
        return 1

    logger.info("[2] 特徴量生成")
    machines_cfg = yaml.safe_load((CONFIG_DIR / "machines.yaml").read_text(encoding="utf-8"))
    feat_df, meta = build_features(df, machines_config=machines_cfg)
    logger.info("feature_cols=%d", len(meta.feature_cols))
    logger.info("juggler 行 (machine_dummy のいずれかが 1): %d / 全 %d",
                int(feat_df[meta.machine_dummy_cols].sum(axis=1).gt(0).sum()),
                len(feat_df))

    logger.info("[3] 時系列 split")
    train, valid = time_split(feat_df, valid_days=args.valid_days)

    print()
    print("=" * 60)
    print("[DATASET SUMMARY]")
    print("=" * 60)
    print(f"  全行数        : {len(feat_df)}")
    print(f"  店舗数        : {feat_df['shop_id'].nunique()}")
    print(f"  日付範囲      : {feat_df['date'].min()} 〜 {feat_df['date'].max()}")
    print(f"  特徴量列数    : {len(meta.feature_cols)}")
    print(f"  train rows    : {len(train)}")
    print(f"  valid rows    : {len(valid)}")
    if not train.empty:
        print(f"  train target_win 率: {train['target_win'].mean():.3f}")
    if not valid.empty:
        print(f"  valid target_win 率: {valid['target_win'].mean():.3f}")
    print()
    print("=== 機種別 行数 (上位 10) ===")
    counts = feat_df["machine_name"].value_counts().head(10)
    for name, n in counts.items():
        print(f"  {name:30s}  {n}")
    print()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    feat_df.to_parquet(out_path, index=False)
    logger.info("[OK] parquet 保存: %s (%d MB)",
                out_path, out_path.stat().st_size // (1024 * 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------------------
# tests/fixtures/sample_dataset/  (合成データ)
# ---------------------------------------------------------------------------
import json as _json

_SAMPLE_PAGES: dict[str, dict] = {
    "kingsetagaya/2026-04-29.json": {
        "shop_display_name": "キングNo.1世田谷店",
        "date_str": "2026-04-29",
        "rows": [
            {"machine_name": "マイジャグラーV", "machine_name_raw": "マイジャグラーV",
             "unit_number": "1", "unit_number_raw": "1",
             "g_count": 5000, "diff": 1500, "bb": 20, "rb": 10, "art": None,
             "composite_prob": "1/166.67", "bb_prob": "1/250", "rb_prob": "1/500",
             "art_prob": None},
            {"machine_name": "ネオアイムジャグラーEX",
             "machine_name_raw": "ネオアイムジャグラーEX",
             "unit_number": "2", "unit_number_raw": "2",
             "g_count": 4500, "diff": -800, "bb": 14, "rb": 8, "art": None,
             "composite_prob": "1/204.55", "bb_prob": "1/321", "rb_prob": "1/562",
             "art_prob": None},
        ],
        "total_rows_in_table": 50,
    },
    "kingsetagaya/2026-04-30.json": {
        "shop_display_name": "キングNo.1世田谷店",
        "date_str": "2026-04-30",
        "rows": [
            {"machine_name": "マイジャグラーV", "machine_name_raw": "マイジャグラーV",
             "unit_number": "1", "unit_number_raw": "1",
             "g_count": 6000, "diff": 2200, "bb": 28, "rb": 14, "art": None,
             "composite_prob": "1/142.85", "bb_prob": "1/214", "rb_prob": "1/428",
             "art_prob": None},
            {"machine_name": "ネオアイムジャグラーEX",
             "machine_name_raw": "ネオアイムジャグラーEX",
             "unit_number": "2", "unit_number_raw": "2",
             "g_count": 5200, "diff": 300, "bb": 18, "rb": 11, "art": None,
             "composite_prob": "1/179.31", "bb_prob": "1/289", "rb_prob": "1/472",
             "art_prob": None},
        ],
        "total_rows_in_table": 55,
    },
    "kingsetagaya/2026-05-05.json": {
        "shop_display_name": "キングNo.1世田谷店",
        "date_str": "2026-05-05",
        "rows": [
            {"machine_name": "マイジャグラーV", "machine_name_raw": "マイジャグラーV",
             "unit_number": "1", "unit_number_raw": "1",
             "g_count": 5500, "diff": -500, "bb": 18, "rb": 10, "art": None,
             "composite_prob": "1/196.42", "bb_prob": "1/305", "rb_prob": "1/550",
             "art_prob": None},
        ],
        "total_rows_in_table": 60,
    },
    "messekichijoji/2026-05-05.json": {
        "shop_display_name": "メッセ吉祥寺店本館",
        "date_str": "2026-05-05",
        "rows": [
            {"machine_name": "マイジャグラーV", "machine_name_raw": "マイジャグラーV",
             "unit_number": "11", "unit_number_raw": "11",
             "g_count": 4800, "diff": 1800, "bb": 22, "rb": 12, "art": None,
             "composite_prob": "1/141.18", "bb_prob": "1/218", "rb_prob": "1/400",
             "art_prob": None},
        ],
        "total_rows_in_table": 40,
    },
}

for rel_subpath, page in _SAMPLE_PAGES.items():
    FILES[f"tests/fixtures/sample_dataset/{rel_subpath}"] = _json.dumps(
        page, ensure_ascii=False, indent=2
    )

# ---------------------------------------------------------------------------
# tests/test_model_dataset.py
# ---------------------------------------------------------------------------
FILES["tests/test_model_dataset.py"] = '''"""dataset.load_dataset_from_local のテスト。"""
from __future__ import annotations

from pathlib import Path

from juggler_predictor.model import load_dataset_from_local

ROOT = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"


def test_load_local_returns_dataframe() -> None:
    df = load_dataset_from_local(ROOT)
    assert not df.empty
    assert "shop_id" in df.columns
    assert "date" in df.columns
    assert "machine_name" in df.columns


def test_load_local_unique_shops_and_dates() -> None:
    df = load_dataset_from_local(ROOT)
    assert set(df["shop_id"].unique()) == {"kingsetagaya", "messekichijoji"}
    assert "2026-04-29" in df["date"].unique()
    assert "2026-05-05" in df["date"].unique()


def test_load_local_row_counts() -> None:
    df = load_dataset_from_local(ROOT)
    # kingsetagaya: 2 + 2 + 1 = 5
    # messekichijoji: 1
    assert (df["shop_id"] == "kingsetagaya").sum() == 5
    assert (df["shop_id"] == "messekichijoji").sum() == 1


def test_load_empty_returns_empty_df() -> None:
    df = load_dataset_from_local(Path("tests/fixtures/__not_exist__"))
    assert df.empty
'''

# ---------------------------------------------------------------------------
# tests/test_model_features.py
# ---------------------------------------------------------------------------
FILES["tests/test_model_features.py"] = '''"""features.build_features のテスト。"""
from __future__ import annotations

from pathlib import Path

import yaml

from juggler_predictor.model import (
    TARGET_DIFF_THRESHOLD,
    build_features,
    load_dataset_from_local,
)

ROOT = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"
MACHINES_YAML = (
    Path(__file__).resolve().parents[1] / "config" / "machines.yaml"
)


def _machines_cfg() -> dict:
    return yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8"))


def test_build_features_adds_rate_columns() -> None:
    df = load_dataset_from_local(ROOT)
    feat, meta = build_features(df, machines_config=_machines_cfg())
    for col in ("bb_rate", "rb_rate", "total_rate", "bb_per_rb"):
        assert col in feat.columns
    assert meta.target_diff_col == "target_diff"
    assert meta.target_win_col == "target_win"


def test_target_win_threshold() -> None:
    df = load_dataset_from_local(ROOT)
    feat, _ = build_features(df, machines_config=_machines_cfg())
    # diff>1000 の行は target_win=1
    for _, row in feat.iterrows():
        expected = int(row["diff"] > TARGET_DIFF_THRESHOLD)
        assert int(row["target_win"]) == expected


def test_machine_dummy_columns_present() -> None:
    df = load_dataset_from_local(ROOT)
    feat, meta = build_features(df, machines_config=_machines_cfg())
    canonicals = [m["canonical"] for m in _machines_cfg()["machines"]]
    for name in canonicals:
        col = f"is_{name}"
        assert col in feat.columns
    # 「マイジャグラーV」フラグが立っている行が 4 行 (合計 4 ファイルの先頭行)
    assert int(feat["is_マイジャグラーV"].sum()) == 4


def test_feature_cols_meta() -> None:
    df = load_dataset_from_local(ROOT)
    _, meta = build_features(df, machines_config=_machines_cfg())
    # 主要派生 + 機種 dummy が含まれる
    assert "bb_rate" in meta.feature_cols
    assert "rb_rate" in meta.feature_cols
    assert "total_rate" in meta.feature_cols
    assert any(c.startswith("is_") for c in meta.feature_cols)


def test_drops_na_target_rows() -> None:
    import pandas as pd
    df = load_dataset_from_local(ROOT)
    # diff を NaN にした行を追加
    extra = df.iloc[0].to_dict()
    extra["diff"] = None
    extra["unit_number"] = "999"
    df2 = pd.concat([df, pd.DataFrame([extra])], ignore_index=True)
    feat, _ = build_features(df2, machines_config=_machines_cfg())
    assert len(feat) == len(df)  # NaN 行は除外される
'''

# ---------------------------------------------------------------------------
# tests/test_model_split.py
# ---------------------------------------------------------------------------
FILES["tests/test_model_split.py"] = '''"""split.time_split のテスト。"""
from __future__ import annotations

from pathlib import Path

import yaml

from juggler_predictor.model import (
    build_features,
    load_dataset_from_local,
    time_split,
)

ROOT = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"
MACHINES_YAML = (
    Path(__file__).resolve().parents[1] / "config" / "machines.yaml"
)


def test_time_split_train_before_valid() -> None:
    df = load_dataset_from_local(ROOT)
    feat, _ = build_features(
        df,
        machines_config=yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8")),
    )
    train, valid = time_split(feat, valid_days=7)

    # valid は最新日 (2026-05-05) を含む 7 日
    assert "2026-05-05" in valid["date"].unique()
    if not train.empty:
        # train の全日付は valid の最小日付より前
        assert train["date_dt"].max() < valid["date_dt"].min()


def test_time_split_with_valid_days_2_only_recent() -> None:
    df = load_dataset_from_local(ROOT)
    feat, _ = build_features(
        df,
        machines_config=yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8")),
    )
    # サンプルは 04-29, 04-30, 05-05 → valid_days=2 なら valid は 05-05 と前日 (05-04 はデータなし) のみ
    train, valid = time_split(feat, valid_days=2)
    valid_dates = set(valid["date"].unique())
    assert "2026-05-05" in valid_dates
    assert "2026-04-29" not in valid_dates
    assert "2026-04-30" not in valid_dates


def test_empty_input_returns_empty() -> None:
    import pandas as pd
    train, valid = time_split(pd.DataFrame())
    assert train.empty
    assert valid.empty
'''


def main() -> None:
    print("=" * 60)
    print("P3b Part 1: dataset + features + split")
    print("=" * 60)
    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")
    print()
    print("[OK] 生成完了")
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print("  uv run python scripts/build_dataset.py")


if __name__ == "__main__":
    main()
