"""JSON I/O. atomic write, gzip 対応."""
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
