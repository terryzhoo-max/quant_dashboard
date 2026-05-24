"""
V3.2 Sigmoid 回测验证 — 快速单参数验证 (非全网格搜索)
=====================================================
用当前生产参数 (erp_params.OPTIMIZER_DEFAULTS) 运行 IS+OOS 回测,
验证 V3 Sigmoid 评分公式在历史数据上的表现。

目的: 更新 BACKTEST_GRADE 中的 IS/OOS 评级, 消除 _needs_rerun=True 技术债。
"""
import sys, os, time, json
# strategies/ 子目录 → 父目录 (quant_dashboard/) 加入 path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
sys.path.insert(0, _script_dir)
sys.path.insert(0, _parent_dir)
os.chdir(_script_dir)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import datetime
import pandas as pd

from erp_backtest_data import prepare_erp_backtest_data
from strategies_backtest import erp_timing_strategy_vectorized
from backtest_engine import AlphaBacktester
import erp_params

print("=" * 70)
print("  V3.2 Sigmoid 回测验证 — 当前生产参数")
print(f"  参数版本: {erp_params.VERSION}")
print(f"  评分公式: {erp_params.SCORING_VERSION}")
print("=" * 70)

# ─── 配置 ───
ETF_CODE = "510300.SH"
IN_SAMPLE_START  = "20180101"
IN_SAMPLE_END    = "20231231"
OUT_SAMPLE_START = "20240101"
OUT_SAMPLE_END   = "20251231"
MACRO_PRE_FETCH  = "20150101"

# ─── 1. 数据准备 ───
print("\n📦 加载宏观日频宽表...")
t0 = time.time()
macro_df = prepare_erp_backtest_data(MACRO_PRE_FETCH, OUT_SAMPLE_END)
print(f"   宏观数据: {len(macro_df)} 行 ({time.time()-t0:.1f}s)")

print("\n📦 加载ETF价格数据...")
bt = AlphaBacktester(initial_cash=1000000.0)
df_full = bt.fetch_tushare_data(ETF_CODE, IN_SAMPLE_START, OUT_SAMPLE_END)
if df_full.empty:
    print("❌ ETF数据拉取失败!")
    sys.exit(1)
print(f"   ETF数据: {len(df_full)} 行")

# ─── 2. 分割 IS/OOS ───
is_end = pd.Timestamp(datetime.strptime(IN_SAMPLE_END, "%Y%m%d"))
os_start = pd.Timestamp(datetime.strptime(OUT_SAMPLE_START, "%Y%m%d"))

df_in = df_full[df_full.index <= is_end].copy()
df_out = df_full[df_full.index >= os_start].copy()
print(f"   样本内: {len(df_in)} 天 | 样本外: {len(df_out)} 天")

# ─── 3. 当前生产参数 ───
params = dict(erp_params.OPTIMIZER_DEFAULTS)
print(f"\n📋 生产参数: {params}")

# ─── 4. 样本内回测 ───
print("\n" + "═" * 70)
print("  样本内回测 (IS: 2018-2023)")
print("═" * 70)

signals_in = erp_timing_strategy_vectorized(df_in, macro_df=macro_df, **params)
results_in = bt.run_vectorized(df_in, signals_in, ts_code=ETF_CODE)
m_in = results_in.get("metrics", {})
g_in = results_in.get("grade", {})
rt_in = results_in.get("round_trips", {})

print(f"  年化收益: {m_in.get('annualized_return', 0)*100:.2f}%")
print(f"  Sharpe:   {m_in.get('sharpe_ratio', 0):.3f}")
print(f"  最大回撤: {m_in.get('max_drawdown', 0)*100:.2f}%")
print(f"  Alpha:    {m_in.get('alpha', 0)*100:.2f}%")
print(f"  交易次数: {rt_in.get('total_trades', 0)}")
print(f"  胜率:     {rt_in.get('win_rate', 0):.1f}%")
print(f"  评级:     {g_in.get('grade', '?')} (分数: {g_in.get('score', 0):.1f})")

# ─── 5. 样本外回测 ───
print("\n" + "═" * 70)
print("  样本外回测 (OOS: 2024-2025)")
print("═" * 70)

