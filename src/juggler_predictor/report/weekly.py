"""週次レポートの Markdown 生成。"""
from __future__ import annotations

from datetime import date

import pandas as pd


def render_weekly_report(
    week_start: str,
    week_end: str,
    shop_metrics: pd.DataFrame,
    overall_hit_rate: float,
    overall_top1_avg_diff: float,
) -> str:
    """週次レポート Markdown を生成。

    shop_metrics columns:
      shop_id, display_name, n_days, top1_hit_rate (TOP1 が翌日 setting>=4 だった割合),
      top1_avg_diff (TOP1 推奨台の翌日 diff 平均),
      top3_avg_diff (TOP3 推奨台の翌日 diff 平均),
      high_count_avg (高設定期待台数の平均)
    """
    parts: list[str] = []
    parts.append(f"# 週次レポート {week_start} 〜 {week_end}\n")
    parts.append(f"## 📊 全体サマリー\n")
    parts.append(f"- 集計対象期間: **{week_start} 〜 {week_end}** (7日間)")
    parts.append(f"- 全店舗 TOP1 命中率: **{overall_hit_rate:.1%}** (TOP1 推奨が翌日設定4以上だった割合)")
    parts.append(f"- 全店舗 TOP1 翌日差枚平均: **{overall_top1_avg_diff:+.0f}枚**")
    parts.append("")
    parts.append("## 🏆 店舗別パフォーマンス\n")
    parts.append("| 店舗 | 日数 | TOP1命中率 | TOP1平均 | TOP3平均 | 高設定台/日 |")
    parts.append("|---|---:|---:|---:|---:|---:|")

    for _, r in shop_metrics.sort_values("top1_avg_diff", ascending=False).iterrows():
        parts.append(
            f"| {r['display_name']} | {int(r['n_days'])} | "
            f"{r['top1_hit_rate']:.0%} | "
            f"{r['top1_avg_diff']:+.0f}枚 | "
            f"{r['top3_avg_diff']:+.0f}枚 | "
            f"{r['high_count_avg']:.1f}台 |"
        )
    parts.append("")
    parts.append("## 📝 注意事項\n")
    parts.append("本レポートは過去1週間の推奨成績を集計したものです。")
    parts.append("「TOP1命中率」は当日記事の TOP1 推奨台が、実際に翌日 (=投稿日当日) に")
    parts.append("推定設定4以上であった割合です。設定はあくまで推定値で、")
    parts.append("実際の店長の意図とは異なる可能性があります。")
    return "\n".join(parts) + "\n"
