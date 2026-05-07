# setup_p3b_part2_fix.py
"""test_train_handles_small_classes: train/valid 両方に両クラスを含める"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
target = ROOT / "tests" / "test_model_train.py"

src = target.read_text(encoding="utf-8")

old = '''def test_train_handles_small_classes():
    """片方のクラスがほとんど無い場合でもエラーで落ちないこと。"""
    df = _make_synthetic_df(400, seed=7)
    # 強制的に win=0 を多くする
    df.loc[df.index[:380], "target_win"] = 0
    df.loc[df.index[380:], "target_win"] = 1
    train_df = df.iloc[:300].copy()
    valid_df = df.iloc[300:].copy()
    # cv=2 で OK
    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)
    assert result.classifier_calibrated is not None'''

new = '''def test_train_handles_small_classes():
    """片方のクラスが極端に少ない不均衡データでもエラーで落ちないこと。

    train/valid ともに両クラスを含むようにシャッフルしてから分割する。
    """
    import numpy as np

    df = _make_synthetic_df(400, seed=7)
    # 強制的に不均衡にする (約 95% を win=0、5% を win=1)
    df["target_win"] = 0
    rng = np.random.default_rng(42)
    win_idx = rng.choice(df.index, size=20, replace=False)
    df.loc[win_idx, "target_win"] = 1

    # シャッフルして両クラスが train/valid 両方に入るようにする
    df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
    train_df = df.iloc[:300].copy()
    valid_df = df.iloc[300:].copy()

    # 両方に両クラスが存在することを確認 (テスト前提)
    assert train_df["target_win"].nunique() == 2
    assert valid_df["target_win"].nunique() == 2

    # cv=2 で学習が走り、エラーで落ちないこと
    result = train_models(train_df, valid_df, FEATURE_COLS, calibration_cv=2)
    assert result.classifier_calibrated is not None'''

if old not in src:
    print("[ERROR] 想定ブロックが見つかりません。test_model_train.py の現在内容を確認してください。")
    raise SystemExit(1)

src = src.replace(old, new, 1)
target.write_text(src, encoding="utf-8")
print(f"[WRITE] {target}")
print("[DONE] test_train_handles_small_classes を修正しました")
