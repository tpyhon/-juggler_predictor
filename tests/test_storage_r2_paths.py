"""R2Paths のキー命名規約テスト (R2 通信なし)。"""
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
