"""AIAE V2.1 优化验证脚本"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 清除旧种子文件以测试自动创建
fp_file = os.path.join("data_lake", "aiae_fund_position.json")
if os.path.exists(fp_file):
    os.remove(fp_file)
    print("[Test] 已删除旧 fund_position 文件")

from aiae_engine import AIAEEngine, FUND_REPORT_SCHEDULE, FUND_UPDATE_GUIDE

print("\n=== 1. 季报日历常量 ===")
for q, info in FUND_REPORT_SCHEDULE.items():
    print(f"  {q}: 截止{info['cutoff_md']} → 发布截止{info['deadline_md']} ({info['label']})")

print(f"\n=== 2. 查阅指引 ({len(FUND_UPDATE_GUIDE['steps'])} 步) ===")
for step in FUND_UPDATE_GUIDE['steps']:
    print(f"  {step}")

print("\n=== 3. 初始化引擎 (应自动创建种子文件) ===")
e = AIAEEngine()
print(f"  基金仓位: {e._fund_position}% ({e._fund_position_date})")
print(f"  种子文件存在: {os.path.exists(fp_file)}")

# 验证种子文件内容
if os.path.exists(fp_file):
    with open(fp_file, 'r', encoding='utf-8') as f:
        seed = json.load(f)
    print(f"  source: {seed.get('source')}")
    print(f"  history: {len(seed.get('history', []))} 条")

print("\n=== 4. 季度感知过期检查 ===")
warning = e._get_fund_position_stale_warning()
if warning:
    print(f"  类型: {warning['type']}")
    print(f"  级别: {warning['severity']}")
    print(f"  消息: {warning['message']}")
    print(f"  action_required: {warning.get('action_required', False)}")
    if warning.get('expected_label'):
        print(f"  期望季度: {warning['expected_label']}")
else:
    print("  无告警 (数据足够新)")

print("\n=== 5. 测试更新基金仓位 ===")
result = e.update_fund_position(79.5, "2026-03-31")
print(f"  结果: {result['success']} - {result['message']}")


print("\n=== 6. 更新后再检查过期 ===")
warning2 = e._get_fund_position_stale_warning()
if warning2:
    print(f"  仍有告警: {warning2['type']} - {warning2['message']}")
else:
    print("  ✅ 告警已消除 (数据足够新)")

# 验证 history 追加
with open(fp_file, 'r', encoding='utf-8') as f:
    updated = json.load(f)
print(f"  history: {len(updated.get('history', []))} 条")
for h in updated.get('history', []):
    print(f"    {h.get('quarter', '?')}: {h.get('value')}% ({h.get('date')})")

print("\n=== 7. 月度历史冷启动验证 ===")
history_file = os.path.join("data_lake", "aiae_monthly_history.json")
if os.path.exists(history_file):
    with open(history_file, 'r', encoding='utf-8') as f:
        mh = json.load(f)
    print(f"  当前月度历史: {len(mh)} 条记录")
    for h in mh:
        src = h.get('source', 'live')
        print(f"    {h['month']}: {h['aiae_v1']}% regime={h['regime']} [{src}]")

prev = e._get_prev_month_aiae()
print(f"  上月 AIAE 值: {prev}")
if prev is not None:
    slope = e.compute_slope(21.87, prev)
    print(f"  斜率: {slope}")
else:
    print("  斜率: flat (无上月数据)")

print("\n=== 全部测试完成 ✅ ===")
