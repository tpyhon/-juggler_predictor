"""P2 Part 1 ホットフィックス: parser.py の machines_config I/F を修正する。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "juggler_predictor" / "scrape" / "parser.py"

NEW_CONTENT = '''"""ana-slo.com の HTML を機種・台単位の構造化データに変換するパーサ。

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

TITLE_DATE_RE = re.compile(r"(\\d{4})[/-](\\d{1,2})[/-](\\d{1,2})")


@dataclass
class MachineRow:
    machine_name: str
    machine_name_raw: str
    unit_number: str | None
    unit_number_raw: str
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
    shop_display_name: str | None
    date_str: str | None
    rows: list[MachineRow] = field(default_factory=list)
    total_rows_in_table: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "shop_display_name": self.shop_display_name,
            "date_str": self.date_str,
            "rows": [r.to_dict() for r in self.rows],
            "total_rows_in_table": self.total_rows_in_table,
        }


def _extract_machines_list(machines_config: Any) -> list[dict]:
    """machines_config から machine 定義のリストを取り出す。

    - dict 形式 ({"machines": [...], "clip_diff": ...}) なら "machines" を返す。
    - すでに list なら そのまま返す。
    - それ以外は空リスト。
    """
    if machines_config is None:
        return []
    if isinstance(machines_config, dict):
        return list(machines_config.get("machines", []))
    if isinstance(machines_config, list):
        return list(machines_config)
    return []


def parse_ana_slo_html(
    html: str,
    *,
    machines_config: Any = None,
    juggler_only: bool = True,
) -> ParsedPage:
    """ana-slo.com の HTML を解析して :class:`ParsedPage` を返す。"""
    soup = BeautifulSoup(html, "lxml")

    shop_name, date_str = _extract_title_info(soup)
    table = _find_main_table(soup)
    if table is None:
        return ParsedPage(shop_display_name=shop_name, date_str=date_str)

    headers = _parse_headers(table)
    raw_rows = _parse_body_rows(table, headers)

    machine_list = _extract_machines_list(machines_config)
    alias_map: dict[str, str] = {}
    canonical_set: set[str] = set()
    if machine_list:
        alias_map = build_alias_map(machine_list)
        canonical_set = {m["canonical"] for m in machine_list if "canonical" in m}

    rows: list[MachineRow] = []
    for r in raw_rows:
        raw_name = r.get("machine_name_raw", "")
        normalized = (
            normalize_machine_name(raw_name, alias_map) if alias_map else raw_name
        )
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


def _extract_title_info(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    h1 = soup.find("h1", class_="entry-title")
    if h1 is None:
        return None, None
    title = h1.get_text(strip=True)

    date_str: str | None = None
    m = TITLE_DATE_RE.search(title)
    if m:
        y, mo, d = m.groups()
        date_str = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    shop_name: str | None = None
    after = TITLE_DATE_RE.sub("", title).strip()
    after = re.sub(r"データまとめ$", "", after).strip()
    if after:
        shop_name = after

    return shop_name, date_str


def _find_main_table(soup: BeautifulSoup) -> Tag | None:
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = h.get_text(strip=True)
        if "全データ一覧" in text:
            tbl = h.find_next("table", class_="fixed_get_medals_table")
            if tbl is not None:
                return tbl
    return soup.find("table", class_="fixed_get_medals_table")


def _parse_headers(table: Tag) -> list[str]:
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
    rows: list[dict[str, str]] = []
    trs: Iterable[Tag] = table.find_all("tr")
    for i, tr in enumerate(trs):
        if i == 0:
            continue
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row: dict[str, str] = {}
        for key, cell in zip(headers, cells):
            row[key] = cell.get_text(strip=True)
        if not row.get("machine_name_raw"):
            continue
        rows.append(row)
    return rows


def _clean_prob(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v or v in {"-", "ー", "—", "/"}:
        return None
    if v in {"1/0.00", "1/0", "1/-"}:
        return None
    return v
'''


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(NEW_CONTENT, encoding="utf-8", newline="\n")
    print(f"[WRITE] {TARGET.relative_to(ROOT)}  ({len(NEW_CONTENT):,} chars)")
    print("[OK] parser.py を修正しました")
    print()
    print("次のコマンド:")
    print("  uv run pytest tests/test_scrape_parser.py -v")


if __name__ == "__main__":
    main()
