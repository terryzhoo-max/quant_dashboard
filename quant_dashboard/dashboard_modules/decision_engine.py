"""
AlphaCore V27.0 Decision Intelligence Hub (Facade)
====================================================
O1 Refactor: 2949L -> ~700L (78% reduction)

All core logic split into dashboard_modules.decision.* subpackage.
This file serves as:
  1. Backward-compatible facade (all external imports unchanged)
  2. Home for aggregation functions that depend on multiple submodules
"""

import copy
import math
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from services.logger import get_logger

logger = get_logger("ac.decision")

try:
    from engines.erp_params import D1_SIGMOID_CENTER as _ERP_CENTER, D1_SIGMOID_K as _ERP_K
except ImportError:
    _ERP_CENTER, _ERP_K = 4.0, 1.5


# ==============================================================
#  Re-export from submodules (backward compatibility)
# ==============================================================

from dashboard_modules.decision.conflicts import (  # noqa: F401,F403
    _signal_direction, _CONFLICT_RULES, compute_conflict_matrix,
)

from dashboard_modules.decision.jcs import (  # noqa: F401,F403
    _JCS_WEIGHTS, _JCS_WEIGHTS_V4, _REGIME_CN_MAP, _REGIME_CAP_MAP,
    _recalc_vix_score, _recalc_hub_composite, _compute_jcs_with_weights, compute_jcs,
)

from dashboard_modules.decision.temperature import (  # noqa: F401,F403
    _GLOBAL_REGIMES, _GLOBAL_GAUGE_BANDS, _REGIME_CAP_LOOKUP,
    _build_global_temperature,
)

from dashboard_modules.decision.snapshot import (  # noqa: F401,F403
    _parse_erp_value, _build_snapshot_from_cache,
)

from dashboard_modules.decision.action_plan import (  # noqa: F401,F403
    _get_current_position, _apply_position_gap_note,
    generate_action_plan, generate_alerts,
)

from dashboard_modules.decision.scenarios import (  # noqa: F401,F403
    SCENARIOS, _SHOCK_NODES, _SHOCK_EDGES, _SHOCK_SOURCES, _SNAPSHOT_DELTA_MAP,
    _build_adjacency, propagate_shock, apply_shock_to_snapshot,
    run_shock_simulation, simulate_scenario,
)

from dashboard_modules.decision.position_path import (  # noqa: F401,F403
    _POSITION_RULES, generate_position_path,
    _estimate_volatility, _estimate_daily_volume,
    estimate_execution_cost, estimate_position_path_costs,
)

from dashboard_modules.decision.events import (  # noqa: F401,F403
    _EVENT_LOG_PATH, _SNAPSHOT_PATH, _MAX_EVENTS, _EVENT_COOLDOWNS,
    _check_event_cooldown, _load_last_snapshot, _save_last_snapshot,
    _load_event_log, _save_event_log,
    detect_market_events, get_recent_events,
)

from dashboard_modules.decision.risk_matrix import (  # noqa: F401,F403
    compute_risk_matrix,
)

from dashboard_modules.decision.accuracy import (  # noqa: F401,F403
    _get_index_close, _get_t5_trade_date, backfill_signal_accuracy,
)

from dashboard_modules.decision.contagion import (  # noqa: F401,F403
    _CONTAGION_INDICES, compute_contagion_matrix,
)


# ==============================================================
#  Aggregation functions (depend on multiple submodules)
# ==============================================================

