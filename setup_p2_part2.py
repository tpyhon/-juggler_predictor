"""P2 Part 2: HTTPクライアント / Playwright fallback / R2 storage / オーケストレーションを生成する。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# storage/__init__.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/storage/__init__.py"] = '''"""Cloudflare R2 を中心としたストレージ層。"""
from juggler_predictor.storage.paths import R2Paths
from juggler_predictor.storage.r2 import R2Client, R2Config, build_r2_client_from_env

__all__ = ["R2Client", "R2Config", "R2Paths", "build_r2_client_from_env"]
'''

# ---------------------------------------------------------------------------
# storage/paths.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/storage/paths.py"] = '''"""R2 内のオブジェクトキー命名規約を一元管理する。

すべてのレイヤーは直接 ``f"raw/{shop}/..."`` のような文字列を組み立てず、
このモジュール経由でキーを生成する。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R2Paths:
    """R2 オブジェクトキー命名規約。"""

    # ---- 認証 (cf_clearance クッキー) ----
    @staticmethod
    def cf_cookie_latest() -> str:
        return "auth/cf_cookies.json"

    @staticmethod
    def cf_cookie_backup(date_str: str) -> str:
        """``date_str`` は ``YYYYMMDD`` 形式。"""
        return f"auth/cf_cookies_{date_str}.json"

    # ---- 生 HTML ----
    @staticmethod
    def raw_html(shop_id: str, date_str: str) -> str:
        """``date_str`` は ``YYYY-MM-DD`` 形式。gzip 圧縮想定。"""
        return f"raw/{shop_id}/{date_str}.html.gz"

    # ---- パース後 JSON ----
    @staticmethod
    def dataset_json(shop_id: str, date_str: str) -> str:
        return f"dataset/{shop_id}/{date_str}.json.gz"

    # ---- 予測キャッシュ ----
    @staticmethod
    def pred_cache(shop_id: str, date_str: str) -> str:
        return f"pred_cache/{shop_id}/{date_str}.json"

    # ---- ML モデル ----
    @staticmethod
    def model_bundle(name: str = "ALL") -> str:
        return f"models/model_bundle__{name}.joblib"

    # ---- 記事 ----
    @staticmethod
    def article_md(shop_id: str, date_str: str) -> str:
        return f"articles/{shop_id}/{date_str}.md"

    # ---- 公開済みURL記録 ----
    @staticmethod
    def published_log(date_str: str) -> str:
        return f"reports/published/{date_str}.json"

    # ---- マーカー (ingest 完了印) ----
    @staticmethod
    def ingest_marker(shop_id: str, date_str: str) -> str:
        return f"markers/ingest/{shop_id}/{date_str}.ok"

    @staticmethod
    def publish_marker(shop_id: str, date_str: str) -> str:
        return f"markers/publish/{shop_id}/{date_str}.ok"
