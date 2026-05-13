"""ローカル朝バッチ本体: cf_clearance チェック → スクレイピング → Slack 通知。

Windows タスクスケジューラから run_local_morning.bat 経由で呼ばれる。
"""
from __future__ import annotations

import datetime as dt
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

_WARN_HOURS = 48  # 残り何時間未満で警告するか


def _check_cf_cookie() -> None:
    """cf_clearance の残り期限を確認し、不足なら Slack に警告する。"""
    from juggler_predictor.notify.slack import notify_slack
    from juggler_predictor.storage.r2 import build_r2_client_from_env

    try:
        r2 = build_r2_client_from_env()
        data = r2.get_json("auth/cf_cookies.json")
    except Exception as e:
        msg = f"[警告] cf_cookies.json の取得失敗: {e}\nスクレイピングが 403 で失敗する可能性があります。\n`refresh_cf_cookie.py` を実行してください。"
        logger.warning(msg)
        notify_slack(msg)
        return

    cookies = data.get("cookies", [])
    cf = next((c for c in cookies if c.get("name") == "cf_clearance"), None)

    if cf is None:
        msg = "[警告] cf_clearance cookie が R2 に存在しません。\n`refresh_cf_cookie.py` を実行してください。"
        logger.warning(msg)
        notify_slack(msg)
        return

    expires = cf.get("expires", -1)
    if expires and expires > 0:
        now = dt.datetime.now(tz=dt.timezone.utc).timestamp()
        remaining_h = (expires - now) / 3600
        exp_str = dt.datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M JST")
        if remaining_h < 0:
            msg = f"[警告] cf_clearance が失効しています（期限: {exp_str}）。\n今日のスクレイピングは失敗します。\n`refresh_cf_cookie.py` を今すぐ実行してください。"
            logger.warning(msg)
            notify_slack(msg)
        elif remaining_h < _WARN_HOURS:
            msg = f"[警告] cf_clearance の残り有効期限が {remaining_h:.1f} 時間です（期限: {exp_str}）。\n近日中に `refresh_cf_cookie.py` を実行してください。"
            logger.warning(msg)
            notify_slack(msg)
        else:
            logger.info("cf_clearance OK: 残り %.1f 時間 (期限: %s)", remaining_h, exp_str)
    else:
        # session cookie (expires=-1 or 0) は期限なしとみなす
        logger.info("cf_clearance: session cookie (期限なし) — OK")


def main() -> int:
    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    target_input_date = (date.today() - timedelta(days=1)).isoformat()
    logger.info("=" * 60)
    logger.info("Local Morning Batch start: scraping date=%s", target_input_date)
    logger.info("=" * 60)

    # 1. cf_clearance 期限チェック
    logger.info("--- cf_clearance 期限チェック ---")
    try:
        _check_cf_cookie()
    except Exception as e:
        logger.warning("cf_clearance チェック中に例外: %s", e)

    # 2. スクレイピング
    cmd_simple = [
        "uv", "run", "python",
        str(ROOT / "scripts" / "scrape_daily_all.py"),
        "--date", target_input_date,
        "--sleep", "3",
    ]
    cmd_fallback = [
        sys.executable, "-m", "uv", "run", "python",
        str(ROOT / "scripts" / "scrape_daily_all.py"),
        "--date", target_input_date,
        "--sleep", "3",
    ]

    rc = 1
    try:
        result = subprocess.run(cmd_simple, timeout=1800)
        rc = result.returncode
    except FileNotFoundError:
        logger.warning("uv not on PATH, fallback to python -m")
        result = subprocess.run(cmd_fallback, timeout=1800)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        logger.error("scrape_daily_all timed out")
        rc = 124

    # 3. Slack 通知
    try:
        from juggler_predictor.notify.slack import notify_slack
        if rc == 0:
            notify_slack(f"朝スクレイピング 完了 {target_input_date}")
        else:
            notify_slack(f":warning: 朝スクレイピング 失敗 (rc={rc}) {target_input_date}\nログ: logs/local_morning_*.log を確認してください。")
    except Exception as e:
        logger.warning("Slack 通知失敗: %s", e)

    logger.info("Local Morning Batch end: rc=%d", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
