"""共通フィクスチャ."""
from __future__ import annotations

from pathlib import Path

import pytest

from juggler_predictor import PROJECT_ROOT


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def sample_machines_config() -> list[dict]:
    return [
        {"canonical": "マイジャグラーV", "aliases": ["マイジャグラー5", "マイジャグラーⅤ"]},
        {"canonical": "ファンキージャグラー2", "aliases": ["ファンキージャグラーⅡ"]},
    ]
