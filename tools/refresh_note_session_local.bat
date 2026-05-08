@echo off
REM Note セッション cookie を手動更新する (ローカル PC 用)
REM 使い方: tools\refresh_note_session_local.bat
cd /d "%~dp0\.."
echo === Note Session Refresh (Local) ===
uv run python scripts/refresh_note_session.py --headed
if errorlevel 1 (
    echo [FAIL] cookie refresh failed
    pause
    exit /b 1
)
uv run python tools/check_note_session.py
echo === Done ===
pause