'''

# ---------------------------------------------------------------------------
# storage/r2.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/storage/r2.py"] = '''"""Cloudflare R2 (S3 互換) クライアント薄ラッパ。

- 環境変数からクライアントを構築するヘルパを提供する。
- bytes / JSON / gzip-JSON の get/put をサポートする。
- list / delete / exists のユーティリティも併設。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class R2Config:
    """R2 接続設定。環境変数または明示パラメータから構築する。"""

    endpoint: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    region: str = "auto"


def build_r2_client_from_env(env: dict[str, str] | None = None) -> "R2Client":
    """環境変数から :class:`R2Client` を組み立てる。

    必須環境変数: ``R2_ENDPOINT``, ``R2_ACCESS_KEY_ID``,
    ``R2_SECRET_ACCESS_KEY``, ``R2_BUCKET``.
    """
    src = env if env is not None else os.environ
    missing = [
        k for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        if not src.get(k)
    ]
    if missing:
        raise RuntimeError(f"R2 環境変数が不足しています: {missing}")

    cfg = R2Config(
        endpoint=src["R2_ENDPOINT"],
        access_key_id=src["R2_ACCESS_KEY_ID"],
        secret_access_key=src["R2_SECRET_ACCESS_KEY"],
        bucket=src["R2_BUCKET"],
        region=src.get("R2_REGION", "auto"),
    )
    return R2Client(cfg)


class R2Client:
    """boto3 ベースの R2 クライアント。"""

    def __init__(self, config: R2Config) -> None:
        self.config = config
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
            config=BotoConfig(signature_version="s3v4"),
        )

    # ---------------- 基本 I/O ----------------
    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self.config.bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)
        logger.debug("R2 put: %s (%d bytes)", key, len(data))

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.config.bucket, Key=key)
        body = resp["Body"].read()
        logger.debug("R2 get: %s (%d bytes)", key, len(body))
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.config.bucket, Key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.config.bucket, Key=key)
        logger.debug("R2 delete: %s", key)

    def list_keys(self, prefix: str = "") -> Iterable[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                yield obj["Key"]

    # ---------------- 高水準 ----------------
    def put_json(self, key: str, obj: Any, *, gzipped: bool = False) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        if gzipped:
            body = gzip.compress(body)
            self.put_bytes(key, body, content_type="application/gzip")
        else:
            self.put_bytes(key, body, content_type="application/json")

    def get_json(self, key: str, *, gzipped: bool = False) -> Any:
        body = self.get_bytes(key)
        if gzipped:
            body = gzip.decompress(body)
        return json.loads(body.decode("utf-8"))

    def put_gzip_text(self, key: str, text: str) -> None:
        body = gzip.compress(text.encode("utf-8"))
        self.put_bytes(key, body, content_type="application/gzip")

    def get_gzip_text(self, key: str) -> str:
        body = gzip.decompress(self.get_bytes(key))
        return body.decode("utf-8")
'''

# ---------------------------------------------------------------------------
# scrape/http_client.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/http_client.py"] = '''"""curl_cffi をラップした HTTP クライアント。

- Cloudflare 通過済みのクッキーを R2 から渡せる構造。
- tenacity による指数バックオフリトライを内蔵。
- ana-slo.com の hot-link 保護を意識して Referer を都度設定する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from curl_cffi import requests as cffi_requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class HTTPError(RuntimeError):
    """HTTP 通信全般の失敗。"""


class CloudflareBlocked(HTTPError):
    """Cloudflare により 403 が返った状態。クッキー再取得が必要。"""


