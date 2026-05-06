"""日付ユーティリティ. JST を全プロジェクトで統一."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

JST = timezone(timedelta(hours=9), name="JST")


def today_jst() -> date:
    """JST における今日."""
    return datetime.now(JST).date()


def now_jst() -> datetime:
    """JST における現在時刻 (tz-aware)."""
    return datetime.now(JST)


def to_jst(dt: datetime) -> datetime:
    """任意の datetime を JST に変換. naive は JST とみなす."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def parse_date_any(s: str | date | datetime) -> date:
    """\"2025-01-15\", \"2025/1/15\", \"20250115\", date, datetime を date に統一."""
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日付として解釈できません: {s!r}")


def range_dates(start: date | str, end: date | str, *, inclusive: bool = True) -> list[date]:
    """[start, end] の日付リスト. inclusive=False で end を除外."""
    s = parse_date_any(start)
    e = parse_date_any(end)
    if e < s:
        raise ValueError(f"end < start: {s} -> {e}")
    days = (e - s).days + (1 if inclusive else 0)
    return [s + timedelta(days=i) for i in range(days)]


def fmt_date(d: date, sep: str = "-") -> str:
    """YYYY{sep}MM{sep}DD."""
    return d.strftime(f"%Y{sep}%m{sep}%d")


def daterange_iter(start: date, end: date) -> Iterable[date]:
    """ジェネレータ版."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)
