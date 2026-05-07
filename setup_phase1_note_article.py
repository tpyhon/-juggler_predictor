"""Phase 1: Note 記事生成パイプライン (既存 SlotPrediction 互換出力)。

- juggler_specs.yaml: 9 機種スペック表
- setting_estimator.py: 合成確率 → 設定 1〜6 (ヒューリスティック)
- score.py: diff01 / scoreA / p4 / base100 計算
- note_article.py: Markdown 記事生成
- generate_article.py: CLI
- tests: 9 件追加
"""
from __future__ import annotations
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ============================================================
# config/juggler_specs.yaml
# ============================================================
FILES["config/juggler_specs.yaml"] = """\
# 機種別スペック表 (BB/RB/合成 の各設定値の確率)
# 既存 SlotPrediction prod/JugAnalyzer_universal.py から移植
# 各リストは [設定1, 設定2, 設定3, 設定4, 設定5, 設定6]

マイジャグラーV:
  BB:    [0.003661, 0.003723, 0.003815, 0.003967, 0.004120, 0.004272]
  RB:    [0.002441, 0.002839, 0.002990, 0.003174, 0.003557, 0.004272]
  合成:  [0.006105, 0.006410, 0.006775, 0.007112, 0.007843, 0.008726]
  機械割: [97.0, 98.7, 100.8, 103.6, 105.8, 109.4]

ネオアイムジャグラーEX:
  BB:    [0.003708, 0.003784, 0.003861, 0.004029, 0.004196, 0.004376]
  RB:    [0.002319, 0.002747, 0.002990, 0.003144, 0.003417, 0.003922]
  合成:  [0.006028, 0.006536, 0.006844, 0.007163, 0.007628, 0.008299]
  機械割: [96.6, 98.9, 101.0, 103.4, 105.4, 109.0]

ゴーゴージャグラー3:
  BB:    [0.003661, 0.003723, 0.003861, 0.004044, 0.004151, 0.004365]
  RB:    [0.001892, 0.002518, 0.002990, 0.003144, 0.003540, 0.004272]
  合成:  [0.005553, 0.006250, 0.006844, 0.007179, 0.007634, 0.008627]
  機械割: [96.5, 98.7, 101.9, 103.8, 106.0, 110.1]

ファンキージャグラー2:
  BB:    [0.003480, 0.003661, 0.003723, 0.003861, 0.003982, 0.004151]
  RB:    [0.002319, 0.002625, 0.002868, 0.003174, 0.003357, 0.003723]
  合成:  [0.005797, 0.006285, 0.006592, 0.007032, 0.007337, 0.007843]
  機械割: [96.4, 98.6, 100.7, 103.3, 105.3, 108.5]

アイムジャグラーEX-TP:
  BB:    [0.003480, 0.003661, 0.003661, 0.003723, 0.003861, 0.003982]
  RB:    [0.002319, 0.002747, 0.003082, 0.003296, 0.003480, 0.003723]
  合成:  [0.005797, 0.006410, 0.006729, 0.006998, 0.007262, 0.007728]
  機械割: [96.4, 99.9, 102.0, 104.0, 106.0, 109.2]

ハッピージャグラーVIII:
  BB:    [0.003661, 0.003693, 0.003799, 0.003937, 0.004181, 0.004425]
  RB:    [0.002518, 0.002762, 0.003006, 0.003327, 0.003661, 0.003906]
  合成:  [0.006180, 0.006454, 0.006807, 0.007264, 0.007843, 0.008333]
  機械割: [97.0, 98.1, 99.9, 102.9, 105.8, 108.4]

ミスタージャグラー:
  BB:    [0.003723, 0.003738, 0.003845, 0.004013, 0.004151, 0.004212]
  RB:    [0.002670, 0.002823, 0.003021, 0.003433, 0.003891, 0.004212]
  合成:  [0.006394, 0.006562, 0.006868, 0.007446, 0.008039, 0.008425]
  機械割: [97.0, 98.0, 99.8, 102.7, 105.5, 107.3]

ジャグラーガールズSS:
  BB:    [0.003661, 0.003693, 0.003845, 0.003998, 0.004105, 0.004425]
  RB:    [0.002625, 0.002853, 0.003158, 0.003555, 0.003693, 0.003967]
  合成:  [0.006285, 0.006546, 0.007003, 0.007553, 0.007795, 0.008389]
  機械割: [97.0, 97.9, 99.9, 102.1, 104.0, 107.5]

ウルトラミラクルジャグラー:
  BB:    [0.003738, 0.003830, 0.003906, 0.004120, 0.004288, 0.004623]
  RB:    [0.002350, 0.002487, 0.002853, 0.003098, 0.003357, 0.003601]
  合成:  [0.006086, 0.006317, 0.006760, 0.007215, 0.007645, 0.008224]
  機械割: [97.0, 98.1, 99.8, 102.1, 104.5, 108.1]
"""

