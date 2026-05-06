"""Cloudflare R2 (S3 互換) クライアント薄ラッパ。

- 環境変数からクライアントを構築するヘルパを提供する。
- bytes / JSON / gzip-JSON の get/put をサポートする。
- list / delete / exists のユーティリティも併設。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class R2Config:
    """R2 接続設定。環境変数または明示パラメータから構築する。"""

    endpoint: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    region: str = "auto"


def build_r2_client_from_env(env: dict[str, str] | None = None) -> "R2Client":
    """環境変数から :class:`R2Client` を組み立てる。

    必須環境変数: ``R2_ENDPOINT``, ``R2_ACCESS_KEY_ID``,
    ``R2_SECRET_ACCESS_KEY``, ``R2_BUCKET``.
    """
    src = env if env is not None else os.environ
    missing = [
        k for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        if not src.get(k)
    ]
    if missing:
        raise RuntimeError(f"R2 環境変数が不足しています: {missing}")

    cfg = R2Config(
        endpoint=src["R2_ENDPOINT"],
        access_key_id=src["R2_ACCESS_KEY_ID"],
        secret_access_key=src["R2_SECRET_ACCESS_KEY"],
        bucket=src["R2_BUCKET"],
        region=src.get("R2_REGION", "auto"),
    )
    return R2Client(cfg)


class R2Client:
    """boto3 ベースの R2 クライアント。"""

    def __init__(self, config: R2Config) -> None:
        self.config = config
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
            config=BotoConfig(signature_version="s3v4"),
        )

    # ---------------- 基本 I/O ----------------
    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self.config.bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)
        logger.debug("R2 put: %s (%d bytes)", key, len(data))

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.config.bucket, Key=key)
        body = resp["Body"].read()
        logger.debug("R2 get: %s (%d bytes)", key, len(body))
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.config.bucket, Key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.config.bucket, Key=key)
        logger.debug("R2 delete: %s", key)

    def list_keys(self, prefix: str = "") -> Iterable[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                yield obj["Key"]

    # ---------------- 高水準 ----------------
    def put_json(self, key: str, obj: Any, *, gzipped: bool = False) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        if gzipped:
            body = gzip.compress(body)
            self.put_bytes(key, body, content_type="application/gzip")
        else:
            self.put_bytes(key, body, content_type="application/json")

    def get_json(self, key: str, *, gzipped: bool = False) -> Any:
        body = self.get_bytes(key)
        if gzipped:
            body = gzip.decompress(body)
        return json.loads(body.decode("utf-8"))

    def put_gzip_text(self, key: str, text: str) -> None:
        body = gzip.compress(text.encode("utf-8"))
        self.put_bytes(key, body, content_type="application/gzip")

    def get_gzip_text(self, key: str) -> str:
        body = gzip.decompress(self.get_bytes(key))
        return body.decode("utf-8")
