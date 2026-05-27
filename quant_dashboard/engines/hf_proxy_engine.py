"""
AlphaCore · AIAE 高频代理引擎 (HF Proxy Engine) V1.0
=====================================================
核心目标: 补充 M2 月频数据间隙 (每月10-15号才发布上月 M2)
         用日频代理指标估算 AIAE 短期偏移量

设计思想:
  AIAE_HF = AIAE_V1(latest) + total_hf_delta
  total_hf_delta = w1×turnover_zscore + w2×etf_flow_rank + w3×margin_delta_5d

  三个子指标独立计算, 任一失败不影响其他, 全部失败时 delta=0 (降级)

子指标说明:
  1. turnover_zscore: 全市场换手率 Z-Score vs 20日均值
     - 数据源: Tushare daily_basic → turnover_rate_f
     - 含义: 换手率偏高 → 市场活跃度上升 → AIAE 上修
  2. etf_flow_rank: 三大宽基 ETF 资金流净额 60日分位
     - 标的: 510300(沪深300), 510500(中证500), 159915(创业板)
     - 含义: 资金净流入分位高 → 配置意愿强 → AIAE 上修
  3. margin_delta_5d: 融资余额5日变化率
     - 数据源: data_lake/aiae_margin.json (复用 AIAE 引擎已有数据)
     - 含义: 融资余额放大 → 杠杆偏好回升 → AIAE 上修

置信度 (Confidence):
  M2 发布后 <5天  → LOW  (HF 代理价值最小, AIAE_V1 已足够)
  M2 发布后 5-10天 → MEDIUM
  M2 发布后 10-25天 → HIGH (HF 代理价值最大)
  M2 发布后 >25天  → MEDIUM (接近下一发布, 但数据仍旧)

V1.0 2026-05-26
"""

import pandas as pd
import numpy as np
import tushare as ts
import time
import os
import json
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# ===== 统一从 config 读取 Token =====
from config import TUSHARE_TOKEN
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ===== 常量 =====
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

HF_CACHE_FILE = os.path.join(CACHE_DIR, "hf_proxy_cache.json")
HF_CACHE_TTL = 6 * 3600  # 6小时 TTL

# 子指标权重 (初始经验值, 总和 = 1.0)
W_TURNOVER = 0.35
W_ETF_FLOW = 0.35
W_MARGIN_D = 0.30
assert abs(W_TURNOVER + W_ETF_FLOW + W_MARGIN_D - 1.0) < 1e-9, \
    f"HF权重总和 ≠ 1.0: {W_TURNOVER + W_ETF_FLOW + W_MARGIN_D}"

# 各子指标归一化后范围 [-1.0, +1.0], 加权求和后 clamp
SUB_DELTA_RANGE = (-1.0, 1.0)
TOTAL_DELTA_CLAMP = (-3.0, 3.0)   # 总偏移量上下限 (AIAE 百分点)

# 换手率 Z-Score 参数
TURNOVER_LOOKBACK = 20   # 20 个交易日均值/标准差

# ETF 资金流标的
ETF_TARGETS = [
    {"ts_code": "510300.SH", "name": "沪深300ETF"},
    {"ts_code": "510500.SH", "name": "中证500ETF"},
    {"ts_code": "159915.SZ", "name": "创业板ETF"},
]
ETF_FLOW_LOOKBACK = 60   # 60日分位排名

# 融资余额 delta 参数
MARGIN_DELTA_DAYS = 5    # 5日变化率
MARGIN_DELTA_NORM_CAP = 5.0  # ±5% 视为极值, 映射到 ±1.0

# M2 发布周期 (每月10-15号发布上月 M2)
M2_PUBLISH_DAY_RANGE = (10, 15)


# ===== 日志 =====
def _log(msg: str, level: str = "INFO"):
    """结构化日志"""
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [HF_PROXY] {msg}")


# ===== 原子写入 =====
def _atomic_write_json(data, filepath):
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e


# ===== 线程安全缓存 =====
_hf_cache = {}
_hf_cache_lock = threading.Lock()


