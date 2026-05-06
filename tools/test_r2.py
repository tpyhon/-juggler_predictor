"""R2 接続テスト. .env の値で R2 に接続できるか確認する."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

required = ["R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f"[NG] .env に未設定: {missing}")
    sys.exit(1)

print("[INFO] R2 クライアント作成")
client = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
    config=BotoConfig(signature_version="s3v4"),
)
bucket = os.environ["R2_BUCKET"]
print(f"[INFO] Target bucket: {bucket}")

try:
    print("[TEST 1] put: hello.txt")
    client.put_object(Bucket=bucket, Key="hello.txt",
                      Body=b"Hello R2 from juggler_predictor",
                      ContentType="text/plain")
    print("  OK")

    print("[TEST 2] list:")
    resp = client.list_objects_v2(Bucket=bucket, MaxKeys=5)
    keys = [obj["Key"] for obj in resp.get("Contents", [])]
    print(f"  found: {keys}")

    print("[TEST 3] get: hello.txt")
    obj = client.get_object(Bucket=bucket, Key="hello.txt")
    body = obj["Body"].read().decode("utf-8")
    print(f"  body: {body!r}")

    print("[TEST 4] delete: hello.txt")
    client.delete_object(Bucket=bucket, Key="hello.txt")
    print("  OK")

    print()
    print("=" * 60)
    print("[SUCCESS] R2 接続テスト 4/4 すべて成功!")
    print("=" * 60)
except Exception as e:
    print(f"[NG] {type(e).__name__}: {e}")
    sys.exit(1)
