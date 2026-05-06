"""P3a: bootstrap (過去データ一括取得) スクリプトと workflow を生成。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# src/juggler_predictor/pipeline/__init__.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/pipeline/__init__.py"] = '''"""パイプライン (ingest / publish / bootstrap) のオーケストレーション層。"""
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/pipeline/ingest_one.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/pipeline/ingest_one.py"] = '''"""1 店舗 1 日分の取り込み処理を関数化したもの。

bootstrap.py / ingest.py の両方から再利用される。
- raw HTML を取得 -> R2 raw/ に gzip 保存
- パース -> R2 dataset/ に gzip-JSON 保存
- マーカー (ok / miss) を R2 markers/ に書く
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from juggler_predictor.scrape.ana_slo import fetch_shop_date_html
from juggler_predictor.scrape.checker import check_parsed_page
from juggler_predictor.scrape.http_client import (
    AnaSloHTTPClient,
    CloudflareBlocked,
    HTTPError,
)
from juggler_predictor.scrape.parser import parse_ana_slo_html
from juggler_predictor.storage import R2Client, R2Paths

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    shop_id: str
    date_str: str
    status: str  # "ok" | "skip_existing" | "miss" | "error" | "cf_blocked"
    juggler_rows: int = 0
    total_rows: int = 0
    html_size: int = 0
    message: str = ""


def ingest_one(
    *,
    r2: R2Client,
    client: AnaSloHTTPClient,
    shop_id: str,
    shop_slug: str,
    date_str: str,
    machines_config: dict[str, Any],
    skip_if_exists: bool = True,
    upload_raw: bool = True,
    upload_dataset: bool = True,
) -> IngestResult:
    """1 店舗 1 日分の取り込み。

    例外送出:
        - :class:`CloudflareBlocked` のみ呼び出し元に再送出する。これは
          全体停止すべき致命的状態のため。それ以外は IngestResult に詰めて返す。
    """
    raw_key = R2Paths.raw_html(shop_id, date_str)
    ds_key = R2Paths.dataset_json(shop_id, date_str)
    ok_marker = R2Paths.ingest_marker(shop_id, date_str)
    miss_marker = ok_marker.replace(".ok", ".miss")

    # 1. 既存スキップ
    if skip_if_exists and r2.exists(ok_marker):
        return IngestResult(shop_id, date_str, "skip_existing", message="ok marker 存在")
    if skip_if_exists and r2.exists(miss_marker):
        return IngestResult(shop_id, date_str, "skip_existing", message="miss marker 存在")

    # 2. fetch
    try:
        html = fetch_shop_date_html(client, shop_slug=shop_slug, date_str=date_str)
    except CloudflareBlocked:
        # cf_clearance 失効 -> 全体を止める
        raise
    except HTTPError as e:
        msg = str(e)
        if "404" in msg or "410" in msg:
            # データ無し: miss marker
            r2.put_bytes(miss_marker, b"miss")
            logger.info("miss: shop=%s date=%s", shop_id, date_str)
            return IngestResult(shop_id, date_str, "miss", message=msg)
        logger.warning("HTTP error: shop=%s date=%s err=%s", shop_id, date_str, e)
        return IngestResult(shop_id, date_str, "error", message=msg)

    html_size = len(html)

    # 3. parse + check
    page = parse_ana_slo_html(html, machines_config=machines_config)
    rep = check_parsed_page(page, shop_id=shop_id, date_str=date_str)

    if not rep.ok:
        logger.warning(
            "check 失敗 shop=%s date=%s errors=%s", shop_id, date_str, rep.errors
        )
        return IngestResult(
            shop_id, date_str, "error",
            juggler_rows=len(page.rows),
            total_rows=page.total_rows_in_table,
            html_size=html_size,
            message=f"check.errors={rep.errors}",
        )

    # 4. R2 アップロード
    if upload_raw:
        r2.put_gzip_text(raw_key, html)
    if upload_dataset:
        r2.put_json(ds_key, page.to_dict(), gzipped=True)
    r2.put_bytes(ok_marker, b"ok")

    logger.info(
        "ok shop=%s date=%s juggler=%d total=%d size=%d",
        shop_id, date_str, len(page.rows), page.total_rows_in_table, html_size,
    )
    return IngestResult(
        shop_id, date_str, "ok",
        juggler_rows=len(page.rows),
        total_rows=page.total_rows_in_table,
        html_size=html_size,
    )
