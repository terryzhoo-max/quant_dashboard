@echo off
chcp 65001 >nul
cd /d "d:\FIONA\google AI"

echo.
echo ══════ AlphaCore 一键推送 ══════
echo.

:: 暂存所有代码文件 (排除数据文件)
git add quant_dashboard/*.py quant_dashboard/*.html quant_dashboard/*.sh quant_dashboard/*.md quant_dashboard/*.txt quant_dashboard/*.json quant_dashboard/*.yml quant_dashboard/Dockerfile quant_dashboard/static/ quant_dashboard/routers/ quant_dashboard/services/ quant_dashboard/models/ quant_dashboard/tests/ quant_dashboard/dashboard_modules/ 2>nul

:: 检查是否有变更
git diff --cached --quiet
if %errorlevel%==0 (
    echo 没有新的代码变更需要提交
    pause
    exit /b
)

:: 显示变更
echo 变更文件:
git diff --cached --stat
echo.

:: 提示输入 commit 信息
set /p MSG="请输入提交说明: "
if "%MSG%"=="" set MSG=update: 日常更新

:: 提交
git commit -m "%MSG%"

:: 推送到两个仓库
echo.
echo 推送到 NEWS...
git push "git@github.com-terryzhoo-max/NEWS.git" main

echo 推送到 quant_dashboard (服务器)...
git push "https://github.com/terryzhoo-max/quant_dashboard.git" main

echo.
echo ✅ 推送完成! 服务器执行 bash /root/update.sh 即可部署
echo.
pause
