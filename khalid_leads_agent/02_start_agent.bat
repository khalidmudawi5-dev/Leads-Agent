@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Please run 01_install.bat first.
    pause
    exit /b 1
)
if not exist ".env" copy ".env.example" ".env" >nul
echo Starting Khalid Leads Agent ...
echo The dashboard will open automatically at http://127.0.0.1:8765
echo (Keep the minimized "Khalid Leads Agent" window open. Use 03_stop_agent.bat to stop.)
start "Khalid Leads Agent" /min ".venv\Scripts\python.exe" run.py
timeout /t 3 >nul
exit /b 0
