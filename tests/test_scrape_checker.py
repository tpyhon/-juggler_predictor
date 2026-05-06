"""checker.py のユニットテスト (HTTP 通信なし)。"""
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
