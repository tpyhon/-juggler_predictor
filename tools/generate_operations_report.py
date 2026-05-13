"""運用レポートを PDF で生成する。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "operations_report.pdf"

HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Yu Gothic", "游ゴシック", "Meiryo", "メイリオ", sans-serif;
    font-size: 11pt;
    color: #1a1a1a;
    line-height: 1.7;
    padding: 28mm 22mm 28mm 22mm;
  }
  h1 {
    font-size: 20pt;
    font-weight: bold;
    border-bottom: 3px solid #1565c0;
    padding-bottom: 8px;
    margin-bottom: 6px;
    color: #0d47a1;
  }
  .subtitle {
    color: #555;
    font-size: 10pt;
    margin-bottom: 28px;
  }
  h2 {
    font-size: 14pt;
    font-weight: bold;
    color: #0d47a1;
    margin-top: 28px;
    margin-bottom: 10px;
    border-left: 5px solid #1565c0;
    padding-left: 10px;
  }
  h3 {
    font-size: 11.5pt;
    font-weight: bold;
    color: #1a237e;
    margin-top: 16px;
    margin-bottom: 6px;
  }
  p { margin-bottom: 8px; }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 18px 0;
    font-size: 10pt;
  }
  th {
    background: #1565c0;
    color: white;
    padding: 7px 10px;
    text-align: left;
    font-weight: bold;
  }
  td {
    padding: 6px 10px;
    border-bottom: 1px solid #ddd;
    vertical-align: top;
  }
  tr:nth-child(even) td { background: #f5f8ff; }
  .badge-auto {
    display: inline-block;
    background: #1b5e20;
    color: white;
    border-radius: 3px;
    padding: 1px 7px;
    font-size: 9pt;
    font-weight: bold;
  }
  .badge-manual {
    display: inline-block;
    background: #b71c1c;
    color: white;
    border-radius: 3px;
    padding: 1px 7px;
    font-size: 9pt;
    font-weight: bold;
  }
  .badge-monthly {
    display: inline-block;
    background: #4a148c;
    color: white;
    border-radius: 3px;
    padding: 1px 7px;
    font-size: 9pt;
    font-weight: bold;
  }
  .section-box {
    background: #fafafa;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 14px 18px;
    margin: 12px 0;
  }
  .warn-box {
    background: #fff8e1;
    border: 1px solid #f9a825;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 12px 0;
    font-size: 10pt;
  }
  ul { padding-left: 20px; margin-bottom: 8px; }
  li { margin-bottom: 4px; }
  code {
    font-family: "Courier New", monospace;
    font-size: 9.5pt;
    background: #eceff1;
    border-radius: 3px;
    padding: 1px 5px;
  }
  .flow {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    margin: 8px 0;
  }
  .flow-step {
    background: #e3f2fd;
    border: 1px solid #90caf9;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 9.5pt;
  }
  .arrow { color: #1565c0; font-weight: bold; font-size: 12pt; }
  .page-break { page-break-before: always; }
  .footer {
    margin-top: 40px;
    padding-top: 10px;
    border-top: 1px solid #ccc;
    font-size: 9pt;
    color: #888;
    text-align: right;
  }
</style>
</head>
<body>

<h1>Juggler Predictor 運用レポート</h1>
<div class="subtitle">更新日: 2026-05-12 ／ 対象環境: Windows 11 + WSL2 (Ubuntu 24.04) + Cloudflare R2 + Slack</div>

<!-- =========================================================
     1. システム概要
     ========================================================= -->
<h2>1. システム概要</h2>
<div class="section-box">
  <p>パチスロ店舗の設定推測モデルを用いて、毎日 Note.com に予測記事を自動投稿するシステム。
  スクレイピング → データ蓄積 → 推論 → 記事生成 → Note 投稿 という一連のパイプラインを、
  Windows タスクスケジューラ + WSL2 で自律運用する。</p>
  <p>データベースには <strong>Cloudflare R2</strong> を使用し、スクレイピングデータ・学習済みモデル・
  生成記事・投稿ログを一元管理する。</p>
</div>

<h3>主要コンポーネント</h3>
<table>
  <tr><th>コンポーネント</th><th>役割</th><th>場所</th></tr>
  <tr><td>Windows タスクスケジューラ</td><td>バッチ起動トリガー</td><td>Windows 側</td></tr>
  <tr><td>.bat ファイル群</td><td>WSL2 への橋渡し</td><td>プロジェクトルート</td></tr>
  <tr><td>tools/local_*.py</td><td>各バッチ本体（ログ・通知付き）</td><td>WSL2</td></tr>
  <tr><td>scripts/</td><td>スクレイピング・学習・記事生成・投稿</td><td>WSL2</td></tr>
  <tr><td>Cloudflare R2</td><td>永続ストレージ（DB 代替）</td><td>クラウド</td></tr>
  <tr><td>Slack Webhook</td><td>成否通知</td><td>クラウド</td></tr>
</table>

<!-- =========================================================
     2. 自動化されていること
     ========================================================= -->
<h2>2. 自動化されていること</h2>
<p>以下の 4 つのバッチがタスクスケジューラによって自動実行される。<span class="badge-auto">自動</span></p>

<h3>2-1. 朝バッチ（毎朝 07:30 JST）</h3>
<div class="section-box">
  <p><strong>起動: </strong><code>run_local_morning.bat</code> → <code>tools/local_morning.py</code></p>
  <div class="flow">
    <span class="flow-step">cf_clearance 期限チェック</span>
    <span class="arrow">→</span>
    <span class="flow-step">前日データをスクレイピング</span>
    <span class="arrow">→</span>
    <span class="flow-step">R2 に保存</span>
    <span class="arrow">→</span>
    <span class="flow-step">Slack 通知</span>
  </div>
  <ul>
    <li><strong>起動直後に cf_clearance Cookie の残り期限を自動確認</strong> — 残り 48 時間未満で Slack に警告を送信</li>
    <li>対象店舗 17 店舗分の前日実績データを Web スクレイピング</li>
    <li>取得データを <code>R2: data/{shop}/{date}.json</code> に保存</li>
    <li>✅ 成功 / ❌ 失敗を Slack に通知</li>
    <li>ログ: <code>logs/</code>（WSL2 内）に出力</li>
  </ul>
</div>

<h3>2-2. 日次バッチ（毎日 08:00 JST）</h3>
<div class="section-box">
  <p><strong>起動: </strong><code>run_local_daily.bat</code> → <code>tools/local_daily.py</code></p>
  <div class="flow">
    <span class="flow-step">データセット構築</span>
    <span class="arrow">→</span>
    <span class="flow-step">モデル DL (R2)</span>
    <span class="arrow">→</span>
    <span class="flow-step">記事生成 (17 店舗)</span>
    <span class="arrow">→</span>
    <span class="flow-step">記事を R2 にアップロード</span>
    <span class="arrow">→</span>
    <span class="flow-step">Note.com に投稿</span>
    <span class="arrow">→</span>
    <span class="flow-step">Slack 通知</span>
  </div>
  <ul>
    <li>R2 から最新モデルバンドルを取得して推論</li>
    <li>17 店舗分の予測記事を Markdown で生成し R2 に保存</li>
    <li>Note.com API 経由で順次投稿（バッチ間待機・レート制限対応付き）</li>
    <li>投稿済みログを R2 に保存 → 再実行時に重複投稿を自動スキップ</li>
    <li>失敗時は Slack 通知＋ログ確認で手動再実行が可能</li>
  </ul>
</div>

<h3>2-3. 週次バッチ（毎週月曜 09:30 JST）</h3>
<div class="section-box">
  <p><strong>起動: </strong><code>run_local_weekly.bat</code> → <code>tools/local_weekly.py</code></p>
  <div class="flow">
    <span class="flow-step">データセット構築</span>
    <span class="arrow">→</span>
    <span class="flow-step">モデル DL (R2)</span>
    <span class="arrow">→</span>
    <span class="flow-step">週次レポート生成</span>
    <span class="arrow">→</span>
    <span class="flow-step">Note.com に投稿</span>
    <span class="arrow">→</span>
    <span class="flow-step">Slack 通知</span>
  </div>
  <ul>
    <li>直前の完了週（月〜日）の集計レポートを生成</li>
    <li>Note.com に週次まとめ記事として投稿</li>
  </ul>
</div>

<h3>2-4. 月次再学習バッチ（毎月 2 日 04:00 JST）</h3>
<div class="section-box">
  <p><strong>起動: </strong><code>run_local_monthly_retrain.bat</code> → <code>tools/local_monthly_retrain.py</code></p>
  <div class="flow">
    <span class="flow-step">データセット構築</span>
    <span class="arrow">→</span>
    <span class="flow-step">p_win/diff モデル学習</span>
    <span class="arrow">→</span>
    <span class="flow-step">設定分類器学習</span>
    <span class="arrow">→</span>
    <span class="flow-step">モデルを R2 にアップロード</span>
    <span class="arrow">→</span>
    <span class="flow-step">Slack 通知</span>
  </div>
  <ul>
    <li>蓄積された全実績データで LightGBM モデルを再学習</li>
    <li>旧モデルを <code>R2: models/backup/{date}_model_bundle.joblib</code> にバックアップ</li>
    <li>新モデルを <code>R2: models/model_bundle.joblib</code> に本番反映</li>
  </ul>
</div>

<!-- =========================================================
     3. 人間がやること
     ========================================================= -->
<div class="page-break"></div>
<h2>3. 人間がやること</h2>

<h3>3-1. 初期セットアップ（一度だけ）<span class="badge-manual" style="margin-left:8px">手動</span></h3>
<table>
  <tr><th>#</th><th>作業</th><th>備考</th></tr>
  <tr>
    <td>1</td>
    <td>Windows タスクスケジューラに 4 つのタスクを登録</td>
    <td>
      07:30 → <code>run_local_morning.bat</code>（毎日）<br>
      08:00 → <code>run_local_daily.bat</code>（毎日）<br>
      09:30 → <code>run_local_weekly.bat</code>（月曜のみ）<br>
      毎月 2 日 04:00 → <code>run_local_monthly_retrain.bat</code>
    </td>
  </tr>
  <tr>
    <td>2</td>
    <td><code>.env</code> ファイルに認証情報を設定</td>
    <td>R2 認証情報・Note セッション Cookie・Slack Webhook URL</td>
  </tr>
  <tr>
    <td>3</td>
    <td>初回モデル学習の実行確認</td>
    <td><code>run_local_monthly_retrain.bat</code> を手動実行</td>
  </tr>
</table>

<h3>3-2. Cloudflare Cookie（cf_clearance）の更新（月 1 回程度）<span class="badge-monthly" style="margin-left:8px">定期</span></h3>
<div class="section-box">
  <p>スクレイピング対象サイト（ana-slo.com）は Cloudflare で保護されており、
  通過済みの <code>cf_clearance</code> Cookie が必要。期限切れになると全店舗のスクレイピングが
  403 で失敗する。</p>
  <p><strong>期限切れの検知（自動）:</strong> 朝バッチ起動時に残り期限を自動チェックし、
  残り 48 時間未満になると Slack に警告を送信する。</p>
  <p><strong>更新手順:</strong></p>
  <ul>
    <li>Slack の警告を受け取ったら当日中に実行する</li>
    <li>WSL 端末で <code>uv run python scripts/refresh_cf_cookie.py</code> を実行</li>
    <li>Playwright のブラウザが開くので、ana-slo.com をトップ → 東京都 → 店舗 → 日付詳細 の順にクリック</li>
    <li>日付詳細ページに到達すると自動的に Cookie を回収し R2 に保存される</li>
  </ul>
  <div class="warn-box">
    ⚠️ 現状期限の確認: <code>uv run python tools/check_cf_cookie.py</code>
  </div>
</div>

<h3>3-4. Note セッション Cookie の更新（数ヶ月に 1 回）<span class="badge-monthly" style="margin-left:8px">定期</span></h3>
<div class="section-box">
  <p>Note.com のセッション Cookie（<code>_note_session_v5</code>）は一定期間で失効する。
  失効すると投稿バッチが失敗するため、定期的に更新が必要。</p>
  <p><strong>更新手順:</strong></p>
  <ul>
    <li><code>tools\refresh_note_session_local.bat</code> をダブルクリック</li>
    <li>WSLg のブラウザ画面が開くので Note.com にログイン</li>
    <li>ターミナルで Enter を押す → Cookie が自動的に <code>.env</code> と R2 に保存される</li>
  </ul>
  <div class="warn-box">
    ⚠️ GitHub Actions の <strong>Check Note Session</strong> ワークフローが毎月 15 日に自動チェックを行い、
    失効が近い場合は GitHub の通知が届く。通知を受け取ったら上記手順で更新すること。
  </div>
</div>

<h3>3-5. 異常時の対応<span class="badge-manual" style="margin-left:8px">手動</span></h3>
<table>
  <tr><th>症状</th><th>確認場所</th><th>対処</th></tr>
  <tr>
    <td>Slack に失敗通知が来た</td>
    <td><code>logs/local_*.log</code> でエラー確認</td>
    <td>原因解消後、対応する <code>.bat</code> を手動実行（<code>--resume</code> で重複スキップ）</td>
  </tr>
  <tr>
    <td>スクレイピングデータが取れていない</td>
    <td><code>uv run python tools/check_r2_dates.py</code></td>
    <td>サイト構造変更の可能性 → <code>scrape_daily_all.py</code> を確認</td>
  </tr>
  <tr>
    <td>Note 投稿が途中で止まった</td>
    <td><code>logs/local_daily_*.log</code></td>
    <td><code>run_local_daily.bat</code> を再実行（投稿済み記事は自動スキップ）</td>
  </tr>
  <tr>
    <td>モデル精度が下がってきた</td>
    <td>週次レポートの精度グラフ</td>
    <td><code>run_local_monthly_retrain.bat</code> を手動実行して再学習</td>
  </tr>
  <tr>
    <td>WSL2 が起動しない</td>
    <td>Windows の WSL ステータス</td>
    <td>PowerShell で <code>wsl --shutdown</code> → 再起動</td>
  </tr>
</table>

<h3>3-6. 店舗の追加・削除<span class="badge-manual" style="margin-left:8px">手動</span></h3>
<div class="section-box">
  <ul>
    <li><strong>追加:</strong> <code>config/shops.yaml</code> に店舗情報を追記 → <code>scripts/scrape_daily_all.py</code> で動作確認</li>
    <li><strong>削除:</strong> <code>uv run python scripts/remove_shop.py --shop {shop_id}</code> を実行（R2 のデータも削除）</li>
  </ul>
</div>

<!-- =========================================================
     4. バッチスケジュール一覧
     ========================================================= -->
<h2>4. バッチスケジュール一覧</h2>
<table>
  <tr><th>バッチ</th><th>スケジュール</th><th>起動ファイル</th><th>所要時間（目安）</th></tr>
  <tr>
    <td>朝スクレイピング</td>
    <td>毎朝 07:30 JST</td>
    <td><code>run_local_morning.bat</code></td>
    <td>5〜15 分</td>
  </tr>
  <tr>
    <td>記事生成・Note 投稿</td>
    <td>毎日 08:00 JST</td>
    <td><code>run_local_daily.bat</code></td>
    <td>20〜40 分（9 時前完了）</td>
  </tr>
  <tr>
    <td>週次レポート</td>
    <td>毎週月曜 09:30 JST</td>
    <td><code>run_local_weekly.bat</code></td>
    <td>5〜15 分</td>
  </tr>
  <tr>
    <td>月次再学習</td>
    <td>毎月 2 日 04:00 JST</td>
    <td><code>run_local_monthly_retrain.bat</code></td>
    <td>30〜60 分</td>
  </tr>
</table>

<!-- =========================================================
     5. データフロー図
     ========================================================= -->
<h2>5. データフロー</h2>
<div class="section-box">
<table>
  <tr><th>フェーズ</th><th>処理</th><th>入力</th><th>出力 (R2 保存先)</th></tr>
  <tr>
    <td>スクレイピング</td>
    <td><code>scrape_daily_all.py</code></td>
    <td>店舗 Web サイト</td>
    <td><code>data/{shop}/{date}.json</code></td>
  </tr>
  <tr>
    <td>データセット構築</td>
    <td><code>build_dataset.py</code></td>
    <td>R2 の日次データ</td>
    <td><code>dataset/dataset.parquet</code></td>
  </tr>
  <tr>
    <td>モデル学習（月次）</td>
    <td><code>train.py / train_setting.py</code></td>
    <td>dataset.parquet</td>
    <td><code>models/model_bundle.joblib</code></td>
  </tr>
  <tr>
    <td>記事生成</td>
    <td><code>generate_articles_all.py</code></td>
    <td>model_bundle + dataset</td>
    <td><code>articles/{shop}/{date}.md</code></td>
  </tr>
  <tr>
    <td>Note 投稿</td>
    <td><code>post_articles_via_api.py</code></td>
    <td>articles/*.md</td>
    <td><code>post_logs/{date}.json</code></td>
  </tr>
</table>
</div>

<!-- =========================================================
     6. Slack 通知一覧
     ========================================================= -->
<h2>6. Slack 通知一覧</h2>
<p>すべてのバッチ成否が Slack に通知される。<code>SLACK_WEBHOOK_URL</code> を <code>.env</code> に設定済み。</p>
<table>
  <tr><th>送信タイミング</th><th>メッセージ例</th></tr>
  <tr>
    <td>朝スクレイピング 完了</td>
    <td><code>✅ 朝スクレイピング 完了 2026-05-12</code></td>
  </tr>
  <tr>
    <td>朝スクレイピング 失敗</td>
    <td><code>⚠️ 朝スクレイピング 失敗 (rc=1) 2026-05-12</code></td>
  </tr>
  <tr>
    <td>cf_clearance 期限警告（残り 48h 未満）</td>
    <td><code>[警告] cf_clearance の残り有効期限が XX 時間です（期限: YYYY-MM-DD HH:MM JST）。近日中に refresh_cf_cookie.py を実行してください。</code></td>
  </tr>
  <tr>
    <td>cf_clearance 失効済み</td>
    <td><code>[警告] cf_clearance が失効しています。今日のスクレイピングは失敗します。refresh_cf_cookie.py を今すぐ実行してください。</code></td>
  </tr>
  <tr>
    <td>日次バッチ 完了</td>
    <td><code>✅ 日次バッチ完了 2026-05-12 — Note 投稿が完了しました</code></td>
  </tr>
  <tr>
    <td>日次バッチ 失敗</td>
    <td><code>❌ 日次バッチ失敗 [フェーズ名] 2026-05-12</code></td>
  </tr>
  <tr>
    <td>週次レポート 完了</td>
    <td><code>✅ 週次レポート完了 2026-05-12</code></td>
  </tr>
  <tr>
    <td>月次再学習 完了</td>
    <td><code>✅ 月次再学習完了 2026-05-01 — モデルを R2 に反映しました</code></td>
  </tr>
</table>

<!-- =========================================================
     7. 秘密情報の管理
     ========================================================= -->
<h2>7. 秘密情報の管理</h2>
<table>
  <tr><th>項目</th><th>保存場所</th><th>更新タイミング</th></tr>
  <tr>
    <td>R2 認証情報<br>（Endpoint / Access Key / Secret）</td>
    <td><code>.env</code>（WSL2 ローカル）</td>
    <td>Cloudflare ダッシュボードで再発行した時</td>
  </tr>
  <tr>
    <td>Note セッション Cookie<br>（<code>_note_session_v5</code>）</td>
    <td><code>.env</code> + <code>R2: auth/note_storage_state.json</code></td>
    <td>数ヶ月に 1 回 / GitHub 通知を受けたとき</td>
  </tr>
  <tr>
    <td>Slack Webhook URL<br>（<code>SLACK_WEBHOOK_URL</code>）</td>
    <td><code>.env</code>（WSL2 ローカル）<br>設定済み: hooks.slack.com/…</td>
    <td>Slack アプリの削除・再作成時</td>
  </tr>
</table>
<div class="warn-box">
  ⚠️ <code>.env</code> ファイルは <code>.gitignore</code> に含まれており、Git へのコミットは行われない。
  PC 故障・初期化に備え、別途安全な場所（パスワードマネージャー等）にバックアップすること。
</div>

<div class="footer">
  Juggler Predictor Operations Report — updated 2026-05-12
</div>

</body>
</html>
"""


def main() -> None:
    import os
    from pathlib import Path as _P
    from playwright.sync_api import sync_playwright

    # 追加ライブラリを優先して検索させる
    local_lib = str(_P.home() / ".local" / "lib")
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    if local_lib not in existing:
        os.environ["LD_LIBRARY_PATH"] = f"{local_lib}:{existing}" if existing else local_lib

    # headless-shell ではなく通常 chrome バイナリを使う（ライブラリ確認済み）
    chrome_exe = _P.home() / ".cache/ms-playwright/chromium-1217/chrome-linux64/chrome"

    html_path = ROOT / "operations_report.html"
    html_path.write_text(HTML, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=str(chrome_exe),
        )
        page = browser.new_page()
        page.goto(f"file://{html_path}", wait_until="networkidle")
        page.pdf(
            path=str(OUTPUT),
            format="A4",
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"},
            print_background=True,
        )
        browser.close()

    html_path.unlink()
    print(f"[OK] {OUTPUT}")


if __name__ == "__main__":
    main()
