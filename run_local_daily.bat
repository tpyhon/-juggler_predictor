@echo off
REM 日次バッチ: 記事生成 + Note 投稿
REM スクレイピング (run_local_morning.bat) の完了後に実行すること
REM タスクスケジューラ推奨時刻: 毎朝 08:30 JST
setlocal

wsl --cd /home/takum/juggler_predictor bash -lc "uv run python tools/local_daily.py %*"

exit /b %ERRORLEVEL%