'''

# ---------------------------------------------------------------------------
# scripts/bootstrap.py
# ---------------------------------------------------------------------------
FILES["scripts/bootstrap.py"] = '''"""過去 N 日 × 全店舗の bootstrap 取得スクリプト。

使い方:
    # 1 店舗 過去 7 日
    uv run python scripts/bootstrap.py --shop kingsetagaya --days 7

    # 全店舗 過去 60 日 (本番)
    uv run python scripts/bootstrap.py --all --days 60

    # 取得済みも上書き
    uv run python scripts/bootstrap.py --all --days 60 --no-skip

    # スリープ間隔を変える
    uv run python scripts/bootstrap.py --all --days 60 --sleep 1.5
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import timedelta

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR
from juggler_predictor.common.dates import fmt_date, today_jst
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.pipeline.ingest_one import ingest_one
from juggler_predictor.scrape.http_client import AnaSloHTTPClient, CloudflareBlocked
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

logger = logging.getLogger(__name__)


def _load_shops_with_slug() -> list[dict]:
    raw = yaml.safe_load((CONFIG_DIR / "shops.yaml").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("shops", [])
    return [s for s in (items or []) if s.get("slug")]


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--shop", help="単一店舗の id")
    g.add_argument("--all", action="store_true", help="shops.yaml の全店舗")
    ap.add_argument("--days", type=int, default=7, help="過去何日 (今日含まず)")
    ap.add_argument("--start", help="開始日 YYYY-MM-DD (--days より優先)")
    ap.add_argument("--end", help="終了日 YYYY-MM-DD (--days より優先)")
    ap.add_argument("--sleep", type=float, default=1.0, help="1 リクエストごとのスリープ秒")
    ap.add_argument("--no-skip", action="store_true", help="取得済みもスキップしない")
    args = ap.parse_args()

    # 1. 対象店舗
    shops = _load_shops_with_slug()
    if args.shop:
        shops = [s for s in shops if s.get("id") == args.shop]
        if not shops:
            logger.error("shop=%s が shops.yaml に無い、または slug 未設定", args.shop)
            return 1
    if not shops:
        logger.error("対象店舗ゼロ。shops.yaml に slug が入っているか確認してください。")
        return 1

    # 2. 対象期間
    if args.start and args.end:
        from juggler_predictor.common.dates import parse_date_any, range_dates
        start = parse_date_any(args.start)
        end = parse_date_any(args.end)
        dates = [fmt_date(d) for d in range_dates(start, end)]
    else:
        end = today_jst() - timedelta(days=1)  # 昨日まで
        start = end - timedelta(days=args.days - 1)
        dates = [fmt_date(start + timedelta(days=i)) for i in range((end - start).days + 1)]

    logger.info("対象店舗: %d 件", len(shops))
    logger.info("対象期間: %s - %s (%d 日)", dates[0], dates[-1], len(dates))
    logger.info("総タスク: %d 件", len(shops) * len(dates))

    # 3. クッキー & クライアント
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    client = AnaSloHTTPClient(
        cookies=payload.get("cookies", []),
        user_agent=payload.get("user_agent"),
    )
    machines_cfg = yaml.safe_load((CONFIG_DIR / "machines.yaml").read_text(encoding="utf-8"))

    # 4. ループ
    counts: dict[str, int] = {"ok": 0, "skip_existing": 0, "miss": 0, "error": 0}
    total = len(shops) * len(dates)
    done = 0
    cf_blocked = False

    try:
        for shop in shops:
            for d in dates:
                done += 1
                try:
                    result = ingest_one(
                        r2=r2,
                        client=client,
                        shop_id=shop["id"],
                        shop_slug=shop["slug"],
                        date_str=d,
                        machines_config=machines_cfg,
                        skip_if_exists=not args.no_skip,
                    )
                except CloudflareBlocked as e:
                    logger.error("[CF BLOCKED] %s -- 処理を中断します", e)
                    cf_blocked = True
                    break

                counts[result.status] = counts.get(result.status, 0) + 1
                logger.info(
                    "[%4d/%4d] %s %s -> %s (juggler=%d size=%d)",
                    done, total, shop["id"], d, result.status,
                    result.juggler_rows, result.html_size,
                )

                if result.status not in ("skip_existing",) and args.sleep > 0:
                    time.sleep(args.sleep)
            if cf_blocked:
                break
    except KeyboardInterrupt:
        logger.warning("ユーザ中断")

    # 5. サマリ
    print()
    print("=" * 60)
    print("[BOOTSTRAP SUMMARY]")
    print("=" * 60)
    print(f"  ok           : {counts.get('ok', 0)}")
    print(f"  skip_existing: {counts.get('skip_existing', 0)}")
    print(f"  miss         : {counts.get('miss', 0)}")
    print(f"  error        : {counts.get('error', 0)}")
    print(f"  total        : {total}")
    print(f"  cf_blocked   : {cf_blocked}")
    print()
    return 0 if not cf_blocked else 2


if __name__ == "__main__":
    sys.exit(main())
'''

# ---------------------------------------------------------------------------
# .github/workflows/bootstrap.yml
# ---------------------------------------------------------------------------
FILES[".github/workflows/bootstrap.yml"] = '''name: bootstrap

on:
  workflow_dispatch:
    inputs:
      days:
        description: "過去何日分を取得するか (今日除く)"
        required: false
        default: "60"
      shop:
        description: "単一店舗 id を指定する場合 (空なら全店舗)"
        required: false
        default: ""
      sleep:
        description: "1 リクエスト間隔 (秒)"
        required: false
        default: "1.0"

jobs:
  bootstrap:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    env:
      R2_ENDPOINT:           ${{ secrets.R2_ENDPOINT }}
      R2_ACCESS_KEY_ID:      ${{ secrets.R2_ACCESS_KEY_ID }}
      R2_SECRET_ACCESS_KEY:  ${{ secrets.R2_SECRET_ACCESS_KEY }}
      R2_BUCKET:             ${{ secrets.R2_BUCKET }}
    steps:
      - uses: actions/checkout@v4

      - name: Setup uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "latest"

      - name: Setup Python
        run: uv python install 3.11

      - name: Sync deps
        run: uv sync --extra dev

      - name: Run bootstrap
        run: |
          set -e
          if [ -z "${{ inputs.shop }}" ]; then
            uv run python scripts/bootstrap.py --all --days "${{ inputs.days }}" --sleep "${{ inputs.sleep }}"
          else
            uv run python scripts/bootstrap.py --shop "${{ inputs.shop }}" --days "${{ inputs.days }}" --sleep "${{ inputs.sleep }}"
          fi
'''

# ---------------------------------------------------------------------------
# tests/test_pipeline_ingest_one.py
# ---------------------------------------------------------------------------
FILES["tests/test_pipeline_ingest_one.py"] = '''"""ingest_one のユニットテスト (R2 / HTTP は fake で差し替え)。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
import pytest

