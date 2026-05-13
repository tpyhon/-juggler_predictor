"""tools/check_note_session.py の単体テスト。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from check_note_session import days_until_expiry  # noqa: E402


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def test_cookie_60_days_left():
    expires = _now_ts() + 60 * 86400
    state = {"cookies": [{"name": "_note_session_v5", "expires": expires}]}
    days = days_until_expiry(state)
    assert days is not None
    assert 59.5 < days < 60.5


def test_cookie_5_days_left():
    expires = _now_ts() + 5 * 86400
    state = {"cookies": [{"name": "_note_session_v5", "expires": expires}]}
    days = days_until_expiry(state)
    assert days is not None
    assert 4.5 < days < 5.5


def test_cookie_no_expiry():
    state = {"cookies": [{"name": "_note_session_v5", "expires": -1}]}
    assert days_until_expiry(state) is None


def test_cookie_not_found():
    state = {"cookies": [{"name": "other_cookie", "expires": _now_ts() + 86400}]}
    assert days_until_expiry(state) is None
