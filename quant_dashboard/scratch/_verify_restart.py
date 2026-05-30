"""模拟服务器重启: 新建 PortfolioEngine 实例, 验证是否能恢复持仓"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 添加项目路径
sys.path.insert(0, os.getcwd())

print("=" * 60)
print("  模拟服务器重启 - PortfolioEngine 恢复测试")
print("=" * 60)

# 加载 .env (模拟真实启动)
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# 模拟重启: 确保单例为空
import portfolio_engine as pe
pe._engine_instance = None  # 强制清空单例 = 模拟进程重启

print("\n[1] 单例已清空, 模拟全新启动...")

# 重新获取引擎 (触发 __init__ → _load_portfolio)
try:
    engine = pe.get_portfolio_engine()
    print(f"    [OK] PortfolioEngine 创建成功")
except Exception as e:
    print(f"    [FAIL] 创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 检查恢复的数据
holdings = engine.holdings
positions = holdings.get("positions", {})
cash = holdings.get("cash", 0)

print(f"\n[2] 恢复的持仓数据:")
print(f"    cash:         {cash}")
print(f"    positions:    {len(positions)} 只")
print(f"    import_date:  {holdings.get('import_date', 'N/A')}")

if len(positions) == 0:
    print(f"\n    [FAIL] 持仓为空! 数据未能恢复!")
    print(f"    holdings 完整内容: {holdings}")
else:
    print(f"\n    持仓列表:")
    for code, pos in list(positions.items())[:5]:
        print(f"      {code}: {pos.get('name','?')} x{pos.get('amount',0)} @{pos.get('cost',0)}")
    if len(positions) > 5:
        print(f"      ... 还有 {len(positions)-5} 只 ...")

# 调用 get_valuation 验证完整估值链
print(f"\n[3] 调用 get_valuation() 验证完整估值链...")
try:
    val = engine.get_valuation()
    print(f"    [OK] 估值返回成功")
    print(f"    cash:          {val['cash']}")
    print(f"    market_value:  {val['market_value']}")
    print(f"    total_asset:   {val['total_asset']}")
    print(f"    position_count: {val['position_count']}")
    print(f"    total_pnl_pct: {val.get('total_pnl_pct', 'N/A')}%")
except Exception as e:
    print(f"    [FAIL] 估值失败: {e}")
    import traceback
    traceback.print_exc()

print(f"\n{'=' * 60}")
if len(positions) > 0:
    print(f"  [PASS] 服务器重启后, 持仓正确恢复 ({len(positions)} 只)")
    print(f"         持久化机制工作正常")
else:
    print(f"  [FAIL] 重启后持仓丢失, 需要排查原因")
print(f"{'=' * 60}")
