"""東京一覧ページから店舗 slug を取得し、shops.yaml に書き戻す。

shops.yaml は以下のいずれかの形式に対応:
    a) トップレベル list:        [{id: ..., display_name: ...}, ...]
    b) トップレベル dict:        {shops: [{id: ..., ...}, ...]}

使い方:
    uv run python scripts/collect_shop_slugs.py            # ドライラン
    uv run python scripts/collect_shop_slugs.py --apply    # 実際に書き戻す
"""
from __future__ import annotations

import argparse
import logging
import sys

import yaml
from dotenv import load_dotenv

from juggler_predictor import CONFIG_DIR
from juggler_predictor.common.logging import setup_logging
from juggler_predictor.scrape.ana_slo import AnaSloUrls
from juggler_predictor.scrape.http_client import AnaSloHTTPClient
from juggler_predictor.scrape.shop_slug_collector import (
    ShopCandidate,
    extract_shop_candidates,
)
from juggler_predictor.storage import R2Paths, build_r2_client_from_env

logger = logging.getLogger(__name__)


def _read_shops_doc(path) -> tuple[list[dict], object]:
    """shops.yaml を読み、 (shops_list, original_doc) を返す。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc, doc
    if isinstance(doc, dict) and isinstance(doc.get("shops"), list):
        return doc["shops"], doc
    raise RuntimeError(f"shops.yaml の形式が不明: top={type(doc)}")


def _write_shops_doc(path, original_doc, shops_list: list[dict]) -> None:
    """元の構造を保ったまま書き戻す。"""
    if isinstance(original_doc, list):
        out = shops_list
    else:
        original_doc["shops"] = shops_list
        out = original_doc
    path.write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> int:
    setup_logging()
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="shops.yaml を実際に書き換える")
    args = parser.parse_args()

    logger.info("[1] R2 からクッキーを取得")
    r2 = build_r2_client_from_env()
    payload = r2.get_json(R2Paths.cf_cookie_latest())
    cookies = payload.get("cookies", [])
    ua = payload.get("user_agent")
    logger.info("cookies=%d ua_len=%d", len(cookies), len(ua or ""))

    logger.info("[2] 東京一覧ページ GET")
    client = AnaSloHTTPClient(cookies=cookies, user_agent=ua)
    urls = AnaSloUrls()
    html = client.get(urls.tokyo_index(), referer=urls.home())
    logger.info("html size=%d", len(html))

    candidates = extract_shop_candidates(html)
    logger.info("候補数: %d", len(candidates))
    print()
    print("=== 抽出された候補 (先頭 30 件) ===")
    for c in candidates[:30]:
        print(f"  {c.display_name:35s}  ward={c.ward or '-':6s}  slug={c.slug}")
    print()

    shops_path = CONFIG_DIR / "shops.yaml"
    shops, doc = _read_shops_doc(shops_path)

    matched, unmatched = _match_slugs(shops, candidates)

    print("=" * 60)
    print(f"[結果] matched={len(matched)} / unmatched={len(unmatched)} / total={len(shops)}")
    print("=" * 60)
    for sid, slug in matched:
        print(f"  OK  {sid:30s} -> {slug}")
    for sid in unmatched:
        print(f"  --  {sid:30s} (slug が見つからず)")

    if not args.apply:
        print()
        print("[INFO] ドライラン。--apply で書き戻し。")
        return 0

    matched_map = dict(matched)
    for shop in shops:
        sid = shop.get("id")
        if sid in matched_map:
            shop["slug"] = matched_map[sid]
    _write_shops_doc(shops_path, doc, shops)
    logger.info("[SUCCESS] shops.yaml を更新しました: %s", shops_path)
    return 0


def _match_slugs(
    shops: list[dict], candidates: list[ShopCandidate]
) -> tuple[list[tuple[str, str]], list[str]]:
    """display_name から slug を割り当てる。"""
    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for shop in shops:
        sid = shop.get("id", "")
        name = shop.get("display_name", "")
        hit: str | None = None

        # 段階的に緩和してマッチ
        for c in candidates:
            if c.display_name == name:
                hit = c.slug
                break
        if hit is None:
            simp_name = _simplify(name)
            for c in candidates:
                if _simplify(c.display_name) == simp_name:
                    hit = c.slug
                    break
        if hit is None:
            simp_name = _simplify(name)
            for c in candidates:
                if simp_name and simp_name in _simplify(c.slug):
                    hit = c.slug
                    break
        if hit is None:
            simp_name = _simplify(name)
            for c in candidates:
                if simp_name and _simplify(c.display_name) and (
                    simp_name in _simplify(c.display_name)
                    or _simplify(c.display_name) in simp_name
                ):
                    hit = c.slug
                    break

        if hit:
            matched.append((sid, hit))
        else:
            unmatched.append(sid)
    return matched, unmatched


def _simplify(s: str) -> str:
    return (
        s.replace("No.", "no")
        .replace("NO.", "no")
        .replace(".", "")
        .replace(" ", "")
        .replace("　", "")
        .replace("・", "")
        .lower()
    )


if __name__ == "__main__":
    sys.exit(main())
