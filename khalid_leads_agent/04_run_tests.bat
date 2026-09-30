@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Please run 01_install.bat first.
    pause
    exit /b 1
)
echo Running tests (mocks only - no real Google Sheet or Odoo data is touched) ...
".venv\Scripts\python.exe" -m pytest -v
echo.
if errorlevel 1 (echo Some tests FAILED.) else (echo All tests passed.)
pause