@dataclass
class AnaSloHTTPClient:
    """ana-slo.com 専用 curl_cffi セッション。

    Parameters
    ----------
    cookies:
        ``[{"name": ..., "value": ..., "domain": ...}, ...]`` 形式。
    impersonate:
        curl_cffi の TLS フィンガープリント識別子。
    timeout:
        個別リクエストのタイムアウト秒。
    user_agent:
        Playwright で取得時の UA を引き継ぐと整合する。
    """

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
            except Exception as e:  # 防御的: 一部 cookie は domain が原因で失敗しうる
                logger.warning("cookie set 失敗: name=%s err=%s", name, e)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(HTTPError),
    )
    def get(self, url: str, *, referer: str | None = None) -> str:
        """URL を GET し、テキスト本文を返す。403 は :class:`CloudflareBlocked`。"""
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if self.user_agent:
            headers["User-Agent"] = self.user_agent

        try:
            resp = self._session.get(url, headers=headers, timeout=self.timeout)
        except Exception as e:
            raise HTTPError(f"GET 失敗 url={url} err={e}") from e

        status = resp.status_code
        body = resp.text or ""
        size = len(body.encode("utf-8")) if body else 0

        if status == 403:
            logger.warning("Cloudflare 403: url=%s size=%d", url, size)
            raise CloudflareBlocked(
                f"403 Forbidden url={url} size={size} -- cf_clearance を再取得してください"
            )
        if status >= 400:
            raise HTTPError(f"HTTP {status} url={url}")

        logger.info("GET ok url=%s status=%d size=%d", url, status, size)
        return body

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
'''

# ---------------------------------------------------------------------------
# scrape/playwright_fallback.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/playwright_fallback.py"] = '''"""Playwright を使った cf_clearance 取得 (手動運用想定)。

GitHub Actions では呼ばない。月 1 回ローカルで実行して
取得した cookie を R2 にアップロードする。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CookieAcquireResult:
    cookies: list[dict[str, Any]]
    user_agent: str
    final_url: str
    html_size: int


def acquire_cookies(
    *,
    home_url: str = "https://ana-slo.com/",
    list_url: str | None = None,
    target_url: str | None = None,
    headless: bool = False,
    wait_seconds: int = 90,
) -> CookieAcquireResult:
    """ブラウザを開いて Cloudflare 通過後の cookie を取得する。

    手順:
        1) home_url を開く -> Cloudflare チャレンジを通過させる
        2) list_url があれば遷移
        3) target_url があれば遷移して通過確認
        4) wait_seconds 経過 or ページが安定したら cookie を回収

    Notes
    -----
    Playwright の自動化はチャレンジを突破できないことがあるため、
    headless=False を既定にしてユーザの手動操作を許容する。
    """
    # ローカル import: GitHub Actions で playwright 未インストール時にも
    # storage / scrape の他モジュールが import 可能にするため遅延 import。
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
            page.wait_for_timeout(3000)

            if list_url:
                logger.info("playwright open list: %s", list_url)
                page.goto(list_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2000)

            if target_url:
                logger.info("playwright open target: %s", target_url)
                page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)

            # 手動チャレンジ突破の余地を残す
            page.wait_for_timeout(wait_seconds * 1000)

            content = page.content()
            html_size = len(content.encode("utf-8"))
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
'''

# ---------------------------------------------------------------------------
# scrape/ana_slo.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/ana_slo.py"] = '''"""ana-slo.com の URL 組立とフェッチオーケストレーション。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from juggler_predictor.scrape.http_client import AnaSloHTTPClient

logger = logging.getLogger(__name__)

BASE = "https://ana-slo.com"


@dataclass(frozen=True)
class AnaSloUrls:
    """ana-slo.com の URL 組み立て。

    日本語スラッグ (例: "キングno-1世田谷店") を渡すとパーセントエンコードして組み立てる。
    """

    base: str = BASE

    def home(self) -> str:
        return f"{self.base}/"

    def tokyo_index(self) -> str:
        # /ホールデータ/東京都/
        return f"{self.base}/{quote('ホールデータ')}/{quote('東京都')}/"

    def shop_index(self, shop_slug: str) -> str:
        # /ホールデータ/東京都/<slug>-データ一覧/
        return f"{self.base}/{quote('ホールデータ')}/{quote('東京都')}/{quote(shop_slug + '-データ一覧')}/"

    def shop_date(self, shop_slug: str, date_str: str) -> str:
        """``date_str`` は ``YYYY-MM-DD`` 形式。"""
        # /<YYYY-MM-DD>-<slug>-data/
        return f"{self.base}/{date_str}-{quote(shop_slug)}-data/"


def fetch_shop_date_html(
    client: AnaSloHTTPClient,
    *,
    shop_slug: str,
    date_str: str,
    urls: AnaSloUrls | None = None,
) -> str:
    """1 店舗 1 日分の HTML を返す。

    手順:
        1. 店舗一覧ページを GET (Referer はホーム)
        2. 日付詳細ページを GET (Referer は店舗一覧)
    """
    u = urls or AnaSloUrls()
    list_url = u.shop_index(shop_slug)
    detail_url = u.shop_date(shop_slug, date_str)

    logger.info("step1 list: %s", list_url)
    client.get(list_url, referer=u.home())

    logger.info("step2 detail: %s", detail_url)
    return client.get(detail_url, referer=list_url)
'''

# ---------------------------------------------------------------------------
# scrape/checker.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/checker.py"] = '''"""パース後データの品質チェック。"""
from __future__ import annotations

from dataclasses import dataclass, field

from juggler_predictor.scrape.parser import ParsedPage


@dataclass
class CheckReport:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    juggler_rows: int = 0
    total_rows: int = 0


