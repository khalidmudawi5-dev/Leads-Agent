@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PORT=8765"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if /i "%%a"=="APP_PORT" set "PORT=%%b"
    )
)
echo Stopping Khalid Leads Agent on port !PORT! ...
powershell -NoProfile -Command "try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:!PORT!/api/admin/shutdown' -Headers @{'X-KLA'='1'} -TimeoutSec 5 | Out-Null; Write-Host 'Graceful stop requested.' } catch { Write-Host 'Agent did not answer (maybe already stopped).' }"
timeout /t 4 >nul
if exist "data\agent.pid" (
    set /p AGENT_PID=<"data\agent.pid"
    taskkill /PID !AGENT_PID! /T /F >nul 2>&1
    del "data\agent.pid" >nul 2>&1
)
echo Done.
timeout /t 2 >nul
exit /b 0
