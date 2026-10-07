@echo off
setlocal EnableExtensions
title ClawCV - Supervised Interview

cd /d "%~dp0"
set "APP_ROOT=%~dp0"

if not exist "%APP_ROOT%main.py" (
    echo ERROR: main.py was not found in %APP_ROOT%
    pause
    exit /b 1
)

if not exist "%APP_ROOT%python\python.exe" (
    echo ERROR: Embedded Python runtime was not found.
    echo Expected: %APP_ROOT%python\python.exe
    pause
    exit /b 1
)

if not exist "%APP_ROOT%.env" (
    echo WARNING: .env was not found. AI configuration may be unavailable.
)

echo.
echo Starting ClawCV...
echo URL: http://127.0.0.1:8787
echo Close this window or press Ctrl+C to stop the server.
echo.

"%APP_ROOT%python\python.exe" -B "%APP_ROOT%main.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo ClawCV stopped.
) else (
    echo ClawCV stopped with error code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
