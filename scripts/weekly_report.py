"""週次レポート生成・Note 無料公開スクリプト.

毎週月曜に直近7日間（先週月曜〜日曜）のデータから、
全17店舗を横断した高設定期待店舗 TOP10 ランキングを生成し、
note.com に無料公開する（集客目的）。

Usage:
    # 生成のみ（投稿しない）
    uv run python scripts/weekly_report.py --dry-run

    # 生成＋下書き保存（公開しない）
    uv run python scripts/weekly_report.py --draft-only

    # 生成＋無料公開（本番）
    uv run python scripts/weekly_report.py

    # 既存 markdown を投稿のみ
    uv run python scripts/weekly_report.py --post-only --date 2026-05-04

    # 特定日付を週末として指定
    uv run python scripts/weekly_report.py --date 2026-05-04
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

load_dotenv()

# ローカル import は load_dotenv 後
from juggler_predictor.storage.r2 import build_r2_client_from_env  # noqa: E402
from juggler_predictor.model.setting_predictor import (  # noqa: E402
    compute_p_high,
    compute_p_setting6,
    compute_p_top,
)
from juggler_predictor.model.score import compute_diff01, compute_score_a  # noqa: E402
from juggler_predictor.model.setting_predictor import compute_expected_setting  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
MODELS_DIR = PROJECT_ROOT / "models"

DEFAULT_HASHTAGS = [
    "ジャグラー",
    "スロット",
    "パチスロ",
    "高設定",
    "立ち回り",
]


# ---------------------------------------------------------------------------
# 期間計算
# ---------------------------------------------------------------------------
def resolve_week_range(target: date | None) -> tuple[date, date]:
    """週次レポート対象期間（月曜〜日曜）を決定する.

    target が None の場合は「直近の日曜」を end とする。
    target が指定された場合は、その日を含む週の月曜〜日曜を返す。
    """
    if target is None:
        today = date.today()
        # 月曜=0 ... 日曜=6
        # 直近の日曜を取得
        days_since_sunday = (today.weekday() + 1) % 7
        end = today - timedelta(days=days_since_sunday if days_since_sunday > 0 else 7)
    else:
        # target を含む週の日曜を end にする
        days_to_sunday = 6 - target.weekday() if target.weekday() != 6 else 0
        end = target + timedelta(days=days_to_sunday)
        if end > date.today():
            end = target  # 未来日にならないよう抑制
    start = end - timedelta(days=6)
    return start, end


# ---------------------------------------------------------------------------
# データ読み込み・集計
# ---------------------------------------------------------------------------
def load_shops_config() -> dict:
    path = CONFIG_DIR / "shops.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_dataset() -> pd.DataFrame:
    parquet_path = DATA_DIR / "dataset.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"dataset.parquet が見つかりません: {parquet_path}\n"
            "先に `uv run python scripts/build_dataset.py` を実行してください。"
        )
    df = pd.read_parquet(parquet_path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_model_bundle():
    import joblib

    bundle_path = MODELS_DIR / "model_bundle.joblib"
    if not bundle_path.exists():
        raise FileNotFoundError(
            f"model_bundle.joblib が見つかりません: {bundle_path}"
        )
    return joblib.load(bundle_path)


def aggregate_weekly_ranking(
    df: pd.DataFrame,
    start: date,
    end: date,
    shops_config: dict,
    top_n: int = 10,
) -> pd.DataFrame:
    """店舗ごとの週間集計を行い、p_high の平均でランキングを作成."""
    mask = (df["date"] >= start) & (df["date"] <= end)
    week_df = df.loc[mask].copy()

    if week_df.empty:
        raise ValueError(f"期間 {start}〜{end} のデータが空です")

    # p_high が無い場合はモデル推論する想定だが、build_dataset 後に推論済みカラムが
    # ある前提（generate_article.py と同じ流れ）
    if "p_high" not in week_df.columns:
        bundle = load_model_bundle()
        if "setting_classifier" not in bundle:
            raise RuntimeError(
                "setting_classifier が bundle にありません。"
                "train_setting.py を実行してください。"
            )
        clf = bundle["setting_classifier"]
        feat_setting = bundle.get("setting_features", bundle["feature_cols"])

        # 不足列があれば 0 埋め
        for col in feat_setting:
            if col not in week_df.columns:
                week_df[col] = 0.0
        X = week_df[feat_setting].astype(float).fillna(0.0)
        proba = clf.predict_proba(X)
        week_df["p_high"] = compute_p_high(proba)


    # 店舗別集計
    # shops.yaml がトップレベル list か {"shops": [...]} かを吸収
    shops_list = shops_config["shops"] if isinstance(shops_config, dict) and "shops" in shops_config else shops_config
    shop_names = {s["id"]: s.get("display_name", s["id"]) for s in shops_list}

    agg = (
        week_df.groupby("shop_id")
        .agg(
            p_high_mean=("p_high", "mean"),
            p_high_max=("p_high", "max"),
            n_machines=("p_high", "count"),
            avg_diff=("diff", "mean") if "diff" in week_df.columns else ("p_high", "mean"),
        )
        .reset_index()
    )
    agg["display_name"] = agg["shop_id"].map(shop_names).fillna(agg["shop_id"])
    agg = agg.sort_values("p_high_mean", ascending=False).head(top_n).reset_index(drop=True)
    agg.index = agg.index + 1  # ランキング順位
    return agg

def aggregate_weekly_actuals(
    df: pd.DataFrame,
    start: date,
    end: date,
    shops_config: dict,
) -> dict:
    """各日・各店舗の予測 TOP1（score_a 最大）の実績差枚を集計する."""
    bundle = load_model_bundle()
    if "setting_classifier" not in bundle:
        raise RuntimeError("setting_classifier が bundle にありません")
    clf = bundle["setting_classifier"]
    feat_setting = bundle.get("setting_features", bundle["feature_cols"])

    shops_list = (
        shops_config["shops"]
        if isinstance(shops_config, dict) and "shops" in shops_config
        else shops_config
    )
    shop_names = {s["id"]: s.get("name", s.get("display_name", s["id"])) for s in shops_list}

    records: list[dict] = []
    current = start
    while current <= end:
        day_df = df[df["date"] == current].copy()
        if day_df.empty:
            current += timedelta(days=1)
            continue

        # 不足列を 0 埋め
        for col in feat_setting:
            if col not in day_df.columns:
                day_df[col] = 0.0
        X = day_df[feat_setting].astype(float).fillna(0.0)
        proba = clf.predict_proba(X)
        day_df["p_high"] = compute_p_high(proba)
        day_df["p_top"] = compute_p_top(proba)
        # diff01_prev: 前日 diff の正規化（generate_article.py と同じ）
        # ここでは簡易的に unit_diff_mean_7d ベースで近似
        if "unit_diff_mean_7d" in day_df.columns:
            diff01_prev = compute_diff01(day_df["unit_diff_mean_7d"].fillna(0.0))
        else:
            diff01_prev = pd.Series(0.5, index=day_df.index)
        day_df["score_a"] = compute_score_a(
            day_df["p_high"], day_df["p_top"], diff01_prev
        ).values

        # 店舗ごとに score_a TOP1 を抽出
        for shop_id, shop_df in day_df.groupby("shop_id"):
            top1 = shop_df.sort_values("score_a", ascending=False).head(1).iloc[0]
            records.append(
                {
                    "date": current,
                    "shop_id": shop_id,
                    "shop_name": shop_names.get(shop_id, shop_id),
                    "machine_name": top1["machine_name"],
                    "score_a": float(top1["score_a"]),
                    "p_high": float(top1["p_high"]),
                    "diff": int(top1["diff"]) if pd.notna(top1["diff"]) else 0,
                }
            )
        current += timedelta(days=1)

    if not records:
        return {"records": [], "summary": {}}

    rec_df = pd.DataFrame(records)
    n_total = len(rec_df)
    n_win = int((rec_df["diff"] > 0).sum())
    n_lose = int((rec_df["diff"] < 0).sum())
    win_rate = n_win / n_total if n_total > 0 else 0.0
    avg_diff = float(rec_df["diff"].mean())
    sum_diff = int(rec_df["diff"].sum())
    median_diff = float(rec_df["diff"].median())

    # ベスト3 / ワースト3
    best3 = rec_df.sort_values("diff", ascending=False).head(3)
    worst3 = rec_df.sort_values("diff", ascending=True).head(3)

    return {
        "records": records,
        "summary": {
            "n_total": n_total,
            "n_win": n_win,
            "n_lose": n_lose,
            "win_rate": win_rate,
            "avg_diff": avg_diff,
            "sum_diff": sum_diff,
            "median_diff": median_diff,
        },
        "best3": best3.to_dict(orient="records"),
        "worst3": worst3.to_dict(orient="records"),
    }

# ---------------------------------------------------------------------------
# Markdown 生成
# ---------------------------------------------------------------------------
def build_title(start: date, end: date) -> str:
    return f"【週間】ジャグラー高設定期待店舗ランキング {start:%Y/%m/%d}〜{end:%Y/%m/%d}"


def build_markdown(
    start: date,
    end: date,
    ranking: pd.DataFrame,
    actuals: dict | None = None,
) -> str:
    title = build_title(start, end)
    lines = [
        f"# {title}",
        "",
        f"**集計期間**: {start:%Y年%m月%d日}（月）〜 {end:%Y年%m月%d日}（日）",
        "",
        "## 概要",
        "",
        "本記事は、機械学習モデルが算出した**高設定期待度（p_high）**の週間平均で、"
        "東京都内の17店舗をランキング化したものです。",
        "毎日の店舗別詳細記事は有料メンバーシップで公開していますが、"
        "週次のサマリーは無料で公開しています。",
        "",
        "## 週間ランキング TOP10",
        "",
    ]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for rank, row in ranking.iterrows():
        prefix = medals.get(rank, f"**{rank}位**")
        lines.append(
            f"{prefix} **{row['display_name']}**"
        )
        lines.append(
            f"　週平均 p_high: {row['p_high_mean']:.3f}　"
            f"最大: {row['p_high_max']:.3f}　"
            f"集計台数: {int(row['n_machines'])}台"
        )
        lines.append("")


    # ===== 実績セクション（actuals が渡された場合のみ） =====
    if actuals and actuals.get("records"):
        s = actuals["summary"]
        lines.extend(
            [
                "",
                "## 先週の予測実績（透明性のため公開）",
                "",
                "各店舗で AI が予測1位とした機種を、実際の差枚と照らし合わせました。",
                "",
                "### 全店舗サマリー",
                "",
                f"- 集計対象: {s['n_total']} 台（7日 × 店舗数）",
                f"- 勝率（差枚プラス）: **{s['win_rate']*100:.1f}%** "
                f"（{s['n_win']}勝 / {s['n_lose']}負）",
                f"- 平均差枚: **{s['avg_diff']:+.0f}枚**",
                f"- 中央値: {s['median_diff']:+.0f}枚",
                f"- 累計差枚: **{s['sum_diff']:+,}枚**",
                "",
                "### ベスト3（予測的中）",
                "",
            ]
        )
        for i, r in enumerate(actuals["best3"], 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}位")
            d = r["date"]
            date_str = d.strftime("%m/%d") if hasattr(d, "strftime") else str(d)
            lines.append(f"{medal} **{r['shop_name']}** （{date_str}）")
            lines.append(f"　{r['machine_name']}　**{r['diff']:+,}枚**")
            lines.append("")

        lines.extend(
            [
                "### ワースト3（参考: 外した予測）",
                "",
            ]
        )
        for i, r in enumerate(actuals["worst3"], 1):
            d = r["date"]
            date_str = d.strftime("%m/%d") if hasattr(d, "strftime") else str(d)
            lines.append(f"{i}位 {r['shop_name']} （{date_str}）")
            lines.append(f"　{r['machine_name']}　{r['diff']:+,}枚")
            lines.append("")

    # ===== 実績セクションここまで =====

    lines.extend(
        [
            "",
            "## 指標について",
            "",
            "- **p_high**: 当該機種・店舗が「高設定（設定5・6相当）」である確率を、"
            "過去の差枚推移・店舗傾向・曜日特性などから算出した値です（0〜1）。",
            "- 値が高いほど、その日に高設定が投入された期待が大きいことを意味します。",
            "- 週平均は7日間（月曜〜日曜）の単純平均です。",
            "",
            "## 注意事項",
            "",
            "本記事は過去データに基づく**統計的な期待値**であり、"
            "実際の設定や勝敗を保証するものではありません。",
            "投資は自己責任でお願いします。",
            "",
            "## 毎日の詳細記事",
            "",
            "店舗別の機種ランキング（TOP10）は、メンバーシップ加入者向けに毎朝7:30に公開しています。",
            "ご興味のある方はクリエイターページからご確認ください。",
            "",
        ]
    )
    return "\n".join(lines)



def markdown_to_note_html(md: str) -> str:
    """簡易 Markdown → Note HTML 変換.

    Note の API は <p>, <h2>, <table>, <ul> 等の基本タグをサポート。
    日次記事の generate_article.py と同じ変換ロジックを踏襲。
    """
    import re
    import uuid

    html_parts: list[str] = []
    lines = md.split("\n")
    i = 0

    def new_id() -> str:
        return str(uuid.uuid4())

    while i < len(lines):
        line = lines[i].rstrip()

        if not line:
            i += 1
            continue

        # H1
        if line.startswith("# "):
            html_parts.append(f'<h2 id="{new_id()}">{line[2:]}</h2>')
            i += 1
            continue
        # H2
        if line.startswith("## "):
            html_parts.append(f'<h3 id="{new_id()}">{line[3:]}</h3>')
            i += 1
            continue

        # テーブル
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            if len(table_lines) >= 2:
                header_cells = [c.strip() for c in table_lines[0].strip("|").split("|")]
                body_rows = []
                for tl in table_lines[2:]:  # 区切り行をスキップ
                    cells = [c.strip() for c in tl.strip("|").split("|")]
                    body_rows.append(cells)
                t = ["<table>"]
                t.append("<thead><tr>")
                for h in header_cells:
                    t.append(f"<th>{h}</th>")
                t.append("</tr></thead>")
                t.append("<tbody>")
                for row in body_rows:
                    t.append("<tr>")
                    for c in row:
                        t.append(f"<td>{c}</td>")
                    t.append("</tr>")
                t.append("</tbody></table>")
                html_parts.append("".join(t))
            continue

        # 通常段落（**強調** を <strong> に変換）
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        html_parts.append(f'<p id="{new_id()}">{text}</p>')
        i += 1

    return "".join(html_parts)


# ---------------------------------------------------------------------------
# Note API 投稿
# ---------------------------------------------------------------------------
def get_note_session_cookie() -> str:
    """環境変数 NOTE_SESSION_V5 → ローカル storage_state → R2 の順に取得."""
    import os

    cookie = os.environ.get("NOTE_SESSION_V5")
    if cookie:
        return cookie

    state_path = PROJECT_ROOT / "auth" / "note_storage_state.json"
    if state_path.exists():
        data = json.loads(state_path.read_text(encoding="utf-8"))
        for c in data.get("cookies", []):
            if c["name"] == "_note_session_v5":
                return c["value"]

    # R2 fallback
    try:
        r2 = build_r2_client_from_env()
        obj = r2._client.get_object(
            Bucket=r2.config.bucket, Key="auth/note_storage_state.json"
        )
        data = json.loads(obj["Body"].read())
        for c in data.get("cookies", []):
            if c["name"] == "_note_session_v5":
                return c["value"]
    except Exception as e:
        logger.error(f"R2 から storage_state 取得失敗: {e}")

    raise RuntimeError("_note_session_v5 cookie が取得できません")


def build_session(cookie: str):
    import requests

    ORIGIN = "https://editor.note.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
    )

    s = requests.Session()
    s.headers.update(
        {
            "Accept": "*/*",
            "Accept-Language": "ja,en;q=0.9,en-GB;q=0.8,en-US;q=0.7",
            "Content-Type": "application/json",
            "Origin": ORIGIN,
            "Referer": f"{ORIGIN}/",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    s.cookies.set("_note_session_v5", cookie, domain=".note.com")
    return s




def create_text_note(session) -> dict:
    r = session.post(
        "https://note.com/api/v1/text_notes",
        json={"template_key": None},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise RuntimeError(f"text_notes 作成失敗: {payload['error']}")
    data = payload["data"]
    return {
        "id": data["id"],
        "key": data["key"],
        "slug": data.get("slug", f"slug-{data['key']}"),
    }




def save_draft(session, note_id: int, title: str, body_html: str) -> None:
    r = session.post(
        f"https://note.com/api/v1/text_notes/draft_save?id={note_id}&is_temp_saved=true",
        json={
            "body": body_html,
            "body_length": len(body_html),
            "name": title,
            "index": False,
            "is_lead_form": False,
        },
        timeout=30,
    )
    r.raise_for_status()


def publish_free(
    session,
    note_id: int,
    note_key: str,
    title: str,
    body_html: str,
    hashtags: list[str],
) -> dict:
    """無料公開（メンバーシップ制限なし、価格0、ハッシュタグ付き）."""
    payload = {
        "name": title,
        "free_body": body_html,
        "body_length": len(body_html),
        "status": "published",
        "circle_permissions": [],  # 空 = 全員に公開
        "price": 0,
        "slug": f"slug-{note_key}",
        "author_ids": [],
        "index": True,
        "is_lead_form": False,
        "exclude_from_creator_top": False,
        "line_add_friend_access_token": "",
        "hashtags": [{"name": h} for h in hashtags],
    }
    r = session.put(
        f"https://note.com/api/v1/text_notes/{note_id}",
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def post_weekly_report(
    title: str,
    body_html: str,
    hashtags: list[str],
    *,
    draft_only: bool = False,
) -> dict:
    cookie = get_note_session_cookie()
    session = build_session(cookie)

    logger.info("Step 1: text_note 作成")
    note = create_text_note(session)
    note_id = note["id"]
    note_key = note["key"]
    logger.info(f"  -> id={note_id}, key={note_key}")

    logger.info("Step 2: 下書き保存")
    save_draft(session, note_id, title, body_html)

    if draft_only:
        logger.info("draft-only モード: 公開はスキップ")
        return {"status": "draft", "note_id": note_id, "note_key": note_key}

    logger.info("Step 3: 無料公開")
    time.sleep(1)
    result = publish_free(session, note_id, note_key, title, body_html, hashtags)
    logger.info(f"  -> 公開完了: https://note.com/notes/{note_key}")
    return {
        "status": "published",
        "note_id": note_id,
        "note_key": note_key,
        "url": f"https://note.com/notes/{note_key}",
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="週次レポート生成・Note 無料公開")
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="集計対象週の任意の日付（YYYY-MM-DD）。空欄なら直近の完了週。",
    )
    p.add_argument("--dry-run", action="store_true", help="生成のみ、投稿しない")
    p.add_argument(
        "--draft-only", action="store_true", help="下書き保存のみ、公開しない"
    )
    p.add_argument(
        "--post-only",
        action="store_true",
        help="既存の markdown ファイルを投稿のみ実行（生成はスキップ）",
    )
    p.add_argument("--top-n", type=int, default=10, help="ランキング上位件数")
    p.add_argument(
        "--hashtags",
        type=str,
        default=",".join(DEFAULT_HASHTAGS),
        help="カンマ区切りのハッシュタグ",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    target = None
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    start, end = resolve_week_range(target)
    logger.info(f"集計期間: {start} 〜 {end}")

    REPORTS_DIR.mkdir(exist_ok=True)
    md_path = REPORTS_DIR / f"weekly_{end:%Y-%m-%d}.md"
    title = build_title(start, end)
    hashtags = [h.strip() for h in args.hashtags.split(",") if h.strip()]

    # --post-only: 既存 markdown を読み込んで投稿のみ
    if args.post_only:
        if not md_path.exists():
            logger.error(f"markdown が見つかりません: {md_path}")
            return 1
        md = md_path.read_text(encoding="utf-8")
        body_html = markdown_to_note_html(md)
        result = post_weekly_report(
            title, body_html, hashtags, draft_only=args.draft_only
        )
        logger.info(f"投稿結果: {result}")
        return 0

    # 生成
    shops_config = load_shops_config()
    df = load_dataset()
    ranking = aggregate_weekly_ranking(df, start, end, shops_config, top_n=args.top_n)
    logger.info(f"ランキング上位:\n{ranking[['display_name', 'p_high_mean']].to_string()}")

    logger.info("先週の予測実績を集計中...")
    try:
        actuals = aggregate_weekly_actuals(df, start, end, shops_config)
        s = actuals["summary"]
        if s:
            logger.info(
                f"実績集計: 勝率 {s['win_rate']*100:.1f}% "
                f"({s['n_win']}勝/{s['n_lose']}負), "
                f"平均 {s['avg_diff']:+.0f}枚, 累計 {s['sum_diff']:+,}枚"
            )
    except Exception as e:
        logger.warning(f"実績集計失敗（スキップ）: {e}")
        actuals = None

    md = build_markdown(start, end, ranking, actuals=actuals)

    md_path.write_text(md, encoding="utf-8")
    logger.info(f"markdown 保存: {md_path}")

    if args.dry_run:
        logger.info("dry-run モード: 投稿はスキップ")
        return 0

    # 投稿
    body_html = markdown_to_note_html(md)
    result = post_weekly_report(title, body_html, hashtags, draft_only=args.draft_only)

    # ログ保存
    log_path = PROJECT_ROOT / "logs" / f"weekly_report_{end:%Y-%m-%d}.json"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(
        json.dumps(
            {
                "period": {"start": str(start), "end": str(end)},
                "title": title,
                "result": result,
                "ranking": ranking.to_dict(orient="records"),
                "actuals_summary": actuals["summary"] if actuals else None,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    logger.info(f"ログ保存: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
