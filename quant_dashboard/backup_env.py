import os
import sys
import json
import pandas as pd

def backup_antigravity_status():
    print("--- Antigravity 环境备份启动 ---")
    
    # 1. 记录 Python 版本和已安装的非标准库
    print("\n[1/3] 正在记录环境依赖...")
    # 获取当前已加载的模块名（过滤掉内置模块）
    loaded_modules = [m for m in sys.modules.keys() if not m.startswith('_')][:20] 
    
    # 2. 列出当前工作目录下的文件 (例如 /mnt/data/ 目录)
    print("[2/3] 正在扫描当前工作目录文件...")
    files = os.listdir('.')
    
    # 3. 汇总当前内存中的关键变量 (排除内置变量)
    print("[3/3] 正在提取内存变量摘要...")
    user_vars = {k: str(type(v)) for k, v in globals().items() 
                 if not k.startswith('_') and k not in ['os', 'sys', 'json', 'pd', 'backup_antigravity_status']}

    # 打印备份报告
    print("\n" + "="*30)
    print("📋 备份报告 (请复制保存此内容):")
    report = {
        "Python_Version": sys.version.split()[0],
        "Loaded_Modules_Sample": loaded_modules,
        "Files_In_Workspace": files,
        "Global_Variables_Summary": user_vars
    }
    print(json.dumps(report, indent=4, ensure_ascii=False))
    print("="*30)
    print("\n💡 提示：如果有名为 .csv, .xlsx 或 .png 的重要文件，请立即手动点击下载！")

# 执行备份
backup_antigravity_status()
