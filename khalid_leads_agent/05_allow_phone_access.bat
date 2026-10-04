@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

rem Needs administrator rights to add a Windows Firewall rule: ask for them once.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator rights ...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "PORT=8765"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if /i "%%a"=="APP_PORT" set "PORT=%%b"
    )
)

echo Allowing Tailscale devices (100.64.0.0/10) to open Khalid Leads Agent on port !PORT! ...
netsh advfirewall firewall delete rule name="Khalid Leads Agent (Tailscale)" >nul 2>&1
netsh advfirewall firewall add rule name="Khalid Leads Agent (Tailscale)" dir=in action=allow protocol=TCP localport=!PORT! remoteip=100.64.0.0/10 profile=any
if errorlevel 1 (
    echo [ERROR] Could not add the firewall rule.
) else (
    echo Done. Other devices ^(not on Tailscale^) are still blocked.
)
echo.
pause
exit /b 0
