"""過去 N 日 × 全店舗の bootstrap 取得スクリプト。

使い方:
    # 1 店舗 過去 7 日
    uv run python scripts/bootstrap.py --shop kingsetagaya --days 7

    # 全店舗 過去 60 日 (本番)
    uv run python scripts/bootstrap.py --all --days 60

    # 取得済みも上書き
    uv run python scripts/bootstrap.py --all --days 60 --no-skip

    # スリープ間隔を変える
    uv run python scripts/bootstrap.py --all --days 60 --sleep 1.5
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import timedelta

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR
from juggler_predictor.common.dates import fmt_date, today_jst
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.pipeline.ingest_one import ingest_one
from juggler_predictor.scrape.http_client import AnaSloHTTPClient, CloudflareBlocked
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

logger = logging.getLogger(__name__)


def _load_shops_with_slug() -> list[dict]:
    raw = yaml.safe_load((CONFIG_DIR / "shops.yaml").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("shops", [])
    return [s for s in (items or []) if s.get("slug")]


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--shop", help="単一店舗の id")
    g.add_argument("--all", action="store_true", help="shops.yaml の全店舗")
    ap.add_argument("--days", type=int, default=7, help="過去何日 (今日含まず)")
    ap.add_argument("--start", help="開始日 YYYY-MM-DD (--days より優先)")
    ap.add_argument("--end", help="終了日 YYYY-MM-DD (--days より優先)")
    ap.add_argument("--sleep", type=float, default=1.0, help="1 リクエストごとのスリープ秒")
    ap.add_argument("--no-skip", action="store_true", help="取得済みもスキップしない")
    args = ap.parse_args()

    # 1. 対象店舗
    shops = _load_shops_with_slug()
    if args.shop:
        shops = [s for s in shops if s.get("id") == args.shop]
        if not shops:
            logger.error("shop=%s が shops.yaml に無い、または slug 未設定", args.shop)
            return 1
    if not shops:
        logger.error("対象店舗ゼロ。shops.yaml に slug が入っているか確認してください。")
        return 1

    # 2. 対象期間
    if args.start and args.end:
        from juggler_predictor.common.dates import parse_date_any, range_dates
        start = parse_date_any(args.start)
        end = parse_date_any(args.end)
        dates = [fmt_date(d) for d in range_dates(start, end)]
    else:
        end = today_jst() - timedelta(days=1)  # 昨日まで
        start = end - timedelta(days=args.days - 1)
        dates = [fmt_date(start + timedelta(days=i)) for i in range((end - start).days + 1)]

    logger.info("対象店舗: %d 件", len(shops))
    logger.info("対象期間: %s - %s (%d 日)", dates[0], dates[-1], len(dates))
    logger.info("総タスク: %d 件", len(shops) * len(dates))

    # 3. クッキー & クライアント
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    client = AnaSloHTTPClient(
        cookies=payload.get("cookies", []),
        user_agent=payload.get("user_agent"),
    )
    machines_cfg = yaml.safe_load((CONFIG_DIR / "machines.yaml").read_text(encoding="utf-8"))

    # 4. ループ
    counts: dict[str, int] = {"ok": 0, "skip_existing": 0, "miss": 0, "error": 0}
    total = len(shops) * len(dates)
    done = 0
    cf_blocked = False

    try:
        for shop in shops:
            for d in dates:
                done += 1
                try:
                    result = ingest_one(
                        r2=r2,
                        client=client,
                        shop_id=shop["id"],
                        shop_slug=shop["slug"],
                        date_str=d,
                        machines_config=machines_cfg,
                        skip_if_exists=not args.no_skip,
                    )
                except CloudflareBlocked as e:
                    logger.error("[CF BLOCKED] %s -- 処理を中断します", e)
                    cf_blocked = True
                    break

                counts[result.status] = counts.get(result.status, 0) + 1
                logger.info(
                    "[%4d/%4d] %s %s -> %s (juggler=%d size=%d)",
                    done, total, shop["id"], d, result.status,
                    result.juggler_rows, result.html_size,
                )

                if result.status not in ("skip_existing",) and args.sleep > 0:
                    time.sleep(args.sleep)
            if cf_blocked:
                break
    except KeyboardInterrupt:
        logger.warning("ユーザ中断")

    # 5. サマリ
    print()
    print("=" * 60)
    print("[BOOTSTRAP SUMMARY]")
    print("=" * 60)
    print(f"  ok           : {counts.get('ok', 0)}")
    print(f"  skip_existing: {counts.get('skip_existing', 0)}")
    print(f"  miss         : {counts.get('miss', 0)}")
    print(f"  error        : {counts.get('error', 0)}")
    print(f"  total        : {total}")
    print(f"  cf_blocked   : {cf_blocked}")
    print()
    return 0 if not cf_blocked else 2


if __name__ == "__main__":
    sys.exit(main())
