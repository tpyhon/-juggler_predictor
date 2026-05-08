"""Note 投稿用 API クライアント (非公式)。

post_to_note.py をベースに、複数記事の連続投稿に対応したラッパー。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://note.com"
COOKIE_FILE = Path("data/note_cookies.json")


class NoteClient:
    """Note の非公式 API を叩くクライアント。

    使い方:
        client = NoteClient()
        client.login()  # NOTE_SESSION_COOKIE があれば優先、なければ email/password
        for article in articles:
            client.post(title, body_md, price=300)
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self._prefetched_draft: dict | None = None
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://note.com/",
                "Origin": "https://note.com",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def login(self, email: str | None = None, password: str | None = None) -> None:
        """セッション Cookie 注入優先、失敗時は email/password でログイン。"""
        session_cookie = os.environ.get("NOTE_SESSION_COOKIE", "")
        if session_cookie:
            logger.info("NOTE_SESSION_COOKIE からセッションを注入")
            self.session.cookies.clear()
            self.session.cookies.set(
                "_note_session_v5",
                session_cookie,
                domain=".note.com",
            )
            resp = self.session.post(
                f"{BASE_URL}/api/v1/text_notes",
                json={"template_key": None},
                timeout=15,
            )
            logger.info("セッション確認: %s", resp.status_code)
            if resp.status_code in (200, 201):
                body = resp.json()
                data = body.get("data", body)
                self._prefetched_draft = data
                logger.info("Cookie 認証 OK 下書き id=%s", data.get("id"))
                return
            logger.warning("Cookie 無効、email/password に fallback")
            self.session.cookies.clear()

        email = email or os.environ.get("NOTE_EMAIL", "")
        password = password or os.environ.get("NOTE_PASSWORD", "")
        if not email or not password:
            raise RuntimeError(
                "NOTE_SESSION_COOKIE か NOTE_EMAIL/NOTE_PASSWORD が必要です"
            )
        logger.info("email/password でログイン")
        resp = self.session.post(
            f"{BASE_URL}/api/v1/sessions/sign_in",
            json={"login": email, "password": password, "redirect_path": ""},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"ログイン失敗 {resp.status_code}: {resp.text[:200]}"
            )
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(
            json.dumps(dict(self.session.cookies.items()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        new_cookie = self.session.cookies.get("_note_session_v5", "")
        if new_cookie:
            logger.info("=" * 50)
            logger.info("NOTE_SESSION_COOKIE Secret を更新してください:")
            logger.info(new_cookie)
            logger.info("=" * 50)
        self._prefetched_draft = None

    def create_draft(self) -> dict:
        if self._prefetched_draft:
            draft = self._prefetched_draft
            self._prefetched_draft = None
            logger.info("既存下書きを使用 id=%s", draft.get("id"))
            return draft
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes",
            json={"template_key": None},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"下書き作成失敗 {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json().get("data", resp.json())
        if "id" not in data:
            raise RuntimeError(f"予期しないレスポンス: {data}")
        logger.info("下書き作成 id=%s key=%s", data["id"], data.get("key"))
        return data

    def save_draft(self, note_id: int, title: str, body_html: str) -> None:
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes/draft_save",
            params={"id": note_id, "is_temp_saved": "true"},
            json={
                "name": title,
                "body": body_html,
                "body_length": len(body_html),
                "index": False,
                "is_lead_form": False,
            },
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"下書き保存失敗 {resp.status_code}: {resp.text[:200]}"
            )
        logger.info("下書き保存 id=%s", note_id)

    def publish(
        self,
        note_id: int,
        note_key: str,
        title: str,
        body_html: str,
        price: int = 300,
        hashtags: list[str] | None = None,
    ) -> str:
        hashtags = hashtags or []
        resp = self.session.post(
            f"{BASE_URL}/api/v1/text_notes/draft_save",
            params={"id": note_id, "is_temp_saved": "false"},
            json={
                "name": title,
                "body": body_html,
                "body_length": len(body_html),
                "price": price,
                "hashtag_list": hashtags,
                "index": True,
                "is_lead_form": False,
                "publish": True,
                "status": "published",
            },
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"公開失敗 {resp.status_code}: {resp.text[:300]}"
            )
        url = f"https://note.com/notes/{note_key}"
        logger.info("公開完了 %s", url)
        return url

    def post(
        self,
        title: str,
        body_html: str,
        price: int = 300,
        hashtags: list[str] | None = None,
    ) -> str:
        """下書き作成 → 保存 → 公開を1回で実行。失敗時は例外。"""
        draft = self.create_draft()
        note_id = draft["id"]
        note_key = draft["key"]
        self.save_draft(note_id, title, body_html)
        return self.publish(note_id, note_key, title, body_html, price=price, hashtags=hashtags)
