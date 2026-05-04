"""
AlphaCore · 红利趋势增强策略引擎 V4.0
数据源：Tushare（5000积分用户 — 按ts_code批量获取）
标的池：8只红利类ETF · 固定权重配置

V4.0 升级：
  · 7维100分评分体系（新增RSI动量方向Δ RSI₅）
  · 波动率维度实质化（30日年化波动率实际计算）
  · 信号交叉验证（温和版：调用均值回归评分引擎做技术面检查）
  · 四状态自适应参数框架（BULL/RANGE/BEAR/CRASH）

设计决策：
  · 股息率历史分位 → 方案A：固定阈值（TTM>5%高/4-5%中/<4%低）
  · CRASH下已持仓高股息(>6%)标的 → 不强制清仓
  · 交叉验证门槛比动量策略低10分（红利ETF有股息率安全边际）
"""

import pandas as pd
import numpy as np
import tushare as ts
import os
import time
from datetime import datetime, timedelta
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== Tushare 初始化 ======
from config import TUSHARE_TOKEN
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ====== 标的池与固定权重 ======
DIVIDEND_POOL = [
    {'code': '515100.SH', 'name': '中证红利低波100ETF', 'weight': 15},
    {'code': '510880.SH', 'name': '红利ETF',           'weight': 15},
    {'code': '159545.SZ', 'name': '恒生红利低波ETF',    'weight': 15},
    {'code': '512890.SH', 'name': '红利低波ETF',        'weight': 15},
    {'code': '515080.SH', 'name': '央企红利ETF',        'weight': 10},
    {'code': '513530.SH', 'name': '港股通红利ETF',      'weight': 10},
    {'code': '513950.SH', 'name': '恒生红利ETF',        'weight': 10},
    {'code': '159201.SZ', 'name': '自由现金流ETF',      'weight': 10},
]

# ====================================================================
# V3.1 · 四状态自适应参数表
# 回测依据：
#   RANGE = V3.0网格搜索最优（2022-2026, 144组合, 样本外α=+17.3%）
#   BULL  = 基于RANGE放宽 RSI/BIAS 阈值（趋势市减少错误卖出）
#   BEAR  = 基于RANGE收紧 RSI/BIAS + 加长趋势均线（高确信度才进）
#   CRASH = 熔断保护，禁止买入
# ====================================================================
REGIME_PARAMS = {
    "BULL": {
        "ma_trend":  60,    # 与RANGE相同，60日趋势足够
        "rsi_buy":   40,    # 放宽：牛市中稍早介入
        "rsi_sell":  80,    # 放宽：牛市中让利润跑久点
        "bias_buy":  -1.5,  # 放宽：红利ETF牛市波幅也扩大
        "bias_sell":  7.0,  # 放宽：给足盈利空间
        "ma_defend": 20,    # 收紧防守：牛市跌破MA20就走
        "boll_n":    20,
        "pos_cap":   0.85,  # 仓位上限85%
        "entry_gate": 55,   # 评分入场门槛55分（趋势市降低要求）
        "note":      "牛市模式：RSI/BIAS阈值放宽，趋势持仓为主"
    },
    "RANGE": {  # V3.0标准参数（回测最优）
        "ma_trend":  60,
        "rsi_buy":   35,
        "rsi_sell":  75,
        "bias_buy":  -2.0,
        "bias_sell":  5.5,
        "ma_defend": 30,
        "boll_n":    20,
        "pos_cap":   0.70,  # 仓位上限70%
        "entry_gate": 65,   # 标准入场门槛65分
        "note":      "震荡模式：V3.0标准参数，低吸高卖"
    },
    "BEAR": {
        "ma_trend":  90,    # 收紧：需要更长趋势确认
        "rsi_buy":   30,    # 收紧：只在极度超卖才买
        "rsi_sell":  70,    # 收紧：更早止盈
        "bias_buy":  -3.0,  # 收紧：需要更大偏离才值得入场
        "bias_sell":  4.5,  # 收紧：更早止盈
        "ma_defend": 40,    # 宽松防守：减少假跌破清仓频率
        "boll_n":    20,
        "pos_cap":   0.45,  # 仓位上限45%
        "entry_gate": 75,   # 高门槛75分，确定性才入
        "note":      "熊市模式：RSI/BIAS阈值收紧，严控仓位"
    },
    "CRASH": {
        "ma_trend":  999,   # 实质性禁止买入
        "rsi_buy":   0,
        "rsi_sell":  60,    # 较低止盈，快速保护
        "bias_buy":  -99,
        "bias_sell":  3.0,
        "ma_defend": 20,
        "boll_n":    20,
        "pos_cap":   0.0,   # 全面空仓
        "entry_gate": 999,  # 禁止任何新建仓
        "note":      "熔断保护：禁止买入，高股息已持仓不强制清仓"
    },
}

