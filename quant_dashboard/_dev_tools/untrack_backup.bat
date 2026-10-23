@echo off
chcp 65001 >nul
rem Stop tracking the local backup folder in git (files stay on disk). Run once, then run the push script.
cd /d "%~dp0..\.."
git rm -r --cached --quiet "quant_dashboard/_backup_20261023"
if errorlevel 1 (echo [WARN] git rm failed or already untracked) else (echo [OK] _backup_20261023 untracked. Now run the push script.)
pause
