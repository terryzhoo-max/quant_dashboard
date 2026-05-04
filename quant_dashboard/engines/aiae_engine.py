"""
AlphaCore · AIAE 全市场权益配置择时引擎 V3.0
================================================
核心思想: AIAE = 全市场投资者把多少比例的钱放在了股票里
  - 比例极高 → 市场过热，减仓
  - 比例极低 → 市场冰点，加仓

计算公式:
  AIAE_简 = A股总市值 / (A股总市值 + M2)
  AIAE_V1 = 0.55×AIAE_简 + 0.20×基金仓位(Sigmoid) + 0.25×融资热度(Sigmoid)

五档状态:
  Ⅰ级 极度恐慌 (<12.5%) → 总仓位 90-95%
  Ⅱ级 低配置区 (12.5-17%) → 总仓位 70-85%
  Ⅲ级 中性均衡 (17-23%) → 总仓位 50-65%
  Ⅳ级 偏热区域 (23-30%) → 总仓位 25-40%
  Ⅴ级 极度过热 (>30%)   → 总仓位 0-15%

数据源: Tushare Pro
  - daily_basic → total_mv / circ_mv (日频)
  - cn_m → M2 (月频)
  - margin → 融资余额/买入额 (日频)

V3.0 Changelog:
  - Sigmoid 归一化替代线性映射 (基金仓位 / 融资热度)
  - 三维权重重标定 [0.55, 0.20, 0.25]
  - 五档分界线重划 [12.5, 17, 23, 30]
  - 仓位矩阵 ±1.5pt 缓冲带平滑插值
  - 参数中心化 aiae_params.py (Single Source of Truth)

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
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

# ===== Token: 统一从 config 读取 =====
from config import TUSHARE_TOKEN
import aiae_params as AP  # V3.0: 参数中心 (Single Source of Truth)
from services import db as ac_db
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# ===== 线程安全 TTL 缓存 =====
_cache = {}
_cache_lock = threading.Lock()
_bg_executor = ThreadPoolExecutor(max_workers=3)

def _log(msg: str, level: str = "INFO"):
    """结构化日志"""
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [AIAE] {msg}")

def atomic_write_json(data, filepath):
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e

def _refresh_cache(key: str, fetcher):
    try:
        data = fetcher()
        with _cache_lock:
            _cache[key] = (time.time(), data)
        return data
    except Exception as e:
        _log(f"后台缓存刷新失败 ({key}): {e}", "WARN")
        with _cache_lock:
            if key in _cache:
                return _cache[key][1]
        raise

def _cached(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存 (支持 SWR - Stale-While-Revalidate)"""
    now = time.time()
    with _cache_lock:
        if key in _cache:
            ts_cached, data = _cache[key]
            if now - ts_cached < ttl_seconds:
                return data
            else:
                try:
                    _bg_executor.submit(_refresh_cache, key, fetcher)
                except RuntimeError:
                    pass  # shutdown 阶段, 跳过后台刷新
                return data

    return _refresh_cache(key, fetcher)


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

# ===== 季报发布日历 (证监会规定: 季末后1个月内披露, +7天缓冲) =====
FUND_REPORT_SCHEDULE = {
    "Q1": {"cutoff_md": "03-31", "deadline_md": "05-07", "label": "一季报"},
    "Q2": {"cutoff_md": "06-30", "deadline_md": "08-07", "label": "中报/二季报"},
    "Q3": {"cutoff_md": "09-30", "deadline_md": "11-07", "label": "三季报"},
    "Q4": {"cutoff_md": "12-31", "deadline_md": "02-07", "label": "年报/四季报"},
}

# ===== 基金仓位手动更新查阅指引 =====
FUND_UPDATE_GUIDE = {
    "title": "偏股型基金仓位数据查阅方案",
    "steps": [
        "① 天天基金网 → 基金数据 → 基金仓位测算 (fund.eastmoney.com/data/fundposition.html)",
        "② 搜索 '偏股型基金仓位' → 查看最新季度的中位数仓位",
        "③ 或使用 Wind/Choice 终端 → 基金仓位指标 → 偏股混合型基金股票仓位中位数",
        "④ 记录数值 (通常在 60-95% 之间) 和对应季报截止日 (如 2026-03-31)",
        "⑤ 通过下方表单提交，或调用 API: POST /api/v1/aiae/update_fund_position {value: 80.5, date: '2026-03-31'}",
    ],
    "sources": [
        {"name": "天天基金-仓位测算", "url": "https://fund.eastmoney.com/data/fundposition.html"},
        {"name": "好买基金-仓位指数", "url": "https://www.howbuy.com/fund/cangwei/"},
    ],
    "frequency": "每季度更新一次 (Q1→4月底, Q2→7月底, Q3→10月底, Q4→次年1月底)",
}

