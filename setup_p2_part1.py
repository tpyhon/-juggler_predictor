"""
P2 Part 1: parser.py + tests を生成するセットアップスクリプト
- src/juggler_predictor/scrape/__init__.py
- src/juggler_predictor/scrape/parser.py
- tests/test_scrape_parser.py
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# src/juggler_predictor/scrape/__init__.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/__init__.py"] = '''"""スクレイピング層パッケージ。

ana-slo.com からホールデータを取得し、機種ごとの台データに変換するモジュール群。
"""
from juggler_predictor.scrape.parser import (
    MachineRow,
    ParsedPage,
    parse_ana_slo_html,
)

__all__ = [
    "MachineRow",
    "ParsedPage",
    "parse_ana_slo_html",
]
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/scrape/parser.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/scrape/parser.py"] = '''"""ana-slo.com の HTML を機種・台単位の構造化データに変換するパーサ。

設計メモ:
- メインの台データは ``<h4>全データ一覧</h4>`` 直後の
  ``<table class="fixed_get_medals_table">`` に集約されている。
- ヘッダ列: 機種名 / 台番号 / G数 / 差枚 / BB / RB / ART / 合成確率 / BB確率 / RB確率 / ART確率
- ジャグラーシリーズのみ machines.yaml のホワイトリストでフィルタする。
- 値が "-" や空文字、"1/0.00" など欠損のセルは None で返す。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from bs4 import BeautifulSoup, Tag

from juggler_predictor.common.normalize import (
    build_alias_map,
    normalize_machine_name,
    normalize_unit_number,
)
from juggler_predictor.common.nums import safe_int

# ヘッダ列名 → 内部キー
HEADER_MAP: dict[str, str] = {
    "機種名": "machine_name_raw",
    "台番号": "unit_number_raw",
    "台番": "unit_number_raw",
    "G数": "g_count",
    "ゲーム数": "g_count",
    "差枚": "diff",
    "差枚数": "diff",
    "BB": "bb",
    "RB": "rb",
    "ART": "art",
    "合成確率": "composite_prob",
    "合成": "composite_prob",
    "BB確率": "bb_prob",
    "RB確率": "rb_prob",
    "ART確率": "art_prob",
}

# タイトル例: "2026/05/05 キングNo.1世田谷店 データまとめ"
TITLE_DATE_RE = re.compile(r"(\\d{4})[/-](\\d{1,2})[/-](\\d{1,2})")