def get_hub_data() -> dict:
    """决策中枢全量数据 (供 API 返回)"""
    snapshot = _build_snapshot_from_cache()

    conflicts = compute_conflict_matrix(snapshot)
    jcs = compute_jcs(snapshot)
    action_plan = generate_action_plan(snapshot, jcs, conflicts)

    # V19.0: 全球市场温度
    global_temp = _build_global_temperature()

    # V21.2: 数据新鲜度元数据 — 前端据此显示各引擎最后更新时间
    from services.cache_service import cache_manager
    _now_ts = datetime.now().timestamp()
    _freshness = {}

    # ── 各引擎缓存状态 + 数据日期提取 ──
    _engine_defs = [
        ("dashboard", "dashboard_data", "Dashboard"),
        ("aiae", "aiae_ctx", "AIAE"),
        ("strategy", "strategy_results", "策略引擎"),
        ("global", "aiae_global_report_data", "全球对比"),
    ]
    _dates_seen = []
    for _fk, _ck, _label in _engine_defs:
        _cached = cache_manager.get_json(_ck)
        if _cached:
            # 提取数据日期 (各引擎存储位置不同)
            _dd = None
            if _fk == "dashboard":
                # dashboard_data 不含 trade_date, 但内嵌 ERP 信号有日期
                _erp_snap = (_cached.get("data", {}).get("macro_cards", {})
                             .get("erp", {}))
                # 从 erp_pct 值存在推断数据有效, 日期从 strategy 补
            elif _fk == "aiae":
                _dd = _cached.get("trade_date") or _cached.get("date")
            elif _fk == "strategy":
                # strategy_results.erp_timing.current_snapshot.trade_date
                _erp_t = _cached.get("erp_timing", {})
                if isinstance(_erp_t, dict):
                    _dd = (_erp_t.get("data", _erp_t).get("current_snapshot", {})
                           .get("trade_date"))
                if not _dd:
                    _mr = _cached.get("mr", {})
                    if isinstance(_mr, dict):
                        _dd = (_mr.get("data", {}).get("market_overview", {})
                               .get("trade_date"))
            elif _fk == "global":
                _dd = (_cached.get("generated_at", "")[:10]
                       if isinstance(_cached.get("generated_at"), str) else None)

            _freshness[_fk] = {"label": _label, "status": "ok", "age_min": 0, "data_date": _dd}
            if _dd:
                _dates_seen.append(_dd)
        else:
            _freshness[_fk] = {"label": _label, "status": "stale", "age_min": -1, "data_date": None}

    # 权威日期源: ERP Timing 引擎的 current_snapshot.trade_date (数据交易日)
    if not _dates_seen:
        try:
            from erp_timing_engine import get_erp_engine
            _erp_sig = get_erp_engine().compute_signal()
            _erp_td = _erp_sig.get("current_snapshot", {}).get("trade_date")
            if _erp_td:
                _erp_td = str(_erp_td)[:10]
                _dates_seen.append(_erp_td)
                if "strategy" in _freshness:
                    _freshness["strategy"]["data_date"] = _erp_td
        except Exception:
            pass

    # ── 跨引擎日期一致性检查 ──
    _unique_dates = list(set(_dates_seen))
    _date_consistent = len(_unique_dates) <= 1
    _primary_date = _unique_dates[0] if _unique_dates else None

    # 用 last_update 时间戳计算各引擎数据年龄
    _last_upd = cache_manager.get_json("last_update")
    if _last_upd and isinstance(_last_upd, (int, float)):
        _age = max(0, int((_now_ts - _last_upd) / 60))  # V22.0 O3: 防时钟偏差产生负值
        for _fk2 in _freshness:
            if _freshness[_fk2]["status"] == "ok":
                _freshness[_fk2]["age_min"] = _age

    # V22.0: 信号半衰期 — 各引擎数据年龄映射为可靠性系数 (放射性衰变模型)
    # 半衰期定义: 经过此天数后, 信号可靠性降至 50%
    _DECAY_HALF_LIVES = {
        "aiae": 15,   # 月频数据, 缓慢衰减
        "erp": 3,     # 日频, 中等衰减 (ERP 信号本身是慢变量)
        "vix": 1,     # 实时数据, 快速衰减
        "mr": 2,      # 日频, 中等衰减
    }
    _DECAY_FRESHNESS_MAP = {
        "aiae": "aiae",
        "erp": "strategy",
        "vix": "dashboard",
        "mr": "strategy",
    }
    _signal_decay = {}
    for _eng_key, _hl_days in _DECAY_HALF_LIVES.items():
        _fk = _DECAY_FRESHNESS_MAP.get(_eng_key, _eng_key)
        _f = _freshness.get(_fk, {})
        _age_min = _f.get("age_min", -1)
        if _age_min >= 0:
            _age_days = _age_min / (60 * 24)
            _reliability = round(0.5 ** (_age_days / _hl_days), 3)
            _signal_decay[_eng_key] = {
                "age_min": _age_min,
                "half_life_hours": _hl_days * 24,
                "reliability": _reliability,
                "label": {"aiae": "AIAE", "erp": "ERP", "vix": "VIX", "mr": "MR"}.get(_eng_key, _eng_key),
            }
        else:
            _signal_decay[_eng_key] = {
                "age_min": -1,
                "half_life_hours": _hl_days * 24,
                "reliability": 0.0,
                "label": {"aiae": "AIAE", "erp": "ERP", "vix": "VIX", "mr": "MR"}.get(_eng_key, _eng_key),
            }

    # V22.0: 合规检查 (在 return 前计算, 内联到 dict)
    _compliance = {"status": "unknown", "summary": "合规检查不可用", "checks": []}
    try:
        from engines.compliance_engine import run_compliance_check
        _pos_target = action_plan.get("position_target", 55)
        _pos_current = snapshot.get("suggested_position", 55)
        _direction = "increase" if _pos_target > _pos_current + 3 \
            else ("decrease" if _pos_target < _pos_current - 3 else "hold")
        _ctx = {"direction": _direction, "jcs_level": jcs.get("level"), "jcs_score": jcs.get("score")}
        _compliance = run_compliance_check(snapshot, context=_ctx)
    except Exception as e:
        logger.debug("合规检查异常: %s", e)

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "snapshot": snapshot,
        "conflicts": conflicts,
        "jcs": jcs,
        "action_plan": action_plan,
        "alerts": generate_alerts(snapshot),
        "scenarios": {k: {"name": v["name"], "desc": v["desc"], "icon": v["icon"], "severity": v["severity"]}
                      for k, v in SCENARIOS.items()},
        "global_temperature": global_temp,
        "data_freshness": _freshness,
        "signal_decay": _signal_decay,
        "data_date": _primary_date,
        "date_consistent": _date_consistent,
        "compliance": _compliance,
    }


