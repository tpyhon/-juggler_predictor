"""Phase 1.5: 高設定期待度ベースの記事生成 CLI。

--date は記事投稿日 (D)。内部で D-1 のデータをモデル入力とする。
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

from juggler_predictor.model.score import compute_diff01, compute_score_a
from juggler_predictor.model.setting_predictor import (
    compute_expected_setting,
    compute_p_high,
    compute_p_setting6,
    compute_p_top,
)
from juggler_predictor.report.note_article import render_article

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dataset.parquet"
BUNDLE = ROOT / "models" / "model_bundle.joblib"
SHOPS = ROOT / "config" / "shops.yaml"
REPORTS = ROOT / "reports"


def load_shop_display_name(shop_id: str) -> str:
    data = yaml.safe_load(SHOPS.read_text(encoding="utf-8"))
    shops = data if isinstance(data, list) else data.get("shops", [])
    for s in shops:
        if isinstance(s, dict) and s.get("id") == shop_id:
            return s.get("display_name", shop_id)
    return shop_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", required=True)
    parser.add_argument("--date", required=True, help="記事投稿日 YYYY-MM-DD")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    input_date = target_date - timedelta(days=1)
    input_date_str = input_date.isoformat()
    logger.info("記事投稿日 D=%s, モデル入力日 D-1=%s", args.date, input_date_str)

    df = pd.read_parquet(DATA)
    target = df[(df["shop_id"] == args.shop) & (df["date"] == input_date_str)].copy().reset_index(drop=True)
    logger.info("rows=%d for shop=%s date=%s", len(target), args.shop, input_date_str)
    if target.empty:
        raise SystemExit(f"対象データなし: shop={args.shop} date={input_date_str}")

    bundle = joblib.load(BUNDLE)
    if "setting_classifier" not in bundle:
        raise SystemExit("setting_classifier が bundle にありません。train_setting.py を実行してください。")

    shop_entry = bundle.get("shop_models", {}).get(args.shop)
    if shop_entry:
        clf = shop_entry["setting_classifier"]
        feat_setting = shop_entry["setting_features"]
        logger.info("shop-specific classifier used for %s", args.shop)
    else:
        clf = bundle["setting_classifier"]
        feat_setting = bundle.get("setting_features", bundle["feature_cols"])
        logger.info("global classifier used for %s (no shop model)", args.shop)

    # 不足列があれば 0 埋め
    for c in feat_setting:
        if c not in target.columns:
            target[c] = 0.0
    X = target[feat_setting].astype(float).values
    proba = clf.predict_proba(X)
    target["p_high"] = compute_p_high(proba)
    target["p_top"] = compute_p_top(proba)
    target["p_setting6"] = compute_p_setting6(proba)
    target["expected_setting"] = compute_expected_setting(proba)

    # 前日実績 (= 入力日の diff)
    target["prev_diff"] = target["diff"].astype(float)
    diff01_prev = compute_diff01(target["prev_diff"]).values
    target["score_a"] = compute_score_a(target["p_high"], target["p_top"], diff01_prev).values

    # prev_setting は dataset 由来 (なければ setting で代替)
    if "prev_setting" not in target.columns and "setting" in target.columns:
        target["prev_setting"] = target["setting"]

    shop_display = load_shop_display_name(args.shop)
    md = render_article(
        shop_id=args.shop,
        shop_display_name=shop_display,
        target_date=args.date,
        input_date=input_date_str,
        rows=target,
    )

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{args.shop}_{args.date}.md"
    out.write_text(md, encoding="utf-8")
    n_high = int((target["p_high"] >= 0.50).sum())
    p_high_max = float(target["p_high"].max())

    print("[ARTICLE GENERATED]")
    print(f"  path        : {out}")
    print(f"  shop        : {shop_display} ({args.shop})")
    print(f"  target_date : {args.date}")
    print(f"  input_date  : {input_date_str}")
    print(f"  rows        : {len(target)}")
    print(f"  p_high_max  : {p_high_max:.4f}")
    print(f"  high_count  : {n_high} / {len(target)}")
    print(f"  size_bytes  : {out.stat().st_size}")


if __name__ == "__main__":
    main()
