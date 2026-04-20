"""AlphaCore 产业追踪服务层 — 从 main.py L2208-2580 提取
包含: 缓存管理、价格分位、RPS、动量、热力图、Alpha Score、风险预警、投研建议
"""
import threading
import numpy as np
from datetime import datetime
from typing import Dict
from services.cache_store import get_cache_ttl

# V6.0 Tracking 多级缓存
_TRACKING_CACHE: Dict[str, dict] = {}
_TRACKING_CACHE_MAX_HISTORY = 5
_TRACKING_LOCK = threading.Lock()

def _get_tracking_ttl() -> int:
    """产业追踪缓存 TTL (智能跟随盘口状态)
    盘中: 5分钟 (高频刷新)
    盘后: 1小时 (无新数据)
    周末: 24小时 (绝对静默)
    """
    return get_cache_ttl()  # 复用全局智能 TTL 函数

def _tracking_cache_get(cache_key: str = "latest") -> tuple:
    """线程安全读取指定日期的缓存 → (data_list, timestamp_str, is_valid)"""
    with _TRACKING_LOCK:
        slot = _TRACKING_CACHE.get(cache_key)
        if not slot:
            return None, None, False
        data = slot.get("data")
        ts = slot.get("timestamp")
    if not data or not ts:
        return data, ts, False
    try:
        age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
        ttl = _get_tracking_ttl()
        return data, ts, age < ttl
    except Exception:
        return data, ts, False

def _tracking_cache_set(cache_key: str, sector_data: list):
    """线程安全写入指定日期的缓存 + LRU 淘汰"""
    with _TRACKING_LOCK:
        _TRACKING_CACHE[cache_key] = {
            "data": sector_data,
            "timestamp": datetime.now().isoformat()
        }
        # LRU 淘汰: 超出限额时删除最旧的历史缓存 (保留 latest)
        history_keys = [k for k in _TRACKING_CACHE if k != "latest"]
        if len(history_keys) > _TRACKING_CACHE_MAX_HISTORY:
            oldest = sorted(history_keys, key=lambda k: _TRACKING_CACHE[k].get("timestamp", ""))[:len(history_keys) - _TRACKING_CACHE_MAX_HISTORY]
            for k in oldest:
                del _TRACKING_CACHE[k]

def compute_price_percentile(p_df, lookback_days: int = 1250) -> float:
    """
    V4.0 价格百分位 (替代硬编码PE分位)
    当前价格在过去N个交易日中的百分位位置
    lookback_days=1250 ≈ 5年交易日
    低百分位=便宜(均值回归机会)  高百分位=昂贵(回撤风险)
    """
    if p_df.empty or len(p_df) < 20:
        return 50.0  # 数据不足返回中性
    closes = p_df['close'].values
    # 取可用的历史数据(最多lookback_days)
    history = closes[-min(len(closes), lookback_days):]
    current = float(closes[-1])
    # 百分位 = 低于当前价的天数 / 总天数 × 100
    percentile = float(np.sum(history < current)) / len(history) * 100
    return round(min(100, max(0, percentile)), 1)


def compute_dynamic_rps(sector_data: list, code: str) -> float:
    """
    V4.0 动态RPS (Relative Price Strength)
    基于12个ETF的20D收益率，计算当前ETF在池内的排名百分位
    V5.1 Fix P2#10: 当 ret_20d 全为 0 时返回中性 50，避免随机排名误导
    """
    if not sector_data:
        return 50.0
    # Fix P2#10: 全0检测 — 数据未就绪时所有 ETF 均为中性
    if all(d.get('ret_20d', 0) == 0 for d in sector_data):
        return 50.0
    # 按 ret_20d 排序
    sorted_data = sorted(sector_data, key=lambda x: x.get('ret_20d', 0))
    total = len(sorted_data)
    for i, d in enumerate(sorted_data):
        if (d.get('ts_code') or d.get('code')) == code:
            return round((i + 1) / total * 100, 1)
    return 50.0


