"""
AlphaCore · 组合层波动率预算 (Portfolio Vol Budget V3)
======================================================

市场层 (services/vol_regime.py) 只做尾部刹车; 本模块解决的是"结构性风险":
同样 90% 的仓位, 放在宽基 ETF 和放在 17 只半导体个股上, 风险相差 2~3 倍。

这里用的是"按组成定预算", 不是择时:
  - 波动与相关性用 250 日等权窗口估计 (慢变量), 反映的是持仓结构本身,
    而不是最近几天的市场情绪 (回测已证明 A 股上的短期波动择时无效)

三条约束, 取最严:
  1. 组合波动目标   最大权益仓位 = 目标波动 / 当前持仓结构满仓时的波动
  2. 单票波动上限   单票上限 = min(静态上限, k / 该标的年化波动)
  3. 涨跌停跳空上限 连续 N 个跌停的损失 ≤ 账户的 gap_loss_budget
       20cm 板 (科创/创业): 2 个跌停 ≈ -36% → 单票 ≤ 5.6%
       10cm 主板:           2 个跌停 ≈ -19% → 单票 ≤ 10.5%

V3 架构 (2026-10): 一条纯函数流水线, 每一段可单测、可替换
  ① _load_inputs      持仓 → 权重 (占账户总资产)
  ② _build_risk_model 行情 → 收益面板 / 波动 / 收缩相关 / 协方差 / β / 新鲜度
  ③ _constraints      单票上限 + 目标波动 → 最大权益仓位
  ④ _rebalance        等比缩放 vs 最小换手, 按规则选推荐草案
  ⑤ _analytics        执行前后 · 历史回放 (非参数 VaR/ES/回撤) · 压力 · 再配置 · 流动性
  ⑥ 组装 + 审计元数据 (schema / 指纹 / 计算时间)

V3 新增:
  - 历史回放: 用当前权重回放过去 250 个交易日 → 非参数 VaR/ES、最差单日、最大回撤
    (正态近似会低估 A 股肥尾; 两者都给, 并给出"肥尾倍数")
  - 风险归因分桶: 科创 20cm / 创业 20cm / 主板 10cm / ETF
  - 行情新鲜度: 每个持仓的最后行情日; 过期行情计入数据质量, 不静默使用
  - 单票超限的超额金额 (结论层据此在"总仓位在预算内"时仍给出警告)
  - 结果缓存: 指纹 = 持仓 + 参数 + 行情文件 mtime; 行情或持仓变化自动失效

所有参数可在 strategy_runtime.json → vol_targeting.portfolio 中覆盖。
本模块只给出约束与减仓草案, 不会自动下单。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Mapping, Optional

from services.logger import get_logger

logger = get_logger("ac.portfolio_vol")

TRADING_DAYS = 252
SCHEMA_VERSION = "vol_budget/3"

DEFAULT_PORTFOLIO_VOL_CONFIG: dict[str, Any] = {
    "enabled": True,
    "target_vol": 0.15,             # 组合年化波动目标 (≈ 最大回撤 -25% 量级); 应与个人投资政策一致
    "vol_window": 250,              # 估计窗口 (交易日), 慢变量
    "min_obs": 60,                  # 少于该样本用代理波动
    "shrinkage": 0.30,              # 相关矩阵向平均相关收缩的强度
    "k_stock": 0.03,                # 个股: 权重 × 波动 ≤ 3%  (波动 60% → 5%)
    "k_etf": 0.08,                  # ETF:  权重 × 波动 ≤ 8%  (波动 40% → 20%)
    "static_cap_stock": 8.0,        # 个股静态上限 (%)
    "static_cap_etf": 25.0,         # ETF 静态上限 (%)
    "gap_loss_budget": 0.02,        # 连续跌停的最大可承受损失 (占账户)
    "gap_limit_days": 2,            # 假设连续跌停天数
    "gap_shock_etf": -0.10,         # 跳空情景下 ETF 的冲击 (ETF 无连续跌停, 但会随成分股折价)
    "proxy_vol_stock": 0.60,
    "proxy_vol_etf": 0.40,
    "proxy_corr": 0.60,
    "max_abs_log_return": 0.21,
    "proxy_weight_warn": 0.30,      # 代理估计 + 过期行情占比超过该值 → status=partial
    "max_price_age_days": 7,        # 行情最后一日距估值日 > N 个日历日 → 视为过期
    "enforce_in_compliance": False, # True: 超出目标波动对应仓位 10pp 以上 → 合规硬阻断; False: 软警告
    "trim_step": 0.0025,            # 最小换手减仓的步长 (占账户)
    "participation_rate": 0.10,     # 执行参与率上限 (占 20 日成交额中位数)
    "market_index": "000300.SH",    # 压力情景 β 锚: 大盘
    "theme_index": "588000.SH",     # 压力情景 β 锚: 科创50 (用 ETF 收盘价); 也用于历史回放的缺口填充
    "proxy_vol_band": 0.25,         # 代理波动 ±25% 的敏感度区间
    "min_turnover_saving": 0.15,    # 最小换手方案需比等比缩放少交易 ≥15% 才被推荐, 否则推荐保持结构的等比缩放
    "stress_corr_floor": 0.30,      # 再配置测算时的压力相关下限: 危机中相关性上升, 不用短样本的负相关定规模
    "hs_window": 250,               # 历史回放窗口 (交易日)
    "cache_ttl_seconds": 300,       # 结果缓存 (指纹不变时); 0 = 关闭
    "diversifiers": [               # 风险预算再利用候选 (有行情才计算)
        ["512890.SH", "红利低波ETF"],
        ["510300.SH", "沪深300ETF"],
        ["518880.SH", "黄金ETF"],
        ["511010.SH", "国债ETF"],
        ["511880.SH", "货币ETF"],
    ],
}

Z95 = 1.6448536269514722
ES95_MULT = 2.0627128075074257   # φ(z95) / 0.05


# ═══════════════════════════════════════════════════════
#  分类工具
# ═══════════════════════════════════════════════════════

def is_etf(ts_code: str) -> bool:
    c = (ts_code or "").split(".")[0]
    return c.startswith(("51", "52", "56", "58", "159", "16"))


def price_limit_pct(ts_code: str, name: str = "") -> float:
    """A 股日涨跌幅限制."""
    c = (ts_code or "").split(".")[0]
    if "ST" in (name or "").upper():
        return 0.05
    if c.startswith(("688", "689", "300", "301")):
        return 0.20
    if c.startswith(("8", "4", "92")):
        return 0.30
    return 0.10


BUCKETS = (
    ("star", "科创板 20cm"),
    ("chinext", "创业板 20cm"),
    ("main", "主板 10cm"),
    ("bse", "北交所 30cm"),
    ("etf", "ETF"),
)


def risk_bucket(ts_code: str) -> str:
    """风险归因分桶: 跌停幅度决定了止损失效时的跳空损失, 是 A 股组合最重要的结构维度."""
    if is_etf(ts_code):
        return "etf"
    c = (ts_code or "").split(".")[0]
    if c.startswith(("688", "689")):
        return "star"
    if c.startswith(("300", "301")):
        return "chinext"
    if c.startswith(("8", "4", "92")):
        return "bse"
    return "main"


def _merge_cfg(cfg: Optional[Mapping[str, Any]]) -> dict:
    merged = dict(DEFAULT_PORTFOLIO_VOL_CONFIG)
    if cfg:
        merged.update({k: v for k, v in cfg.items() if k in merged})
    return merged


def load_portfolio_vol_config() -> dict:
    try:
        from services.strategy_params import load_runtime_config
        section = (load_runtime_config().get("vol_targeting") or {}).get("portfolio") or {}
        return _merge_cfg(section)
    except Exception as e:
        logger.debug("vol_targeting.portfolio 配置加载失败, 使用默认值: %s", e)
        return _merge_cfg(None)


# ═══════════════════════════════════════════════════════
#  行情读取 (每个文件按 mtime 只读一次; close 与 amount 共用一次读取)
# ═══════════════════════════════════════════════════════

def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _price_path(ts_code: str) -> Optional[str]:
    base = os.path.join(_root(), "data_lake", "daily_prices")
    for name in (f"{ts_code}.parquet", f"gem_{ts_code}.parquet"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None


_frame_cache: dict[str, tuple[float, Any]] = {}
_frame_lock = threading.Lock()


def _read_frame(ts_code: str):
    """data_lake/daily_prices/{code}.parquet (或 gem_ 前缀副本) → DataFrame[close, amount], 日期索引."""
    import pandas as pd

    path = _price_path(ts_code)
    if path is None:
        return None
    mtime = os.path.getmtime(path)
    with _frame_lock:
        hit = _frame_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    df = pd.read_parquet(path)
    if "close" not in df.columns or "trade_date" not in df.columns:
        return None
    df = df.sort_values("trade_date")
    idx = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
    out = pd.DataFrame({
        "close": pd.to_numeric(df["close"], errors="coerce").values,
        "amount": (pd.to_numeric(df["amount"], errors="coerce").values * 1000.0
                   if "amount" in df.columns else float("nan")),   # Tushare amount 单位为千元
    }, index=idx)
    out = out[out.index.notna()]
    out = out[~out.index.duplicated(keep="last")]
    with _frame_lock:
        _frame_cache[path] = (mtime, out)
    return out


def default_price_loader(ts_code: str):
    """收盘价 Series (日期索引)."""
    f = _read_frame(ts_code)
    return None if f is None else f["close"].dropna()


def default_amount_loader(ts_code: str):
    """日成交额 Series (元)."""
    f = _read_frame(ts_code)
    return None if f is None else f["amount"].dropna()


def _price_mtime(ts_code: str) -> Optional[float]:
    p = _price_path(ts_code)
    return os.path.getmtime(p) if p else None


# ═══════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════

@dataclass
class _Inputs:
    rows: list
    codes: list
    w: Any                 # np.ndarray, 占账户总资产
    total: float
    invested: float


@dataclass
class _RiskModel:
    rets: dict             # code → 对数收益 Series (已清洗, 已截窗)
    vols: Any              # np.ndarray 年化波动
    sources: list          # "data" | "proxy"
    corr: Any
    cov: Any
    avg_corr: float
    last_dates: list       # 每个持仓的最后行情日 (None = 无行情)
    stale: list            # bool
    beta_mkt: Any
    beta_thm: Any
    beta_estimated: list   # bool: 对主题指数的 β 是否为估计值
    m_ret: Any = None
    t_ret: Any = None
    obs: list = field(default_factory=list)


def _clean_returns(close, c) -> Any:
    import numpy as np
    import pandas as pd

    s = pd.Series(close, dtype="float64").dropna()
    s = s[s > 0]
    lr = np.log(s).diff().dropna()
    return lr[lr.abs() <= float(c["max_abs_log_return"])].tail(int(c["vol_window"]))


def _nearest_psd(corr):
    import numpy as np

    vals, vecs = np.linalg.eigh(corr)
    vals = np.clip(vals, 1e-6, None)
    fixed = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    fixed = fixed / np.outer(d, d)
    np.fill_diagonal(fixed, 1.0)
    return fixed


def _beta(r, m, min_obs):
    import pandas as pd

    df = pd.concat([r, m], axis=1, join="inner").dropna()
    if len(df) < min_obs:
        return None
    var = float(df.iloc[:, 1].var())
    return float(df.cov().iloc[0, 1] / var) if var > 0 else None


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════
#  ① 输入
# ═══════════════════════════════════════════════════════

def _load_inputs(positions, total_asset) -> Optional[_Inputs]:
    import numpy as np

    try:
        total = float(total_asset)
    except (TypeError, ValueError):
        total = 0.0
    rows = []
    for code, p in (positions or {}).items():
        mv = p.get("broker_market_value", p.get("market_value", 0)) or 0
        try:
            mv = float(mv)
        except (TypeError, ValueError):
            mv = 0.0
        if mv > 0 and math.isfinite(mv):
            rows.append({"ts_code": code, "name": p.get("name", code), "mv": mv})
    if not rows or total <= 0 or not math.isfinite(total):
        return None
    w = np.array([r["mv"] / total for r in rows])
    return _Inputs(rows=rows, codes=[r["ts_code"] for r in rows], w=w, total=total, invested=float(w.sum()))


# ═══════════════════════════════════════════════════════
#  ② 风险模型
# ═══════════════════════════════════════════════════════

def _build_risk_model(inp: _Inputs, loader, c, asof: Optional[date]) -> _RiskModel:
    import numpy as np
    import pandas as pd

    min_obs = int(c["min_obs"])
    max_age = int(c["max_price_age_days"])
    rets, last_dates, obs = {}, [], []
    for r in inp.rows:
        try:
            close = loader(r["ts_code"])
        except Exception as e:
            logger.debug("组合波动: 读取 %s 失败: %s", r["ts_code"], e)
            close = None
        lr = _clean_returns(close, c) if close is not None and len(close) >= 2 else None
        if lr is not None and len(lr) >= min_obs:
            rets[r["ts_code"]] = lr
            last_dates.append(_to_date(lr.index[-1]))
            obs.append(int(len(lr)))
        else:
            last_dates.append(None)
            obs.append(int(len(lr)) if lr is not None else 0)

    vols, sources = [], []
    for r in inp.rows:
        code = r["ts_code"]
        if code in rets:
            vols.append(float(rets[code].std() * math.sqrt(TRADING_DAYS)))
            sources.append("data")
        else:
            vols.append(float(c["proxy_vol_etf"] if is_etf(code) else c["proxy_vol_stock"]))
            sources.append("proxy")
    vols = np.array(vols)
    # 估值日缺省时以最新行情日为参照 (相对滞后); compute_from_store 传入今天 (绝对过期)
    known = [d for d in last_dates if d]
    ref = asof or (max(known) if known else None)
    stale = [bool(ref and d and (ref - d).days > max_age) for d in last_dates]

    n = len(inp.codes)
    corr = np.full((n, n), np.nan)
    np.fill_diagonal(corr, 1.0)
    if len(rets) >= 2:
        cm = pd.DataFrame(rets).corr(min_periods=min_obs)
        for i, ci in enumerate(inp.codes):
            for j, cj in enumerate(inp.codes):
                if i != j and ci in cm.index and cj in cm.columns:
                    v = cm.loc[ci, cj]
                    if pd.notna(v):
                        corr[i, j] = float(v)
    off = corr[~np.eye(n, dtype=bool)] if n > 1 else np.array([])
    observed = off[~np.isnan(off)]
    avg_corr = float(observed.mean()) if observed.size else float(c["proxy_corr"])
    corr = np.where(np.isnan(corr), avg_corr, corr)
    delta = float(c["shrinkage"])
    target = np.full((n, n), avg_corr)
    np.fill_diagonal(target, 1.0)
    corr = (1 - delta) * corr + delta * target
    if n > 1:
        corr = _nearest_psd(corr)
    cov = np.outer(vols, vols) * corr

    def _index_ret(code):
        try:
            s_ = loader(code)
        except Exception:
            s_ = None
        if s_ is None or len(s_) < min_obs:
            return None
        return _clean_returns(s_, c)

    m_ret, t_ret = _index_ret(c["market_index"]), _index_ret(c["theme_index"])
    b_mkt, b_thm = [], []
    for r in inp.rows:
        rr = rets.get(r["ts_code"])
        b_mkt.append(_beta(rr, m_ret, min_obs) if rr is not None and m_ret is not None else None)
        b_thm.append(_beta(rr, t_ret, min_obs) if rr is not None and t_ret is not None else None)

    def _fill(betas, default_stock, default_etf):
        stock_vals = [b for b, r in zip(betas, inp.rows) if b is not None and not is_etf(r["ts_code"])]
        etf_vals = [b for b, r in zip(betas, inp.rows) if b is not None and is_etf(r["ts_code"])]
        ms = float(np.median(stock_vals)) if stock_vals else default_stock
        me = float(np.median(etf_vals)) if etf_vals else default_etf
        return np.array([b if b is not None else (me if is_etf(r["ts_code"]) else ms)
                         for b, r in zip(betas, inp.rows)])

    return _RiskModel(
        rets=rets, vols=vols, sources=sources, corr=corr, cov=cov, avg_corr=avg_corr,
        last_dates=last_dates, stale=stale,
        beta_mkt=_fill(b_mkt, 1.3, 1.2), beta_thm=_fill(b_thm, 1.0, 0.9),
        beta_estimated=[b is None for b in b_thm], m_ret=m_ret, t_ret=t_ret, obs=obs,
    )


# ═══════════════════════════════════════════════════════
#  ③ 约束
# ═══════════════════════════════════════════════════════

def name_cap_pct(ts_code: str, name: str, vol: float, cfg: Mapping[str, Any]) -> tuple[float, str]:
    """单票上限 (%) 及起约束作用的规则."""
    etf = is_etf(ts_code)
    static = float(cfg["static_cap_etf"] if etf else cfg["static_cap_stock"])
    k = float(cfg["k_etf"] if etf else cfg["k_stock"])
    candidates = {"static": static}
    if vol and vol > 0:
        candidates["vol"] = k / vol * 100
    if not etf:
        limit = price_limit_pct(ts_code, name)
        days = int(cfg["gap_limit_days"])
        gap_loss = 1 - (1 - limit) ** days
        candidates["gap"] = float(cfg["gap_loss_budget"]) / gap_loss * 100
    rule = min(candidates, key=candidates.get)
    return round(candidates[rule], 2), rule


def _constraints(inp: _Inputs, rm: _RiskModel, c) -> dict:
    import numpy as np

    port_var = float(inp.w @ rm.cov @ inp.w)
    port_vol = math.sqrt(max(port_var, 0.0))
    sleeve_vol = port_vol / inp.invested if inp.invested > 0 else 0.0
    target_vol = float(c["target_vol"])
    max_equity = min(1.0, target_vol / sleeve_vol) if sleeve_vol > 0 else 1.0
    caps, rules = [], []
    for i, r in enumerate(inp.rows):
        cap, rule = name_cap_pct(r["ts_code"], r["name"], rm.vols[i], c)
        caps.append(cap)
        rules.append(rule)
    return {
        "port_var": port_var, "port_vol": port_vol, "sleeve_vol": sleeve_vol,
        "target_vol": target_vol, "max_equity": max_equity,
        "caps_pct": caps, "cap_rules": rules, "caps": np.array(caps) / 100,
    }


# ═══════════════════════════════════════════════════════
#  ④ 再平衡草案
# ═══════════════════════════════════════════════════════

def _min_turnover_trim(w, caps, cov, target_vol, step):
    """最小换手的风险削减 (贪心): 先压到单票上限, 再反复削减"边际风险/单位权重"最高的持仓.

    与等比缩放相比, 同样达到目标波动时交易更少, 并优先保留低边际风险的分散化持仓 (如宽基/主题 ETF)。
    """
    import numpy as np

    x = np.minimum(w, caps).astype(float)
    step = max(float(step), 1e-4)
    for _ in range(int(2.0 / step) + 10):        # 上界: 把 200% 权重全部减完所需的步数
        var = float(x @ cov @ x)
        if var <= target_vol ** 2 or x.sum() <= 0:
            break
        mcr = (cov @ x) / math.sqrt(var)
        mcr = np.where(x > 1e-9, mcr, -np.inf)
        i = int(np.argmax(mcr))
        x[i] = max(0.0, x[i] - step)
    return x


def _rebalance(inp: _Inputs, rm: _RiskModel, cons: dict, c) -> dict:
    import numpy as np

    w, cov, target_vol = inp.w, rm.cov, cons["target_vol"]
    capped_w = np.minimum(w, cons["caps"])
    capped_vol = math.sqrt(max(float(capped_w @ cov @ capped_w), 0.0))
    scale = min(1.0, target_vol / capped_vol) if capped_vol > 0 else 1.0
    prop_w = capped_w * scale
    greedy_w = _min_turnover_trim(w, cons["caps"], cov, target_vol, float(c["trim_step"]))
    prop_turnover = float((w - prop_w).clip(min=0).sum()) * inp.total
    greedy_turnover = float((w - greedy_w).clip(min=0).sum()) * inp.total
    saving = (prop_turnover - greedy_turnover) / prop_turnover if prop_turnover > 0 else 0.0
    # 推荐规则: 省下的换手不足阈值时, 保持结构 (分散度) 比少交易一点更重要
    use_greedy = saving >= float(c["min_turnover_saving"])
    return {
        "prop_w": prop_w, "greedy_w": greedy_w, "final_w": greedy_w if use_greedy else prop_w,
        "prop_turnover": prop_turnover, "greedy_turnover": greedy_turnover,
        "saving": saving, "use_greedy": use_greedy,
        "cap_excess_amt": float((w - cons["caps"]).clip(min=0).sum()) * inp.total,
    }


# ═══════════════════════════════════════════════════════
#  ⑤ 分析
# ═══════════════════════════════════════════════════════

def _risk_snapshot(x, cov, vols, total):
    """一组权重的风险读数 (金额按账户总资产; 正态近似)."""
    import numpy as np

    var = float(x @ cov @ x)
    vol = math.sqrt(max(var, 0.0))
    d = vol / math.sqrt(TRADING_DAYS)
    rc = (x * (cov @ x) / var) if var > 0 else np.zeros(len(x))
    dr = float((x @ vols) / vol) if vol > 0 else 0.0
    top3 = float(np.sort(rc)[-3:].sum()) if len(rc) else 0.0
    return {
        "invested_pct": round(float(x.sum()) * 100, 2),
        "portfolio_vol": round(vol, 4),
        "var_1d_95_amt": round(Z95 * d * total, 0),
        "es_20d_95_amt": round(ES95_MULT * d * math.sqrt(20) * total, 0),
        "effective_bets": round(dr ** 2, 2),
        "max_weight_pct": round(float(x.max()) * 100, 2) if len(x) else 0.0,
        "top3_risk_share": round(top3, 4),
    }


def _replay_panel(inp: _Inputs, rm: _RiskModel, c):
    """历史回放用的简单收益面板 (行=交易日, 列=持仓).

    缺口 (上市晚 / 停牌 / 无行情) 用 β_主题 × 主题指数收益填充; 主题指数也缺失则填 0。
    返回 (panel DataFrame, 填充占比) ; 数据不足时返回 (None, None)。
    """
    import numpy as np
    import pandas as pd

    window = int(c["hs_window"])
    anchor = rm.t_ret if rm.t_ret is not None else rm.m_ret
    frames = {code: s for code, s in rm.rets.items()}
    if anchor is not None:
        idx = anchor.index
    elif frames:
        idx = pd.DataFrame(frames).index
    else:
        return None, None
    idx = idx.sort_values()[-window:]
    if len(idx) < int(c["min_obs"]):
        return None, None
    panel = pd.DataFrame(index=idx)
    filled = 0
    for i, code in enumerate(inp.codes):
        s = frames.get(code)
        col = s.reindex(idx) if s is not None else pd.Series(np.nan, index=idx)
        miss = col.isna()
        if miss.any():
            filled += int(miss.sum())
            if anchor is not None:
                col = col.where(~miss, float(rm.beta_thm[i]) * anchor.reindex(idx))
            col = col.fillna(0.0)
        panel[code] = np.expm1(col.values)          # 对数收益 → 简单收益
    return panel, filled / float(panel.size) if panel.size else None


def _replay_stats(panel, x, total) -> dict:
    """按固定权重 x 回放: 非参数 VaR/ES、最差单日、最大回撤."""
    import numpy as np

    pnl = panel.values @ x                          # 每日占账户的盈亏
    n = len(pnl)
    q = float(np.quantile(pnl, 0.05))
    tail = pnl[pnl <= q]
    es = float(-tail.mean()) if tail.size else float(-q)
    nav = np.cumprod(1.0 + pnl)
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    t_i = int(np.argmin(dd))
    p_i = int(np.argmax(nav[: t_i + 1])) if t_i > 0 else 0
    worst_i = int(np.argmin(pnl))
    dates = [d.strftime("%Y-%m-%d") for d in panel.index]
    return {
        "obs": n,
        "realized_vol": round(float(pnl.std(ddof=1) * math.sqrt(TRADING_DAYS)), 4) if n > 1 else None,
        "var_1d_95_amt": round(-q * total, 0),
        "es_1d_95_amt": round(es * total, 0),
        "es_1d_95_pct": round(es * 100, 2),
        "worst_day_pct": round(float(pnl[worst_i]) * 100, 2),
        "worst_day_amt": round(float(pnl[worst_i]) * total, 0),
        "worst_day_date": dates[worst_i],
        "max_drawdown_pct": round(float(dd[t_i]) * 100, 2),
        "max_drawdown_amt": round(float(dd[t_i]) * total, 0),     # 按当前账户规模折算
        "mdd_peak_date": dates[p_i],
        "mdd_trough_date": dates[t_i],
        "period_return_pct": round(float(nav[-1] - 1.0) * 100, 2),
        "_nav": nav,
    }


def _historical_replay(inp: _Inputs, rm: _RiskModel, final_w, c) -> Optional[dict]:
    import numpy as np

    panel, fill_share = _replay_panel(inp, rm, c)
    if panel is None:
        return None
    cur = _replay_stats(panel, inp.w, inp.total)
    aft = _replay_stats(panel, final_w, inp.total)
    # 正态 1 日 ES (同口径) 与非参数 ES 之比: >1 说明正态近似低估了尾部
    pv = math.sqrt(max(float(inp.w @ rm.cov @ inp.w), 0.0)) / math.sqrt(TRADING_DAYS)
    normal_es_1d = ES95_MULT * pv * inp.total
    tail_mult = round(cur["es_1d_95_amt"] / normal_es_1d, 2) if normal_es_1d > 0 else None
    step = max(1, len(panel) // 125)                # 降采样到约 125 点供前端画图
    sel = list(range(0, len(panel), step))
    if sel[-1] != len(panel) - 1:
        sel.append(len(panel) - 1)
    path = {
        "dates": [panel.index[i].strftime("%Y-%m-%d") for i in sel],
        "current": [round(float(cur["_nav"][i]), 4) for i in sel],
        "after": [round(float(aft["_nav"][i]), 4) for i in sel],
    }
    cur.pop("_nav")
    aft.pop("_nav")
    return {
        "window": int(len(panel)),
        "start": panel.index[0].strftime("%Y-%m-%d"),
        "end": panel.index[-1].strftime("%Y-%m-%d"),
        "fill_share": round(float(fill_share), 3) if fill_share is not None else None,
        "current": cur, "after": aft,
        "normal_es_1d_95_amt": round(normal_es_1d, 0),
        "tail_multiplier": tail_mult,
        "path": path,
        "note": "按当前权重回放, 不是策略回测: 不含调仓, 假设持仓结构在整个窗口内不变",
    }


def _stress(inp: _Inputs, rm: _RiskModel, final_w, c) -> list:
    import numpy as np

    days = int(c["gap_limit_days"])
    gap_etf = float(c["gap_shock_etf"])
    gap_loss = np.array([gap_etf if is_etf(r["ts_code"])
                         else -(1 - (1 - price_limit_pct(r["ts_code"], r["name"])) ** days) for r in inp.rows])
    scenarios = [
        ("mkt_5", "沪深300 单日 -5%", "大盘恐慌日 (2016-01 熔断量级)", np.clip(rm.beta_mkt * -0.05, -1, 0.5)),
        ("thm_20", "科创50 -20%", "主题级回调 (一年内多次出现)", np.clip(rm.beta_thm * -0.20, -1, 0.5)),
        ("thm_40", "科创50 -40%", "主题熊市 (2021-2024 量级)", np.clip(rm.beta_thm * -0.40, -1, 0.5)),
        ("gap", f"个股{days}连跌停 + ETF {gap_etf * 100:.0f}%", "流动性冻结, 止损无法成交", gap_loss),
    ]
    out = []
    for key, name, desc, shock in scenarios:
        cur = float(inp.w @ shock)
        aft = float(final_w @ shock)
        out.append({
            "key": key, "name": name, "desc": desc,
            "current_pct": round(cur * 100, 2), "current_amt": round(cur * inp.total, 0),
            "after_pct": round(aft * 100, 2), "after_amt": round(aft * inp.total, 0),
        })
    return out


def _diversifiers(inp: _Inputs, rm: _RiskModel, final_w, loader, c) -> list:
    import numpy as np
    import pandas as pd

    min_obs, target_vol = int(c["min_obs"]), float(c["target_vol"])
    after_var = float(final_w @ rm.cov @ final_w)
    out = []
    for code_d, name_d in (c.get("diversifiers") or []):
        if code_d in inp.codes:
            continue
        try:
            dc = loader(code_d)
        except Exception:
            dc = None
        if dc is None or len(dc) < min_obs:
            continue
        dr_ = _clean_returns(dc, c)
        if len(dr_) < min_obs:
            continue
        sd = float(dr_.std() * math.sqrt(TRADING_DAYS))
        cvec = []
        for code in inp.codes:
            rr = rm.rets.get(code)
            cc = None
            if rr is not None:
                j = pd.concat([rr, dr_], axis=1, join="inner").dropna()
                if len(j) >= min_obs:
                    cc = float(j.corr().iloc[0, 1])
            cvec.append(cc)
        known = [x for x in cvec if x is not None]
        fill = float(np.mean(known)) if known else 0.3
        cvec = np.array([x if x is not None else fill for x in cvec])
        sample_corr = None
        if after_var > 0 and sd > 0:
            sample_corr = float(final_w @ (rm.vols * sd * cvec)) / (sd * math.sqrt(after_var))
        floor_c = float(c["stress_corr_floor"])
        cov_d = rm.vols * sd * np.maximum(cvec, floor_c)     # 用压力相关定规模
        b1 = float(final_w @ cov_d)
        a = sd ** 2
        theme_now = float(final_w.sum())
        frontier = []
        for k in (1.0, 0.85, 0.70, 0.55):
            var_k = k * k * after_var
            b = k * b1
            disc = b * b - a * (var_k - target_vol ** 2)
            room = max(0.0, (-b + math.sqrt(disc)) / a) if disc >= 0 and a > 0 else 0.0
            room = min(room, max(0.0, 1.0 - k * theme_now))
            frontier.append({
                "theme_pct": round(k * theme_now * 100, 1),
                "add_pct": round(room * 100, 1),
                "total_pct": round((k * theme_now + room) * 100, 1),
            })
        out.append({
            "ts_code": code_d, "name": name_d, "vol": round(sd, 4),
            "corr_to_portfolio": round(sample_corr, 3) if sample_corr is not None else None,
            "stress_corr_floor": floor_c,
            "short_sample": len(dr_) < 250,
            "frontier": frontier,
            "max_add_pct": frontier[-1]["add_pct"],
            "obs": int(len(dr_)),
        })
    out.sort(key=lambda x: -x["frontier"][1]["add_pct"] if x["frontier"] else 0)
    return out


def _liquidity_and_plan(inp: _Inputs, rm: _RiskModel, cons, reb, amount_loader, c):
    import numpy as np
    import pandas as pd

    adv = {}
    if amount_loader is not None:
        for r in inp.rows:
            try:
                a = amount_loader(r["ts_code"])
            except Exception:
                a = None
            if a is not None and len(a) >= 5:
                v = float(pd.Series(a).tail(20).median())
                if math.isfinite(v) and v > 0:
                    adv[r["ts_code"]] = v
    part = float(c["participation_rate"])
    w, final_w = inp.w, reb["final_w"]
    mcr_now = (rm.cov @ w) / cons["port_vol"] if cons["port_vol"] > 0 else np.zeros(len(w))
    plan = []
    for i, r in enumerate(inp.rows):
        cut = w[i] - final_w[i]
        if cut > 1e-6:
            amt = cut * inp.total
            a = adv.get(r["ts_code"])
            plan.append({
                "ts_code": r["ts_code"], "name": r["name"],
                "from_pct": round(w[i] * 100, 2), "to_pct": round(final_w[i] * 100, 2),
                "reduce_amount": round(amt, 0),
                "cap_part_amount": round(max(0.0, w[i] - cons["caps"][i]) * inp.total, 0),
                "mcr": round(float(mcr_now[i]), 4),
                "vol_source": rm.sources[i],
                "adv_amt": round(a, 0) if a else None,
                "adv_participation_pct": round(amt / a * 100, 3) if a else None,
                "days_at_cap": round(amt / (a * part), 2) if a else None,
            })
    plan.sort(key=lambda x: -x["reduce_amount"])
    max_part = max((t["adv_participation_pct"] or 0) for t in plan) if plan else 0.0
    liquidity = {
        "participation_rate": part,
        "max_participation_pct": round(max_part, 3),
        "max_days_at_cap": max((t["days_at_cap"] or 0) for t in plan) if plan else 0,
        "covered": sum(1 for t in plan if t["adv_amt"]),
        "total": len(plan),
    }
    return plan, liquidity, adv


def _vol_range(inp: _Inputs, rm: _RiskModel, c) -> Optional[dict]:
    import numpy as np

    if not any(sv == "proxy" for sv in rm.sources):
        return None
    band = float(c["proxy_vol_band"])
    rng = []
    for f in (1 - band, 1 + band):
        v2 = np.array([v * f if sv == "proxy" else v for v, sv in zip(rm.vols, rm.sources)])
        c2 = np.outer(v2, v2) * rm.corr
        rng.append(math.sqrt(max(float(inp.w @ c2 @ inp.w), 0.0)))
    return {"low": round(min(rng), 4), "high": round(max(rng), 4), "band": band}


def _risk_by_bucket(inp: _Inputs, rc) -> list:
    agg = {}
    for i, r in enumerate(inp.rows):
        b = risk_bucket(r["ts_code"])
        a = agg.setdefault(b, {"weight": 0.0, "risk": 0.0, "count": 0})
        a["weight"] += float(inp.w[i])
        a["risk"] += float(rc[i])
        a["count"] += 1
    out = []
    for key, label in BUCKETS:
        if key in agg:
            a = agg[key]
            out.append({
                "key": key, "label": label, "count": a["count"],
                "weight_pct": round(a["weight"] * 100, 2),
                "risk_share": round(a["risk"], 4),
                "risk_per_weight": round(a["risk"] / (a["weight"] / inp.invested), 2)
                if a["weight"] > 0 and inp.invested > 0 else None,
            })
    return out


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def compute_portfolio_vol(
    positions: Mapping[str, Mapping[str, Any]],
    total_asset: float,
    price_loader: Optional[Callable[[str], Any]] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    amount_loader: Optional[Callable[[str], Any]] = None,
    asof: Any = None,
) -> dict:
    """计算组合层波动预算.

    Args:
        positions:     {ts_code: {"name", "broker_market_value" 或 "market_value"}}
        total_asset:   账户总资产 (含现金)
        price_loader:  ts_code → 收盘价 Series; 缺省读 data_lake/daily_prices
        cfg:           覆盖参数
        amount_loader: ts_code → 成交额 Series (元); 缺省与 price_loader 一起读本地文件
        asof:          估值日 (判定行情是否过期); 缺省今天

    Returns: dict, 关键字段
        portfolio_vol / sleeve_vol / invested_pct / max_equity_pct / equity_excess_pp
        effective_bets / risk_concentration_n / avg_corr
        positions          每个持仓: 权重/波动/上限/超限/风险贡献/β/行情日
        risk_by_bucket     科创/创业/主板/ETF 的权重与风险贡献
        trim_plan          推荐草案的逐笔减仓 (含边际风险、成交额参与率)
        trim_compare       等比缩放 vs 最小换手
        pre_trade          执行前 / 执行后的风险读数 (正态近似 VaR/ES)
        replay             历史回放: 非参数 VaR/ES、最差单日、最大回撤、净值路径
        stress             β 线性压力情景 (执行前 / 执行后)
        vol_range          代理波动 ±25% 时的组合波动区间
        data_quality       行情覆盖 / 过期 / 最早行情日
        meta               schema / 计算时间 / 耗时
    """
    import numpy as np

    t0 = time.perf_counter()
    c = _merge_cfg(cfg)
    loader = price_loader or default_price_loader
    if amount_loader is None and price_loader is None:
        amount_loader = default_amount_loader
    if not c.get("enabled", True):
        return {"status": "disabled"}

    inp = _load_inputs(positions, total_asset)
    if inp is None:
        return {"status": "empty", "message": "无持仓或总资产无效"}
    asof_d = _to_date(asof)

    rm = _build_risk_model(inp, loader, c, asof_d)
    cons = _constraints(inp, rm, c)
    reb = _rebalance(inp, rm, cons, c)
    final_w = reb["final_w"]
    n = len(inp.codes)
    w, cov, port_var, port_vol = inp.w, rm.cov, cons["port_var"], cons["port_vol"]

    rc = (w * (cov @ w) / port_var) if port_var > 0 else np.zeros(n)
    div_ratio = float((w @ rm.vols) / port_vol) if port_vol > 0 else 0.0
    risk_concentration_n = float(1.0 / np.sum(rc ** 2)) if port_var > 0 else 0.0

    plan, liquidity, adv = _liquidity_and_plan(inp, rm, cons, reb, amount_loader, c)

    out_pos = []
    for i, r in enumerate(inp.rows):
        weight_pct = w[i] * 100
        over = round(weight_pct - cons["caps_pct"][i], 2)
        ld = rm.last_dates[i]
        out_pos.append({
            "ts_code": r["ts_code"], "name": r["name"],
            "bucket": risk_bucket(r["ts_code"]),
            "weight_pct": round(weight_pct, 2),
            "vol": round(float(rm.vols[i]), 4),
            "vol_source": rm.sources[i],
            "cap_pct": cons["caps_pct"][i],
            "cap_rule": cons["cap_rules"][i],
            "over_cap_pp": over if over > 0 else 0.0,
            "risk_share": round(float(rc[i]), 4),
            "risk_per_weight": round(float(rc[i]) / (w[i] / inp.invested), 2) if w[i] > 0 else None,
            "target_pct": round(float(final_w[i]) * 100, 2),
            "beta_mkt": round(float(rm.beta_mkt[i]), 2),
            "beta_theme": round(float(rm.beta_thm[i]), 2),
            "beta_estimated": rm.beta_estimated[i],
            "adv_amt": round(adv[r["ts_code"]], 0) if r["ts_code"] in adv else None,
            "last_price_date": ld.isoformat() if ld else None,
            "price_stale": rm.stale[i],
            "obs": rm.obs[i],
        })

    invested = inp.invested
    proxy_weight = float(sum(w[i] for i in range(n) if rm.sources[i] == "proxy") / invested) if invested else 0.0
    stale_weight = float(sum(w[i] for i in range(n) if rm.stale[i]) / invested) if invested else 0.0
    status = "partial" if proxy_weight + stale_weight > float(c["proxy_weight_warn"]) else "ok"
    data_dates = [d for d in rm.last_dates if d]
    data_quality = {
        "coverage_pct": round((1 - proxy_weight) * 100, 1),
        "proxy_weight": round(proxy_weight, 3),
        "stale_weight": round(stale_weight, 3),
        "stale_names": [inp.rows[i]["name"] for i in range(n) if rm.stale[i]],
        "proxy_names": [inp.rows[i]["name"] for i in range(n) if rm.sources[i] == "proxy"],
        "price_asof": max(data_dates).isoformat() if data_dates else None,
        "oldest_price_date": min(data_dates).isoformat() if data_dates else None,
        "min_obs": min((o for o, s in zip(rm.obs, rm.sources) if s == "data"), default=0),
        "valuation_date": asof_d.isoformat() if asof_d else None,
    }

    out_pos.sort(key=lambda x: -x["weight_pct"])
    top3 = sorted(out_pos, key=lambda x: -x["risk_share"])[:3]
    now_snap = _risk_snapshot(w, cov, rm.vols, inp.total)
    after_snap = _risk_snapshot(final_w, cov, rm.vols, inp.total)
    untouched = [inp.rows[i]["name"] for i in range(n) if w[i] - final_w[i] <= 1e-6]
    sleeve_vol, target_vol = cons["sleeve_vol"], cons["target_vol"]

    try:
        replay = _historical_replay(inp, rm, final_w, c)
    except Exception as e:                       # 分析层失败不影响约束与结论
        logger.warning("组合波动: 历史回放失败 (非致命): %s", e)
        replay = None

    return {
        "status": status,
        "total_asset": round(inp.total, 2),
        "target_vol": target_vol,
        "portfolio_vol": round(port_vol, 4),
        "vol_range": _vol_range(inp, rm, c),
        "sleeve_vol": round(sleeve_vol, 4),
        "invested_pct": round(invested * 100, 2),
        "max_equity_pct": round(cons["max_equity"] * 100, 2),
        "equity_excess_pp": round(max(0.0, invested - cons["max_equity"]) * 100, 2),
        "avg_corr": round(rm.avg_corr, 3),
        "diversification_ratio": round(div_ratio, 3),
        "effective_bets": round(div_ratio ** 2, 2),
        "risk_concentration_n": round(risk_concentration_n, 2),
        "equity_by_target": {
            f"{int(t * 100)}%": round(min(1.0, t / sleeve_vol) * 100, 1) if sleeve_vol > 0 else 100.0
            for t in (0.12, 0.15, 0.18, 0.22, 0.25, 0.30)
        },
        "proxy_weight": round(proxy_weight, 3),
        "data_quality": data_quality,
        "breach_count": sum(1 for p in out_pos if p["over_cap_pp"] > 0),
        "cap_excess_amount": round(reb["cap_excess_amt"], 0),
        "top_risk": [{"name": p["name"], "risk_share": p["risk_share"]} for p in top3],
        "positions": out_pos,
        "risk_by_bucket": _risk_by_bucket(inp, rc),
        "pre_trade": {"current": now_snap, "after": after_snap},
        "after_trim": {
            "invested_pct": after_snap["invested_pct"],
            "portfolio_vol": round(math.sqrt(max(float(final_w @ cov @ final_w), 0.0)), 4),
            "total_reduce_amount": round(float((w - final_w).clip(min=0).sum()) * inp.total, 0),
        },
        "trim_plan": plan,
        "trim_compare": {
            "recommended": "min_turnover" if reb["use_greedy"] else "proportional",
            "rule": f"最小换手需少交易 ≥{float(c['min_turnover_saving']) * 100:.0f}% 才推荐, 否则保持结构",
            "saving_pct": round(reb["saving"] * 100, 1),
            "proportional": {**_risk_snapshot(reb["prop_w"], cov, rm.vols, inp.total),
                             "turnover_amt": round(reb["prop_turnover"], 0)},
            "min_turnover": {**_risk_snapshot(reb["greedy_w"], cov, rm.vols, inp.total),
                             "turnover_amt": round(reb["greedy_turnover"], 0)},
            "untouched": untouched,
        },
        "liquidity": liquidity,
        "replay": replay,
        "diversifiers": _diversifiers(inp, rm, final_w, loader, c),
        "stress": _stress(inp, rm, final_w, c),
        "method": "250日等权波动 + 收缩相关矩阵; 单票上限=min(静态, k/σ, 跌停跳空); 最小换手减仓; 不自动下单",
        "meta": {
            "schema": SCHEMA_VERSION,
            "computed_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        },
    }


# ═══════════════════════════════════════════════════════
#  从持仓文件计算 (带指纹缓存)
# ═══════════════════════════════════════════════════════

_result_cache: dict[str, Any] = {}
_result_lock = threading.Lock()


def _fingerprint(positions, total, cfg, asof) -> str:
    """输入指纹: 持仓市值 + 总资产 + 参数 + 相关行情文件 mtime + 估值日."""
    codes = sorted(positions.keys())
    extra = [cfg.get("market_index"), cfg.get("theme_index")] + [d[0] for d in (cfg.get("diversifiers") or [])]
    payload = {
        "pos": [(k, (positions[k] or {}).get("broker_market_value", (positions[k] or {}).get("market_value")))
                for k in codes],
        "total": total,
        "cfg": {k: v for k, v in cfg.items() if k != "diversifiers"},
        "div": cfg.get("diversifiers"),
        "mtime": [(k, _price_mtime(k)) for k in codes + [e for e in extra if e]],
        "asof": str(asof),
        "schema": SCHEMA_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def compute_from_store(store: Optional[Mapping[str, Any]] = None,
                       price_loader: Optional[Callable[[str], Any]] = None,
                       use_cache: bool = True) -> dict:
    """从 portfolio_store.json (券商导入格式) 计算; 默认行情时按输入指纹缓存."""
    if store is None:
        path = os.path.join(_root(), "data_lake", "portfolio_store.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                store = json.load(f)
        except Exception as e:
            return {"status": "empty", "message": f"持仓文件不可读: {e}"}
    positions = store.get("positions", {}) or {}
    total = store.get("broker_total_asset") or 0
    if not total:
        mv = sum(float(p.get("broker_market_value", 0) or 0) for p in positions.values())
        total = mv + float(store.get("cash", 0) or 0)
    cfg = load_portfolio_vol_config()
    asof = date.today()
    ttl = float(cfg.get("cache_ttl_seconds") or 0)
    cacheable = use_cache and price_loader is None and ttl > 0
    fp = None
    if price_loader is None:
        try:
            fp = _fingerprint(positions, total, cfg, asof)
        except Exception as e:
            logger.debug("组合波动: 指纹计算失败, 不缓存: %s", e)
            cacheable = False
    if cacheable and fp:
        with _result_lock:
            hit = _result_cache.get(fp)
        if hit and time.time() - hit[0] < ttl:
            res = dict(hit[1])
            res["meta"] = {**res.get("meta", {}), "cache": "hit"}
            return res

    result = compute_portfolio_vol(positions, total, price_loader, cfg, asof=asof)
    result["as_of"] = store.get("import_date")
    if isinstance(result.get("meta"), dict):
        result["meta"].update({"fingerprint": fp, "cache": "miss", "positions_asof": store.get("import_date")})
        dq = result.get("data_quality") or {}
        imp = _to_date(store.get("import_date"))
        if imp:
            dq["positions_age_days"] = (asof - imp).days
    if cacheable and fp and result.get("status") in ("ok", "partial"):
        with _result_lock:
            _result_cache.clear()                   # 只保留最新一份
            _result_cache[fp] = (time.time(), result)
    return result


def clear_cache() -> None:
    with _result_lock:
        _result_cache.clear()
    with _frame_lock:
        _frame_cache.clear()


SUMMARY_KEYS = (
    "status", "target_vol", "portfolio_vol", "sleeve_vol", "invested_pct",
    "max_equity_pct", "equity_excess_pp", "effective_bets", "breach_count",
    "top_risk", "as_of",
)


def summarize(result: Mapping[str, Any]) -> Optional[dict]:
    """缓存/风险面板使用的精简版; 无效结果返回 None."""
    if not isinstance(result, Mapping) or result.get("status") not in ("ok", "partial"):
        return None
    return {k: result.get(k) for k in SUMMARY_KEYS}


# ═══════════════════════════════════════════════════════
#  ⑥ 决策视图: 上限瀑布 + 约束来源 + 结论 (决策页面板的唯一数据源)
# ═══════════════════════════════════════════════════════

def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _verdict(gap, effective, portfolio) -> tuple[str, str, str]:
    """总仓位偏离 + 单票超限 → (level, verdict, instruction).

    总仓位在预算内但有持仓超单票上限时, 不能报"在预算内": 单票超限是独立的硬约束。
    """
    breaches = int(_num(portfolio.get("breach_count")) or 0)
    cap_amt = _num(portfolio.get("cap_excess_amount"))
    cap_txt = f" (合计约 ¥{cap_amt / 10000:.1f}万)" if cap_amt else ""
    if gap is None:
        return "unknown", "数据不足", "无法判定: 缺少持仓或上限数据"
    if gap > 10:
        rec = (portfolio.get("trim_compare") or {}).get("recommended")
        how = ("再优先卖出边际风险最高的持仓 (最小换手)" if rec == "min_turnover"
               else "再整体等比缩放, 保持结构")
        return ("danger", f"超出风险预算 {gap:.0f}pp",
                f"禁止加仓; 按减仓草案分 3–5 个交易日降至 {effective:.0f}% 以内: "
                f"先压超单票上限的持仓, {how}")
    if gap > 5:
        return "warning", f"略超预算 {gap:.0f}pp", f"暂停加仓; 择机减至 {effective:.0f}% 以内"
    if breaches:
        return ("warning", f"总仓位在预算内 · {breaches} 只超单票上限",
                f"超限持仓禁止加仓; 把超出上限的部分降到上限{cap_txt}, 总仓位可维持")
    if gap >= -5:
        return "ok", "在预算内", "维持; 单票按上限管理"
    return "room", f"低于上限 {-gap:.0f}pp", "存在加仓空间, 但上限不是目标: 加仓需 JCS/信号确认"


def build_decision_view(market: Optional[Mapping[str, Any]],
                        portfolio: Optional[Mapping[str, Any]],
                        aiae_ctx: Optional[Mapping[str, Any]],
                        enforce: Optional[bool] = None,
                        drawdown: Optional[Mapping[str, Any]] = None) -> dict:
    """把三层约束合成一个可执行结论.

    上限瀑布:
      AIAE 矩阵上限 (base_cap)
        × 市场尾部刹车系数              → 波动调整后上限
        ∧ 组合波动预算 (目标/结构波动)
        ∧ 组合回撤刹车 (可选, 仅在分档触发时) → 有效上限 = 取最严
      vs 实际仓位 → 偏离 → 结论 (同时检查单票上限)

    原则: 上限是天花板, 不是目标。低于上限不构成买入理由, 加仓仍需信号确认。
    """
    market = dict(market or {})
    portfolio = dict(portfolio or {})
    ctx = dict(aiae_ctx or {})
    if enforce is None:
        enforce = bool(load_portfolio_vol_config().get("enforce_in_compliance", False))

    factor = _num(market.get("factor"))
    factor = 1.0 if factor is None else factor
    aiae_locked = ctx.get("decision_locked") is not False or _num(ctx.get("cap")) is None
    base_cap = None if aiae_locked else _num(ctx.get("base_cap", ctx.get("cap")))
    vol_adj_cap = None if base_cap is None else round(min(95.0, base_cap * factor), 1)
    pf_ok = portfolio.get("status") in ("ok", "partial")
    pf_cap = _num(portfolio.get("max_equity_pct")) if pf_ok else None
    actual = _num(portfolio.get("invested_pct")) if pf_ok else None

    candidates = {}
    if vol_adj_cap is not None:
        candidates["aiae_vol"] = vol_adj_cap
    if pf_cap is not None:
        candidates["portfolio_budget"] = pf_cap
    dd = dict(drawdown or {})
    dd_cap = _num(dd.get("cap_pct")) if dd.get("tier") else None
    if dd_cap is not None:
        candidates["drawdown_brake"] = dd_cap
    binding = min(candidates, key=candidates.get) if candidates else None
    effective = round(candidates[binding], 1) if binding else None

    steps = [
        {"key": "aiae", "label": "AIAE 矩阵上限", "value": base_cap,
         "note": f"R{ctx.get('regime')} {ctx.get('regime_cn') or ''}".strip() if base_cap is not None else "AIAE 锁定/缺失"},
        {"key": "market", "label": "× 市场尾部刹车", "value": vol_adj_cap,
         "note": f"系数 {factor:.2f}" + (" (数据过期, 保守)" if market.get("status") == "stale"
                                        else " (数据缺失, 保守)" if market.get("status") == "missing"
                                        else " (刹车中)" if factor < 1 else " (未触发)")},
        {"key": "portfolio", "label": "∧ 组合波动预算", "value": pf_cap,
         "note": (f"目标 {portfolio.get('target_vol', 0) * 100:.0f}% ÷ 结构波动 {portfolio.get('sleeve_vol', 0) * 100:.0f}%"
                  if pf_cap is not None else "无持仓数据")},
        *([{"key": "drawdown", "label": "∧ 组合回撤刹车", "value": dd_cap,
            "note": (f"净值回撤 {abs(_num(dd.get('dd')) or 0) * 100:.1f}% · {dd.get('label') or ''}" if dd_cap is not None
                     else f"净值回撤 {abs(_num(dd.get('dd')) or 0) * 100:.1f}%, 未触发")}] if dd else []),
        {"key": "effective", "label": "= 有效上限", "value": effective, "note": "取最严约束"},
        {"key": "actual", "label": "实际仓位", "value": actual,
         "note": f"截至 {portfolio.get('as_of')}" if portfolio.get("as_of") else ""},
    ]

    gap = round(actual - effective, 1) if actual is not None and effective is not None else None
    level, verdict, instruction = _verdict(gap, effective, portfolio)

    binding_label = {"aiae_vol": "AIAE × 市场刹车", "portfolio_budget": "组合波动预算",
                     "drawdown_brake": "组合回撤刹车"}.get(binding, "—")
    target = _num(portfolio.get("target_vol"))
    caveats = []
    if not enforce:
        caveats.append(f"目标波动 {target * 100:.0f}% 为默认值, 合规层仅软警告; 在投资政策中确认后可开启硬阻断"
                       if target is not None else "组合波动预算未启用硬阻断")
    dq = portfolio.get("data_quality") or {}
    if portfolio.get("status") == "partial":
        caveats.append(f"{portfolio.get('proxy_weight', 0) * 100:.0f}% 的持仓缺少行情、"
                       f"{(dq.get('stale_weight') or 0) * 100:.0f}% 行情过期, 结果偏粗")
    elif dq.get("stale_names"):
        caveats.append(f"行情过期: {'、'.join(dq['stale_names'][:5])} (最后行情日明显早于估值日), "
                       f"波动与相关性仍按历史估计, 但最新走势未计入")
    if (dq.get("positions_age_days") or 0) > 3:
        caveats.append(f"持仓快照已 {dq['positions_age_days']} 天未更新, 实际仓位可能已变化; 请重新导入")
    if market.get("status") in ("stale", "missing"):
        caveats.append(market.get("reason") or "市场波动数据不可用, 已保守处理")
    if aiae_locked:
        caveats.append("AIAE 决策锁定或缺失, 有效上限仅由组合波动预算决定")
    replay = portfolio.get("replay") or {}
    tm = _num(replay.get("tail_multiplier"))
    if tm and tm > 1.15:
        caveats.append(f"历史回放的 1 日 ES 是正态近似的 {tm:.1f} 倍: 尾部比波动率显示的更厚")

    return {
        "status": "ok" if effective is not None else "insufficient",
        "schema": SCHEMA_VERSION,
        "verdict": {"level": level, "text": verdict, "instruction": instruction,
                    "binding": binding, "binding_label": binding_label,
                    "enforced": bool(enforce)},
        "waterfall": steps,
        "effective_cap_pct": effective,
        "actual_pct": actual,
        "gap_pp": gap,
        "market": {k: market.get(k) for k in (
            "status", "factor", "ratio", "trigger_ratio", "sigma_hat", "baseline",
            "brake_on", "trade_date", "index_code", "reason", "vol_pct")},
        "portfolio": portfolio,
        "caveats": caveats,
        "method": [
            "市场层: 沪深300 波动 ≥ 2 倍自适应基准才刹车 (回测: 连续波动择时在 A 股无效, 尾部刹车成本≈0)",
            "组合层: 250 日波动 + 收缩相关矩阵; 最大仓位 = 目标波动 / 结构波动",
            "单票: min(静态上限, k/σ, 两个跌停损失 ≤ 账户 2%); 单票超限独立于总仓位判定",
            "VaR/ES: 正态近似 + 历史回放 (当前权重回放 250 日, 缺口用 β×科创50 填充) 两种口径并列",
            "压力情景: β 线性冲击, 未计跌停无法成交的连锁损失",
            "减仓: 同时计算等比缩放与最小换手两种草案; 最小换手需少交易 ≥15% 才推荐, 否则保持结构",
            "再配置: 在目标波动内求解可加入的低相关资产上限; 相关性按 max(样本, 0.3) 的压力假设定规模",
            "只读视图, 不自动下单",
        ],
    }
