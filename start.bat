@echo off
setlocal
cd /d "%~dp0"
title MyAgent Unified Console

echo ===================================================
echo       MyAgent Unified RealityPatch Agent
echo ===================================================
echo.

set PY_CMD=
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PY_CMD=py -3
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set PY_CMD=python
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python environment not found! Please install Python 3.9+ and add to PATH.
    pause
    exit /b 1
)

echo [1/2] Python: %PY_CMD%
echo.
echo [2/2] Starting MyAgent Unified Server...
echo ---------------------------------------------------
echo  * Web UI:    http://127.0.0.1:8091/
echo  * Health:    http://127.0.0.1:8091/health
echo ---------------------------------------------------
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8091/"

%PY_CMD% app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Server stopped with error code %ERRORLEVEL%.
    pause
)
