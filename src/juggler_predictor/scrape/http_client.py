"""curl_cffi をラップした HTTP クライアント。

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