# 默认回退到RANGE（V3.0最优参数）
DEFAULT_REGIME = "RANGE"

# ====== 布林带周期（固定，各状态统一使用20日）======
BOLL_N = 20

# TTM 分红静态近似（方案A：固定阈值，快速落地）
DIVIDEND_D_TTM = {
    '515100.SH': 0.082,
    '510880.SH': 0.165,
    '159545.SZ': 0.085,
    '512890.SH': 0.065,
    '515080.SH': 0.075,
    '513530.SH': 0.080,
    '513950.SH': 0.060,
    '159201.SZ': 0.055,
}

# 股息率估值固定阈值（方案A）
# high: TTM > 5%  → 高估值，具备安全边际
# mid:  TTM 4-5% → 中等估值
# low:  TTM < 4% → 低估值，注意风险
def classify_yield(ttm_yield: float) -> str:
    if ttm_yield >= 5.0:
        return "high"
    elif ttm_yield >= 4.0:
        return "mid"
    else:
        return "low"


def _fetch_single_dividend_etf(item, start_date, end_date, days):
    code = item['code']
    cache_file = f"data_lake/daily_prices/{code}.parquet"
    try:
        df = ts.pro_bar(ts_code=code, asset='FD', adj='qfq',
                        start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
            df = df.tail(days).reset_index(drop=True)
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            df.to_parquet(cache_file)
            return code, df, f"  [OK] {item['name']}({code}): {len(df)}条数据"
    except Exception as e:
        if os.path.exists(cache_file):
            df = pd.read_parquet(cache_file)
            if not df.empty:
                df = df.tail(days).reset_index(drop=True)
                return code, df, f"  [WARN] {item['name']}({code}) API失败，使用本地缓存: {len(df)}条"
        return code, None, f"  [FAIL] {item['name']}({code}): {e}"
    return code, None, f"  [FAIL] {item['name']}({code}): 无数据返回"

def fetch_etf_data_by_code(days: int = 150) -> dict:
    """
    V5.0: 并发拉取历史数据并引入本地 Parquet 降级保护
    """
    print(f"[红利引擎] 开始并发获取{days}天历史数据...")

    end_date   = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 2.0))).strftime("%Y%m%d")

    etf_data = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_single_dividend_etf, item, start_date, end_date, days) for item in DIVIDEND_POOL]
        for future in as_completed(futures):
            code, df, msg = future.result()
            print(msg)
            if df is not None:
                etf_data[code] = df

    print(f"[红利引擎] 数据获取完成，共{len(etf_data)}/8只ETF有数据")
    return etf_data


