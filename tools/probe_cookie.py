"""cf_clearance の動作切り分け v2: URL を必ず percent-encode してから送る。"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
COOKIE_PATH = ROOT / "auth" / "cf_cookies.json"


def encode_url(url: str) -> str:
    """日本語を含む URL を percent-encode する (既にエンコード済みは保持)。"""
    return quote(url, safe=":/?#[]@!$&'()*+,;=%-_.~")


def main() -> None:
    load_dotenv()
    payload = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
    cookies = payload["cookies"]
    ua = payload.get("user_agent", "")
    print(f"cookies={len(cookies)} cf_clearance_len={len(next(c for c in cookies if c['name']=='cf_clearance')['value'])}")
    print()

    cases = [
        ("home",                "https://ana-slo.com/",                                                       None),
        ("tokyo index",         "https://ana-slo.com/ホールデータ/東京都/",                                    "https://ana-slo.com/"),
        ("kingsetagaya list",   "https://ana-slo.com/ホールデータ/東京都/キングno-1世田谷店-データ一覧/",
                                "https://ana-slo.com/ホールデータ/東京都/"),
        ("kingsetagaya list (Referer=home)",
                                "https://ana-slo.com/ホールデータ/東京都/キングno-1世田谷店-データ一覧/",
                                "https://ana-slo.com/"),
        ("detail 2026-05-05",   "https://ana-slo.com/2026-05-05-キングno-1世田谷店-data/",
                                "https://ana-slo.com/ホールデータ/東京都/キングno-1世田谷店-データ一覧/"),
        ("detail 2026-05-04",   "https://ana-slo.com/2026-05-04-キングno-1世田谷店-data/",
                                "https://ana-slo.com/ホールデータ/東京都/キングno-1世田谷店-データ一覧/"),
    ]

    for label, url, ref in cases:
        sess = cffi_requests.Session(impersonate="chrome120")
        for c in cookies:
            try:
                sess.cookies.set(c["name"], c["value"], domain=c.get("domain") or ".ana-slo.com")
            except Exception:
                pass
        headers = {"User-Agent": ua}
        if ref:
            headers["Referer"] = encode_url(ref)
        try:
            r = sess.get(encode_url(url), headers=headers, timeout=20)
            size = len(r.text.encode("utf-8")) if r.text else 0
            print(f"[{label:42s}] status={r.status_code} size={size}")
        except Exception as e:
            print(f"[{label:42s}] ERROR {type(e).__name__}: {e}")
        sess.close()


if __name__ == "__main__":
    main()
