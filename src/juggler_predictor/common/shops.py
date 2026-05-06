"""shops.yaml ローダー."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from juggler_predictor import CONFIG_DIR


@dataclass(frozen=True)
class Shop:
    id: str
    display_name: str
    prefecture: str
    region: str
    note_plans: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict) -> "Shop":
        return cls(
            id=d["id"],
            display_name=d["display_name"],
            prefecture=d["prefecture"],
            region=d["region"],
            note_plans=tuple(d.get("note_plans", [])),
        )


@lru_cache(maxsize=1)
def load_shops(path: Path | None = None) -> list[Shop]:
    p = path or (CONFIG_DIR / "shops.yaml")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    shops = [Shop.from_dict(d) for d in raw]
    ids = [s.id for s in shops]
    if len(ids) != len(set(ids)):
        dup = [i for i in ids if ids.count(i) > 1]
        raise ValueError(f"shops.yaml に重複した id があります: {set(dup)}")
    return shops


def get_shop(shop_id: str) -> Shop:
    for s in load_shops():
        if s.id == shop_id:
            return s
    raise KeyError(f"shop_id 不明: {shop_id}")


def shops_by_region(region: str) -> list[Shop]:
    return [s for s in load_shops() if s.region == region]


def shops_by_prefecture(prefecture: str) -> list[Shop]:
    return [s for s in load_shops() if s.prefecture == prefecture]


def all_shop_ids() -> list[str]:
    return [s.id for s in load_shops()]
