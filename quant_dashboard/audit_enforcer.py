"""
AlphaCore 审计执行器 V4.0 — "带枪保安"
========================================
职责:
  1. enforce_stop_loss()     — 突破止损线的持仓 → 自动全量卖出 (个股-12%/ETF-8% 差异化)
  2. enforce_trade_block()   — 数据过期 → 写入交易阻断标志文件
  3. get_enforcer_status()   — 查询执行器当前状态
  4. run_post_audit_enforcement() — 审计报告出炉后的统一执行入口

设计原则:
  - 所有执行动作均记录到 audit_enforcement_log.json (不可篡改审计轨迹)
  - 每个强制操作都有 "reason" 字段，可追溯触发条件
  - 静音期内不执行 (但会记录 "skipped" 状态)
"""

import os
import json
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BLOCK_FILE = os.path.join(BASE_DIR, "audit_trade_block.json")
LOG_FILE = os.path.join(BASE_DIR, "audit_enforcement_log.json")
MUTE_RUNTIME_FILE = os.path.join(BASE_DIR, "audit_mute_runtime.json")
MAX_LOG_ENTRIES = 200  # 保留最近 200 条执行日志


# ═══════════════════════════════════════════════════════
#  配置加载
# ═══════════════════════════════════════════════════════
def _load_enforcer_config():
    """从 runtime 文件加载执行器配置 (优先), 降级到 config.py"""
    # V5.0: 先检查 runtime 文件 (toggle_enforcer 写入的)
    runtime_file = os.path.join(BASE_DIR, "audit_enforcer_runtime.json")
    runtime_overrides = {}
    if os.path.exists(runtime_file):
        try:
            with open(runtime_file, "r", encoding="utf-8") as f:
                runtime_overrides = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    try:
        from config import AUDIT_ENFORCER
        cfg = dict(AUDIT_ENFORCER)
    except ImportError:
        cfg = {"enabled": True, "auto_stop_loss": True,
                "block_trade_on_stale_data": True, "stale_data_block_days": 5}

    # runtime 覆盖 config 默认值
    if "enabled" in runtime_overrides:
        cfg["enabled"] = runtime_overrides["enabled"]
    return cfg


def _load_mute_config():
    """
    从运行时文件加载静音配置 (优先级高于 config.py 的默认值)
    运行时文件由 API 写入，支持动态修改
    """
    if os.path.exists(MUTE_RUNTIME_FILE):
        try:
            with open(MUTE_RUNTIME_FILE, "r", encoding="utf-8") as f:
                rt = json.load(f)
            # 检查静音是否过期
            mute_until = rt.get("mute_until")
            if mute_until:
                try:
                    expiry = datetime.fromisoformat(mute_until)
                    if datetime.now() > expiry:
                        # 静音已过期，自动解除
                        os.remove(MUTE_RUNTIME_FILE)
                        return {"muted_checks": [], "degraded_mode": False, "mute_until": None}
                except (ValueError, TypeError):
                    pass
            return rt
        except (json.JSONDecodeError, IOError):
            pass

    # 降级到 config.py 默认值
    try:
        from config import AUDIT_MUTE
        return dict(AUDIT_MUTE)
    except ImportError:
        return {"muted_checks": [], "degraded_mode": False, "mute_until": None}


def _save_mute_config(mute_cfg):
    """持久化静音配置到运行时文件"""
    with open(MUTE_RUNTIME_FILE, "w", encoding="utf-8") as f:
        json.dump(mute_cfg, f, indent=2, ensure_ascii=False)


def _load_audit_config():
    """从 config.py 加载审计阈值"""
    try:
        from config import AUDIT_CONFIG
        return dict(AUDIT_CONFIG)
    except ImportError:
        return {"stop_loss_stock": -10.0, "stop_loss_etf": -8.0, "stale_data_block_days": 5}


