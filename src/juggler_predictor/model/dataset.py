"""R2 / ローカルから dataset JSON を一括ロードして DataFrame にまとめる。

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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    max_workers: int = 32,
) -> pd.DataFrame:
    """R2 dataset/ 以下の json.gz を並列で全て読み込んで DataFrame を返す。"""
    # 1. 対象キーを先に列挙
    target_keys: list[tuple[str, str, str]] = []  # (key, shop_id, date_str)
    for key in r2.list_keys("dataset/"):
        parts = key.split("/")
        if len(parts) != 3:
            continue
        _, shop_id, fname = parts
        if shop_ids is not None and shop_id not in shop_ids:
            continue
        if not fname.endswith(".json.gz"):
            continue
        date_str = fname.rsplit(".", 2)[0]
        target_keys.append((key, shop_id, date_str))

    logger.info("R2 dataset 並列ダウンロード開始: %d files (workers=%d)", len(target_keys), max_workers)

    rows: list[dict] = []

    def _fetch(item: tuple[str, str, str]) -> list[dict] | None:
        key, shop_id, date_str = item
        try:
            page = r2.get_json(key, gzipped=True)
        except Exception as e:
            logger.warning("R2 read 失敗: key=%s err=%s", key, e)
            return None
        return _row_dict(shop_id, date_str, page)

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch, item) for item in target_keys]
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                rows.extend(result)
            completed += 1
            if completed % 500 == 0:
                logger.info("R2 dataset loaded: %d/%d files, %d rows", completed, len(target_keys), len(rows))

    logger.info("R2 dataset 全 %d files, %d rows", len(target_keys), len(rows))
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


from .setting_estimator import estimate_setting


def add_prev_setting_features(df):
    """prev_setting / prev_p_high / y_setting_next を生成。"""
    import pandas as pd

    if "setting" not in df.columns:
        def _est(row):
            return estimate_setting(
                composite_prob=row.get("composite_prob"),
                diff=row.get("diff", 0.0),
                machine_name=row.get("machine_name", ""),
            )

        df = df.copy()
        df["setting"] = df.apply(_est, axis=1).astype(int)

    df = df.sort_values(["shop_id", "unit_number", "date"]).copy()
    grp = df.groupby(["shop_id", "unit_number"], sort=False)
    df["prev_setting"] = grp["setting"].shift(1)
    df["prev_p_high"] = (df["prev_setting"] >= 4).astype("float")
    df["prev_setting"] = df["prev_setting"].fillna(3.0)
    df["prev_p_high"] = df["prev_p_high"].fillna(0.0)

    if "y_setting_next" not in df.columns:
        df["y_setting_next"] = grp["setting"].shift(-1)
    return df
