"""
严格审核: portfolio_store.json vs broker 源文件 (20260408资金股份查询.txt)
"""
import json

# 1. 从 portfolio_store.json 读取当前存储的数据
with open(r"D:\FIONA\google AI\quant_dashboard\portfolio_store.json", "r", encoding="utf-8") as f:
    store = json.load(f)

print("=== PORTFOLIO_STORE.JSON 审核 ===")
print(f"现金 (cash): {store['cash']}")
print(f"持仓数: {len(store['positions'])}")
print()

# 2. 逐一比对 broker 数据
total_broker_mv = 0
total_broker_pnl = 0
total_cost_amount = 0

print(f"{'代码':<14} {'数量':>8} {'成本价':>10} {'券商价':>10} {'券商市值':>12} {'券商盈亏':>12} {'盈亏%':>8}")
print("-" * 85)

for code, pos in store["positions"].items():
    amt = pos["amount"]
    cost = pos["cost"]
    bp = pos.get("broker_price", 0)
    bmv = pos.get("broker_market_value", 0)
    bpnl = pos.get("broker_pnl", 0)
    bpnl_pct = pos.get("broker_pnl_pct", 0)

    total_broker_mv += bmv
    total_broker_pnl += bpnl
    total_cost_amount += amt * cost

    # 验证: broker_market_value 是否 = amount * broker_price
    expected_mv = amt * bp if bp > 0 else 0
    mv_ok = abs(bmv - expected_mv) < 1.0 if bmv > 0 else True

    mv_flag = "OK" if mv_ok else f"MISMATCH (expected {expected_mv:.2f})"
    print(f"{code:<14} {amt:>8} {cost:>10.3f} {bp:>10.3f} {bmv:>12.2f} {bpnl:>12.2f} {bpnl_pct:>7.2f}%  {mv_flag}")

print()
print("=== 汇总与 Broker 文件对比 ===")
print(f"store.cash            = {store['cash']:>14.2f}")
print(f"sum(broker_mv)        = {total_broker_mv:>14.2f}")
print(f"broker文件参考市值     = {1431688.68:>14.2f}")
print(f"差异                   = {total_broker_mv - 1431688.68:>14.2f}")
print()
print(f"sum(broker_pnl)       = {total_broker_pnl:>14.2f}")
print(f"broker文件盈亏         = {54212.66:>14.2f}")
print(f"差异                   = {total_broker_pnl - 54212.66:>14.2f}")
print()

# Broker 文件头数据
broker_balance = 53622.00  # 余额
broker_available = 6391.00  # 可用
broker_ref_mv = 1431688.68  # 参考市值
broker_total_asset = 1438179.68  # 总资产
broker_pnl = 54212.66  # 盈亏

print("=== 总资产计算分析 ===")
print(f"余额: {broker_balance}")
print(f"可用: {broker_available}")
print(f"冻结资金(余额-可用): {broker_balance - broker_available:.2f}")
print()
print(f"方式A: 余额 + 参考市值 = {broker_balance + broker_ref_mv:.2f}")
print(f"方式B: 可用 + 参考市值 = {broker_available + broker_ref_mv:.2f}")
print(f"Broker总资产           = {broker_total_asset:.2f}")
print()

# 002916 分析
print("=== 关键发现: 002916 (深电路/深电力) ===")
print("Broker文件: 证券数量=0, 库存数量=200, 可用数量=0")
print("import 代码在 amount<=0 时 continue -> 002916 被跳过!")
print(f"但文件头市值(1431688.68) 包含了002916的市值(47502)")
print()

# 如果去掉002916
mv_without_002916 = broker_ref_mv - 47502.00
pnl_without_002916 = broker_pnl - 371.00
print(f"去掉002916后: 市值 = {mv_without_002916:.2f}")
print(f"去掉002916后: 盈亏 = {pnl_without_002916:.2f}")
print(f"store中的市值合计     = {total_broker_mv:.2f}")
print(f"差异                  = {total_broker_mv - mv_without_002916:.2f}")
print()

# 总资产的正确计算
# broker总资产 = 余额 + 参考市值 - 002916的成本(已含在余额中)
print("=== 总资产正确理解 ===")

# 实际上, 券商的总资产计算:
# 总资产 = 余额(含冻结) + 参考市值(不含qty=0的)
# 或者 总资产 = 可用 + 冻结 + 有效持仓市值
# 1438179.68 = ?
# 试: 余额(53622) + 参考市值(1431688.68) - 002916市值(47502) = 1437808.68 (差371, 即002916的盈亏)
# 试: 可用(6391) + 参考市值(1431688.68) = 1438079.68 (差100)
# 试: 余额(53622) + (参考市值 - 002916成本47131) = 53622 + 1384557.68 = 1438179.68 ✓✓✓

result = 53622 + (1431688.68 - 47131.00)
print(f"余额(53622) + (参考市值(1431688.68) - 002916成本(47131)) = {result:.2f}")
print(f"Broker总资产 = {broker_total_asset:.2f}")
print(f"完全匹配!" if abs(result - broker_total_asset) < 0.01 else f"差异: {result - broker_total_asset}")
print()

# 结论
print("=" * 80)
print("=== 审核结论 ===")
print("=" * 80)
print()
print("【BUG 1】002916 被错误跳过")
print("  - 原因: import_from_txt() 中 amount<=0 时 continue")
print("  - 002916 的 '证券数量'=0 (因为是当日买入/冻结), 但 '库存数量'=200")
print("  - 解析使用了 '证券数量' 列而非 '库存数量' 列")
print("  - 结果: 002916 丢失, 市值少计 47502")
print()
print("【BUG 2】总市值不准")
print(f"  - store 中 18 只持仓的 broker_market_value 合计 = {total_broker_mv:.2f}")
print(f"  - Broker 文件参考市值 = {broker_ref_mv:.2f}")
print(f"  - 差异 = {total_broker_mv - broker_ref_mv:.2f} (002916的市值+成本相关)")
print()
print("【BUG 3】总资产不准")
print("  - store.cash = 可用资金(6391), 但 Broker 文件余额=53622")
print("  - 可用 vs 余额 差 47231 = 冻结资金(含002916卖出/买入冻结)")
print("  - import 代码使用 '可用' 而非 '余额' 作为 cash 存储")
print("  - 导致: total_asset = cash(6391) + mv(1384186.68) = 1390577.68")
print("  - 而正确值应为 1438179.68")
print()
print("【修复方案】")
print("  1. import_from_txt() 应使用 '余额' 而非 '可用' 作为 cash")
print("  2. amount 应优先使用 '库存数量' 而非 '证券数量' (处理冻结/在途情况)")
print("  3. 对于 002916 这类 qty=0 但有库存的情况, 应使用库存数量")
print("  4. 或者: 从文件头直接提取 '参考市值' 和 '总资产' 用于前端显示")
