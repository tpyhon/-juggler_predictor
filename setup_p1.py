"""
Juggler Predictor: Phase 1 セットアップスクリプト
このファイルを実行すると、プロジェクト雛形のすべてのファイルが生成されます。

使い方:
    cd C:\\Users\\takum\\Desktop\\code\\juggler_predictor
    python setup_p1.py
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ------------------------------------------------------------
# 作成するディレクトリ一覧
# ------------------------------------------------------------
DIRS = [
    ".github/workflows",
    "auth",
    "data",
    "tools",
    "config",
    "src/juggler_predictor/common",
    "src/juggler_predictor/scrape",
    "src/juggler_predictor/storage",
    "src/juggler_predictor/model",
    "src/juggler_predictor/policy",
    "src/juggler_predictor/report",
    "src/juggler_predictor/publish",
    "src/juggler_predictor/notify",
    "src/juggler_predictor/pipeline",
    "scripts",
    "tests",
]

# ------------------------------------------------------------
# 空ファイル(.gitkeep / __init__.py)
# ------------------------------------------------------------
EMPTY_FILES = [
    ".github/workflows/.gitkeep",
    "auth/.gitkeep",
    "data/.gitkeep",
    "tools/.gitkeep",
    "src/juggler_predictor/scrape/__init__.py",
    "src/juggler_predictor/storage/__init__.py",
    "src/juggler_predictor/model/__init__.py",
    "src/juggler_predictor/policy/__init__.py",
    "src/juggler_predictor/report/__init__.py",
    "src/juggler_predictor/publish/__init__.py",
    "src/juggler_predictor/notify/__init__.py",
    "src/juggler_predictor/pipeline/__init__.py",
    "scripts/__init__.py",
    "tests/__init__.py",
    "src/juggler_predictor/common/__init__.py",
]

# ------------------------------------------------------------
# 内容ありファイル(辞書: 相対パス → 内容)
# ------------------------------------------------------------
FILES: dict[str, str] = {}

# ============================================================
# pyproject.toml
# ============================================================
FILES["pyproject.toml"] = '''[project]
name = "juggler-predictor"
version = "0.1.0"
description = "ジャグラー予測 Note 自動投稿システム"
readme = "README.md"
requires-python = ">=3.11,<3.13"
license = { text = "MIT" }
authors = [{ name = "tpyhon" }]

dependencies = [
    "curl-cffi>=0.7.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.2.0",
    "playwright>=1.45.0",
    "scikit-learn>=1.5.0",
    "lightgbm>=4.5.0",
    "numpy>=1.26.0",
    "pandas>=2.2.0",
    "joblib>=1.4.0",
    "boto3>=1.34.0",
    "botocore>=1.34.0",
    "pyyaml>=6.0.2",
    "python-dotenv>=1.0.0",
    "google-genai>=0.3.0",
    "tenacity>=9.0.0",
    "rich>=13.7.0",
    "requests>=2.32.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "pytest-mock>=3.14.0",
    "moto[s3]>=5.0.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
    "types-pyyaml>=6.0.12",
    "types-requests>=2.32.0",
    "freezegun>=1.5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/juggler_predictor"]

[tool.ruff]
line-length = 110
target-version = "py311"
src = ["src", "tests", "scripts"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["B011"]
"scripts/*" = ["E402"]

[tool.mypy]
python_version = "3.11"
strict = false
warn_return_any = true
warn_unused_ignores = true
ignore_missing_imports = true
files = ["src/juggler_predictor"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "slow: 重いテスト (CI で skip 可能)",
    "integration: 外部サービスを使うテスト",
]
'''

# ============================================================
# .gitignore
# ============================================================
FILES[".gitignore"] = '''# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# venv / uv
.venv/
venv/
.uv-cache/

# Distribution
build/
dist/
*.egg-info/
*.egg

# Testing
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# 機密情報
.env
.env.local
auth/*.json
!auth/.gitkeep

# データ・モデル
data/
!data/.gitkeep
*.joblib
*.pkl
dataset/
pred_cache/
articles/

# Playwright
playwright-report/
test-results/
.playwright/

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# ログ
*.log
logs/
'''

# ============================================================
# .env.example
# ============================================================
FILES[".env.example"] = '''# === Cloudflare R2 ===
R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=slot-prediction

# === ana-slo.com ===
ANA_SLO_BASE_URL=https://ana-slo.com

# === Gemini API ===
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# === Note ===
NOTE_STORAGE_STATE_B64=
NOTE_EMAIL=
NOTE_PASSWORD=

# === Discord ===
DISCORD_WEBHOOK_URL=

# === Runtime ===
RUNTIME_ENV=local
LOG_LEVEL=INFO
TZ=Asia/Tokyo
'''

# ============================================================
# README.md
# ============================================================
FILES["README.md"] = '''# Juggler Predictor

ジャグラー予測 Note 自動投稿システム。GitHub Actions が毎朝自動でデータ取得・予測・記事生成・Note 投稿まで実行します。

## アーキテクチャ概要

GitHub Actions cron (JST 4-8 時) で以下を自動実行:

- Stage A: scrape -> 増分マージ -> 予測 -> 記事生成 (店舗 matrix 並列)
- Stage B: 全店マージ -> Gemini 総括 -> Note 投稿 -> Discord 通知

データは Cloudflare R2 に集約。PC を一切起動せずに完結します。

## クイックスタート

### 必要環境
- Python 3.11 / 3.12
- [uv](https://docs.astral.sh/uv/)
- Cloudflare R2 アカウント
- Note のメンバーシップ運営権限

### Windows でのセットアップ

powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" git clone https://github.com//juggler_predictor.git cd juggler_predictor uv sync --extra dev uv run playwright install chromium copy .env.example .env uv run pytest

Copy
uv について: `uv sync` 一発で .venv 作成・依存解決・ロックまで完了します。

### macOS / Linux

curl -LsSf https://astral.sh/uv/install.sh | sh git clone https://github.com//juggler_predictor.git cd juggler_predictor uv sync --extra dev uv run playwright install chromium cp .env.example .env uv run pytest

Copy
## GitHub Secrets 一覧

| Secret 名 | 用途 |
|----------|------|
| R2_ENDPOINT | Cloudflare R2 のエンドポイント URL |
| R2_ACCESS_KEY_ID | R2 アクセスキー |
| R2_SECRET_ACCESS_KEY | R2 シークレット |
| R2_BUCKET | バケット名 |
| GEMINI_API_KEY | Gemini API キー |
| DISCORD_WEBHOOK_URL | Discord 通知 Webhook |
| NOTE_STORAGE_STATE_B64 | Note 認証用 cookie (base64) |
| ANA_SLO_BASE_URL | ana-slo のベース URL |

## 開発ロードマップ

| Phase | 状態 | 内容 |
|-------|------|------|
| P1 | done | プロジェクト雛形・共通ユーティリティ |
| P2 | next | スクレイピング層 |
| P3 | TODO | ストレージ層 (R2) |
| P4 | TODO | 機械学習層 |
| P5 | TODO | ポリシー層 |
| P6 | TODO | レポート生成層 |
| P7 | TODO | Note 投稿層 |
| P8 | TODO | パイプライン統合 |
| P9 | TODO | GitHub Actions + 地方店舗追加 |
| P10 | TODO | 通知・仕上げ |

## ライセンス

個人利用 (private repository)
'''

# ============================================================
# src/juggler_predictor/__init__.py
# ============================================================
FILES["src/juggler_predictor/__init__.py"] = '''"""ジャグラー予測 Note 自動投稿システム."""
from __future__ import annotations

__version__ = "0.1.0"

from pathlib import Path

# プロジェクトルート(絶対パス禁止のため、ここで一元管理)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CONFIG_DIR: Path = PROJECT_ROOT / "config"
DATA_DIR: Path = PROJECT_ROOT / "data"
AUTH_DIR: Path = PROJECT_ROOT / "auth"

__all__ = ["PROJECT_ROOT", "CONFIG_DIR", "DATA_DIR", "AUTH_DIR", "__version__"]
'''

# ============================================================
# common/dates.py
# ============================================================
FILES["src/juggler_predictor/common/dates.py"] = '''"""日付ユーティリティ. JST を全プロジェクトで統一."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

