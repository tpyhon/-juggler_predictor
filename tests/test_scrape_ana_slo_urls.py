"""AnaSloUrls の URL 組立テスト。"""
from __future__ import annotations

from juggler_predictor.scrape.ana_slo import AnaSloUrls


def test_home_url() -> None:
    assert AnaSloUrls().home() == "https://ana-slo.com/"


def test_tokyo_index_is_percent_encoded() -> None:
    url = AnaSloUrls().tokyo_index()
    assert url.startswith("https://ana-slo.com/")
    assert "%E3%83%9B%E3%83%BC%E3%83%AB" in url  # ホール
    assert url.endswith("/")


def test_shop_index_contains_slug() -> None:
    url = AnaSloUrls().shop_index("キングno-1世田谷店")
    # スラッグも一覧サフィックスもパーセントエンコードされる
    assert "no-1" in url.lower()
    assert url.startswith("https://ana-slo.com/")
    assert url.endswith("/")


def test_shop_date_url_pattern() -> None:
    url = AnaSloUrls().shop_date("キングno-1世田谷店", "2026-05-05")
    # 日付がそのまま (エンコードなし) で入る
    assert "/2026-05-05-" in url
    assert url.endswith("-data/")
