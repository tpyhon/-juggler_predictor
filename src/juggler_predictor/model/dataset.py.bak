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
