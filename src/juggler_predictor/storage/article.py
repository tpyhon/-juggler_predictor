"""記事 (Markdown) を R2 articles/ 配下にアップロードするヘルパー。"""
from __future__ import annotations

import logging
from pathlib import Path

from .r2 import R2Client, build_r2_client_from_env

logger = logging.getLogger(__name__)


def article_key(shop_id: str, target_date: str) -> str:
    return f"articles/{shop_id}/{target_date}.md"


def upload_article(shop_id: str, target_date: str, md_text: str, client: R2Client | None = None) -> str:
    """記事 Markdown を R2 にアップロードしキーを返す。"""
    client = client or build_r2_client_from_env()
    key = article_key(shop_id, target_date)
    client.put_bytes(key, md_text.encode("utf-8"), content_type="text/markdown; charset=utf-8")
    logger.info("article uploaded: %s (%d bytes)", key, len(md_text))
    return key


def upload_article_from_path(shop_id: str, target_date: str, md_path: Path, client: R2Client | None = None) -> str:
    return upload_article(shop_id, target_date, md_path.read_text(encoding="utf-8"), client=client)
