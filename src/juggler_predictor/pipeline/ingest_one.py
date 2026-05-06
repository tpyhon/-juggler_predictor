"""1 店舗 1 日分の取り込み処理を関数化したもの。

bootstrap.py / ingest.py の両方から再利用される。
- raw HTML を取得 -> R2 raw/ に gzip 保存
- パース -> R2 dataset/ に gzip-JSON 保存
- マーカー (ok / miss) を R2 markers/ に書く
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from juggler_predictor.scrape.ana_slo import fetch_shop_date_html
from juggler_predictor.scrape.checker import check_parsed_page
from juggler_predictor.scrape.http_client import (
    AnaSloHTTPClient,
    CloudflareBlocked,
    HTTPError,
)
from juggler_predictor.scrape.parser import parse_ana_slo_html
from juggler_predictor.storage import R2Client, R2Paths

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    shop_id: str
    date_str: str
    status: str  # "ok" | "skip_existing" | "miss" | "error" | "cf_blocked"
    juggler_rows: int = 0
    total_rows: int = 0
    html_size: int = 0
    message: str = ""


def ingest_one(
    *,
    r2: R2Client,
    client: AnaSloHTTPClient,
    shop_id: str,
    shop_slug: str,
    date_str: str,
    machines_config: dict[str, Any],
    skip_if_exists: bool = True,
    upload_raw: bool = True,
    upload_dataset: bool = True,
) -> IngestResult:
    """1 店舗 1 日分の取り込み。

    例外送出:
        - :class:`CloudflareBlocked` のみ呼び出し元に再送出する。これは
          全体停止すべき致命的状態のため。それ以外は IngestResult に詰めて返す。
    """
    raw_key = R2Paths.raw_html(shop_id, date_str)
    ds_key = R2Paths.dataset_json(shop_id, date_str)
    ok_marker = R2Paths.ingest_marker(shop_id, date_str)
    miss_marker = ok_marker.replace(".ok", ".miss")

    # 1. 既存スキップ
    if skip_if_exists and r2.exists(ok_marker):
        return IngestResult(shop_id, date_str, "skip_existing", message="ok marker 存在")
    if skip_if_exists and r2.exists(miss_marker):
        return IngestResult(shop_id, date_str, "skip_existing", message="miss marker 存在")

    # 2. fetch
    try:
        html = fetch_shop_date_html(client, shop_slug=shop_slug, date_str=date_str)
    except CloudflareBlocked:
        # cf_clearance 失効 -> 全体を止める
        raise
    except HTTPError as e:
        msg = str(e)
        if "404" in msg or "410" in msg:
            # データ無し: miss marker
            r2.put_bytes(miss_marker, b"miss")
            logger.info("miss: shop=%s date=%s", shop_id, date_str)
            return IngestResult(shop_id, date_str, "miss", message=msg)
        logger.warning("HTTP error: shop=%s date=%s err=%s", shop_id, date_str, e)
        return IngestResult(shop_id, date_str, "error", message=msg)

    html_size = len(html)

    # 3. parse + check
    page = parse_ana_slo_html(html, machines_config=machines_config)
    rep = check_parsed_page(page, shop_id=shop_id, date_str=date_str)

    if not rep.ok:
        logger.warning(
            "check 失敗 shop=%s date=%s errors=%s", shop_id, date_str, rep.errors
        )
        return IngestResult(
            shop_id, date_str, "error",
            juggler_rows=len(page.rows),
            total_rows=page.total_rows_in_table,
            html_size=html_size,
            message=f"check.errors={rep.errors}",
        )

    # 4. R2 アップロード
    if upload_raw:
        r2.put_gzip_text(raw_key, html)
    if upload_dataset:
        r2.put_json(ds_key, page.to_dict(), gzipped=True)
    r2.put_bytes(ok_marker, b"ok")

    logger.info(
        "ok shop=%s date=%s juggler=%d total=%d size=%d",
        shop_id, date_str, len(page.rows), page.total_rows_in_table, html_size,
    )
    return IngestResult(
        shop_id, date_str, "ok",
        juggler_rows=len(page.rows),
        total_rows=page.total_rows_in_table,
        html_size=html_size,
    )
