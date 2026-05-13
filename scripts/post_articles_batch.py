"""17店舗の記事を Note に一括投稿。

reports/{shop_id}_{date}.md を読み込んで Note API で順次投稿。
投稿間隔 5 秒、失敗時は記録して続行。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from juggler_predictor.note import NoteClient, markdown_to_note_html
from juggler_predictor.notify.slack import notify_slack

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SHOPS = ROOT / "config" / "shops.yaml"
REPORTS = ROOT / "reports"


def load_shops() -> list[dict]:
    data = yaml.safe_load(SHOPS.read_text(encoding="utf-8"))
    shops = data if isinstance(data, list) else data.get("shops", [])
    return [s for s in shops if isinstance(s, dict)]


def build_title(shop_display: str, target_date: str) -> str:
    return f"{shop_display} {target_date} 高設定期待度レポート"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="記事投稿日 YYYY-MM-DD (デフォルト: 今日)")
    ap.add_argument("--price", type=int, default=300)
    ap.add_argument("--sleep", type=float, default=5.0, help="投稿間 sleep 秒数")
    ap.add_argument("--shop", action="append", help="個別店舗指定 (複数可)")
    ap.add_argument("--dry-run", action="store_true", help="実際には投稿せず確認のみ")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    shops = load_shops()
    if args.shop:
        shops = [s for s in shops if s["id"] in args.shop]

    logger.info("投稿日=%s 店舗数=%d 価格=%d円 dry_run=%s", target_date, len(shops), args.price, args.dry_run)

    if not args.dry_run:
        client = NoteClient()
        client.login()
    else:
        client = None

    success: list[tuple[str, str]] = []
    failure: list[tuple[str, str]] = []

    for s in shops:
        sid = s["id"]
        display = s.get("display_name", sid)
        md_path = REPORTS / f"{sid}_{target_date}.md"
        if not md_path.exists():
            logger.warning("[SKIP] %s: %s なし", sid, md_path.name)
            failure.append((sid, "md not found"))
            continue

        body_md = md_path.read_text(encoding="utf-8")
        body_html = markdown_to_note_html(body_md)
        title = build_title(display, target_date)

        if args.dry_run:
            logger.info("[DRY] %s -> title=%s body=%d chars", sid, title, len(body_html))
            success.append((sid, "dry"))
            continue

        try:
            url = client.post(title=title, body_html=body_html, price=args.price)
            logger.info("[POSTED] %s -> %s", sid, url)
            success.append((sid, url))
        except Exception as e:
            logger.error("[FAIL] %s: %s", sid, e)
            failure.append((sid, str(e)))
        time.sleep(args.sleep)

    logger.info("=" * 50)
    logger.info("[POST SUMMARY] success=%d / failure=%d", len(success), len(failure))

    # Slack 通知
    msg_lines = [f"*Note 投稿結果* {target_date}", f"成功 {len(success)}件 / 失敗 {len(failure)}件"]
    if failure:
        msg_lines.append("失敗:")
        for sid, reason in failure[:5]:
            msg_lines.append(f"  - {sid}: {reason[:80]}")
    notify_slack("\n".join(msg_lines))

    return 0 if not failure else 1


if __name__ == "__main__":
    sys.exit(main())
