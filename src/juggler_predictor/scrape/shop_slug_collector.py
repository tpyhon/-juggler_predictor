"""東京都ホール一覧ページから店舗 slug を抽出する。

ana-slo.com の店舗一覧 URL パターン:
    https://ana-slo.com/ホールデータ/東京都/<slug>-データ一覧/

URL は実際には %e3%83%9b... (小文字 hex) または %E3%83%9B... (大文字 hex) の
パーセントエンコード形式で入っているため正規表現は両対応にする。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# パーセントエンコードされた "ホールデータ" / "東京都" / "データ一覧"
# 大文字 hex / 小文字 hex の両方を許容する
_HOLE_DATA_ENC = "(?:ホールデータ|(?:%[0-9a-fA-F]{2}){5,})"
_TOKYO_ENC = "(?:東京都|(?:%[0-9a-fA-F]{2}){3,})"
_LIST_SUFFIX_ENC = "(?:データ一覧|(?:%[0-9a-fA-F]{2}){3,})"

SHOP_LIST_PATH_RE = re.compile(
    rf"^/{_HOLE_DATA_ENC}/{_TOKYO_ENC}/(.+?)-{_LIST_SUFFIX_ENC}/?$"
)


@dataclass(frozen=True)
class ShopCandidate:
    """店舗一覧から発見した候補。"""

    display_name: str
    slug: str
    href: str
    ward: str | None = None  # 区名 (取得できれば)


def extract_shop_candidates(
    html: str, *, base_url: str = "https://ana-slo.com"
) -> list[ShopCandidate]:
    """東京都ホール一覧 HTML から店舗候補を抽出する。slug 単位で重複除去。"""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[ShopCandidate] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = urlparse(href).path or href
        m = SHOP_LIST_PATH_RE.match(path)
        if not m:
            continue
        slug_raw = m.group(1)
        # "ホールデータ" / "東京都" を含むスラッグ部分は本当は来ないはずだが、
        # 念のため空判定する
        if not slug_raw:
            continue
        slug = unquote(slug_raw)
        if slug in seen:
            continue
        seen.add(slug)

        text = a.get_text(strip=True) or slug
        ward = _find_ward_for_anchor(a)
        out.append(ShopCandidate(display_name=text, slug=slug, href=href, ward=ward))

    logger.info("店舗候補抽出: %d 件", len(out))
    return out


def _find_ward_for_anchor(anchor) -> str | None:
    """同じ table-row 内の隣セルから区名を拾う。

    HTML 構造例:
        <div class="table-row">
          <div class="table-data-cell"><a href="...">店舗名</a></div>
          <div class="table-data-cell">世田谷区</div>
        </div>
    """
    row = anchor
    for _ in range(4):  # 4 階層上まで遡る
        if row is None:
            break
        try:
            classes = row.get("class") or []
        except Exception:
            classes = []
        if "table-row" in classes:
            cells = row.find_all("div", class_="table-data-cell")
            for c in cells:
                txt = c.get_text(strip=True)
                if txt and txt.endswith(("区", "市", "町", "村")) and len(txt) <= 8:
                    return txt
            return None
        row = row.parent
    return None
