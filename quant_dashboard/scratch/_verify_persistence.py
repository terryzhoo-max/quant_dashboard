"""验证持仓持久化完整链路"""
import json, os, sys, time
from datetime import datetime

# 修复 Windows 终端编码
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

print("=" * 60)
print("  持仓持久化链路验证")
print("=" * 60)

store_path = "portfolio_store.json"
abs_path = os.path.abspath(store_path)

print(f"\n[1] 文件路径")
print(f"    CWD:  {os.getcwd()}")
print(f"    绝对:  {abs_path}")
print(f"    存在:  {os.path.exists(abs_path)}")
print(f"    大小:  {os.path.getsize(abs_path)} bytes" if os.path.exists(abs_path) else "    N/A")

if not os.path.exists(abs_path):
    print("\n    [FAIL] 文件不存在! 这是数据丢失的原因。")
    sys.exit(1)

# 读取内容
with open(store_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

positions = data.get("positions", {})
print(f"\n[2] 当前存储内容")
print(f"    cash:         {data.get('cash')}")
print(f"    positions:    {len(positions)} 只")
print(f"    import_date:  {data.get('import_date')}")
print(f"    broker_total: {data.get('broker_total_asset')}")
print(f"    顶级 keys:    {list(data.keys())}")

for i, (code, pos) in enumerate(positions.items()):
    if i >= 3:
        print(f"    ... 省略 {len(positions) - 3} 只 ...")
        break
    print(f"    {code}: {pos['name']} x{pos['amount']} @{pos['cost']}")

# 模拟 _load_portfolio
print(f"\n[3] 模拟引擎 _load_portfolio() 逻辑")
default = {"cash": 1000000.0, "positions": {}}
loaded = default
if os.path.exists(store_path):
    try:
        with open(store_path, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
            if isinstance(loaded_data, dict) and "positions" in loaded_data:
                loaded = loaded_data
                print(f"    [OK] 加载成功: {len(loaded['positions'])} 只持仓, cash={loaded['cash']}")
            else:
                print(f"    [FAIL] 格式异常: 不是 dict 或缺少 positions key")
    except Exception as e:
        print(f"    [FAIL] 读取异常: {e}")
else:
    print(f"    [FAIL] 文件不存在 -> 使用默认值 (空持仓 + 100万现金)")

# 日期检查
today = datetime.now().strftime("%Y-%m-%d")
import_date = data.get("import_date", "")
print(f"\n[4] 日期检查")
print(f"    今天:       {today}")
print(f"    导入日期:   {import_date}")
print(f"    是否当日:   {import_date == today}")
if import_date != today:
    print(f"    [WARN] 导入日期不是今天 -> 估值会切换到 Tushare 价格源")

# 文件时间戳
mtime = os.path.getmtime(abs_path)
mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
age_hours = (time.time() - mtime) / 3600
print(f"\n[5] 文件时间戳")
print(f"    最后修改:  {mtime_str}")
print(f"    距今:      {age_hours:.1f} 小时")

# 搜索同名文件
print(f"\n[6] 同名文件搜索 (检查路径混淆)")
search_dirs = [
    r"d:\FIONA\google AI\quant_dashboard",
    r"d:\FIONA\google AI\quant_dashboard\quant_dashboard",
    r"d:\FIONA\google AI",
]
for d in search_dirs:
    fp = os.path.join(d, "portfolio_store.json")
    if os.path.exists(fp):
        sz = os.path.getsize(fp)
        mt = datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")
        with open(fp, 'r', encoding='utf-8') as f:
            fd = json.load(f)
        pc = len(fd.get("positions", {}))
        print(f"    [FOUND] {fp}")
        print(f"            {sz} bytes | {mt} | {pc} 只持仓 | cash={fd.get('cash')}")
    else:
        print(f"    [NONE]  {fp}")

# 验证 _save_portfolio 的原子写入
print(f"\n[7] 验证原子写入 (.tmp 残留检查)")
tmp_path = store_path + ".tmp"
if os.path.exists(tmp_path):
    print(f"    [WARN] 发现 .tmp 残留文件! 上次写入可能中断")
    print(f"           路径: {os.path.abspath(tmp_path)}")
    print(f"           大小: {os.path.getsize(tmp_path)}")
else:
    print(f"    [OK] 无 .tmp 残留, 上次写入正常完成")

# 验证 trade_history.json
print(f"\n[8] 交易历史检查")
hist_path = "trade_history.json"
if os.path.exists(hist_path):
    with open(hist_path, 'r', encoding='utf-8') as f:
        hist = json.load(f)
    imports = [t for t in hist if t.get("action") == "import"]
    print(f"    [OK] {len(hist)} 条交易记录, 其中 {len(imports)} 次导入")
    if imports:
        last_imp = imports[-1]
        print(f"    最近导入: {last_imp.get('timestamp')} | {last_imp.get('name')}")
else:
    print(f"    [NONE] trade_history.json 不存在")

# SQLite 检查
print(f"\n[9] SQLite 数据库检查")
db_path = "alpha_core.db"
if os.path.exists(db_path):
    sz = os.path.getsize(db_path)
    mt = datetime.fromtimestamp(os.path.getmtime(db_path)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"    [OK] {db_path} 存在 | {sz/1024:.0f} KB | {mt}")
else:
    print(f"    [NONE] {db_path} 不存在")

# 总结
print(f"\n{'=' * 60}")
print(f"  验证总结")
print(f"{'=' * 60}")
if len(positions) > 0 and os.path.exists(abs_path):
    print(f"  [PASS] 持久化链路正常")
    print(f"         文件存在 + 内容完整 ({len(positions)} 只持仓)")
    print(f"         当前状态下, 重启服务器应能正确恢复持仓")
    print(f"")
    print(f"  若你确实观察到重启后丢失, 请排查:")
    print(f"  A. 你是用 Docker 还是本地 bat 启动?")
    print(f"  B. 重启后用浏览器 F12 检查 /api/v1/portfolio/valuation 返回什么?")
    print(f"  C. 是整个持仓消失, 还是数字/价格变了?")
print(f"{'=' * 60}")
