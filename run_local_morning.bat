@echo off
setlocal

cd /d "C:\Users\takum\Desktop\code\juggler_predictor"

if not exist logs mkdir logs

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i

set PATH=%USERPROFILE%\.local\bin;%PATH%

uv run python tools\local_morning.py >> logs\local_morning_%TODAY%.log 2>&1

exit /b %ERRORLEVEL%
