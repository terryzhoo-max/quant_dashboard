@echo off
chcp 65001 >nul
echo 🚀 开始一键备份项目核心代码与AI对话记忆...

set BACKUP_DIR=D:\FIONA\AlphaCore_Backups
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TIMESTAMP=%datetime:~0,4%%datetime:~4,2%%datetime:~6,2%_%datetime:~8,2%%datetime:~10,2%%datetime:~12,2%

echo 📦 正在打包项目代码 (quant_dashboard)...
powershell -Command "Compress-Archive -Path 'D:\FIONA\google AI\quant_dashboard\*' -DestinationPath '%BACKUP_DIR%\quant_dashboard_%TIMESTAMP%.zip' -Force"

echo 🧠 正在打包AI记忆 (Brain 上下文)...
powershell -Command "Compress-Archive -Path 'C:\Users\magas\.gemini\antigravity\brain\f979dacf-9ea7-4c78-80be-e353886121e5\*' -DestinationPath '%BACKUP_DIR%\brain_memory_%TIMESTAMP%.zip' -Force"

echo.
echo ✅ 备份成功！
echo 📂 备份文件已保存至: %BACKUP_DIR%
pause
