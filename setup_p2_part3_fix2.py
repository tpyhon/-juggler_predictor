"""P2 Part 3 ホットフィックス v2: cf_clearance の取得フローを手動誘導方式に変更。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# scrape/playwright_fallback.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/playwright_fallback.py"] = '''"""Playwright を使った cf_clearance 取得 (手動誘導モード)。

GitHub Actions では呼ばない。月 1 回ローカルで実行して、
ユーザが手動でホーム→店舗一覧→日付詳細とクリック遷移し、
最終的な日付詳細ページの cookie を回収する。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# /YYYY-MM-DD-{slug}-data/ にマッチ
DETAIL_URL_RE = re.compile(r"/\\d{4}-\\d{2}-\\d{2}-.+?-data/?$")


@dataclass
class CookieAcquireResult:
    cookies: list[dict[str, Any]]
    user_agent: str
    final_url: str
    html_size: int


def acquire_cookies_manual(
    *,
    home_url: str = "https://ana-slo.com/",
    headless: bool = False,
    max_wait_seconds: int = 240,
    poll_interval: float = 1.0,
) -> CookieAcquireResult:
    """ユーザに手動クリック遷移してもらい、日付詳細ページの cookie を回収する。

    手順:
        1) home_url を開く
        2) ユーザに「東京一覧 → 店舗一覧 → 日付詳細」とクリック誘導
        3) URL が /YYYY-MM-DD-...-data/ パターンになった時点で cookie 確定
        4) max_wait_seconds 経過 or ページが日付詳細に到達したら終了
    """
    from playwright.sync_api import sync_playwright

    cookies: list[dict[str, Any]] = []
    user_agent = ""
    final_url = ""
    html_size = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            ua = page.evaluate("() => navigator.userAgent") or ""
            user_agent = str(ua)

            logger.info("playwright open: %s", home_url)
            page.goto(home_url, wait_until="domcontentloaded", timeout=60_000)

            print()
            print("=" * 70)
            print("【手動操作のお願い】")
            print(" 開いたブラウザで以下の順にクリックしてください:")
            print("   1) ホールデータ -> 東京都")
            print("   2) お好きな店舗 (例: キングNo.1世田谷店)")
            print("   3) 日付一覧から いずれかの日付 (例: 一番上の最新)")
            print(" 日付詳細ページが表示されたら自動で cookie を回収します。")
            print(f" 最大 {max_wait_seconds} 秒で打ち切ります。")
            print("=" * 70)
            print()

            elapsed = 0.0
            reached_detail = False
            while elapsed < max_wait_seconds:
                try:
                    current = page.url
                except Exception:
                    current = ""
                if current and DETAIL_URL_RE.search(current):
                    logger.info("日付詳細ページに到達: %s", current)
                    # ページの読み込みが落ち着くのを少し待つ
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        page.wait_for_timeout(2000)
                    reached_detail = True
                    break
                page.wait_for_timeout(int(poll_interval * 1000))
                elapsed += poll_interval

            if not reached_detail:
                logger.warning(
                    "日付詳細ページに到達せずタイムアウト。現在の URL=%s で cookie を回収します",
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


# 旧 API も残す (Part 2 互換)
def acquire_cookies(
    *,
    home_url: str = "https://ana-slo.com/",
    list_url: str | None = None,
    target_url: str | None = None,
    headless: bool = False,
    wait_seconds: int = 90,
) -> CookieAcquireResult:
    """旧シグネチャ互換ラッパ。内部では acquire_cookies_manual を呼ぶ。"""
    return acquire_cookies_manual(
        home_url=home_url,
        headless=headless,
        max_wait_seconds=max(wait_seconds, 180),
    )
'''

# ---------------------------------------------------------------------------
# scrape/http_client.py  (URL/Referer を必ず percent-encode)
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/http_client.py"] = '''"""curl_cffi をラップした HTTP クライアント。

- Cloudflare 通過済みのクッキーを R2 から渡せる構造。
- tenacity による指数バックオフリトライを内蔵。
- ana-slo.com の hot-link 保護を意識して Referer を都度設定する。
- libcurl は HTTP ヘッダ値を latin-1 で扱うため、URL/Referer は必ず
  percent-encode してから送る。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from curl_cffi import requests as cffi_requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# percent-encode 時に温存する記号 (RFC 3986 の予約文字 + % 自体)
_SAFE_URL_CHARS = ":/?#[]@!$&'()*+,;=%-_.~"


def encode_url(url: str) -> str:
    """URL を ASCII-only に整形する。既にエンコード済みの部分は保持される。"""
    return quote(url, safe=_SAFE_URL_CHARS)


class HTTPError(RuntimeError):
    """HTTP 通信全般の失敗。"""


class CloudflareBlocked(HTTPError):
    """Cloudflare により 403 が返った状態。クッキー再取得が必要。"""


@dataclass
class AnaSloHTTPClient:
    """ana-slo.com 専用 curl_cffi セッション。"""

    cookies: list[dict[str, Any]] = field(default_factory=list)
    impersonate: str = "chrome120"
    timeout: float = 20.0
    user_agent: str | None = None

    def __post_init__(self) -> None:
        self._session = cffi_requests.Session(impersonate=self.impersonate)
        for c in self.cookies:
            name = c.get("name")
            value = c.get("value")
            domain = c.get("domain") or ".ana-slo.com"
            if not name or value is None:
                continue
            try:
                self._session.cookies.set(name, value, domain=domain)
            except Exception as e:
                logger.warning("cookie set 失敗: name=%s err=%s", name, e)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(HTTPError),
    )
    def get(self, url: str, *, referer: str | None = None) -> str:
        """URL を GET し、テキスト本文を返す。403 は :class:`CloudflareBlocked`。"""
        url_enc = encode_url(url)
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = encode_url(referer)
        if self.user_agent:
            headers["User-Agent"] = self.user_agent

        try:
            resp = self._session.get(url_enc, headers=headers, timeout=self.timeout)
        except Exception as e:
            raise HTTPError(f"GET 失敗 url={url_enc} err={e}") from e

        status = resp.status_code
        body = resp.text or ""
        size = len(body.encode("utf-8")) if body else 0

        if status == 403:
            logger.warning("Cloudflare 403: url=%s size=%d", url_enc, size)
            raise CloudflareBlocked(
                f"403 Forbidden url={url_enc} size={size} -- cf_clearance を再取得してください"
            )
        if status >= 400:
            raise HTTPError(f"HTTP {status} url={url_enc}")

        logger.info("GET ok url=%s status=%d size=%d", url_enc, status, size)
        return body

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
'''

# ---------------------------------------------------------------------------
# scripts/refresh_cf_cookie.py  (手動誘導フローに変更)
# ---------------------------------------------------------------------------
FILES["scripts/refresh_cf_cookie.py"] = '''"""月 1 回手動: Cloudflare 通過済みクッキーを取得して R2 にアップロードする。

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
'''


def main() -> None:
    print("=" * 60)
    print("P2 Part 3 fix v2: 手動誘導 cookie 取得フローに変更")
    print("=" * 60)
    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")
    print()
    print("[OK] 修正完了")
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print("  uv run python scripts/refresh_cf_cookie.py")


if __name__ == "__main__":
    main()