def log_daily_decision():
    """每日收盘快照写入 SQLite (由 warmup_pipeline 调用)"""
    from services import db as ac_db

    snapshot = _build_snapshot_from_cache()
    if not snapshot.get("aiae_regime"):
        logger.warning("决策快照跳过: 缓存数据不完整")
        return

    jcs = compute_jcs(snapshot)
    conflicts = compute_conflict_matrix(snapshot)

    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "aiae_regime": snapshot.get("aiae_regime"),
        "aiae_v1": snapshot.get("aiae_v1"),
        "erp_score": snapshot.get("erp_score"),
        "erp_val": snapshot.get("erp_val"),
        "vix_val": snapshot.get("vix_val"),
        "mr_regime": snapshot.get("mr_regime"),
        "hub_composite": snapshot.get("hub_composite"),
        "jcs_score": jcs["score"],
        "jcs_level": jcs["level"],
        "suggested_position": snapshot.get("suggested_position"),
        "conflict_count": conflicts["conflict_count"],
        "degraded_modules": ",".join(snapshot.get("degraded_modules", [])) if isinstance(snapshot.get("degraded_modules"), list) else str(snapshot.get("degraded_modules", "")),
        # V25.3: 影子模式 + 多资产信号
        "jcs_v4_score": jcs.get("shadow", {}).get("v4_score"),
        "jcs_v6_score": jcs.get("shadow", {}).get("v6_score"),
        "jcs_shadow_delta": jcs.get("shadow", {}).get("delta"),
        "gold_signal": snapshot.get("gold_signal"),
        "bond_signal": snapshot.get("bond_signal"),
    }

    ac_db.upsert_decision_log(data)
    ac_db.cleanup_old_decisions(365)

    shadow = jcs.get("shadow", {})
    logger.info("决策快照存档: JCS=%.1f (%s) shadow_delta=%.1f conflicts=%d pos=%s%%",
                jcs["score"], jcs["level"], shadow.get("delta", 0),
                conflicts["conflict_count"],
                snapshot.get("suggested_position", "?"))


