"""
验证修复: 重新导入 20260408资金股份查询.txt 并检查结果
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_engine import PortfolioEngine

# 创建引擎实例
engine = PortfolioEngine()

# 读取 broker 文件
txt_path = r"D:\FIONA\google AI\20260408资金股份查询.txt"
with open(txt_path, "rb") as f:
    raw = f.read()

# GBK 解码
text = None
for enc in ['gbk', 'gb18030', 'utf-8']:
    try:
        text = raw.decode(enc)
        break
    except (UnicodeDecodeError, LookupError):
        continue
if text is None:
    text = raw.decode('gbk', errors='replace')

# 执行导入
result = engine.import_from_txt(text)

print("=== 导入结果 ===")
print(f"成功: {result['success']}")
print(f"导入持仓数: {result['imported']}")
print(f"现金(余额): {result['cash']}")
print(f"总资产: {result['total_asset']}")
print(f"错误: {result['errors']}")
print()

# 检查哪些持仓被导入
print("=== 导入的持仓 ===")
for p in result['positions']:
    print(f"  {p['ts_code']:<14} {p['name']:<20} qty={p['amount']:<8} cost={p['cost']:<10.3f} price={p['price']:.3f}")
print()

# 检查 002916 是否被导入
codes = [p['ts_code'] for p in result['positions']]
if '002916.SZ' in codes:
    print("✅ 002916.SZ (深电路) 已成功导入")
else:
    print("❌ 002916.SZ (深电路) 仍然丢失!")
print()

# 获取估值结果
valuation = engine.get_valuation()
print("=== 估值结果 (get_valuation) ===")
print(f"现金:     {valuation['cash']:>14.2f}  (预期: 53,622.00)")
print(f"市值:     {valuation['market_value']:>14.2f}  (预期: 1,431,688.68)")
print(f"总资产:   {valuation['total_asset']:>14.2f}  (预期: 1,438,179.68)")
print(f"总盈亏:   {valuation['total_pnl']:>14.2f}  (预期: 54,212.66)")
print(f"盈亏率:   {valuation['total_pnl_pct']:>14.2f}%")
print(f"持仓数:   {valuation['position_count']}")
print()

# 逐项验证
checks = [
    ("现金", valuation['cash'], 53622.00, 1.0),
    ("市值", valuation['market_value'], 1431688.68, 1.0),
    ("总资产", valuation['total_asset'], 1438179.68, 1.0),
    ("总盈亏", valuation['total_pnl'], 54212.66, 1.0),
    ("持仓数", valuation['position_count'], 19, 0),
]

print("=== 验证清单 ===")
all_pass = True
for name, actual, expected, tolerance in checks:
    passed = abs(actual - expected) <= tolerance
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}: {actual} (预期: {expected})")
    if not passed:
        all_pass = False

print()
if all_pass:
    print("🎉 所有验证项全部通过!")
else:
    print("⚠️ 存在未通过的验证项")
