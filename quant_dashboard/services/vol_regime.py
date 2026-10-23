"""
AlphaCore · 市场波动率自适应仓位系数 (Vol Overlay V2)
=====================================================

把"仓位上限"从静态查表升级为随 A 股实际波动自适应:

    有效上限 = min(审计红线 95%, 基础上限 × 市场波动系数)

V1 的问题 (2026-10 审计):
  1. refresh_vol_cache() 没有任何调用方 → 缓存永远是初始值 1.0, 模块形同虚设
  2. 只作用于子策略上限, 决定总仓位的 AIAE 主轴 cap 完全不受影响
  3. 20 日单窗口 + 对称 + 瞬时生效, 容易来回跳
  4. 基准波动率是常数 18%, 无法适应不同年代的波动中枢
  5. 数据缺失时 fail-neutral (=1.0), 与系统其它部分的 fail-closed 原则矛盾

V2 设计 (2026-10, 经时点安全回测校准, 详见 docs/vol_overlay_calibration.md):

  回测结论 (沪深300 2015-2026 / 中证1000 / 创业板指 / 中证红利, 对照组 = 平均仓位相同的固定仓位):
    - "指数波动高就降仓、低就加仓" 的连续择时: 48 组参数全部跑输 (夏普更低, 回撤更深)
      → A 股高波动集中在底部与 V 型反弹期, 连续降仓会系统性错过反弹
    - 趋势+波动 / 回撤刹车 / 下行波动: 同样无法稳健跑赢
    - 仅在"极端波动"时刹车 (σ ≥ 2× 自适应基准, α=0.5): 平时完全不动, 成本≈0
      (夏普 -0.004, 回撤 -0.3pp, 年换手 0.18), 在 2015 股灾 / 2016 熔断等极端期触发

  因此本模块定位为"尾部保险刹车", 不是择时信号:
    - 波动估计: max(EWMA λ=0.94, 60 日实现波动)
    - 自适应基准: 过去 3 年 60 日波动的滚动中位数 (夹在 12%~30%)
    - 系数 = clamp((trigger_ratio × 基准 / 当前波动) ^ α, floor, ceiling)
      默认 trigger_ratio=2.0, α=0.5, floor=0.5, ceiling=1.0 → 波动 < 2 倍基准时系数恒为 1
    - 降快升慢参数保留但默认关闭 (回测中开启无增益)
    - 企业行为过滤: |日对数收益| > 0.21 视为拆分/除权等非交易跳变, 剔除
    - 时点安全: compute_vol_factor_frame() 第 t 行只用 ≤t 的数据,
      生产中 t 日收盘计算的系数用于 t+1 日决策; 回测可直接复用同一函数
    - 失效保守: 数据过期/缺失 → 系数 = min(最近有效值, stale_factor_cap)
    - 组合自身的结构性风险 (高波个股、主题集中) 由 services/portfolio_vol.py 负责

公开 API:
  - compute_vol_factor_frame(close, cfg)  纯函数, 回测/校准/单测使用
  - refresh_vol_cache(force=False)       收盘后由 warmup 调用 (幂等, 按文件 mtime 记忆)
  - current_overlay()                    刷新 + 读取, 永不抛异常
  - get_vol_overlay()                    供决策消费者使用的完整状态 (含新鲜度判定)
  - get_vol_adjustment_factor()          兼容 V1: 返回当前有效系数
  - apply_vol_overlay_to_cap(cap, ov)    基础上限 → 有效上限
  - get_vol_regime_info()                兼容 V1 的前端展示接口
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import date, datetime
from typing import Any, Mapping, Optional

from services.logger import get_logger

logger = get_logger("ac.vol_regime")

TRADING_DAYS = 252
AUDIT_HARD_CAP = 95.0

# ═══════════════════════════════════════════════════════
#  默认参数 (可被 strategy_runtime.json → vol_targeting.market 覆盖)
#  2026-10 用 2015-2026 A 股指数做过时点安全的参数网格校准,
#  结论与数据见 docs/vol_overlay_calibration.md
# ═══════════════════════════════════════════════════════
DEFAULT_MARKET_VOL_CONFIG: dict[str, Any] = {
    "enabled": True,
    "index_code": "000300.SH",      # 锚定指数 (市场层只负责"大环境", 组合自身风险由 portfolio_vol 负责)
    "ewma_lambda": 0.94,            # RiskMetrics 日频标准值, 半衰期约 11 个交易日
    "slow_window": 60,              # 慢速实现波动窗口
    "baseline_window": 756,         # 自适应基准: 约 3 年
    "baseline_min_days": 250,       # 基准至少需要 1 年数据, 否则用 fallback
    "baseline_fallback": 0.18,
    "baseline_floor": 0.12,
    "baseline_ceiling": 0.30,
    "trigger_ratio": 2.0,           # 当前波动 ≥ 2 倍基准才开始刹车 (尾部保险)
    "alpha": 0.5,                   # 刹车力度弹性
    "floor": 0.50,                  # 最多把上限砍半
    "ceiling": 1.00,                # 不因低波而放大上限 (回测无增益)
    "up_confirm_days": 1,           # 降快升慢: 默认关闭 (回测无增益, 保留可配置)
    "up_deadband": 0.0,
    "max_up_step_per_day": 1.0,
    "max_abs_log_return": 0.21,     # 超过视为企业行为跳变 (20cm 板 + 余量)
    "min_data_days": 120,
    "max_data_age_days": 10,        # 日历日; 覆盖国庆/春节长假
    "stale_factor_cap": 0.80,       # 数据过期/缺失时系数上限
}

_STATE_FILE_NAME = "vol_overlay_state.json"

# ═══════════════════════════════════════════════════════
#  纯计算 (无 IO, 时点安全)
# ═══════════════════════════════════════════════════════


def clean_log_returns(close, max_abs_log_return: float = 0.21):
    """收盘价 → 对数收益, 剔除非正价格与企业行为跳变 (拆分/除权未复权)."""
    import numpy as np
    import pandas as pd

    s = pd.Series(close, dtype="float64").dropna()
    s = s[s > 0]
    r = np.log(s).diff().dropna()
    return r[r.abs() <= max_abs_log_return]


def _regime_label(factor: float, brake_on: bool) -> str:
    if not brake_on:
        return "normal"
    if factor <= 0.65:
        return "extreme"
    if factor < 0.90:
        return "high_vol"
    return "elevated"


def compute_vol_factor_frame(close, cfg: Optional[Mapping[str, Any]] = None):
    """计算完整的时点安全系数序列.

    Args:
        close: 以日期为索引的收盘价 Series (升序)
        cfg:   参数, 缺省项取 DEFAULT_MARKET_VOL_CONFIG

    Returns:
        DataFrame (索引=日期), 列:
          sigma_fast / sigma_slow / sigma_hat / baseline / ratio / raw_factor / factor / crash / regime
          (crash=True 表示尾部刹车已触发)
        第 t 行只使用 ≤t 的数据; 数据不足 min_data_days 的行被剔除.
    """
    import numpy as np
    import pandas as pd

    c = dict(DEFAULT_MARKET_VOL_CONFIG)
    if cfg:
        c.update({k: v for k, v in cfg.items() if k in DEFAULT_MARKET_VOL_CONFIG})

    r = clean_log_returns(close, c["max_abs_log_return"])
    if len(r) < max(int(c["min_data_days"]), 30):
        return pd.DataFrame(columns=[
            "sigma_fast", "sigma_slow", "sigma_hat", "baseline", "ratio",
            "raw_factor", "factor", "crash", "regime",
        ])

    lam = float(c["ewma_lambda"])
    r2 = (r.values ** 2)
    var = np.empty_like(r2)
    seed_n = min(20, len(r2))
    v = float(np.mean(r2[:seed_n]))
    for i, x in enumerate(r2):
        v = lam * v + (1.0 - lam) * x
        var[i] = v
    sigma_fast = pd.Series(np.sqrt(var * TRADING_DAYS), index=r.index)

    win = int(c["slow_window"])
    sigma_slow = r.rolling(win, min_periods=max(20, win // 2)).std() * math.sqrt(TRADING_DAYS)
    sigma_hat = pd.concat([sigma_fast, sigma_slow], axis=1).max(axis=1, skipna=True)

    baseline = sigma_slow.rolling(
        int(c["baseline_window"]), min_periods=int(c["baseline_min_days"])
    ).median()
    baseline = baseline.fillna(float(c["baseline_fallback"]))
    baseline = baseline.clip(float(c["baseline_floor"]), float(c["baseline_ceiling"]))

    alpha = float(c["alpha"])
    floor, ceiling = float(c["floor"]), float(c["ceiling"])
    trigger = float(c["trigger_ratio"])
    ratio = sigma_hat / baseline
    raw = (trigger * baseline / sigma_hat.clip(lower=1e-4)) ** alpha
    raw = raw.clip(floor, ceiling)
    crash = ratio >= trigger

    # 降快升慢状态机
    confirm = int(c["up_confirm_days"])
    dead = float(c["up_deadband"])
    step = float(c["max_up_step_per_day"])
    factors = np.empty(len(raw))
    f = float(raw.iloc[0])
    up_count = 0
    for i, x in enumerate(raw.values):
        if x < f:
            f = float(x)
            up_count = 0
        elif x > f + dead:
            up_count += 1
            if up_count >= confirm:
                f = min(float(x), f + step)
        else:
            up_count = 0
        factors[i] = f

    out = pd.DataFrame({
        "sigma_fast": sigma_fast,
        "sigma_slow": sigma_slow,
        "sigma_hat": sigma_hat,
        "baseline": baseline,
        "ratio": ratio,
        "raw_factor": raw,
        "factor": factors,
        "crash": crash,
    }, index=r.index)
    out["regime"] = [
        _regime_label(fv, bool(cv)) for fv, cv in zip(out["factor"], out["crash"])
    ]
    # 预热期: 需要足够的样本才输出
    return out.iloc[int(c["min_data_days"]) - 1:] if len(out) >= int(c["min_data_days"]) else out.iloc[0:0]


def evaluate_overlay(snapshot: Optional[Mapping[str, Any]], cfg: Mapping[str, Any],
                     today: Optional[date] = None) -> dict:
    """把缓存快照 + 当前日期 → 可用于决策的系数 (新鲜度在读取时判定).

    status:
      ok        数据新鲜, 系数照常使用
      stale     数据过期, 系数 = min(最近有效值, stale_factor_cap)
      missing   从未成功计算, 系数 = stale_factor_cap
      disabled  用户在配置中显式关闭, 系数 = 1.0
    """
    today = today or date.today()
    stale_cap = float(cfg.get("stale_factor_cap", DEFAULT_MARKET_VOL_CONFIG["stale_factor_cap"]))
    max_age = int(cfg.get("max_data_age_days", DEFAULT_MARKET_VOL_CONFIG["max_data_age_days"]))

    if not cfg.get("enabled", True):
        return {"status": "disabled", "factor": 1.0, "reason": "配置已关闭波动率自适应"}

    snap = dict(snapshot or {})
    last = snap.get("factor")
    trade_date = snap.get("trade_date")
    valid_last = isinstance(last, (int, float)) and not isinstance(last, bool) and math.isfinite(last) and last > 0

    if not valid_last or not trade_date:
        return {
            **snap, "status": "missing", "factor": stale_cap,
            "reason": f"波动率数据缺失, 保守取系数 {stale_cap:.2f}",
        }

    try:
        td = datetime.strptime(str(trade_date)[:10], "%Y-%m-%d").date()
        age = (today - td).days
    except ValueError:
        return {
            **snap, "status": "missing", "factor": stale_cap,
            "reason": "波动率数据日期无效, 保守处理",
        }

    if age > max_age:
        eff = round(min(float(last), stale_cap), 4)
        return {
            **snap, "status": "stale", "factor": eff, "age_days": age,
            "reason": f"波动率数据已 {age} 天未更新 (> {max_age} 天), 系数降为 {eff:.2f}",
        }
    return {**snap, "status": "ok", "factor": round(float(last), 4), "age_days": age, "reason": ""}


def apply_vol_overlay_to_cap(base_cap, overlay: Optional[Mapping[str, Any]],
                             hard_cap: float = AUDIT_HARD_CAP) -> Optional[float]:
    """基础仓位上限 (0-100) × 系数 → 有效上限, 永不超过审计红线."""
    try:
        cap = float(base_cap)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(cap):
        return None
    factor = 1.0
    if overlay:
        try:
            factor = float(overlay.get("factor", 1.0))
        except (TypeError, ValueError):
            factor = 1.0
        if not math.isfinite(factor) or factor <= 0:
            factor = 1.0
    return round(max(0.0, min(hard_cap, cap * factor)), 1)


# ═══════════════════════════════════════════════════════
#  IO 层: 配置 / 数据 / 缓存
# ═══════════════════════════════════════════════════════

_vol_lock = threading.RLock()
_vol_cache: dict[str, Any] = {}
_vol_source_mtime: Optional[float] = None
_lazy_attempted = False


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _state_path() -> str:
    return os.path.join(_project_root(), "data_lake", _STATE_FILE_NAME)


def load_market_vol_config() -> dict:
    """strategy_runtime.json → vol_targeting.market, 缺省项用默认值."""
    merged = dict(DEFAULT_MARKET_VOL_CONFIG)
    try:
        from services.strategy_params import load_runtime_config
        section = (load_runtime_config().get("vol_targeting") or {}).get("market") or {}
        for k, v in section.items():
            if k in merged:
                merged[k] = v
    except Exception as e:  # 配置不可用时用默认值, 不影响系数的保守性
        logger.debug("vol_targeting.market 配置加载失败, 使用默认值: %s", e)
    return merged


def _load_index_close(index_code: str):
    """读取 data_lake/daily_prices/{code}.parquet → (close Series, mtime)."""
    import pandas as pd

    fpath = os.path.join(_project_root(), "data_lake", "daily_prices", f"{index_code}.parquet")
    if not os.path.exists(fpath):
        logger.warning("波动率: 文件不存在 %s", fpath)
        return None, None
    df = pd.read_parquet(fpath)
    if "close" not in df.columns or "trade_date" not in df.columns:
        logger.warning("波动率: %s 缺少 close/trade_date 字段", index_code)
        return None, None
    df = df.sort_values("trade_date")
    idx = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
    close = pd.Series(pd.to_numeric(df["close"], errors="coerce").values, index=idx)
    close = close[close.index.notna()].dropna()
    close = close[~close.index.duplicated(keep="last")]
    return close, os.path.getmtime(fpath)


def _persist_state(state: Mapping[str, Any]) -> None:
    try:
        path = _state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(state), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("波动率状态持久化失败 (非致命): %s", e)


def _load_persisted_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def refresh_vol_cache(force: bool = False) -> dict:
    """重新计算市场波动系数并更新缓存. 幂等: 源文件未变化时直接返回缓存.

    由 warmup_aiae_cache (启动 + 每日 15:35) 与 Dashboard 构建调用.
    """
    global _vol_source_mtime
    cfg = load_market_vol_config()

    with _vol_lock:
        if not cfg.get("enabled", True):
            _vol_cache.clear()
            _vol_cache.update({"updated_at": datetime.now().isoformat(), "source": "disabled"})
            return dict(_vol_cache)

        try:
            close, mtime = _load_index_close(cfg["index_code"])
        except Exception as e:
            logger.warning("波动率: 读取 %s 失败: %s", cfg["index_code"], e)
            close, mtime = None, None

        if close is None or len(close) == 0:
            # 保留最近一次有效快照 (内存或磁盘), 由 evaluate_overlay 按日期判定是否过期
            if not _vol_cache:
                _vol_cache.update(_load_persisted_state())
            return dict(_vol_cache)

        if not force and _vol_cache.get("factor") is not None and mtime == _vol_source_mtime:
            return dict(_vol_cache)

        frame = compute_vol_factor_frame(close, cfg)
        if frame.empty:
            logger.warning("波动率: %s 数据不足, 无法计算系数", cfg["index_code"])
            if not _vol_cache:
                _vol_cache.update(_load_persisted_state())
            return dict(_vol_cache)

        last = frame.iloc[-1]
        hist = frame["sigma_slow"].dropna()
        vol_pct = None
        if len(hist) > 60:
            vol_pct = round(float((hist.tail(756) < float(last["sigma_hat"])).mean() * 100), 1)

        state = {
            "factor": round(float(last["factor"]), 4),
            "raw_factor": round(float(last["raw_factor"]), 4),
            "sigma_fast": round(float(last["sigma_fast"]), 4),
            "sigma_slow": round(float(last["sigma_slow"]), 4) if math.isfinite(last["sigma_slow"]) else None,
            "sigma_hat": round(float(last["sigma_hat"]), 4),
            "baseline": round(float(last["baseline"]), 4),
            "ratio": round(float(last["ratio"]), 3),
            "trigger_ratio": float(cfg["trigger_ratio"]),
            "brake_on": bool(last["crash"]),
            "vol_pct": vol_pct,
            "regime": str(last["regime"]),
            "trade_date": frame.index[-1].strftime("%Y-%m-%d"),
            "index_code": cfg["index_code"],
            "updated_at": datetime.now().isoformat(),
            "source": "computed",
            "recent": [
                {"date": d.strftime("%Y-%m-%d"), "factor": round(float(v), 4)}
                for d, v in frame["factor"].tail(20).items()
            ],
        }
        _vol_cache.clear()
        _vol_cache.update(state)
        _vol_source_mtime = mtime
        _persist_state(state)

    logger.info(
        "波动系数更新: %s σ=%.1f%% 基准=%.1f%% (%.2f倍, 触发线%.1f倍) 系数=%.3f 数据日=%s",
        cfg["index_code"], state["sigma_hat"] * 100, state["baseline"] * 100,
        state["ratio"], state["trigger_ratio"], state["factor"], state["trade_date"],
    )
    return dict(state)


def get_vol_overlay(today: Optional[date] = None) -> dict:
    """决策消费者使用的系数 (含新鲜度判定). 首次调用会惰性刷新一次."""
    global _lazy_attempted
    cfg = load_market_vol_config()
    with _vol_lock:
        need_lazy = not _vol_cache and not _lazy_attempted
        if need_lazy:
            _lazy_attempted = True
    if need_lazy:
        try:
            refresh_vol_cache()
        except Exception as e:
            logger.warning("波动系数惰性刷新失败: %s", e)
    with _vol_lock:
        snap = dict(_vol_cache)
    ov = evaluate_overlay(snap, cfg, today=today)
    ov.pop("recent", None)
    return ov


def current_overlay() -> dict:
    """刷新 (幂等) 后读取系数; 永不抛异常. 供 warmup / Dashboard 构建使用."""
    try:
        refresh_vol_cache()
        return get_vol_overlay()
    except Exception as e:
        logger.warning("波动率系数刷新失败: %s", e)
        try:
            return get_vol_overlay()
        except Exception:
            cap = float(DEFAULT_MARKET_VOL_CONFIG["stale_factor_cap"])
            return {"status": "missing", "factor": cap, "reason": f"波动率模块异常, 保守取 {cap:.2f}"}


def get_vol_adjustment_factor() -> float:
    """兼容 V1: 当前有效系数 (已考虑新鲜度)."""
    return float(get_vol_overlay()["factor"])


def get_vol_regime_info() -> dict:
    """兼容 V1 的前端展示接口."""
    cfg = load_market_vol_config()
    ov = get_vol_overlay()
    with _vol_lock:
        recent = list(_vol_cache.get("recent", []))
    return {
        **ov,
        "current_vol": ov.get("sigma_hat"),
        "base_vol": ov.get("baseline", cfg["baseline_fallback"]),
        "recent": recent,
        "config": {k: cfg[k] for k in (
            "enabled", "index_code", "trigger_ratio", "alpha", "floor", "ceiling", "ewma_lambda",
            "slow_window", "up_confirm_days", "max_up_step_per_day",
            "max_data_age_days", "stale_factor_cap",
        )},
    }


def _reset_for_tests() -> None:
    """单元测试使用: 清空内存缓存."""
    global _vol_source_mtime, _lazy_attempted
    with _vol_lock:
        _vol_cache.clear()
        _vol_source_mtime = None
        _lazy_attempted = False
