"""ana-slo 取得調査 v3: playwright-stealth で Cloudflare Turnstile 突破."""
from __future__ import annotations

import json
from pathlib import Path

from curl_cffi import requests as cffi_requests

TARGET_URL = "https://ana-slo.com/2026-05-05-%e3%82%ad%e3%83%b3%e3%82%b0no-1%e4%b8%96%e7%94%b0%e8%b0%b7%e5%ba%97-data/"
LIST_URL = "https://ana-slo.com/%e3%83%9b%e3%83%bc%e3%83%ab%e3%83%87%e3%83%bc%e3%82%bf/%e6%9d%b1%e4%ba%ac%e9%83%bd/%e3%82%ad%e3%83%b3%e3%82%b0no-1%e4%b8%96%e7%94%b0%e8%b0%b7%e5%ba%97-%e3%83%87%e3%83%bc%e3%82%bf%e4%b8%80%e8%a6%a7/"
HOME = "https://ana-slo.com/"

OUT_DIR = Path(__file__).resolve().parent / "samples"
OUT_DIR.mkdir(parents=True, exist_ok=True)
COOKIE_PATH = OUT_DIR / "cf_cookies.json"


def acquire_via_stealth(manual_fallback_seconds: int = 60) -> tuple[dict[str, str], str]:
    """
    playwright-stealth で cf challenge を自動突破試行.
    ダメなら manual_fallback_seconds 秒だけ「手動でチェック入れる時間」を待つ.
    
    Returns:
        (cookies_dict, fetched_html)
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    print("[Stealth] ブラウザを起動 (stealth モード)")
    cookies_dict: dict[str, str] = {}
    target_html = ""

    stealth = Stealth()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
        )
        # Stealth スクリプトを context に適用
        stealth.apply_stealth_sync(context)

        page = context.new_page()

        # まずトップに行く
        print(f"[Stealth] GOTO {HOME}")
        page.goto(HOME, timeout=60000)
        # cf challenge があれば 15 秒くらい待つ(stealth で自動通過するはず)
        page.wait_for_timeout(8000)

        # 一覧ページに行く
        print(f"[Stealth] GOTO {LIST_URL[:60]}...")
        page.goto(LIST_URL, timeout=60000)
        page.wait_for_timeout(5000)

        # 詳細ページに行く
        print(f"[Stealth] GOTO {TARGET_URL[:60]}...")
        page.goto(TARGET_URL, timeout=60000)
        page.wait_for_timeout(5000)

        # 取得した HTML サイズを確認
        html_now = page.content()
        size = len(html_now)
        print(f"[Stealth] 詳細ページ HTML サイズ: {size:,} bytes")

        if size < 10000 or "ジャグラー" not in html_now:
            print()
            print("=" * 60)
            print("[手動モード] 自動突破できなかったので人間の助けを求めます")
            print(f"  これから {manual_fallback_seconds} 秒待ちます")
            print("  ブラウザでチェックボックスが見えたらクリックしてください")
            print("  通過したら自動で先に進みます")
            print("=" * 60)

            # 手動チェックを待つ:HTML サイズが大きくなるまでポーリング
            import time
            start = time.time()
            while time.time() - start < manual_fallback_seconds:
                time.sleep(2)
                try:
                    cur_html = page.content()
                    if len(cur_html) > 30000 and "ジャグラー" in cur_html:
                        print(f"[手動モード] 通過検出! size={len(cur_html):,}")
                        html_now = cur_html
                        break
                    print(f"  待機中... 現在 size={len(cur_html):,}")
                except Exception as e:
                    print(f"  ポーリングエラー: {e}")
            else:
                print("[手動モード] タイムアウト. 取得した範囲で進めます")
                html_now = page.content()

        target_html = html_now

        # cookie を取り出す
        for c in context.cookies():
            cookies_dict[c["name"]] = c["value"]

        # キャプチャ画像も保存(構造把握用)
        try:
            page.screenshot(path=str(OUT_DIR / "page_screenshot.png"), full_page=False)
        except Exception:
            pass

        browser.close()

    print(f"[Stealth] 取得 cookie: {list(cookies_dict.keys())[:5]}... ({len(cookies_dict)}個)")
    return cookies_dict, target_html


def try_curl_cffi_with_cookies(cookies: dict[str, str], referer: str) -> tuple[int, str]:
    sess = cffi_requests.Session(impersonate="chrome120")
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain=".ana-slo.com")
    resp = sess.get(TARGET_URL, headers={"Referer": referer}, timeout=30)
    return resp.status_code, resp.text


def analyze(html: str, label: str) -> None:
    print()
    print(f"=== 構造調査 ({label}) size={len(html):,} bytes ===")
    if len(html) < 5000:
        print(f"  [WARN] 小さすぎ. 冒頭: {html[:300]!r}")
        return
    for tag in ["table", "h1", "h2", "h3", "tr", "td"]:
        cnt = html.lower().count(f"<{tag}")
        print(f"  <{tag}>: {cnt}")
    for kw in ["ジャグラー", "マイジャグ", "アイム", "ファンキー", "BB", "RB", "差枚", "総回転"]:
        print(f"  '{kw}': {html.count(kw)}")


def main() -> None:
    print("=" * 60)
    print("【Step 1】 Playwright (stealth) でページ取得")
    print("=" * 60)
    cookies, html_browser = acquire_via_stealth(manual_fallback_seconds=90)

    # cookie 保存
    COOKIE_PATH.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVE] {COOKIE_PATH}")

    # ブラウザ経由 HTML を保存
    if len(html_browser) > 5000:
        out = OUT_DIR / "kingsetagaya_2026-05-05_via_browser.html"
        out.write_text(html_browser, encoding="utf-8")
        print(f"[SAVE] {out}")
        analyze(html_browser, "via Playwright(stealth)")
    else:
        print(f"[NG] ブラウザでも取得できず (size={len(html_browser)})")
        return

    # ====== Step 2: cookie を使って curl_cffi で再取得 ======
    print()
    print("=" * 60)
    print("【Step 2】 取得した cookie で curl_cffi 経由取得")
    print("=" * 60)
    status, html_curl = try_curl_cffi_with_cookies(cookies, referer=LIST_URL)
    print(f"  Status: {status}, Size: {len(html_curl):,}")

    if status == 200 and len(html_curl) > 10000:
        print("[OK] curl_cffi でも取得成功! cookie が効いた")
        out = OUT_DIR / "kingsetagaya_2026-05-05_via_curl.html"
        out.write_text(html_curl, encoding="utf-8")
        print(f"[SAVE] {out}")
        analyze(html_curl, "via curl_cffi(stealth-cookie)")
    else:
        print("[NG] curl_cffi では再現できず. 本番は Playwright 直で取得する設計に")


if __name__ == "__main__":
    main()