JST = timezone(timedelta(hours=9), name="JST")


def today_jst() -> date:
    """JST における今日."""
    return datetime.now(JST).date()


def now_jst() -> datetime:
    """JST における現在時刻 (tz-aware)."""
    return datetime.now(JST)


def to_jst(dt: datetime) -> datetime:
    """任意の datetime を JST に変換. naive は JST とみなす."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def parse_date_any(s: str | date | datetime) -> date:
    """\\"2025-01-15\\", \\"2025/1/15\\", \\"20250115\\", date, datetime を date に統一."""
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日付として解釈できません: {s!r}")


def range_dates(start: date | str, end: date | str, *, inclusive: bool = True) -> list[date]:
    """[start, end] の日付リスト. inclusive=False で end を除外."""
    s = parse_date_any(start)
    e = parse_date_any(end)
    if e < s:
        raise ValueError(f"end < start: {s} -> {e}")
    days = (e - s).days + (1 if inclusive else 0)
    return [s + timedelta(days=i) for i in range(days)]


def fmt_date(d: date, sep: str = "-") -> str:
    """YYYY{sep}MM{sep}DD."""
    return d.strftime(f"%Y{sep}%m{sep}%d")


def daterange_iter(start: date, end: date) -> Iterable[date]:
    """ジェネレータ版."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)