signals_out = erp_timing_strategy_vectorized(df_out, macro_df=macro_df, **params)
results_out = bt.run_vectorized(df_out, signals_out, ts_code=ETF_CODE)
m_out = results_out.get("metrics", {})
g_out = results_out.get("grade", {})
rt_out = results_out.get("round_trips", {})

print(f"  年化收益: {m_out.get('annualized_return', 0)*100:.2f}%")
print(f"  Sharpe:   {m_out.get('sharpe_ratio', 0):.3f}")
print(f"  最大回撤: {m_out.get('max_drawdown', 0)*100:.2f}%")
print(f"  Alpha:    {m_out.get('alpha', 0)*100:.2f}%")
print(f"  交易次数: {rt_out.get('total_trades', 0)}")
print(f"  胜率:     {rt_out.get('win_rate', 0):.1f}%")
print(f"  评级:     {g_out.get('grade', '?')} (分数: {g_out.get('score', 0):.1f})")

# ─── 6. 综合评估 ───
print("\n" + "═" * 70)
print("  V3.2 综合评估")
print("═" * 70)

sharpe_is = m_in.get('sharpe_ratio', 0)
sharpe_oos = m_out.get('sharpe_ratio', 0)
composite = sharpe_is * 0.4 + sharpe_oos * 0.6
decay = sharpe_oos / sharpe_is if sharpe_is > 0 else 0

print(f"  Composite Sharpe (IS×0.4 + OOS×0.6): {composite:.3f}")
print(f"  OOS/IS 衰减率: {decay:.2f} ({'✅ >0.5' if decay > 0.5 else '⚠️ <0.5'})")
print(f"  OOS Alpha: {m_out.get('alpha',0)*100:.2f}% ({'✅ 正' if m_out.get('alpha',0) > 0 else '❌ 负'})")

# 与 V2 基线对比
v2_composite = erp_params.COMPOSITE_SHARPE
print(f"\n  V2 Composite Sharpe (历史): {v2_composite:.3f}")
print(f"  V3 Composite Sharpe (本次): {composite:.3f}")
change = (composite - v2_composite) / v2_composite * 100 if v2_composite > 0 else 0
print(f"  变化: {change:+.1f}%")

# ─── 7. 输出更新建议 ───
print("\n" + "═" * 70)
print("  BACKTEST_GRADE 更新建议")
print("═" * 70)

grade_map = {"A+": 90, "A": 80, "B+": 70, "B": 60, "C": 50, "D": 40, "F": 0}

print(f'  IS  评级: {g_in.get("grade", "?")}')
print(f'  OOS 评级: {g_out.get("grade", "?")}')
print(f"""
  建议更新 erp_params.py:
  BACKTEST_GRADE = {{
      "IS": "{g_in.get('grade', '?')}", "OOS": "{g_out.get('grade', '?')}",
      "_formula_version": "v3_sigmoid",
      "_needs_rerun": False,
      "_last_verified": "{datetime.now().strftime('%Y-%m-%d')}",
      "_composite_sharpe": {composite:.3f},
      "_oos_decay": {decay:.2f},
  }}
""")

# ─── 8. 保存详细结果 ───
output = {
    "meta": {
        "version": erp_params.VERSION,
        "scoring": erp_params.SCORING_VERSION,
        "timestamp": datetime.now().isoformat(),
        "etf": ETF_CODE,
    },
    "params": params,
    "in_sample": {
        "period": f"{IN_SAMPLE_START} → {IN_SAMPLE_END}",
        "days": len(df_in),
        **m_in,
        "grade": g_in,
        "round_trips": rt_in,
    },
    "out_sample": {
        "period": f"{OUT_SAMPLE_START} → {OUT_SAMPLE_END}",
        "days": len(df_out),
        **m_out,
        "grade": g_out,
        "round_trips": rt_out,
    },
    "summary": {
        "composite_sharpe": composite,
        "oos_decay": decay,
        "v2_composite": v2_composite,
        "change_pct": change,
    },
}

out_file = os.path.join("data_lake", "erp_v32_backtest_verification.json")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)
print(f"  💾 详细结果: {out_file}")
print(f"\n  ⏱️ 总耗时: {time.time()-t0:.0f}s")
print("=" * 70)
