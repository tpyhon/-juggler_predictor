"""ana-slo.com の URL 組立とフェッチオーケストレーション。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from juggler_predictor.scrape.http_client import AnaSloHTTPClient

logger = logging.getLogger(__name__)

BASE = "https://ana-slo.com"


@dataclass(frozen=True)
class AnaSloUrls:
    """ana-slo.com の URL 組み立て。

    日本語スラッグ (例: "キングno-1世田谷店") を渡すとパーセントエンコードして組み立てる。
    """

    base: str = BASE

    def home(self) -> str:
        return f"{self.base}/"

    def tokyo_index(self) -> str:
        # /ホールデータ/東京都/
        return f"{self.base}/{quote('ホールデータ')}/{quote('東京都')}/"

    def shop_index(self, shop_slug: str) -> str:
        # /ホールデータ/東京都/<slug>-データ一覧/
        return f"{self.base}/{quote('ホールデータ')}/{quote('東京都')}/{quote(shop_slug + '-データ一覧')}/"

    def shop_date(self, shop_slug: str, date_str: str) -> str:
        """``date_str`` は ``YYYY-MM-DD`` 形式。"""
        # /<YYYY-MM-DD>-<slug>-data/
        return f"{self.base}/{date_str}-{quote(shop_slug)}-data/"


def fetch_shop_date_html(
    client: AnaSloHTTPClient,
    *,
    shop_slug: str,
    date_str: str,
    urls: AnaSloUrls | None = None,
) -> str:
    """1 店舗 1 日分の HTML を返す。

    手順:
        1. 店舗一覧ページを GET (Referer はホーム)
        2. 日付詳細ページを GET (Referer は店舗一覧)
    """
    u = urls or AnaSloUrls()
    list_url = u.shop_index(shop_slug)
    detail_url = u.shop_date(shop_slug, date_str)

    logger.info("step1 list: %s", list_url)
    client.get(list_url, referer=u.home())

    logger.info("step2 detail: %s", detail_url)
    return client.get(detail_url, referer=list_url)