# ===== 五档状态定义 (V3.0: 分界线从 aiae_params.py 读取) =====
_T = AP.REGIME_THRESHOLDS  # [13, 17, 23, 30]
REGIMES = {
    1: {"name": "Ⅰ级 · EXTREME FEAR", "cn": "极度恐慌", "range": f"<{_T[0]}%",
        "color": "#10b981", "emoji": "🟢", "position": "90-95%", "pos_min": 90, "pos_max": 95,
        "action": "满配进攻", "desc": "越跌越买，分3批建仓"},
    2: {"name": "Ⅱ级 · LOW ALLOCATION", "cn": "低配置区", "range": f"{_T[0]}-{_T[1]}%",
        "color": "#3b82f6", "emoji": "🔵", "position": "70-85%", "pos_min": 70, "pos_max": 85,
        "action": "标准建仓", "desc": "耐心持有，不因波动减仓"},
    3: {"name": "Ⅲ级 · NEUTRAL", "cn": "中性均衡", "range": f"{_T[1]}-{_T[2]}%",
        "color": "#eab308", "emoji": "🟡", "position": "50-65%", "pos_min": 50, "pos_max": 65,
        "action": "均衡持有", "desc": "有纪律地持有，到了就卖"},
    4: {"name": "Ⅳ级 · GETTING HOT", "cn": "偏热区域", "range": f"{_T[2]}-{_T[3]}%",
        "color": "#f97316", "emoji": "🟠", "position": "25-40%", "pos_min": 25, "pos_max": 40,
        "action": "系统减仓", "desc": "每周减5%总仓位"},
    5: {"name": "Ⅴ级 · EUPHORIA", "cn": "极度过热", "range": f">{_T[3]}%",
        "color": "#ef4444", "emoji": "🔴", "position": "0-15%", "pos_min": 0, "pos_max": 15,
        "action": "清仓防守", "desc": "3天内完成清仓"},
}

# ===== AIAE × ERP 仓位矩阵 (V3.0: 从参数中心读取) =====
POSITION_MATRIX = AP.POSITION_MATRIX

# ===== 子策略配额矩阵 (V3.0: 从参数中心读取) =====
SUB_STRATEGY_ALLOC = AP.SUB_STRATEGY_ALLOC

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

# ===== AIAE 五档 × ETF 仓位矩阵 (同档内各 ETF 相对权重占比) =====
# 注意: 各档数值为"相对权重"而非绝对仓位百分比。
# 实际仓位 = matrix_position × (etf_weight / sum_of_row_weights)
# 例: Ⅰ级总和=110 → 沪深300ETF 实际占比 = 25/110 = 22.7% (× 仓位上限)
AIAE_ETF_MATRIX = {
    #                300   50  500  创业 1000 红利 低波 深红  (和)
    1: {"510300.SH": 25, "510050.SH": 20, "510500.SH": 20, "159915.SZ": 15, "512100.SH": 10,
        "510880.SH": 10, "515180.SH":  5, "159905.SZ":  5},  # 110
    2: {"510300.SH": 25, "510050.SH": 20, "510500.SH": 15, "159915.SZ":  5, "512100.SH":  0,
        "510880.SH": 10, "515180.SH":  8, "159905.SZ":  7},  # 90
    3: {"510300.SH": 15, "510050.SH": 10, "510500.SH":  5, "159915.SZ":  0, "512100.SH":  0,
        "510880.SH": 15, "515180.SH": 10, "159905.SZ": 10},  # 65
    4: {"510300.SH":  5, "510050.SH":  5, "510500.SH":  0, "159915.SZ":  0, "512100.SH":  0,
        "510880.SH": 15, "515180.SH": 10, "159905.SZ":  5},  # 40
    5: {"510300.SH":  0, "510050.SH":  0, "510500.SH":  0, "159915.SZ":  0, "512100.SH":  0,
        "510880.SH":  8, "515180.SH":  5, "159905.SZ":  2},  # 15
}

