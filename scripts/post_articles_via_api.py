"""
Note 記事を非公式 API 経由で投稿する (メンバーシップ + 公開まで全自動)。

使い方:
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --shop espas_ueno --dry-run
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --shop espas_ueno --draft-only
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --shop espas_ueno
  uv run python scripts/post_articles_via_api.py --date 2026-05-08
  uv run python scripts/post_articles_via_api.py --date 2026-05-08 --resume  # 途中から再開
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
from dotenv import load_dotenv
load_dotenv()


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

PLAN_NAME_MAP = {
    "master": "東京マスタープラン",
    "shinjuku_shibuya_ikebukuro": "新宿・渋谷・池袋プラン",
    "saitama_chiba_kanagawa": "埼玉・千葉・神奈川プラン",
    "other_kanto": "関東以外プラン",
    "nationwide": "全国津々浦々プラン",
}

# rate limit 判定: これらの HTTP ステータスはリトライ対象
_RATE_LIMIT_STATUSES = {422, 429, 503}
# 422 はすべてリトライ対象ではないためキーワードで絞る
_RATE_LIMIT_KEYWORDS = ["しばらく時間をあけて", "too many", "rate limit", "slow down"]


def _is_rate_limit(e: Exception) -> bool:
    """レート制限エラーかどうかを判定する。"""
    if isinstance(e, requests.exceptions.HTTPError):
        resp = e.response
        if resp is None:
            return False
        status = resp.status_code
        if status in (429, 503):
            return True
        if status == 422:
            try:
                body_text = resp.json().get("message", "") or resp.text
            except Exception:
                body_text = resp.text
            return any(kw in body_text for kw in _RATE_LIMIT_KEYWORDS)
    if isinstance(e, RuntimeError):
        msg = str(e)
        if "status=422" in msg:
            return any(kw in msg for kw in _RATE_LIMIT_KEYWORDS)
    return False


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
    separator = str(uuid.uuid4())
    payload = {
        "author_ids": [],
        "body_length": len(body_html),
        "disable_comment": False,
        "exclude_from_creator_top": True,
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


def _load_resume_log(log_path: Path, target_date: str) -> tuple[list[dict], set[str]]:
    """投稿済みログをローカル → R2 の順で取得。(results, posted_shop_ids) を返す。"""
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
            posted = {r["shop"] for r in existing if r.get("shop") and r.get("key")}
            logger.info("resume: ローカルログ読み込み (%d 件投稿済み)", len(posted))
            return existing, posted
        except Exception as e:
            logger.warning("resume: ローカルログ読み込み失敗: %s", e)

    try:
        from juggler_predictor.storage.r2 import build_r2_client_from_env
        r2 = build_r2_client_from_env()
        obj = r2._client.get_object(
            Bucket=r2.config.bucket, Key=f"post_logs/{target_date}.json"
        )
        existing = json.loads(obj["Body"].read().decode("utf-8"))
        posted = {r["shop"] for r in existing if r.get("shop") and r.get("key")}
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("resume: R2 ログ読み込み (%d 件投稿済み)", len(posted))
        return existing, posted
    except Exception as e:
        logger.info("resume: R2 ログなし (%s) → 全件投稿", e)
        return [], set()


def _save_log(log_path: Path, results: list[dict]) -> None:
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def _upload_log_to_r2(log_path: Path, target_date: str) -> None:
    try:
        from juggler_predictor.storage.r2 import build_r2_client_from_env
        r2 = build_r2_client_from_env()
        r2._client.put_object(
            Bucket=r2.config.bucket,
            Key=f"post_logs/{target_date}.json",
            Body=log_path.read_bytes(),
            ContentType="application/json",
        )
        logger.info("投稿ログを R2 にアップロード: post_logs/%s.json", target_date)
    except Exception as e:
        logger.warning("R2 アップロード失敗 (続行): %s", e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="投稿対象日 YYYY-MM-DD")
    ap.add_argument("--sleep", type=float, default=5.0, help="バッチ内の投稿間隔 (秒)")
    ap.add_argument("--batch-size", type=int, default=5, help="連続投稿の最大件数")
    ap.add_argument("--batch-rest", type=int, default=300, help="バッチ間の休止秒数 (デフォルト 5分)")
    ap.add_argument("--shop", default=None, help="単一店舗のみ (動作確認用)")
    ap.add_argument("--draft-only", action="store_true", help="下書き保存のみ (公開しない)")
    ap.add_argument("--dry-run", action="store_true", help="API は呼ばずに対象一覧のみ表示")
    ap.add_argument("--resume", action="store_true",
                    help="既投稿ログ (ローカル or R2) を読み込み、投稿済みをスキップして再開")
    args = ap.parse_args()

    cookie = get_session_cookie()
    session = build_session(cookie)

    shops = load_shops()
    if args.shop:
        shops = [s for s in shops if s["id"] == args.shop]
    if not shops:
        logger.error("対象店舗がありません")
        return 1

    log_path = ROOT / "logs" / f"post_via_api_{args.date}.json"
    results: list[dict] = []
    posted_ids: set[str] = set()

    if args.resume and not args.dry_run:
        results, posted_ids = _load_resume_log(log_path, args.date)

    mode = "dry-run" if args.dry_run else ("draft" if args.draft_only else "publish")
    logger.info("対象: %d 店舗 / 日付: %s / mode: %s", len(shops), args.date, mode)
    if mode == "publish":
        logger.info(
            "バッチ設定: %d 件ごとに %d 秒休止 / 投稿間隔 %.1f 秒",
            args.batch_size, args.batch_rest, args.sleep,
        )

    # rate limit リトライ待機秒数 (指数的に増加)
    retry_delays = [180, 360, 600]

    success = 0
    failure = 0
    posted_count = 0

    for i, shop in enumerate(shops, 1):
        shop_id = shop["id"]
        shop_display = shop.get("display_name", shop_id)
        shop_plans = shop.get("note_plans", ["master"])
        md_path = ROOT / "reports" / f"{shop_id}_{args.date}.md"

        if not md_path.exists():
            logger.warning("[SKIP] %s: %s なし", shop_id, md_path.name)
            failure += 1
            continue

        if args.resume and shop_id in posted_ids:
            logger.info("[SKIP (resume)] %s: 投稿済み", shop_id)
            success += 1
            continue

        body_html = markdown_to_note_html(md_path.read_text(encoding="utf-8"))
        title = f"【{args.date}】{shop_display}"

        if args.dry_run:
            logger.info("[DRY] %s: title=%s plans=%s body_len=%d",
                        shop_id, title, shop_plans, len(body_html))
            success += 1
            continue

        # バッチ境界: publish モードのみ
        if mode == "publish" and posted_count > 0 and posted_count % args.batch_size == 0:
            logger.info(
                "  === バッチ境界: %d 秒休止 (%d/%d 件 publish 済み) ===",
                args.batch_rest, posted_count, len(shops),
            )
            time.sleep(args.batch_rest)

        logger.info("[%d/%d] %s (%s) plans=%s 投稿中...", i, len(shops), shop_id, shop_display, shop_plans)

        plan_keys = None
        last_error = None
        published_ok = False
        note: dict = {}

        for attempt in range(len(retry_delays) + 1):
            try:
                note = create_text_note(session)
                save_draft(session, note["id"], title, body_html)

                if args.draft_only:
                    logger.info("[OK draft] %s -> https://editor.note.com/notes/%s/edit",
                                shop_id, note["id"])
                    published_ok = True
                    break

                available = get_circle_plans(session, note["key"])
                plan_keys = resolve_plan_keys(available, shop_plans)
                if not plan_keys:
                    raise RuntimeError(f"プラン解決失敗: shop_plans={shop_plans}")
                publish(session, note["id"], note["key"], note["slug"], title, body_html, plan_keys)
                logger.info("[OK published] %s -> https://note.com/notes/%s", shop_id, note["key"])
                published_ok = True
                break

            except Exception as e:
                last_error = str(e)
                if _is_rate_limit(e) and attempt < len(retry_delays):
                    wait = retry_delays[attempt]
                    logger.warning(
                        "  レート制限検出 (attempt %d/%d)。%d 秒待機して再試行... [%s]",
                        attempt + 1, len(retry_delays), wait, type(e).__name__,
                    )
                    time.sleep(wait)
                    continue
                logger.debug("  リトライ対象外エラー: %s", last_error)
                break

        if published_ok:
            results.append({
                "shop": shop_id,
                "id": note["id"],
                "key": note.get("key", ""),
                "title": title,
                "plan_keys": plan_keys if not args.draft_only else None,
            })
            _save_log(log_path, results)  # 逐次保存: 途中失敗しても再開可能
            success += 1
            posted_count += 1
        else:
            logger.error("[FAIL] %s: %s", shop_id, last_error)
            failure += 1

        if i < len(shops):
            time.sleep(args.sleep)

    _save_log(log_path, results)

    if mode == "publish" and results:
        _upload_log_to_r2(log_path, args.date)

    logger.info("=" * 60)
    logger.info("[POST SUMMARY] success=%d / failure=%d", success, failure)
    logger.info("結果ログ: %s", log_path)
    logger.info("=" * 60)
    return 0 if failure == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
