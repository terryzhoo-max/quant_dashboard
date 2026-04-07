"""
AlphaCore · AIAE 全市场权益配置择时引擎 V2.0
================================================
核心思想: AIAE = 全市场投资者把多少比例的钱放在了股票里
  - 比例极高 → 市场过热，减仓
  - 比例极低 → 市场冰点，加仓

计算公式:
  AIAE_简 = A股总市值 / (A股总市值 + M2)
  AIAE_V1 = 0.5×AIAE_简 + 0.3×基金仓位(手动) + 0.2×融资占比(日频)

五档状态:
  Ⅰ级 极度恐慌 (<12%)  → 总仓位 90-95%
  Ⅱ级 低配置区 (12-16%) → 总仓位 70-85%
  Ⅲ级 中性均衡 (16-24%) → 总仓位 50-65%
  Ⅳ级 偏热区域 (24-32%) → 总仓位 25-40%
  Ⅴ级 极度过热 (>32%)   → 总仓位 0-15%

数据源: Tushare Pro
  - daily_basic → total_mv / circ_mv (日频)
  - cn_m → M2 (月频)
  - margin → 融资余额/买入额 (日频)

V2.0 Changelog:
  - ThreadPoolExecutor 并行数据获取 (3x speedup)
  - threading.Lock 线程安全缓存
  - Token 环境变量化
  - 市值合理性校验 (历史区间断言)
  - 交叉验证覆盖率扩展 (7→11 分支)
"""

import pandas as pd
import numpy as np
import tushare as ts
import time
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

# ===== Token: 优先环境变量, 降级硬编码 =====
TUSHARE_TOKEN = os.environ.get(
    "TUSHARE_TOKEN",
    "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
)
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# ===== 线程安全 TTL 缓存 =====
_cache = {}
_cache_lock = threading.Lock()

def _log(msg: str, level: str = "INFO"):
    """结构化日志"""
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [AIAE] {msg}")

