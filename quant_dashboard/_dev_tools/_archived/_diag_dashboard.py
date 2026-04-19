"""
Dashboard 深度诊断: 逐层检查每个子模块的数据完整性
用法: 先启动 main.py, 然后运行本脚本
"""
import requests, json, sys, time

BASE = "http://localhost:8000"
API  = f"{BASE}/api/v1/dashboard-data"

def colored(text, ok):
    return f"  {'✅' if ok else '❌'} {text}"

def check_field(data, path, label=None):
    """递归取值, 返回 (value, exists)"""
    keys = path.split(".")
    v = data
    for k in keys:
        if isinstance(v, dict):
            v = v.get(k)
        else:
            v = None
            break
    ok = v is not None
    display = label or path
    if ok:
        # 截断长值
        show = str(v)
        if len(show) > 80:
            show = show[:77] + "..."
        print(colored(f"{display} = {show}", True))
    else:
        print(colored(f"{display} = None/Missing ⚠️", False))
    return v, ok

print("=" * 60)
print("🔍 Dashboard 深度诊断")
print("=" * 60)

# Step 1: 连接检查
print("\n📡 Step 1: 后端连接")
try:
    t0 = time.time()
    r = requests.get(API, timeout=300)
    elapsed = time.time() - t0
    print(colored(f"HTTP {r.status_code} ({elapsed:.1f}s)", r.status_code == 200))
    if r.status_code != 200:
        print("  后端返回非200, 终止诊断")
        sys.exit(1)
except Exception as e:
    print(colored(f"连接失败: {e}", False))
    print("  请确认 main.py 已启动且监听 8000 端口")
    sys.exit(1)

d = r.json()

# Step 2: 顶层结构
print("\n📦 Step 2: 顶层结构")
print(f"  顶层 keys: {list(d.keys())}")
check_field(d, "status", "status")
check_field(d, "timestamp", "timestamp")
data_val, data_ok = check_field(d, "data", "data (核心载荷)")

if not data_ok:
    print("\n  ⛔ data 字段缺失, 可能是全局异常。完整响应:")
    print(json.dumps(d, indent=2, ensure_ascii=False, default=str)[:2000])
    sys.exit(1)

data = d["data"]
print(f"  data keys: {list(data.keys())}")

# Step 3: macro_cards 子模块逐一检查
print("\n🏗️ Step 3: macro_cards 子模块检查")
mc = data.get("macro_cards")
if not mc:
    print(colored("macro_cards 整体缺失!", False))
    print(f"  data 实际 keys: {list(data.keys())}")
    sys.exit(1)

print(f"  macro_cards keys ({len(mc)}): {list(mc.keys())}")

# 3a. VIX
print("\n  --- VIX 模块 ---")
check_field(mc, "vix.value", "vix.value")
check_field(mc, "vix.trend", "vix.trend")
check_field(mc, "vix.regime", "vix.regime")
check_field(mc, "vix.percentile", "vix.percentile")

# 3b. Market Temperature
print("\n  --- 市场温度 模块 ---")
mt_val, _ = check_field(mc, "market_temp.value", "market_temp.value (总温度)")
check_field(mc, "market_temp.label", "market_temp.label")
check_field(mc, "market_temp.advice", "market_temp.advice (仓位建议)")
check_field(mc, "market_temp.advice_tier", "market_temp.advice_tier (AIAE档)")
check_field(mc, "market_temp.score_a", "market_temp.score_a (A股评分)")
check_field(mc, "market_temp.score_hk", "market_temp.score_hk (港股评分)")
check_field(mc, "market_temp.erp_z", "market_temp.erp_z")
check_field(mc, "market_temp.regime_name", "market_temp.regime_name")
check_field(mc, "market_temp.hub_composite", "market_temp.hub_composite")
check_field(mc, "market_temp.hub_confidence", "market_temp.hub_confidence")
check_field(mc, "market_temp.z_capital", "market_temp.z_capital")

# 3c. ERP
print("\n  --- ERP 模块 ---")
check_field(mc, "erp.value", "erp.value")
check_field(mc, "erp.trend", "erp.trend (估值标签)")
check_field(mc, "erp.erp_pct", "erp.erp_pct (4Y分位)")
check_field(mc, "erp.signal_label", "erp.signal_label")

# 3d. Capital Flow
print("\n  --- 资金流 模块 ---")
check_field(mc, "capital_a.value", "capital_a.value (北向)")
check_field(mc, "capital_a.z_score", "capital_a.z_score")
check_field(mc, "capital_a.resonance", "capital_a.resonance (共振)")
check_field(mc, "capital_h.value", "capital_h.value (南向)")

