"""ingest_one のユニットテスト (R2 / HTTP は fake で差し替え)。"""
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
    keys_written = [c.args[0] for c in r2.put_gzip_text.call_args_list] + \
                   [c.args[0] for c in r2.put_json.call_args_list] + \
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