# ===== run-all 联合权重矩阵 V2.0 (五策略, AIAE×ERP 双维驱动) =====
# 5×3 矩阵: AIAE regime(1-5) × ERP tier(bull/neutral/bear)
# ERP档: bull(≥55) / neutral(40-55) / bear(<40)
# 每行权重总和 = 1.0
JOINT_WEIGHTS = {
    # AIAE Ⅰ 恐慌
    1: {
        "bull":    {"mr": 0.35, "div": 0.10, "mom": 0.25, "erp": 0.10, "aiae_etf": 0.20},  # 极端贪婪
        "neutral": {"mr": 0.25, "div": 0.20, "mom": 0.20, "erp": 0.10, "aiae_etf": 0.25},  # 温和进攻
        "bear":    {"mr": 0.10, "div": 0.30, "mom": 0.10, "erp": 0.10, "aiae_etf": 0.40},  # 矛盾态防御优先
    },
    # AIAE Ⅱ 低估
    2: {
        "bull":    {"mr": 0.30, "div": 0.15, "mom": 0.20, "erp": 0.10, "aiae_etf": 0.25},
        "neutral": {"mr": 0.20, "div": 0.25, "mom": 0.15, "erp": 0.10, "aiae_etf": 0.30},
        "bear":    {"mr": 0.10, "div": 0.30, "mom": 0.05, "erp": 0.10, "aiae_etf": 0.45},
    },
    # AIAE Ⅲ 中性
    3: {
        "bull":    {"mr": 0.25, "div": 0.20, "mom": 0.20, "erp": 0.10, "aiae_etf": 0.25},
        "neutral": {"mr": 0.15, "div": 0.30, "mom": 0.10, "erp": 0.15, "aiae_etf": 0.30},
        "bear":    {"mr": 0.05, "div": 0.40, "mom": 0.05, "erp": 0.10, "aiae_etf": 0.40},
    },
    # AIAE Ⅳ 偏热
    4: {
        "bull":    {"mr": 0.15, "div": 0.30, "mom": 0.10, "erp": 0.10, "aiae_etf": 0.35},
        "neutral": {"mr": 0.05, "div": 0.40, "mom": 0.05, "erp": 0.15, "aiae_etf": 0.35},
        "bear":    {"mr": 0.00, "div": 0.45, "mom": 0.00, "erp": 0.10, "aiae_etf": 0.45},
    },
    # AIAE Ⅴ 过热 — 纯防御，MR/MOM归零
    5: {
        "bull":    {"mr": 0.00, "div": 0.40, "mom": 0.00, "erp": 0.10, "aiae_etf": 0.50},
        "neutral": {"mr": 0.00, "div": 0.45, "mom": 0.00, "erp": 0.10, "aiae_etf": 0.45},
        "bear":    {"mr": 0.00, "div": 0.50, "mom": 0.00, "erp": 0.05, "aiae_etf": 0.45},
    },
}

# 向后兼容: 保留旧名称引用 (降级用)
AIAE_RUN_ALL_WEIGHTS = {r: JOINT_WEIGHTS[r]["neutral"] for r in JOINT_WEIGHTS}


# ===== 数据合理性断言阈值 (V3.0: 从参数中心读取) =====
MV_BOUNDS = {"min": AP.MV_BOUNDS_MIN, "max": AP.MV_BOUNDS_MAX}
M2_BOUNDS = {"min": AP.M2_BOUNDS_MIN, "max": AP.M2_BOUNDS_MAX}


