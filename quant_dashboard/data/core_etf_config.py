"""
core_etf_config.py — 产业追踪模块 ETF 核心配置 (Single Source of Truth)

所有涉及核心 ETF 的代码都应从此处引用，禁止各模块自行硬编码。
修改 ETF 池时只需改此文件，全链路自动同步。

V6.0 — 十五五政策规划扩展版 (16只)
  · 剔除: 酒/自选消费 (512690), 银行/金融 (512800)
  · 新增: 人形机器人, 数据要素, 创新药, 工业母机, 新材料, 卫星/商业航天
"""

# ─── 16 只核心行业 ETF (十五五·新质生产力版) ───
CORE_ETFS = [
    # ── 硬科技·芯片算力 ──
    {"code": "512760.SH", "name": "半导体/芯片"},
    {"code": "512720.SH", "name": "计算机/AI"},
    {"code": "562030.SH", "name": "算力/AI基建"},
    # ── 通信·星际 ──
    {"code": "515880.SH", "name": "通信设备/卫星互联"},
    {"code": "159218.SZ", "name": "卫星/商业航天"},
    # ── 智造·装备 ──
    {"code": "562500.SH", "name": "人形机器人/智能制造"},
    {"code": "159663.SZ", "name": "工业母机/自主可控"},
    # ── 新能源·新材料 ──
    {"code": "515030.SH", "name": "新能源车"},
    {"code": "516360.SH", "name": "前沿新材料"},
    {"code": "512400.SH", "name": "有色金属"},
    # ── 生物·医药 ──
    {"code": "512010.SH", "name": "医药生物"},
    {"code": "159992.SZ", "name": "创新药/生物制造"},
    # ── 数字经济 ──
    {"code": "515400.SH", "name": "数据要素/数字经济"},
    # ── 国防·金融·成长 ──
    {"code": "512660.SH", "name": "军工龙头"},
    {"code": "512880.SH", "name": "证券/非银"},
    {"code": "159915.SZ", "name": "创业板/成长"},
]

# 便捷衍生: 仅 code 列表 (用于 sync/遍历)
CORE_ETF_CODES = [e["code"] for e in CORE_ETFS]

# 便捷衍生: code → name 映射
CORE_ETF_NAME_MAP = {e["code"]: e["name"] for e in CORE_ETFS}

# Deprecated compatibility export.  Unverified hand-written weights were removed;
# decision surfaces must use services.industry_constituents instead.
ETF_CONSTITUENTS = {}
