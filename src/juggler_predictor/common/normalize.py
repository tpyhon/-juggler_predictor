"""機種名・台番号などの表記ゆれ吸収."""
from __future__ import annotations

import re
import unicodedata

# ローマ数字 -> アラビア数字
_ROMAN_MAP = str.maketrans({
    "Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5",
    "Ⅵ": "6", "Ⅶ": "7", "Ⅷ": "8", "Ⅸ": "9", "Ⅹ": "10",
})


def _basic_normalize(s: str) -> str:
    """NFKC + ローマ数字変換 + 空白除去 + 大文字統一."""
    s = unicodedata.normalize("NFKC", s).translate(_ROMAN_MAP)
    s = re.sub(r"\s+", "", s)
    return s.upper()


def normalize_machine_name(name: str, aliases_map: dict[str, str] | None = None) -> str:
    """機種名を正準名に正規化. マッチしなければ元の文字列."""
    if not name:
        return ""
    key = _basic_normalize(name)
    if aliases_map:
        for alias_key, canonical in aliases_map.items():
            if _basic_normalize(alias_key) == key:
                return canonical
    return name.strip()


def normalize_unit_number(s: str | int) -> str:
    """台番号. '0123' / '123番' / '#123' -> '123'."""
    if isinstance(s, int):
        return str(s)
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    m = re.search(r"\d+", s)
    return m.group(0) if m else s.strip()


def is_juggler(machine_name: str, whitelist_canonical: set[str]) -> bool:
    """ホワイトリストに含まれるか."""
    return machine_name in whitelist_canonical


def build_alias_map(machines_config: list[dict]) -> dict[str, str]:
    """machines.yaml の構造から {alias: canonical} のフラットマップを作る."""
    out: dict[str, str] = {}
    for m in machines_config:
        canonical = m["canonical"]
        out[canonical] = canonical
        for alias in m.get("aliases", []):
            out[alias] = canonical
    return out
