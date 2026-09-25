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

set "PYTHON_EXE="
set "PYTHON_ARGS="
set "PYTHON_SOURCE="

:: Prefer the project-local environment so dependency checks and launch use
:: the exact same interpreter, even when Python is missing from PATH.
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
    set "PYTHON_SOURCE=project .venv"
)

if not defined PYTHON_EXE (
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        py -3 --version >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=py"
            set "PYTHON_ARGS=-3"
            set "PYTHON_SOURCE=Python Launcher"
        )
    )
)

if not defined PYTHON_EXE (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
        set "PYTHON_SOURCE=PATH"
    )
)

:: Codex Desktop ships an isolated Python runtime. Use it only as a bootstrap
:: to create .venv; normal launches will then take the first branch above.
if not defined PYTHON_EXE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    set "PYTHON_SOURCE=Codex runtime bootstrap"
)

if not defined PYTHON_EXE (
    echo [FATAL] Python 3 not found and project .venv is missing.
    echo         Install Python 3.10+ or create: .venv\Scripts\python.exe
    goto :error_exit
)

"%PYTHON_EXE%" %PYTHON_ARGS% --version >nul 2>&1
if errorlevel 1 (
    echo [FATAL] Resolved Python interpreter cannot run: %PYTHON_EXE%
    goto :error_exit
)

for /f "tokens=2 delims= " %%v in ('"%PYTHON_EXE%" %PYTHON_ARGS% --version 2^>^&1') do set "PY_VER=%%v"
echo       OK - Python !PY_VER! ^(!PYTHON_SOURCE!^)

:: ------ [3/5] Dependencies ------
echo [3/5] Checking dependencies...

set "MISSING="

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import fastapi" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! fastapi"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import uvicorn" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! uvicorn"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import pandas" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! pandas"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import numpy" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! numpy"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import pyarrow" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! pyarrow"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import simplejson" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! simplejson"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import tushare" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! tushare"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import multipart" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! python-multipart"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import scipy" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! scipy"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import requests" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! requests"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import dotenv" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! python-dotenv"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import fredapi" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! fredapi"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import redis" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! redis"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import apscheduler" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! apscheduler"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sklearn" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! scikit-learn"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import yfinance" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! yfinance"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import akshare" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! akshare"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import httpx" >nul 2>&1
if errorlevel 1 set "MISSING=!MISSING! httpx"

if not "!MISSING!"=="" (
    echo [WARN] Missing:!MISSING!
    set /p "YN=       Auto-install? (Y/N): "
    if /i "!YN!"=="Y" (
        if not exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
            echo       Creating project virtual environment...
            "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%PROJECT_DIR%\.venv"
            if errorlevel 1 (
                echo [FATAL] Failed to create project virtual environment.
                goto :error_exit
            )
        )
        set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
        set "PYTHON_ARGS="
        set "PYTHON_SOURCE=project .venv"
        "%PYTHON_EXE%" -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [FATAL] Install failed. Run manually:
            echo         .venv\Scripts\python.exe -m pip install -r requirements.txt
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

"%PYTHON_EXE%" %PYTHON_ARGS% -m uvicorn %APP_MODULE% --host %HOST% --port %PORT%

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
