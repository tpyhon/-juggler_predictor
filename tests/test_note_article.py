"""note_article.py のユニットテスト (Phase 1.5)。"""
from __future__ import annotations

import pandas as pd
import pytest

from juggler_predictor.report.note_article import render_article


def _make_rows(n: int = 12, p_high_top: float = 0.80) -> pd.DataFrame:
    rows = []
    for i in range(n):
        p_high = max(0.05, p_high_top - i * 0.05)
        p_top = p_high * 0.6
        p6 = p_high * 0.3
        exp = 1 + 5 * p_high
        prev_diff = 4000 - i * 400
        prev_set = 6 if p_high > 0.7 else (5 if p_high > 0.5 else 3)
        rows.append(
            {
                "unit_number": 2000 + i,
                "machine_name": "マイジャグラーV",
                "p_high": p_high,
                "p_top": p_top,
                "p_setting6": p6,
                "expected_setting": exp,
                "prev_diff": prev_diff,
                "prev_setting": prev_set,
                "score_a": 0.5 * p_high + 0.3 * p_top + 0.2 * 0.5,
            }
        )
    return pd.DataFrame(rows)


def test_render_article_go():
    rows = _make_rows(n=12, p_high_top=0.80)
    md = render_article(
        shop_id="test_shop",
        shop_display_name="テスト店舗",
        target_date="2026-05-05",
        input_date="2026-05-04",
        rows=rows,
    )
    assert "テスト店舗" in md
    assert "2026-05-05" in md
    assert "GO" in md
    assert "高設定期待度" in md
    # 予測差枚という文字列は廃止
    assert "予測差枚" not in md
    # 前日実績は残す
    assert "前日実績" in md
    # TOP10 ヘッダー
    assert "推奨台 TOP10" in md
    # 注意事項
    assert "実際の設定を保証" in md


def test_render_article_no_go():
    rows = _make_rows(n=12, p_high_top=0.30)  # 全台 p_high < 0.5
    md = render_article(
        shop_id="test_shop",
        shop_display_name="テスト店舗",
        target_date="2026-05-05",
        input_date="2026-05-04",
        rows=rows,
    )
    assert "NO-GO" in md
    assert "見送り" in md


def test_render_article_empty():
    md = render_article(
        shop_id="test_shop",
        shop_display_name="テスト店舗",
        target_date="2026-05-05",
        input_date="2026-05-04",
        rows=pd.DataFrame(),
    )
    assert "対象データがありません" in md


def test_render_article_no_predicted_diff_label():
    rows = _make_rows(n=8, p_high_top=0.60)
    md = render_article(
        shop_id="test_shop",
        shop_display_name="テスト店舗",
        target_date="2026-05-05",
        input_date="2026-05-04",
        rows=rows,
    )
    # 予測差枚ラベルが残っていないこと
    assert "予測差枚" not in md
    # モデルの p_win 表記も無いこと
    assert "翌日p_win" not in md
