@echo off
REM ============================================================
REM ????????: PowerShell ??? uv ??????
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set LOGFILE=logs\local_morning_%date:~0,4%%date:~5,2%%date:~8,2%.log

echo ====================================== >> "%LOGFILE%"
echo Local Morning Batch start at %date% %time% >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"

REM PowerShell ??? uv ??? (PATH ?????)
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { Set-Location '%~dp0'; uv run python tools/local_morning.py }" >> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%

echo Local Morning Batch end rc=%RC% at %date% %time% >> "%LOGFILE%"
endlocal & exit /b %RC%