def _cached_hf(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存 (简化版, 无 SWR)"""
    now = time.time()
    with _hf_cache_lock:
        if key in _hf_cache:
            ts_cached, data = _hf_cache[key]
            if now - ts_cached < ttl_seconds:
                return data

    # 缓存未命中或过期 → 重新获取
    data = fetcher()
    with _hf_cache_lock:
        _hf_cache[key] = (time.time(), data)
    return data


class HFProxyEngine:
    """AIAE 高频代理引擎 — 日频指标补充 M2 月频间隙"""

    VERSION = "1.0"

    def __init__(self):
        _log(f"HFProxyEngine V{self.VERSION} 初始化")

    # ================================================================
    #  子指标 1: 全市场换手率 Z-Score
    # ================================================================

    def compute_turnover_zscore(self) -> dict:
        """
        全市场加权平均换手率的 Z-Score (vs 20日均值)

        数据源: Tushare daily_basic → turnover_rate_f
        逻辑:
          1. 获取最近 TURNOVER_LOOKBACK+1 个交易日的全市场换手率均值
          2. 最新一天 vs 前 N 天的均值/标准差 → Z-Score
          3. Z-Score 归一化到 [-1, +1] (用 tanh 压缩)
        """
        try:
            # 获取最近 N+5 天数据 (覆盖非交易日)
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=TURNOVER_LOOKBACK * 2 + 10)).strftime("%Y%m%d")

            daily_avgs = []
            # 逐日获取会触发 API 限频, 改用 start_date/end_date 批量
            # daily_basic 按 trade_date 批量获取代价太大 (全市场5000+股)
            # 改用更高效的方式: 获取指数日线换手率作为市场代理
            # 方案B: 直接获取最近若干天, 每天取一次市场均值
            for offset in range(TURNOVER_LOOKBACK + 5):
                try_date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    df = pro.daily_basic(
                        trade_date=try_date,
                        fields="ts_code,turnover_rate_f"
                    )
                    if df is not None and not df.empty:
                        # 全市场中位数换手率 (中位数比均值更抗极端股干扰)
                        median_tr = df['turnover_rate_f'].dropna().median()
                        daily_avgs.append({
                            "date": try_date,
                            "median_turnover": float(median_tr)
                        })
                        if len(daily_avgs) >= TURNOVER_LOOKBACK + 1:
                            break
                except Exception as e:
                    _log(f"daily_basic {try_date} 获取失败: {e}", "WARN")
                time.sleep(0.3)  # Tushare 限频

            if len(daily_avgs) < 5:
                _log(f"换手率数据不足: 仅获取 {len(daily_avgs)} 天", "WARN")
                return {"status": "failed", "reason": "data_insufficient", "value": None}

            # 最新一天 vs 前 N 天
            latest = daily_avgs[0]["median_turnover"]
            history = [d["median_turnover"] for d in daily_avgs[1:]]
            mean_h = np.mean(history)
            std_h = np.std(history)

            if std_h < 1e-6:
                zscore = 0.0
            else:
                zscore = (latest - mean_h) / std_h

            # tanh 归一化到 [-1, +1]
            normalized = float(np.tanh(zscore / 2.0))  # /2.0 使 Z=2 → ~0.76
            normalized = max(SUB_DELTA_RANGE[0], min(SUB_DELTA_RANGE[1], normalized))

            result = {
                "status": "success",
                "latest_turnover": round(latest, 4),
                "mean_20d": round(mean_h, 4),
                "std_20d": round(std_h, 4),
                "zscore": round(zscore, 3),
                "normalized": round(normalized, 4),
                "data_points": len(daily_avgs),
                "latest_date": daily_avgs[0]["date"],
            }
            _log(f"换手率 Z-Score: {zscore:.3f} → normalized={normalized:.4f} "
                 f"(latest={latest:.4f}, mean={mean_h:.4f})")
            return result

        except Exception as e:
            _log(f"compute_turnover_zscore 异常: {e}", "ERROR")
            return {"status": "failed", "reason": str(e), "value": None}

    # ================================================================
    #  子指标 2: ETF 资金流分位排名
    # ================================================================

    def compute_etf_flow_signal(self) -> dict:
        """
        三大宽基 ETF 资金流净额的 60 日分位排名

        逻辑:
          1. 获取每只 ETF 最近 60+5 天日线 (amount + vol)
          2. 用 amount(成交额) 配合 close 方向估算资金流
             简化公式: flow_proxy = amount × sign(close - pre_close)
          3. 三只 ETF 汇总后取 60 日分位排名
          4. 分位 [0, 1] 映射到 [-1, +1] (线性: rank*2-1)
        """
        try:
            lookback_days = ETF_FLOW_LOOKBACK + 10  # 冗余覆盖非交易日
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")

            all_flows = []  # 每个交易日的合计 flow_proxy

            etf_dfs = {}
            for etf in ETF_TARGETS:
                try:
                    df = pro.fund_daily(
                        ts_code=etf["ts_code"],
                        start_date=start_date,
                        end_date=end_date,
                        fields="trade_date,close,pre_close,amount"
                    )
                    if df is not None and not df.empty:
                        df = df.sort_values("trade_date").reset_index(drop=True)
                        # flow_proxy = amount × sign(涨跌)
                        df["direction"] = np.sign(df["close"] - df["pre_close"])
                        df["flow_proxy"] = df["amount"] * df["direction"]
                        etf_dfs[etf["ts_code"]] = df[["trade_date", "flow_proxy"]].copy()
                    time.sleep(0.3)
                except Exception as e:
                    _log(f"ETF {etf['ts_code']} 数据获取失败: {e}", "WARN")

            if not etf_dfs:
                _log("ETF 资金流数据全部获取失败", "WARN")
                return {"status": "failed", "reason": "no_etf_data", "value": None}

            # 按日期合并, 求每日合计 flow_proxy
            merged = None
            for code, df in etf_dfs.items():
                df = df.rename(columns={"flow_proxy": f"flow_{code}"})
                if merged is None:
                    merged = df
                else:
                    merged = pd.merge(merged, df, on="trade_date", how="outer")

            merged = merged.sort_values("trade_date").reset_index(drop=True)
            flow_cols = [c for c in merged.columns if c.startswith("flow_")]
            merged["total_flow"] = merged[flow_cols].sum(axis=1)

            # 取最近 ETF_FLOW_LOOKBACK 个交易日
            if len(merged) < 10:
                return {"status": "failed", "reason": "data_insufficient", "value": None}

            recent = merged.tail(ETF_FLOW_LOOKBACK + 1).copy()
            latest_flow = recent.iloc[-1]["total_flow"]

            # 分位排名 (percentile rank)
            history_flows = recent["total_flow"].values
            rank = float(np.sum(history_flows <= latest_flow) / len(history_flows))

            # 线性映射 [0, 1] → [-1, +1]
            normalized = rank * 2.0 - 1.0
            normalized = max(SUB_DELTA_RANGE[0], min(SUB_DELTA_RANGE[1], normalized))

            result = {
                "status": "success",
                "latest_flow": round(float(latest_flow), 2),
                "rank_60d": round(rank, 4),
                "normalized": round(normalized, 4),
                "etf_count": len(etf_dfs),
                "data_points": len(recent),
                "latest_date": recent.iloc[-1]["trade_date"],
            }
            _log(f"ETF资金流: rank={rank:.4f} → normalized={normalized:.4f} "
                 f"({len(etf_dfs)} ETFs, {len(recent)}天)")
            return result

        except Exception as e:
            _log(f"compute_etf_flow_signal 异常: {e}", "ERROR")
            return {"status": "failed", "reason": str(e), "value": None}

    # ================================================================
    #  子指标 3: 融资余额 5 日变化率
    # ================================================================

    def compute_margin_delta(self) -> dict:
        """
        融资余额5日变化率 (复用 AIAE 引擎的 margin 数据)

        逻辑:
          1. 从 Tushare margin 接口获取最近 MARGIN_DELTA_DAYS+5 天数据
          2. 如果 API 失败, 降级到 data_lake/aiae_margin.json
          3. 计算 (latest - 5d_ago) / 5d_ago * 100 (百分比)
          4. 映射到 [-1, +1]: delta_pct / MARGIN_DELTA_NORM_CAP, clamp
        """
        try:
            margin_history = []

            # 优先从 Tushare 获取最近多天数据
            for offset in range(MARGIN_DELTA_DAYS + 10):
                try_date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    df = pro.margin(trade_date=try_date)
                    if df is not None and not df.empty:
                        total_rzye = df['rzye'].sum() if 'rzye' in df.columns else 0
                        margin_history.append({
                            "date": try_date,
                            "rzye": total_rzye / 100000000  # → 亿元
                        })
                        if len(margin_history) >= MARGIN_DELTA_DAYS + 1:
                            break
                except Exception as e:
                    _log(f"margin {try_date}: {e}", "WARN")
                time.sleep(0.3)

            if len(margin_history) < 2:
                # 降级: 仅用缓存单点, 无法计算 delta
                _log("融资余额历史数据不足, 无法计算 5 日变化率", "WARN")
                return {"status": "failed", "reason": "data_insufficient", "value": None}

            # 排序: 最新在前
            margin_history.sort(key=lambda x: x["date"], reverse=True)
            latest_rzye = margin_history[0]["rzye"]
            oldest_rzye = margin_history[-1]["rzye"]

            if oldest_rzye <= 0:
                return {"status": "failed", "reason": "zero_base", "value": None}

            delta_pct = (latest_rzye - oldest_rzye) / oldest_rzye * 100

            # 归一化: delta_pct / NORM_CAP, clamp to [-1, +1]
            normalized = delta_pct / MARGIN_DELTA_NORM_CAP
            normalized = max(SUB_DELTA_RANGE[0], min(SUB_DELTA_RANGE[1], normalized))

            result = {
                "status": "success",
                "latest_rzye": round(latest_rzye, 2),
                "base_rzye": round(oldest_rzye, 2),
                "delta_pct": round(delta_pct, 3),
                "normalized": round(normalized, 4),
                "days_span": len(margin_history),
                "latest_date": margin_history[0]["date"],
                "base_date": margin_history[-1]["date"],
            }
            _log(f"融资Delta: {delta_pct:+.3f}% → normalized={normalized:.4f} "
                 f"({latest_rzye:.0f}亿 vs {oldest_rzye:.0f}亿)")
            return result

        except Exception as e:
            _log(f"compute_margin_delta 异常: {e}", "ERROR")
            return {"status": "failed", "reason": str(e), "value": None}

    # ================================================================
    #  综合: 三指标加权 → total_hf_delta
    # ================================================================

    def compute_hf_delta(self) -> dict:
        """
        合并三个子指标为 total_hf_delta (AIAE 百分点偏移)

        权重: turnover(0.35) + etf_flow(0.35) + margin_delta(0.30)
        每个子指标 normalized ∈ [-1, +1]
        total = Σ(weight × normalized × scale_factor)
        其中 scale_factor = TOTAL_DELTA_CLAMP[1] = 3.0, 使满权重输出 = ±3.0

        失败子指标: 被跳过, 权重重新归一化到剩余指标
        """
        def _fetch():
            t0 = time.time()

            turnover = self.compute_turnover_zscore()
            etf_flow = self.compute_etf_flow_signal()
            margin_d = self.compute_margin_delta()

            # 收集成功的子指标
            components = []
            if turnover.get("status") == "success":
                components.append(("turnover", W_TURNOVER, turnover["normalized"]))
            if etf_flow.get("status") == "success":
                components.append(("etf_flow", W_ETF_FLOW, etf_flow["normalized"]))
            if margin_d.get("status") == "success":
                components.append(("margin_delta", W_MARGIN_D, margin_d["normalized"]))

            # 全部失败 → 降级
            if not components:
                _log("三个子指标全部失败, hf_delta = 0 (降级)", "WARN")
                return {
                    "status": "degraded",
                    "hf_delta": 0.0,
                    "components_available": 0,
                    "turnover": turnover,
                    "etf_flow": etf_flow,
                    "margin_delta": margin_d,
                    "computed_at": datetime.now().isoformat(),
                    "latency_ms": round((time.time() - t0) * 1000),
                }

            # 权重重新归一化 (仅在有子指标失败时)
            total_weight = sum(w for _, w, _ in components)
            scale_factor = TOTAL_DELTA_CLAMP[1]  # 3.0

            # 加权求和
            weighted_sum = sum(
                (w / total_weight) * normalized * scale_factor
                for _, w, normalized in components
            )

            # Clamp
            hf_delta = max(TOTAL_DELTA_CLAMP[0], min(TOTAL_DELTA_CLAMP[1], weighted_sum))

            # 各子指标对 delta 的贡献明细
            breakdown = {}
            for name, w, norm in components:
                contrib = (w / total_weight) * norm * scale_factor
                breakdown[name] = {
                    "weight": round(w, 2),
                    "weight_adjusted": round(w / total_weight, 4),
                    "normalized": round(norm, 4),
                    "contribution": round(contrib, 4),
                }

            result = {
                "status": "success",
                "hf_delta": round(hf_delta, 3),
                "components_available": len(components),
                "components_total": 3,
                "breakdown": breakdown,
                "turnover": turnover,
                "etf_flow": etf_flow,
                "margin_delta": margin_d,
                "computed_at": datetime.now().isoformat(),
                "latency_ms": round((time.time() - t0) * 1000),
            }

            # 持久化缓存
            try:
                _atomic_write_json(result, HF_CACHE_FILE)
            except Exception as e:
                _log(f"HF缓存写入失败: {e}", "WARN")

            _log(f"HF Delta: {hf_delta:+.3f} AIAE pt "
                 f"({len(components)}/3 指标可用, {result['latency_ms']}ms)")
            return result

        return _cached_hf("hf_delta", HF_CACHE_TTL, _fetch)

    # ================================================================
    #  M2 新鲜度评估
    # ================================================================

    def _days_since_m2(self) -> int:
        """
        估算距上次 M2 发布的天数

        M2 发布规律: 每月 10-15 号发布上月 M2
        当前日: 若过了本月15号 → 距离本月发布; 否则 → 距离上月发布
        """
        now = datetime.now()
        day = now.day

        if day >= M2_PUBLISH_DAY_RANGE[1]:
            # 本月 M2 已发布, 距发布日 = day - 12 (取中位估算)
            publish_est = datetime(now.year, now.month, 12)
        else:
            # 本月 M2 未发布, 用上月发布日
            last_month = now.replace(day=1) - timedelta(days=1)
            publish_est = datetime(last_month.year, last_month.month, 12)

        days_since = (now - publish_est).days
        return max(0, days_since)

    def _compute_confidence(self, days_since_m2: int) -> dict:
        """
        置信度评估: M2 越旧 → HF 代理越有价值

        Returns:
            {"level": "LOW|MEDIUM|HIGH", "score": 0-100, "reason": str}
        """
        if days_since_m2 < 5:
            return {
                "level": "LOW",
                "score": 30,
                "reason": f"M2 刚发布 ({days_since_m2}天前), AIAE_V1 已足够准确"
            }
        elif days_since_m2 < 10:
            return {
                "level": "MEDIUM",
                "score": 60,
                "reason": f"M2 发布 {days_since_m2} 天, HF 代理开始有参考价值"
            }
        elif days_since_m2 <= 25:
            return {
                "level": "HIGH",
                "score": 85,
                "reason": f"M2 已过 {days_since_m2} 天, HF 代理指标价值最高"
            }
        else:
            return {
                "level": "MEDIUM",
                "score": 55,
                "reason": f"M2 已过 {days_since_m2} 天, 接近下一发布窗口"
            }

    # ================================================================
    #  主入口: HF 估算值
    # ================================================================

    def get_aiae_hf_estimate(self, base_aiae_v1: float) -> dict:
        """
        主入口: 在 AIAE_V1 基础上叠加高频偏移量

        Args:
            base_aiae_v1: 最新 AIAE_V1 值 (从 AIAE 引擎获取)

        Returns:
            {
                "status": "success|degraded",
                "aiae_v1_base": float,
                "hf_delta": float,
                "aiae_hf": float,
                "confidence": {...},
                "delta_detail": {...},
                ...
            }
        """
        t0 = time.time()
        _log(f"计算 AIAE_HF, base_v1={base_aiae_v1:.2f}%")

        # 1. M2 新鲜度
        days_m2 = self._days_since_m2()
        confidence = self._compute_confidence(days_m2)

        # 2. 计算 HF Delta
        delta_result = self.compute_hf_delta()
        hf_delta = delta_result.get("hf_delta", 0.0)

        # 3. 叠加
        aiae_hf = round(base_aiae_v1 + hf_delta, 2)

        result = {
            "status": delta_result.get("status", "degraded"),
            "engine_version": self.VERSION,
            "aiae_v1_base": base_aiae_v1,
            "hf_delta": hf_delta,
            "aiae_hf": aiae_hf,
            "delta_direction": "上修" if hf_delta > 0.1 else ("下修" if hf_delta < -0.1 else "持平"),
            "confidence": confidence,
            "days_since_m2": days_m2,
            "components_available": delta_result.get("components_available", 0),
            "breakdown": delta_result.get("breakdown", {}),
            "delta_detail": delta_result,
            "computed_at": datetime.now().isoformat(),
            "latency_ms": round((time.time() - t0) * 1000),
        }

        _log(f"AIAE_HF = {base_aiae_v1:.2f} + ({hf_delta:+.3f}) = {aiae_hf:.2f}% "
             f"| 置信度={confidence['level']} | M2+{days_m2}天 | {result['latency_ms']}ms")

        return result

    # ================================================================
    #  缓存管理
    # ================================================================

    def refresh(self):
        """强制清除缓存"""
        with _hf_cache_lock:
            _hf_cache.clear()
        _log("HF Proxy 缓存已清除")

    def get_cached_result(self) -> Optional[dict]:
        """读取磁盘缓存 (供其他引擎降级使用)"""
        if os.path.exists(HF_CACHE_FILE):
            try:
                with open(HF_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                # 检查 TTL
                computed_at = cached.get("computed_at")
                if computed_at:
                    age = (datetime.now() - datetime.fromisoformat(computed_at)).total_seconds()
                    if age < HF_CACHE_TTL:
                        return cached
                    else:
                        _log(f"磁盘缓存已过期 ({age/3600:.1f}h)", "WARN")
            except Exception as e:
                _log(f"磁盘缓存读取失败: {e}", "WARN")
        return None


# ===== 引擎单例 =====
_hf_instance = None
_hf_instance_lock = threading.Lock()


def get_hf_engine() -> HFProxyEngine:
    """线程安全单例"""
    global _hf_instance
    if _hf_instance is None:
        with _hf_instance_lock:
            if _hf_instance is None:
                _hf_instance = HFProxyEngine()
    return _hf_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    # Windows GBK console fix
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  AIAE HF Proxy Engine V1.0 · Self-Test")
    print("=" * 60)

    engine = HFProxyEngine()

    # --- 子指标独立测试 ---
    print("\n[1/4] 换手率 Z-Score ...")
    turnover = engine.compute_turnover_zscore()
    if turnover["status"] == "success":
        print(f"  ✓ zscore={turnover['zscore']:.3f}  normalized={turnover['normalized']:.4f}")
        print(f"    latest={turnover['latest_turnover']:.4f}  mean_20d={turnover['mean_20d']:.4f}")
    else:
        print(f"  ✗ 失败: {turnover.get('reason', '?')}")

    print("\n[2/4] ETF 资金流分位 ...")
    etf_flow = engine.compute_etf_flow_signal()
    if etf_flow["status"] == "success":
        print(f"  ✓ rank={etf_flow['rank_60d']:.4f}  normalized={etf_flow['normalized']:.4f}")
        print(f"    ETFs={etf_flow['etf_count']}  data_points={etf_flow['data_points']}")
    else:
        print(f"  ✗ 失败: {etf_flow.get('reason', '?')}")

    print("\n[3/4] 融资余额 5日 Delta ...")
    margin_d = engine.compute_margin_delta()
    if margin_d["status"] == "success":
        print(f"  ✓ delta={margin_d['delta_pct']:+.3f}%  normalized={margin_d['normalized']:.4f}")
        print(f"    latest={margin_d['latest_rzye']:.0f}亿  base={margin_d['base_rzye']:.0f}亿")
    else:
        print(f"  ✗ 失败: {margin_d.get('reason', '?')}")

    # --- 综合 HF 估算 ---
    print("\n[4/4] 综合 HF 估算 (base_aiae_v1=22.3) ...")
    result = engine.get_aiae_hf_estimate(base_aiae_v1=22.3)
    print(f"\n  AIAE_V1 (base): {result['aiae_v1_base']:.2f}%")
    print(f"  HF Delta:       {result['hf_delta']:+.3f} AIAE pt ({result['delta_direction']})")
    print(f"  AIAE_HF:        {result['aiae_hf']:.2f}%")
    print(f"  置信度:          {result['confidence']['level']} (score={result['confidence']['score']})")
    print(f"  M2距今:          {result['days_since_m2']} 天")
    print(f"  可用指标:        {result['components_available']}/3")
    print(f"  状态:            {result['status']}")
    print(f"  耗时:            {result['latency_ms']}ms")

    if result.get("breakdown"):
        print("\n  --- 贡献分解 ---")
        for name, info in result["breakdown"].items():
            print(f"    {name}: normalized={info['normalized']:+.4f} "
                  f"× weight={info['weight_adjusted']:.2f} "
                  f"→ contribution={info['contribution']:+.4f}")

    print(f"\n{'=' * 60}")
    print(f"  Self-Test Complete | Status: {result['status']}")
    print(f"{'=' * 60}")