'''

# ============================================================
# common/nums.py
# ============================================================
FILES["src/juggler_predictor/common/nums.py"] = '''"""数値ユーティリティ."""
from __future__ import annotations

from typing import Iterable, Sequence

# 全角数字 -> 半角数字の変換テーブル
_FW_DIGITS = str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")


def safe_float(x: object, default: float = 0.0) -> float:
    """カンマ・全角・空文字・None 対応の float 変換."""
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace(" ", "").replace("\u3000", "")
    s = s.translate(_FW_DIGITS)
    if s in ("", "-", "--", "N/A", "n/a", "null", "None"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def safe_int(x: object, default: int = 0) -> int:
    """float 経由で int に."""
    f = safe_float(x, default=float(default))
    try:
        return int(f)
    except (ValueError, OverflowError):
        return default


def clip(v: float, lo: float, hi: float) -> float:
    """値を [lo, hi] に丸める."""
    if lo > hi:
        raise ValueError(f"lo > hi: {lo} > {hi}")
    return max(lo, min(hi, v))


def minmax_normalize(values: Sequence[float]) -> list[float]:
    """min-max 正規化. 全部同じ値なら 0.5 で埋める."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def mean(values: Iterable[float]) -> float:
    vs = list(values)
    return sum(vs) / len(vs) if vs else 0.0
'''

# ============================================================
# common/normalize.py
# ============================================================
FILES["src/juggler_predictor/common/normalize.py"] = '''"""機種名・台番号などの表記ゆれ吸収."""
from __future__ import annotations

import re
import unicodedata

# ローマ数字 -> アラビア数字
_ROMAN_MAP = str.maketrans({
    "\u2160": "1", "\u2161": "2", "\u2162": "3", "\u2163": "4", "\u2164": "5",
    "\u2165": "6", "\u2166": "7", "\u2167": "8", "\u2168": "9", "\u2169": "10",
})


def _basic_normalize(s: str) -> str:
    """NFKC + ローマ数字変換 + 空白除去 + 大文字統一."""
    s = unicodedata.normalize("NFKC", s).translate(_ROMAN_MAP)
    s = re.sub(r"\\s+", "", s)
    return s.upper()


def normalize_machine_name(name: str, aliases_map: dict[str, str] | None = None) -> str:
    """機種名を正準名に正規化. マッチしなければ元の文字列."""
    if not name:
        return ""
    key = _basic_normalize(name)
    if aliases_map:
        for alias_key, canonical in aliases_map.items():
            if _basic_normalize(alias_key) == key:
                return canonical
    return name.strip()


def normalize_unit_number(s: str | int) -> str:
    """台番号. '0123' / '123番' / '#123' -> '123'."""
    if isinstance(s, int):
        return str(s)
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    m = re.search(r"\\d+", s)
    return m.group(0) if m else s.strip()


def is_juggler(machine_name: str, whitelist_canonical: set[str]) -> bool:
    """ホワイトリストに含まれるか."""
    return machine_name in whitelist_canonical


def build_alias_map(machines_config: list[dict]) -> dict[str, str]:
    """machines.yaml の構造から {alias: canonical} のフラットマップを作る."""
    out: dict[str, str] = {}
    for m in machines_config:
        canonical = m["canonical"]
        out[canonical] = canonical
        for alias in m.get("aliases", []):
            out[alias] = canonical
    return out
'''

# ============================================================
# common/io_json.py
# ============================================================
FILES["src/juggler_predictor/common/io_json.py"] = '''"""JSON I/O. atomic write, gzip 対応."""
from __future__ import annotations

import gzip
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path | str) -> Any:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path | str, obj: Any, *, indent: int = 2, sort_keys: bool = False) -> None:
    """atomic write: tmp ファイルに書いて rename."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent, sort_keys=sort_keys)
        os.replace(tmp_path, p)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_json_gz(path: Path | str) -> Any:
    p = Path(path)
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def save_json_gz(path: Path | str, obj: Any, *, indent: int | None = None) -> None:
    """gzip + atomic write."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=p.parent)
    try:
        os.close(fd)
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, p)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_json_bytes(b: bytes, *, gz: bool = False) -> Any:
    """R2 から取得した bytes を直接デコード."""
    if gz:
        return json.loads(gzip.decompress(b).decode("utf-8"))
    return json.loads(b.decode("utf-8"))


def dump_json_bytes(obj: Any, *, gz: bool = False, indent: int | None = None) -> bytes:
    """R2 アップロード用に bytes に."""
    s = json.dumps(obj, ensure_ascii=False, indent=indent)
    raw = s.encode("utf-8")
    return gzip.compress(raw) if gz else raw
'''

# ============================================================
# common/logging.py
# ============================================================
FILES["src/juggler_predictor/common/logging.py"] = '''"""rich + 標準 logging. UTF-8 stdout 強制."""
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
'''

# ============================================================
# common/shops.py
# ============================================================
FILES["src/juggler_predictor/common/shops.py"] = '''"""shops.yaml ローダー."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from juggler_predictor import CONFIG_DIR


@dataclass(frozen=True)
class Shop:
    id: str
    display_name: str
    prefecture: str
    region: str
    note_plans: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict) -> "Shop":
        return cls(
            id=d["id"],
            display_name=d["display_name"],
            prefecture=d["prefecture"],
            region=d["region"],
            note_plans=tuple(d.get("note_plans", [])),
        )