def calculate_indicators(df, code, p: dict) -> dict:
    """
    计算红利趋势策略所需的全部指标（V4.0 · 增加RSI斜率+波动率）
    """
    close = df['close'].astype(float)

    ma_trend_n  = p["ma_trend"]
    ma_defend_n = p["ma_defend"]
    boll_n      = p.get("boll_n", BOLL_N)

    # 1. 宏观趋势：MA趋势均线（状态自适应）
    ma_trend = close.rolling(ma_trend_n).mean()
    trend_up = (float(close.iloc[-1]) > float(ma_trend.iloc[-1])
                if pd.notna(ma_trend.iloc[-1]) else False)

    # 2. 布林带(20) & 防守线（状态自适应）
    ma_defend  = close.rolling(ma_defend_n).mean()
    ma_boll    = close.rolling(boll_n).mean()
    std_boll   = close.rolling(boll_n).std()
    boll_upper = ma_boll + 2 * std_boll
    boll_lower = ma_boll - 2 * std_boll

    # 3. RSI(9)
    delta = close.diff()
    gain  = (delta.where(delta > 0, 0.0)).rolling(9).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(9).mean()
    rs    = gain / loss.replace(0, 0.001)
    rsi   = 100 - (100 / (1 + rs))

    # 4. 乖离率（基于状态自适应防守线）
    bias = (close - ma_defend) / ma_defend * 100

    # 5. V4.0新增：RSI动量方向（近5日RSI线性回归斜率）
    rsi_slope5 = 0.0
    if len(rsi) >= 5:
        rsi_tail = rsi.iloc[-5:].dropna()
        if len(rsi_tail) >= 3:
            x = np.arange(len(rsi_tail))
            try:
                slope = np.polyfit(x, rsi_tail.values, 1)[0]
                rsi_slope5 = round(float(slope), 2)
            except:
                rsi_slope5 = 0.0

    # 6. V4.0新增：30日年化波动率
    vol_30d = 0.0
    if len(close) >= 30:
        daily_ret = close.pct_change().iloc[-30:].dropna()
        if len(daily_ret) >= 20:
            vol_30d = round(float(daily_ret.std() * np.sqrt(252) * 100), 1)

    # TTM 股息率（静态近似 · 方案A）
    trailing_dividend = DIVIDEND_D_TTM.get(code, 0.05)
    real_ttm_yield    = (trailing_dividend / float(close.iloc[-1])) * 100

    idx = len(df) - 1
    return {
        'close':       round(float(close.iloc[idx]), 3),
        'ma_trend':    round(float(ma_trend.iloc[idx]), 3) if pd.notna(ma_trend.iloc[idx]) else 0,
        'ma_defend':   round(float(ma_defend.iloc[idx]), 3) if pd.notna(ma_defend.iloc[idx]) else 0,
        'trend_up':    bool(trend_up),
        'rsi':         round(float(rsi.iloc[idx]), 1) if pd.notna(rsi.iloc[idx]) else 50,
        'rsi_slope5':  rsi_slope5,
        'bias':        round(float(bias.iloc[idx]), 2) if pd.notna(bias.iloc[idx]) else 0,
        'boll_upper':  round(float(boll_upper.iloc[idx]), 3) if pd.notna(boll_upper.iloc[idx]) else 0,
        'boll_lower':  round(float(boll_lower.iloc[idx]), 3) if pd.notna(boll_lower.iloc[idx]) else 0,
        'boll_mid':    round(float(ma_boll.iloc[idx]), 3) if pd.notna(ma_boll.iloc[idx]) else 0,
        'ttm_yield':   round(float(real_ttm_yield), 2),
        'yield_class': classify_yield(real_ttm_yield),
        'vol_30d':     vol_30d,
        'date':        df['trade_date'].iloc[idx],
    }


