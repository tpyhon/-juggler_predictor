# setup_p3b_part1_fix2.py
"""build_features: target_win 計算前に NaN drop、fillna(False) で堅牢化"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
target = ROOT / "src" / "juggler_predictor" / "model" / "features.py"

src = target.read_text(encoding="utf-8")

# ===== Patch 1: target_diff 計算直後に dropna ブロックを移動 =====
old_block = '''    # ターゲット
    out["target_diff"] = out["diff"].astype("Float64")
    out["target_win"] = (out["target_diff"] > TARGET_DIFF_THRESHOLD).astype(np.int8)

    # date 列を datetime 化 (split のため)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")'''

new_block = '''    # ターゲット
    out["target_diff"] = out["diff"].astype("Float64")

    # target_diff が NaN の行は target_win 計算前に除去 (Float64 -> int8 変換のため)
    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除去", dropped)

    # target_win: NaN は False として扱う (drop_na_target=False の場合の保険)
    out["target_win"] = (
        (out["target_diff"] > TARGET_DIFF_THRESHOLD).fillna(False).astype(np.int8)
    )

    # date 列を datetime 化 (split のため)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y-%m-%d", errors="coerce")'''

if old_block not in src:
    print("[ERROR] 想定ブロックが見つかりません。features.py の中身を確認してください。")
    raise SystemExit(1)

src = src.replace(old_block, new_block, 1)

# ===== Patch 2: 元々あった末尾の if drop_na_target ブロックを削除 =====
old_tail = '''    if drop_na_target:
        before = len(out)
        out = out[out["target_diff"].notna()].copy()
        dropped = before - len(out)
        if dropped:
            logger.info("target_diff が NaN の %d 行を除去", dropped)

    meta = FeatureMeta('''

new_tail = '''    meta = FeatureMeta('''

if old_tail not in src:
    print("[ERROR] 末尾の dropna ブロックが見つかりません。")
    raise SystemExit(1)

src = src.replace(old_tail, new_tail, 1)

target.write_text(src, encoding="utf-8")
print(f"[WRITE] {target}")
print("[DONE] features.py を修正しました")
print()
print("修正内容:")
print("  1. target_diff の NaN drop を target_win 計算より前に移動")
print("  2. target_win 計算に .fillna(False) を追加（drop_na_target=False の保険）")