def compute_momentum_20d(p_df) -> dict:
    """
    V4.0 20D动量趋势卡 (替代虚假北向资金卡)
    返回: 20D累计收益 + 趋势方向 + 动量强度描述
    """
    if p_df.empty or len(p_df) < 20:
        return {"ret_20d": 0.0, "label": "数据不足", "trend": "neutral"}
    closes = p_df['close'].values
    ret = round(float((closes[-1] / closes[-20] - 1) * 100), 2)
    if ret > 5:
        label, trend = f"+{ret:.1f}% 强势上攻", "strong_up"
    elif ret > 2:
        label, trend = f"+{ret:.1f}% 温和上行", "up"
    elif ret > -2:
        label, trend = f"{ret:+.1f}% 横盘震荡", "neutral"
    elif ret > -5:
        label, trend = f"{ret:.1f}% 弱势调整", "down"
    else:
        label, trend = f"{ret:.1f}% 深度回调", "strong_down"
    return {"ret_20d": ret, "label": label, "trend": trend}

def compute_sector_heat_score(p_df, trend_5d: float) -> dict:
    """
    V2.0 资金热度多因子引擎
    三因子加权: 成交额放量比(40%) + 5D价格动量(35%) + 拥挤度修正(25%)
    输出: heat_score 0-100, heat_tier 分层标签
    """
    if p_df.empty or len(p_df) < 5:
        return {"heat_score": 30.0, "heat_tier": "❄️ 冷淡", "vol_ratio": 1.0,
                "vol_score": 50.0, "mom_score": 50.0, "crowd_score": 80.0}

    latest_amount = float(p_df['amount'].iloc[-1]) if 'amount' in p_df.columns else 0
    vol_ma20 = float(p_df['amount'].tail(20).mean()) if 'amount' in p_df.columns else 1

    # 因子 A: 成交额放量比 (1x=50分, 1.5x=75分, 2x=100分)
    vol_ratio = latest_amount / vol_ma20 if vol_ma20 > 0 else 1.0
    vol_score = min(100, max(0, vol_ratio * 50))

    # 因子 B: 5D 价格动量 (0%=50分, +3%=80分, -3%=20分)
    mom_score = min(100, max(0, 50 + trend_5d * 10))

    # 因子 C: 拥挤度修正 (1x=满分, >2x 开始惩罚)
    if vol_ratio > 2.0:
        crowd_score = max(0, 100 - (vol_ratio - 2.0) * 60)
    else:
        crowd_score = 80 + min(20, vol_ratio * 10)

    # 加权合成
    heat_score = vol_score * 0.40 + mom_score * 0.35 + crowd_score * 0.25
    heat_score = round(min(100, max(0, heat_score)), 1)

    # 分层
    if heat_score >= 70:
        tier = "🔥 激进"
    elif heat_score >= 45:
        tier = "⚡ 活跃"
    else:
        tier = "❄️ 冷淡"

    return {
        "heat_score": heat_score,
        "heat_tier": tier,
        "vol_ratio": round(vol_ratio, 2),
        "vol_score": round(vol_score, 1),
        "mom_score": round(mom_score, 1),
        "crowd_score": round(crowd_score, 1)
    }


