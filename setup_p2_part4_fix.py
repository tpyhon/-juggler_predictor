"""P2 Part 4 fix: slug 抽出ロジックと shops.yaml 入出力を実 HTML 仕様に合わせる。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# scrape/shop_slug_collector.py  (大文字/小文字 hex 両対応 + 区名拾い)
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/shop_slug_collector.py"] = '''"""東京都ホール一覧ページから店舗 slug を抽出する。

ana-slo.com の店舗一覧 URL パターン:
    https://ana-slo.com/ホールデータ/東京都/<slug>-データ一覧/

URL は実際には %e3%83%9b... (小文字 hex) または %E3%83%9B... (大文字 hex) の
パーセントエンコード形式で入っているため正規表現は両対応にする。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# パーセントエンコードされた "ホールデータ" / "東京都" / "データ一覧"
# 大文字 hex / 小文字 hex の両方を許容する
_HOLE_DATA_ENC = "(?:ホールデータ|(?:%[0-9a-fA-F]{2}){5,})"
_TOKYO_ENC = "(?:東京都|(?:%[0-9a-fA-F]{2}){3,})"
_LIST_SUFFIX_ENC = "(?:データ一覧|(?:%[0-9a-fA-F]{2}){3,})"

SHOP_LIST_PATH_RE = re.compile(
    rf"^/{_HOLE_DATA_ENC}/{_TOKYO_ENC}/(.+?)-{_LIST_SUFFIX_ENC}/?$"
)


@dataclass(frozen=True)
class ShopCandidate:
    """店舗一覧から発見した候補。"""

    display_name: str
    slug: str
    href: str
    ward: str | None = None  # 区名 (取得できれば)


def extract_shop_candidates(
    html: str, *, base_url: str = "https://ana-slo.com"
) -> list[ShopCandidate]:
    """東京都ホール一覧 HTML から店舗候補を抽出する。slug 単位で重複除去。"""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[ShopCandidate] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = urlparse(href).path or href
        m = SHOP_LIST_PATH_RE.match(path)
        if not m:
            continue
        slug_raw = m.group(1)
        # "ホールデータ" / "東京都" を含むスラッグ部分は本当は来ないはずだが、
        # 念のため空判定する
        if not slug_raw:
            continue
        slug = unquote(slug_raw)
        if slug in seen:
            continue
        seen.add(slug)

        text = a.get_text(strip=True) or slug
        ward = _find_ward_for_anchor(a)
        out.append(ShopCandidate(display_name=text, slug=slug, href=href, ward=ward))

    logger.info("店舗候補抽出: %d 件", len(out))
    return out


def _find_ward_for_anchor(anchor) -> str | None:
    """同じ table-row 内の隣セルから区名を拾う。

    HTML 構造例:
        <div class="table-row">
          <div class="table-data-cell"><a href="...">店舗名</a></div>
          <div class="table-data-cell">世田谷区</div>
        </div>
    """
    row = anchor
    for _ in range(4):  # 4 階層上まで遡る
        if row is None:
            break
        try:
            classes = row.get("class") or []
        except Exception:
            classes = []
        if "table-row" in classes:
            cells = row.find_all("div", class_="table-data-cell")
            for c in cells:
                txt = c.get_text(strip=True)
                if txt and txt.endswith(("区", "市", "町", "村")) and len(txt) <= 8:
                    return txt
            return None
        row = row.parent
    return None
'''

# ---------------------------------------------------------------------------
# scripts/collect_shop_slugs.py  (shops.yaml が list/dict 両対応)
# ---------------------------------------------------------------------------
FILES["scripts/collect_shop_slugs.py"] = '''"""東京一覧ページから店舗 slug を取得し、shops.yaml に書き戻す。

shops.yaml は以下のいずれかの形式に対応:
    a) トップレベル list:        [{id: ..., display_name: ...}, ...]
    b) トップレベル dict:        {shops: [{id: ..., ...}, ...]}

使い方:
    uv run python scripts/collect_shop_slugs.py            # ドライラン
    uv run python scripts/collect_shop_slugs.py --apply    # 実際に書き戻す
"""
from __future__ import annotations

import argparse
import logging
import sys

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.scrape.ana_slo import AnaSloUrls
from juggler_predictor.scrape.http_client import AnaSloHTTPClient
from juggler_predictor.scrape.shop_slug_collector import (
    ShopCandidate,
    extract_shop_candidates,
)
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

logger = logging.getLogger(__name__)


