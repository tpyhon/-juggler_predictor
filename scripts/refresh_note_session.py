"""Note の _note_session_v5 cookie を更新し R2 にアップロードする。

実行モード:
  - headed (--headed): ローカル手動実行用、ブラウザを表示してログイン
  - headless (デフォルト): Actions 用、NOTE_EMAIL/NOTE_PASSWORD で自動ログイン
                            reCAPTCHA に引っかかった場合は失敗終了

使い方:
  uv run python scripts/refresh_note_session.py --headed       # ローカル手動
  uv run python scripts/refresh_note_session.py                 # Actions 自動
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()


import os
from pathlib import Path as _Path

def _ensure_ld_library_path() -> None:
    local_lib = str(_Path.home() / ".local" / "lib")
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    if local_lib not in existing:
        os.environ["LD_LIBRARY_PATH"] = f"{local_lib}:{existing}" if existing else local_lib

_ensure_ld_library_path()

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def upload_storage_state_to_r2(state_path: Path) -> None:
    from juggler_predictor.storage.r2 import build_r2_client_from_env
    r2 = build_r2_client_from_env()
    data = state_path.read_bytes()
    r2._client.put_object(
        Bucket=r2.config.bucket,
        Key="auth/note_storage_state.json",
        Body=data,
        ContentType="application/json",
    )
    logger.info(f"R2 にアップロード: auth/note_storage_state.json ({len(data) / 1024:.1f} KB)")


def login_headed(state_path: Path) -> bool:
    """ブラウザを表示して手動ログインを待つ。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://note.com/login")
        print("=" * 60)
        print("ブラウザで note にログインしてください。")
        print("ログイン完了後、ターミナルで Enter を押してください。")
        print("=" * 60)
        input("Enter で続行 > ")
        # ログイン確認 (リダイレクト発生でも例外にならないよう wait_until を緩める)
        try:
            page.goto("https://note.com/notes", wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            logger.warning(f"ナビゲーション警告 (無視): {e}")
        page.wait_for_timeout(2000)  # リダイレクト完了待ち
        current_url = page.url
        logger.info(f"現在の URL: {current_url}")
        if "/login" in current_url:
            logger.error("ログインされていません")
            browser.close()
            return False
        # cookie に _note_session_v5 が含まれているかで最終確認
        cookies = context.cookies("https://note.com")
        has_session = any(c["name"] == "_note_session_v5" for c in cookies)
        if not has_session:
            logger.error("_note_session_v5 cookie が取得できていません")
            browser.close()
            return False
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        browser.close()
        logger.info(f"storage_state 保存: {state_path}")
        return True



def login_headless(state_path: Path, email: str, password: str) -> bool:
    """email/password で自動ログインする。reCAPTCHA に引っかかったら失敗。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
            ),
        )
        page = context.new_page()
        try:
            page.goto("https://note.com/login", wait_until="networkidle")
            page.wait_for_selector("#email", timeout=15000)
            # Vue のバリデーションを通すため1文字ずつ入力（input イベント発火）
            page.locator("#email").click()
            page.locator("#email").press_sequentially(email, delay=30)
            page.locator("#password").click()
            page.locator("#password").press_sequentially(password, delay=30)

            # disabled が外れるまで待機
            page.wait_for_function(
                "() => { const btn = document.querySelector('button.a-button[type=\"button\"]'); return btn && !btn.disabled; }",
                timeout=10000,)

            for sel in ['button.a-button:has-text("ログイン")', 'button:has-text("ログイン")', 'button[type="submit"]']:
                page.wait_for_load_state("networkidle", timeout=20000)
            # reCAPTCHA / login error 判定
            content = page.content()
            if "recaptcha" in content.lower() or "もう一度お試しください" in content:
                logger.error("reCAPTCHA 検出 or ログインブロック")
                return False
            if "/login" in page.url:
                logger.error(f"ログイン失敗 (URL: {page.url})")
                return False
            state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(state_path))
            logger.info(f"storage_state 保存: {state_path}")
            return True
        except Exception as e:
            logger.error(f"自動ログイン例外: {e}")
            return False
        finally:
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="ブラウザを表示して手動ログイン")
    ap.add_argument("--state-path", default="auth/note_storage_state.json")
    ap.add_argument("--no-upload", action="store_true", help="R2 アップロードしない")
    args = ap.parse_args()

    state_path = Path(args.state_path)

    if args.headed:
        ok = login_headed(state_path)
    else:
        email = os.environ.get("NOTE_EMAIL")
        password = os.environ.get("NOTE_PASSWORD")
        if not (email and password):
            logger.error("NOTE_EMAIL / NOTE_PASSWORD 環境変数が必要です (--headed なら不要)")
            return 1
        ok = login_headless(state_path, email, password)

    if not ok:
        return 1

    if not args.no_upload:
        try:
            upload_storage_state_to_r2(state_path)
        except Exception as e:
            logger.error(f"R2 アップロード失敗: {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
