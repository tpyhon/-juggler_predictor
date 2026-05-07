"""Phase 1.5: 設定期待度モデル導入セットアップスクリプト。

新規:
  - scripts/train_setting.py
  - src/juggler_predictor/model/setting_predictor.py
  - tests/test_setting_predictor.py

変更:
  - src/juggler_predictor/model/score.py (p_high_to_stars, compute_score_a 再定義)
  - src/juggler_predictor/model/dataset.py (prev_setting, prev_p_high 列追加)
  - src/juggler_predictor/report/note_article.py (高設定期待度ベース)
  - scripts/generate_article.py (predicted_diff 廃止, p_high 使用)
  - tests/test_score.py (新閾値テスト追加)
  - tests/test_note_article.py (予測差枚不在の確認)
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES: dict[str, str] = {}

# ---------------------------------------------------------------------------
# scripts/train_setting.py
# ---------------------------------------------------------------------------
FILES["scripts/train_setting.py"] = '''"""設定期待度分類器 (multiclass) の学習スクリプト。

既存 model_bundle.joblib に setting_classifier キーを追加して保存する。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping, log_evaluation
from sklearn.metrics import accuracy_score, roc_auc_score

from juggler_predictor.model.dataset import time_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dataset.parquet"
BUNDLE = ROOT / "models" / "model_bundle.joblib"
META = ROOT / "models" / "setting_classifier_meta.json"


