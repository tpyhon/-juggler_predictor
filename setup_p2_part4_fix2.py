"""P2 Part 4 fix v2: scrape_one.py を shops.py の現行 I/F に合わせる。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scripts" / "scrape_one.py"

NEW_CONTENT = '''"""1 店舗 1 日分の HTML を取得 → パース → JSON 出力する PoC。

使い方:
    uv run python scripts/scrape_one.py --shop kingsetagaya --date 2026-05-05
    uv run python scripts/scrape_one.py --shop kingsetagaya --date 2026-05-05 --upload-raw
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR, DATA_DIR
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.common.shops import get_shop
from juggler_predictor.scrape.ana_slo import fetch_shop_date_html
from juggler_predictor.scrape.checker import check_parsed_page
from juggler_predictor.scrape.http_client import AnaSloHTTPClient
from juggler_predictor.scrape.parser import parse_ana_slo_html
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

logger = logging.getLogger(__name__)


def _lookup_slug(shop_id: str) -> str | None:
    """shops.yaml から slug を直接拾う (Shop dataclass に slug が無いため)。"""
    raw = yaml.safe_load((CONFIG_DIR / "shops.yaml").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("shops", [])
    for s in items or []:
        if s.get("id") == shop_id:
            return s.get("slug")
    return None


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True, help="shops.yaml の id (例: kingsetagaya)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--upload-raw", action="store_true", help="生 HTML を R2 raw/ にアップロード")
    args = ap.parse_args()

    # 1. shop 情報
    shop = get_shop(args.shop)
    slug = _lookup_slug(args.shop)
    if not slug:
        logger.error(
            "shop %s に slug が登録されていません。先に scripts/collect_shop_slugs.py --apply を実行してください。",
            args.shop,
        )
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
    html_path.write_text(html, encoding="utf-8")
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
            f"  {row.machine_name:25s} #{(row.unit_number or '-'):<5s} "
            f"G={row.g_count} BB={row.bb} RB={row.rb} diff={row.diff}"
        )
    return 0 if rep.ok else 2


if __name__ == "__main__":
    sys.exit(main())
'''


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(NEW_CONTENT, encoding="utf-8", newline="\n")
    print(f"[WRITE] {TARGET.relative_to(ROOT)}  ({len(NEW_CONTENT):,} chars)")
    print("[OK] scrape_one.py を修正しました")
    print()
    print("次のコマンド:")
    print("  uv run python scripts/scrape_one.py --shop kingsetagaya --date 2026-05-05")


if __name__ == "__main__":
    main()