def _read_shops_doc(path) -> tuple[list[dict], object]:
    """shops.yaml を読み、 (shops_list, original_doc) を返す。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc, doc
    if isinstance(doc, dict) and isinstance(doc.get("shops"), list):
        return doc["shops"], doc
    raise RuntimeError(f"shops.yaml の形式が不明: top={type(doc)}")


def _write_shops_doc(path, original_doc, shops_list: list[dict]) -> None:
    """元の構造を保ったまま書き戻す。"""
    if isinstance(original_doc, list):
        out = shops_list
    else:
        original_doc["shops"] = shops_list
        out = original_doc
    path.write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> int:
    setup_logging()
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="shops.yaml を実際に書き換える")
    args = parser.parse_args()

    logger.info("[1] R2 からクッキーを取得")
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    cookies = payload.get("cookies", [])
    ua = payload.get("user_agent")
    logger.info("cookies=%d ua_len=%d", len(cookies), len(ua or ""))

    logger.info("[2] 東京一覧ページ GET")
    client = AnaSloHTTPClient(cookies=cookies, user_agent=ua)
    urls = AnaSloUrls()
    html = client.get(urls.tokyo_index(), referer=urls.home())
    logger.info("html size=%d", len(html))

    candidates = extract_shop_candidates(html)
    logger.info("候補数: %d", len(candidates))
    print()
    print("=== 抽出された候補 (先頭 30 件) ===")
    for c in candidates[:30]:
        print(f"  {c.display_name:35s}  ward={c.ward or '-':6s}  slug={c.slug}")
    print()

    shops_path = CONFIG_DIR / "shops.yaml"
    shops, doc = _read_shops_doc(shops_path)

    matched, unmatched = _match_slugs(shops, candidates)

    print("=" * 60)
    print(f"[結果] matched={len(matched)} / unmatched={len(unmatched)} / total={len(shops)}")
    print("=" * 60)
    for sid, slug in matched:
        print(f"  OK  {sid:30s} -> {slug}")
    for sid in unmatched:
        print(f"  --  {sid:30s} (slug が見つからず)")

    if not args.apply:
        print()
        print("[INFO] ドライラン。--apply で書き戻し。")
        return 0

    matched_map = dict(matched)
    for shop in shops:
        sid = shop.get("id")
        if sid in matched_map:
            shop["slug"] = matched_map[sid]
    _write_shops_doc(shops_path, doc, shops)
    logger.info("[SUCCESS] shops.yaml を更新しました: %s", shops_path)
    return 0


def _match_slugs(
    shops: list[dict], candidates: list[ShopCandidate]
) -> tuple[list[tuple[str, str]], list[str]]:
    """display_name から slug を割り当てる。"""
    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for shop in shops:
        sid = shop.get("id", "")
        name = shop.get("display_name", "")
        hit: str | None = None

        # 段階的に緩和してマッチ
        for c in candidates:
            if c.display_name == name:
                hit = c.slug
                break
        if hit is None:
            simp_name = _simplify(name)
            for c in candidates:
                if _simplify(c.display_name) == simp_name:
                    hit = c.slug
                    break
        if hit is None:
            simp_name = _simplify(name)
            for c in candidates:
                if simp_name and simp_name in _simplify(c.slug):
                    hit = c.slug
                    break
        if hit is None:
            simp_name = _simplify(name)
            for c in candidates:
                if simp_name and _simplify(c.display_name) and (
                    simp_name in _simplify(c.display_name)
                    or _simplify(c.display_name) in simp_name
                ):
                    hit = c.slug
                    break

        if hit:
            matched.append((sid, hit))
        else:
            unmatched.append(sid)
    return matched, unmatched


def _simplify(s: str) -> str:
    return (
        s.replace("No.", "no")
        .replace("NO.", "no")
        .replace(".", "")
        .replace(" ", "")
        .replace("　", "")
        .replace("・", "")
        .lower()
    )


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------------------
# tests/test_shop_slug_collector.py  (実 HTML 形式の小文字 hex も検証)
# ---------------------------------------------------------------------------
FILES["tests/test_shop_slug_collector.py"] = '''"""shop_slug_collector のユニットテスト (HTTP 通信なし)。"""
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
'''


def main() -> None:
    print("=" * 60)
    print("P2 Part 4 fix: slug 抽出 + shops.yaml list 形式対応")
    print("=" * 60)
    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")
    print()
    print("[OK] 修正完了")
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print("  uv run python scripts/collect_shop_slugs.py")


if __name__ == "__main__":
    main()