# ============================================================
# src/juggler_predictor/model/setting_estimator.py
# ============================================================
FILES["src/juggler_predictor/model/setting_estimator.py"] = '''\
"""合成確率 → 設定 1〜6 のヒューリスティック推定。

既存 SlotPrediction prod/JugAnalyzer_universal._estimate_setting と互換。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# fallback の差枚閾値
_FALLBACK_THRESHOLDS = [
    (1500, 6),
    (500, 5),
    (0, 4),
    (-500, 3),
    (-1000, 2),
]


@lru_cache(maxsize=1)
def load_juggler_specs(path: str | None = None) -> dict[str, dict[str, list[float]]]:
    """機種スペック表を YAML から読み込む。"""
    if path is None:
        # repo root / config / juggler_specs.yaml を自動解決
        root = Path(__file__).resolve().parents[3]
        path = str(root / "config" / "juggler_specs.yaml")
    p = Path(path)
    if not p.exists():
        logger.warning("juggler_specs.yaml not found at %s", p)
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def parse_composite_prob(value: Any) -> float:
    """\"1/156.3\" 形式の文字列 / 数値を float に変換。失敗時は 0.0。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "nan", "NaN"):
        return 0.0
    if "/" in s:
        try:
            num, den = s.split("/", 1)
            num_f = float(num.strip())
            den_f = float(den.strip())
            if den_f <= 0:
                return 0.0
            return num_f / den_f
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def estimate_setting(
    composite_prob: float | str | None,
    diff: float,
    machine_name: str,
    *,
    specs: dict[str, dict[str, list[float]]] | None = None,
) -> int:
    """合成確率と機種名から設定 1〜6 を推定。

    1. 機種スペックがあり composite_prob > 0 なら、合成確率を 6 段階の公称値と
       比較して最近傍の設定を返す。
    2. それ以外は diff の閾値で fallback。
    """
    if specs is None:
        specs = load_juggler_specs()

    cp = parse_composite_prob(composite_prob)
    if machine_name in specs and cp > 0:
        spec = specs[machine_name].get("合成") or specs[machine_name].get("composite")
        if spec:
            distances = [(i + 1, abs(cp - sp)) for i, sp in enumerate(spec)]
            return min(distances, key=lambda x: x[1])[0]

    # fallback
    d = float(diff) if diff is not None else 0.0
    for threshold, setting in _FALLBACK_THRESHOLDS:
        if d > threshold:
            return setting
    return 1
'''

