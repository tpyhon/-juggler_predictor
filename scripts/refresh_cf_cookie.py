"""月 1 回手動: Cloudflare 通過済みクッキーを取得して R2 にアップロードする。

使い方:
    uv run python scripts/refresh_cf_cookie.py

挙動:
    1. Playwright (非ヘッドレス) で ana-slo.com のホームを開く。
    2. ユーザが「ホールデータ→東京都→店舗→日付」と手動でクリック。
    3. 日付詳細 (/YYYY-MM-DD-{slug}-data/) に到達した時点で cookie 回収。
    4. R2 の auth/cf_cookies.json と auth/cf_cookies_YYYYMMDD.json に保存。
    5. ローカル auth/cf_cookies.json にも保存 (デバッグ用)。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from juggler_predictor.common.logging import setup_logging
from juggler_predictor.scrape.playwright_fallback import acquire_cookies_manual
from juggler_predictor.storage import R2Paths, build_r2_client_from_env
from juggler_predictor import AUTH_DIR

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    load_dotenv()

    logger.info("[Step 1] Playwright で手動誘導 cookie 取得")
    result = acquire_cookies_manual(
        home_url="https://ana-slo.com/",
        headless=False,
        max_wait_seconds=240,
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
        logger.error("cf_clearance が取得できませんでした。")
        return 1

    if "-data" not in result.final_url:
        logger.warning(
            "最終 URL が日付詳細ページではありません: %s。"
            " 取得した cookie のスコープが不十分な可能性があります。",
            result.final_url,
        )

    payload = {
        "cookies": result.cookies,
        "user_agent": result.user_agent,
        "final_url": result.final_url,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }

    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    local_path = AUTH_DIR / "cf_cookies.json"
    local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("local saved: %s", local_path)

    logger.info("[Step 2] R2 アップロード")
    r2 = build_r2_client_from_env()
    r2.put_json(R2Paths.cf_cookie_latest(), payload)
    logger.info("uploaded: %s", R2Paths.cf_cookie_latest())

    backup_key = R2Paths.cf_cookie_backup(datetime.now().strftime("%Y%m%d"))
    r2.put_json(backup_key, payload)
    logger.info("backup uploaded: %s", backup_key)

    logger.info("[SUCCESS] cookie refresh 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