def main() -> None:
    if not DATA.exists():
        raise FileNotFoundError(f"dataset.parquet not found: {DATA}")
    if not BUNDLE.exists():
        raise FileNotFoundError(f"model_bundle.joblib not found: {BUNDLE}")

    df = pd.read_parquet(DATA)
    logger.info("dataset rows=%d cols=%d", len(df), len(df.columns))

    if "y_setting_next" not in df.columns:
        raise KeyError(
            "y_setting_next 列がありません。build_dataset.py を再実行してください。"
        )

    bundle = joblib.load(BUNDLE)
    feature_cols = list(bundle["feature_cols"])
    # prev_setting, prev_p_high を追加
    extra = [c for c in ("prev_setting", "prev_p_high") if c in df.columns and c not in feature_cols]
    feat_setting = feature_cols + extra
    logger.info("setting features = %d (base %d + extra %d)", len(feat_setting), len(feature_cols), len(extra))

    df_train, df_valid = time_split(df)
    df_train = df_train.dropna(subset=["y_setting_next"]).copy()
    df_valid = df_valid.dropna(subset=["y_setting_next"]).copy()

    X_train = df_train[feat_setting].astype(float).values
    X_valid = df_valid[feat_setting].astype(float).values
    y_train = df_train["y_setting_next"].astype(int).values
    y_valid = df_valid["y_setting_next"].astype(int).values

    logger.info("train rows=%d valid rows=%d", len(y_train), len(y_valid))
    logger.info("train class dist: %s", np.bincount(y_train, minlength=7)[1:].tolist())
    logger.info("valid class dist: %s", np.bincount(y_valid, minlength=7)[1:].tolist())

    # LightGBM は 0-indexed クラスを期待
    y_train0 = y_train - 1
    y_valid0 = y_valid - 1

    clf = LGBMClassifier(
        objective="multiclass",
        num_class=6,
        class_weight="balanced",
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=20,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        n_jobs=-1,
    )

    clf.fit(
        X_train,
        y_train0,
        eval_set=[(X_valid, y_valid0)],
        callbacks=[early_stopping(30), log_evaluation(50)],
    )

    proba = clf.predict_proba(X_valid)
    pred0 = proba.argmax(axis=1)
    acc = accuracy_score(y_valid0, pred0)

    # one-vs-rest macro AUC
    aucs = []
    for k in range(6):
        y_bin = (y_valid0 == k).astype(int)
        if y_bin.sum() == 0 or y_bin.sum() == len(y_bin):
            continue
        aucs.append(roc_auc_score(y_bin, proba[:, k]))
    macro_auc = float(np.mean(aucs)) if aucs else float("nan")

    p_high = proba[:, 3:].sum(axis=1)
    p_top = proba[:, 4:].sum(axis=1)
    high_actual = (y_valid >= 4).astype(int)
    auc_high = roc_auc_score(high_actual, p_high) if high_actual.sum() > 0 else float("nan")

    # P@5 per shop-date
    p5_list = []
    df_valid = df_valid.assign(p_high=p_high, high_actual=high_actual)
    for (sid, d), g in df_valid.groupby(["shop_id", "date"]):
        if len(g) < 5:
            continue
        top5 = g.nlargest(5, "p_high")
        p5_list.append(top5["high_actual"].mean())
    p_at_5 = float(np.mean(p5_list)) if p5_list else float("nan")

    logger.info("=== SETTING CLASSIFIER METRICS ===")
    logger.info("Top-1 accuracy : %.4f (random=0.1667)", acc)
    logger.info("Macro AUC (OvR): %.4f", macro_auc)
    logger.info("AUC (p_high)   : %.4f", auc_high)
    logger.info("P@5 (high)     : %.4f", p_at_5)
    logger.info("best iteration : %s", clf.best_iteration_)

    if macro_auc < 0.55:
        logger.warning("Macro AUC < 0.55: 設定予測の精度が低いため Phase 5 で特徴量改善検討。")

    bundle["setting_classifier"] = clf
    bundle["setting_features"] = feat_setting
    joblib.dump(bundle, BUNDLE)
    logger.info("setting_classifier saved into %s", BUNDLE)

    META.parent.mkdir(parents=True, exist_ok=True)
    META.write_text(
        json.dumps(
            {
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "n_train": int(len(y_train)),
                "n_valid": int(len(y_valid)),
                "best_iteration": int(clf.best_iteration_ or 0),
                "top1_accuracy": float(acc),
                "macro_auc_ovr": float(macro_auc),
                "auc_p_high": float(auc_high),
                "p_at_5_high": float(p_at_5),
                "features": feat_setting,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("meta saved: %s", META)


if __name__ == "__main__":
    main()
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/setting_predictor.py
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/model/setting_predictor.py"] = '''"""設定期待度モデルの推論ヘルパー。"""
from __future__ import annotations

import numpy as np


def validate_proba(proba: np.ndarray) -> None:
    """proba shape チェック。(n, 6) であること。"""
    if proba.ndim != 2 or proba.shape[1] != 6:
        raise ValueError(f"proba must be shape (n, 6), got {proba.shape}")


def compute_p_high(proba: np.ndarray) -> np.ndarray:
    """設定4以上の確率 P[setting >= 4]。proba は 0-indexed (列0=設定1)。"""
    validate_proba(proba)
    return proba[:, 3:].sum(axis=1)


def compute_p_top(proba: np.ndarray) -> np.ndarray:
    """設定5以上の確率 P[setting >= 5]。"""
    validate_proba(proba)
    return proba[:, 4:].sum(axis=1)


def compute_p_setting6(proba: np.ndarray) -> np.ndarray:
    """設定6 の確率 P[setting == 6]。"""
    validate_proba(proba)
    return proba[:, 5]


def compute_expected_setting(proba: np.ndarray) -> np.ndarray:
    """期待設定値 = Σ k * P(setting=k), k=1..6。"""
    validate_proba(proba)
    weights = np.arange(1, 7, dtype=float)
    return proba @ weights


def p_high_to_stars(p_high_max: float) -> int:
    """店内最大 p_high から ★ 評価 (1〜5) を算出。"""
    if p_high_max >= 0.70:
        return 5
    if p_high_max >= 0.55:
        return 4
    if p_high_max >= 0.40:
        return 3
    if p_high_max >= 0.25:
        return 2
    return 1
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/score.py (全面書き換え)
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/model/score.py"] = '''"""スコアリング関連: scoreA / base100 / 星評価 (Phase 1.5)。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_diff01(diff: pd.Series | np.ndarray, lo: float = -3000, hi: float = 5000) -> pd.Series:
    """差枚を 0.0〜1.0 にクリップ正規化。"""
    s = pd.Series(diff, dtype=float)
    s = s.clip(lower=lo, upper=hi)
    return (s - lo) / (hi - lo)


def compute_p4(setting: pd.Series | np.ndarray) -> pd.Series:
    """設定4以上ダミー。当日推定設定 >= 4 なら 1.0、それ未満なら 0.0。"""
    s = pd.Series(setting, dtype=float)
    return (s >= 4).astype(float)


def compute_score_a(
    p_high: pd.Series | np.ndarray,
    p_top: pd.Series | np.ndarray,
    diff01_prev: pd.Series | np.ndarray,
    w_high: float = 0.50,
    w_top: float = 0.30,
    w_prev: float = 0.20,
) -> pd.Series:
    """Phase 1.5 の scoreA = 0.50 * p_high + 0.30 * p_top + 0.20 * diff01_prev。"""
    ph = pd.Series(p_high, dtype=float)
    pt = pd.Series(p_top, dtype=float)
    dp = pd.Series(diff01_prev, dtype=float)
    return w_high * ph + w_top * pt + w_prev * dp


def compute_base100(
    p_win: pd.Series | np.ndarray,
    diff01: pd.Series | np.ndarray,
    p4: pd.Series | np.ndarray,
    w_pwin: float = 0.72,
    w_diff: float = 0.22,
    w_p4: float = 0.06,
) -> pd.Series:
    """既存指標 base100 = 100 * (0.72 p_win + 0.22 diff01 + 0.06 p4) (互換用)。"""
    pw = pd.Series(p_win, dtype=float)
    d = pd.Series(diff01, dtype=float)
    p = pd.Series(p4, dtype=float)
    return 100.0 * (w_pwin * pw + w_diff * d + w_p4 * p)


def base100_to_stars(base100_max: float) -> int:
    """[非推奨] base100 ベースの ★ 評価。互換のため残置。"""
    if base100_max >= 50:
        return 5
    if base100_max >= 42:
        return 4
    if base100_max >= 36:
        return 3
    if base100_max >= 30:
        return 2
    return 1
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/model/dataset.py への prev_setting / prev_p_high 追加パッチ
# ---------------------------------------------------------------------------
# 既存ファイルを読み込んで関数を追加・呼び出し箇所を編集する形にする
FILES["__patch_dataset__"] = '''"""dataset.py パッチ: prev_setting と prev_p_high 列を追加。

build_dataset.py 経由で再生成される際に新列を含むようにする。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "juggler_predictor" / "model" / "dataset.py"


def patch() -> None:
    src = TARGET.read_text(encoding="utf-8")

    marker_import = "from .setting_estimator import estimate_setting"
    if marker_import not in src:
        # 先頭の from import 群の後に追加
        lines = src.splitlines()
        insert_idx = 0
        for i, ln in enumerate(lines):
            if ln.startswith("from ") or ln.startswith("import "):
                insert_idx = i + 1
        lines.insert(insert_idx, marker_import)
        src = "\\n".join(lines) + "\\n"

    # add_prev_setting_features 関数を末尾に追加 (重複追加防止)
    if "def add_prev_setting_features(" not in src:
        helper = """

def add_prev_setting_features(df):
    \\"\\"\\"prev_setting / prev_p_high を groupby+shift で生成し付与。\\"\\"\\"
    import pandas as pd

    if "setting" not in df.columns:
        # 当日推定設定がまだ無い場合はここで計算
        def _est(row):
            return estimate_setting(
                composite_prob=row.get("composite_prob"),
                diff=row.get("diff", 0.0),
                machine_name=row.get("machine_name", ""),
            )

        df = df.copy()
        df["setting"] = df.apply(_est, axis=1).astype(int)

    df = df.sort_values(["shop_id", "unit_number", "date"]).copy()
    grp = df.groupby(["shop_id", "unit_number"], sort=False)
    df["prev_setting"] = grp["setting"].shift(1)
    df["prev_p_high"] = (df["prev_setting"] >= 4).astype("float")
    df["prev_setting"] = df["prev_setting"].fillna(3.0)
    df["prev_p_high"] = df["prev_p_high"].fillna(0.0)

    if "y_setting_next" not in df.columns:
        df["y_setting_next"] = grp["setting"].shift(-1)
    return df
"""
        src = src.rstrip() + helper + "\\n"

    # load_dataset_from_r2 の戻り値直前に add_prev_setting_features を呼び出す
    if "df = add_prev_setting_features(df)" not in src:
        # return df より前に挿入する単純なパターン: "    return df" を置換
        # 複数 return df があると壊れるので、最後の return df のみ置換
        target_line = "    return df"
        last_idx = src.rfind(target_line)
        if last_idx >= 0:
            new_block = "    df = add_prev_setting_features(df)\\n    return df"
            src = src[:last_idx] + new_block + src[last_idx + len(target_line):]

    TARGET.write_text(src, encoding="utf-8")
    print(f"[PATCH] {TARGET} updated (prev_setting / prev_p_high)")


if __name__ == "__main__":
    patch()
'''

# ---------------------------------------------------------------------------
# src/juggler_predictor/report/note_article.py (全面書き換え)
# ---------------------------------------------------------------------------
FILES["src/juggler_predictor/report/note_article.py"] = '''"""Note 記事 Markdown 生成 (Phase 1.5: 高設定期待度ベース)。"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from juggler_predictor.model.setting_predictor import p_high_to_stars

P_HIGH_GO_THRESHOLD = 0.50
GO_MIN_COUNT = 5


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
    n_high = int((rows["p_high"] >= P_HIGH_GO_THRESHOLD).sum())
    p_high_max = float(rows["p_high"].max())
    star = p_high_to_stars(p_high_max)
    is_go = n_high >= GO_MIN_COUNT

    parts: list[str] = []
    parts.append(_render_header(shop_display_name, target_date, input_date, star, is_go, n_high, n_total))
    parts.append(_render_summary(rows, n_high, n_total, p_high_max))
    parts.append(_render_top10(rows.head(10)))
    parts.append(_render_top1_reason(rows.iloc[0]))
    if not is_go:
        parts.append(_render_no_go(n_high, p_high_max))
    parts.append(_render_machine_detail(rows))
    parts.append(_render_disclaimer())
    return "\\n\\n".join(parts) + "\\n"


def _render_empty(shop: str, d: str) -> str:
    return f"# {shop} {d} の予測\\n\\n対象データがありません。\\n"


def _render_header(shop: str, d: str, input_d: str, star: int, is_go: bool, n_high: int, n_total: int) -> str:
    star_mark = "★" * star + "☆" * (5 - star)
    go_mark = "🟢 GO" if is_go else "🔴 NO-GO"
    return (
        f"# {shop} {d} 高設定期待度レポート\\n\\n"
        f"- 対象日: **{d}** (入力: {input_d} までの実績)\\n"
        f"- 注目度: **{star_mark}** ({star}/5)\\n"
        f"- 判定: **{go_mark}** (高設定期待台 {n_high}/{n_total} 台)"
    )


def _render_summary(rows: pd.DataFrame, n_high: int, n_total: int, p_high_max: float) -> str:
    pct = 100.0 * n_high / n_total if n_total else 0.0
    expected_mean = float(rows["expected_setting"].mean()) if "expected_setting" in rows else 0.0
    return (
        "## 📊 本日のサマリー\\n\\n"
        f"- 高設定期待台 (p_high ≥ {P_HIGH_GO_THRESHOLD:.2f}): **{n_high} / {n_total} 台 ({pct:.1f}%)**\\n"
        f"- 店内最大 p_high: **{p_high_max:.1%}**\\n"
        f"- 平均期待設定: **{expected_mean:.2f}**\\n"
        f"- GO/NO-GO 基準: 高設定期待台が {GO_MIN_COUNT} 台以上で GO"
    )


def _render_top10(top: pd.DataFrame) -> str:
    lines = ["## 🏆 推奨台 TOP10 (高設定期待度ランキング)\\n"]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, r in top.iterrows():
        m = medals.get(i, f"{i + 1}.")
        prev_diff = int(r.get("prev_diff", 0)) if pd.notna(r.get("prev_diff", 0)) else 0
        prev_set = int(r.get("prev_setting", 3)) if pd.notna(r.get("prev_setting", 3)) else 3
        lines.append(
            f"{m} **{int(r['unit_number'])}番台**({r['machine_name']}) — "
            f"設定4以上: **{r['p_high']:.0%}** / 設定5以上: {r['p_top']:.0%} / "
            f"設定6: {r['p_setting6']:.0%} / 期待設定: {r['expected_setting']:.2f}\\n"
            f"   - 前日実績: {prev_diff:+d}枚 (推定設定{prev_set}) / scoreA: {r['score_a']:.3f}"
        )
    return "\\n".join(lines)


def _render_top1_reason(top1: pd.Series) -> str:
    prev_diff = int(top1.get("prev_diff", 0)) if pd.notna(top1.get("prev_diff", 0)) else 0
    prev_set = int(top1.get("prev_setting", 3)) if pd.notna(top1.get("prev_setting", 3)) else 3
    return (
        "## 🎯 TOP1 推奨理由\\n\\n"
        f"**{int(top1['unit_number'])}番台 ({top1['machine_name']})** を最有力として推奨します。\\n\\n"
        f"- 設定4以上の確率が **{top1['p_high']:.1%}** と店内最高水準\\n"
        f"- 期待設定値 **{top1['expected_setting']:.2f}** (1〜6 のスコア)\\n"
        f"- 前日 {prev_diff:+d} 枚 / 推定設定{prev_set} の流れ"
    )


def _render_no_go(n_high: int, p_high_max: float) -> str:
    return (
        "## ⚠️ NO-GO 判定理由\\n\\n"
        f"- 高設定期待台が **{n_high} 台**しかなく、基準 {GO_MIN_COUNT} 台に届きません\\n"
        f"- 店内最大 p_high が {p_high_max:.1%} に留まる\\n"
        "- 本日の来店は見送り、別店舗の検討を推奨します"
    )


def _render_machine_detail(rows: pd.DataFrame) -> str:
    lines = ["## 🎰 機種別詳細\\n"]
    for machine, g in rows.groupby("machine_name"):
        g = g.sort_values("p_high", ascending=False)
        n = len(g)
        n_high = int((g["p_high"] >= P_HIGH_GO_THRESHOLD).sum())
        avg_p_high = float(g["p_high"].mean())
        lines.append(f"### {machine} ({n}台 / 高設定期待 {n_high}台 / 平均p_high {avg_p_high:.1%})\\n")
        for _, r in g.head(5).iterrows():
            prev_diff = int(r.get("prev_diff", 0)) if pd.notna(r.get("prev_diff", 0)) else 0
            lines.append(
                f"- {int(r['unit_number'])}番台: p_high {r['p_high']:.0%} / "
                f"期待設定 {r['expected_setting']:.2f} / 前日 {prev_diff:+d}枚"
            )
        lines.append("")
    return "\\n".join(lines)


def _render_disclaimer(): 
    return (
        "## 📝 注意事項\\n\\n"
        "本記事の「設定期待度」は当方の推定モデルによる確率値であり、"
        "実際の設定を保証するものではありません。"
        "設定は各店舗の店長のみが知る情報であり、本予測は過去の差枚・合成確率の傾向に基づく統計的推定です。\\n\\n"
        "立ち回りの参考としてご活用いただき、最終的な投資判断はご自身でお願いします。"
    )
'''

# ---------------------------------------------------------------------------
# scripts/generate_article.py (全面書き換え)
# ---------------------------------------------------------------------------
FILES["scripts/generate_article.py"] = '''"""Phase 1.5: 高設定期待度ベースの記事生成 CLI。

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
    target = df[(df["shop_id"] == args.shop) & (df["date"] == input_date_str)].copy()
    logger.info("rows=%d for shop=%s date=%s", len(target), args.shop, input_date_str)
    if target.empty:
        raise SystemExit(f"対象データなし: shop={args.shop} date={input_date_str}")

    bundle = joblib.load(BUNDLE)
    if "setting_classifier" not in bundle:
        raise SystemExit("setting_classifier が bundle にありません。train_setting.py を実行してください。")
    clf = bundle["setting_classifier"]
    feat_setting = bundle.get("setting_features", bundle["feature_cols"])

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
'''
# ---------------------------------------------------------------------------
# tests/test_setting_predictor.py
# ---------------------------------------------------------------------------
FILES["tests/test_setting_predictor.py"] = '''"""setting_predictor のユニットテスト。"""
from __future__ import annotations

import numpy as np
import pytest

from juggler_predictor.model.setting_predictor import (
    compute_expected_setting,
    compute_p_high,
    compute_p_setting6,
    compute_p_top,
    p_high_to_stars,
    validate_proba,
)


def test_validate_proba_ok():
    proba = np.full((3, 6), 1 / 6)
    validate_proba(proba)  # no raise


def test_validate_proba_bad_shape():
    with pytest.raises(ValueError):
        validate_proba(np.zeros((3, 5)))
    with pytest.raises(ValueError):
        validate_proba(np.zeros(6))


def test_compute_p_high_uniform():
    proba = np.full((1, 6), 1 / 6)
    assert compute_p_high(proba)[0] == pytest.approx(0.5, rel=1e-6)


def test_compute_p_top_uniform():
    proba = np.full((1, 6), 1 / 6)
    assert compute_p_top(proba)[0] == pytest.approx(2 / 6, rel=1e-6)


def test_compute_p_setting6():
    proba = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 1.0]])
    assert compute_p_setting6(proba)[0] == pytest.approx(1.0)


def test_compute_expected_setting_uniform():
    proba = np.full((1, 6), 1 / 6)
    # E[setting] = (1+2+3+4+5+6)/6 = 3.5
    assert compute_expected_setting(proba)[0] == pytest.approx(3.5, rel=1e-6)


def test_compute_expected_setting_concentrated():
    # 設定6 確率 1.0 → E = 6.0
    proba = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 1.0]])
    assert compute_expected_setting(proba)[0] == pytest.approx(6.0)


def test_p_high_to_stars_thresholds():
    assert p_high_to_stars(0.80) == 5
    assert p_high_to_stars(0.70) == 5
    assert p_high_to_stars(0.60) == 4
    assert p_high_to_stars(0.55) == 4
    assert p_high_to_stars(0.45) == 3
    assert p_high_to_stars(0.40) == 3
    assert p_high_to_stars(0.30) == 2
    assert p_high_to_stars(0.25) == 2
    assert p_high_to_stars(0.10) == 1
    assert p_high_to_stars(0.00) == 1
'''

# ---------------------------------------------------------------------------
# tests/test_score.py に新閾値テスト追加 (既存テストは置き換え)
# ---------------------------------------------------------------------------
FILES["tests/test_score.py"] = '''"""score.py のユニットテスト (Phase 1.5 仕様)。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from juggler_predictor.model.score import (
    base100_to_stars,
    compute_base100,
    compute_diff01,
    compute_p4,
    compute_score_a,
)


def test_compute_diff01_clip():
    s = pd.Series([-5000, -3000, 0, 5000, 10000])
    out = compute_diff01(s)
    assert out.iloc[0] == pytest.approx(0.0)
    assert out.iloc[1] == pytest.approx(0.0)
    assert out.iloc[3] == pytest.approx(1.0)
    assert out.iloc[4] == pytest.approx(1.0)
    # 0 は (0 - (-3000))/(5000 - (-3000)) = 0.375
    assert out.iloc[2] == pytest.approx(0.375, rel=1e-6)


def test_compute_p4():
    s = pd.Series([1, 2, 3, 4, 5, 6])
    out = compute_p4(s)
    assert list(out) == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]


def test_compute_score_a_weights():
    p_high = pd.Series([1.0, 0.0])
    p_top = pd.Series([0.0, 1.0])
    diff01 = pd.Series([0.0, 0.0])
    out = compute_score_a(p_high, p_top, diff01)
    # row0: 0.50*1 + 0.30*0 + 0.20*0 = 0.50
    # row1: 0.50*0 + 0.30*1 + 0.20*0 = 0.30
    assert out.iloc[0] == pytest.approx(0.50)
    assert out.iloc[1] == pytest.approx(0.30)


def test_compute_score_a_full():
    p_high = pd.Series([1.0])
    p_top = pd.Series([1.0])
    diff01 = pd.Series([1.0])
    out = compute_score_a(p_high, p_top, diff01)
    assert out.iloc[0] == pytest.approx(1.0)


def test_compute_base100_legacy():
    p_win = pd.Series([0.5])
    diff01 = pd.Series([0.5])
    p4 = pd.Series([1.0])
    out = compute_base100(p_win, diff01, p4)
    # 100 * (0.72*0.5 + 0.22*0.5 + 0.06*1) = 100 * (0.36 + 0.11 + 0.06) = 53.0
    assert out.iloc[0] == pytest.approx(53.0)


def test_stars_thresholds():
    # Phase 1 暫定閾値 (50/42/36/30) 互換
    assert base100_to_stars(70.0) == 5
    assert base100_to_stars(50.0) == 5
    assert base100_to_stars(45.0) == 4
    assert base100_to_stars(42.0) == 4
    assert base100_to_stars(38.0) == 3
    assert base100_to_stars(33.0) == 2
    assert base100_to_stars(25.0) == 1
'''

# ---------------------------------------------------------------------------
# tests/test_note_article.py (Phase 1.5 仕様で書き換え)
# ---------------------------------------------------------------------------
FILES["tests/test_note_article.py"] = '''"""note_article.py のユニットテスト (Phase 1.5)。"""
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
'''


# ---------------------------------------------------------------------------
# write_all + dataset patch 実行
# ---------------------------------------------------------------------------
def write_all() -> None:
    written = 0
    patched = 0
    for rel, content in FILES.items():
        if rel == "__patch_dataset__":
            # patch スクリプトを一時実行
            tmp = ROOT / "_patch_dataset_tmp.py"
            tmp.write_text(content, encoding="utf-8")
            print(f"[PATCH] running dataset.py patch via {tmp}")
            import runpy
            try:
                runpy.run_path(str(tmp), run_name="__main__")
                patched += 1
            finally:
                if tmp.exists():
                    tmp.unlink()
            continue
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"[WRITE] {path} ({len(content)} bytes)")
        written += 1
    print(f"[SUCCESS] wrote {written} files, applied {patched} patches")


if __name__ == "__main__":
    write_all()

