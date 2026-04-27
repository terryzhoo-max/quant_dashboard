@echo off
setlocal enabledelayedexpansion

:: AlphaCore Push Script v2.2
:: quant_dashboard repo: d:\FIONA\google AI\quant_dashboard
:: NEWS repo:            d:\FIONA\google AI

echo.
echo  ========================================
echo    AlphaCore Push v2.2
echo  ========================================
echo.

set "ROOT=d:\FIONA\google AI"
set "QD_DIR=%ROOT%\quant_dashboard"
set "PUSH_COUNT=0"
set "FAIL_COUNT=0"
set "QD_MSG="
set "NEWS_MSG="

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] git not found
    goto :FAIL_EXIT
)

:: ========================================
::  STEP 1: quant_dashboard (Server Deploy)
:: ========================================
echo ----------------------------------------
echo  [1/2] quant_dashboard
echo ----------------------------------------

cd /d "%QD_DIR%"
if %errorlevel% neq 0 (
    echo [ERROR] Cannot enter: %QD_DIR%
    goto :FAIL_EXIT
)

git add -A 2>nul

git diff --cached --quiet
if %errorlevel%==0 goto :QD_SKIP

echo   Changed files:
git diff --cached --stat
echo.

set /p "QD_MSG=  Commit message (Enter=daily update): "
if "!QD_MSG!"=="" set "QD_MSG=update: daily update"

git commit -m "!QD_MSG!"
if %errorlevel% neq 0 (
    echo   [WARN] commit failed
    set /a FAIL_COUNT+=1
    goto :STEP2
)

echo.
echo   Pushing to quant_dashboard (server)...
git push origin main
if %errorlevel%==0 (
    echo   [OK] quant_dashboard push success
    set /a PUSH_COUNT+=1
) else (
    echo   [FAIL] quant_dashboard push failed
    set /a FAIL_COUNT+=1
)
echo.
goto :STEP2

:QD_SKIP
echo   No changes
echo.

:: ========================================
::  STEP 2: NEWS (Archive)
:: ========================================
:STEP2
echo ----------------------------------------
echo  [2/2] NEWS
echo ----------------------------------------

cd /d "%ROOT%"

git add -A 2>nul

git diff --cached --quiet
if %errorlevel%==0 goto :NEWS_SKIP

echo   Changed files:
git diff --cached --stat
echo.

if defined QD_MSG echo   Hint: last msg = "!QD_MSG!"
set /p "NEWS_MSG=  Commit message (Enter=reuse last): "
if "!NEWS_MSG!"=="" (
    if defined QD_MSG (
        set "NEWS_MSG=!QD_MSG!"
    ) else (
        set "NEWS_MSG=update: daily update"
    )
)

git commit -m "!NEWS_MSG!"
if %errorlevel% neq 0 (
    echo   [WARN] commit failed
    set /a FAIL_COUNT+=1
    goto :SUMMARY
)

echo.
echo   Pushing to NEWS...
git push "git@github.com-terryzhoo-max/NEWS.git" main
if %errorlevel%==0 (
    echo   [OK] NEWS push success
    set /a PUSH_COUNT+=1
    goto :SUMMARY
)

echo   [WARN] SSH failed, trying origin...
git push origin main
if %errorlevel%==0 (
    echo   [OK] NEWS push success via origin
    set /a PUSH_COUNT+=1
) else (
    echo   [FAIL] NEWS push failed
    set /a FAIL_COUNT+=1
)
echo.
goto :SUMMARY

:NEWS_SKIP
echo   No changes
echo.

:: ========================================
::  SUMMARY
:: ========================================
:SUMMARY
echo.
echo ========================================
if !FAIL_COUNT!==0 (
    echo  [OK] All done - pushed !PUSH_COUNT! repos
) else (
    echo  [WARN] Done with !FAIL_COUNT! errors
)
echo.
if !PUSH_COUNT! gtr 0 (
    echo  Deploy: ssh server, run bash /root/update.sh
)
echo ========================================
echo.
pause
endlocal
exit /b 0

:FAIL_EXIT
echo.
pause
endlocal
exit /b 1
