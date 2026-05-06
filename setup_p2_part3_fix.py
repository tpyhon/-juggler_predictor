"""P2 Part 3 ホットフィックス: common/logging.py に setup_logging エイリアスを追加。"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "juggler_predictor" / "common" / "logging.py"

ALIAS_BLOCK = """

# ---------------------------------------------------------------------------
# 後方互換: setup_logging エイリアス
# ---------------------------------------------------------------------------
def setup_logging(level: str | None = None) -> None:
    \"\"\":func:`configure_logging` のエイリアス。

    scripts/ から ``setup_logging`` 名で参照されるため互換用に追加。
    \"\"\"
    configure_logging(level)
"""


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")

    if "def setup_logging(" in text:
        print("[SKIP] setup_logging は既に定義されています")
        return

    new_text = text.rstrip() + ALIAS_BLOCK
    TARGET.write_text(new_text, encoding="utf-8", newline="\n")
    print(f"[WRITE] {TARGET.relative_to(ROOT)}")
    print("[OK] setup_logging エイリアスを追加しました")
    print()
    print("次のコマンド:")
    print("  uv run pytest -v")
    print("  uv run python scripts/refresh_cf_cookie.py")


if __name__ == "__main__":
    main()
