"""Note 記事 Markdown 生成 (Phase 1.5: 高設定期待度ベース)。"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from juggler_predictor.model.setting_predictor import p_high_to_stars

EXPECTED_SETTING_GO_THRESHOLD = 3.5
GO_RATIO_THRESHOLD = 0.25
GO_MIN_COUNT = 3


def render_article(
    shop_id: str,
    shop_display_name: str,
    target_date: str,
    input_date: str,
    rows: pd.DataFrame,
) -> str:
    """記事 Markdown を生成。

    rows には少なくとも次の列が必要:
      unit_number, machine_name, p_high, p_top, p_setting6, expected_setting,
      prev_diff (前日実績差枚), prev_setting (前日推定設定), score_a
    """
    if rows.empty:
        return _render_empty(shop_display_name, target_date)

    rows = rows.sort_values("score_a", ascending=False).reset_index(drop=True)
    n_total = len(rows)
    n_high = int((rows["expected_setting"] >= EXPECTED_SETTING_GO_THRESHOLD).sum())
    p_high_max = float(rows["p_high"].max())
    star = p_high_to_stars(p_high_max)
    is_go = n_high >= GO_MIN_COUNT and (n_high / n_total) >= GO_RATIO_THRESHOLD

    parts: list[str] = []
    parts.append(_render_header(shop_display_name, target_date, input_date, star, is_go, n_high, n_total))
    parts.append(_render_summary(rows, n_high, n_total, p_high_max))
    parts.append(_render_top10(rows.head(10)))
    parts.append(_render_top1_reason(rows.iloc[0]))
    if not is_go:
        parts.append(_render_no_go(n_high, n_total, p_high_max))
    parts.append(_render_machine_detail(rows))
    parts.append(_render_disclaimer())
    return "\n\n".join(parts) + "\n"


def _render_empty(shop: str, d: str) -> str:
    return f"# {shop} {d} の予測\n\n対象データがありません。\n"


def _render_header(shop: str, d: str, input_d: str, star: int, is_go: bool, n_high: int, n_total: int) -> str:
    star_mark = "★" * star + "☆" * (5 - star)
    go_mark = "🟢 GO" if is_go else "🔴 NO-GO"
    return (
        f"# {shop} {d} 高設定期待度レポート\n\n"
        f"- 対象日: **{d}** (入力: {input_d} までの実績)\n"
        f"- 注目度: **{star_mark}** ({star}/5)\n"
        f"- 判定: **{go_mark}** (高設定期待台 {n_high}/{n_total} 台)"
    )


def _render_summary(rows: pd.DataFrame, n_high: int, n_total: int, p_high_max: float) -> str:
    pct = 100.0 * n_high / n_total if n_total else 0.0
    expected_mean = float(rows["expected_setting"].mean()) if "expected_setting" in rows else 0.0
    return (
        "## 📊 本日のサマリー\n\n"
        f"- 高設定期待台 (期待設定 ≥ {EXPECTED_SETTING_GO_THRESHOLD:.1f}): **{n_high} / {n_total} 台 ({pct:.1f}%)**\n"
        f"- 店内最大 p_high: **{p_high_max:.1%}**\n"
        f"- 平均期待設定: **{expected_mean:.2f}**\n"
        f"- GO/NO-GO 基準: 高設定期待台が {GO_RATIO_THRESHOLD:.0%} 以上かつ {GO_MIN_COUNT} 台以上で GO"
    )


def _render_top10(top: pd.DataFrame) -> str:
    lines = ["## 🏆 推奨台 TOP10 (高設定期待度ランキング)\n"]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, r in top.iterrows():
        m = medals.get(i, f"{i + 1}.")
        prev_diff = int(r.get("prev_diff", 0)) if pd.notna(r.get("prev_diff", 0)) else 0
        prev_set = int(r.get("prev_setting", 3)) if pd.notna(r.get("prev_setting", 3)) else 3
        lines.append(
            f"{m} **{int(r['unit_number'])}番台**({r['machine_name']}) — "
            f"設定4以上: **{r['p_high']:.0%}** / 設定5以上: {r['p_top']:.0%} / "
            f"設定6: {r['p_setting6']:.0%} / 期待設定: {r['expected_setting']:.2f}\n"
            f"   - 前日実績: {prev_diff:+d}枚 (推定設定{prev_set}) / scoreA: {r['score_a']:.3f}"
        )
    return "\n".join(lines)


def _render_top1_reason(top1: pd.Series) -> str:
    prev_diff = int(top1.get("prev_diff", 0)) if pd.notna(top1.get("prev_diff", 0)) else 0
    prev_set = int(top1.get("prev_setting", 3)) if pd.notna(top1.get("prev_setting", 3)) else 3
    return (
        "## 🎯 TOP1 推奨理由\n\n"
        f"**{int(top1['unit_number'])}番台 ({top1['machine_name']})** を最有力として推奨します。\n\n"
        f"- 設定4以上の確率が **{top1['p_high']:.1%}** と店内最高水準\n"
        f"- 期待設定値 **{top1['expected_setting']:.2f}** (1〜6 のスコア)\n"
        f"- 前日 {prev_diff:+d} 枚 / 推定設定{prev_set} の流れ"
    )


def _render_no_go(n_high: int, n_total: int, p_high_max: float) -> str:
    ratio = n_high / n_total if n_total else 0.0
    return (
        "## ⚠️ NO-GO 判定理由\n\n"
        f"- 高設定期待台 (期待設定 ≥ {EXPECTED_SETTING_GO_THRESHOLD:.1f}) が **{n_high} / {n_total} 台 ({ratio:.1%})** で基準 {GO_RATIO_THRESHOLD:.0%} 未満または {GO_MIN_COUNT} 台未満\n"
        f"- 店内最大 p_high が {p_high_max:.1%} に留まる\n"
        "- 本日の来店は見送り、別店舗の検討を推奨します"
    )


def _render_machine_detail(rows: pd.DataFrame) -> str:
    lines = ["## 🎰 機種別詳細\n"]
    for machine, g in rows.groupby("machine_name"):
        g = g.sort_values("p_high", ascending=False)
        n = len(g)
        n_high = int((g["expected_setting"] >= EXPECTED_SETTING_GO_THRESHOLD).sum())
        avg_p_high = float(g["p_high"].mean())
        lines.append(f"### {machine} ({n}台 / 高設定期待 {n_high}台 / 平均p_high {avg_p_high:.1%})\n")
        for _, r in g.head(5).iterrows():
            prev_diff = int(r.get("prev_diff", 0)) if pd.notna(r.get("prev_diff", 0)) else 0
            lines.append(
                f"- {int(r['unit_number'])}番台: p_high {r['p_high']:.0%} / "
                f"期待設定 {r['expected_setting']:.2f} / 前日 {prev_diff:+d}枚"
            )
        lines.append("")
    return "\n".join(lines)


def _render_disclaimer(): 
    return (
        "## 📝 注意事項\n\n"
        "本記事の「設定期待度」は当方の推定モデルによる確率値であり、"
        "実際の設定を保証するものではありません。"
        "設定は各店舗の店長のみが知る情報であり、本予測は過去の差枚・合成確率の傾向に基づく統計的推定です。\n\n"
        "立ち回りの参考としてご活用いただき、最終的な投資判断はご自身でお願いします。"
    )