#  Phase 2: 风险关联矩阵
# ═══════════════════════════════════════════════════════════

def compute_risk_matrix() -> dict:
    """
    风险关联矩阵:
    1. 策略标的重叠分析 (Jaccard Index)
    2. 板块集中度
    3. 尾部风险仪表
    """
    from services.cache_service import cache_manager

    strategy_results = cache_manager.get_json("strategy_results") or {}

    # 提取各策略买入标的集合
    strategy_codes = {}
    strategy_sectors = {}
    for sname in ["mr", "div", "mom"]:
        sdata = strategy_results.get(sname, {})
        if isinstance(sdata, dict):
            signals = sdata.get("data", {}).get("buy_signals", [])
            codes = set()
            sectors = {}
            for s in signals:
                code = s.get("ts_code") or s.get("code", "")
                if code:
                    codes.add(code)
                sector = s.get("group") or s.get("sector", "other")
                sectors[sector] = sectors.get(sector, 0) + 1
            strategy_codes[sname] = codes
            strategy_sectors[sname] = sectors

    # 1. Jaccard 重叠矩阵
    strat_names = list(strategy_codes.keys())
    overlap_matrix = []
    for i, a in enumerate(strat_names):
        row = []
        for j, b in enumerate(strat_names):
            sa, sb = strategy_codes.get(a, set()), strategy_codes.get(b, set())
            if i == j:
                row.append({"pair": f"{a}-{b}", "jaccard": 1.0, "shared": len(sa)})
            elif len(sa | sb) > 0:
                jaccard = round(len(sa & sb) / len(sa | sb), 3)
                row.append({"pair": f"{a}-{b}", "jaccard": jaccard, "shared": len(sa & sb)})
            else:
                row.append({"pair": f"{a}-{b}", "jaccard": 0, "shared": 0})
        overlap_matrix.append(row)

    # 共有标的列表
    all_codes = set()
    for codes in strategy_codes.values():
        all_codes |= codes
    multi_strategy_codes = []
    for code in all_codes:
        in_strats = [s for s, c in strategy_codes.items() if code in c]
        if len(in_strats) >= 2:
            multi_strategy_codes.append({"code": code, "strategies": in_strats, "count": len(in_strats)})
    multi_strategy_codes.sort(key=lambda x: x["count"], reverse=True)

    # 2. 板块集中度 (V19.2: 实际持仓优先, 策略信号回退)
    strat_labels = {"mr": "MR趋势", "div": "红利", "mom": "动量"}
    data_source = "signal"

    # ── 尝试从实际持仓读取 (市值加权 — 真实风险暴露) ──
    portfolio_sectors = {}
    portfolio_count = 0
    try:
        from portfolio_engine import get_portfolio_engine
        _pe = get_portfolio_engine()
        _val = _pe.get_valuation()
        _positions = _val.get("positions", [])
        if _positions:
            for p in _positions:
                industry = p.get("industry", "其他")
                weight = float(p.get("weight", 0))
                portfolio_sectors[industry] = portfolio_sectors.get(industry, 0) + weight
            portfolio_count = len(_positions)
            if portfolio_sectors:
                data_source = "portfolio"
    except Exception as e:
        logger.debug("板块集中度: 持仓读取失败, 回退策略信号: %s", e)

    if data_source == "portfolio":
        # 实际持仓路径 (市值权重)
        total_weight = sum(portfolio_sectors.values()) or 1
        sector_concentration = []
        for sec, w in sorted(portfolio_sectors.items(), key=lambda x: x[1], reverse=True)[:8]:
            pct = round(w / total_weight * 100, 1)
            sector_concentration.append({
                "sector": sec, "count": 0, "pct": pct, "sources": ["实际持仓"],
            })
        top_sector_pct = sector_concentration[0]["pct"] if sector_concentration else 0
        total_signals = portfolio_count
    else:
        # 回退路径: 策略信号 (等权计数)
        all_sectors = {}
        sector_sources = {}
        for sname, sectors in strategy_sectors.items():
            for sec, cnt in sectors.items():
                all_sectors[sec] = all_sectors.get(sec, 0) + cnt
                if sname not in sector_sources.setdefault(sec, []):
                    sector_sources[sec].append(sname)
        total_signals = sum(all_sectors.values()) or 1
        sector_concentration = []
        for sec, cnt in sorted(all_sectors.items(), key=lambda x: x[1], reverse=True)[:8]:
            pct = round(cnt / total_signals * 100, 1)
            sources = [strat_labels.get(s, s) for s in sector_sources.get(sec, [])]
            sector_concentration.append({
                "sector": sec, "count": cnt, "pct": pct, "sources": sources,
            })
        top_sector_pct = sector_concentration[0]["pct"] if sector_concentration else 0

    # HHI: 赫芬达尔指数 (0-10000, >2500 高集中)
    hhi = round(sum(s["pct"] ** 2 for s in sector_concentration))

    # 3. 尾部风险仪表 (综合: 集中度 + VIX + AIAE + 矛盾)
    snapshot = _build_snapshot_from_cache()
    vix = snapshot.get("vix_val", 20) or 20
    conflicts = compute_conflict_matrix(snapshot)

    # 尾部风险公式: 0-100 (V19.1: 参数校准 + 权重重分配)

    # 集中度 — 20%以下健康, 100%满分; 信号池<5时衰减防虚高
    concentration_risk = min(100, max(0, (top_sector_pct - 20) * 1.25))
    if total_signals < 5:
        concentration_risk *= total_signals / 5

    # VIX — 不变 (15→0, 40→100)
    vix_risk = min(100, max(0, (vix - 15) * 4))

    # V19.1: AIAE 连续值映射 (10%→0, 25%→50, 40%→100), 取代粗糙5级离散
    aiae_v1 = snapshot.get("aiae_v1") or 22
    aiae_risk = min(100, max(0, (aiae_v1 - 10) / 30 * 100))

    # 矛盾 — 不变
    conflict_risk = min(100, conflicts["conflict_count"] * 30)

    # V19.1: 权重重分配 — AIAE结构性风险提权, VIX情绪噪声降权
    tail_risk = round(
        concentration_risk * 0.30 +
        vix_risk * 0.20 +          # 30→20: VIX 是短期情绪指标
        aiae_risk * 0.35 +         # 25→35: AIAE 是核心宏观风险锚
        conflict_risk * 0.15, 1
    )

    if tail_risk >= 70:
        tail_level, tail_label = "high", "🔴 尾部风险偏高"
    elif tail_risk >= 40:
        tail_level, tail_label = "medium", "🟡 尾部风险中等"
    else:
        tail_level, tail_label = "low", "🟢 尾部风险可控"

    return {
        "strategy_names": strat_names,
        "overlap_matrix": overlap_matrix,
        "multi_strategy_codes": multi_strategy_codes[:10],
        "sector_concentration": sector_concentration,
        "top_sector_pct": top_sector_pct,
        "hhi": hhi,
        "total_signals": total_signals,
        "data_source": data_source,
        "tail_risk": {
            "score": tail_risk,
            "level": tail_level,
            "label": tail_label,
            "components": {
                "concentration": round(concentration_risk, 1),
                "vix": round(vix_risk, 1),
                "aiae": round(aiae_risk, 1),
                "conflict": round(conflict_risk, 1),
            },
        },
    }