@dataclass
class MachineRow:
    """1 台 1 行分のスクレイピング結果。"""

    machine_name: str          # 正規化後の機種名 (例: "マイジャグラーV")
    machine_name_raw: str      # HTML上の生文字列
    unit_number: str | None    # 正規化後の台番号 (例: "123")
    unit_number_raw: str       # HTML上の生文字列
    g_count: int | None
    diff: int | None
    bb: int | None
    rb: int | None
    art: int | None = None
    composite_prob: str | None = None
    bb_prob: str | None = None
    rb_prob: str | None = None
    art_prob: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedPage:
    """ページ単位のパース結果。"""

    shop_display_name: str | None
    date_str: str | None        # "YYYY-MM-DD" 形式
    rows: list[MachineRow] = field(default_factory=list)
    total_rows_in_table: int = 0  # フィルタ前の全行数（デバッグ用）

    def to_dict(self) -> dict[str, Any]:
        return {
            "shop_display_name": self.shop_display_name,
            "date_str": self.date_str,
            "rows": [r.to_dict() for r in self.rows],
            "total_rows_in_table": self.total_rows_in_table,
        }


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------
def parse_ana_slo_html(
    html: str,
    *,
    machines_config: dict[str, Any] | None = None,
    juggler_only: bool = True,
) -> ParsedPage:
    """ana-slo.com の HTML を解析して :class:`ParsedPage` を返す。

    Parameters
    ----------
    html:
        取得済みの HTML 文字列。
    machines_config:
        ``config/machines.yaml`` をロードした dict。``None`` の場合はフィルタなし。
    juggler_only:
        ``True`` (既定) の場合、machines_config のホワイトリストに含まれる
        機種のみを返す。``False`` なら全機種を返す。
    """
    soup = BeautifulSoup(html, "lxml")

    shop_name, date_str = _extract_title_info(soup)
    table = _find_main_table(soup)
    if table is None:
        return ParsedPage(shop_display_name=shop_name, date_str=date_str)

    headers = _parse_headers(table)
    raw_rows = _parse_body_rows(table, headers)

    alias_map: dict[str, str] = {}
    canonical_set: set[str] = set()
    if machines_config is not None:
        alias_map = build_alias_map(machines_config)
        canonical_set = {
            m["canonical_name"]
            for m in machines_config.get("machines", [])
            if "canonical_name" in m
        }

    rows: list[MachineRow] = []
    for r in raw_rows:
        raw_name = r.get("machine_name_raw", "")
        normalized = normalize_machine_name(raw_name, alias_map) if alias_map else raw_name
        if juggler_only and canonical_set and normalized not in canonical_set:
            continue

        unit_raw = r.get("unit_number_raw", "")
        rows.append(
            MachineRow(
                machine_name=normalized,
                machine_name_raw=raw_name,
                unit_number=normalize_unit_number(unit_raw),
                unit_number_raw=unit_raw,
                g_count=safe_int(r.get("g_count")),
                diff=safe_int(r.get("diff")),
                bb=safe_int(r.get("bb")),
                rb=safe_int(r.get("rb")),
                art=safe_int(r.get("art")),
                composite_prob=_clean_prob(r.get("composite_prob")),
                bb_prob=_clean_prob(r.get("bb_prob")),
                rb_prob=_clean_prob(r.get("rb_prob")),
                art_prob=_clean_prob(r.get("art_prob")),
            )
        )

    return ParsedPage(
        shop_display_name=shop_name,
        date_str=date_str,
        rows=rows,
        total_rows_in_table=len(raw_rows),
    )


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------
def _extract_title_info(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """``<h1 class="entry-title">`` から店舗名と日付を抽出する。"""
    h1 = soup.find("h1", class_="entry-title")
    if h1 is None:
        return None, None
    title = h1.get_text(strip=True)

    date_str: str | None = None
    m = TITLE_DATE_RE.search(title)
    if m:
        y, mo, d = m.groups()
        date_str = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    # 日付部分を除いた残りから店舗名を切り出す
    shop_name: str | None = None
    after = TITLE_DATE_RE.sub("", title).strip()
    # "キングNo.1世田谷店 データまとめ" → "キングNo.1世田谷店"
    after = re.sub(r"データまとめ$", "", after).strip()
    if after:
        shop_name = after

    return shop_name, date_str


def _find_main_table(soup: BeautifulSoup) -> Tag | None:
    """``<h4>全データ一覧</h4>`` 直後の fixed_get_medals_table を返す。"""
    # 1) h4 ベース
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = h.get_text(strip=True)
        if "全データ一覧" in text:
            tbl = h.find_next("table", class_="fixed_get_medals_table")
            if tbl is not None:
                return tbl

    # 2) フォールバック: 最初の fixed_get_medals_table
    return soup.find("table", class_="fixed_get_medals_table")


def _parse_headers(table: Tag) -> list[str]:
    """先頭行のヘッダを内部キーのリストに変換する。"""
    first_tr = table.find("tr")
    if first_tr is None:
        return []
    cells = first_tr.find_all(["th", "td"])
    keys: list[str] = []
    for c in cells:
        label = c.get_text(strip=True)
        keys.append(HEADER_MAP.get(label, f"_unknown_{label}"))
    return keys


def _parse_body_rows(table: Tag, headers: list[str]) -> list[dict[str, str]]:
    """データ行を ``[{key: value}, ...]`` の形式で返す。"""
    rows: list[dict[str, str]] = []
    trs: Iterable[Tag] = table.find_all("tr")
    for i, tr in enumerate(trs):
        if i == 0:
            continue  # ヘッダ行
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row: dict[str, str] = {}
        for key, cell in zip(headers, cells):
            row[key] = cell.get_text(strip=True)
        # 機種名が空の行はスキップ
        if not row.get("machine_name_raw"):
            continue
        rows.append(row)
    return rows


def _clean_prob(value: str | None) -> str | None:
    """確率文字列のクリーニング。空 / "-" / "1/0.00" は None。"""
    if value is None:
        return None
    v = value.strip()
    if not v or v in {"-", "ー", "—", "/"}:
        return None
    if v in {"1/0.00", "1/0", "1/-"}:
        return None
    return v
'''

# ---------------------------------------------------------------------------
# tests/test_scrape_parser.py
# ---------------------------------------------------------------------------
FILES["tests/test_scrape_parser.py"] = '''"""parser.py のユニットテスト。

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fixture_html() -> str:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"fixture not found: {FIXTURE_PATH}")
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def machines_config() -> dict:
    return yaml.safe_load(MACHINES_YAML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
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

    canonical_set = {
        m["canonical_name"] for m in machines_config["machines"]
    }
    assert len(page.rows) > 0, "ジャグラーが 1 台も検出されない"
    for row in page.rows:
        assert row.machine_name in canonical_set, (
            f"想定外の機種が混入: {row.machine_name}"
        )


def test_total_rows_greater_than_filtered(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    # フィルタ前は数百行、フィルタ後はジャグラー台のみで通常はずっと少ない
    assert page.total_rows_in_table > len(page.rows)
    assert page.total_rows_in_table > 50


def test_each_row_has_expected_types(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    for row in page.rows:
        assert isinstance(row, MachineRow)
        assert isinstance(row.machine_name, str) and row.machine_name
        # 台番号は文字列 or None
        assert row.unit_number is None or isinstance(row.unit_number, str)
        # g_count, bb, rb, diff は int or None
        for v in (row.g_count, row.bb, row.rb, row.diff):
            assert v is None or isinstance(v, int)


def test_no_juggler_filter_returns_all(fixture_html: str) -> None:
    page = parse_ana_slo_html(fixture_html, juggler_only=False)
    # フィルタなしでは全機種が rows に入る
    assert len(page.rows) == page.total_rows_in_table
    assert len(page.rows) > 50


def test_diff_values_are_within_reasonable_range(
    fixture_html: str, machines_config: dict
) -> None:
    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    for row in page.rows:
        if row.diff is None:
            continue
        # スロットの差枚は通常 -20000 〜 +20000 の範囲
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
    """JSON シリアライズ可能であること。"""
    import json

    page = parse_ana_slo_html(fixture_html, machines_config=machines_config)
    d = page.to_dict()
    s = json.dumps(d, ensure_ascii=False)
    assert "machine_name" in s
    assert page.date_str in s
'''


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("P2 Part 1: parser + tests を生成します")
    print("=" * 60)

    for rel_path, content in FILES.items():
        target = ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # LF 改行で書き出す
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [WRITE] {rel_path}  ({len(content):,} chars)")

    fixture = ROOT / "tests" / "fixtures" / "kingsetagaya_2026-05-05.html"
    if fixture.exists():
        size = fixture.stat().st_size
        print(f"  [OK] fixture 確認: {fixture.relative_to(ROOT)}  ({size:,} bytes)")
    else:
        print(f"  [WARN] fixture が見つかりません: {fixture}")
        print("        Copy-Item tools\\samples\\kingsetagaya_2026-05-05_via_curl.html "
              "tests\\fixtures\\kingsetagaya_2026-05-05.html を実行してください")

    print()
    print("=" * 60)
    print("[SUCCESS] P2 Part 1 ファイル生成 完了")
    print("=" * 60)
    print()
    print("次のコマンド:")
    print("  uv run pytest tests/test_scrape_parser.py -v")
    print()


if __name__ == "__main__":
    main()
