"""
Note 記事を非公式 API 経由で投稿する (メンバーシップ + 公開まで全自動)。

使い方:
  # ローカル動作確認
  $env:NOTE_SESSION_V5 = "xxxxx"
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --shop espas_ueno --dry-run
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --shop espas_ueno --draft-only
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --shop espas_ueno
  uv run python scripts/post_articles_via_api.py --date 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from juggler_predictor.note.markdown_to_html import markdown_to_note_html  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NOTE_API = "https://note.com/api"
ORIGIN = "https://editor.note.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
)

# 店舗 yaml の note_plans (master, shinjuku_shibuya_ikebukuro 等) → note 実プラン名
PLAN_NAME_MAP = {
    "master": "東京マスタープラン",
    "shinjuku_shibuya_ikebukuro": "新宿・渋谷・池袋プラン",
    "saitama_chiba_kanagawa": "埼玉・千葉・神奈川プラン",
    "other_kanto": "関東以外プラン",
    "nationwide": "全国津々浦々プラン",
}


def get_session_cookie() -> str:
    cookie = os.environ.get("NOTE_SESSION_V5")
    if cookie:
        logger.info("環境変数 NOTE_SESSION_V5 から cookie を取得")
        return cookie.strip()
    state_path = Path(os.environ.get("NOTE_STORAGE_STATE", "auth/note_storage_state.json"))
    if state_path.exists():
        logger.info(f"{state_path} から cookie を取得")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for c in state.get("cookies", []):
            if c.get("name") == "_note_session_v5":
                return c["value"]
    # R2 フォールバック
    logger.info("R2 から auth/note_storage_state.json を取得")
    from juggler_predictor.storage.r2 import build_r2_client_from_env
    r2 = build_r2_client_from_env()
    obj = r2._client.get_object(Bucket=r2.config.bucket, Key="auth/note_storage_state.json")
    state = json.loads(obj["Body"].read().decode("utf-8"))
    for c in state.get("cookies", []):
        if c.get("name") == "_note_session_v5":
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            return c["value"]
    raise RuntimeError("_note_session_v5 が取得できません")


def build_session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "*/*",
        "Accept-Language": "ja,en;q=0.9,en-GB;q=0.8,en-US;q=0.7",
        "Content-Type": "application/json",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
    })
    s.cookies.set("_note_session_v5", cookie, domain=".note.com")
    return s


def create_text_note(s: requests.Session) -> dict:
    res = s.post(f"{NOTE_API}/v1/text_notes", json={"template_key": None}, timeout=30)
    res.raise_for_status()
    data = res.json()["data"]
    return {"id": data["id"], "key": data["key"], "slug": data.get("slug", f"slug-{data['key']}")}


def save_draft(s: requests.Session, note_id: int, title: str, body_html: str) -> None:
    res = s.post(
        f"{NOTE_API}/v1/text_notes/draft_save",
        params={"id": str(note_id), "is_temp_saved": "true"},
        json={
            "body": body_html,
            "body_length": len(body_html),
            "name": title,
            "index": False,
            "is_lead_form": False,
        },
        timeout=30,
    )
    res.raise_for_status()


def get_circle_plans(s: requests.Session, note_key: str) -> list[dict]:
    """サークルプラン一覧を {key, name} のリストで返す。"""
    res = s.get(
        f"{NOTE_API}/v3/memberships/circle_permissions",
        params={"note_key": note_key},
        timeout=30,
    )
    res.raise_for_status()
    data = res.json()["data"]
    plans = []
    for circle_entry in data:
        for plan in circle_entry.get("circle_plans", []):
            plans.append({"key": plan["key"], "name": plan["name"]})
    return plans


def resolve_plan_keys(available_plans: list[dict], shop_plan_names: list[str]) -> list[str]:
    """店舗の note_plans (例: ['master', 'shinjuku_shibuya_ikebukuro']) を実 key に変換。"""
    keys = []
    for shop_plan in shop_plan_names:
        target_name = PLAN_NAME_MAP.get(shop_plan, shop_plan)
        match = next((p for p in available_plans if p["name"] == target_name), None)
        if match is None:
            logger.warning(
                f"プラン名 '{target_name}' が note 上に見つかりません "
                f"(利用可能: {[p['name'] for p in available_plans]})"
            )
            continue
        keys.append(match["key"])
    return keys


def publish(
    s: requests.Session,
    note_id: int,
    note_key: str,
    note_slug: str,
    title: str,
    body_html: str,
    circle_plan_keys: list[str],
) -> dict:
    """記事を公開する (メンバーシップ限定、無料、クリエイターページ非表示)。"""
    separator = str(uuid.uuid4())
    payload = {
        "author_ids": [],
        "body_length": len(body_html),
        "disable_comment": False,
        "exclude_from_creator_top": True,  # クリエイターページに表示 OFF
        "exclude_ai_learning_reward": False,
        "free_body": body_html,
        "hashtags": [],
        "image_keys": [],
        "index": False,
        "is_refund": False,
        "limited": False,
        "magazine_ids": [],
        "magazine_keys": [],
        "name": title,
        "pay_body": "",
        "price": 0,
        "send_notifications_flag": True,
        "separator": separator,
        "slug": note_slug,
        "status": "published",
        "circle_permissions": (
            [{"kind": "circle_plan", "keys": circle_plan_keys}]
            if circle_plan_keys else []
        ),
        "discount_campaigns": [],
        "lead_form": {"is_active": False, "consent_url": ""},
        "line_add_friend": {"is_active": False, "keyword": "", "add_friend_url": ""},
        "line_add_friend_access_token": "",
        "pro_coupon_keys": [],
    }
    res = s.put(f"{NOTE_API}/v1/text_notes/{note_id}", json=payload, timeout=60)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"publish 失敗: status={res.status_code} body={res.text[:500]}")
    return res.json()


def load_shops() -> list[dict]:
    with open(ROOT / "config" / "shops.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    shops = data.get("shops", data) if isinstance(data, dict) else data
    return [s for s in shops if s.get("active", True)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="投稿対象日 YYYY-MM-DD")
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--shop", default=None, help="単一店舗のみ (動作確認用)")
    ap.add_argument("--draft-only", action="store_true", help="下書き保存のみ (公開しない)")
    ap.add_argument("--dry-run", action="store_true", help="API は呼ばずに対象一覧のみ表示")
    args = ap.parse_args()

    cookie = get_session_cookie()
    session = build_session(cookie)

    shops = load_shops()
    if args.shop:
        shops = [s for s in shops if s["id"] == args.shop]
    if not shops:
        logger.error("対象店舗がありません")
        return 1

    mode = "dry-run" if args.dry_run else ("draft" if args.draft_only else "publish")
    logger.info(f"対象: {len(shops)} 店舗 / 日付: {args.date} / mode: {mode}")

    success = 0
    failure = 0
    results = []
    for i, shop in enumerate(shops, 1):
        shop_id = shop["id"]
        shop_display = shop.get("display_name", shop_id)
        shop_plans = shop.get("note_plans", ["master"])
        md_path = ROOT / "reports" / f"{shop_id}_{args.date}.md"
        if not md_path.exists():
            logger.warning(f"[SKIP] {shop_id}: {md_path.name} なし")
            failure += 1
            continue

        body_html = markdown_to_note_html(md_path.read_text(encoding="utf-8"))
        title = f"【{args.date}】{shop_display}"

        if args.dry_run:
            logger.info(f"[DRY] {shop_id}: title={title} plans={shop_plans} body_len={len(body_html)}")
            success += 1
            continue

        logger.info(f"[{i}/{len(shops)}] {shop_id} ({shop_display}) plans={shop_plans} 投稿中...")
        try:
            note = create_text_note(session)
            save_draft(session, note["id"], title, body_html)

            if args.draft_only:
                logger.info(f"[OK draft] {shop_id} -> https://editor.note.com/notes/{note['id']}/edit")
            else:
                available = get_circle_plans(session, note["key"])
                plan_keys = resolve_plan_keys(available, shop_plans)
                if not plan_keys:
                    raise RuntimeError(f"プラン解決失敗: shop_plans={shop_plans}")
                publish(
                    session, note["id"], note["key"], note["slug"],
                    title, body_html, plan_keys,
                )
                logger.info(f"[OK published] {shop_id} -> https://note.com/notes/{note['key']}")

            results.append({
                "shop": shop_id,
                "id": note["id"],
                "key": note["key"],
                "title": title,
                "plan_keys": plan_keys if not args.draft_only else None,
            })
            success += 1
        except Exception as e:
            logger.error(f"[FAIL] {shop_id}: {e}")
            failure += 1

        if i < len(shops):
            time.sleep(args.sleep)

    log_path = ROOT / "logs" / f"post_via_api_{args.date}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("=" * 60)
    logger.info(f"[POST SUMMARY] success={success} / failure={failure}")
    logger.info(f"結果ログ: {log_path}")
    logger.info("=" * 60)
    return 0 if failure == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