# ============================================================
# src/juggler_predictor/model/score.py
# ============================================================
FILES["src/juggler_predictor/model/score.py"] = '''\
"""予測スコア計算: diff01 / scoreA / p4 / base100。

既存 SlotPrediction の base100 計算式を踏襲:
    base100 = 100 * (0.72 * p_win + 0.22 * diff01 + 0.06 * p4)
    scoreA  = alpha * p_win + (1 - alpha) * diff01    (alpha = 0.70)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ALPHA_DEFAULT = 0.70
BASE100_W_PWIN = 0.72
BASE100_W_DIFF01 = 0.22
BASE100_W_P4 = 0.06


def compute_diff01(predicted_diff: pd.Series) -> pd.Series:
    """店舗内で predicted_diff を [0, 1] に min-max 正規化。

    全値が等しい場合は 0.5 を返す。
    """
    s = pd.Series(predicted_diff).astype(float)
    lo, hi = s.min(), s.max()
    if hi - lo < 1e-9:
        return pd.Series(np.full(len(s), 0.5), index=s.index)
    return (s - lo) / (hi - lo)


def compute_score_a(p_win: pd.Series, diff01: pd.Series, alpha: float = ALPHA_DEFAULT) -> pd.Series:
    """scoreA = alpha * p_win + (1 - alpha) * diff01"""
    p = pd.Series(p_win).astype(float).clip(0.0, 1.0)
    d = pd.Series(diff01).astype(float).clip(0.0, 1.0)
    return alpha * p + (1.0 - alpha) * d


def compute_p4(predicted_setting: pd.Series) -> pd.Series:
    """設定4以上確率の代理指標。当日推定設定 >= 4 なら 1.0、それ未満なら 0.0。

    将来的に予測モデル化したら本来の確率に差し替え。
    """
    s = pd.Series(predicted_setting).astype(float)
    return (s >= 4).astype(float)


def compute_base100(p_win: pd.Series, diff01: pd.Series, p4: pd.Series) -> pd.Series:
    """総合スコア (0-100)。"""
    p = pd.Series(p_win).astype(float).clip(0.0, 1.0)
    d = pd.Series(diff01).astype(float).clip(0.0, 1.0)
    f = pd.Series(p4).astype(float).clip(0.0, 1.0)
    return 100.0 * (BASE100_W_PWIN * p + BASE100_W_DIFF01 * d + BASE100_W_P4 * f)


def base100_to_stars(base100_max: float) -> int:
    """注目度 ★ (1〜5) を base100 の店内最大値から算出。仮閾値。"""
    if base100_max >= 65:
        return 5
    if base100_max >= 58:
        return 4
    if base100_max >= 52:
        return 3
    if base100_max >= 46:
        return 2
    return 1
'''

# ============================================================
# src/juggler_predictor/report/__init__.py
# ============================================================
FILES["src/juggler_predictor/report/__init__.py"] = '''\
"""レポート / 記事生成モジュール。"""
from juggler_predictor.report.note_article import render_article  # noqa: F401
'''

