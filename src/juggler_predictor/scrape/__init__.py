"""スクレイピング層パッケージ。

ana-slo.com からホールデータを取得し、機種ごとの台データに変換するモジュール群。
"""
from juggler_predictor.scrape.parser import (
    MachineRow,
    ParsedPage,
    parse_ana_slo_html,
)

__all__ = [
    "MachineRow",
    "ParsedPage",
    "parse_ana_slo_html",
]
