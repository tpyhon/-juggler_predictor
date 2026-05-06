"""東京一覧ページの HTML をダンプして slug 抽出ロジックを点検する。"""
from __future__ import annotations

import re
from pathlib import Path

from dotenv import load_dotenv

from juggler_predictor.scrape.ana_slo import AnaSloUrls
from juggler_predictor.scrape.http_client import AnaSloHTTPClient
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "samples" / "tokyo_index.html"


def main() -> None:
    load_dotenv()
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    client = AnaSloHTTPClient(cookies=payload["cookies"], user_agent=payload.get("user_agent"))
    urls = AnaSloUrls()
    html = client.get(urls.tokyo_index(), referer=urls.home())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"saved {OUT} ({len(html):,} bytes)")
    print()

    # ana-slo の店舗関連リンク候補を抽出
    print("--- href 候補 (上位 30件) ---")
    hrefs = re.findall(r'href="([^"]+)"', html)
    print(f"全 href 数: {len(hrefs)}")
    keywords = ["世田谷", "吉祥寺", "新宿", "池袋", "渋谷", "data", "データ", "ホール", "東京"]
    matched: list[str] = []
    for h in hrefs:
        if any(k in h for k in keywords) or "%" in h:
            matched.append(h)
    print(f"キーワード一致: {len(matched)}")
    for h in matched[:30]:
        print(f"  {h}")
    print()

    print("--- '世田谷' を含む箇所の周辺 200 文字 (最大3箇所) ---")
    for i, m in enumerate(re.finditer(r"世田谷", html)):
        if i >= 3:
            break
        s = max(0, m.start() - 100)
        e = min(len(html), m.end() + 100)
        print(f"[{i}] ...{html[s:e]}...")
        print()


if __name__ == "__main__":
    main()