# ============================================================
# src/juggler_predictor/report/note_article.py
# ============================================================
FILES["src/juggler_predictor/report/note_article.py"] = '''\
"""Note 記事 (Markdown) 生成。

入力 DataFrame に必要な列:
    machine_name, unit_number, p_win, predicted_diff, predicted_setting,
    diff01, scoreA, base100
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
    lines.append("> scoreA = α × p_win + (1-α) × diff01（正規化済）")
    lines.append("")
    top = df.sort_values("scoreA", ascending=False).head(10).reset_index(drop=True)
    for i, row in top.iterrows():
        rank = i + 1
        prefix = MEDAL_RANK.get(rank, f"{rank}.")
        bullet = f"{rank}. " if rank > 3 else f"{rank}. {prefix} "
        if rank <= 3:
            head = f"{rank}. {prefix} **{row['unit_number']}番台**（{row['machine_name']}）"
        else:
            head = f"{rank}. **{row['unit_number']}番台**（{row['machine_name']}）"
        lines.append(head)
        detail = (
            f"   - scoreA: {row['scoreA']:.3f} / "
            f"p_win: {_fmt_pct(row['p_win'])} / "
            f"予測差枚: {_fmt_diff(row['predicted_diff'])} / "
            f"設定{int(row['predicted_setting'])}"
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
    lines.append(f"- **p_win（プラス確率）**: {_fmt_pct(r1['p_win'])}（p_win_raw）")
    lines.append(f"- **予測差枚**: {_fmt_diff(r1['predicted_diff'])}")
    lines.append(f"- **diff01（正規化）**: {r1['diff01']:.3f}")
    lines.append(f"- **予測設定**: 設定{int(r1['predicted_setting'])}")
    lines.append("")
    lines.append("### 📝 選定理由")
    lines.append("")
    pw = float(r1["p_win"])
    if pw >= 0.60:
        lines.append(f"- ✅ **プラス確率が高め**（{_fmt_pct(pw)}）：50%以上の確率でプラス収支が期待")
    elif pw >= 0.50:
        lines.append(f"- 📊 プラス確率は中程度（{_fmt_pct(pw)}）")
    else:
        lines.append(f"- ⚠️ プラス確率はやや低め（{_fmt_pct(pw)}）")
    pd_diff = float(r1["predicted_diff"])
    if pd_diff > 0:
        lines.append(f"- 📊 **予測差枚はプラス圏**（{_fmt_diff(pd_diff)}）")
    else:
        lines.append(f"- 📊 予測差枚はマイナス圏（{_fmt_diff(pd_diff)}）")
    if float(r1["diff01"]) >= 0.80:
        lines.append(f"- ✅ **店内での相対順位がトップクラス**（diff01: {r1['diff01']:.3f}）")
    elif float(r1["diff01"]) >= 0.50:
        lines.append(f"- 📊 店内相対順位は中位（diff01: {r1['diff01']:.3f}）")
    lines.append(f"- 📊 α値が高め（{alpha:.2f}）→ p_win 重視の選定")
    lines.append("")
    if len(top) >= 2:
        lines.append("### 📊 2位・3位との比較")
        lines.append("")
        for i, row in top.iterrows():
            rank = i + 1
            line = (
                f"{rank}. **{row['unit_number']}番台**（{row['machine_name']}）: "
                f"scoreA {row['scoreA']:.3f} / p_win {_fmt_pct(row['p_win'])} / "
                f"差枚 {_fmt_diff(row['predicted_diff'])}"
            )
            lines.append(line)
        lines.append("")
    return lines


def _render_no_go(df: pd.DataFrame, threshold: float) -> list[str]:
    lines: list[str] = []
    lines.append("## ⚠️ NO-GO 判定")
    lines.append("")
    if len(df) == 0:
        lines.append("対象データがありません。")
        return lines
    pwin_max = float(df["p_win"].max())
    if pwin_max >= threshold:
        lines.append(
            f"🟢 **GO** — Top1 の p_win が {_fmt_pct(pwin_max)} で閾値 {_fmt_pct(threshold)} 以上"
        )
    else:
        lines.append(
            f"🔴 **NO-GO** — Top1 の p_win が {_fmt_pct(pwin_max)} で閾値 {_fmt_pct(threshold)} 未満"
        )
        lines.append("")
        lines.append("- 全台のプラス確率が低水準のため、本日は見送り推奨")
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
                f"- scoreA: {row['scoreA']:.3f} / p_win: {_fmt_pct(row['p_win'])} / "
                f"差枚: {_fmt_diff(row['predicted_diff'])}"
            )
            lines.append(line)
        lines.append("")
    n_total = len(df)
    n_high = int((df["predicted_setting"] >= 4).sum())
    rate = (n_high / n_total) if n_total > 0 else 0.0
    lines.append("### 📈 設定4以上出現統計")
    lines.append("")
    lines.append(f"- 設定4以上予測台数: **{n_high}台** / 全{n_total}台")
    lines.append(f"- 設定4以上出現率: **{rate * 100:.1f}%**")
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
                f"p_win {_fmt_pct(row['p_win'])} / "
                f"差枚 {_fmt_diff(row['predicted_diff'])} / "
                f"diff01 {row['diff01']:.3f} / "
                f"設定{int(row['predicted_setting'])}"
            )
            lines.append(line)
        lines.append("")
    return lines


def render_article(
    *,
    shop_display_name: str,
    date_str: str,
    predictions: pd.DataFrame,
    alpha: float = 0.70,
    no_go_threshold: float = 0.55,
    hashtags: Iterable[str] | None = None,
) -> str:
    """Note 記事 Markdown を生成。

    predictions に必要な列:
        machine_name, unit_number, p_win, predicted_diff,
        predicted_setting, diff01, scoreA, base100
    """
    required = {
        "machine_name", "unit_number", "p_win", "predicted_diff",
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
    lines.append(f"- **データ更新日時**: {date_str}")
    lines.append("")
    lines.append(f"## 🎯 本日の注目度：{_stars(stars)}（{stars}.0/5.0）")
    lines.append("")
    lines.append("## 📊 本日のデータ概要")
    lines.append("")
    lines.append(f"- **対象台数**: {n_total}台")
    lines.append(f"- **scoreA 0.5以上**: {n_score05}台")
    lines.append(f"- **高設定予測台（設定4以上）**: {n_high}台")
    lines.append("")
    lines.append("## 💡 このデータでできること")
    lines.append("")
    lines.append("- 全台の設定予測を確認（scoreA / p_win / 予測差枚）")
    lines.append("- 推奨度ランキングTOP10をチェック")
    lines.append("- 機種別の詳細データを閲覧")
    lines.append("")
    lines.append("## ⚠️ 免責事項")
    lines.append("")
    lines.append("本データは統計分析に基づく予測であり、実際の設定を保証するものではありません。")
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
# scripts/generate_article.py
# ============================================================
FILES["scripts/generate_article.py"] = '''\
"""Note 記事生成 CLI。

使い方:
    uv run python scripts/generate_article.py --shop espas_ueno --date 2026-05-04
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys
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
    parser.add_argument("--date", required=True, help="対象日 YYYY-MM-DD (この日の実績→翌日予測)")
    parser.add_argument("--parquet", default=str(ROOT / "data" / "dataset.parquet"))
    parser.add_argument("--bundle", default=str(ROOT / "models" / "model_bundle.joblib"))
    parser.add_argument("--out-dir", default=str(ROOT / "reports"))
    parser.add_argument("--alpha", type=float, default=0.70)
    parser.add_argument("--no-go-threshold", type=float, default=0.55)
    args = parser.parse_args()

    load_dotenv()
    setup_logging()

    shops = _load_shops()
    shop = next((s for s in shops if s["id"] == args.shop), None)
    if shop is None:
        logger.error("shop_id %s が shops.yaml に存在しません", args.shop)
        return 1
    display_name = shop.get("display_name", args.shop)

    logger.info("[1] dataset 読み込み: %s", args.parquet)
    df = pd.read_parquet(args.parquet)
    df["date"] = df["date"].astype(str)

    target = df[(df["shop_id"] == args.shop) & (df["date"] == args.date)].copy()
    if len(target) == 0:
        logger.error("該当データなし: shop=%s date=%s", args.shop, args.date)
        return 2
    logger.info("対象行数: %d", len(target))

    logger.info("[2] モデル読み込み: %s", args.bundle)
    bundle = joblib.load(args.bundle)
    feature_cols = bundle["feature_cols"]
    regressor = bundle["regressor"]
    classifier = bundle.get("classifier_calibrated") or bundle["classifier_raw"]

    X = target[feature_cols]

    logger.info("[3] 予測実行")
    target["predicted_diff"] = regressor.predict(X)
    if hasattr(classifier, "predict_proba"):
        proba = classifier.predict_proba(X)
        target["p_win"] = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
    else:
        target["p_win"] = classifier.predict(X)

    logger.info("[4] 当日推定設定")
    target["predicted_setting"] = target.apply(
        lambda r: estimate_setting(
            r.get("composite_prob"),
            r.get("diff", 0.0),
            r.get("machine_name", ""),
        ),
        axis=1,
    )

    logger.info("[5] スコア計算")
    target["diff01"] = compute_diff01(target["predicted_diff"]).values
    target["scoreA"] = compute_score_a(target["p_win"], target["diff01"], alpha=args.alpha).values
    target["p4"] = compute_p4(target["predicted_setting"]).values
    target["base100"] = compute_base100(target["p_win"], target["diff01"], target["p4"]).values

    logger.info("[6] 記事生成")
    hashtags = ["ジャグラー", "スロット", "パチスロ", "設定狙い", "立ち回り", "期待値", "東京"]
    md = render_article(
        shop_display_name=display_name,
        date_str=args.date,
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
    print(f"  対象日    : {args.date}")
    print(f"  対象台数  : {len(target)}")
    print(f"  Top1 p_win: {target['p_win'].max():.3f}")
    print(f"  base100 max: {target['base100'].max():.1f}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

# ============================================================
# tests/test_setting_estimator.py
# ============================================================
FILES["tests/test_setting_estimator.py"] = '''\
"""setting_estimator のテスト。"""
from juggler_predictor.model.setting_estimator import (
    estimate_setting,
    load_juggler_specs,
    parse_composite_prob,
)


def test_parse_composite_prob_str():
    assert abs(parse_composite_prob("1/156.0") - 1 / 156.0) < 1e-9
    assert abs(parse_composite_prob("1/100") - 0.01) < 1e-9


def test_parse_composite_prob_invalid():
    assert parse_composite_prob(None) == 0.0
    assert parse_composite_prob("") == 0.0
    assert parse_composite_prob("-") == 0.0
    assert parse_composite_prob("nan") == 0.0


def test_specs_loaded():
    specs = load_juggler_specs()
    assert "マイジャグラーV" in specs
    assert "合成" in specs["マイジャグラーV"]
    assert len(specs["マイジャグラーV"]["合成"]) == 6


def test_estimate_setting_high_prob():
    # 設定6 相当の合成確率 (1/114.6 ≒ 0.008726)
    s = estimate_setting("1/114.6", 0.0, "マイジャグラーV")
    assert s == 6


def test_estimate_setting_low_prob():
    # 設定1 相当 (1/163.8 ≒ 0.006105)
    s = estimate_setting("1/163.8", 0.0, "マイジャグラーV")
    assert s == 1


def test_estimate_setting_fallback_high_diff():
    # 不明機種は diff fallback
    s = estimate_setting("1/100", 2000.0, "未知の機種")
    assert s == 6


def test_estimate_setting_fallback_low_diff():
    s = estimate_setting(None, -1500.0, "未知の機種")
    assert s == 1
'''

# ============================================================
# tests/test_score.py
# ============================================================
FILES["tests/test_score.py"] = '''\
"""score.py のテスト。"""
import pandas as pd

from juggler_predictor.model.score import (
    base100_to_stars,
    compute_base100,
    compute_diff01,
    compute_p4,
    compute_score_a,
)


def test_diff01_normalization():
    s = pd.Series([100.0, 200.0, 300.0])
    out = compute_diff01(s)
    assert abs(out.iloc[0] - 0.0) < 1e-9
    assert abs(out.iloc[1] - 0.5) < 1e-9
    assert abs(out.iloc[2] - 1.0) < 1e-9


def test_diff01_constant():
    s = pd.Series([500.0, 500.0, 500.0])
    out = compute_diff01(s)
    assert (out == 0.5).all()


def test_score_a_formula():
    p_win = pd.Series([0.5])
    diff01 = pd.Series([0.8])
    out = compute_score_a(p_win, diff01, alpha=0.7)
    # 0.7*0.5 + 0.3*0.8 = 0.35 + 0.24 = 0.59
    assert abs(out.iloc[0] - 0.59) < 1e-9


def test_p4_threshold():
    s = pd.Series([1, 3, 4, 5, 6])
    out = compute_p4(s)
    assert list(out) == [0.0, 0.0, 1.0, 1.0, 1.0]


def test_base100_formula():
    out = compute_base100(pd.Series([0.5]), pd.Series([0.5]), pd.Series([1.0]))
    # 100 * (0.72*0.5 + 0.22*0.5 + 0.06*1.0) = 100 * (0.36 + 0.11 + 0.06) = 53.0
    assert abs(out.iloc[0] - 53.0) < 1e-6


def test_stars_thresholds():
    assert base100_to_stars(70.0) == 5
    assert base100_to_stars(60.0) == 4
    assert base100_to_stars(53.0) == 3
    assert base100_to_stars(48.0) == 2
    assert base100_to_stars(40.0) == 1
'''

# ============================================================
# tests/test_note_article.py
# ============================================================
FILES["tests/test_note_article.py"] = '''\
"""note_article.render_article のテスト。"""
import pandas as pd
import pytest

from juggler_predictor.report import render_article


def _sample_predictions(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "machine_name": ["マイジャグラーV"] * n,
        "unit_number": [str(2000 + i) for i in range(n)],
        "p_win": [0.65, 0.55, 0.50, 0.45, 0.40][:n],
        "predicted_diff": [400.0, 200.0, 100.0, -100.0, -300.0][:n],
        "predicted_setting": [6, 5, 4, 3, 1][:n],
        "diff01": [1.0, 0.7, 0.5, 0.3, 0.0][:n],
        "scoreA": [0.75, 0.60, 0.50, 0.40, 0.28][:n],
        "base100": [70.0, 55.0, 45.0, 35.0, 25.0][:n],
    })


def test_render_article_basic():
    df = _sample_predictions(5)
    md = render_article(
        shop_display_name="テスト店舗",
        date_str="2026-05-04",
        predictions=df,
    )
    assert "テスト店舗" in md
    assert "2026-05-04" in md
    assert "対象台数**: 5台" in md
    assert "🥇" in md
    assert "TOP10" in md or "TOP3" in md
    assert "免責事項" in md


def test_render_article_missing_columns():
    df = pd.DataFrame({"machine_name": ["A"], "unit_number": ["1"]})
    with pytest.raises(ValueError, match="不足"):
        render_article(
            shop_display_name="X",
            date_str="2026-05-04",
            predictions=df,
        )


def test_render_article_no_go():
    df = _sample_predictions(3)
    df["p_win"] = [0.40, 0.35, 0.30]  # 全部低い
    md = render_article(
        shop_display_name="テスト",
        date_str="2026-05-04",
        predictions=df,
        no_go_threshold=0.55,
    )
    assert "NO-GO" in md
'''

# ============================================================
# src/juggler_predictor/model/__init__.py 更新 (追記)
# ============================================================
INIT_APPEND = """

# Phase 1: Note 記事生成パイプライン
from juggler_predictor.model.setting_estimator import (  # noqa: F401,E402
    estimate_setting,
    load_juggler_specs,
    parse_composite_prob,
)
from juggler_predictor.model.score import (  # noqa: F401,E402
    base100_to_stars,
    compute_base100,
    compute_diff01,
    compute_p4,
    compute_score_a,
)
"""


def write_all() -> None:
    n = 0
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        size = len(content.encode("utf-8"))
        print(f"[WRITE] {rel} ({size} bytes)")
        n += 1

    init_path = ROOT / "src" / "juggler_predictor" / "model" / "__init__.py"
    if init_path.exists():
        current = init_path.read_text(encoding="utf-8")
        if "setting_estimator" not in current:
            init_path.write_text(current + INIT_APPEND, encoding="utf-8")
            print(f"[APPEND] {init_path.relative_to(ROOT)}")
        else:
            print(f"[SKIP] {init_path.relative_to(ROOT)} (already has setting_estimator)")
    else:
        print(f"[WARN] {init_path} が存在しません")

    print(f"\n[SUCCESS] {n} files written")


if __name__ == "__main__":
    write_all()