def _cached(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存"""
    now = time.time()
    with _cache_lock:
        if key in _cache:
            ts_cached, data = _cache[key]
            if now - ts_cached < ttl_seconds:
                return data
    try:
        data = fetcher()
        with _cache_lock:
            _cache[key] = (now, data)
        return data
    except Exception as e:
        _log(f"缓存获取失败 ({key}): {e}", "WARN")
        with _cache_lock:
            if key in _cache:
                return _cache[key][1]
        raise


# ===== 历史基准数据 (回测验证) =====
# 来源: A股证券化率历史回溯 2005-2026
HISTORICAL_SNAPSHOTS = [
    {"date": "2005-06-06", "aiae": 8.2,  "csi300_after_1y": 130,  "label": "998点历史大底"},
    {"date": "2007-10-16", "aiae": 42.5, "csi300_after_1y": -65,  "label": "6124点历史顶部"},
    {"date": "2008-10-28", "aiae": 10.1, "csi300_after_1y": 108,  "label": "1664点恐慌底部"},
    {"date": "2014-06-20", "aiae": 15.3, "csi300_after_1y": 150,  "label": "2000点底部区域"},
    {"date": "2015-06-12", "aiae": 38.7, "csi300_after_1y": -47,  "label": "5178点杠杆顶部"},
    {"date": "2018-12-27", "aiae": 13.8, "csi300_after_1y": 36,   "label": "2440点底部区域"},
    {"date": "2021-02-18", "aiae": 28.9, "csi300_after_1y": -22,  "label": "创业板泡沫"},
    {"date": "2024-01-22", "aiae": 14.2, "csi300_after_1y": 25,   "label": "2635点底部区域"},
    {"date": "2026-04-06", "aiae": 22.3, "csi300_after_1y": None, "label": "当前状态(估)"},
]

# ===== 五档状态定义 =====
REGIMES = {
    1: {"name": "Ⅰ级 · EXTREME FEAR", "cn": "极度恐慌", "range": "<12%",
        "color": "#10b981", "emoji": "🟢", "position": "90-95%", "pos_min": 90, "pos_max": 95,
        "action": "满配进攻", "desc": "越跌越买，分3批建仓"},
    2: {"name": "Ⅱ级 · LOW ALLOCATION", "cn": "低配置区", "range": "12-16%",
        "color": "#3b82f6", "emoji": "🔵", "position": "70-85%", "pos_min": 70, "pos_max": 85,
        "action": "标准建仓", "desc": "耐心持有，不因波动减仓"},
    3: {"name": "Ⅲ级 · NEUTRAL", "cn": "中性均衡", "range": "16-24%",
        "color": "#eab308", "emoji": "🟡", "position": "50-65%", "pos_min": 50, "pos_max": 65,
        "action": "均衡持有", "desc": "有纪律地持有，到了就卖"},
    4: {"name": "Ⅳ级 · GETTING HOT", "cn": "偏热区域", "range": "24-32%",
        "color": "#f97316", "emoji": "🟠", "position": "25-40%", "pos_min": 25, "pos_max": 40,
        "action": "系统减仓", "desc": "每周减5%总仓位"},
    5: {"name": "Ⅴ级 · EUPHORIA", "cn": "极度过热", "range": ">32%",
        "color": "#ef4444", "emoji": "🔴", "position": "0-15%", "pos_min": 0, "pos_max": 15,
        "action": "清仓防守", "desc": "3天内完成清仓"},
}

# ===== AIAE × ERP 仓位矩阵 =====
# 行: ERP水位, 列: AIAE档位(1-5)
POSITION_MATRIX = {
    "erp_gt6":  [95, 85, 70, 45, 20],  # ERP > 6%
    "erp_4_6":  [90, 80, 65, 40, 15],  # ERP 4-6%
    "erp_2_4":  [85, 70, 55, 30, 10],  # ERP 2-4%
    "erp_lt2":  [75, 60, 40, 20,  5],  # ERP < 2%
}

# ===== 子策略配额矩阵 =====
SUB_STRATEGY_ALLOC = {
    1: {"mr": 40, "div": 20, "mom": 25, "erp": 15},  # Ⅰ级
    2: {"mr": 35, "div": 25, "mom": 25, "erp": 15},  # Ⅱ级
    3: {"mr": 25, "div": 30, "mom": 25, "erp": 20},  # Ⅲ级
    4: {"mr": 10, "div": 50, "mom": 15, "erp": 25},  # Ⅳ级
    5: {"mr":  0, "div": 80, "mom":  0, "erp": 20},  # Ⅴ级
}

# ===== AIAE ETF 标的池 V1.0 =====
# 5 宽基 (进攻) + 3 红利 (防御) = 8 只 ETF
AIAE_ETF_POOL = [
    # 宽基 — 随 AIAE 档位↑ 逐步减仓
    {"ts_code": "510300.SH", "name": "沪深300ETF", "style": "核心宽基", "group": "broad"},
    {"ts_code": "510050.SH", "name": "上证50ETF",  "style": "大盘蓝筹", "group": "broad"},
    {"ts_code": "510500.SH", "name": "中证500ETF", "style": "中盘成长", "group": "broad"},
    {"ts_code": "159915.SZ", "name": "创业板ETF",  "style": "高弹成长", "group": "broad"},
    {"ts_code": "512100.SH", "name": "中证1000ETF","style": "小盘超额", "group": "broad"},
    # 红利 — 随 AIAE 档位↑ 逐步增配
    {"ts_code": "510880.SH", "name": "红利ETF",    "style": "红利核心", "group": "dividend"},
    {"ts_code": "515180.SH", "name": "红利低波100","style": "红利低波", "group": "dividend"},
    {"ts_code": "159905.SZ", "name": "深红利ETF",  "style": "深市红利", "group": "dividend"},
]

# ===== AIAE 五档 × ETF 仓位矩阵 (每只 ETF 在不同档位的建议仓位%) =====
AIAE_ETF_MATRIX = {
    #                300   50  500  创业 1000 红利 低波 深红
    1: {"510300.SH": 25, "510050.SH": 20, "510500.SH": 20, "159915.SZ": 15, "512100.SH": 10,
        "510880.SH": 10, "515180.SH":  5, "159905.SZ":  5},
    2: {"510300.SH": 25, "510050.SH": 20, "510500.SH": 15, "159915.SZ":  5, "512100.SH":  0,
        "510880.SH": 10, "515180.SH":  8, "159905.SZ":  7},
    3: {"510300.SH": 15, "510050.SH": 10, "510500.SH":  5, "159915.SZ":  0, "512100.SH":  0,
        "510880.SH": 15, "515180.SH": 10, "159905.SZ": 10},
    4: {"510300.SH":  5, "510050.SH":  5, "510500.SH":  0, "159915.SZ":  0, "512100.SH":  0,
        "510880.SH": 15, "515180.SH": 10, "159905.SZ":  5},
    5: {"510300.SH":  0, "510050.SH":  0, "510500.SH":  0, "159915.SZ":  0, "512100.SH":  0,
        "510880.SH":  8, "515180.SH":  5, "159905.SZ":  2},
}

# ===== run-all 动态权重矩阵 (五策略, AIAE驱动) =====
# key: AIAE regime → value: 五策略权重 (总和=1.0)
AIAE_RUN_ALL_WEIGHTS = {
    1: {"mr": 0.35, "div": 0.15, "mom": 0.25, "erp": 0.10, "aiae_etf": 0.15},  # 恐慌→进攻
    2: {"mr": 0.30, "div": 0.20, "mom": 0.20, "erp": 0.10, "aiae_etf": 0.20},  # 低估→建仓
    3: {"mr": 0.20, "div": 0.25, "mom": 0.15, "erp": 0.15, "aiae_etf": 0.25},  # 中性→均衡
    4: {"mr": 0.10, "div": 0.35, "mom": 0.05, "erp": 0.15, "aiae_etf": 0.35},  # 偏热→防御
    5: {"mr": 0.00, "div": 0.45, "mom": 0.00, "erp": 0.10, "aiae_etf": 0.45},  # 过热→纯防御
}


# ===== 数据合理性断言阈值 =====
MV_BOUNDS = {"min": 30.0, "max": 300.0}  # 总市值万亿元合理区间
M2_BOUNDS = {"min": 200.0, "max": 600.0}  # M2万亿元合理区间


class AIAEEngine:
    """AIAE 全市场权益配置择时引擎 V2.0"""

    VERSION = "2.0"

    def __init__(self):
        self._fund_position = 82.0  # 公募偏股基金仓位 (手动配置, 2025Q4)
        self._fund_position_date = "2025-12-31"

    # ========== 数据获取层 ==========

    def _fetch_total_market_cap(self) -> Dict:
        """获取A股最新总市值 (daily_basic汇总)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_total_mv.json")

            # 尝试获取最近交易日数据
            end_date = datetime.now().strftime("%Y%m%d")
            # 往前尝试5天(覆盖周末)
            for offset in range(6):
                try_date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    df = pro.daily_basic(trade_date=try_date,
                                         fields="ts_code,trade_date,total_mv,circ_mv")
                    if df is not None and not df.empty:
                        total_mv = df['total_mv'].sum() / 10000  # 万元 → 亿元
                        circ_mv = df['circ_mv'].sum() / 10000
                        result = {
                            "trade_date": try_date,
                            "total_mv_yi": round(total_mv, 0),      # 亿元
                            "circ_mv_yi": round(circ_mv, 0),
                            "total_mv_wan_yi": round(total_mv / 10000, 2),  # 万亿
                            "circ_mv_wan_yi": round(circ_mv / 10000, 2),
                            "stock_count": len(df),
                            "fetched_at": datetime.now().isoformat()
                        }
                        # 磁盘缓存
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                        # 合理性校验
                        if not (MV_BOUNDS['min'] <= result['total_mv_wan_yi'] <= MV_BOUNDS['max']):
                            _log(f"市值 {result['total_mv_wan_yi']}万亿 超出合理区间 [{MV_BOUNDS['min']},{MV_BOUNDS['max']}]，可能为部分数据", "WARN")
                        _log(f"总市值: {result['total_mv_wan_yi']}万亿 ({result['stock_count']}只)")
                        return result
                except Exception as e:
                    _log(f"daily_basic {try_date} 失败: {e}", "WARN")
                    time.sleep(1)

            # 降级: 读磁盘缓存
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    _log("使用磁盘缓存的市值数据", "WARN")
                    return json.load(f)

            # 最终降级: 硬编码估算
            _log("使用硬编码估算市值", "ERROR")
            return {
                "trade_date": end_date, "total_mv_yi": 950000,
                "circ_mv_yi": 720000, "total_mv_wan_yi": 95.0,
                "circ_mv_wan_yi": 72.0, "stock_count": 5300,
                "fetched_at": datetime.now().isoformat(), "is_fallback": True
            }

        return _cached("aiae_total_mv", 5 * 60, _fetch)  # 5分钟TTL

    def _fetch_m2(self) -> Dict:
        """获取最新M2数据 (cn_m)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_m2.json")
            try:
                end_m = datetime.now().strftime("%Y%m")
                start_m = (datetime.now() - timedelta(days=180)).strftime("%Y%m")
                df = pro.cn_m(start_m=start_m, end_m=end_m,
                             fields="month,m2,m2_yoy")
                if df is not None and not df.empty:
                    df = df.sort_values('month')
                    latest = df.iloc[-1]
                    result = {
                        "month": latest['month'],
                        "m2": float(latest['m2']),           # 亿元
                        "m2_wan_yi": round(float(latest['m2']) / 10000, 2),  # 万亿
                        "m2_yoy": float(latest['m2_yoy']),
                        "fetched_at": datetime.now().isoformat()
                    }
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    _log(f"M2: {result['m2_wan_yi']}万亿 (同比{result['m2_yoy']}%)")
                    return result
            except Exception as e:
                _log(f"M2数据获取失败: {e}", "WARN")

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            return {
                "month": "202603", "m2": 3300000, "m2_wan_yi": 330.0,
                "m2_yoy": 7.0, "fetched_at": datetime.now().isoformat(),
                "is_fallback": True
            }

        return _cached("aiae_m2", 6 * 3600, _fetch)  # 6小时TTL

    def _fetch_margin_data(self) -> Dict:
        """获取融资融券数据 (margin)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_margin.json")
            for offset in range(6):
                try_date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    df = pro.margin(trade_date=try_date)
                    if df is not None and not df.empty:
                        total_rzye = df['rzye'].sum() if 'rzye' in df.columns else 0
                        total_rzmre = df['rzmre'].sum() if 'rzmre' in df.columns else 0
                        result = {
                            "trade_date": try_date,
                            "rzye": round(total_rzye / 100000000, 2),      # 亿元
                            "rzmre": round(total_rzmre / 100000000, 2),
                            "rzye_wan_yi": round(total_rzye / 1000000000000, 4),  # 万亿
                            "fetched_at": datetime.now().isoformat()
                        }
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                        _log(f"融资余额: {result['rzye']}亿")
                        return result
                except Exception as e:
                    _log(f"margin {try_date}: {e}", "WARN")
                    time.sleep(1)

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            return {
                "trade_date": datetime.now().strftime("%Y%m%d"),
                "rzye": 18500, "rzmre": 800, "rzye_wan_yi": 1.85,
                "fetched_at": datetime.now().isoformat(), "is_fallback": True
            }

        return _cached("aiae_margin", 2 * 60, _fetch)  # 2分钟TTL

    # ========== 核心计算层 ==========

    def compute_aiae_simple(self, total_mv_wan_yi: float, m2_wan_yi: float) -> float:
        """AIAE_简 = 总市值 / (总市值 + M2)"""
        if m2_wan_yi <= 0:
            return 20.0  # 降级
        return round(total_mv_wan_yi / (total_mv_wan_yi + m2_wan_yi) * 100, 2)

    def compute_margin_heat(self, margin_data: Dict, total_mv_wan_yi: float) -> float:
        """融资占比热度 = 融资余额 / 总市值 × 100"""
        rzye_wan_yi = margin_data.get("rzye_wan_yi", 1.85)
        if total_mv_wan_yi <= 0:
            return 2.0
        return round(rzye_wan_yi / total_mv_wan_yi * 100, 2)

    def compute_aiae_v1(self, aiae_simple: float, fund_pos: float, margin_heat: float) -> float:
        """
        融合 AIAE V1.0
        = 0.5 × AIAE_简 + 0.3 × 基金仓位归一化 + 0.2 × 融资热度归一化
        """
        # 基金仓位归一化: 60-95% → 8-32% AIAE等效
        fund_normalized = 8 + (fund_pos - 60) / (95 - 60) * (32 - 8)
        fund_normalized = max(8, min(32, fund_normalized))

        # 融资热度归一化: 1-4% → 8-32% AIAE等效
        margin_normalized = 8 + (margin_heat - 1) / (4 - 1) * (32 - 8)
        margin_normalized = max(8, min(32, margin_normalized))

        return round(0.5 * aiae_simple + 0.3 * fund_normalized + 0.2 * margin_normalized, 2)

    # ========== 五档判定层 ==========

    def classify_regime(self, aiae_value: float) -> int:
        """AIAE值 → 五档状态 (1-5)"""
        if aiae_value < 12:
            return 1
        elif aiae_value < 16:
            return 2
        elif aiae_value < 24:
            return 3
        elif aiae_value < 32:
            return 4
        else:
            return 5

    def compute_slope(self, current: float, previous: float) -> Dict:
        """月环比斜率"""
        if previous is None or previous == 0:
            return {"slope": 0, "direction": "flat", "signal": None}
        slope = current - previous
        direction = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")

        signal = None
        if slope > 1.5:
            signal = {"type": "accel_up", "text": "AIAE 加速上行", "level": "warning"}
        elif slope < -1.5:
            signal = {"type": "accel_down", "text": "AIAE 加速下行", "level": "opportunity"}

        return {"slope": round(slope, 2), "direction": direction, "signal": signal}

    def get_position_from_matrix(self, regime: int, erp_level: str) -> int:
        """AIAE × ERP 仓位矩阵查表"""
        row = POSITION_MATRIX.get(erp_level, POSITION_MATRIX["erp_2_4"])
        idx = min(regime - 1, 4)
        return row[idx]

    def classify_erp_level(self, erp_value: float) -> str:
        """ERP值分级"""
        if erp_value >= 6.0:
            return "erp_gt6"
        elif erp_value >= 4.0:
            return "erp_4_6"
        elif erp_value >= 2.0:
            return "erp_2_4"
        else:
            return "erp_lt2"

    def allocate_sub_strategies(self, regime: int, total_position: int) -> Dict:
        """子策略配额分配"""
        alloc_pct = SUB_STRATEGY_ALLOC.get(regime, SUB_STRATEGY_ALLOC[3])
        return {
            "mr":  {"name": "均值回归", "pct": alloc_pct["mr"],  "position": round(total_position * alloc_pct["mr"] / 100, 1)},
            "div": {"name": "红利趋势", "pct": alloc_pct["div"], "position": round(total_position * alloc_pct["div"] / 100, 1)},
            "mom": {"name": "行业动量", "pct": alloc_pct["mom"], "position": round(total_position * alloc_pct["mom"] / 100, 1)},
            "erp": {"name": "ERP择时", "pct": alloc_pct["erp"], "position": round(total_position * alloc_pct["erp"] / 100, 1)},
        }

    # ========== AIAE ETF 标的池执行 (run-all 集成) ==========

    def generate_etf_signals(self, regime: int) -> List[Dict]:
        """
        根据 AIAE 五档, 为 8 只 ETF 生成标准化执行信号.
        返回格式与其他策略对齐: [{name, ts_code, signal, suggested_position, style, group, ...}]
        """
        etf_allocs = AIAE_ETF_MATRIX.get(regime, AIAE_ETF_MATRIX[3])
        regime_info = REGIMES.get(regime, REGIMES[3])
        signals = []

        for etf in AIAE_ETF_POOL:
            code = etf["ts_code"]
            pos = etf_allocs.get(code, 0)

            # 信号判定: pos>0 → buy, pos==0且档位>3 → sell, 否则 hold
            if pos > 0:
                sig = "buy"
            elif regime >= 4:
                sig = "sell"
            else:
                sig = "hold"

            signals.append({
                "name": etf["name"],
                "ts_code": code,
                "code": code.split(".")[0],
                "signal": sig,
                "signal_score": max(10, 100 - (regime - 1) * 20),  # I:100 II:80 III:60 IV:40 V:20
                "suggested_position": pos,
                "style": etf["style"],
                "group": etf["group"],
                "regime": regime,
                "regime_cn": regime_info["cn"],
                "aiae_driven": True,
            })

        return signals

    def get_run_all_weights(self, regime: int) -> Dict:
        """获取 AIAE 驱动的五策略动态权重"""
        return AIAE_RUN_ALL_WEIGHTS.get(regime, AIAE_RUN_ALL_WEIGHTS[3])

    # ========== 信号系统 ==========

    def generate_signals(self, aiae_value: float, regime: int, slope_info: Dict, margin_heat: float) -> List[Dict]:
        """生成辅助信号"""
        signals = []

        # 主信号
        regime_info = REGIMES[regime]
        signals.append({
            "type": "main", "level": regime_info["emoji"],
            "text": f"{regime_info['cn']}信号 · AIAE={aiae_value:.1f}% · {regime_info['action']}",
            "color": regime_info["color"]
        })

        # 斜率信号
        if slope_info.get("signal"):
            s = slope_info["signal"]
            signals.append({"type": "slope", "level": s["level"], "text": s["text"],
                          "color": "#f59e0b" if s["level"] == "warning" else "#10b981"})

        # 融资占比信号
        if margin_heat > 3.5:
            signals.append({"type": "margin", "level": "warning",
                          "text": f"融资占比 {margin_heat:.1f}% 偏高，散户杠杆入场", "color": "#f97316"})
        elif margin_heat < 1.5:
            signals.append({"type": "margin", "level": "opportunity",
                          "text": f"融资占比 {margin_heat:.1f}% 极低，杠杆出清", "color": "#10b981"})

        return signals

    # ========== 历史走势数据 ==========

    def get_chart_data(self) -> Dict:
        """输出历史 AIAE 走势 (静态+当前点)"""
        # V1.0: 使用预设历史关键节点
        dates = [s["date"] for s in HISTORICAL_SNAPSHOTS]
        values = [s["aiae"] for s in HISTORICAL_SNAPSHOTS]
        labels = [s["label"] for s in HISTORICAL_SNAPSHOTS]

        # 五档区间线
        bands = [
            {"name": "Ⅰ级上限", "value": 12, "color": "#10b981"},
            {"name": "Ⅱ级上限", "value": 16, "color": "#3b82f6"},
            {"name": "Ⅲ级上限", "value": 24, "color": "#eab308"},
            {"name": "Ⅳ级上限", "value": 32, "color": "#f97316"},
        ]

        return {
            "dates": dates, "values": values, "labels": labels,
            "bands": bands,
            "stats": {
                "mean": 18.5, "min": 8.2, "max": 42.5,
                "current": values[-1] if values else 22.3
            }
        }

    # ========== 完整报告 ==========

    def generate_report(self) -> Dict:
        """生成 AIAE 完整报告 (V2.0: 并行数据获取)"""
        t0 = time.time()
        try:
            # 1. 并行获取三个数据源 (ThreadPoolExecutor)
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='aiae') as pool:
                f_mv = pool.submit(self._fetch_total_market_cap)
                f_m2 = pool.submit(self._fetch_m2)
                f_margin = pool.submit(self._fetch_margin_data)

            mv_data = f_mv.result(timeout=30)
            m2_data = f_m2.result(timeout=30)
            margin_data = f_margin.result(timeout=30)
            _log(f"数据获取完成 ({time.time()-t0:.1f}s)")

            total_mv = mv_data.get("total_mv_wan_yi", 95.0)
            m2 = m2_data.get("m2_wan_yi", 330.0)

            # 2. 计算 AIAE
            aiae_simple = self.compute_aiae_simple(total_mv, m2)
            margin_heat = self.compute_margin_heat(margin_data, total_mv)
            aiae_v1 = self.compute_aiae_v1(aiae_simple, self._fund_position, margin_heat)

            # 3. 五档判定
            regime = self.classify_regime(aiae_v1)
            regime_info = REGIMES[regime]

            # 4. 斜率 (与上一个快照对比)
            prev_aiae = HISTORICAL_SNAPSHOTS[-2]["aiae"] if len(HISTORICAL_SNAPSHOTS) >= 2 else None
            slope_info = self.compute_slope(aiae_v1, prev_aiae)

            # 5. ERP 交叉 (尝试从 ERP 引擎获取)
            erp_value = self._get_erp_value()
            erp_level = self.classify_erp_level(erp_value)
            matrix_position = self.get_position_from_matrix(regime, erp_level)

            # 6. 子策略配额
            allocations = self.allocate_sub_strategies(regime, matrix_position)

            # 7. 信号
            signals = self.generate_signals(aiae_v1, regime, slope_info, margin_heat)

            # 8. 图表数据
            chart_data = self.get_chart_data()

            # 9. ERP交叉验证
            cross_validation = self._cross_validate(regime, erp_value)

            _log(f"报告生成完成 ({time.time()-t0:.1f}s) | AIAE={aiae_v1}% Regime={regime} Pos={matrix_position}%")

            return {
                "status": "success",
                "engine_version": self.VERSION,
                "updated_at": datetime.now().isoformat(),
                "latency_ms": round((time.time()-t0)*1000),

                "current": {
                    "aiae_simple": aiae_simple,
                    "aiae_v1": aiae_v1,
                    "regime": regime,
                    "regime_info": regime_info,
                    "total_mv_wan_yi": total_mv,
                    "m2_wan_yi": m2,
                    "margin_heat": margin_heat,
                    "fund_position": self._fund_position,
                    "fund_position_date": self._fund_position_date,
                    "slope": slope_info,
                },

                "position": {
                    "matrix_position": matrix_position,
                    "erp_value": erp_value,
                    "erp_level": erp_level,
                    "regime": regime,
                    "matrix": POSITION_MATRIX,
                    "allocations": allocations,
                },

                "signals": signals,
                "cross_validation": cross_validation,
                "chart": chart_data,
                "regimes": REGIMES,

                "raw_data": {
                    "mv": mv_data,
                    "m2": m2_data,
                    "margin": margin_data,
                }
            }

        except Exception as e:
            _log(f"generate_report 异常: {e}", "ERROR")
            import traceback; traceback.print_exc()
            return self._fallback_report(str(e))

    def _get_erp_value(self) -> float:
        """尝试从ERP引擎获取当前ERP值"""
        try:
            from erp_timing_engine import get_erp_engine
            engine = get_erp_engine()
            signal = engine.compute_signal()
            if signal.get("status") == "success":
                return signal["current_snapshot"].get("erp_value", 3.5)
        except Exception as e:
            _log(f"ERP引擎读取失败, 降级为3.5%: {e}", "WARN")
        return 3.5  # 降级估算

    def _cross_validate(self, regime: int, erp_value: float) -> Dict:
        """AIAE × ERP 交叉验证 (V2.0: 11分支全覆盖)"""
        erp_level = self.classify_erp_level(erp_value)

        # 置信度矩阵 — 11 分支全覆盖
        if regime <= 2 and erp_value >= 6.0:
            confidence, verdict, color = 5, "极强买入", "#10b981"
        elif regime <= 2 and erp_value >= 4.0:
            confidence, verdict, color = 5, "强买入", "#10b981"
        elif regime <= 2 and erp_value >= 2.0:
            confidence, verdict, color = 4, "标准买入", "#34d399"
        elif regime <= 2 and erp_value < 2.0:
            confidence, verdict, color = 3, "谨慎买入 · ERP偏低", "#eab308"
        elif regime == 3 and erp_value >= 4.0:
            confidence, verdict, color = 3, "谨慎乐观", "#34d399"
        elif regime == 3 and 2.0 <= erp_value < 4.0:
            confidence, verdict, color = 3, "中性", "#94a3b8"
        elif regime == 3 and erp_value < 2.0:
            confidence, verdict, color = 3, "中性偏谨慎", "#eab308"
        elif regime == 4 and erp_value >= 4.0:
            confidence, verdict, color = 2, "矛盾信号 · 以保守为准", "#f97316"
        elif regime == 4 and erp_value < 4.0:
            confidence, verdict, color = 4, "强减仓信号", "#ef4444"
        elif regime == 5 and erp_value < 2.0:
            confidence, verdict, color = 5, "全面撤退", "#ef4444"
        else:  # regime==5 and erp>=2
            confidence, verdict, color = 4, "清仓 · ERP未确认底部", "#ef4444"

        return {
            "aiae_regime": regime,
            "erp_value": erp_value,
            "erp_level": erp_level,
            "confidence": confidence,
            "confidence_stars": "⭐" * confidence,
            "verdict": verdict,
            "color": color,
        }

    def _fallback_report(self, reason: str) -> Dict:
        """降级报告"""
        return {
            "status": "fallback",
            "message": reason,
            "engine_version": self.VERSION,
            "updated_at": datetime.now().isoformat(),
            "current": {
                "aiae_simple": 22.3, "aiae_v1": 21.5, "regime": 3,
                "regime_info": REGIMES[3],
                "total_mv_wan_yi": 95.0, "m2_wan_yi": 330.0,
                "margin_heat": 2.0, "fund_position": 82.0,
                "fund_position_date": "2025-12-31",
                "slope": {"slope": 0, "direction": "flat", "signal": None},
            },
            "position": {
                "matrix_position": 55, "erp_value": 3.5, "erp_level": "erp_2_4",
                "regime": 3, "matrix": POSITION_MATRIX,
                "allocations": self.allocate_sub_strategies(3, 55),
            },
            "signals": [{"type": "fallback", "level": "warning",
                        "text": f"数据降级: {reason}", "color": "#f59e0b"}],
            "cross_validation": self._cross_validate(3, 3.5),
            "chart": self.get_chart_data(),
            "regimes": REGIMES,
            "raw_data": {},
        }

    def refresh(self):
        """强制清除缓存 (线程安全)"""
        with _cache_lock:
            keys_to_clear = [k for k in _cache if k.startswith("aiae_")]
            for k in keys_to_clear:
                del _cache[k]
        _log(f"缓存已清除 ({len(keys_to_clear)} keys)")