@lru_cache(maxsize=1)
def load_shops(path: Path | None = None) -> list[Shop]:
    p = path or (CONFIG_DIR / "shops.yaml")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    shops = [Shop.from_dict(d) for d in raw]
    ids = [s.id for s in shops]
    if len(ids) != len(set(ids)):
        dup = [i for i in ids if ids.count(i) > 1]
        raise ValueError(f"shops.yaml に重複した id があります: {set(dup)}")
    return shops


def get_shop(shop_id: str) -> Shop:
    for s in load_shops():
        if s.id == shop_id:
            return s
    raise KeyError(f"shop_id 不明: {shop_id}")


def shops_by_region(region: str) -> list[Shop]:
    return [s for s in load_shops() if s.region == region]


def shops_by_prefecture(prefecture: str) -> list[Shop]:
    return [s for s in load_shops() if s.prefecture == prefecture]


def all_shop_ids() -> list[str]:
    return [s.id for s in load_shops()]
'''

# ============================================================
# config/shops.yaml
# ============================================================
FILES["config/shops.yaml"] = '''# 東京都(19 店舗)
# 地方 21 店舗は P9 で追加
- id: kingsetagaya
  display_name: "キングNo.1世田谷店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: messekichijoji
  display_name: "メッセ吉祥寺店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: godonsoshigaya
  display_name: "ゴードン祖師谷店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: espas_seibushinjuku
  display_name: "エスパス日拓西武新宿駅前店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: espas_kabukicho
  display_name: "エスパス日拓新宿歌舞伎町店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: espas_shibuya
  display_name: "エスパス日拓渋谷本館"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: espas_shibuyanew
  display_name: "エスパス日拓渋谷駅前新館"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: maruhan_shinjuku
  display_name: "マルハン新宿東宝ビル店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: maruhan_ikebukuro
  display_name: "マルハン池袋店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: espas_akihabara
  display_name: "エスパス日拓秋葉原駅前店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: mega_chofu
  display_name: "メガガイア調布店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: espas_takadanobaba
  display_name: "エスパス日拓高田馬場本店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: granpaNakano
  display_name: "グランパ中野"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: granpaOkubo
  display_name: "グランパ大久保"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: sengawaUno
  display_name: "仙川UNO"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: rakuen_shibuya
  display_name: "楽園渋谷駅前店"
  prefecture: 東京都
  region: tokyo
  note_plans: [master, shinjuku_shibuya_ikebukuro]