def generate_signal(ind: dict, weight: int, p: dict, regime: str) -> tuple:
    """
    V3.1 · 四状态自适应信号生成
    regime: BULL / RANGE / BEAR / CRASH
    CRASH策略：禁止买入，高股息(>6%)已持仓不强制清仓（外部持仓状态管理）
    """
    close      = ind['close']
    ma_trend   = ind['ma_trend']
    ma_defend  = ind['ma_defend']
    rsi        = ind['rsi']
    bias       = ind['bias']
    boll_upper = ind['boll_upper']
    boll_lower = ind['boll_lower']
    ttm_yield  = ind['ttm_yield']
    trend_up   = ind['trend_up']

    rsi_buy    = p["rsi_buy"]
    rsi_sell   = p["rsi_sell"]
    bias_buy   = p["bias_buy"]
    bias_sell  = p["bias_sell"]

    # 股息率特权托底（>6%豁免卖出；CRASH状态下禁止新买/保留持仓）
    yield_floor_active = ttm_yield > 6.0

    # ===== CRASH 熔断状态 =====
    if regime == "CRASH":
        # 禁止任何新买入
        # 已持仓高股息：保留（不触发 sell），等CRASH解除后正常判断
        # 已持仓低股息：允许正常止损
        sell_in_crash = (
            close < ma_defend or
            close >= boll_upper or
            bias >= p["bias_sell"] or
            rsi >= p["rsi_sell"]
        ) and not yield_floor_active
        return ('sell', 0) if sell_in_crash else ('hold', weight)

    # === Layer 1：宏观趋势过滤 ===
    trend_ok = (close > ma_trend) or yield_floor_active

    # === Layer 2：买入触发 ===
    buy_trigger = (rsi <= rsi_buy or bias <= bias_buy or close <= boll_lower)

    # === Layer 3：卖出触发 ===
    sell_trigger = (
        close < ma_defend or
        close >= boll_upper or
        bias >= bias_sell or
        rsi >= rsi_sell
    )

    if trend_ok and buy_trigger:
        return 'buy', weight

    if not yield_floor_active and sell_trigger:
        return 'sell', 0

    return 'hold', weight


def score_etf(ind: dict, regime: str, p: dict) -> dict:
    """
    V4.0 · 红利策略专属信号评分（7维，满分100分）
    返回: {total: int, breakdown: dict}
    """
    # 维度1 · 市场环境（15分）— 降权：红利不应过度依赖市场状态
    env_score = {"BULL": 15, "RANGE": 10, "BEAR": 4, "CRASH": 0}.get(regime, 10)

    # 维度2 · RSI(9) 技术位（18分）
    rsi = ind['rsi']
    if rsi <= 30:
        rsi_score = 18
    elif rsi <= 35:
        rsi_score = 14
    elif rsi <= 40:
        rsi_score = 9
    elif rsi <= 50:
        rsi_score = 4
    else:
        rsi_score = 0

    # 维度3 · 乖离率位置（18分）
    bias = ind['bias']
    if bias <= -3.0:
        bias_score = 18
    elif bias <= -2.0:
        bias_score = 14
    elif bias <= 0:
        bias_score = 7
    else:
        bias_score = 0

    # 维度4 · 股息率估值（20分）— 保持最高权重，红利核心
    ttm = ind['ttm_yield']
    if ttm >= 5.0:
        yield_score = 20
    elif ttm >= 4.0:
        yield_score = 12
    elif ttm >= 3.0:
        yield_score = 5
    else:
        yield_score = 0

    # 维度5 · 布林带位置（10分）
    if ind['boll_upper'] > ind['boll_lower']:
        boll_pct = (ind['close'] - ind['boll_lower']) / (ind['boll_upper'] - ind['boll_lower'])
        if boll_pct <= 0.05:
            boll_score = 10
        elif boll_pct <= 0.35:
            boll_score = 6
        elif boll_pct <= 0.7:
            boll_score = 2
        else:
            boll_score = 0
    else:
        boll_score = 5

    # 维度6 · 30日波动率（9分）— V4.0实质化
    vol_30d = ind.get('vol_30d', 10.0)
    if vol_30d <= 12:
        vol_score = 9    # 极低波动（红利ETF正常）
    elif vol_30d <= 18:
        vol_score = 6    # 正常范围
    elif vol_30d <= 25:
        vol_score = 3    # 偏高（港股红利ETF可能出现）
    else:
        vol_score = 0    # 异常高波

    # 维度7 · RSI动量方向（10分）— V4.0新增
    rsi_slope = ind.get('rsi_slope5', 0.0)
    if rsi_slope >= 3.0:
        rsi_dir_score = 10   # 强反弹（超卖回升确认）
    elif rsi_slope >= 1.0:
        rsi_dir_score = 7    # 温和回升
    elif rsi_slope >= -1.0:
        rsi_dir_score = 4    # 横盘筑底
    elif rsi_slope >= -3.0:
        rsi_dir_score = 1    # 持续下行
    else:
        rsi_dir_score = 0    # 急跌中

    total = env_score + rsi_score + bias_score + yield_score + boll_score + vol_score + rsi_dir_score
    total = min(total, 100)

    return {
        'total': total,
        'breakdown': {
            'env': env_score,
            'rsi': rsi_score,
            'bias': bias_score,
            'yield': yield_score,
            'boll': boll_score,
            'vol': vol_score,
            'rsi_dir': rsi_dir_score,
        }
    }


