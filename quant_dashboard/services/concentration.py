"""
AlphaCore · 主题集中度约束 (Theme Concentration V1, 2026-10 P1)
================================================================

问题: 组合波动预算 (portfolio_vol) 回答"总仓位能放多少", 但不回答"放在哪"。
同样 60% 仓位, 若全部是半导体/电子, 一次行业级冲击 (出口管制、景气下行)
就会让所有持仓同向下跌 —— 分散化失效。机构通用做法: 单一主题 ≤ 权益部分的 40%。

规则:
  - 权益基数 = 全部持仓市值 - 固收/现金类
  - 主题占比 = 主题市值 / 权益基数
  - 宽基与固收/现金不受主题上限约束 (本身即分散 / 非权益)
  - 超过 limit (默认 40%) → warning: 禁止新增该主题
  - 超过 danger (默认 60%) → danger: 禁止新增 + 给出减持量

主题归类优先级:
  1. 配置 concentration.theme_overrides {ts_code: 主题}  (用户手工指定, 最高优先)
  2. ETF: 名称关键词
  3. 个股: Tushare stock_basic.industry → 主题映射; 未映射的行业以行业名自成一类
  4. 都没有 → "未分类" (单独列出, 占比 > 10% 时提示补充 override)

说明: 科创50 约六成权重为电子/半导体, 与芯片类 ETF 高度同涨同跌, 归入"半导体电子"。

本模块是纯计算 + 只读诊断, 不下单。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Optional

from services.logger import get_logger

logger = get_logger("ac.concentration")

DEFAULT_CONCENTRATION_CONFIG: dict[str, Any] = {
    "enabled": True,
    "theme_limit_pct": 40.0,        # 单一主题 ≤ 权益部分的 40%
    "theme_danger_pct": 60.0,       # 超过该值视为严重集中
    "exempt_themes": ["宽基指数", "固收现金"],
    "unclassified_warn_pct": 10.0,
    "theme_overrides": {},          # {"688019.SH": "半导体电子"}
}

NON_EQUITY_THEMES = {"固收现金"}

# ETF 名称关键词 → 主题 (按顺序匹配, 先具体后宽泛)
ETF_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("固收现金", ("国债", "政金债", "信用债", "可转债", "城投", "短融", "货币", "债")),
    ("贵金属资源", ("黄金", "白银", "有色", "稀土", "煤炭", "钢铁", "矿业", "能源化工")),
    ("半导体电子", ("芯片", "半导体", "集成电路", "科创", "电子", "通信", "5G")),
    ("军工航天", ("卫星", "军工", "国防", "航天", "航空", "通航")),
    ("电力设备新能源", ("光伏", "新能源", "电池", "储能", "电网", "电力设备", "锂电")),
    ("机器人智能制造", ("机器人", "智能制造", "工业母机", "机床")),
    ("软件互联网", ("软件", "计算机", "人工智能", "云计算", "大数据", "互联网", "传媒", "游戏")),
    ("医药医疗", ("医药", "医疗", "生物", "创新药", "中药")),
    ("大金融", ("证券", "券商", "保险", "金融", "银行")),
    ("消费", ("消费", "酒", "食品", "家电", "旅游", "汽车")),
    ("红利防御", ("红利", "低波", "价值", "公用")),
    ("海外市场", ("恒生", "港股", "香港", "纳指", "纳斯达克", "标普", "日经", "德国", "法国", "中概", "H股")),
    ("宽基指数", ("沪深300", "中证500", "中证1000", "中证2000", "上证50", "上证180", "A500", "A50",
                 "中证800", "创业板", "深证100", "双创", "MSCI")),
]

# Tushare stock_basic.industry → 主题
INDUSTRY_THEME_MAP: dict[str, str] = {
    **{k: "半导体电子" for k in ("半导体", "元器件", "通信设备", "IT设备", "电器仪表")},
    **{k: "软件互联网" for k in ("软件服务", "互联网", "影视音像", "出版业")},
    **{k: "电力设备新能源" for k in ("电气设备", "电源设备")},
    **{k: "军工航天" for k in ("航空", "船舶", "运输设备")},
    **{k: "机器人智能制造" for k in ("专用机械", "机械基件", "工程机械", "机床制造", "轻工机械", "化工机械", "农用机械", "纺织机械")},
    **{k: "贵金属资源" for k in ("黄金", "小金属", "铜", "铝", "铅锌", "普钢", "特种钢", "钢加工", "煤炭开采", "焦炭加工", "石油开采", "矿物制品")},
    **{k: "大金融" for k in ("银行", "证券", "保险", "多元金融")},
    **{k: "医药医疗" for k in ("化学制药", "生物制药", "中成药", "医疗保健", "医药商业")},
    **{k: "消费" for k in ("白酒", "红黄酒", "啤酒", "软饮料", "乳制品", "食品", "家用电器", "服饰", "纺织",
                         "旅游服务", "旅游景点", "酒店餐饮", "百货", "超市连锁", "汽车整车", "汽车配件", "日用化工")},
    **{k: "公用事业" for k in ("新型电力", "火力发电", "水力发电", "供气供热", "水务", "环境保护")},
}


def _merge_cfg(cfg: Optional[Mapping[str, Any]]) -> dict:
    merged = dict(DEFAULT_CONCENTRATION_CONFIG)
    if cfg:
        merged.update({k: v for k, v in cfg.items() if k in merged})
    return merged


def load_concentration_config() -> dict:
    """strategy_runtime.json → concentration (可选段), 缺省用默认值."""
    try:
        from services.strategy_params import load_runtime_config
        return _merge_cfg(load_runtime_config().get("concentration") or {})
    except Exception as e:
        logger.debug("concentration 配置加载失败, 使用默认值: %s", e)
        return _merge_cfg(None)


def default_industry_loader() -> dict[str, str]:
    """data_lake/stock_list.parquet → {ts_code: industry}; 失败返回空 dict."""
    try:
        import pandas as pd
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "data_lake", "stock_list.parquet")
        if not os.path.exists(path):
            return {}
        df = pd.read_parquet(path, columns=["ts_code", "industry"])
        return {str(c): str(i) for c, i in zip(df["ts_code"], df["industry"]) if isinstance(i, str) and i}
    except Exception as e:
        logger.warning("行业表读取失败, 个股将按未分类处理: %s", e)
        return {}


def _is_etf(ts_code: str) -> bool:
    c = (ts_code or "").split(".")[0]
    return c.startswith(("51", "52", "56", "58", "159", "16"))


def classify_theme(ts_code: str, name: str, industry_map: Mapping[str, str],
                   overrides: Mapping[str, str]) -> tuple[str, str]:
    """→ (主题, 归类依据)."""
    if ts_code in overrides and overrides[ts_code]:
        return str(overrides[ts_code]), "override"
    nm = name or ""
    if _is_etf(ts_code):
        for theme, kws in ETF_KEYWORD_RULES:
            if any(k in nm for k in kws):
                return theme, "etf_name"
        return "未分类", "none"
    ind = industry_map.get(ts_code)
    if ind:
        return INDUSTRY_THEME_MAP.get(ind, ind), f"industry:{ind}"
    # 港股 / 其他市场个股: 无 Tushare A 股行业
    if ts_code.endswith(".HK"):
        return "海外市场", "market:HK"
    return "未分类", "none"


def compute_concentration(store: Mapping[str, Any],
                          industry_map: Optional[Mapping[str, str]] = None,
                          cfg: Optional[Mapping[str, Any]] = None,
                          target_equity_pct: Optional[float] = None) -> dict:
    """持仓 → 主题集中度诊断.

    target_equity_pct: 可执行仓位上限 (占总资产 %), 用于计算主题上限金额; None = 按当前权益轮动.
    """
    c = _merge_cfg(cfg)
    if not c.get("enabled", True):
        return {"status": "disabled"}
    positions = (store or {}).get("positions") or {}
    if not positions:
        return {"status": "empty", "message": "无持仓"}
    if industry_map is None:
        industry_map = default_industry_loader()
    overrides = c.get("theme_overrides") or {}

    total_asset = float((store or {}).get("broker_total_asset") or 0)
    rows = []
    for code, p in positions.items():
        mv = float(p.get("broker_market_value", 0) or 0)
        if mv <= 0:
            continue
        theme, basis = classify_theme(code, p.get("name", ""), industry_map, overrides)
        rows.append({"ts_code": code, "name": p.get("name", code), "value": mv, "theme": theme, "basis": basis})
    # 2026-10-23: 总资产以 持仓市值+可用资金 为准 (券商「资产」字段可能漏计当日卖出资金)
    _computed = sum(r["value"] for r in rows) + float((store or {}).get("cash", 0) or 0)
    if _computed > 0:
        total_asset = _computed

    equity = sum(r["value"] for r in rows if r["theme"] not in NON_EQUITY_THEMES)
    if equity <= 0:
        return {"status": "empty", "message": "无权益持仓", "as_of": store.get("import_date")}

    buckets: dict[str, dict] = {}
    for r in rows:
        b = buckets.setdefault(r["theme"], {"theme": r["theme"], "value": 0.0, "members": []})
        b["value"] += r["value"]
        b["members"].append({"ts_code": r["ts_code"], "name": r["name"],
                             "value": round(r["value"], 2), "basis": r["basis"]})

    limit = float(c["theme_limit_pct"])
    danger = float(c["theme_danger_pct"])
    exempt = set(c.get("exempt_themes") or []) | NON_EQUITY_THEMES

    themes = []
    for b in buckets.values():
        is_equity = b["theme"] not in NON_EQUITY_THEMES
        pct_eq = b["value"] / equity * 100 if is_equity else None
        b["members"].sort(key=lambda m: -m["value"])
        themes.append({
            "theme": b["theme"],
            "value": round(b["value"], 2),
            "pct_of_equity": round(pct_eq, 1) if pct_eq is not None else None,
            "pct_of_account": round(b["value"] / total_asset * 100, 1) if total_asset else None,
            "count": len(b["members"]),
            "exempt": b["theme"] in exempt,
            "members": b["members"],
        })
    themes.sort(key=lambda t: -t["value"])

    eq_themes = [t for t in themes if t["pct_of_equity"] is not None]
    w = [t["pct_of_equity"] / 100 for t in eq_themes]
    effective_themes = round(1 / sum(x * x for x in w), 2) if w else None

    constrained = [t for t in eq_themes if not t["exempt"]]
    top = max(constrained, key=lambda t: t["pct_of_equity"]) if constrained else None
    top_pct = top["pct_of_equity"] if top else 0.0

    breaches = [t["theme"] for t in constrained if t["pct_of_equity"] > limit]
    # 主题上限金额 = 限额 × 目标权益规模
    #   目标权益 = min(当前权益, 可执行仓位上限 × 总资产); 无上限时按当前权益 (纯轮动)
    #   与总仓位约束联立求解, 避免 "卖到现金 → 权益缩小 → 占比不降" 的无解建议
    target_equity = equity
    if target_equity_pct is not None and total_asset:
        try:
            target_equity = min(equity, max(0.0, float(target_equity_pct)) / 100 * total_asset)
        except (TypeError, ValueError):
            target_equity = equity
    theme_max_value = trim_value = trim_pct_account = None
    if top:
        theme_max_value = round(limit / 100 * target_equity, 0)
    if top and top_pct > limit:
        trim_value = round(max(0.0, top["value"] - theme_max_value), 0)
        trim_pct_account = round(trim_value / total_asset * 100, 1) if total_asset else None

    if not top:
        level, text, instruction = "ok", "无受约束主题", "维持"
    elif top_pct > danger:
        level = "danger"
        text = f"{top['theme']} 占权益 {top_pct:.0f}% (> {danger:.0f}%)"
        instruction = (f"禁止新增「{top['theme']}」; 该主题上限 {theme_max_value / 10000:.1f} 万"
                       f" ({limit:.0f}% × 目标权益 {target_equity / 10000:.1f} 万), 需减持约"
                       f" {trim_value / 10000:.1f} 万 (占账户 {trim_pct_account}%), 分批执行, 可留现金或转投其他主题")
    elif top_pct > limit:
        level = "warning"
        text = f"{top['theme']} 占权益 {top_pct:.0f}% (> {limit:.0f}%)"
        instruction = (f"禁止新增「{top['theme']}」; 新增资金只投向其他主题"
                       f" (该主题上限 {theme_max_value / 10000:.1f} 万)")
    else:
        level, text, instruction = "ok", f"最大主题 {top['theme']} {top_pct:.0f}%", "在限额内"

    unclassified = next((t for t in themes if t["theme"] == "未分类"), None)
    unclassified_pct = unclassified["pct_of_equity"] if unclassified else 0.0
    caveats = []
    if unclassified_pct and unclassified_pct > float(c["unclassified_warn_pct"]):
        caveats.append(f"{unclassified_pct:.0f}% 的权益未能归类, 请在 strategy_runtime.json → "
                       "concentration.theme_overrides 中补充")
    if not industry_map:
        caveats.append("行业表不可用, 个股归类可能不全")

    return {
        "status": "ok",
        "as_of": (store or {}).get("import_date"),
        "limit_pct": limit,
        "danger_pct": danger,
        "equity_value": round(equity, 2),
        "total_asset": round(total_asset, 2),
        "top_theme": top["theme"] if top else None,
        "top_pct": round(top_pct, 1) if top else None,
        "effective_themes": effective_themes,
        "breaches": breaches,
        "target_equity": round(target_equity, 2),
        "theme_max_value": theme_max_value,
        "trim_value": trim_value,
        "trim_pct_account": trim_pct_account,
        "level": level,
        "text": text,
        "instruction": instruction,
        "themes": themes,
        "caveats": caveats,
    }


def compute_from_store(store: Optional[Mapping[str, Any]] = None,
                       industry_loader: Optional[Callable[[], Mapping[str, str]]] = None,
                       target_equity_pct: Optional[float] = None) -> dict:
    """从 data_lake/portfolio_store.json 计算 (与 portfolio_vol 同一持仓源)."""
    import json
    if store is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "data_lake", "portfolio_store.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                store = json.load(f)
        except Exception as e:
            return {"status": "empty", "message": f"持仓文件不可读: {e}"}
    ind = (industry_loader or default_industry_loader)()
    return compute_concentration(store, ind, load_concentration_config(), target_equity_pct=target_equity_pct)


def summarize(result: Mapping[str, Any]) -> Optional[dict]:
    """面板用精简版 (主题列表只保留前 5 个, 成员只保留名称)."""
    if not isinstance(result, Mapping) or result.get("status") != "ok":
        return None
    keys = ("status", "as_of", "limit_pct", "danger_pct", "top_theme", "top_pct", "effective_themes",
            "breaches", "target_equity", "theme_max_value", "trim_value", "trim_pct_account", "level", "text", "instruction", "caveats")
    out = {k: result.get(k) for k in keys}
    out["themes"] = [
        {"theme": t["theme"], "pct_of_equity": t["pct_of_equity"], "pct_of_account": t["pct_of_account"],
         "count": t["count"], "exempt": t["exempt"], "names": [m["name"] for m in t["members"]][:8]}
        for t in result.get("themes", [])[:5]
    ]
    return out
