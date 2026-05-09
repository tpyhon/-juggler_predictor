"""ローカル朝バッチ本体: スクレイピングのみ実行。

Windows タスクスケジューラから run_local_morning.bat 経由で呼ばれる。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def check_cf_cookie() -> tuple[bool, str]:
    """cf_clearance の有効期限をチェック。
    
    Returns:
        (is_valid, message): 24時間以上残っていれば True
    """
    cookie_path = ROOT / "auth" / "cf_cookies.json"
    if not cookie_path.exists():
        return False, f"cf_cookies.json が見つかりません: {cookie_path}"
    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        cf = next((c for c in cookies if c.get("name") == "cf_clearance"), None)
        if not cf:
            return False, "cf_clearance cookie が見つかりません"
        expires = cf.get("expires")
        if not expires:
            return False, "cf_clearance に expires がありません"
        # expires は数値（unix timestamp）または ISO 文字列
        if isinstance(expires, (int, float)):
            exp_dt = datetime.fromtimestamp(expires, tz=timezone.utc)
        else:
            exp_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        remaining = exp_dt - datetime.now(timezone.utc)
        msg = f"cf_clearance 残り {remaining}"
        if remaining < timedelta(hours=24):
            return False, f"{msg} (24時間未満、要更新)"
        return True, msg
    except Exception as e:
        return False, f"cf cookie チェック失敗: {e}"


def main() -> int:
    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    target_input_date = (date.today() - timedelta(days=1)).isoformat()
    logger.info("=" * 60)
    logger.info("Local Morning Batch start: scraping date=%s", target_input_date)
    logger.info("=" * 60)

    # cf cookie 事前チェック
    cf_ok, cf_msg = check_cf_cookie()
    logger.info("cf cookie status: %s", cf_msg)
    if not cf_ok:
        logger.warning("cf cookie が無効または期限切れ間近。スクレイピング失敗の可能性あり。")
        logger.warning("手動で `uv run python scripts/refresh_cf_cookie.py` を実行してください。")

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

    logger.info("Local Morning Batch end: rc=%d", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
