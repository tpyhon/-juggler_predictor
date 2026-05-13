"""cf_clearance cookie の残り有効期限を確認。

毎週末などに手動実行し、期限切れ前に refresh_cf_cookie.py を回す判断用。
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env")
    from juggler_predictor.storage.r2 import build_r2_client_from_env

    c = build_r2_client_from_env()
    try:
        data = c.get_json("auth/cf_cookies.json")
    except Exception as e:
        logger.error("cookie ファイル取得失敗: %s", e)
        return 1

    now = dt.datetime.now(tz=dt.timezone.utc).astimezone()
    print(f"=== cf_cookies.json status ===")
    print(f"saved_at: {data.get('saved_at') or data.get('updated_at') or 'unknown'}")
    print(f"user_agent len: {len(data.get('user_agent', ''))}")
    print(f"cookies count: {len(data.get('cookies', []))}")

    cf = None
    for ck in data.get("cookies", []):
        if ck.get("name") == "cf_clearance":
            cf = ck
            break

    if not cf:
        logger.warning("cf_clearance が見つかりません")
        return 2

    expires = cf.get("expires")
    if expires and expires > 0:
        exp_dt = dt.datetime.fromtimestamp(expires).astimezone()
        remaining = exp_dt - now
        print(f"cf_clearance expires: {exp_dt.isoformat()}")
        print(f"remaining: {remaining}")
        if remaining.total_seconds() < 3600:
            print("[WARN] 残り 1 時間未満。refresh_cf_cookie.py を実行してください")
            return 3
        elif remaining.total_seconds() < 86400:
            print("[INFO] 残り 24 時間未満。明日の朝までに refresh 推奨")
            return 0
        else:
            print("[OK] 24 時間以上の有効期限あり")
            return 0
    else:
        print("cf_clearance: session cookie (期限なし)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
