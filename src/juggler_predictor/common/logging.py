"""rich + 標準 logging. UTF-8 stdout 強制."""
from __future__ import annotations

import logging
import os
import sys

from rich.console import Console
from rich.logging import RichHandler

_CONFIGURED = False


def _force_utf8_stdout() -> None:
    """Windows console の文字化け対策."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def configure_logging(level: str | None = None) -> None:
    """プロセス全体で 1 回だけ呼ぶ."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    _force_utf8_stdout()
    lvl = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    is_ci = os.environ.get("GITHUB_ACTIONS") == "true"

    if is_ci:
        logging.basicConfig(
            level=lvl,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            stream=sys.stdout,
            force=True,
        )
    else:
        console = Console(stderr=False, force_terminal=True)
        handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            log_time_format="%H:%M:%S",
        )
        logging.basicConfig(level=lvl, format="%(message)s", handlers=[handler], force=True)

    for noisy in ("botocore", "boto3", "urllib3", "s3transfer", "playwright"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """各モジュールの先頭で呼ぶ."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)

# ---------------------------------------------------------------------------
# 後方互換: setup_logging エイリアス
# ---------------------------------------------------------------------------
def setup_logging(level: str | None = None) -> None:
    """:func:`configure_logging` のエイリアス。

    scripts/ から ``setup_logging`` 名で参照されるため互換用に追加。
    """
    configure_logging(level)