# 3e. Signal Consensus
print("\n  --- 五策略信号 模块 ---")
check_field(mc, "signal.consensus", "signal.consensus")
check_field(mc, "signal.consensus_label", "signal.consensus_label")
sig_strats = mc.get("signal", {}).get("strategies", [])
print(f"  strategies 数组长度: {len(sig_strats)}")
for s in sig_strats:
    d_icon = '↑' if s.get('direction') == 'up' else ('↓' if s.get('direction') == 'down' else '—')
    print(f"    {s.get('icon','')} {s.get('name','?'):6s} | {s.get('signal','?'):10s} | {s.get('metric','?'):10s} | {d_icon}")

# 3f. Regime Banner
print("\n  --- Regime Banner ---")
check_field(mc, "regime_banner.regime", "regime_banner.regime")
check_field(mc, "regime_banner.temp", "regime_banner.temp")
check_field(mc, "regime_banner.advice", "regime_banner.advice")
check_field(mc, "regime_banner.aiae_regime", "regime_banner.aiae_regime")
check_field(mc, "regime_banner.aiae_regime_cn", "regime_banner.aiae_regime_cn")
check_field(mc, "regime_banner.aiae_cap", "regime_banner.aiae_cap")

# 3g. AIAE Thermometer
print("\n  --- AIAE 温度计 ---")
check_field(mc, "aiae_thermometer.aiae_v1", "aiae_thermometer.aiae_v1")
check_field(mc, "aiae_thermometer.regime", "aiae_thermometer.regime")
check_field(mc, "aiae_thermometer.regime_cn", "aiae_thermometer.regime_cn")
check_field(mc, "aiae_thermometer.cap", "aiae_thermometer.cap")
check_field(mc, "aiae_thermometer.slope", "aiae_thermometer.slope")
check_field(mc, "aiae_thermometer.status", "aiae_thermometer.status")

# 3h. Tomorrow Plan
print("\n  --- 明日计划 ---")
check_field(mc, "tomorrow_plan.primary_regime.tier", "plan.primary_regime.tier")
check_field(mc, "tomorrow_plan.primary_regime.cap", "plan.primary_regime.cap")
check_field(mc, "tomorrow_plan.directives", "plan.directives")
check_field(mc, "tomorrow_plan.risk_panel.overall_risk", "plan.risk_panel.overall_risk")

# Step 4: 其他顶层模块
print("\n🗂️ Step 4: 其他数据模块")
sh = data.get("sector_heatmap", [])
print(colored(f"sector_heatmap: {len(sh)} 个行业", len(sh) > 0))
if sh:
    print(f"    示例: {sh[0].get('name', '?')} pct={sh[0].get('pct_change', '?')}%")

ss = data.get("strategy_status", {})
print(colored(f"strategy_status: {list(ss.keys())}", len(ss) > 0))

el_data = data.get("execution_lists", {})
buy_z = el_data.get("buy_zone", [])
sell_z = el_data.get("danger_zone", [])
print(colored(f"execution_lists: buy_zone={len(buy_z)}只, danger_zone={len(sell_z)}只", True))

# Step 5: 缺失汇总
print("\n" + "=" * 60)
print("📊 诊断摘要")
print("=" * 60)

# 统计 None 字段
critical_paths = [
    "market_temp.value", "market_temp.advice", "market_temp.score_a",
    "vix.value", "vix.regime",
    "erp.value", "erp.trend",
    "capital_a.value", "capital_h.value",
    "signal.consensus",
    "regime_banner.regime", "regime_banner.aiae_regime",
    "aiae_thermometer.aiae_v1",
    "tomorrow_plan.primary_regime.tier",
]

missing = []
for p in critical_paths:
    keys = p.split(".")
    v = mc
    for k in keys:
        if isinstance(v, dict):
            v = v.get(k)
        else:
            v = None
            break
    if v is None:
        missing.append(p)

if missing:
    print(f"\n❌ {len(missing)} 个关键字段缺失:")
    for m in missing:
        print(f"   - macro_cards.{m}")
    print("\n🔎 推测故障源:")
    missing_str = " ".join(missing)
    if "market_temp" in missing_str:
        print("   → market_temp 模块 (compute_market_temperature) 可能异常")
    if "erp" in missing_str:
        print("   → ERP 引擎 (erp_timing_engine) 可能异常")
    if "capital" in missing_str:
        print("   → 资金流模块 (capital_flow / Tushare HSGT) 可能异常")
    if "aiae" in missing_str:
        print("   → AIAE 引擎 (aiae_engine) 可能异常")
    if "tomorrow_plan" in missing_str:
        print("   → 明日计划 (get_tomorrow_plan) 可能异常")
else:
    print("\n✅ 所有关键字段均有数据，Dashboard 数据完整！")

print()
