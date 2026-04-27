@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ═══════════════════════════════════════════════════════════════
::  AlphaCore 一键推送 v2.0
::  架构: 双仓库 (NEWS + quant_dashboard) 同步推送
::  NEWS 仓库:           d:\FIONA\google AI
::  quant_dashboard 仓库: d:\FIONA\google AI\quant_dashboard
:: ═══════════════════════════════════════════════════════════════

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║     AlphaCore 一键推送 v2.0              ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ─── 全局变量 ────────────────────────────────────────────────
set "ROOT=d:\FIONA\google AI"
set "QD_DIR=%ROOT%\quant_dashboard"
set "PUSH_COUNT=0"
set "FAIL_COUNT=0"

:: ─── 预检: Git 是否可用 ──────────────────────────────────────
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 git, 请确认已安装并加入 PATH
    pause
    exit /b 1
)

:: ═══════════════════════════════════════════════════════════════
::  STEP 1: quant_dashboard 仓库 (服务器部署用)
:: ═══════════════════════════════════════════════════════════════
echo ──────────────────────────────────────────
echo  [1/2] quant_dashboard 仓库
echo ──────────────────────────────────────────

cd /d "%QD_DIR%"
if %errorlevel% neq 0 (
    echo [错误] 无法进入目录: %QD_DIR%
    pause
    exit /b 1
)

:: 暂存代码文件 (排除 data_lake, .env, .parquet 等已被 .gitignore 忽略的文件)
:: 使用 git add -A 来捕获所有变更(新增/修改/删除), .gitignore 会自动过滤
git add -A 2>nul

:: 检查是否有变更
git diff --cached --quiet
if %errorlevel%==0 (
    echo   没有新的代码变更
    echo.
) else (
    echo   变更文件:
    git diff --cached --stat
    echo.

    :: 提示输入 commit 信息
    set /p "QD_MSG=  请输入提交说明 (回车=日常更新): "
    if "!QD_MSG!"=="" set "QD_MSG=update: 日常更新"

    :: 提交
    git commit -m "!QD_MSG!"
    if %errorlevel% neq 0 (
        echo   [警告] commit 失败
        set /a FAIL_COUNT+=1
        goto :STEP2
    )

    :: 推送
    echo.
    echo   推送到 quant_dashboard (服务器)...
    git push origin main
    if %errorlevel%==0 (
        echo   ✅ quant_dashboard 推送成功
        set /a PUSH_COUNT+=1
    ) else (
        echo   ❌ quant_dashboard 推送失败
        set /a FAIL_COUNT+=1
    )
    echo.
)

:: ═══════════════════════════════════════════════════════════════
::  STEP 2: NEWS 仓库 (全量归档)
:: ═══════════════════════════════════════════════════════════════
:STEP2
echo ──────────────────────────────────────────
echo  [2/2] NEWS 仓库
echo ──────────────────────────────────────────

cd /d "%ROOT%"

:: NEWS 仓库: 暂存全部变更 (.gitignore 已配置排除规则)
git add -A 2>nul

:: 检查是否有变更
git diff --cached --quiet
if %errorlevel%==0 (
    echo   没有新的代码变更
    echo.
) else (
    echo   变更文件:
    git diff --cached --stat
    echo.

    :: 提示输入 commit 信息 (可复用上一条)
    if defined QD_MSG (
        echo   提示: 上一条提交说明为 "!QD_MSG!"
    )
    set /p "NEWS_MSG=  请输入提交说明 (回车=复用上条或'日常更新'): "
    if "!NEWS_MSG!"=="" (
        if defined QD_MSG (
            set "NEWS_MSG=!QD_MSG!"
        ) else (
            set "NEWS_MSG=update: 日常更新"
        )
    )

    :: 提交
    git commit -m "!NEWS_MSG!"
    if %errorlevel% neq 0 (
        echo   [警告] commit 失败
        set /a FAIL_COUNT+=1
        goto :SUMMARY
    )

    :: 推送
    echo.
    echo   推送到 NEWS...
    git push "git@github.com-terryzhoo-max/NEWS.git" main
    if %errorlevel%==0 (
        echo   ✅ NEWS 推送成功
        set /a PUSH_COUNT+=1
    ) else (
        echo   ❌ NEWS 推送失败, 尝试 origin...
        git push origin main
        if %errorlevel%==0 (
            echo   ✅ NEWS 推送成功 (via origin)
            set /a PUSH_COUNT+=1
        ) else (
            echo   ❌ NEWS 推送失败
            set /a FAIL_COUNT+=1
        )
    )
    echo.
)

:: ═══════════════════════════════════════════════════════════════
::  SUMMARY
:: ═══════════════════════════════════════════════════════════════
:SUMMARY
echo ══════════════════════════════════════════
if %FAIL_COUNT%==0 (
    echo  ✅ 全部完成! 成功推送 %PUSH_COUNT% 个仓库
) else (
    echo  ⚠️  完成, 但有 %FAIL_COUNT% 个错误, 请检查上方日志
)
echo.
if %PUSH_COUNT% gtr 0 (
    echo  部署提示: 服务器执行 bash /root/update.sh 即可更新
)
echo ══════════════════════════════════════════
echo.
pause
endlocal
