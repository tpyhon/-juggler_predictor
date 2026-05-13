"""ローカル週次バッチ: 週次レポート生成 + Note 投稿。

Windows タスクスケジューラから run_local_weekly.bat 経由で呼ばれる。
"""
from __future__ import annotations

import argparse
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
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


def _notify(message: str) -> None:
    try:
        from juggler_predictor.notify.slack import notify_slack
        notify_slack(message)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="対象週の任意の日付 YYYY-MM-DD (デフォルト: 直近の完了週)")
    ap.add_argument("--draft-only", action="store_true", help="下書き保存のみ")
    ap.add_argument("--dry-run", action="store_true", help="投稿せず生成のみ")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    run_date = args.date or date.today().isoformat()
    _setup_logging(ROOT / "logs" / f"local_weekly_{run_date}.log")

    logger.info("=" * 60)
    logger.info("Local Weekly Batch start: run_date=%s", run_date)
    logger.info("=" * 60)

    uv = ["uv", "run", "python"]

    # 1. dataset 構築
    rc = _run(uv + ["scripts/build_dataset.py"], "Build dataset", 600)
    if rc != 0:
        _notify(f"❌ 週次バッチ失敗 [build_dataset] {run_date}")
        return rc

    # 2. モデルバンドル DL
    logger.info("--- Download model bundle from R2 ---")
    dl_code = "\n".join([
        "from juggler_predictor.storage.r2 import build_r2_client_from_env",
        "from pathlib import Path",
        "r2 = build_r2_client_from_env()",
        "Path('models').mkdir(exist_ok=True)",
        "obj = r2._client.get_object(Bucket=r2.config.bucket, Key='models/model_bundle.joblib')",
        "Path('models/model_bundle.joblib').write_bytes(obj['Body'].read())",
        "print('[OK] downloaded model_bundle.joblib')",
    ])
    rc = subprocess.run(uv + ["-c", dl_code], timeout=120).returncode
    if rc != 0:
        logger.error("[FAIL] Download model bundle")
        _notify(f"❌ 週次バッチ失敗 [download model] {run_date}")
        return rc
    logger.info("[OK] Download model bundle")

    # 3. 週次レポート生成・投稿
    report_cmd = uv + ["scripts/weekly_report.py"]
    if args.date:
        report_cmd += ["--date", args.date]
    if args.draft_only:
        report_cmd.append("--draft-only")
    if args.dry_run:
        report_cmd.append("--dry-run")

    rc = _run(report_cmd, "Generate & post weekly report", 1200)
    if rc != 0:
        _notify(f"❌ 週次バッチ失敗 [weekly_report] {run_date}")
        return rc

    _notify(f"✅ 週次レポート完了 {run_date}")
    logger.info("=" * 60)
    logger.info("Local Weekly Batch end: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
