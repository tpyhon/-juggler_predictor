"""ローカル朝バッチ本体: スクレイピングのみ実行し Slack 通知。

Windows タスクスケジューラから run_local_morning.bat 経由で呼ばれる。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    target_input_date = (date.today() - timedelta(days=1)).isoformat()
    logger.info("=" * 60)
    logger.info("Local Morning Batch start: scraping date=%s", target_input_date)
    logger.info("=" * 60)

    cmd = [
        sys.executable,
        "-m",
        "uv",
        "run",
        "python",
        str(ROOT / "scripts" / "scrape_daily_all.py"),
        "--date",
        target_input_date,
        "--sleep",
        "3",
    ]
    # uv が PATH にあれば直接呼んだ方が確実
    cmd_simple = [
        "uv",
        "run",
        "python",
        str(ROOT / "scripts" / "scrape_daily_all.py"),
        "--date",
        target_input_date,
        "--sleep",
        "3",
    ]

    rc = 1
    try:
        result = subprocess.run(cmd_simple, timeout=1800)  # 30 分
        rc = result.returncode
    except FileNotFoundError:
        logger.warning("uv not on PATH, fallback to python -m")
        result = subprocess.run(cmd, timeout=1800)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        logger.error("scrape_daily_all timed out")
        rc = 124

    # Slack 通知 (.env に SLACK_WEBHOOK_URL があれば)
    try:
        from juggler_predictor.notify.slack import notify_slack
        if rc == 0:
            notify_slack(f"ローカル朝スクレイピング 成功 {target_input_date}")
        else:
            notify_slack(f"ローカル朝スクレイピング 失敗 (rc={rc}) {target_input_date}")
    except Exception as e:
        logger.warning("Slack 通知失敗: %s", e)

    logger.info("Local Morning Batch end: rc=%d", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
