"""ローカル月次再学習バッチ: 学習 + R2 アップロード。

Windows タスクスケジューラから run_local_monthly_retrain.bat 経由で呼ばれる。
"""
from __future__ import annotations

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
    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    run_date = date.today().isoformat()
    _setup_logging(ROOT / "logs" / f"local_monthly_retrain_{run_date}.log")

    logger.info("=" * 60)
    logger.info("Local Monthly Retrain start: date=%s", run_date)
    logger.info("=" * 60)

    uv = ["uv", "run", "python"]

    # 1. dataset 構築
    rc = _run(uv + ["scripts/build_dataset.py"], "Build dataset", 600)
    if rc != 0:
        _notify(f"❌ 月次再学習失敗 [build_dataset] {run_date}")
        return rc

    # 2. p_win/diff モデル学習
    rc = _run(uv + ["scripts/train.py"], "Train p_win/diff models", 1800)
    if rc != 0:
        _notify(f"❌ 月次再学習失敗 [train.py] {run_date}")
        return rc

    # 3. 設定分類器学習
    rc = _run(uv + ["scripts/train_setting.py"], "Train setting classifier", 1800)
    if rc != 0:
        _notify(f"❌ 月次再学習失敗 [train_setting.py] {run_date}")
        return rc

    # 4. モデルバンドルを R2 にアップロード
    logger.info("--- Upload model bundle to R2 ---")
    upload_code = "\n".join([
        "from datetime import date",
        "from pathlib import Path",
        "from juggler_predictor.storage.r2 import build_r2_client_from_env",
        "c = build_r2_client_from_env()",
        "b = Path('models/model_bundle.joblib').read_bytes()",
        "backup_key = f'models/backup/{date.today().isoformat()}_model_bundle.joblib'",
        "c.put_bytes(backup_key, b, content_type='application/octet-stream')",
        "print(f'[OK] backup: {backup_key} ({len(b)/1024:.1f} KB)')",
        "c.put_bytes('models/model_bundle.joblib', b, content_type='application/octet-stream')",
        "print(f'[OK] production: models/model_bundle.joblib')",
    ])
    rc = subprocess.run(uv + ["-c", upload_code], timeout=120).returncode
    if rc != 0:
        logger.error("[FAIL] Upload model bundle")
        _notify(f"❌ 月次再学習失敗 [upload model] {run_date}")
        return rc
    logger.info("[OK] Upload model bundle to R2")

    _notify(f"✅ 月次再学習完了 {run_date} — モデルを R2 に反映しました")
    logger.info("=" * 60)
    logger.info("Local Monthly Retrain end: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
