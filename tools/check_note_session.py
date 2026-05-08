"""Note セッション cookie の残り有効期限を確認する。

戻り値:
  0: 30 日以上残っている (OK)
  1: 30 日未満 (要更新)
  2: 取得失敗

使い方:
  uv run python tools/check_note_session.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WARN_THRESHOLD_DAYS = 30


def _load_state() -> dict | None:
    path = Path("auth/note_storage_state.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # R2 フォールバック
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from juggler_predictor.storage.r2 import build_r2_client_from_env
        r2 = build_r2_client_from_env()
        obj = r2._client.get_object(
            Bucket=r2.config.bucket, Key="auth/note_storage_state.json"
        )
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"storage_state 取得失敗: {e}")
        return None


def days_until_expiry(state: dict, cookie_name: str = "_note_session_v5") -> float | None:
    """cookie の残り日数を返す。expiry が無ければ None。"""
    for c in state.get("cookies", []):
        if c.get("name") != cookie_name:
            continue
        expires = c.get("expires", -1)
        if expires <= 0:
            return None
        now = datetime.now(timezone.utc).timestamp()
        return (expires - now) / 86400.0
    return None


def main() -> int:
    state = _load_state()
    if state is None:
        logger.error("storage_state が取得できません")
        return 2
    days = days_until_expiry(state)
    if days is None:
        logger.warning("_note_session_v5 の expiry が未設定 (session cookie の可能性)")
        return 1
    logger.info(f"cookie 残り: {days:.1f} 日")
    if days < WARN_THRESHOLD_DAYS:
        logger.warning(
            f"30 日未満です。月初の自動更新を待つか、scripts/refresh_note_session.py "
            f"--headed で手動更新してください。"
        )
        return 1
    logger.info("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
