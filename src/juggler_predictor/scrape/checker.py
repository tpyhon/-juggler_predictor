"""パース後データの品質チェック。"""
from __future__ import annotations

from dataclasses import dataclass, field

from juggler_predictor.scrape.parser import ParsedPage


@dataclass
class CheckReport:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    juggler_rows: int = 0
    total_rows: int = 0


# 1 店舗で見込まれるジャグラー台の最低台数 (これより少なければ取得失敗を疑う)
MIN_JUGGLER_ROWS = 5


def check_parsed_page(page: ParsedPage, *, shop_id: str, date_str: str) -> CheckReport:
    """:class:`ParsedPage` を検査して :class:`CheckReport` を返す。"""
    rep = CheckReport(
        ok=True,
        juggler_rows=len(page.rows),
        total_rows=page.total_rows_in_table,
    )

    if page.date_str is None:
        rep.errors.append("date_str がパースできていない")
    elif page.date_str != date_str:
        rep.errors.append(
            f"date 不一致: expected={date_str} actual={page.date_str}"
        )

    if page.shop_display_name is None:
        rep.warnings.append("shop_display_name がパースできていない")

    if page.total_rows_in_table == 0:
        rep.errors.append("テーブル本体が 0 行 (取得失敗の可能性)")

    if len(page.rows) < MIN_JUGGLER_ROWS:
        rep.warnings.append(
            f"ジャグラー台数が少ない rows={len(page.rows)} shop={shop_id}"
        )

    # 全行の差枚が None / 0 なら何かおかしい
    has_meaningful_diff = any(
        r.diff is not None and r.diff != 0 for r in page.rows
    )
    if page.rows and not has_meaningful_diff:
        rep.warnings.append("差枚が全行 None/0: データ欠損の可能性")

    if rep.errors:
        rep.ok = False
    return rep