- id: iidabashiPresas
  display_name: "飯田橋プレサス"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: espas_uenonew
  display_name: "エスパス日拓上野新館"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]

- id: espas_ueno
  display_name: "エスパス日拓上野本館"
  prefecture: 東京都
  region: tokyo
  note_plans: [master]
'''

# ============================================================
# config/policies.json (動的生成)
# ============================================================
def _build_policies_json() -> str:
    import json as _json
    default_policy = {
        "k": 5,
        "alpha": 0.7,
        "go_require_topk_pwin_ge": [0.6, 3],
        "go_min_top1_pwin": 0.7,
        "go_min_top1_pred_diff": 0,
        "big_loss_yen": 30000,
        "pwin_prefer": ["p_win_raw", "p_win", "p_win_sigmoid", "p_win_isotonic"],
    }
    shop_ids = [
        "kingsetagaya", "messekichijoji", "godonsoshigaya", "espas_seibushinjuku",
        "espas_kabukicho", "espas_shibuya", "espas_shibuyanew", "maruhan_shinjuku",
        "maruhan_ikebukuro", "espas_akihabara", "mega_chofu", "espas_takadanobaba",
        "granpaNakano", "granpaOkubo", "sengawaUno", "rakuen_shibuya",
        "iidabashiPresas", "espas_uenonew", "espas_ueno",
    ]
    out: dict = {
        "_meta": {
            "version": 1,
            "description": "店舗別ポリシー. tune-policy ワークフローで最適化される. 評価メトリクスは data/policy_metrics.json に分離.",
        },
        "_default": default_policy,
    }
    for sid in shop_ids:
        out[sid] = dict(default_policy)
    return _json.dumps(out, ensure_ascii=False, indent=2)


FILES["config/policies.json"] = _build_policies_json()

# ============================================================
# config/note.yaml
# ============================================================
FILES["config/note.yaml"] = '''plans:
  master: "マスタープラン"
  shinjuku_shibuya_ikebukuro: "新宿・渋谷・池袋プラン"

article:
  title_format: "【{date}】{display_name}"
  date_format: "%Y/%m/%d"

publish:
  show_on_creator_page: false
  set_free_preview: true
  member_only: true
  headless: true