#  Phase 2: 准确率回填 (T+5 真实市场收益) — V17.0 修正
# ═══════════════════════════════════════════════════════════

def _get_index_close(trade_date: str, index_code: str = "000300.SH") -> Optional[float]:
    """
    从 Tushare 获取指定日期的指数收盘价。
    支持交易日回溯: 若当日非交易日则查前一交易日。
    返回 None 表示无法获取。
    """
    try:
        import tushare as ts
        pro = ts.pro_api()
        # trade_date 格式: YYYY-MM-DD → YYYYMMDD
        dt_str = trade_date.replace("-", "")
        dt = datetime.strptime(dt_str, "%Y%m%d")
        from datetime import timedelta
        for offset in range(5):  # 最多回溯5天
            try:
                try_date = (dt - timedelta(days=offset)).strftime("%Y%m%d")
                df = pro.index_daily(ts_code=index_code, trade_date=try_date)
                if df is not None and not df.empty:
                    return float(df.iloc[0]["close"])
            except Exception:
                continue
    except Exception as e:
        logger.warning("获取指数收盘价失败 (%s, %s): %s", trade_date, index_code, e)
    return None


def _get_t5_trade_date(base_date: str) -> Optional[str]:
    """V25.2 A-3: 获取精确 T+5 交易日 (Tushare trade_cal, 降级为 T+7 自然日)"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        dt_str = base_date.replace("-", "")
        # 查询 base_date 后 10 个交易日的日历
        df = pro.trade_cal(
            exchange='SSE', start_date=dt_str,
            end_date=(datetime.strptime(dt_str, "%Y%m%d") + timedelta(days=15)).strftime("%Y%m%d"),
            fields='cal_date,is_open'
        )
        if df is not None and not df.empty:
            open_days = df[df['is_open'] == 1].sort_values('cal_date')
            # 跳过 T 日本身, 取第 5 个交易日
            future = open_days[open_days['cal_date'] > dt_str]
            if len(future) >= 5:
                t5 = future.iloc[4]['cal_date']  # 0-indexed, 第5个
                return f"{t5[:4]}-{t5[4:6]}-{t5[6:]}"
    except Exception as e:
        logger.debug("trade_cal 查询失败 (%s), 降级为 T+7: %s", base_date, e)
    # 降级: T+7 自然日
    dt = datetime.strptime(base_date, "%Y-%m-%d")
    return (dt + timedelta(days=7)).strftime("%Y-%m-%d")


def backfill_signal_accuracy(force_recalc: bool = False):
    """
    V25.2: 使用沪深300真实收盘价计算 T+5 收益率.
    
    Args:
        force_recalc: True 时强制重算已有 signal_correct 的记录 (A-7 一次性修复)
    """
    from services import db as ac_db

    today = datetime.now()
    conn = ac_db._get_conn()
    
    if force_recalc:
        # A-7: 重算所有已回填但使用旧逻辑的记录
        rows = conn.execute(
            "SELECT date, market_return_5d FROM decision_log "
            "WHERE market_return_5d IS NOT NULL "
            "ORDER BY date DESC LIMIT 30"
        ).fetchall()
        recalc_count = 0
        for row in rows:
            log_date, ret = row[0], row[1]
            if ret is not None:
                ac_db.backfill_accuracy(log_date, ret)
                recalc_count += 1
        if recalc_count > 0:
            logger.info("准确率重算完成 (force_recalc): %d 条", recalc_count)
    
    # 常规回填: 查找未回填的记录
    rows = conn.execute(
        "SELECT date FROM decision_log WHERE market_return_5d IS NULL "
        "AND date <= ? ORDER BY date DESC LIMIT 15",
        ((today - timedelta(days=5)).strftime("%Y-%m-%d"),)
    ).fetchall()

    if not rows:
        return

    filled_count = 0
    for row in rows:
        log_date = row[0]  # YYYY-MM-DD
        try:
            # 获取 T 日收盘价
            close_t = _get_index_close(log_date)
            if close_t is None:
                logger.debug("准确率回填跳过 %s: T日收盘价不可用", log_date)
                continue

            # V25.2: 使用 trade_cal 获取精确 T+5 交易日
            t5_date = _get_t5_trade_date(log_date)
            if t5_date is None:
                continue
            close_t5 = _get_index_close(t5_date)
            if close_t5 is None:
                logger.debug("准确率回填跳过 %s: T+5日(%s)收盘价不可用", log_date, t5_date)
                continue

            market_return = round((close_t5 - close_t) / close_t, 4)
            ac_db.backfill_accuracy(log_date, market_return)
            filled_count += 1
            logger.info("准确率回填: %s -> return_5d=%.4f (%.2f->%.2f, T+5=%s)",
                        log_date, market_return, close_t, close_t5, t5_date)
        except Exception as e:
            logger.warning("准确率回填异常 %s: %s", log_date, e)
            continue

    if filled_count > 0:
        logger.info("准确率回填完成: %d/%d 条", filled_count, len(rows))


#  V22.0: 跨市场风险传染矩阵 (Contagion Matrix)
#  计算四大市场 120 日收益率相关性, 零新 API 调用
# ═══════════════════════════════════════════════════════════

# 四大市场索引: parquet 文件 → 标签
_CONTAGION_INDICES = [
    {"key": "cn", "ts_code": "510300.SH", "label": "A股", "flag": "🇨🇳",
     "file": "data_lake/daily_prices/510300.SH.parquet"},
    {"key": "us", "ts_code": "513500.SH", "label": "美股", "flag": "🇺🇸",
     "file": "data_lake/daily_prices/513500.SH.parquet"},
    {"key": "hk", "ts_code": "HSI", "label": "港股", "flag": "🇭🇰",
     "file": "data_lake/erp_hk_hsi_history.parquet", "col": "close"},
    {"key": "jp", "ts_code": "N225", "label": "日股", "flag": "🇯🇵",
     "file": "data_lake/erp_jp_nikkei.parquet", "col": "close"},
    # 数据源确认:
    #   CN: 沪深300ETF (Tushare → daily_prices/510300.SH.parquet)
    #   US: 标普500ETF (Tushare → daily_prices/513500.SH.parquet)
    #   HK: 恒生指数 (erp_hk_engine._fetch_hsi_history → erp_hk_hsi_history.parquet, col=close)
    #   JP: 日经225  (erp_jp_engine._fetch_nikkei_history → erp_jp_nikkei.parquet, col=close)
    # 均为引擎原生缓存, 零新增 API 调用.
]


def compute_contagion_matrix(window_days: int = 120) -> dict:
    """
    计算四大市场日收益率 Pearson 相关性矩阵。

    数据源: data_lake/daily_prices/ 中的 parquet 文件 (零 API 调用)
    方法:
      1. 读取四个 ETF 的日线收盘价
      2. 计算日收益率 (close.pct_change)
      3. 对齐交易日 (取四市场交集)
      4. 计算 {window_days} 日滚动 Pearson 矩阵
      5. 返回矩阵 + 传染力解读

    返回:
    {
        "markets": [{key, label, flag}],
        "correlation_matrix": [[1.0, 0.35, 0.62, 0.28], ...],
        "window_days": 120,
        "common_days": 245,
        "contagion_risk": "medium"/"high"/"low",
        "contagion_note": str,
        "high_pairs": [{a, b, corr, level}],
    }
    """
    import os
    import numpy as np
    import pandas as pd

    # ── 1. 读取 ETF/指数日线 ──
    returns = {}
    for idx in _CONTAGION_INDICES:
        fpath = idx["file"]
        if not os.path.exists(fpath):
            continue
        try:
            df = pd.read_parquet(fpath)
            if df.empty:
                continue

            # 确定价格列名 (默认 "close", 可覆盖为 "index_value" 等)
            price_col = idx.get("col", "close")
            if price_col not in df.columns:
                continue

            # 确保有日期列
            if "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.set_index("trade_date")
            elif df.index.name != "trade_date" and not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # 日收益率
            r = df[price_col].pct_change().dropna()
            # 过滤异常值 (>50% 单日波动)
            r = r[(r > -0.5) & (r < 0.5)]
            if len(r) >= 30:
                returns[idx["key"]] = r
        except Exception as e:
            logger.debug("传染矩阵: 读取 %s 失败: %s", fpath, e)

    if len(returns) < 2:
        return {
            "status": "insufficient_data",
            "markets": [],
            "correlation_matrix": [],
            "window_days": window_days,
            "common_days": 0,
            "contagion_risk": "unknown",
            "contagion_note": "数据不足，需至少两个市场的日线数据",
            "high_pairs": [],
        }

    # ── 2. 对齐日期 ──
    ret_df = pd.DataFrame(returns)
    ret_df = ret_df.dropna()  # 仅保留所有市场都有数据的交易日
    common_days = len(ret_df)
    if common_days < window_days:
        # 数据不够窗口大小, 用全部数据
        effective_window = common_days
    else:
        effective_window = window_days

    # 取最近 effective_window 天
    ret_tail = ret_df.tail(effective_window)

    # ── 3. 计算 Pearson 相关性 ──
    corr_matrix_raw = ret_tail.corr().values
    market_keys = list(ret_df.columns)
    market_count = len(market_keys)

    # 构建输出矩阵 (按原始 _CONTAGION_INDICES 顺序)
    ordered_keys = [idx["key"] for idx in _CONTAGION_INDICES if idx["key"] in market_keys]
    corr_map = {}
    for i, ki in enumerate(market_keys):
        for j, kj in enumerate(market_keys):
            corr_map[(ki, kj)] = round(float(corr_matrix_raw[i][j]), 3)

    matrix = []
    for ki in ordered_keys:
        row = []
        for kj in ordered_keys:
            row.append(corr_map.get((ki, kj), 0.0))
        matrix.append(row)

    # ── 4. 高相关对检测 (|ρ| > 0.5) ──
    high_pairs = []
    for i, ki in enumerate(ordered_keys):
        for j, kj in enumerate(ordered_keys):
            if i >= j:
                continue
            corr = corr_map.get((ki, kj), 0)
            if abs(corr) > 0.5:
                level = "extreme" if abs(corr) > 0.8 else ("high" if abs(corr) > 0.65 else "moderate")
                label_i = next((idx["label"] for idx in _CONTAGION_INDICES if idx["key"] == ki), ki)
                label_j = next((idx["label"] for idx in _CONTAGION_INDICES if idx["key"] == kj), kj)
                high_pairs.append({
                    "a": label_i, "b": label_j,
                    "corr": corr,
                    "level": level,
                    "direction": "同涨同跌" if corr > 0 else "对冲",
                })

    # ── 5. 传染风险评估 ──
    avg_corr = np.mean([abs(corr) for (ki, kj), corr in corr_map.items() if ki != kj]) if len(corr_map) > 1 else 0
    if avg_corr > 0.7:
        contagion_risk = "high"
        contagion_note = f"🔴 市场高度联动 (平均 |ρ|={avg_corr:.2f})，单一风险事件可能引发跨市场共振。建议降低单一市场集中度。"
    elif avg_corr > 0.4:
        contagion_risk = "medium"
        contagion_note = f"🟡 市场温和联动 (平均 |ρ|={avg_corr:.2f})，存在区域性分散价值。选择低相关市场可有效降低组合波动。"
    else:
        contagion_risk = "low"
        contagion_note = f"🟢 市场相对独立 (平均 |ρ|={avg_corr:.2f})，全球分散化效果显著。当前是跨市场配置的理想窗口。"

    # ── 6. 市场信息 ──
    markets_info = []
    for idx in _CONTAGION_INDICES:
        if idx["key"] in ordered_keys:
            markets_info.append({
                "key": idx["key"],
                "label": idx["label"],
                "flag": idx["flag"],
                "ts_code": idx["ts_code"],
            })

    return {
        "markets": markets_info,
        "correlation_matrix": matrix,
        "window_days": effective_window,
        "common_days": common_days,
        "contagion_risk": contagion_risk,
        "contagion_note": contagion_note,
        "high_pairs": high_pairs,
    }


def get_hub_data_with_events() -> dict:
    """
    get_hub_data 的增强版: 额外检测市场事件并附加事件列表。
    供 API 直接调用以原子化获取决策中枢 + 事件。
    """
    result = get_hub_data()

    try:
        snapshot = result.get("snapshot", {})
        if snapshot:
            events = detect_market_events(snapshot)
            result["market_events"] = get_recent_events(10)
            result["new_events_count"] = len(events)
    except Exception as e:
        logger.debug("事件检测异常: %s", e)
        result["market_events"] = []
        result["new_events_count"] = 0

    return result


