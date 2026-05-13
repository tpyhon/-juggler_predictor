"""保存済み HTML の構造を詳しく分析する.

実行前提: tools/samples/kingsetagaya_2026-05-05_via_curl.html が存在
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

HTML_PATH = Path(__file__).resolve().parent / "samples" / "kingsetagaya_2026-05-05_via_curl.html"
OUT_PATH = Path(__file__).resolve().parent / "samples" / "structure_analysis.txt"


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    lines: list[str] = []

    def echo(s: str = "") -> None:
        print(s)
        lines.append(s)

    echo("=" * 70)
    echo("HTML 構造分析")
    echo("=" * 70)

    # ----- 1. 見出し一覧 -----
    echo("")
    echo("--- 見出し (h1〜h4) ---")
    for level in range(1, 5):
        for h in soup.find_all(f"h{level}"):
            text = h.get_text(strip=True)[:80]
            cls = h.get("class")
            echo(f"  <h{level} class={cls}>: {text}")

    # ----- 2. table 構造の代表例 (最初の 5 個) -----
    echo("")
    echo("--- 最初の 5 個の <table> -----")
    for i, t in enumerate(soup.find_all("table")[:5]):
        cls = t.get("class")
        n_rows = len(t.find_all("tr"))
        n_cols = len(t.find_all("th") or t.find_all("td"))
        # 直前の見出しを探す(機種名と紐付くか確認)
        prev_h = t.find_previous(["h1", "h2", "h3", "h4"])
        prev_text = prev_h.get_text(strip=True)[:50] if prev_h else "(none)"
        echo(f"  table[{i}] class={cls}, rows={n_rows}")
        echo(f"    直前見出し: {prev_text}")
        # ヘッダー行
        first_tr = t.find("tr")
        if first_tr:
            headers = [c.get_text(strip=True) for c in first_tr.find_all(["th", "td"])]
            echo(f"    ヘッダ行: {headers}")
        # データ行 1 つ目
        data_trs = t.find_all("tr")[1:2]
        for tr in data_trs:
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            echo(f"    データ行例: {cells}")

    # ----- 3. ジャグラー機種名でテーブルを発見 -----
    echo("")
    echo("--- 'ジャグラー' を含む見出し → 直後の table ---")
    juggler_headings = []
    for tag_name in ["h1", "h2", "h3", "h4"]:
        for h in soup.find_all(tag_name):
            txt = h.get_text(strip=True)
            if "ジャグラー" in txt:
                juggler_headings.append((tag_name, txt, h))
    echo(f"  ジャグラー見出し数: {len(juggler_headings)}")
    for tag_name, txt, h in juggler_headings[:5]:
        next_table = h.find_next("table")
        echo(f"  <{tag_name}>: {txt[:60]}")
        if next_table:
            first_tr = next_table.find("tr")
            if first_tr:
                cells = [c.get_text(strip=True) for c in first_tr.find_all(["th", "td"])]
                echo(f"     直後 table ヘッダ: {cells}")
            data_tr = next_table.find_all("tr")[1] if len(next_table.find_all("tr")) > 1 else None
            if data_tr:
                cells = [c.get_text(strip=True) for c in data_tr.find_all(["td", "th"])]
                echo(f"     データ行 例:     {cells}")

    # ----- 4. マイジャグラー周辺 (具体例) -----
    echo("")
    echo("--- 'マイジャグラー' 周辺の HTML 抜粋 ---")
    idx = html.find("マイジャグラー")
    if idx > 0:
        echo(html[max(0, idx - 200):idx + 1500])

    # ----- 5. 重要キーワードの出現位置 -----
    echo("")
    echo("--- 重要キーワード位置 ---")
    for kw in ["台番号", "台番", "機種名", "総ゲーム数", "G数", "BB回数",
               "RB回数", "差枚", "差枚数", "ボーナス合算", "合成確率"]:
        idx = html.find(kw)
        echo(f"  '{kw}': {'見つかった (位置 ' + str(idx) + ')' if idx >= 0 else '見つからず'}")

    # ----- 6. class 名の頻度 (parser に使えるかも) -----
    echo("")
    echo("--- 主要 class 名 TOP20 (table/tr/td/div 内) ---")
    class_counter: dict[str, int] = {}
    for el in soup.find_all(["table", "tr", "td", "div", "section"]):
        for c in el.get("class") or []:
            class_counter[c] = class_counter.get(c, 0) + 1
    sorted_classes = sorted(class_counter.items(), key=lambda x: -x[1])[:20]
    for c, n in sorted_classes:
        echo(f"  .{c}: {n}")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[SAVE] {OUT_PATH}")


if __name__ == "__main__":
    main()