def cross_validate_dividend_signal(ind: dict, regime: str) -> dict:
    """
    V4.0 · 温和版信号交叉验证
    调用均值回归评分引擎做技术面健康度检查
    返回: {warning: bool, mr_score: int, message: str}
    """
    # 红利策略的交叉验证门槛比动量低10分（有股息率安全边际）
    XV_SAFETY_GATE = {"BULL": 50, "RANGE": 55, "BEAR": 65, "CRASH": 999}
    gate = XV_SAFETY_GATE.get(regime, 55)

    try:
        from mean_reversion_engine import calculate_score
        # 构造均值回归评分所需的输入
        mr_input = {
            'rsi': ind.get('rsi', 50),
            'bias': ind.get('bias', 0),
            'boll_position': (
                (ind['close'] - ind['boll_lower']) / (ind['boll_upper'] - ind['boll_lower']) * 100
                if (ind['boll_upper'] - ind['boll_lower']) > 0 else 50
            ),
            'rsi_slope5': ind.get('rsi_slope5', 0),
            'kline_pattern': 'none',
        }
        score_result = calculate_score(mr_input, regime)
        if isinstance(score_result, dict):
            mr_score = score_result.get('total', 50)
        else:
            mr_score = int(score_result)

        warning = mr_score < gate
        msg = f"[WARN] 技术面警告: 均值回归评分{mr_score}<门槛{gate}" if warning else ""
        return {'warning': warning, 'mr_score': mr_score, 'message': msg}

    except Exception as e:
        return {'warning': False, 'mr_score': -1, 'message': f"交叉验证不可用: {str(e)[:50]}"}


