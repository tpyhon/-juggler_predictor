"""17店舗の前日分を一括スクレイピング (GitHub Actions 用)。

scrape_one.py を subprocess で店舗ごとに呼び出す。
失敗店舗はログに記録して続行。
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SHOPS = ROOT / "config" / "shops.yaml"


def load_shops() -> list[dict]:
    data = yaml.safe_load(SHOPS.read_text(encoding="utf-8"))
    shops = data if isinstance(data, list) else data.get("shops", [])
    return [s for s in shops if isinstance(s, dict)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (デフォルト: 昨日)")
    ap.add_argument("--sleep", type=float, default=3.0, help="店舗間 sleep 秒数")
    ap.add_argument("--shop", action="append", help="個別店舗指定 (複数可)")
    args = ap.parse_args()

    if args.date:
        target_date = args.date
    else:
        target_date = (date.today() - timedelta(days=1)).isoformat()

    shops = load_shops()
    if args.shop:
        shops = [s for s in shops if s["id"] in args.shop]

    logger.info("対象日: %s, 店舗数: %d", target_date, len(shops))

    success: list[str] = []
    failure: list[tuple[str, str]] = []

    for s in shops:
        sid = s["id"]
        logger.info("--- %s (%s) ---", sid, s.get("display_name", ""))
        cmd = [
            sys.executable,
            "-m",
            "scripts.scrape_one",
        ]
        # uv run python scripts/scrape_one.py 形式に変更
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "scrape_one.py"),
            "--shop",
            sid,
            "--date",
            target_date,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info("[OK] %s", sid)
                success.append(sid)
            else:
                logger.error("[FAIL] %s rc=%d", sid, result.returncode)
                logger.error("stderr: %s", result.stderr[-500:])
                failure.append((sid, f"rc={result.returncode}"))
        except subprocess.TimeoutExpired:
            logger.error("[TIMEOUT] %s", sid)
            failure.append((sid, "timeout"))
        except Exception as e:
            logger.error("[ERROR] %s: %s", sid, e)
            failure.append((sid, str(e)))
        time.sleep(args.sleep)

    logger.info("=" * 50)
    logger.info("[SCRAPE SUMMARY] success=%d / failure=%d", len(success), len(failure))
    if failure:
        for sid, reason in failure:
            logger.warning("  FAIL %s: %s", sid, reason)
    return 0 if not failure else 1


if __name__ == "__main__":
    sys.exit(main())
