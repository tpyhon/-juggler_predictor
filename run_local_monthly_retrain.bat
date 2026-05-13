@echo off
REM 月次再学習バッチ: 学習 + R2 アップロード
REM タスクスケジューラ推奨時刻: 毎月2日 04:00 JST
setlocal

wsl --cd /home/takum/juggler_predictor bash -lc "uv run python tools/local_monthly_retrain.py %*"

exit /b %ERRORLEVEL%
