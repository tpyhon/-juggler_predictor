"""Playwright + stealth で cf_clearance を取得する (手動誘導モード)。

Cloudflare の Managed Challenge は素の Playwright だと検知されて通過できない
ため、playwright-stealth で自動化シグナルを隠す。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_ld_library_path() -> None:
    """sudo なしでインストールした共有ライブラリ (~/.local/lib) を LD_LIBRARY_PATH に追加する。
    Playwright が Chrome サブプロセスを spawn する前に呼ぶ必要がある。"""
    local_lib = str(Path.home() / ".local" / "lib")
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    if local_lib not in existing:
        os.environ["LD_LIBRARY_PATH"] = f"{local_lib}:{existing}" if existing else local_lib

DETAIL_URL_RE = re.compile(r"/\d{4}-\d{2}-\d{2}-.+?-data/?$")


@dataclass
class CookieAcquireResult:
    cookies: list[dict[str, Any]]
    user_agent: str
    final_url: str
    html_size: int


def _apply_stealth(page: Any) -> None:
    """playwright-stealth を適用する (バージョン差異吸収)。"""
    try:
        # 新しめのバージョン (stealth_sync があるもの)
        from playwright_stealth import stealth_sync  # type: ignore
        stealth_sync(page)
        logger.info("playwright-stealth 適用 (stealth_sync)")
        return
    except Exception:
        pass
    try:
        from playwright_stealth import Stealth  # type: ignore
        Stealth().apply_stealth_sync(page)
        logger.info("playwright-stealth 適用 (Stealth.apply_stealth_sync)")
        return
    except Exception as e:
        logger.warning("playwright-stealth が利用できません: %s", e)


def acquire_cookies_manual(
    *,
    home_url: str = "https://ana-slo.com/",
    headless: bool = False,
    max_wait_seconds: int = 300,
    poll_interval: float = 1.0,
) -> CookieAcquireResult:
    """ユーザに手動クリック遷移してもらい、日付詳細ページの cookie を回収する。

    手順:
        1) home_url を開く (stealth 適用)
        2) ユーザに「東京一覧 → 店舗一覧 → 日付詳細」とクリック誘導
        3) URL が /YYYY-MM-DD-...-data/ パターンになった時点で cookie 確定
    """
    _ensure_ld_library_path()
    from playwright.sync_api import sync_playwright

    cookies: list[dict[str, Any]] = []
    user_agent = ""
    final_url = ""
    html_size = 0

    with sync_playwright() as p:
        # devtools=False / 各種自動化検知を抑制する起動オプション
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        _apply_stealth(page)

        try:
            ua = page.evaluate("() => navigator.userAgent") or ""
            user_agent = str(ua)

            logger.info("playwright open: %s", home_url)
            page.goto(home_url, wait_until="domcontentloaded", timeout=60_000)

            print()
            print("=" * 70)
            print("【手動操作のお願い】")
            print(" 開いたブラウザで以下の順にクリックしてください:")
            print("   1) トップ画面の「ホールデータ」 -> 「東京都」")
            print("   2) お好きな店舗 (例: キングNo.1世田谷店)")
            print("   3) 日付一覧から最新日付 (例: 2026-05-05)")
            print()
            print(" * チェックボックスが出たら 1 回だけクリック")
            print(" * DevTools (F12) は閉じたままにしてください")
            print(" * 日付詳細ページに到達したら自動で cookie を回収します")
            print(f" * 最大 {max_wait_seconds} 秒で打ち切ります")
            print("=" * 70)
            print()

            elapsed = 0.0
            reached_detail = False
            last_logged_url = ""
            while elapsed < max_wait_seconds:
                try:
                    current = page.url
                except Exception:
                    current = ""
                if current and current != last_logged_url:
                    logger.info("current url: %s", current)
                    last_logged_url = current
                if current and DETAIL_URL_RE.search(current):
                    logger.info("日付詳細ページに到達: %s", current)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15_000)
                    except Exception:
                        page.wait_for_timeout(3000)
                    reached_detail = True
                    break
                page.wait_for_timeout(int(poll_interval * 1000))
                elapsed += poll_interval

            if not reached_detail:
                logger.warning(
                    "日付詳細ページに到達せずタイムアウト。最終 URL=%s",
                    page.url,
                )

            try:
                content = page.content()
                html_size = len(content.encode("utf-8"))
            except Exception:
                html_size = 0
            final_url = page.url
            cookies = context.cookies()
        finally:
            context.close()
            browser.close()

    return CookieAcquireResult(
        cookies=cookies,
        user_agent=user_agent,
        final_url=final_url,
        html_size=html_size,
    )


def acquire_cookies(
    *,
    home_url: str = "https://ana-slo.com/",
    list_url: str | None = None,
    target_url: str | None = None,
    headless: bool = False,
    wait_seconds: int = 90,
) -> CookieAcquireResult:
    """旧シグネチャ互換ラッパ。"""
    return acquire_cookies_manual(
        home_url=home_url,
        headless=headless,
        max_wait_seconds=max(wait_seconds, 300),
    )
