"""週次レポート生成: 直近7日のパフォーマンス集計 → R2 + Note。

GitHub Actions の weekly.yml から呼ばれる前提。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import joblib
import pandas as pd
import yaml

from juggler_predictor.model.score import compute_diff01, compute_score_a
from juggler_predictor.model.setting_predictor import (
    compute_expected_setting,
    compute_p_high,
    compute_p_top,
)
from juggler_predictor.note import NoteClient, markdown_to_note_html
from juggler_predictor.notify.slack import notify_slack
from juggler_predictor.report.weekly import render_weekly_report
from juggler_predictor.storage.article import upload_article

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dataset.parquet"
BUNDLE = ROOT / "models" / "model_bundle.joblib"
SHOPS = ROOT / "config" / "shops.yaml"
REPORTS = ROOT / "reports"


def load_shops() -> list[dict]:
    data = yaml.safe_load(SHOPS.read_text(encoding="utf-8"))
    shops = data if isinstance(data, list) else data.get("shops", [])
    return [s for s in shops if isinstance(s, dict)]


def evaluate_shop_week(
    df: pd.DataFrame,
    clf,
    feat: list[str],
    shop_id: str,
    week_dates: list[str],
) -> dict:
    """店舗 × 週次の集計を計算。

    各日 D について:
      - input_date = D-1 のデータで p_high, p_top を計算
      - TOP1, TOP3 の翌日 (=D) の真の setting (>=4) 命中率
      - TOP1, TOP3 の翌日 (=D) diff 平均
    """
    metrics = {
        "shop_id": shop_id,
        "n_days": 0,
        "top1_hits": 0,
        "top1_diffs": [],
        "top3_diffs": [],
        "high_counts": [],
    }
    for d_str in week_dates:
        d = date.fromisoformat(d_str)
        input_date = (d - timedelta(days=1)).isoformat()
        input_rows = df[(df["shop_id"] == shop_id) & (df["date"] == input_date)].copy().reset_index(drop=True)
        actual_rows = df[(df["shop_id"] == shop_id) & (df["date"] == d_str)].copy()
        if input_rows.empty or actual_rows.empty:
            continue

        for c in feat:
            if c not in input_rows.columns:
                input_rows[c] = 0.0
        X = input_rows[feat].astype(float).values
        proba = clf.predict_proba(X)
        input_rows["p_high"] = compute_p_high(proba)
        input_rows["p_top"] = compute_p_top(proba)
        input_rows["expected_setting"] = compute_expected_setting(proba)
        input_rows["prev_diff"] = input_rows["diff"].astype(float)
        diff01_prev = compute_diff01(input_rows["prev_diff"]).values
        input_rows["score_a"] = compute_score_a(
            input_rows["p_high"], input_rows["p_top"], diff01_prev
        ).values

        ranked = input_rows.sort_values("score_a", ascending=False).reset_index(drop=True)
        top1_unit = ranked.iloc[0]["unit_number"]
        top3_units = ranked.head(3)["unit_number"].tolist()

        actual_lookup = actual_rows.set_index("unit_number")
        if top1_unit in actual_lookup.index:
            top1_actual = actual_lookup.loc[top1_unit]
            top1_setting = int(top1_actual.get("setting", 0))
            metrics["top1_hits"] += int(top1_setting >= 4)
            metrics["top1_diffs"].append(float(top1_actual.get("diff", 0)))
            for u in top3_units:
                if u in actual_lookup.index:
                    metrics["top3_diffs"].append(float(actual_lookup.loc[u, "diff"]))
            metrics["n_days"] += 1
            metrics["high_counts"].append(int((input_rows["p_high"] >= 0.50).sum()))

    n = max(metrics["n_days"], 1)
    return {
        "shop_id": metrics["shop_id"],
        "n_days": metrics["n_days"],
        "top1_hit_rate": metrics["top1_hits"] / n,
        "top1_avg_diff": sum(metrics["top1_diffs"]) / max(len(metrics["top1_diffs"]), 1),
        "top3_avg_diff": sum(metrics["top3_diffs"]) / max(len(metrics["top3_diffs"]), 1),
        "high_count_avg": sum(metrics["high_counts"]) / max(len(metrics["high_counts"]), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week-end", help="週末日 YYYY-MM-DD (デフォルト: 昨日)")
    ap.add_argument("--no-post", action="store_true", help="Note 投稿しない")
    ap.add_argument("--price", type=int, default=300)
    args = ap.parse_args()

    week_end = date.fromisoformat(args.week_end) if args.week_end else (date.today() - timedelta(days=1))
    week_start = week_end - timedelta(days=6)
    week_dates = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
    logger.info("週次レポート期間: %s 〜 %s", week_start, week_end)

    df = pd.read_parquet(DATA)
    bundle = joblib.load(BUNDLE)
    if "setting_classifier" not in bundle:
        logger.error("setting_classifier が bundle にありません")
        return 1
    clf = bundle["setting_classifier"]
    feat = bundle.get("setting_features", bundle["feature_cols"])

    shops = load_shops()
    rows: list[dict] = []
    for s in shops:
        m = evaluate_shop_week(df, clf, feat, s["id"], week_dates)
        m["display_name"] = s.get("display_name", s["id"])
        rows.append(m)
        logger.info(
            "  %s: n=%d hit=%.0f%% top1_avg=%+.0f",
            s["id"], m["n_days"], m["top1_hit_rate"] * 100, m["top1_avg_diff"],
        )

    metrics_df = pd.DataFrame(rows)
    valid = metrics_df[metrics_df["n_days"] > 0]
    overall_hit_rate = float(valid["top1_hit_rate"].mean()) if not valid.empty else 0.0
    overall_top1_avg = float(valid["top1_avg_diff"].mean()) if not valid.empty else 0.0

    md = render_weekly_report(
        week_start.isoformat(),
        week_end.isoformat(),
        metrics_df,
        overall_hit_rate,
        overall_top1_avg,
    )

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / f"weekly_{week_end.isoformat()}.md"
    out_path.write_text(md, encoding="utf-8")
    logger.info("週次レポート保存: %s (%d bytes)", out_path, out_path.stat().st_size)

    # R2 アップロード
    try:
        upload_article("_weekly", week_end.isoformat(), md)
    except Exception as e:
        logger.warning("R2 アップロード失敗: %s", e)

    # Note 投稿
    if not args.no_post:
        try:
            client = NoteClient()
            client.login()
            title = f"週次レポート {week_start.isoformat()} 〜 {week_end.isoformat()}"
            url = client.post(title=title, body_html=markdown_to_note_html(md), price=args.price)
            logger.info("週次レポート投稿: %s", url)
            notify_slack(f"*週次レポート投稿完了* {week_start} 〜 {week_end}\n命中率 {overall_hit_rate:.0%} / 平均 {overall_top1_avg:+.0f}枚\n{url}")
        except Exception as e:
            logger.error("Note 投稿失敗: %s", e)
            notify_slack(f"*週次レポート投稿失敗* {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
