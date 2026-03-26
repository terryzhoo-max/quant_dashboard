@echo off
chcp 65001 >nul
echo ⚠️  AlphaCore 一键环境恢复向导
echo.
echo 这个脚本将打开您的备份文件夹: D:\FIONA\AlphaCore_Backups
echo =======================================================
echo.
echo 【恢复步骤说明】
echo 1. 找到您需要的日期时间戳的两个 zip 压缩包。
echo 2. 将 [quant_dashboard_时间戳.zip] 解压并覆盖到:
echo    D:\FIONA\google AI\quant_dashboard
echo.
echo 3. 将 [brain_memory_时间戳.zip] 解压并覆盖到:
echo    C:\Users\magas\.gemini\antigravity\brain\f979dacf-9ea7-4c78-80be-e353886121e5
echo.
echo =======================================================
echo.
echo 按任意键立即打开备份文件夹...
pause >nul
explorer "D:\FIONA\AlphaCore_Backups"
