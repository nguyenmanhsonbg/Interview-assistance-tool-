@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0python\python.exe" (
  echo Embedded Python runtime is missing.
  pause
  exit /b 1
)
"%~dp0python\python.exe" -B "%~dp0main.py"
if errorlevel 1 pause
endlocal
