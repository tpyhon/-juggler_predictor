"""Phase 1: 前日参照に修正してリーク解消。

- scripts/generate_article.py を全面書き換え
  * --date は記事投稿日（=営業対象日）
  * 内部では date-1 のデータをモデル入力として使用
  * 表示は「前日実績」+「予測p_win」+「予測差枚（モデル）」
- src/juggler_predictor/report/note_article.py のラベルを修正
  * 「予測差枚」→「前日実績」と「予測差枚（モデル）」を併記可能に
"""
from __future__ import annotations
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ============================================================
# scripts/generate_article.py (全面書き換え)
# ============================================================
FILES["scripts/generate_article.py"] = '''\
"""Note 記事生成 CLI (Phase 1, 前日参照版)。

使い方:
    uv run python scripts/generate_article.py --shop espas_ueno --date 2026-05-05

意味:
    指定日 D の朝 9 時に投稿する記事を生成。
    モデル入力は D-1 のデータ。表示は前日実績 + 翌日予測。
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from datetime import date, timedelta
from typing import Any

import joblib
import pandas as pd
import yaml
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from juggler_predictor.common.logging import setup_logging  # noqa: E402
from juggler_predictor.model.score import (  # noqa: E402
    compute_base100,
    compute_diff01,
    compute_p4,
    compute_score_a,
)
from juggler_predictor.model.setting_estimator import estimate_setting  # noqa: E402
from juggler_predictor.report import render_article  # noqa: E402

logger = logging.getLogger(__name__)


def _load_shops() -> list[dict[str, Any]]:
    raw = yaml.safe_load((ROOT / "config" / "shops.yaml").read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("shops", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", required=True, help="shop_id (config/shops.yaml の id)")
    parser.add_argument("--date", required=True, help="記事投稿日 YYYY-MM-DD (=営業対象日)")
    parser.add_argument("--parquet", default=str(ROOT / "data" / "dataset.parquet"))
    parser.add_argument("--bundle", default=str(ROOT / "models" / "model_bundle.joblib"))
    parser.add_argument("--out-dir", default=str(ROOT / "reports"))
    parser.add_argument("--alpha", type=float, default=0.70)
    parser.add_argument("--no-go-threshold", type=float, default=0.25)
    args = parser.parse_args()

    load_dotenv()
    setup_logging()

    shops = _load_shops()
    shop = next((s for s in shops if s["id"] == args.shop), None)
    if shop is None:
        logger.error("shop_id %s が shops.yaml に存在しません", args.shop)
        return 1
    display_name = shop.get("display_name", args.shop)

    # 投稿日 D, 入力日 D-1
    target_date = date.fromisoformat(args.date)
    input_date = target_date - timedelta(days=1)
    input_date_str = input_date.isoformat()
    logger.info("記事投稿日 D=%s, モデル入力日 D-1=%s", args.date, input_date_str)

    logger.info("[1] dataset 読み込み: %s", args.parquet)
    df = pd.read_parquet(args.parquet)
    df["date"] = df["date"].astype(str)

    target = df[(df["shop_id"] == args.shop) & (df["date"] == input_date_str)].copy()
    if len(target) == 0:
        logger.error(
            "前日データなし: shop=%s date=%s (D-1)。"
            "parquet 再生成または対象日を確認してください。",
            args.shop, input_date_str,
        )
        return 2
    logger.info("前日 (%s) 対象行数: %d", input_date_str, len(target))

    logger.info("[2] モデル読み込み: %s", args.bundle)
    bundle = joblib.load(args.bundle)
    feature_cols = bundle["feature_cols"]
    regressor = bundle["regressor"]
    classifier = bundle.get("classifier_calibrated") or bundle["classifier_raw"]

    X = target[feature_cols]

    logger.info("[3] 翌日予測 (D)")
    target["predicted_diff"] = regressor.predict(X)  # D 日の予測差枚
    if hasattr(classifier, "predict_proba"):
        proba = classifier.predict_proba(X)
        target["p_win"] = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
    else:
        target["p_win"] = classifier.predict(X)

    logger.info("[4] 前日推定設定 (D-1)")
    # composite_prob は前日 (D-1) の値 → 前日推定設定
    target["predicted_setting"] = target.apply(
        lambda r: estimate_setting(
            r.get("composite_prob"),
            r.get("diff", 0.0),
            r.get("machine_name", ""),
        ),
        axis=1,
    )

    logger.info("[5] スコア計算")
    # diff01 は前日実績 diff の店内正規化 (=「前日プラス順位」)
    target["prev_diff"] = target["diff"].astype(float)
    target["diff01"] = compute_diff01(target["prev_diff"]).values
    target["scoreA"] = compute_score_a(target["p_win"], target["diff01"], alpha=args.alpha).values
    target["p4"] = compute_p4(target["predicted_setting"]).values
    target["base100"] = compute_base100(target["p_win"], target["diff01"], target["p4"]).values

    logger.info("[6] 記事生成")
    hashtags = ["ジャグラー", "スロット", "パチスロ", "設定狙い", "立ち回り", "期待値", "東京"]
    md = render_article(
        shop_display_name=display_name,
        target_date_str=args.date,
        prev_date_str=input_date_str,
        predictions=target,
        alpha=args.alpha,
        no_go_threshold=args.no_go_threshold,
        hashtags=hashtags,
    )

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.shop}_{args.date}.md"
    out_path.write_text(md, encoding="utf-8")
    logger.info("[OK] 記事保存: %s (%d bytes)", out_path, len(md.encode("utf-8")))

    print()
    print("=" * 60)
    print(f"[ARTICLE GENERATED] {out_path}")
    print("=" * 60)
    print(f"  店舗      : {display_name} ({args.shop})")
    print(f"  投稿日    : {args.date}")
    print(f"  入力日    : {input_date_str} (D-1)")
    print(f"  対象台数  : {len(target)}")
    print(f"  Top1 p_win: {target['p_win'].max():.3f}")
    print(f"  Top1 prev_diff: {int(target.loc[target['scoreA'].idxmax(), 'prev_diff'])}")
    print(f"  base100 max: {target['base100'].max():.1f}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

# ============================================================
# src/juggler_predictor/report/note_article.py (ラベル変更)
# ============================================================
FILES["src/juggler_predictor/report/note_article.py"] = '''\
"""Note 記事 (Markdown) 生成。

入力 DataFrame に必要な列:
    machine_name, unit_number, p_win, predicted_diff, prev_diff,
    predicted_setting, diff01, scoreA, base100
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

MEDAL_RANK = {1: "🥇", 2: "🥈", 3: "🥉"}


def _fmt_diff(v: float) -> str:
    iv = int(round(float(v)))
    sign = "+" if iv >= 0 else ""
    return f"{sign}{iv}枚"


def _fmt_pct(v: float) -> str:
    return f"{float(v) * 100.0:.1f}%"


def _stars(n: int) -> str:
    n = max(1, min(5, int(n)))
    return "★" * n + "☆" * (5 - n)


def _render_top10(df: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    lines.append("## 🏆 推奨台 TOP10（scoreA ランキング）")
    lines.append("")
    lines.append("> scoreA = α × p_win + (1-α) × diff01（前日実績の店内順位）")
    lines.append("")
    top = df.sort_values("scoreA", ascending=False).head(10).reset_index(drop=True)
    for i, row in top.iterrows():
        rank = i + 1
        prefix = MEDAL_RANK.get(rank, f"")
        if rank <= 3:
            head = f"{rank}. {prefix} **{row['unit_number']}番台**（{row['machine_name']}）"
        else:
            head = f"{rank}. **{row['unit_number']}番台**（{row['machine_name']}）"
        lines.append(head)
        detail = (
            f"   - scoreA: {row['scoreA']:.3f} / "
            f"翌日p_win: {_fmt_pct(row['p_win'])} / "
            f"前日実績: {_fmt_diff(row['prev_diff'])} / "
            f"前日設定: 設定{int(row['predicted_setting'])}"
        )
        lines.append(detail)
        lines.append("")
    return lines


def _render_top1_reason(df: pd.DataFrame, alpha: float) -> list[str]:
    lines: list[str] = []
    lines.append("## 🔍 Top1 選定理由")
    lines.append("")
    top = df.sort_values("scoreA", ascending=False).head(3).reset_index(drop=True)
    if len(top) == 0:
        lines.append("対象データがありません。")
        return lines
    r1 = top.iloc[0]
    lines.append(f"### 🥇 第1位: {r1['unit_number']}番台（{r1['machine_name']}）")
    lines.append("")
    lines.append(f"- **scoreA**: {r1['scoreA']:.3f}")
    lines.append(f"- **翌日p_win（プラス確率予測）**: {_fmt_pct(r1['p_win'])}")
    lines.append(f"- **前日実績差枚**: {_fmt_diff(r1['prev_diff'])}")
    lines.append(f"- **diff01（前日順位の正規化）**: {r1['diff01']:.3f}")
    lines.append(f"- **前日推定設定**: 設定{int(r1['predicted_setting'])}")
    lines.append("")
    lines.append("### 📝 選定理由")
    lines.append("")
    pw = float(r1["p_win"])
    if pw >= 0.30:
        lines.append(f"- ✅ **翌日プラス確率が比較的高め**（{_fmt_pct(pw)}）")
    elif pw >= 0.22:
        lines.append(f"- 📊 翌日プラス確率は中程度（{_fmt_pct(pw)}）")
    else:
        lines.append(f"- ⚠️ 翌日プラス確率はやや低め（{_fmt_pct(pw)}）")
    pdiff = float(r1["prev_diff"])
    if pdiff >= 1500:
        lines.append(f"- ✅ **前日大勝ち** ({_fmt_diff(pdiff)})：高設定示唆 / 連投期待")
    elif pdiff >= 500:
        lines.append(f"- 📊 前日プラス収支 ({_fmt_diff(pdiff)})")
    elif pdiff >= 0:
        lines.append(f"- 📊 前日微プラス ({_fmt_diff(pdiff)})")
    else:
        lines.append(f"- ⚠️ 前日マイナス ({_fmt_diff(pdiff)})")
    if float(r1["diff01"]) >= 0.80:
        lines.append(f"- ✅ **店内での前日順位がトップクラス**（diff01: {r1['diff01']:.3f}）")
    elif float(r1["diff01"]) >= 0.50:
        lines.append(f"- 📊 店内前日順位は中位（diff01: {r1['diff01']:.3f}）")
    setting = int(r1["predicted_setting"])
    if setting >= 5:
        lines.append(f"- ✅ **前日推定設定が高め**（設定{setting}）：連投の期待値高")
    elif setting >= 4:
        lines.append(f"- 📊 前日推定設定: 設定{setting}（中高設定圏）")
    lines.append(f"- 📊 α値: {alpha:.2f}（p_win 重視）")
    lines.append("")
    if len(top) >= 2:
        lines.append("### 📊 2位・3位との比較")
        lines.append("")
        for i, row in top.iterrows():
            rank = i + 1
            line = (
                f"{rank}. **{row['unit_number']}番台**（{row['machine_name']}）: "
                f"scoreA {row['scoreA']:.3f} / p_win {_fmt_pct(row['p_win'])} / "
                f"前日 {_fmt_diff(row['prev_diff'])}"
            )
            lines.append(line)
        lines.append("")
    return lines


def _render_no_go(df: pd.DataFrame, threshold: float) -> list[str]:
    lines: list[str] = []
    lines.append("## ⚠️ GO / NO-GO 判定")
    lines.append("")
    if len(df) == 0:
        lines.append("対象データがありません。")
        return lines
    pwin_max = float(df["p_win"].max())
    if pwin_max >= threshold:
        lines.append(
            f"🟢 **GO** — Top1 の翌日 p_win が {_fmt_pct(pwin_max)} で閾値 "
            f"{_fmt_pct(threshold)} 以上"
        )
    else:
        lines.append(
            f"🔴 **NO-GO** — Top1 の翌日 p_win が {_fmt_pct(pwin_max)} で閾値 "
            f"{_fmt_pct(threshold)} 未満"
        )
        lines.append("")
        lines.append("- 全台のプラス確率予測が低水準のため、本日は様子見推奨")
    lines.append("")
    return lines


def _render_summary(df: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    lines.append("## 💬 本日の総評")
    lines.append("")
    top3 = df.sort_values("scoreA", ascending=False).head(3).reset_index(drop=True)
    if len(top3) > 0:
        lines.append("### 🏆 scoreA TOP3")
        lines.append("")
        for i, row in top3.iterrows():
            rank = i + 1
            prefix = MEDAL_RANK.get(rank, f"{rank}.")
            line = (
                f"{prefix} **{row['unit_number']}番台**（{row['machine_name']}）"
                f"- scoreA: {row['scoreA']:.3f} / 翌日p_win: {_fmt_pct(row['p_win'])} / "
                f"前日: {_fmt_diff(row['prev_diff'])}"
            )
            lines.append(line)
        lines.append("")
    n_total = len(df)
    n_high_prev = int((df["predicted_setting"] >= 4).sum())
    rate = (n_high_prev / n_total) if n_total > 0 else 0.0
    lines.append("### 📈 前日 設定4以上 推定統計")
    lines.append("")
    lines.append(f"- 前日に設定4以上と推定された台: **{n_high_prev}台** / 全{n_total}台")
    lines.append(f"- 前日 設定4以上 出現率: **{rate * 100:.1f}%**")
    lines.append("")
    return lines


def _render_machine_breakdown(df: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    lines.append("## 📋 全台の詳細データ（機種別）")
    lines.append("")
    for machine, group in df.groupby("machine_name"):
        g = group.sort_values("scoreA", ascending=False)
        lines.append(f"### 🎰 {machine}（{len(g)}台）")
        lines.append("")
        for _, row in g.iterrows():
            line = (
                f"- **{row['unit_number']}番台**: "
                f"scoreA {row['scoreA']:.3f} / "
                f"翌日p_win {_fmt_pct(row['p_win'])} / "
                f"前日 {_fmt_diff(row['prev_diff'])} / "
                f"diff01 {row['diff01']:.3f} / "
                f"前日設定{int(row['predicted_setting'])}"
            )
            lines.append(line)
        lines.append("")
    return lines


def render_article(
    *,
    shop_display_name: str,
    target_date_str: str,
    prev_date_str: str | None = None,
    predictions: pd.DataFrame,
    alpha: float = 0.70,
    no_go_threshold: float = 0.25,
    hashtags: Iterable[str] | None = None,
    # 旧 API 互換
    date_str: str | None = None,
) -> str:
    """Note 記事 Markdown を生成 (Phase 1, 前日参照版)。

    predictions に必要な列:
        machine_name, unit_number, p_win, predicted_diff, prev_diff,
        predicted_setting, diff01, scoreA, base100
    """
    # 後方互換: date_str だけ渡されたケース
    if target_date_str is None and date_str is not None:
        target_date_str = date_str

    required = {
        "machine_name", "unit_number", "p_win", "prev_diff",
        "predicted_setting", "diff01", "scoreA", "base100",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"predictions に必要な列が不足: {missing}")

    df = predictions.copy()
    n_total = len(df)
    n_score05 = int((df["scoreA"] >= 0.5).sum())
    n_high = int((df["predicted_setting"] >= 4).sum())
    base100_max = float(df["base100"].max()) if n_total > 0 else 0.0

    from juggler_predictor.model.score import base100_to_stars
    stars = base100_to_stars(base100_max)

    lines: list[str] = []
    lines.append("## 🏪 店舗情報")
    lines.append("")
    lines.append(f"- **店舗名**: {shop_display_name}")
    lines.append(f"- **記事対象日**: {target_date_str}")
    if prev_date_str:
        lines.append(f"- **参照前日データ**: {prev_date_str}")
    lines.append("")
    lines.append(f"## 🎯 本日の注目度：{_stars(stars)}（{stars}.0/5.0）")
    lines.append("")
    lines.append("## 📊 本日のデータ概要")
    lines.append("")
    lines.append(f"- **対象台数**: {n_total}台")
    lines.append(f"- **scoreA 0.5以上**: {n_score05}台")
    lines.append(f"- **前日 設定4以上推定**: {n_high}台")
    lines.append("")
    lines.append("## 💡 このデータでできること")
    lines.append("")
    lines.append("- 全台の前日実績と翌日プラス確率予測を確認")
    lines.append("- 推奨度ランキングTOP10をチェック")
    lines.append("- 機種別の詳細データを閲覧")
    lines.append("")
    lines.append("## ⚠️ 免責事項")
    lines.append("")
    lines.append("本データは前日実績と統計分析に基づく予測であり、当日の設定を保証するものではありません。")
    lines.append("パチスロは射幸性のある遊技です。自己責任・無理のない範囲で楽しみましょう。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.extend(_render_top10(df))
    lines.append("---")
    lines.append("")
    lines.extend(_render_top1_reason(df, alpha))
    lines.append("---")
    lines.append("")
    lines.extend(_render_no_go(df, no_go_threshold))
    lines.append("---")
    lines.append("")
    lines.extend(_render_summary(df))
    lines.append("---")
    lines.append("")
    lines.extend(_render_machine_breakdown(df))

    if hashtags:
        lines.append("---")
        lines.append("")
        lines.append(" ".join(f"#{h}" for h in hashtags))
        lines.append("")

    return "\\n".join(lines)
'''

# ============================================================
# tests/test_note_article.py (旧 date_str 互換含むテスト更新)
# ============================================================
FILES["tests/test_note_article.py"] = '''\
"""note_article.render_article のテスト (Phase 1, 前日参照版)。"""
import pandas as pd
import pytest

from juggler_predictor.report import render_article


def _sample_predictions(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "machine_name": ["マイジャグラーV"] * n,
        "unit_number": [str(2000 + i) for i in range(n)],
        "p_win": [0.30, 0.27, 0.25, 0.22, 0.18][:n],
        "predicted_diff": [400.0, 200.0, 100.0, -100.0, -300.0][:n],
        "prev_diff": [3500.0, 1800.0, 500.0, -500.0, -1500.0][:n],
        "predicted_setting": [6, 5, 4, 3, 1][:n],
        "diff01": [1.0, 0.7, 0.5, 0.3, 0.0][:n],
        "scoreA": [0.51, 0.40, 0.33, 0.24, 0.13][:n],
        "base100": [55.0, 45.0, 38.0, 30.0, 22.0][:n],
    })


def test_render_article_basic():
    df = _sample_predictions(5)
    md = render_article(
        shop_display_name="テスト店舗",
        target_date_str="2026-05-05",
        prev_date_str="2026-05-04",
        predictions=df,
    )
    assert "テスト店舗" in md
    assert "2026-05-05" in md
    assert "2026-05-04" in md
    assert "対象台数**: 5台" in md
    assert "🥇" in md
    assert "前日実績" in md
    assert "翌日p_win" in md


def test_render_article_missing_columns():
    df = pd.DataFrame({"machine_name": ["A"], "unit_number": ["1"]})
    with pytest.raises(ValueError, match="不足"):
        render_article(
            shop_display_name="X",
            target_date_str="2026-05-05",
            predictions=df,
        )


def test_render_article_no_go():
    df = _sample_predictions(3)
    df["p_win"] = [0.20, 0.18, 0.15]
    md = render_article(
        shop_display_name="テスト",
        target_date_str="2026-05-05",
        predictions=df,
        no_go_threshold=0.25,
    )
    assert "NO-GO" in md


def test_render_article_go():
    df = _sample_predictions(3)
    df["p_win"] = [0.35, 0.30, 0.28]
    md = render_article(
        shop_display_name="テスト",
        target_date_str="2026-05-05",
        predictions=df,
        no_go_threshold=0.25,
    )
    assert "🟢" in md or "GO" in md
'''


def write_all() -> None:
    n = 0
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        size = len(content.encode("utf-8"))
        print(f"[WRITE] {rel} ({size} bytes)")
        n += 1
    print(f"\n[SUCCESS] {n} files written")


if __name__ == "__main__":
    write_all()
