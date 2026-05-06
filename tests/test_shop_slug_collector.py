"""shop_slug_collector のユニットテスト (HTTP 通信なし)。"""
from __future__ import annotations

from juggler_predictor.scrape.shop_slug_collector import extract_shop_candidates


# 実 HTML と同じく小文字 hex でパーセントエンコードされた href を含む
SAMPLE_HTML = """
<html><body>
  <div class="table-row">
    <div class="table-data-cell"><a href="https://ana-slo.com/%e3%83%9b%e3%83%bc%e3%83%ab%e3%83%87%e3%83%bc%e3%82%bf/%e6%9d%b1%e4%ba%ac%e9%83%bd/%e3%82%ad%e3%83%b3%e3%82%b0no-1%e4%b8%96%e7%94%b0%e8%b0%b7%e5%ba%97-%e3%83%87%e3%83%bc%e3%82%bf%e4%b8%80%e8%a6%a7/">キングNo.1世田谷店</a></div>
    <div class="table-data-cell">世田谷区</div>
  </div>
  <div class="table-row">
    <div class="table-data-cell"><a href="https://ana-slo.com/ホールデータ/東京都/メッセ吉祥寺店-データ一覧/">メッセ吉祥寺店</a></div>
    <div class="table-data-cell">武蔵野市</div>
  </div>
  <div class="table-row">
    <div class="table-data-cell"><a href="/something-else/">無関係</a></div>
  </div>
  <div class="table-row">
    <div class="table-data-cell"><a href="/%e3%83%9b%e3%83%bc%e3%83%ab%e3%83%87%e3%83%bc%e3%82%bf/%e6%9d%b1%e4%ba%ac%e9%83%bd/%e3%83%a1%e3%83%83%e3%82%bb%e5%90%89%e7%a5%a5%e5%af%ba%e5%ba%97-%e3%83%87%e3%83%bc%e3%82%bf%e4%b8%80%e8%a6%a7/">メッセ吉祥寺店 (重複)</a></div>
  </div>
</body></html>
"""


def test_extracts_two_unique_shops() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    slugs = [c.slug for c in cands]
    assert "キングno-1世田谷店" in slugs
    assert "メッセ吉祥寺店" in slugs
    assert len(cands) == 2


def test_display_name_extracted() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    by_slug = {c.slug: c for c in cands}
    assert by_slug["キングno-1世田谷店"].display_name == "キングNo.1世田谷店"
    assert by_slug["メッセ吉祥寺店"].display_name == "メッセ吉祥寺店"


def test_ward_extracted() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    by_slug = {c.slug: c for c in cands}
    assert by_slug["キングno-1世田谷店"].ward == "世田谷区"
    assert by_slug["メッセ吉祥寺店"].ward == "武蔵野市"


def test_irrelevant_links_ignored() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    for c in cands:
        assert "something-else" not in c.href


def test_empty_html_returns_empty() -> None:
    assert extract_shop_candidates("<html></html>") == []
