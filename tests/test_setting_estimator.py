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
