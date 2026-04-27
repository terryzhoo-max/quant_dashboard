@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title AlphaCore Quant Server

:: ====== CONFIG ======
set "PROJECT_DIR=d:\FIONA\google AI\quant_dashboard\quant_dashboard"
set "HOST=127.0.0.1"
set "PORT=8000"
set "APP_MODULE=main:app"

echo.
echo ============================================================
echo    AlphaCore Quant Terminal  v15.1
echo    One-Click Server Launcher
echo ============================================================
echo.

:: ------ [1/5] Project Directory ------
echo [1/5] Checking project directory...

if not exist "%PROJECT_DIR%\main.py" (
    echo [FATAL] main.py not found at: %PROJECT_DIR%
    goto :error_exit
)
cd /d "%PROJECT_DIR%"
echo       OK - %PROJECT_DIR%

:: ------ [2/5] Python ------
echo [2/5] Checking Python...

python --version >nul 2>&1
if errorlevel 1 (
    echo [FATAL] Python not found! Install Python 3.10+
    echo         https://www.python.org/downloads/
    goto :error_exit
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo       OK - Python %PY_VER%

:: ------ [3/5] Dependencies ------
echo [3/5] Checking dependencies...

set "MISSING="

python -c "import fastapi" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! fastapi"

python -c "import uvicorn" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! uvicorn"

python -c "import pandas" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! pandas"

python -c "import tushare" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! tushare"

python -c "import dotenv" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! python-dotenv"

python -c "import apscheduler" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! apscheduler"

if not "!MISSING!"=="" (
    echo [WARN] Missing:!MISSING!
    set /p "YN=       Auto-install? (Y/N): "
    if /i "!YN!"=="Y" (
        pip install -r requirements.txt -q
        if errorlevel 1 (
            echo [FATAL] Install failed. Run manually: pip install -r requirements.txt
            goto :error_exit
        )
        echo       OK - Dependencies installed
    ) else (
        echo [FATAL] Missing dependencies. Cannot start.
        goto :error_exit
    )
) else (
    echo       OK - All dependencies ready
)

:: ------ [4/5] Port Check ------
echo [4/5] Checking port %PORT%...

netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [WARN] Port %PORT% is in use!
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
        set "OLD_PID=%%p"
        echo       Occupied by PID: %%p
    )
    set /p "YN=       Kill old process and restart? (Y/N): "
    if /i "!YN!"=="Y" (
        taskkill /F /PID !OLD_PID! >nul 2>&1
        timeout /t 2 /nobreak >nul
        echo       OK - Old process killed
    ) else (
        echo       Cancelled.
        goto :error_exit
    )
)
echo       OK - Port %PORT% available

:: ------ [5/5] .env ------
echo [5/5] Checking .env config...

if exist ".env" (
    echo       OK - .env loaded
) else (
    echo [WARN] .env not found, some features may be limited
)

:: ====== LAUNCH ======
echo.
echo ============================================================
echo   All checks passed - Starting AlphaCore Server...
echo ============================================================
echo.
echo   URL:     http://%HOST%:%PORT%
echo   Health:  http://%HOST%:%PORT%/health
echo   Press Ctrl+C to stop
echo.

python -m uvicorn %APP_MODULE% --host %HOST% --port %PORT%

:: ====== EXIT HANDLING ======
echo.
if errorlevel 1 (
    echo [ERROR] Server exited abnormally (code: %errorlevel%)
) else (
    echo [INFO] AlphaCore server stopped normally.
)
goto :end

:error_exit
echo.
echo ============================================================
echo   STARTUP FAILED - Check errors above
echo ============================================================

:end
echo.
pause
endlocal
