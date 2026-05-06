"""R2 内のオブジェクトキー命名規約を一元管理する。

すべてのレイヤーは直接 ``f"raw/{shop}/..."`` のような文字列を組み立てず、
このモジュール経由でキーを生成する。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R2Paths:
    """R2 オブジェクトキー命名規約。"""

    # ---- 認証 (cf_clearance クッキー) ----
    @staticmethod
    def cf_cookie_latest() -> str:
        return "auth/cf_cookies.json"

    @staticmethod
    def cf_cookie_backup(date_str: str) -> str:
        """``date_str`` は ``YYYYMMDD`` 形式。"""
        return f"auth/cf_cookies_{date_str}.json"

    # ---- 生 HTML ----
    @staticmethod
    def raw_html(shop_id: str, date_str: str) -> str:
        """``date_str`` は ``YYYY-MM-DD`` 形式。gzip 圧縮想定。"""
        return f"raw/{shop_id}/{date_str}.html.gz"

    # ---- パース後 JSON ----
    @staticmethod
    def dataset_json(shop_id: str, date_str: str) -> str:
        return f"dataset/{shop_id}/{date_str}.json.gz"

    # ---- 予測キャッシュ ----
    @staticmethod
    def pred_cache(shop_id: str, date_str: str) -> str:
        return f"pred_cache/{shop_id}/{date_str}.json"

    # ---- ML モデル ----
    @staticmethod
    def model_bundle(name: str = "ALL") -> str:
        return f"models/model_bundle__{name}.joblib"

    # ---- 記事 ----
    @staticmethod
    def article_md(shop_id: str, date_str: str) -> str:
        return f"articles/{shop_id}/{date_str}.md"

    # ---- 公開済みURL記録 ----
    @staticmethod
    def published_log(date_str: str) -> str:
        return f"reports/published/{date_str}.json"

    # ---- マーカー (ingest 完了印) ----
    @staticmethod
    def ingest_marker(shop_id: str, date_str: str) -> str:
        return f"markers/ingest/{shop_id}/{date_str}.ok"

    @staticmethod
    def publish_marker(shop_id: str, date_str: str) -> str:
        return f"markers/publish/{shop_id}/{date_str}.ok"