from juggler_predictor.pipeline.ingest_one import ingest_one
from juggler_predictor.scrape.http_client import CloudflareBlocked, HTTPError

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "kingsetagaya_2026-05-05.html"
)
MACHINES = (
    Path(__file__).resolve().parents[1] / "config" / "machines.yaml"
)


@pytest.fixture(scope="module")
def html() -> str:
    if not FIXTURE.exists():
        pytest.skip("fixture missing")
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def machines_cfg() -> dict:
    return yaml.safe_load(MACHINES.read_text(encoding="utf-8"))


def _fake_r2(existing: set[str] | None = None) -> MagicMock:
    existing = existing or set()
    r2 = MagicMock()
    r2.exists.side_effect = lambda key: key in existing
    return r2


def _fake_client(html: str) -> MagicMock:
    client = MagicMock()
    client.get.return_value = html
    return client


def test_skip_if_ok_marker_exists(html: str, machines_cfg: dict) -> None:
    r2 = _fake_r2(existing={"markers/ingest/kingsetagaya/2026-05-05.ok"})
    client = _fake_client(html)
    res = ingest_one(
        r2=r2, client=client,
        shop_id="kingsetagaya", shop_slug="キングno-1世田谷店",
        date_str="2026-05-05", machines_config=machines_cfg,
    )
    assert res.status == "skip_existing"
    r2.put_bytes.assert_not_called()


def test_ok_path_uploads_raw_dataset_marker(html: str, machines_cfg: dict) -> None:
    r2 = _fake_r2()
    client = _fake_client(html)
    res = ingest_one(
        r2=r2, client=client,
        shop_id="kingsetagaya", shop_slug="キングno-1世田谷店",
        date_str="2026-05-05", machines_config=machines_cfg,
    )
    assert res.status == "ok"
    assert res.juggler_rows > 0
    # raw + dataset + marker の 3 種が書かれた
    keys_written = [c.args[0] for c in r2.put_gzip_text.call_args_list] + \\
                   [c.args[0] for c in r2.put_json.call_args_list] + \\
                   [c.args[0] for c in r2.put_bytes.call_args_list]
    assert any("raw/" in k for k in keys_written)
    assert any("dataset/" in k for k in keys_written)
    assert any(".ok" in k for k in keys_written)


def test_404_marks_as_miss(machines_cfg: dict) -> None:
    r2 = _fake_r2()
    client = MagicMock()
    client.get.side_effect = HTTPError("HTTP 404 url=...")
    res = ingest_one(
        r2=r2, client=client,
        shop_id="kingsetagaya", shop_slug="キングno-1世田谷店",
        date_str="2099-01-01", machines_config=machines_cfg,
    )
    assert res.status == "miss"
    miss_calls = [c.args[0] for c in r2.put_bytes.call_args_list]
    assert any(".miss" in k for k in miss_calls)


def test_cf_blocked_propagates(machines_cfg: dict) -> None:
    r2 = _fake_r2()
    client = MagicMock()
    client.get.side_effect = CloudflareBlocked("403")
    with pytest.raises(CloudflareBlocked):
        ingest_one(
            r2=r2, client=client,
            shop_id="kingsetagaya", shop_slug="キングno-1世田谷店",
            date_str="2026-05-05", machines_config=machines_cfg,
        )
'''


def main() -> None:
    print("=" * 60)
    print("P3a: bootstrap pipeline")
    print("=" * 60)
    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")
    print()
    print("[OK] 生成完了")
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print("  uv run python scripts/bootstrap.py --shop kingsetagaya --days 7 --sleep 1.0")


if __name__ == "__main__":
    main()
