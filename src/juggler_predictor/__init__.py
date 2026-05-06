"""ジャグラー予測 Note 自動投稿システム."""
from __future__ import annotations

__version__ = "0.1.0"

from pathlib import Path

# プロジェクトルート(絶対パス禁止のため、ここで一元管理)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CONFIG_DIR: Path = PROJECT_ROOT / "config"
DATA_DIR: Path = PROJECT_ROOT / "data"
AUTH_DIR: Path = PROJECT_ROOT / "auth"

__all__ = ["PROJECT_ROOT", "CONFIG_DIR", "DATA_DIR", "AUTH_DIR", "__version__"]
