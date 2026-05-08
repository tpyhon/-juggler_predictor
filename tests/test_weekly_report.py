"""週次レポート Markdown 生成のテスト。"""
import pandas as pd

from juggler_predictor.report.weekly import render_weekly_report


def _make_metrics(n: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "shop_id": f"shop_{i}",
                "display_name": f"店舗{i}",
                "n_days": 7,
                "top1_hit_rate": 0.30 + i * 0.10,
                "top1_avg_diff": 500 + i * 200,
                "top3_avg_diff": 300 + i * 150,
                "high_count_avg": 8.0 + i,
            }
        )
    return pd.DataFrame(rows)


def test_render_weekly_basic():
    md = render_weekly_report(
        week_start="2026-04-27",
        week_end="2026-05-03",
        shop_metrics=_make_metrics(3),
        overall_hit_rate=0.40,
        overall_top1_avg_diff=700.0,
    )
    assert "週次レポート" in md
    assert "2026-04-27" in md
    assert "2026-05-03" in md
    assert "40.0%" in md or "40%" in md
    assert "+700枚" in md
    assert "店舗0" in md and "店舗2" in md
    # 表ヘッダー
    assert "| 店舗 |" in md


def test_weekly_sorting_by_top1_avg_diff():
    """top1_avg_diff の降順でソートされること。"""
    md = render_weekly_report(
        week_start="2026-04-27",
        week_end="2026-05-03",
        shop_metrics=_make_metrics(3),
        overall_hit_rate=0.40,
        overall_top1_avg_diff=700.0,
    )
    # 店舗2 (top1=900) が店舗0 (top1=500) より先に出現
    assert md.index("店舗2") < md.index("店舗0")
