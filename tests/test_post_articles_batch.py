"""post_articles_batch の補助関数テスト。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_post_module():
    """scripts/post_articles_batch.py を直接ロード。"""
    spec = importlib.util.spec_from_file_location(
        "post_articles_batch", ROOT / "scripts" / "post_articles_batch.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_title_format():
    mod = _load_post_module()
    title = mod.build_title("エスパス日拓上野本館", "2026-05-05")
    assert "エスパス日拓上野本館" in title
    assert "2026-05-05" in title
    assert "高設定期待度レポート" in title
