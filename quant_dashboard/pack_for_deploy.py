"""
AlphaCore 一键完整打包
双击运行或 python pack_for_deploy.py → 桌面生成 zip → 拖到服务器即可
"""
import zipfile, os, sys
from pathlib import Path

if sys.platform == 'win32':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = Path.home() / "Desktop" / "quant_dashboard_deploy.zip"

# 只排除这些垃圾，其余全部打包
EXCLUDE = {
    '__pycache__', '.git', '.venv', 'venv', 'env', 'node_modules',
    '_dev_tools', 'data_lake', 'tmp', '.idea', '.vscode',
}
EXCLUDE_EXT = {'.pyc', '.bak', '.log', '.parquet'}
EXCLUDE_FILES = {'pack_for_deploy.py', 'quant_dashboard_deploy.zip'}

def pack():
    print()
    print("  ================================")
    print("  AlphaCore 一键完整打包")
    print("  ================================")
    print()

    count = 0
    total = 0

    with zipfile.ZipFile(OUTPUT_PATH, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_DIR):
            # 跳过排除目录
            dirs[:] = [d for d in dirs if d not in EXCLUDE]
            
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(PROJECT_DIR)
                
                # 跳过排除文件
                if f in EXCLUDE_FILES:
                    continue
                if full.suffix in EXCLUDE_EXT:
                    continue
                
                arcname = f"quant_dashboard/{rel}"
                zf.write(full, arcname)
                size_kb = full.stat().st_size // 1024
                total += full.stat().st_size
                count += 1
                print(f"  + {rel} ({size_kb}KB)")

    zip_kb = OUTPUT_PATH.stat().st_size // 1024
    print()
    print(f"  ================================")
    print(f"  Done! {count} files, {zip_kb}KB")
    print(f"  -> {OUTPUT_PATH}")
    print(f"  ================================")
    print()
    print("  Next:")
    print("  1. Xftp: drag zip to server /root/")
    print("  2. Xshell:")
    print()
    print("     cd /root && unzip -o quant_dashboard_deploy.zip && cd quant_dashboard && docker compose down && docker compose up -d --build")
    print()

if __name__ == "__main__":
    pack()