def compute_alpha_score(p_df, heat_score: float, trend_5d: float, pe_pct: float) -> dict:
    """
    V3.0 综合投资评分引擎 (Alpha Score)
    四因子加权:
      热度因子(30%): 直接取 heat_score
      动量因子(25%): 5D动量(60%) + 20D趋势(40%)，归一化到0-100
      估值安全(25%): 100 - PE百分位 (低估=高分)
      趋势强度(20%): 站上MA20 + 站上MA60 + MA20斜率
    输出: alpha_score 0-100, alpha_grade A/B/C/D/F, trend_strength{}
    """
    # --- 因子 1: 热度 (直接复用) ---
    f_heat = min(100, max(0, heat_score))

    # --- 因子 2: 动量 (5D + 20D 混合) ---
    ret_20d = 0.0
    if not p_df.empty and len(p_df) >= 20:
        ret_20d = round(float((p_df['close'].iloc[-1] / p_df['close'].iloc[-20] - 1) * 100), 2)
    mom_5d_score = min(100, max(0, 50 + trend_5d * 10))   # 与 heat 同口径
    mom_20d_score = min(100, max(0, 50 + ret_20d * 5))     # 20D 灵敏度略低
    f_momentum = mom_5d_score * 0.60 + mom_20d_score * 0.40

    # --- 因子 3: 估值安全 (反转: 低PE=高分) ---
    f_valuation = min(100, max(0, 100 - pe_pct))

    # --- 因子 4: 趋势强度 (MA体系) ---
    above_ma20 = False
    above_ma60 = False
    ma20_slope = 0.0
    if not p_df.empty and len(p_df) >= 60:
        closes = p_df['close'].values
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:]))
        latest = float(closes[-1])
        above_ma20 = latest > ma20
        above_ma60 = latest > ma60
        # MA20 斜率: (MA20_now - MA20_5d_ago) / MA20_5d_ago * 100
        if len(closes) >= 25:
            ma20_5d_ago = float(np.mean(closes[-25:-5]))
            ma20_slope = round((ma20 / ma20_5d_ago - 1) * 100, 3) if ma20_5d_ago > 0 else 0.0
    elif not p_df.empty and len(p_df) >= 20:
        closes = p_df['close'].values
        ma20 = float(np.mean(closes[-20:]))
        latest = float(closes[-1])
        above_ma20 = latest > ma20

    trend_pts = 0
    if above_ma20: trend_pts += 30
    if above_ma60: trend_pts += 30
    trend_pts += min(40, max(0, (ma20_slope + 1) * 20))  # 斜率归一化
    f_trend = min(100, max(0, trend_pts))

    # --- 加权合成 ---
    alpha_score = f_heat * 0.30 + f_momentum * 0.25 + f_valuation * 0.25 + f_trend * 0.20
    alpha_score = round(min(100, max(0, alpha_score)), 1)

    # --- 评级 ---
    if alpha_score >= 80:
        grade = "A"
    elif alpha_score >= 65:
        grade = "B"
    elif alpha_score >= 50:
        grade = "C"
    elif alpha_score >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "alpha_score": alpha_score,
        "alpha_grade": grade,
        "ret_20d": ret_20d,
        "f_heat": round(f_heat, 1),
        "f_momentum": round(f_momentum, 1),
        "f_valuation": round(f_valuation, 1),
        "f_trend": round(f_trend, 1),
        "trend_strength": {
            "above_ma20": above_ma20,
            "above_ma60": above_ma60,
            "ma20_slope": ma20_slope
        }
    }


