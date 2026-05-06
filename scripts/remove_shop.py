"""廃業店舗を shops.yaml と policies.json から除去する。

使い方:
    uv run python scripts/remove_shop.py --shop granpaOkubo
"""
from __future__ import annotations

import argparse
import json
import sys

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR
from juggler_predictor.common.logging import setup_logging


def main() -> int:
    setup_logging()
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True, help="削除する shop id")
    args = ap.parse_args()

    target_id = args.shop

    # 1. shops.yaml
    shops_path = CONFIG_DIR / "shops.yaml"
    raw = yaml.safe_load(shops_path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("shops", [])
    before = len(items)
    new_items = [s for s in items if s.get("id") != target_id]
    after = len(new_items)
    if before == after:
        print(f"[INFO] shops.yaml に {target_id} は存在しません (既に削除済み)")
    else:
        if isinstance(raw, list):
            shops_path.write_text(
                yaml.safe_dump(new_items, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        else:
            raw["shops"] = new_items
            shops_path.write_text(
                yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        print(f"[OK] shops.yaml: {target_id} を削除 ({before} -> {after})")

    # 2. policies.json
    pol_path = CONFIG_DIR / "policies.json"
    if pol_path.exists():
        pol = json.loads(pol_path.read_text(encoding="utf-8"))
        if isinstance(pol, dict) and target_id in pol:
            del pol[target_id]
            pol_path.write_text(
                json.dumps(pol, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[OK] policies.json: {target_id} を削除")
        else:
            print(f"[INFO] policies.json に {target_id} は存在しません")

    print()
    print("[DONE] 廃業店舗の除去が完了しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
