"""parser.py のユニットテスト。

実 HTML (tests/fixtures/kingsetagaya_2026-05-05.html) を fixture として使用。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from juggler_predictor.scrape.parser import (
    MachineRow,
    ParsedPage,
    parse_ana_slo_html,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "kingsetagaya_2026-05-05.html"
)
MACHINES_YAML = (
    Path(__file__).resolve().parents[1] / "config" / "machines.yaml"
)


@pytest.fixture(scope="module")
def fixture_html() -> str:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"fixture not found: {FIXTURE_PATH}")
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def machines_config() -> dict:
    return yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8"))


def test_parsed_page_has_basic_fields(fixture_html: str, machines_config: dict) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)

    assert isinstance(page, ParsedPage)
    assert page.date_str == "2026-05-05"
    assert page.shop_display_name is not None
    assert "世田谷" in page.shop_display_name


def test_juggler_filter_returns_only_whitelisted_machines(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)

    canonical_set = {m["canonical"] for m in machines_config["machines"]}
    assert len(page.rows) > 0, "ジャグラーが 1 台も検出されない"
    for row in page.rows:
        assert row.machine_name in canonical_set, (
            f"想定外の機種が混入: {row.machine_name}"
        )


def test_total_rows_greater_than_filtered(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    assert page.total_rows_in_table > len(page.rows)
    assert page.total_rows_in_table > 50


def test_each_row_has_expected_types(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    for row in page.rows:
        assert isinstance(row, MachineRow)
        assert isinstance(row.machine_name, str) and row.machine_name
        assert row.unit_number is None or isinstance(row.unit_number, str)
        for v in (row.g_count, row.bb, row.rb, row.diff):
            assert v is None or isinstance(v, int)


def test_no_juggler_filter_returns_all(fixture_html: str) -> None:
    page = parse_ana_slo_html(fixture_html, juggler_only=False)
    assert len(page.rows) == page.total_rows_in_table
    assert len(page.rows) > 50


def test_diff_values_are_within_reasonable_range(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    for row in page.rows:
        if row.diff is None:
            continue
        assert -30000 <= row.diff <= 30000, (
            f"差枚が異常: {row.machine_name} {row.unit_number} = {row.diff}"
        )


def test_bb_rb_are_non_negative(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    for row in page.rows:
        if row.bb is not None:
            assert row.bb >= 0
        if row.rb is not None:
            assert row.rb >= 0


def test_to_dict_serializable(fixture_html: str, machines_config: dict) -> None:
    import json

    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    d = page.to_dict()
    s = json.dumps(d, ensure_ascii=False)
    assert "machine_name" in s
    assert page.date_str in s