def compute_risk_alerts(vol_ratio: float, pe_pct: float, trend_5d: float,
                         heat_score: float, crowd_score: float) -> list:
    """
    V3.0 风险警示检测引擎
    根据多个条件产出 0~N 条风险警示或正面信号
    """
    alerts = []

    # ⚠️ 拥挤度过高 — 追高风险
    if vol_ratio > 2.0:
        alerts.append({
            "level": "danger",
            "icon": "🔴",
            "text": f"拥挤度 {vol_ratio:.1f}x 场内过度拥挤，追高风险极大",
            "metric": "crowd"
        })
    elif vol_ratio > 1.5:
        alerts.append({
            "level": "warning",
            "icon": "🟡",
            "text": f"拥挤度 {vol_ratio:.1f}x 偏高，注意仓位控制",
            "metric": "crowd"
        })

    # ⚠️ PE分位过高 — 估值泡沫
    if pe_pct > 80:
        alerts.append({
            "level": "danger",
            "icon": "🔴",
            "text": f"PE分位 {pe_pct:.0f}% 历史极高估区域",
            "metric": "pe"
        })
    elif pe_pct > 70:
        alerts.append({
            "level": "warning",
            "icon": "🟡",
            "text": f"PE分位 {pe_pct:.0f}% 估值偏高",
            "metric": "pe"
        })

    # ⚠️ 短期暴涨 + 拥挤 — 见顶信号
    if trend_5d > 8 and vol_ratio > 1.5:
        alerts.append({
            "level": "danger",
            "icon": "🔴",
            "text": f"5D暴涨 +{trend_5d:.1f}% 且拥挤 {vol_ratio:.1f}x → 见顶概率高",
            "metric": "top_signal"
        })

    # ⚠️ 热度过热 — 情绪过热
    if heat_score > 85:
        alerts.append({
            "level": "warning",
            "icon": "🟡",
            "text": f"热度 {heat_score:.0f} 资金过度聚集，警惕回调",
            "metric": "overheat"
        })

    # 🛡️ 正面信号: 深度价值区
    if pe_pct < 15 and heat_score < 40:
        alerts.append({
            "level": "positive",
            "icon": "💎",
            "text": f"PE仅 {pe_pct:.0f}% + 关注度低 → 深度价值区",
            "metric": "deep_value"
        })

    # 🛡️ 正面信号: 放量突破
    if vol_ratio > 1.3 and trend_5d > 3 and pe_pct < 50:
        alerts.append({
            "level": "positive",
            "icon": "🚀",
            "text": f"放量 {vol_ratio:.1f}x 突破 +{trend_5d:.1f}%，估值安全",
            "metric": "breakout"
        })

    return alerts


def generate_sector_advice(alpha_score: float, alpha_grade: str, heat_score: float,
                           pe_pct: float, trend_5d: float, trend_strength: dict) -> dict:
    """
    V3.0 五级投资建议矩阵
    基于 Alpha Score 驱动，附带量化买入/止盈策略
    """
    above_ma20 = trend_strength.get("above_ma20", False)
    above_ma60 = trend_strength.get("above_ma60", False)

    if alpha_grade == "A":  # Alpha >= 80
        return {
            "text": "低估+放量+强势，最佳配置窗口",
            "action": "strong_buy",
            "label": "🟢 强力买入",
            "buy_strategy": "分批建仓 20%→40%→60%，5-10个交易日完成",
            "take_profit": "PE分位升至>70% 或 热度分降至<40 或 动量衰减连续3日",
            "stop_loss": "跌破MA60 无条件止损",
            "position_cap": "单行业上限60%"
        }
    elif alpha_grade == "B":  # Alpha 65-79
        return {
            "text": "热度好估值合理，可积极参与",
            "action": "buy",
            "label": "🟢 积极关注",
            "buy_strategy": "左侧小仓试探 10%→20%，确认站稳MA20后加至30%",
            "take_profit": "热度分降至<40 或 跌破MA20",
            "stop_loss": "跌破MA60 或 5D回撤>-6%",
            "position_cap": "单行业上限30%"
        }
    elif alpha_grade == "C":  # Alpha 50-64
        return {
            "text": "均衡态势，列入观察池等待确认",
            "action": "watch",
            "label": "🔵 跟踪观察",
            "buy_strategy": "暂不建仓，等待Alpha升至65+再介入",
            "take_profit": "—",
            "stop_loss": "—",
            "position_cap": "0%（仅观察）"
        }
    elif alpha_grade == "D":  # Alpha 35-49
        return {
            "text": "热度降温或估值偏高，谨慎持有",
            "action": "caution",
            "label": "🟡 谨慎持有",
            "buy_strategy": "已持仓者减至半仓，新资金禁入",
            "take_profit": "立即止盈已有浮盈仓位",
            "stop_loss": "跌破MA60 全部离场",
            "position_cap": "已持仓减至<15%"
        }
    else:  # F, Alpha < 35
        return {
            "text": "冷门+高估+弱势，严格回避",
            "action": "avoid",
            "label": "🔴 回避清仓",
            "buy_strategy": "严禁新建仓",
            "take_profit": "若持有立即清仓",
            "stop_loss": "无条件清仓",
            "position_cap": "0%"
        }