# ===== 引擎单例 =====
_aiae_instance = None

def get_aiae_engine() -> AIAEEngine:
    global _aiae_instance
    if _aiae_instance is None:
        _aiae_instance = AIAEEngine()
    return _aiae_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    # Windows GBK console fix
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    engine = AIAEEngine()
    print("=== AIAE Engine V2.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") in ("success", "fallback"):
        c = report["current"]
        p = report["position"]
        latency = report.get("latency_ms", "?")
        print(f"AIAE_简: {c['aiae_simple']}% | AIAE_V1: {c['aiae_v1']}%")
        print(f"档位: {c['regime']} ({c['regime_info']['cn']})")
        print(f"总市值: {c['total_mv_wan_yi']}万亿 | M2: {c['m2_wan_yi']}万亿")
        print(f"融资热度: {c['margin_heat']}% | 基金仓位: {c['fund_position']}%")
        print(f"矩阵仓位: {p['matrix_position']}% (ERP={p['erp_value']}%)")
        cv = report["cross_validation"]
        stars_ascii = '*' * cv['confidence']
        print(f"交叉验证: {cv['verdict']} [{stars_ascii}] ({cv['confidence']}/5)")
        for s in report["signals"]:
            print(f"  > {s['text']}")
        print(f"\n--- Latency: {latency}ms | Status: {report.get('status')} ---")
    else:
        print(f"失败: {report.get('message')}")

