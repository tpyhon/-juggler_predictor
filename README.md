# Juggler Predictor

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
