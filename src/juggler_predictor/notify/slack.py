"""Slack Webhook 通知ヘルパー。"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


def notify_slack(message: str, webhook_url: str | None = None) -> bool:
    """Slack に通知。失敗しても例外は投げず False を返す。"""
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.info("SLACK_WEBHOOK_URL 未設定: skip")
        return False
    try:
        resp = requests.post(url, json={"text": message}, timeout=10)
        if resp.status_code == 200:
            logger.info("Slack 通知 OK")
            return True
        logger.warning("Slack 通知失敗 status=%d body=%s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("Slack 通知例外: %s", e)
        return False