'''

# ============================================================
# config/machines.yaml
# ============================================================
FILES["config/machines.yaml"] = '''# ジャグラー機種ホワイトリスト + 設定値テーブル
# specs はメーカー公表値ベースの代表値. 必要に応じて P4 で精緻化.
machines:
  - canonical: "マイジャグラーV"
    aliases: ["マイジャグラー5", "マイジャグラーⅤ", "MyジャグラーV", "マイジャグV"]
    specs:
      bb_prob:   { "1": 273.07, "2": 270.81, "3": 266.42, "4": 254.03, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 439.83, "2": 399.61, "3": 364.09, "4": 327.68, "5": 297.89, "6": 273.07 }
      composite: { "1": 168.62, "2": 161.10, "3": 153.85, "4": 145.45, "5": 136.53, "6": 127.50 }
      payout:    { "1": 96.0,   "2": 98.3,   "3": 100.4,  "4": 103.1,  "5": 106.7,  "6": 109.4 }

  - canonical: "ネオアイムジャグラーEX"
    aliases: ["NEOアイムジャグラーEX", "ネオアイムジャグラー", "Neoアイムジャグラー"]
    specs:
      bb_prob:   { "1": 287.72, "2": 282.48, "3": 273.07, "4": 264.26, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 455.11, "2": 408.63, "3": 364.09, "4": 327.68, "5": 297.89, "6": 273.07 }
      composite: { "1": 176.34, "2": 167.45, "3": 156.20, "4": 146.39, "5": 136.53, "6": 127.50 }
      payout:    { "1": 96.0,   "2": 97.6,   "3": 99.4,   "4": 101.6,  "5": 105.0,  "6": 108.0 }

  - canonical: "ゴーゴージャグラー3"
    aliases: ["GOGOジャグラー3", "ゴーゴージャグラーIII", "ゴーゴージャグラーⅢ"]
    specs:
      bb_prob:   { "1": 273.07, "2": 268.60, "3": 264.26, "4": 252.06, "5": 240.94, "6": 240.94 }
      rb_prob:   { "1": 528.52, "2": 481.88, "3": 442.77, "4": 364.09, "5": 327.68, "6": 273.07 }
      composite: { "1": 179.90, "2": 172.18, "3": 165.46, "4": 149.13, "5": 138.95, "6": 127.50 }
      payout:    { "1": 95.6,   "2": 97.5,   "3": 99.5,   "4": 102.6,  "5": 105.6,  "6": 109.0 }

  - canonical: "ファンキージャグラー2"
    aliases: ["ファンキージャグラーⅡ", "FUNKYジャグラー2"]
    specs:
      bb_prob:   { "1": 273.07, "2": 270.81, "3": 266.42, "4": 256.00, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 481.88, "2": 442.77, "3": 399.61, "4": 348.04, "5": 318.06, "6": 282.48 }
      composite: { "1": 174.43, "2": 167.83, "3": 159.92, "4": 147.29, "5": 140.43, "6": 129.94 }
      payout:    { "1": 95.7,   "2": 97.5,   "3": 99.4,   "4": 101.9,  "5": 104.7,  "6": 108.5 }

  - canonical: "アイムジャグラーEX-TP"
    aliases: ["アイムジャグラーEXTP", "アイムジャグラーEX TP", "アイムジャグラーEX"]
    specs:
      bb_prob:   { "1": 287.72, "2": 282.48, "3": 273.07, "4": 264.26, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 455.11, "2": 408.63, "3": 364.09, "4": 327.68, "5": 297.89, "6": 273.07 }
      composite: { "1": 176.34, "2": 167.45, "3": 156.20, "4": 146.39, "5": 136.53, "6": 127.50 }
      payout:    { "1": 96.0,   "2": 97.6,   "3": 99.4,   "4": 101.6,  "5": 105.0,  "6": 108.0 }

  - canonical: "ハッピージャグラーVIII"
    aliases: ["ハッピージャグラー8", "ハッピージャグラーⅧ", "ハッピージャグラーV3"]
    specs:
      bb_prob:   { "1": 273.07, "2": 270.81, "3": 266.42, "4": 254.03, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 401.57, "2": 364.09, "3": 334.37, "4": 299.34, "5": 273.07, "6": 252.06 }
      composite: { "1": 162.65, "2": 155.65, "3": 148.30, "4": 137.42, "5": 130.76, "6": 122.66 }
      payout:    { "1": 95.6,   "2": 97.7,   "3": 99.7,   "4": 102.8,  "5": 105.3,  "6": 108.5 }

  - canonical: "ミスタージャグラー"
    aliases: ["Mr.ジャグラー", "Mrジャグラー"]
    specs:
      bb_prob:   { "1": 273.07, "2": 270.81, "3": 264.26, "4": 252.06, "5": 246.55, "6": 240.94 }
      rb_prob:   { "1": 455.11, "2": 414.41, "3": 372.36, "4": 334.37, "5": 299.34, "6": 273.07 }
      composite: { "1": 170.97, "2": 164.10, "3": 154.99, "4": 144.16, "5": 135.51, "6": 127.50 }
      payout:    { "1": 95.7,   "2": 97.5,   "3": 99.5,   "4": 102.5,  "5": 105.5,  "6": 108.7 }

  - canonical: "ジャグラーガールズSS"
    aliases: ["ジャグラーガールズ"]
    specs:
      bb_prob:   { "1": 273.07, "2": 270.81, "3": 266.42, "4": 254.03, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 408.63, "2": 372.36, "3": 334.37, "4": 299.34, "5": 273.07, "6": 252.06 }
      composite: { "1": 163.82, "2": 156.94, "3": 148.30, "4": 137.42, "5": 130.76, "6": 122.66 }
      payout:    { "1": 95.5,   "2": 97.6,   "3": 99.6,   "4": 102.7,  "5": 105.4,  "6": 108.6 }

  - canonical: "ウルトラミラクルジャグラー"
    aliases: ["ウルトラミラクル"]
    specs:
      bb_prob:   { "1": 273.07, "2": 270.81, "3": 266.42, "4": 254.03, "5": 252.06, "6": 240.94 }
      rb_prob:   { "1": 481.88, "2": 442.77, "3": 399.61, "4": 348.04, "5": 318.06, "6": 282.48 }
      composite: { "1": 174.43, "2": 167.83, "3": 159.92, "4": 147.29, "5": 140.43, "6": 129.94 }
      payout:    { "1": 95.7,   "2": 97.6,   "3": 99.5,   "4": 102.0,  "5": 104.8,  "6": 108.6 }

