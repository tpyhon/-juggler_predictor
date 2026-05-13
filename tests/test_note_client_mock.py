"""NoteClient のモックテスト (実 API は叩かない)。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from juggler_predictor.note.client import NoteClient


def _mock_response(status: int = 200, json_data: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = str(json_data or "")
    return m


def test_login_with_session_cookie(monkeypatch):
    monkeypatch.setenv("NOTE_SESSION_COOKIE", "fake_cookie_value")
    client = NoteClient()
    with patch.object(
        client.session, "post",
        return_value=_mock_response(200, {"data": {"id": 123, "key": "abc"}}),
    ):
        client.login()
    assert client._prefetched_draft is not None
    assert client._prefetched_draft["id"] == 123


def test_login_no_credentials(monkeypatch):
    monkeypatch.delenv("NOTE_SESSION_COOKIE", raising=False)
    monkeypatch.delenv("NOTE_EMAIL", raising=False)
    monkeypatch.delenv("NOTE_PASSWORD", raising=False)
    client = NoteClient()
    with pytest.raises(RuntimeError, match="NOTE_SESSION_COOKIE"):
        client.login()


def test_create_draft_uses_prefetched():
    client = NoteClient()
    client._prefetched_draft = {"id": 999, "key": "xyz"}
    draft = client.create_draft()
    assert draft["id"] == 999
    assert client._prefetched_draft is None  # 消費されること


def test_post_full_flow(monkeypatch):
    monkeypatch.setenv("NOTE_SESSION_COOKIE", "fake")
    client = NoteClient()
    responses = [
        _mock_response(200, {"data": {"id": 1, "key": "k1"}}),  # login -> create draft
        _mock_response(200, {}),  # save_draft
        _mock_response(200, {}),  # publish
    ]
    with patch.object(client.session, "post", side_effect=responses):
        client.login()
        url = client.post("title", "<p>body</p>", price=300)
    assert url == "https://note.com/notes/k1"
