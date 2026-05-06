"""common/ モジュールの単体テスト."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from juggler_predictor.common.dates import (
    fmt_date,
    parse_date_any,
    range_dates,
    today_jst,
)
from juggler_predictor.common.io_json import (
    dump_json_bytes,
    load_json,
    load_json_bytes,
    load_json_gz,
    save_json,
    save_json_gz,
)
from juggler_predictor.common.normalize import (
    build_alias_map,
    normalize_machine_name,
    normalize_unit_number,
)
from juggler_predictor.common.nums import clip, minmax_normalize, safe_float, safe_int
from juggler_predictor.common.shops import all_shop_ids, get_shop, load_shops


# ---------- dates ----------
def test_parse_date_any_formats() -> None:
    assert parse_date_any("2025-01-15") == date(2025, 1, 15)
    assert parse_date_any("2025/1/15") == date(2025, 1, 15)
    assert parse_date_any("20250115") == date(2025, 1, 15)
    assert parse_date_any(date(2025, 1, 15)) == date(2025, 1, 15)
    assert parse_date_any(datetime(2025, 1, 15, 12, 0)) == date(2025, 1, 15)


def test_parse_date_any_invalid() -> None:
    with pytest.raises(ValueError):
        parse_date_any("not-a-date")


def test_range_dates() -> None:
    rs = range_dates("2025-01-01", "2025-01-03")
    assert rs == [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    rs = range_dates("2025-01-01", "2025-01-03", inclusive=False)
    assert rs == [date(2025, 1, 1), date(2025, 1, 2)]


def test_today_jst() -> None:
    assert isinstance(today_jst(), date)


def test_fmt_date() -> None:
    assert fmt_date(date(2025, 1, 15)) == "2025-01-15"
    assert fmt_date(date(2025, 1, 15), sep="/") == "2025/01/15"


# ---------- nums ----------
def test_safe_float() -> None:
    assert safe_float("1,234.5") == 1234.5
    assert safe_float("１２３４") == 1234.0
    assert safe_float("") == 0.0
    assert safe_float("-") == 0.0
    assert safe_float(None) == 0.0
    assert safe_float("abc", default=-1.0) == -1.0


def test_safe_int() -> None:
    assert safe_int("1,234") == 1234
    assert safe_int("1.7") == 1
    assert safe_int("") == 0


def test_clip() -> None:
    assert clip(5, 0, 10) == 5
    assert clip(-5, 0, 10) == 0
    assert clip(15, 0, 10) == 10
    with pytest.raises(ValueError):
        clip(0, 10, 0)


def test_minmax_normalize() -> None:
    assert minmax_normalize([0.0, 5.0, 10.0]) == [0.0, 0.5, 1.0]
    assert minmax_normalize([3.0, 3.0, 3.0]) == [0.5, 0.5, 0.5]
    assert minmax_normalize([]) == []


# ---------- normalize ----------
def test_normalize_machine_name(sample_machines_config: list[dict]) -> None:
    amap = build_alias_map(sample_machines_config)
    assert normalize_machine_name("マイジャグラーⅤ", amap) == "マイジャグラーV"
    assert normalize_machine_name("マイジャグラー5", amap) == "マイジャグラーV"
    assert normalize_machine_name("マイジャグラーV", amap) == "マイジャグラーV"
    assert normalize_machine_name("ファンキージャグラーⅡ", amap) == "ファンキージャグラー2"
    assert normalize_machine_name("謎の機種", amap) == "謎の機種"


def test_normalize_unit_number() -> None:
    assert normalize_unit_number("123") == "123"
    assert normalize_unit_number("0123") == "0123"
    assert normalize_unit_number("123番") == "123"
    assert normalize_unit_number("#123") == "123"
    assert normalize_unit_number(123) == "123"


# ---------- io_json ----------
def test_save_load_json(tmp_path) -> None:
    p = tmp_path / "x.json"
    save_json(p, {"a": 1, "日本語": "テスト"})
    assert load_json(p) == {"a": 1, "日本語": "テスト"}


def test_save_load_json_gz(tmp_path) -> None:
    p = tmp_path / "x.json.gz"
    save_json_gz(p, {"a": [1, 2, 3]})
    assert load_json_gz(p) == {"a": [1, 2, 3]}


def test_json_bytes_roundtrip() -> None:
    obj = {"日本語キー": [1, 2, 3]}
    raw = dump_json_bytes(obj)
    assert load_json_bytes(raw) == obj
    gz = dump_json_bytes(obj, gz=True)
    assert load_json_bytes(gz, gz=True) == obj


# ---------- shops ----------
def test_load_shops_no_dup() -> None:
    shops = load_shops()
    assert len(shops) == 19
    assert len({s.id for s in shops}) == 19


def test_get_shop() -> None:
    s = get_shop("kingsetagaya")
    assert s.display_name == "キングNo.1世田谷店"
    assert s.region == "tokyo"
    assert "master" in s.note_plans


def test_get_shop_unknown() -> None:
    with pytest.raises(KeyError):
        get_shop("not_exist")


def test_all_shop_ids() -> None:
    ids = all_shop_ids()
    assert "kingsetagaya" in ids
    assert "espas_seibushinjuku" in ids
