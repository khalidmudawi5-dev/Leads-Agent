@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Khalid Leads Agent - reset sign-in (forgot password)
echo  This turns the username/password sign-in OFF on this PC.
echo  Then open the agent and set a new password in: Settings ^> Security.
echo.
if not exist "data\login.json" (
    echo  Sign-in is not turned on. Nothing to do.
    echo.
    pause
    exit /b 0
)
set /p CONFIRM=Type YES to reset: 
if /i not "%CONFIRM%"=="YES" (
    echo  Cancelled.
    pause
    exit /b 0
)
del "data\login.json" >nul 2>&1
if exist "data\login-secret.bin" del "data\login-secret.bin" >nul 2>&1
echo  Done. Sign-in is OFF. Refresh the agent page (F5).
echo.
pause
