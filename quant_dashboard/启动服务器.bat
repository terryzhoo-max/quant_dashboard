@echo off
echo 启动 AlphaCore 量化服务器...
cd /d "d:\FIONA\google AI\quant_dashboard"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
