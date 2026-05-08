"""17店舗の記事を一括生成 (GitHub Actions 用)。

generate_article.py を import して直接呼び出すのではなく subprocess で実行。
理由: メモリリークやモデル読み込みエラーが起きても他店舗に波及しない。
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SHOPS = ROOT / "config" / "shops.yaml"
REPORTS = ROOT / "reports"


def load_shops() -> list[dict]:
    data = yaml.safe_load(SHOPS.read_text(encoding="utf-8"))
    shops = data if isinstance(data, list) else data.get("shops", [])
    return [s for s in shops if isinstance(s, dict)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="記事投稿日 YYYY-MM-DD (デフォルト: 今日)")
    ap.add_argument("--shop", action="append", help="個別店舗指定 (複数可)")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    shops = load_shops()
    if args.shop:
        shops = [s for s in shops if s["id"] in args.shop]

    logger.info("記事投稿日: %s, 店舗数: %d", target_date, len(shops))
    REPORTS.mkdir(parents=True, exist_ok=True)

    success: list[str] = []
    failure: list[tuple[str, str]] = []

    for s in shops:
        sid = s["id"]
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "generate_article.py"),
            "--shop",
            sid,
            "--date",
            target_date,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, encoding='utf-8', errors='replace')
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

    logger.info("=" * 50)
    logger.info("[GENERATE SUMMARY] success=%d / failure=%d", len(success), len(failure))
    if failure:
        for sid, reason in failure:
            logger.warning("  FAIL %s: %s", sid, reason)
    return 0 if not failure else 1


if __name__ == "__main__":
    sys.exit(main())
