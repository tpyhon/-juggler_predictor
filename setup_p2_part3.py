"""P2 Part 3: スクリプト群 + slug collector の生成。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# src/juggler_predictor/scrape/shop_slug_collector.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/shop_slug_collector.py"] = '''"""東京都ホール一覧ページから店舗 slug を抽出する。

ana-slo.com の各店舗一覧 URL は次のパターン:
    https://ana-slo.com/ホールデータ/東京都/<slug>-データ一覧/

ここから ``<slug>`` 部分（パーセントデコード済み日本語）を取り出す。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# /ホールデータ/東京都/<slug>-データ一覧/
SHOP_LIST_PATH_RE = re.compile(
    r"^/(?:ホールデータ|%E3%83%9B%E3%83%BC%E3%83%AB%E3%83%87%E3%83%BC%E3%82%BF)"
    r"/(?:東京都|%E6%9D%B1%E4%BA%AC%E9%83%BD)"
    r"/(.+?)-(?:データ一覧|%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%80%E8%A6%A7)/?$"
)


@dataclass(frozen=True)
class ShopCandidate:
    """店舗一覧から発見した候補。"""

    display_name: str  # アンカーテキスト
    slug: str          # URL から抽出したスラッグ (デコード済み)
    href: str          # 元 URL


def extract_shop_candidates(html: str, *, base_url: str = "https://ana-slo.com") -> list[ShopCandidate]:
    """東京都ホール一覧 HTML から店舗候補を抽出する。重複は除去 (slug 単位)。"""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[ShopCandidate] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 相対 / 絶対両対応
        path = urlparse(href).path or href
        m = SHOP_LIST_PATH_RE.match(path)
        if not m:
            continue
        slug_raw = m.group(1)
        slug = unquote(slug_raw)
        if slug in seen:
            continue
        seen.add(slug)

        text = a.get_text(strip=True)
        if not text:
            text = slug
        out.append(ShopCandidate(display_name=text, slug=slug, href=href))

    logger.info("店舗候補抽出: %d 件", len(out))
    return out
'''

# ---------------------------------------------------------------------------
# scripts/refresh_cf_cookie.py
# ---------------------------------------------------------------------------
FILES["scripts/refresh_cf_cookie.py"] = '''"""月 1 回手動: Cloudflare 通過済みクッキーを取得して R2 にアップロードする。

使い方:
    uv run python scripts/refresh_cf_cookie.py

挙動:
    1. Playwright (非ヘッドレス) で ana-slo.com を開く。
    2. 必要なら手動でチャレンジを通過 (最大 90 秒待機)。
    3. 取得した cookie を R2 (auth/cf_cookies.json と バックアップ) に保存。
    4. ローカル auth/cf_cookies.json にも保存 (デバッグ用)。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from juggler_predictor.common.logging import setup_logging
from juggler_predictor.scrape.ana_slo import AnaSloUrls
from juggler_predictor.scrape.playwright_fallback import acquire_cookies
from juggler_predictor.storage import R2Paths, build_r2_client_from_env
from juggler_predictor import AUTH_DIR

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    load_dotenv()

    urls = AnaSloUrls()
    home = urls.home()
    list_url = urls.shop_index("キングno-1世田谷店")
    target = urls.shop_date("キングno-1世田谷店", _yesterday())

    logger.info("[Step 1] Playwright でチャレンジ通過")
    result = acquire_cookies(
        home_url=home,
        list_url=list_url,
        target_url=target,
        headless=False,
        wait_seconds=90,
    )
    logger.info(
        "取得 cookie 数=%d ua_len=%d final_url=%s html_size=%d",
        len(result.cookies),
        len(result.user_agent),
        result.final_url,
        result.html_size,
    )

    has_cf = any(c.get("name") == "cf_clearance" for c in result.cookies)
    if not has_cf:
        logger.error("cf_clearance が取得できませんでした。チャレンジ通過に失敗。")
        return 1

    payload = {
        "cookies": result.cookies,
        "user_agent": result.user_agent,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }

    # ローカル保存
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    local_path = AUTH_DIR / "cf_cookies.json"
    local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("local saved: %s", local_path)

    # R2 アップロード
    logger.info("[Step 2] R2 アップロード")
    r2 = build_r2_client_from_env()
    r2.put_json(R2Paths.cf_cookie_latest(), payload)
    logger.info("uploaded: %s", R2Paths.cf_cookie_latest())

    backup_key = R2Paths.cf_cookie_backup(datetime.now().strftime("%Y%m%d"))
    r2.put_json(backup_key, payload)
    logger.info("backup uploaded: %s", backup_key)

    logger.info("[SUCCESS] cookie refresh 完了")
    return 0


def _yesterday() -> str:
    """JST の前日。月初・データ未更新を避けるため当日ではなく前日を狙う。"""
    from juggler_predictor.common.dates import today_jst, fmt_date
    from datetime import timedelta

    return fmt_date(today_jst() - timedelta(days=1))


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------------------
# scripts/collect_shop_slugs.py
# ---------------------------------------------------------------------------
FILES["scripts/collect_shop_slugs.py"] = '''"""東京一覧ページから店舗 slug を取得し、shops.yaml に書き戻す。

