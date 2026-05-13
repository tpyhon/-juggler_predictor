"""Markdown を Note エディタ形式 HTML に変換。"""
from __future__ import annotations

import re
import uuid


def markdown_to_note_html(text: str) -> str:
    """Markdown 本文を Note の draft_save body 用 HTML に変換。

    対応書式:
      - 空行 -> <p><br></p>
      - ## h2 / ### h3
      - - / * 箇条書き -> <ul><li>...</li></ul>
      - **太字** -> <strong>
      - 通常段落 -> <p>
    """
    lines = text.split("\n")
    parts: list[str] = []

    for line in lines:
        uid = str(uuid.uuid4())
        if not line.strip():
            parts.append(f'<p name="{uid}" id="{uid}"><br></p>')
        elif line.startswith("## "):
            content = line[3:].strip()
            parts.append(f'<h2 name="{uid}" id="{uid}">{content}</h2>')
        elif line.startswith("### "):
            content = line[4:].strip()
            parts.append(f'<h3 name="{uid}" id="{uid}">{content}</h3>')
        elif line.startswith("- ") or line.startswith("* "):
            content = line[2:].strip()
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            parts.append(f'<ul><li name="{uid}" id="{uid}">{content}</li></ul>')
        else:
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            parts.append(f'<p name="{uid}" id="{uid}">{content}</p>')

    return "".join(parts)
