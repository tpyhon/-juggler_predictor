# setup_p3b_part1_fix.py
"""build_features: target_diff の NaN を target_win 計算の前に drop"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
target = ROOT / "src" / "juggler_predictor" / "model" / "features.py"

src = target.read_text(encoding="utf-8")

# 修正前のブロック（推定）:
#     out["target_diff"] = ...
#     out["target_win"] = (out["target_diff"] > TARGET_DIFF_THRESHOLD).astype(np.int8)
#     out = out.dropna(subset=["target_diff"])
#
# 修正後:
#     out["target_diff"] = ...
#     out = out.dropna(subset=["target_diff"]).reset_index(drop=True)
#     out["target_win"] = (out["target_diff"] > TARGET_DIFF_THRESHOLD).astype(np.int8)

old = 'out["target_win"] = (out["target_diff"] > TARGET_DIFF_THRESHOLD).astype(np.int8)'
new = (
    'out = out.dropna(subset=["target_diff"]).reset_index(drop=True)\n'
    '    out["target_win"] = (out["target_diff"] > TARGET_DIFF_THRESHOLD).astype(np.int8)'
)

if old not in src:
    print("[ERROR] 想定行が見つかりません。features.py の現在内容を確認してください。")
    print("該当箇所付近を表示します:")
    for i, line in enumerate(src.splitlines(), 1):
        if "target_win" in line or "target_diff" in line or "dropna" in line:
            print(f"  {i:4d}: {line}")
    raise SystemExit(1)

# 既に dropna が target_win より後ろにある場合のみ置換
patched = src.replace(old, new, 1)

# 旧 dropna 行（target_win 計算後にあるもの）を削除
import re
patched = re.sub(
    r'\n\s*out = out\.dropna\(subset=\["target_diff"\]\)\.reset_index\(drop=True\)\s*\n',
    '\n',
    patched,
    count=1,
)
# もし上の sub が末尾で 2 個目を消したケースの保険（前述で先に挿入済の方は残す）
# シンプル化: 重複行があれば 1 個に縮約
patched = re.sub(
    r'(out = out\.dropna\(subset=\["target_diff"\]\)\.reset_index\(drop=True\)\n)(\s*out = out\.dropna\(subset=\["target_diff"\]\)\.reset_index\(drop=True\)\n)',
    r'\1',
    patched,
)

target.write_text(patched, encoding="utf-8")
print(f"[WRITE] {target}")
print("[DONE] features.py を修正しました")
