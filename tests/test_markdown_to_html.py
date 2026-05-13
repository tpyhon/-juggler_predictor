"""markdown_to_note_html のテスト。"""
from juggler_predictor.note import markdown_to_note_html


def test_h2_h3():
    md = "## 見出し2\n### 見出し3"
    html = markdown_to_note_html(md)
    assert "<h2 " in html and "見出し2</h2>" in html
    assert "<h3 " in html and "見出し3</h3>" in html


def test_paragraph_and_bold():
    md = "通常文 **太字** 終わり"
    html = markdown_to_note_html(md)
    assert "<p " in html
    assert "<strong>太字</strong>" in html


def test_list_items():
    md = "- 項目1\n- 項目2"
    html = markdown_to_note_html(md)
    assert html.count("<li ") == 2
    assert "項目1</li>" in html
    assert "項目2</li>" in html


def test_empty_lines_become_br():
    md = "段落1\n\n段落2"
    html = markdown_to_note_html(md)
    assert "<br>" in html


def test_unique_uuids():
    """各行に独立した uuid が振られること。"""
    md = "段落1\n段落2\n段落3"
    html = markdown_to_note_html(md)
    # name="..." の数 = 行数
    assert html.count('name="') == 3