def run_dividend_strategy(regime: str = None) -> dict:
    """
    运行全量红利趋势策略 V3.2
    V3.2 升级：regime 为 None 时自动调用统一 Regime 算法识别
    regime：外部传入市场状态（BULL/RANGE/BEAR/CRASH）
            若为None，自动识别（与均值回归/信号评分系统算法一致）
    """
    if not regime:
        try:
            from mean_reversion_engine import detect_regime
            regime_info = detect_regime()
            regime = regime_info.get("regime", DEFAULT_REGIME)
            print(f"[红利引擎] 自动识别 Regime: {regime} ({regime_info.get('regime_cn', '')})")
        except Exception as e:
            regime = DEFAULT_REGIME
            print(f"[红利引擎] Regime自动识别失败，使用默认{DEFAULT_REGIME}: {e}")
    else:
        regime = regime.upper()

    if regime not in REGIME_PARAMS:
        regime = DEFAULT_REGIME

    p = REGIME_PARAMS[regime]

    print(f"[红利引擎] ========= 红利趋势策略 V3.2 启动 =========")
    print(f"[红利引擎] 市场状态: {regime} | {p['note']}")
    print(f"[红利引擎] 参数: MA趋势={p['ma_trend']}d RSI≤{p['rsi_buy']}/≥{p['rsi_sell']} "
          f"BIAS≤{p['bias_buy']}%/≥{p['bias_sell']}% Defend=MA{p['ma_defend']} "
          f"仓位上限={int(p['pos_cap']*100)}%")

    etf_data = fetch_etf_data_by_code(days=150)

    results = []
    errors  = []

    for item in DIVIDEND_POOL:
        code = item['code']
        try:
            df = etf_data.get(code)
            if df is None or len(df) < max(p['ma_trend'], 100):
                count = len(df) if df is not None else 0
                errors.append({
                    "code": code, "name": item['name'],
                    "error": f"历史数据不足({count}条)"
                })
                continue

            ind    = calculate_indicators(df, code, p)
            signal, suggested_pos = generate_signal(ind, item['weight'], p, regime)
            score_result = score_etf(ind, regime, p)
            xv = cross_validate_dividend_signal(ind, regime)

            results.append({
                'code':               code.split('.')[0],
                'name':               item['name'],
                'close':              ind['close'],
                'ttm_yield':          ind['ttm_yield'],
                'yield_class':        ind['yield_class'],
                'ma100':              ind['ma_trend'],
                'trend':              'UP' if ind['close'] > ind['ma_trend'] else 'DOWN',
                'rsi':                ind['rsi'],
                'rsi_slope5':         ind.get('rsi_slope5', 0),
                'bias':               ind['bias'],
                'vol_30d':            ind.get('vol_30d', 0),
                'boll_pos':           round(
                    (ind['close'] - ind['boll_lower']) /
                    (ind['boll_upper'] - ind['boll_lower']) * 100, 1
                ) if (ind['boll_upper'] - ind['boll_lower']) > 0 else 50,
                'signal':             signal,
                'suggested_position': suggested_pos,
                'signal_score':       score_result['total'],
                'score_breakdown':    score_result['breakdown'],
                'xv_warning':         xv['warning'],
                'xv_message':         xv['message'],
            })

        except Exception as e:
            errors.append({"code": code, "name": item['name'], "error": str(e)})
            traceback.print_exc()

    # 市场概览统计
    buy_count       = len([r for r in results if r['signal'] == 'buy'])
    sell_count      = len([r for r in results if r['signal'] == 'sell'])
    trend_up_count  = len([r for r in results if r['trend'] == 'UP'])
    raw_total_pos   = sum(r['suggested_position'] for r in results if r['signal'] != 'sell')

    # 仓位上限约束（状态自适应）
    pos_cap_pct = int(p['pos_cap'] * 100)
    total_pos   = min(raw_total_pos, pos_cap_pct)

    print(f"[红利引擎] 完成: {len(results)}只有信号, {len(errors)}只异常")
    print(f"[红利引擎] 趋势向上:{trend_up_count}, 买入:{buy_count}, 卖出:{sell_count}, "
          f"仓位:{total_pos}%（上限{pos_cap_pct}%）")

    return {
        "status":    "success",
        "timestamp": datetime.now().isoformat(),
        "regime":    regime,
        "data": {
            "signals": results,
            "market_overview": {
                "trend_up_count":    trend_up_count,
                "buy_count":         buy_count,
                "sell_count":        sell_count,
                "total_suggested_pos": total_pos,
                "pos_cap":           pos_cap_pct,
            },
            "regime_params": {
                "regime":     regime,
                "note":       p['note'],
                "ma_trend":   p['ma_trend'],
                "rsi_buy":    p['rsi_buy'],
                "rsi_sell":   p['rsi_sell'],
                "bias_buy":   p['bias_buy'],
                "bias_sell":  p['bias_sell'],
                "ma_defend":  p['ma_defend'],
                "pos_cap":    pos_cap_pct,
                "entry_gate": p['entry_gate'],
            },
            "errors": errors,
        }
    }


if __name__ == "__main__":
    import json
    print("正在运行红利趋势策略 V4.0（RANGE模式）...")
    result = run_dividend_strategy(regime="RANGE")
    print(json.dumps(result, ensure_ascii=False, indent=2))
