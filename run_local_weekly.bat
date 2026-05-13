@echo off
REM 週次バッチ: 週次レポート生成 + Note 投稿
REM タスクスケジューラ推奨時刻: 毎週月曜 08:30 JST
setlocal

wsl --cd /home/takum/juggler_predictor bash -lc "uv run python tools/local_weekly.py %*"

exit /b %ERRORLEVEL%