# 1 店舗で見込まれるジャグラー台の最低台数 (これより少なければ取得失敗を疑う)
MIN_JUGGLER_ROWS = 5


def check_parsed_page(page: ParsedPage, *, shop_id: str, date_str: str) -> CheckReport:
    """:class:`ParsedPage` を検査して :class:`CheckReport` を返す。"""
    rep = CheckReport(
        ok=True,
        juggler_rows=len(page.rows),
        total_rows=page.total_rows_in_table,
    )

    if page.date_str is None:
        rep.errors.append("date_str がパースできていない")
    elif page.date_str != date_str:
        rep.errors.append(
            f"date 不一致: expected={date_str} actual={page.date_str}"
        )

    if page.shop_display_name is None:
        rep.warnings.append("shop_display_name がパースできていない")

    if page.total_rows_in_table == 0:
        rep.errors.append("テーブル本体が 0 行 (取得失敗の可能性)")

    if len(page.rows) < MIN_JUGGLER_ROWS:
        rep.warnings.append(
            f"ジャグラー台数が少ない rows={len(page.rows)} shop={shop_id}"
        )

    # 全行の差枚が None / 0 なら何かおかしい
    has_meaningful_diff = any(
        r.diff is not None and r.diff != 0 for r in page.rows
    )
    if page.rows and not has_meaningful_diff:
        rep.warnings.append("差枚が全行 None/0: データ欠損の可能性")

    if rep.errors:
        rep.ok = False
    return rep
'''

# ---------------------------------------------------------------------------
# tests/test_storage_r2_paths.py
# ---------------------------------------------------------------------------
FILES["tests/test_storage_r2_paths.py"] = '''"""R2Paths のキー命名規約テスト (R2 通信なし)。"""
from __future__ import annotations

from juggler_predictor.storage.paths import R2Paths


def test_cf_cookie_paths() -> None:
    assert R2Paths.cf_cookie_latest() == "auth/cf_cookies.json"
    assert R2Paths.cf_cookie_backup("20260506") == "auth/cf_cookies_20260506.json"


def test_raw_html_path() -> None:
    assert (
        R2Paths.raw_html("kingsetagaya", "2026-05-05")
        == "raw/kingsetagaya/2026-05-05.html.gz"
    )


def test_dataset_path() -> None:
    assert (
        R2Paths.dataset_json("kingsetagaya", "2026-05-05")
        == "dataset/kingsetagaya/2026-05-05.json.gz"
    )


def test_pred_cache_path() -> None:
    assert (
        R2Paths.pred_cache("kingsetagaya", "2026-05-05")
        == "pred_cache/kingsetagaya/2026-05-05.json"
    )


def test_model_path() -> None:
    assert R2Paths.model_bundle() == "models/model_bundle__ALL.joblib"
    assert R2Paths.model_bundle("kingsetagaya") == "models/model_bundle__kingsetagaya.joblib"


def test_article_path() -> None:
    assert (
        R2Paths.article_md("kingsetagaya", "2026-05-05")
        == "articles/kingsetagaya/2026-05-05.md"
    )


def test_published_log_path() -> None:
    assert R2Paths.published_log("2026-05-05") == "reports/published/2026-05-05.json"


def test_marker_paths() -> None:
    assert (
        R2Paths.ingest_marker("kingsetagaya", "2026-05-05")
        == "markers/ingest/kingsetagaya/2026-05-05.ok"
    )
    assert (
        R2Paths.publish_marker("kingsetagaya", "2026-05-05")
        == "markers/publish/kingsetagaya/2026-05-05.ok"
    )
'''

# ---------------------------------------------------------------------------
# tests/test_scrape_checker.py
# ---------------------------------------------------------------------------
FILES["tests/test_scrape_checker.py"] = '''"""checker.py のユニットテスト (HTTP 通信なし)。"""
from __future__ import annotations

from juggler_predictor.scrape.checker import check_parsed_page
from juggler_predictor.scrape.parser import MachineRow, ParsedPage