使い方:
    uv run python scripts/collect_shop_slugs.py            # ドライラン (差分表示のみ)
    uv run python scripts/collect_shop_slugs.py --apply    # shops.yaml を更新

挙動:
    1. R2 から最新クッキーを取得。
    2. curl_cffi で東京一覧ページを GET。
    3. <slug> を抽出。
    4. shops.yaml の各店舗 display_name と部分一致でマッチさせ、slug を埋める。
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


def main() -> int:
    setup_logging()
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="shops.yaml を実際に書き換える")
    args = parser.parse_args()

    # 1. クッキー取得
    logger.info("[1] R2 からクッキーを取得")
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    cookies = payload.get("cookies", [])
    ua = payload.get("user_agent")
    logger.info("cookies=%d ua_len=%d", len(cookies), len(ua or ""))

    # 2. 東京一覧 GET
    logger.info("[2] 東京一覧ページ GET")
    client = AnaSloHTTPClient(cookies=cookies, user_agent=ua)
    urls = AnaSloUrls()
    html = client.get(urls.tokyo_index(), referer=urls.home())
    logger.info("html size=%d", len(html))

    # 3. 候補抽出
    candidates = extract_shop_candidates(html)
    logger.info("候補数: %d", len(candidates))
    for c in candidates[:10]:
        logger.info("  - %s  (slug=%s)", c.display_name, c.slug)

    # 4. shops.yaml と突合
    shops_path = CONFIG_DIR / "shops.yaml"
    shops_doc = yaml.safe_load(shops_path.read_text(encoding="utf-8"))
    shops = shops_doc.get("shops", [])
    matched, unmatched = _match_slugs(shops, candidates)

    print()
    print("=" * 60)
    print(f"[結果] matched={len(matched)} / unmatched={len(unmatched)} / total={len(shops)}")
    print("=" * 60)
    for sid, slug in matched:
        print(f"  OK  {sid:30s} -> {slug}")
    for sid in unmatched:
        print(f"  --  {sid:30s} (slug が見つからず)")

    if not args.apply:
        print()
        print("[INFO] ドライラン。実際に書き戻すには --apply を付けて再実行してください。")
        return 0

    # 5. 書き戻し
    for shop in shops:
        sid = shop.get("id")
        for matched_id, slug in matched:
            if sid == matched_id:
                shop["slug"] = slug
                break
    shops_path.write_text(
        yaml.safe_dump(shops_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("[SUCCESS] shops.yaml を更新しました: %s", shops_path)
    return 0


def _match_slugs(
    shops: list[dict], candidates: list[ShopCandidate]
) -> tuple[list[tuple[str, str]], list[str]]:
    """display_name の部分一致で slug を割り当てる。"""
    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for shop in shops:
        sid = shop.get("id", "")
        name = shop.get("display_name", "")
        hit: str | None = None

        # 完全一致 → slug の一部に display_name が含まれる → 逆も
        for c in candidates:
            if c.display_name == name:
                hit = c.slug
                break
        if hit is None:
            # 表記ゆれ用に「No.1」などを除去して比較
            simplified = _simplify(name)
            for c in candidates:
                if _simplify(c.display_name) == simplified:
                    hit = c.slug
                    break
        if hit is None:
            simplified = _simplify(name)
            for c in candidates:
                if simplified and simplified in _simplify(c.slug):
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
        .lower()
    )


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------------------
# scripts/scrape_one.py
# ---------------------------------------------------------------------------
FILES["scripts/scrape_one.py"] = '''"""1 店舗 1 日分の HTML を取得 → パース → JSON 出力する PoC。

使い方:
    uv run python scripts/scrape_one.py --shop kingsetagaya --date 2026-05-05
    uv run python scripts/scrape_one.py --shop kingsetagaya --date 2026-05-05 --upload-raw
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR, DATA_DIR
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.common.shops import load_shops, get_shop
from juggler_predictor.scrape.ana_slo import AnaSloUrls, fetch_shop_date_html
from juggler_predictor.scrape.checker import check_parsed_page
from juggler_predictor.scrape.http_client import AnaSloHTTPClient
from juggler_predictor.scrape.parser import parse_ana_slo_html
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True, help="shops.yaml の id (例: kingsetagaya)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--upload-raw", action="store_true", help="生 HTML を R2 raw/ にアップロードする")
    args = ap.parse_args()

    # 1. shop 情報
    shops = load_shops(CONFIG_DIR / "shops.yaml")
    shop = get_shop(shops, args.shop)
    slug = getattr(shop, "slug", None) or shop.extra.get("slug") if hasattr(shop, "extra") else None
    if not slug:
        # Shop dataclass に slug がなければ raw dict から拾う
        raw = yaml.safe_load((CONFIG_DIR / "shops.yaml").read_text(encoding="utf-8"))
        for s in raw.get("shops", []):
            if s.get("id") == args.shop:
                slug = s.get("slug")
                break
    if not slug:
        logger.error("shop %s に slug が登録されていません。先に collect_shop_slugs を実行してください。", args.shop)
        return 1
    logger.info("shop=%s slug=%s display=%s", shop.id, slug, shop.display_name)

    # 2. クッキー
    logger.info("[1] R2 からクッキー取得")
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    cookies = payload.get("cookies", [])
    ua = payload.get("user_agent")

    # 3. fetch
    logger.info("[2] HTML 取得")
    client = AnaSloHTTPClient(cookies=cookies, user_agent=ua)
    html = fetch_shop_date_html(client, shop_slug=slug, date_str=args.date)
    logger.info("html size=%d", len(html))

    # 4. parse
    logger.info("[3] パース")
    machines_cfg = yaml.safe_load((CONFIG_DIR / "machines.yaml").read_text(encoding="utf-8"))
    page = parse_ana_slo_html(html, machines_config=machines_cfg)
    logger.info(
        "parsed: shop=%s date=%s juggler_rows=%d total_rows=%d",
        page.shop_display_name,
        page.date_str,
        len(page.rows),
        page.total_rows_in_table,
    )

    # 5. checker
    rep = check_parsed_page(page, shop_id=shop.id, date_str=args.date)
    logger.info("check ok=%s warnings=%s errors=%s", rep.ok, rep.warnings, rep.errors)

    # 6. ローカル出力
    out_dir = DATA_DIR / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{shop.id}_{args.date}.json"
    json_path.write_text(
        json.dumps(page.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[OK] JSON 保存: %s", json_path)

    html_path = out_dir / f"{shop.id}_{args.date}.html"
    Path(html_path).write_text(html, encoding="utf-8")
    logger.info("[OK] HTML 保存: %s", html_path)

    # 7. (任意) R2 raw アップロード
    if args.upload_raw:
        logger.info("[4] R2 raw/ にアップロード")
        r2.put_gzip_text(R2Paths.raw_html(shop.id, args.date), html)
        logger.info("uploaded: %s", R2Paths.raw_html(shop.id, args.date))

    # 8. 簡易サマリ
    print()
    print("=" * 60)
    print(f"[SUMMARY] {shop.display_name} {args.date}")
    print("=" * 60)
    print(f"  juggler_rows: {len(page.rows)}")
    print(f"  total_rows:   {page.total_rows_in_table}")
    print(f"  check.ok:     {rep.ok}")
    if rep.warnings:
        print(f"  warnings:     {rep.warnings}")
    if rep.errors:
        print(f"  errors:       {rep.errors}")
    print()
    print("=== ジャグラー台一覧 (先頭 10 件) ===")
    for row in page.rows[:10]:
        print(
            f"  {row.machine_name:25s} #{row.unit_number or '-':<5s} "
            f"G={row.g_count} BB={row.bb} RB={row.rb} diff={row.diff}"
        )
    return 0 if rep.ok else 2


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------------------
# tests/test_shop_slug_collector.py
# ---------------------------------------------------------------------------
FILES["tests/test_shop_slug_collector.py"] = '''"""shop_slug_collector のユニットテスト (HTTP 通信なし)。"""
from __future__ import annotations

from juggler_predictor.scrape.shop_slug_collector import extract_shop_candidates


SAMPLE_HTML = """
<html><body>
  <ul>
    <li><a href="/%E3%83%9B%E3%83%BC%E3%83%AB%E3%83%87%E3%83%BC%E3%82%BF/%E6%9D%B1%E4%BA%AC%E9%83%BD/%E3%82%AD%E3%83%B3%E3%82%B0no-1%E4%B8%96%E7%94%B0%E8%B0%B7%E5%BA%97-%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%80%E8%A6%A7/">キングNo.1世田谷店</a></li>
    <li><a href="https://ana-slo.com/ホールデータ/東京都/メッセ吉祥寺店-データ一覧/">メッセ吉祥寺店</a></li>
    <li><a href="/something-else/">無関係なリンク</a></li>
    <li><a href="/ホールデータ/東京都/メッセ吉祥寺店-データ一覧/">メッセ吉祥寺店 (重複)</a></li>
  </ul>
</body></html>
"""


def test_extracts_two_unique_shops() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    slugs = [c.slug for c in cands]
    assert "キングno-1世田谷店" in slugs
    assert "メッセ吉祥寺店" in slugs
    assert len(cands) == 2  # 重複は除去


def test_display_name_extracted() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    by_slug = {c.slug: c for c in cands}
    assert by_slug["キングno-1世田谷店"].display_name == "キングNo.1世田谷店"
    assert by_slug["メッセ吉祥寺店"].display_name == "メッセ吉祥寺店"


def test_irrelevant_links_ignored() -> None:
    cands = extract_shop_candidates(SAMPLE_HTML)
    for c in cands:
        assert "something-else" not in c.href


def test_empty_html_returns_empty() -> None:
    assert extract_shop_candidates("<html></html>") == []
'''


def main() -> None:
    print("=" * 60)
    print("P2 Part 3: scripts + slug collector")
    print("=" * 60)

    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")

    print()
    print("=" * 60)
    print("[SUCCESS] P2 Part 3 ファイル生成 完了")
    print("=" * 60)
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print()


if __name__ == "__main__":
    main()