# ═══════════════════════════════════════════════════════
#  日志系统
# ═══════════════════════════════════════════════════════
def _append_log(entry):
    """追加一条执行日志"""
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except (json.JSONDecodeError, IOError):
            logs = []

    entry["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs.append(entry)

    # 保留最近 N 条
    if len(logs) > MAX_LOG_ENTRIES:
        logs = logs[-MAX_LOG_ENTRIES:]

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


def get_enforcement_log(limit=20):
    """获取最近 N 条执行日志"""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
        return list(reversed(logs[-limit:]))  # 最新在前
    except (json.JSONDecodeError, IOError):
        return []


# ═══════════════════════════════════════════════════════
#  交易阻断标志
# ═══════════════════════════════════════════════════════
def set_trade_block(blocked, reason=""):
    """写入/清除交易阻断标志"""
    data = {
        "blocked": blocked,
        "reason": reason,
        "blocked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if blocked else "",
    }
    with open(BLOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    _append_log({
        "action": "trade_block" if blocked else "trade_unblock",
        "reason": reason,
        "status": "executed",
    })


def is_trade_blocked():
    """外部查询: 交易是否被阻断 (含 24 小时自动解除)"""
    if not os.path.exists(BLOCK_FILE):
        return False, ""
    try:
        with open(BLOCK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("blocked", False):
            return False, ""
        # 24 小时自动解除
        blocked_at = data.get("blocked_at", "")
        if blocked_at:
            dt = datetime.strptime(blocked_at, "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - dt).total_seconds() > 86400:
                set_trade_block(False, "24小时自动解除")
                return False, ""
        return True, data.get("reason", "审计执行器阻断")
    except (json.JSONDecodeError, IOError, ValueError):
        return False, ""


# ═══════════════════════════════════════════════════════
#  止损强制卖出
# ═══════════════════════════════════════════════════════
def enforce_stop_loss(pos_list, stop_loss_stock=-10.0, stop_loss_etf=-8.0):
    """
    遍历持仓，将突破止损线的标的全量卖出。
    V5.1: 个股/ETF 差异化止损 (个股-12%, ETF-8%)
    返回: 执行动作列表 [{"ts_code", "name", "pnl_pct", "amount", "price", "result"}]
    """
    actions = []

    # 导入 ETF 识别工具
    try:
        from audit_engine import _is_etf
    except ImportError:
        def _is_etf(code):
            if not code: return False
            c = code.split(".")[0]
            return c.startswith(("51", "56", "58", "159", "160", "16"))

    try:
        from portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
    except Exception as e:
        _append_log({
            "action": "stop_loss_abort",
            "reason": f"portfolio_engine 不可用: {str(e)[:80]}",
            "status": "error",
        })
        return actions

    for p in pos_list:
        pnl_pct = p.get("pnl_pct", 0)
        ts_code = p.get("ts_code", "")
        is_etf = _is_etf(ts_code)
        sl_line = stop_loss_etf if is_etf else stop_loss_stock

        if pnl_pct >= sl_line:
            continue  # 未触及止损线

        name = p.get("name", ts_code)
        amount = p.get("amount", 0)
        price = p.get("price", p.get("cost", 0))
        tag = "ETF" if is_etf else "个股"

        if amount <= 0 or price <= 0:
            continue

        # 执行全量卖出
        try:
            success, msg = engine.reduce_position(ts_code, amount, price)
            action_entry = {
                "action": "forced_stop_loss",
                "ts_code": ts_code,
                "name": name,
                "type": tag,
                "pnl_pct": round(pnl_pct, 2),
                "sl_line": sl_line,
                "amount": amount,
                "price": round(price, 3),
                "result": "success" if success else "failed",
                "message": msg,
                "status": "executed",
            }
        except Exception as e:
            action_entry = {
                "action": "forced_stop_loss",
                "ts_code": ts_code,
                "name": name,
                "type": tag,
                "pnl_pct": round(pnl_pct, 2),
                "sl_line": sl_line,
                "amount": amount,
                "price": round(price, 3),
                "result": "error",
                "message": str(e)[:100],
                "status": "error",
            }

        actions.append(action_entry)
        _append_log(action_entry)

    return actions


# ═══════════════════════════════════════════════════════
#  数据过期 → 交易阻断
# ═══════════════════════════════════════════════════════
def enforce_trade_block_on_stale_data(audit_report, stale_block_days=5):
    """
    检查审计报告中的数据新鲜度，若过期则写入交易阻断标志。
    """
    dq = audit_report.get("modules", {}).get("data_quality", {})
    checks = dq.get("checks", [])

    # 检查日线数据新鲜度
    for c in checks:
        if c.get("name") == "日线数据新鲜度" and c.get("status") == "fail":
            detail = c.get("detail", "")
            # 提取天数
            import re
            m = re.search(r'(\d+)天前', detail)
            days = int(m.group(1)) if m else 999

            if days >= stale_block_days:
                set_trade_block(True, f"日线数据过期 {days} 天 (阈值: {stale_block_days}天)")
                return True, f"日线数据过期 {days} 天，交易已阻断"

    # 数据正常 → 解除阻断
    blocked, _ = is_trade_blocked()
    if blocked:
        set_trade_block(False, "数据恢复正常，自动解除阻断")

    return False, ""


# ═══════════════════════════════════════════════════════
#  核心入口: 审计后执行
# ═══════════════════════════════════════════════════════
def run_post_audit_enforcement(audit_report):
    """
    审计完毕后的统一执行入口。
    返回: {
        "enforcer_enabled": bool,
        "actions": [...],
        "trade_blocked": bool,
        "mute_status": {...},
    }
    """
    enforcer_cfg = _load_enforcer_config()
    mute_cfg = _load_mute_config()
    audit_cfg = _load_audit_config()

    result = {
        "enforcer_enabled": enforcer_cfg.get("enabled", False),
        "actions": [],
        "trade_blocked": False,
        "trade_block_reason": "",
        "mute_status": {
            "degraded_mode": mute_cfg.get("degraded_mode", False),
            "muted_checks": mute_cfg.get("muted_checks", []),
            "mute_until": mute_cfg.get("mute_until"),
            "is_muted": bool(mute_cfg.get("mute_until") or mute_cfg.get("degraded_mode")),
        },
    }

    # ── 执行器未启用 → 直接返回 ──
    if not enforcer_cfg.get("enabled", False):
        _append_log({
            "action": "enforcer_skipped",
            "reason": "执行器总开关已关闭",
            "status": "skipped",
        })
        return result

    # ── 降级模式 → 只记录不执行 ──
    if mute_cfg.get("degraded_mode", False):
        _append_log({
            "action": "enforcer_degraded",
            "reason": "降级模式启用，仅记录不执行",
            "status": "skipped",
        })
        return result

    # ── 1. 止损强制卖出 ──
    if enforcer_cfg.get("auto_stop_loss", True):
        sl_stock = audit_cfg.get("stop_loss_stock", audit_cfg.get("stop_loss_line", -10.0))
        sl_etf = audit_cfg.get("stop_loss_etf", -8.0)

        # 获取持仓列表 (从风控模块的原始数据)
        rc = audit_report.get("modules", {}).get("risk_control", {})
        pos_list = []

        # 重新获取实时持仓 (不依赖审计报告中的冗余数据)
        try:
            from audit_engine import _get_live_portfolio
            pos_list, _, _, _, _ = _get_live_portfolio()
        except Exception:
            pass

        if pos_list:
            stop_actions = enforce_stop_loss(pos_list, sl_stock, sl_etf)
            result["actions"].extend(stop_actions)

    # ── 2. 数据过期 → 交易阻断 ──
    if enforcer_cfg.get("block_trade_on_stale_data", True):
        stale_days = enforcer_cfg.get("stale_data_block_days", 5)
        blocked, reason = enforce_trade_block_on_stale_data(audit_report, stale_days)
        result["trade_blocked"] = blocked
        result["trade_block_reason"] = reason

    # 更新当前阻断状态
    blocked, reason = is_trade_blocked()
    result["trade_blocked"] = blocked
    result["trade_block_reason"] = reason

    return result


# ═══════════════════════════════════════════════════════
#  状态查询 API
# ═══════════════════════════════════════════════════════
def get_enforcer_status():
    """返回执行器完整状态快照"""
    enforcer_cfg = _load_enforcer_config()
    mute_cfg = _load_mute_config()
    blocked, block_reason = is_trade_blocked()
    recent_logs = get_enforcement_log(10)

    return {
        "enforcer_enabled": enforcer_cfg.get("enabled", False),
        "auto_stop_loss": enforcer_cfg.get("auto_stop_loss", True),
        "block_on_stale": enforcer_cfg.get("block_trade_on_stale_data", True),
        "trade_blocked": blocked,
        "trade_block_reason": block_reason,
        "mute_status": {
            "degraded_mode": mute_cfg.get("degraded_mode", False),
            "muted_checks": mute_cfg.get("muted_checks", []),
            "mute_until": mute_cfg.get("mute_until"),
            "is_muted": bool(mute_cfg.get("mute_until") or mute_cfg.get("degraded_mode")),
        },
        "recent_actions": recent_logs,
    }


# ═══════════════════════════════════════════════════════
#  静音管理
# ═══════════════════════════════════════════════════════
def set_mute(minutes=None, degraded=False, muted_checks=None):
    """
    设置静音配置。
    minutes: 静音 N 分钟 (None = 使用 degraded_mode)
    degraded: 降级模式 (fail → warn)
    muted_checks: 指定静音的检查项名称列表
    """
    from datetime import timedelta
    mute_cfg = {
        "degraded_mode": degraded,
        "muted_checks": muted_checks or [],
        "mute_until": None,
    }
    if minutes and minutes > 0:
        mute_cfg["mute_until"] = (datetime.now() + timedelta(minutes=minutes)).isoformat()

    _save_mute_config(mute_cfg)
    _append_log({
        "action": "mute_set",
        "reason": f"静音 {minutes}分钟" if minutes else f"降级模式: {degraded}",
        "details": mute_cfg,
        "status": "executed",
    })
    return mute_cfg


def clear_mute():
    """解除所有静音"""
    if os.path.exists(MUTE_RUNTIME_FILE):
        os.remove(MUTE_RUNTIME_FILE)
    _append_log({
        "action": "mute_cleared",
        "reason": "手动解除静音",
        "status": "executed",
    })
    return {"degraded_mode": False, "muted_checks": [], "mute_until": None}


def toggle_enforcer(enabled):
    """运行时开关执行器 (修改 config 文件中的值)"""
    # 通过运行时文件实现，不修改 config.py 源码
    runtime_file = os.path.join(BASE_DIR, "audit_enforcer_runtime.json")
    data = {"enabled": enabled}
    with open(runtime_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    _append_log({
        "action": "enforcer_toggle",
        "reason": f"执行器{'启用' if enabled else '禁用'}",
        "status": "executed",
    })
    return enabled