class AIAEEngine:
    """AIAE 全市场权益配置择时引擎 V3.0"""

    VERSION = AP.VERSION

    def __init__(self):
        # C1: 基金仓位从持久化文件加载，降级为硬编码默认值
        fp_data = self._load_fund_position()
        self._fund_position = fp_data["value"]
        self._fund_position_date = fp_data["date"]

        # V2.1: 引擎初始化时预填月度历史 (冷启动修复)
        # 用最新历史快照估算值做种子, 避免首次 generate_report 前斜率为 flat
        try:
            seed_aiae = HISTORICAL_SNAPSHOTS[-1]["aiae"]  # 当前估算 22.3%
            seed_regime = self.classify_regime(seed_aiae)
            self._seed_monthly_history_if_needed(seed_aiae, seed_regime)
        except Exception as e:
            _log(f"__init__ 月度历史预填跳过: {e}", "WARN")

    @staticmethod
    def _load_fund_position() -> Dict:
        """从 data_lake/aiae_fund_position.json 加载基金仓位
        V2.1: 首次启动自动创建种子文件，避免永久使用硬编码降级值
        """
        fp_file = os.path.join(CACHE_DIR, "aiae_fund_position.json")
        if os.path.exists(fp_file):
            try:
                with open(fp_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _log(f"基金仓位已从文件加载: {data['value']}% ({data['date']})")
                return data
            except Exception as e:
                _log(f"基金仓位文件读取失败: {e}", "WARN")

        # 首次启动: 自动创建种子文件 (2025Q4 估算值)
        seed_data = {
            "value": 82.0,
            "date": "2025-12-31",
            "source": "initial_seed",
            "updated_at": datetime.now().isoformat(),
            "note": "首次启动自动创建，请通过 API 或前端表单更新为最新季报数据",
            "history": [
                {"quarter": "2025Q4", "value": 82.0, "date": "2025-12-31", "source": "seed"}
            ]
        }
        try:
            atomic_write_json(seed_data, fp_file)
            _log("基金仓位种子文件已创建 (82.0% 2025-12-31)，请尽快更新")
        except Exception as e:
            _log(f"种子文件创建失败: {e}", "WARN")
        return seed_data

    def update_fund_position(self, value: float, date: str) -> Dict:
        """C1: 手动更新基金仓位 + 持久化存储
        
        Args:
            value: 偏股型基金仓位 (60-100%)
            date: 对应的季报截止日 (如 "2026-03-31")
        Returns:
            更新结果
        """
        if not (50 <= value <= 100):
            return {"success": False, "message": f"基金仓位 {value}% 不在合理范围 [50, 100]"}
        
        old_value = self._fund_position
        self._fund_position = value
        self._fund_position_date = date
        
        # 加载现有文件以保留 history
        fp_file = os.path.join(CACHE_DIR, "aiae_fund_position.json")
        existing = {}
        if os.path.exists(fp_file):
            try:
                with open(fp_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                pass
        history = existing.get("history", [])
        # 推断季度标签
        month = int(date.split("-")[1]) if "-" in date else 1
        q_label = f"{date.split('-')[0]}Q{(month - 1) // 3 + 1}"
        history.append({"quarter": q_label, "value": value, "date": date,
                        "updated_at": datetime.now().isoformat()})

        data = {
            "value": value,
            "date": date,
            "updated_at": datetime.now().isoformat(),
            "previous_value": old_value,
            "source": "manual_update",
            "history": history,
        }
        atomic_write_json(data, fp_file)
        
        _log(f"基金仓位已更新: {old_value}% → {value}% (截至 {date})")
        return {"success": True, "message": f"基金仓位已更新为 {value}% (截至 {date})", "data": data}

    def _get_fund_position_stale_warning(self) -> Optional[Dict]:
        """V2.1: 季度感知智能提醒
        
        逻辑:
        1. 判断当前日期应该已经有哪个季度的数据
        2. 对比基金仓位截止日判断是否过期
        3. 如果已过了某季报 publish_deadline 但仓位数据还是旧季度 → action_required
        """
        try:
            fp_date = datetime.strptime(self._fund_position_date, "%Y-%m-%d")
            days_stale = (datetime.now() - fp_date).days
            now = datetime.now()

            # 判断当前应更新到哪个季度
            expected_quarter, deadline_info = self._get_expected_quarter(now)
            if expected_quarter is None:
                # 无法确定 → 按传统天数判断
                if days_stale > 60:
                    return {
                        "type": "fund_position_stale",
                        "severity": "critical" if days_stale > 120 else "warning",
                        "message": f"基金仓位数据滞后 {days_stale} 天 (截至 {self._fund_position_date})，占 AIAE_V1 权重 30%，建议尽快更新",
                        "days_stale": days_stale,
                        "current_value": self._fund_position,
                        "current_date": self._fund_position_date,
                    }
                return None

            # 判断已有数据是否覆盖了 expected_quarter
            expected_cutoff = datetime.strptime(expected_quarter, "%Y-%m-%d")
            if fp_date >= expected_cutoff:
                return None  # 数据足够新

            # 数据过期 → 生成季度感知告警
            is_overdue = deadline_info.get("overdue", False)
            return {
                "type": "fund_update_due",
                "severity": "critical" if is_overdue else "warning",
                "message": f"{deadline_info['label']}已发布，请更新基金仓位数据 (当前: {self._fund_position}% 截至 {self._fund_position_date})",
                "days_stale": days_stale,
                "current_value": self._fund_position,
                "current_date": self._fund_position_date,
                "expected_quarter": expected_quarter,
                "expected_label": deadline_info["label"],
                "action_required": True,
                "update_guide": FUND_UPDATE_GUIDE,
            }
        except Exception as e:
            _log(f"基金仓位过期检查异常: {e}", "WARN")
        return None

    @staticmethod
    def _get_expected_quarter(now: datetime) -> Tuple[Optional[str], Dict]:
        """根据当前日期，判断应该已经有哪个季度的基金仓位数据
        
        Returns:
            (expected_cutoff_date_str, deadline_info) or (None, {})
        """
        year = now.year
        month = now.month
        day = now.day

        # 遍历季报日历，从最近的季度向前检查
        # Q1(3/31) → deadline 5/7, Q2(6/30) → 8/7, Q3(9/30) → 11/7, Q4(12/31) → 次年2/7
        candidates = []
        for q_key, q_info in FUND_REPORT_SCHEDULE.items():
            cutoff_md = q_info["cutoff_md"]
            deadline_md = q_info["deadline_md"]

            # Q4 的 deadline 在次年
            if q_key == "Q4":
                cutoff_date = datetime(year - 1, 12, 31)
                dl_month, dl_day = map(int, deadline_md.split("-"))
                deadline_date = datetime(year, dl_month, dl_day)
            else:
                c_month, c_day = map(int, cutoff_md.split("-"))
                cutoff_date = datetime(year, c_month, c_day)
                dl_month, dl_day = map(int, deadline_md.split("-"))
                deadline_date = datetime(year, dl_month, dl_day)

            # 只考虑 deadline 已过的季度
            if now >= deadline_date:
                candidates.append({
                    "cutoff": cutoff_date.strftime("%Y-%m-%d"),
                    "deadline": deadline_date,
                    "label": f"{cutoff_date.year}年{q_info['label']}",
                    "overdue": (now - deadline_date).days > 14,  # 超过deadline 14天 → critical
                })

        if not candidates:
            return None, {}

        # 取最近的 (deadline 最大的)
        latest = max(candidates, key=lambda c: c["deadline"])
        return latest["cutoff"], latest

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
                        atomic_write_json(result, cache_file)
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

        return _cached("aiae_total_mv", 86400, _fetch)  # V8.1: 更新为24h，由强制 refresh 主导

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
                    atomic_write_json(result, cache_file)
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

        # M4: M2 TTL 从 7天→3天, 每月10-18号(M2发布窗口)缩短至12小时
        day = datetime.now().day
        ttl = 12 * 3600 if 10 <= day <= 18 else 3 * 86400
        return _cached("aiae_m2", ttl, _fetch)

    def _fetch_margin_data(self) -> Dict:
        """获取融资融券数据 (margin)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_margin.json")
            # V8.1: 智能时差补偿。融资数据晚间22点甚至次日才发布，如果时间早于22点，直接从昨天开始探测
            start_offset = 0 if datetime.now().hour >= 22 else 1
            for offset in range(start_offset, start_offset + 6):
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
                        atomic_write_json(result, cache_file)
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

        return _cached("aiae_margin", 86400, _fetch)  # V8.1: 更新为24h TTL

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
        融合 AIAE V3.0
        = W_AIAE_SIMPLE × AIAE_简 + W_FUND_POS × 基金仓位(Sigmoid) + W_MARGIN_HEAT × 融资热度(Sigmoid)
        
        V3.0 变更:
          - 权重: [0.50, 0.30, 0.20] → [0.55, 0.20, 0.25]
          - 归一化: 线性映射 → Sigmoid 平滑映射
          - 基金仓位区间: 60-95% → Sigmoid(center=80, k=0.15)
          - 融资热度区间: 1-4% → Sigmoid(center=2.2, k=2.5)
        """
        # V3.0: Sigmoid 归一化 (从 aiae_params 读取参数)
        fund_normalized = AP.sigmoid_normalize(
            fund_pos, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)

        margin_normalized = AP.sigmoid_normalize(
            margin_heat, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)

        return round(
            AP.W_AIAE_SIMPLE * aiae_simple +
            AP.W_FUND_POS * fund_normalized +
            AP.W_MARGIN_HEAT * margin_normalized, 2)

    # ========== 五档判定层 ==========

    def classify_regime(self, aiae_value: float) -> int:
        """AIAE值 → 五档状态 (1-5)
        V3.0: 分界线从 aiae_params.REGIME_THRESHOLDS 读取
        """
        t = AP.REGIME_THRESHOLDS  # [13, 17, 23, 30]
        if aiae_value < t[0]:
            return 1
        elif aiae_value < t[1]:
            return 2
        elif aiae_value < t[2]:
            return 3
        elif aiae_value < t[3]:
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
        if slope > AP.SLOPE_ACCEL_UP:
            signal = {"type": "accel_up", "text": "AIAE 加速上行", "level": "warning"}
        elif slope < AP.SLOPE_ACCEL_DOWN:
            signal = {"type": "accel_down", "text": "AIAE 加速下行", "level": "opportunity"}

        return {"slope": round(slope, 2), "direction": direction, "signal": signal}

    def get_position_from_matrix(self, regime: int, erp_level: str, 
                                  aiae_value: float = None) -> int:
        """AIAE × ERP 仓位矩阵查表
        V3.0: 在分界线 ±1.5pt 内做平滑插值，消除仓位跳变
        """
        row = POSITION_MATRIX.get(erp_level, POSITION_MATRIX["erp_2_4"])
        idx = min(regime - 1, 4)
        base_pos = row[idx]
        
        # V3.0: 分界线平滑插值
        if aiae_value is not None:
            t = AP.REGIME_THRESHOLDS
            for i, threshold in enumerate(t):
                pos_high = row[i]       # 低档仓位（AIAE 低→仓位高）
                pos_low = row[i + 1]    # 高档仓位（AIAE 高→仓位低）
                if abs(aiae_value - threshold) <= AP.REGIME_SMOOTH_BUFFER:
                    base_pos = AP.smooth_position(
                        pos_low, pos_high, aiae_value, threshold)
                    _log(f"仓位平滑: AIAE={aiae_value:.1f} 近分界{threshold} → 插值 {base_pos}% (原{row[idx]}%)")
                    break
        
        return base_pos

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

    def get_run_all_weights(self, regime: int, erp_score: float = None) -> Dict:
        """获取 AIAE×ERP 联合驱动的五策略动态权重 (V2.0)
        
        Args:
            regime: AIAE 五档 (1-5)
            erp_score: ERP综合评分 (0-100), None时降级为neutral
        Returns:
            dict: 五策略权重 (mr, div, mom, erp, aiae_etf), 总和=1.0
        """
        # ERP score → tier
        if erp_score is not None and erp_score >= 55:
            tier = "bull"
        elif erp_score is not None and erp_score < 40:
            tier = "bear"
        else:
            tier = "neutral"  # 40-55 或 None
        
        regime_weights = JOINT_WEIGHTS.get(regime, JOINT_WEIGHTS[3])
        weights = regime_weights.get(tier, regime_weights["neutral"])
        
        _log(f"权重查表: AIAE Regime={regime} × ERP Score={erp_score} → Tier={tier} | W={weights}")
        return weights, tier

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

        # 融资占比信号 (V3.0: 阈值从参数中心读取)
        if margin_heat > AP.MARGIN_HEAT_DANGER:
            signals.append({"type": "margin", "level": "warning",
                          "text": f"融资占比 {margin_heat:.1f}% 偏高，散户杠杆入场", "color": "#f97316"})
        elif margin_heat < AP.MARGIN_HEAT_LOW:
            signals.append({"type": "margin", "level": "opportunity",
                          "text": f"融资占比 {margin_heat:.1f}% 极低，杠杆出清", "color": "#10b981"})

        return signals

    # ========== 月度历史管理 (C2) ==========

    def _get_monthly_history_file(self) -> str:
        return os.path.join(CACHE_DIR, "aiae_monthly_history.json")

    def _load_monthly_history(self) -> List[Dict]:
        """C2: 加载月度 AIAE 历史记录 (SQLite 优先, JSON 降级)"""
        try:
            rows = ac_db.get_aiae_history()
            if rows:
                return rows
        except Exception:
            pass
        # JSON fallback
        fp = self._get_monthly_history_file()
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _append_monthly_history(self, aiae_v1: float, regime: int):
        """C2: 追加当月 AIAE 值 (SQLite + JSON 双写)"""
        current_month = datetime.now().strftime("%Y-%m")
        # SQLite 主写入
        try:
            ac_db.upsert_aiae_monthly(current_month, aiae_v1, regime)
        except Exception as e:
            _log(f"SQLite upsert_aiae_monthly 失败: {e}", "WARN")
        # JSON 备份写入
        history = []
        fp = self._get_monthly_history_file()
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                pass
        if history and history[-1].get("month") == current_month:
            history[-1]["aiae_v1"] = aiae_v1
            history[-1]["regime"] = regime
            history[-1]["updated_at"] = datetime.now().isoformat()
        else:
            history.append({
                "month": current_month,
                "aiae_v1": aiae_v1,
                "regime": regime,
                "recorded_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            })
        atomic_write_json(history, fp)

    def _get_prev_month_aiae(self) -> Optional[float]:
        """C2: 获取上个月的 AIAE 值 (SQLite 优先)"""
        current_month = datetime.now().strftime("%Y-%m")
        # SQLite 优先
        try:
            val = ac_db.get_prev_month_aiae(current_month)
            if val is not None:
                return val
        except Exception:
            pass
        # JSON fallback
        history = []
        fp = self._get_monthly_history_file()
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                pass
        for entry in reversed(history):
            if entry["month"] != current_month:
                return entry["aiae_v1"]
        _log("月度历史不足: 斜率计算将输出 flat (无上月对比数据)", "WARN")
        return None

    # ========== 历史走势数据 ==========

    def get_chart_data(self, live_aiae: float = None) -> Dict:
        """输出历史 AIAE 走势 (静态+当前点)
        H3: 如果提供 live_aiae, 自动替换末尾估算点为实时值
        """
        # V1.0: 使用预设历史关键节点
        dates = [s["date"] for s in HISTORICAL_SNAPSHOTS]
        values = [s["aiae"] for s in HISTORICAL_SNAPSHOTS]
        labels = [s["label"] for s in HISTORICAL_SNAPSHOTS]

        # H3: 替换末尾 "当前状态(估)" 为实时计算值
        if live_aiae is not None and values:
            values[-1] = round(live_aiae, 1)
            dates[-1] = datetime.now().strftime("%Y-%m-%d")
            labels[-1] = "当前状态(实时)"

        # 五档区间线 (V3.0: 从参数中心读取, 消除硬编码漂移)
        _t = AP.REGIME_THRESHOLDS  # [12.5, 17, 23, 30]
        bands = [
            {"name": "Ⅰ级上限", "value": _t[0], "color": "#10b981"},
            {"name": "Ⅱ级上限", "value": _t[1], "color": "#3b82f6"},
            {"name": "Ⅲ级上限", "value": _t[2], "color": "#eab308"},
            {"name": "Ⅳ级上限", "value": _t[3], "color": "#f97316"},
        ]

        return {
            "dates": dates, "values": values, "labels": labels,
            "bands": bands,
            "stats": {
                "mean": 18.5, "min": 8.2, "max": 42.5,
                "current": values[-1] if values else 22.3
            }
        }

    # ========== 月度历史预填 (V2.1 冷启动修复) ==========

    def _seed_monthly_history_if_needed(self, current_aiae: float, current_regime: int):
        """V2.1: 如果月度历史为空或只有本月, 用近似值预填最近3个月
        避免斜率计算因无上月对比而永远为 flat
        """
        history = self._load_monthly_history()
        current_month = datetime.now().strftime("%Y-%m")
        
        # 如果已有2条以上记录 → 无需预填
        non_current = [h for h in history if h["month"] != current_month]
        if len(non_current) >= 1:
            return  # 已有上月数据
        
        # 预填最近3个月 (用当前值±小幅波动估算)
        seed_entries = []
        for i in range(3, 0, -1):
            seed_date = datetime.now() - timedelta(days=30 * i)
            seed_month = seed_date.strftime("%Y-%m")
            if seed_month == current_month:
                continue
            # 微调 ±0.3 避免完全相同
            seed_val = round(current_aiae + (i - 2) * 0.3, 2)
            seed_entries.append({
                "month": seed_month,
                "aiae_v1": seed_val,
                "regime": current_regime,
                "recorded_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "source": "seed_estimate",
            })
        
        if seed_entries:
            history = seed_entries + history
            fp = self._get_monthly_history_file()
            atomic_write_json(history, fp)
            _log(f"月度历史已预填 {len(seed_entries)} 条估算记录 (冷启动修复)")

    # ========== 完整报告 ==========

    def generate_report(self) -> Dict:
        """生成 AIAE 完整报告 (V2.1: 并行数据获取 + 季度提醒 + 冷启动修复)"""
        t0 = time.time()
        try:
            # 1. 并行获取三个数据源 (模块级线程池, 若 shutdown 则降级同步)
            try:
                f_mv = _bg_executor.submit(self._fetch_total_market_cap)
                f_m2 = _bg_executor.submit(self._fetch_m2)
                f_margin = _bg_executor.submit(self._fetch_margin_data)
                mv_data = f_mv.result(timeout=30)
                m2_data = f_m2.result(timeout=30)
                margin_data = f_margin.result(timeout=30)
            except RuntimeError:
                # 解释器 shutdown 阶段, 降级为同步
                _log("ThreadPool shutdown, 降级同步获取", "WARN")
                mv_data = self._fetch_total_market_cap()
                m2_data = self._fetch_m2()
                margin_data = self._fetch_margin_data()
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

            # V2.1: 月度历史冷启动修复
            try:
                self._seed_monthly_history_if_needed(aiae_v1, regime)
            except Exception as e:
                _log(f"月度历史预填失败 (non-fatal): {e}", "WARN")

            # 4. 斜率 (C2: 与上月同口径值对比)
            prev_aiae = self._get_prev_month_aiae()
            slope_info = self.compute_slope(aiae_v1, prev_aiae)

            # 5. ERP 交叉 (尝试从 ERP 引擎获取)
            erp_value = self._get_erp_value()
            erp_level = self.classify_erp_level(erp_value)
            matrix_position = self.get_position_from_matrix(regime, erp_level, aiae_value=aiae_v1)

            # 6. 子策略配额
            allocations = self.allocate_sub_strategies(regime, matrix_position)

            # 7. 信号
            signals = self.generate_signals(aiae_v1, regime, slope_info, margin_heat)

            # 8. 图表数据 (H3: 传入实时 AIAE 值替换末尾估算点)
            chart_data = self.get_chart_data(live_aiae=aiae_v1)

            # C2: 追加月度历史记录
            try:
                self._append_monthly_history(aiae_v1, regime)
            except Exception as e:
                _log(f"月度历史记录写入失败: {e}", "WARN")

            # 9. ERP交叉验证
            cross_validation = self._cross_validate(regime, erp_value)

            _log(f"报告生成完成 ({time.time()-t0:.1f}s) | AIAE={aiae_v1}% Regime={regime} Pos={matrix_position}%")

            # C1: 收集数据过期告警
            stale_warnings = []
            fund_stale = self._get_fund_position_stale_warning()
            if fund_stale:
                stale_warnings.append(fund_stale)
            # 检查数据源降级
            for src_name, src_data in [("市值", mv_data), ("M2", m2_data), ("融资", margin_data)]:
                if src_data.get("is_fallback"):
                    stale_warnings.append({
                        "type": f"{src_name}_fallback",
                        "severity": "warning",
                        "message": f"{src_name}数据使用降级值，非实时",
                    })

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
                "stale_data_warnings": stale_warnings,
                "fund_update_guide": FUND_UPDATE_GUIDE,

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
        """尝试从ERP引擎获取当前ERP值, 三级降级: 引擎→磁盘缓存→硬编码"""
        erp_cache_file = os.path.join(CACHE_DIR, "aiae_erp_latest.json")
        try:
            from erp_timing_engine import get_erp_engine
            engine = get_erp_engine()
            signal = engine.compute_signal()
            if signal.get("status") == "success":
                erp_val = signal["current_snapshot"].get("erp_value", 3.5)
                # 成功时持久化, 供后续降级使用
                try:
                    atomic_write_json({"erp_value": erp_val, "ts": datetime.now().isoformat()}, erp_cache_file)
                except Exception:
                    pass
                return erp_val
        except Exception as e:
            _log(f"ERP引擎读取失败, 尝试磁盘缓存: {e}", "WARN")
        # 降级 L2: 磁盘缓存
        if os.path.exists(erp_cache_file):
            try:
                with open(erp_cache_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                erp_val = cached.get("erp_value", 3.5)
                _log(f"ERP 使用磁盘缓存: {erp_val}% (from {cached.get('ts', '?')})", "WARN")
                return erp_val
            except Exception:
                pass
        # 降级 L3: 硬编码
        _log("ERP 使用硬编码降级值 3.5%", "WARN")
        return 3.5

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

