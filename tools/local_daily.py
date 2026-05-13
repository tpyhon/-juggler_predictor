"""ローカル日次バッチ: 記事生成 + Note 投稿。

スクレイピング (run_local_morning) 完了後に実行する。
Windows タスクスケジューラから run_local_daily.bat 経由で呼ばれる。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


logger = logging.getLogger(__name__)


def _run(cmd: list[str], desc: str, timeout: int = 1800) -> int:
    logger.info("--- %s ---", desc)
    rc = subprocess.run(cmd, timeout=timeout).returncode
    if rc != 0:
        logger.error("[FAIL] %s rc=%d", desc, rc)
    else:
        logger.info("[OK] %s", desc)
    return rc


def _run_with_capture(cmd: list[str], desc: str, timeout: int = 1800) -> tuple[int, str]:
    """サブプロセスを実行し、stderr をキャプチャする。返り値は (rc, stderr)"""
    logger.info("--- %s ---", desc)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.error("[FAIL] %s rc=%d", desc, result.returncode)
    else:
        logger.info("[OK] %s", desc)
    return result.returncode, result.stderr


def _notify(message: str) -> None:
    try:
        from juggler_predictor.notify.slack import notify_slack
        notify_slack(message)
    except Exception:
        pass


def _upload_articles(target_date: str) -> int:
    from juggler_predictor.storage.article import upload_article_from_path
    reports = ROOT / "reports"
    count = 0
    for md in reports.glob(f"*_{target_date}.md"):
        shop_id = md.stem.replace(f"_{target_date}", "")
        upload_article_from_path(shop_id, target_date, md)
        logger.info("[UPLOAD] %s -> articles/%s/%s.md", shop_id, shop_id, target_date)
        count += 1
    logger.info("[OK] uploaded %d articles", count)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="記事投稿日 YYYY-MM-DD (デフォルト: 今日 JST)")
    ap.add_argument("--skip-post", action="store_true", help="Note 投稿をスキップ")
    ap.add_argument("--dry-run", action="store_true", help="Note 投稿を dry-run モードで実行")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    target_date = args.date or date.today().isoformat()
    _setup_logging(ROOT / "logs" / f"local_daily_{target_date}.log")

    logger.info("=" * 60)
    logger.info("Local Daily Batch start: date=%s", target_date)
    logger.info("=" * 60)

    uv = ["uv", "run", "python"]

    # 1. dataset 構築
    rc = _run(uv + ["scripts/build_dataset.py"], "Build dataset", 600)
    if rc != 0:
        _notify(f"❌ 日次バッチ失敗 [build_dataset] {target_date}")
        return rc

    # 2. モデルバンドル DL
    logger.info("--- Download model bundle from R2 ---")
    dl_code = "\n".join([
        "from juggler_predictor.storage.r2 import build_r2_client_from_env",
        "from pathlib import Path",
        "r2 = build_r2_client_from_env()",
        "Path('models').mkdir(exist_ok=True)",
        "obj = r2._client.get_object(Bucket=r2.config.bucket, Key='models/model_bundle.joblib')",
        "data = obj['Body'].read()",
        "Path('models/model_bundle.joblib').write_bytes(data)",
        "print(f'[OK] model_bundle.joblib ({len(data)/1024:.1f} KB)')",
    ])
    rc = subprocess.run(uv + ["-c", dl_code], timeout=120).returncode
    if rc != 0:
        logger.error("[FAIL] Download model bundle")
        _notify(f"❌ 日次バッチ失敗 [download model] {target_date}")
        return rc
    logger.info("[OK] Download model bundle")

    # 3. 記事生成
    rc = _run(uv + ["scripts/generate_articles_all.py", "--date", target_date], "Generate articles", 1800)
    partial_failure = False
    if rc != 0:
        summary_path = ROOT / "reports" / f"generate_articles_summary_{target_date}.json"
        failed_shops = []
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                failed_shops = [f"{item['shop']}({item['reason']})" for item in summary.get("failure", [])]
            except Exception:
                failed_shops = []

        if failed_shops:
            _notify(
                f"⚠️ 日次バッチ: 記事生成で一部失敗 {target_date}\n"
                f"失敗店舗: {', '.join(failed_shops)}\n"
                "成功した店舗の記事は投稿を続行します。"
            )
        else:
            _notify(f"⚠️ 日次バッチ: 記事生成で一部失敗 {target_date} — 詳細は logs/local_daily_{target_date}.log を確認してください。")

        partial_failure = True

    generated_files = list((ROOT / "reports").glob(f"*_{target_date}.md"))
    if not generated_files:
        _notify(f"❌ 日次バッチ失敗: 生成済み記事がありません {target_date}")
        return 1

    # 4. 記事を R2 にアップロード
    logger.info("--- Upload articles to R2 ---")
    try:
        rc = _upload_articles(target_date)
    except Exception as e:
        logger.error("[FAIL] Upload articles: %s", e)
        _notify(f"❌ 日次バッチ失敗 [upload articles] {target_date}")
        return 1

    # 5. Note 投稿
    if not args.skip_post:
        post_cmd = uv + [
            "scripts/post_articles_via_api.py",
            "--date", target_date,
            "--sleep", "10",
            "--batch-size", "5",
            "--batch-rest", "120",
            "--resume",  # 途中失敗時・再実行時に投稿済みをスキップ
        ]
        if args.dry_run:
            post_cmd.append("--dry-run")
        rc, stderr = _run_with_capture(post_cmd, "Post to Note", 3600)  # ローカルは 60分タイムアウト
        if rc != 0:
            # stderr から [FAIL] shop_id: パターンを抽出
            failed_shops = []
            import re
            for line in stderr.split("\n"):
                match = re.search(r"\[FAIL\]\s+(\S+):\s*(.*)", line)
                if match:
                    shop_id = match.group(1)
                    error_msg = match.group(2)[:50]  # 最初の 50 文字
                    failed_shops.append(f"{shop_id}({error_msg})")
            
            if failed_shops:
                _notify(
                    f"⚠️ 日次バッチ: 一部投稿失敗 {target_date}\n"
                    f"失敗店舗: {', '.join(failed_shops)}\n"
                    "他の店舗の投稿は完了しました。"
                )
            else:
                _notify(f"❌ 日次バッチ失敗 [post to Note] {target_date} — 詳細は logs/local_daily_{target_date}.log を確認してください。")
            # 一部投稿失敗でもバッチ全体は成功扱い
            partial_failure = True

    if partial_failure:
        _notify(f"✅ 日次バッチ完了 {target_date} — 一部店舗は失敗しましたが、成功した店舗は投稿されました")
    else:
        _notify(f"✅ 日次バッチ完了 {target_date} — Note 投稿が完了しました")
    logger.info("=" * 60)
    logger.info("Local Daily Batch end: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
