@echo off
REM Note セッション cookie を手動更新する (ローカル PC 用)
REM 使い方: tools\refresh_note_session_local.bat をダブルクリック
REM WSLg のブラウザ画面が開くので note にログインして Enter を押す
setlocal

echo === Note Session Refresh (Local) ===
wsl --cd /home/takum/juggler_predictor bash -lc "uv run python scripts/refresh_note_session.py --headed"
if %ERRORLEVEL% neq 0 (
    echo [FAIL] cookie refresh failed
    pause
    exit /b 1
)
wsl --cd /home/takum/juggler_predictor bash -lc "uv run python tools/check_note_session.py"
echo === Done ===
pause
