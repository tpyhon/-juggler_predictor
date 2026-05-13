@echo off
REM 朝バッチ: スクレイピング (毎朝 07:00 JST 推奨)
REM タスクスケジューラから呼び出す。ログは WSL 側の logs/ に保存される。
setlocal

wsl --cd /home/takum/juggler_predictor bash -lc "uv run python tools/local_morning.py"

exit /b %ERRORLEVEL%