def _row(diff: int = 100, **kw: object) -> MachineRow:
    base = dict(
        machine_name="マイジャグラーV",
        machine_name_raw="マイジャグラーV",
        unit_number="1",
        unit_number_raw="1",
        g_count=5000,
        diff=diff,
        bb=15,
        rb=10,
    )
    base.update(kw)
    return MachineRow(**base)  # type: ignore[arg-type]


def test_check_ok_for_normal_page() -> None:
    page = ParsedPage(
        shop_display_name="キングNo.1世田谷店",
        date_str="2026-05-05",
        rows=[_row(diff=i * 100) for i in range(10)],
        total_rows_in_table=200,
    )
    rep = check_parsed_page(page, shop_id="kingsetagaya", date_str="2026-05-05")
    assert rep.ok is True
    assert rep.errors == []
    assert rep.juggler_rows == 10
    assert rep.total_rows == 200


def test_check_fails_when_date_mismatch() -> None:
    page = ParsedPage(
        shop_display_name="A",
        date_str="2026-05-04",
        rows=[_row() for _ in range(10)],
        total_rows_in_table=100,
    )
    rep = check_parsed_page(page, shop_id="kingsetagaya", date_str="2026-05-05")
    assert rep.ok is False
    assert any("date 不一致" in e for e in rep.errors)


def test_check_fails_on_empty_table() -> None:
    page = ParsedPage(
        shop_display_name="A",
        date_str="2026-05-05",
        rows=[],
        total_rows_in_table=0,
    )
    rep = check_parsed_page(page, shop_id="kingsetagaya", date_str="2026-05-05")
    assert rep.ok is False
    assert any("0 行" in e for e in rep.errors)


def test_check_warns_on_few_juggler_rows() -> None:
    page = ParsedPage(
        shop_display_name="A",
        date_str="2026-05-05",
        rows=[_row()],
        total_rows_in_table=200,
    )
    rep = check_parsed_page(page, shop_id="kingsetagaya", date_str="2026-05-05")
    assert rep.ok is True
    assert any("少ない" in w for w in rep.warnings)


def test_check_warns_when_all_diff_zero() -> None:
    page = ParsedPage(
        shop_display_name="A",
        date_str="2026-05-05",
        rows=[_row(diff=0) for _ in range(10)],
        total_rows_in_table=200,
    )
    rep = check_parsed_page(page, shop_id="kingsetagaya", date_str="2026-05-05")
    assert any("差枚" in w for w in rep.warnings)
'''


# ---------------------------------------------------------------------------
# tests/test_scrape_ana_slo_urls.py
# ---------------------------------------------------------------------------
FILES["tests/test_scrape_ana_slo_urls.py"] = '''"""AnaSloUrls の URL 組立テスト。"""
from __future__ import annotations

from juggler_predictor.scrape.ana_slo import AnaSloUrls


def test_home_url() -> None:
    assert AnaSloUrls().home() == "https://ana-slo.com/"


def test_tokyo_index_is_percent_encoded() -> None:
    url = AnaSloUrls().tokyo_index()
    assert url.startswith("https://ana-slo.com/")
    assert "%E3%83%9B%E3%83%BC%E3%83%AB" in url  # ホール
    assert url.endswith("/")


def test_shop_index_contains_slug() -> None:
    url = AnaSloUrls().shop_index("キングno-1世田谷店")
    # スラッグも一覧サフィックスもパーセントエンコードされる
    assert "no-1" in url.lower()
    assert url.startswith("https://ana-slo.com/")
    assert url.endswith("/")


def test_shop_date_url_pattern() -> None:
    url = AnaSloUrls().shop_date("キングno-1世田谷店", "2026-05-05")
    # 日付がそのまま (エンコードなし) で入る
    assert "/2026-05-05-" in url
    assert url.endswith("-data/")
'''


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("P2 Part 2: HTTP / Playwright / R2 / orchestration")
    print("=" * 60)

    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")

    print()
    print("=" * 60)
    print("[SUCCESS] P2 Part 2 ファイル生成 完了")
    print("=" * 60)
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print()


if __name__ == "__main__":
    main()
