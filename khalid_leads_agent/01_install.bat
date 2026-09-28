@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo   Khalid Leads Agent - Installation
echo ==========================================================

set "PY="
py -3.13 -c "import sys" >nul 2>&1
if %errorlevel%==0 (set "PY=py -3.13" & goto :havepy)
py -3.12 -c "import sys" >nul 2>&1
if %errorlevel%==0 (set "PY=py -3.12" & goto :havepy)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if %errorlevel%==0 (set "PY=python" & goto :havepy)
echo [ERROR] Python 3.12 or newer was not found.
echo         Install it from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH" during installation.
pause
exit /b 1

:havepy
echo [1/5] Using Python: %PY%
if not exist ".venv\Scripts\python.exe" (
    echo [2/5] Creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [2/5] Virtual environment already exists.
)

echo [3/5] Installing Python packages ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [4/5] Installing Playwright Chromium ...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :fail

echo [5/5] Creating folders and .env ...
for %%d in (data data\credentials data\browser-profile logs logs\screenshots logs\snapshots) do if not exist "%%d" mkdir "%%d"
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo        .env created from .env.example
) else (
    echo        .env already exists - not changed.
)

echo.
echo Installation completed successfully.
echo Next step: run 02_start_agent.bat
pause
exit /b 0

:fail
echo.
echo [ERROR] Installation failed. Check the messages above (internet connection / Python version).
pause
exit /b 1