clip_diff: 2000.0
'''

# ============================================================
# tests/conftest.py
# ============================================================
FILES["tests/conftest.py"] = '''"""共通フィクスチャ."""
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
'''

# ============================================================
# tests/test_common.py
# ============================================================
FILES["tests/test_common.py"] = '''"""common/ モジュールの単体テスト."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from juggler_predictor.common.dates import (
    fmt_date,
    parse_date_any,
    range_dates,
    today_jst,
)
from juggler_predictor.common.io_json import (
    dump_json_bytes,
    load_json,
    load_json_bytes,
    load_json_gz,
    save_json,
    save_json_gz,
)
from juggler_predictor.common.normalize import (
    build_alias_map,
    normalize_machine_name,
    normalize_unit_number,
)
from juggler_predictor.common.nums import clip, minmax_normalize, safe_float, safe_int
from juggler_predictor.common.shops import all_shop_ids, get_shop, load_shops


# ---------- dates ----------
def test_parse_date_any_formats() -> None:
    assert parse_date_any("2025-01-15") == date(2025, 1, 15)
    assert parse_date_any("2025/1/15") == date(2025, 1, 15)
    assert parse_date_any("20250115") == date(2025, 1, 15)
    assert parse_date_any(date(2025, 1, 15)) == date(2025, 1, 15)
    assert parse_date_any(datetime(2025, 1, 15, 12, 0)) == date(2025, 1, 15)


def test_parse_date_any_invalid() -> None:
    with pytest.raises(ValueError):
        parse_date_any("not-a-date")


def test_range_dates() -> None:
    rs = range_dates("2025-01-01", "2025-01-03")
    assert rs == [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    rs = range_dates("2025-01-01", "2025-01-03", inclusive=False)
    assert rs == [date(2025, 1, 1), date(2025, 1, 2)]


def test_today_jst() -> None:
    assert isinstance(today_jst(), date)


def test_fmt_date() -> None:
    assert fmt_date(date(2025, 1, 15)) == "2025-01-15"
    assert fmt_date(date(2025, 1, 15), sep="/") == "2025/01/15"


# ---------- nums ----------
def test_safe_float() -> None:
    assert safe_float("1,234.5") == 1234.5
    assert safe_float("\uff11\uff12\uff13\uff14") == 1234.0
    assert safe_float("") == 0.0
    assert safe_float("-") == 0.0
    assert safe_float(None) == 0.0
    assert safe_float("abc", default=-1.0) == -1.0


def test_safe_int() -> None:
    assert safe_int("1,234") == 1234
    assert safe_int("1.7") == 1
    assert safe_int("") == 0


def test_clip() -> None:
    assert clip(5, 0, 10) == 5
    assert clip(-5, 0, 10) == 0
    assert clip(15, 0, 10) == 10
    with pytest.raises(ValueError):
        clip(0, 10, 0)


def test_minmax_normalize() -> None:
    assert minmax_normalize([0.0, 5.0, 10.0]) == [0.0, 0.5, 1.0]
    assert minmax_normalize([3.0, 3.0, 3.0]) == [0.5, 0.5, 0.5]
    assert minmax_normalize([]) == []


# ---------- normalize ----------
def test_normalize_machine_name(sample_machines_config: list[dict]) -> None:
    amap = build_alias_map(sample_machines_config)
    assert normalize_machine_name("マイジャグラーⅤ", amap) == "マイジャグラーV"
    assert normalize_machine_name("マイジャグラー5", amap) == "マイジャグラーV"
    assert normalize_machine_name("マイジャグラーV", amap) == "マイジャグラーV"
    assert normalize_machine_name("ファンキージャグラーⅡ", amap) == "ファンキージャグラー2"
    assert normalize_machine_name("謎の機種", amap) == "謎の機種"


def test_normalize_unit_number() -> None:
    assert normalize_unit_number("123") == "123"
    assert normalize_unit_number("0123") == "0123"
    assert normalize_unit_number("123番") == "123"
    assert normalize_unit_number("#123") == "123"
    assert normalize_unit_number(123) == "123"


# ---------- io_json ----------
def test_save_load_json(tmp_path) -> None:
    p = tmp_path / "x.json"
    save_json(p, {"a": 1, "日本語": "テスト"})
    assert load_json(p) == {"a": 1, "日本語": "テスト"}


def test_save_load_json_gz(tmp_path) -> None:
    p = tmp_path / "x.json.gz"
    save_json_gz(p, {"a": [1, 2, 3]})
    assert load_json_gz(p) == {"a": [1, 2, 3]}


def test_json_bytes_roundtrip() -> None:
    obj = {"日本語キー": [1, 2, 3]}
    raw = dump_json_bytes(obj)
    assert load_json_bytes(raw) == obj
    gz = dump_json_bytes(obj, gz=True)
    assert load_json_bytes(gz, gz=True) == obj


# ---------- shops ----------
def test_load_shops_no_dup() -> None:
    shops = load_shops()
    assert len(shops) == 19
    assert len({s.id for s in shops}) == 19


def test_get_shop() -> None:
    s = get_shop("kingsetagaya")
    assert s.display_name == "キングNo.1世田谷店"
    assert s.region == "tokyo"
    assert "master" in s.note_plans


def test_get_shop_unknown() -> None:
    with pytest.raises(KeyError):
        get_shop("not_exist")


def test_all_shop_ids() -> None:
    ids = all_shop_ids()
    assert "kingsetagaya" in ids
    assert "espas_seibushinjuku" in ids
'''

# ============================================================
# 実行ロジック
# ============================================================
def main() -> None:
    print("=" * 60)
    print("Juggler Predictor: Phase 1 セットアップ開始")
    print(f"Root: {ROOT}")
    print("=" * 60)

    # 1. ディレクトリ作成
    for d in DIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    print(f"[OK] ディレクトリ作成完了 ({len(DIRS)} 個)")

    # 2. 空ファイル
    for f in EMPTY_FILES:
        path = ROOT / f
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
    print(f"[OK] 空ファイル作成完了 ({len(EMPTY_FILES)} 個)")

    # 3. 内容ありファイル(UTF-8 BOMなし)
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # 改行コードは LF 統一(GitHub / Linux 互換のため)
        content_lf = content.replace("\r\n", "\n").replace("\r", "\n")
        path.write_text(content_lf, encoding="utf-8", newline="\n")
    print(f"[OK] 内容ありファイル書き込み完了 ({len(FILES)} 個)")

    # 4. 完了サマリ
    print()
    print("=" * 60)
    print("[SUCCESS] Phase 1 ファイル生成 完了")
    print("=" * 60)
    print()
    print("次のステップ:")
    print(f"  1. cd {ROOT}")
    print("  2. uv sync --extra dev")
    print("  3. uv run pytest")
    print("  4. git init && git add -A && git commit -m \"P1: project skeleton\"")
    print("  5. git remote add origin https://github.com/<your-account>/juggler_predictor.git")
    print("  6. git branch -M main && git push -u origin main")
    print()


if __name__ == "__main__":
    main()
