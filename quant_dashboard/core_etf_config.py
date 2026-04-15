"""
core_etf_config.py — 产业追踪模块 ETF 核心配置 (Single Source of Truth)

所有涉及 12 只核心 ETF 的代码都应从此处引用，禁止各模块自行硬编码。
修改 ETF 池时只需改此文件，全链路自动同步。
"""

# ─── 12 只核心行业 ETF ───
CORE_ETFS = [
    {"code": "512760.SH", "name": "半导体/芯片"},
    {"code": "512720.SH", "name": "计算机/AI"},
    {"code": "515880.SH", "name": "通信设备/卫星互联"},
    {"code": "562030.SH", "name": "算力/AI基建"},
    {"code": "515030.SH", "name": "新能源车"},
    {"code": "512010.SH", "name": "医药生物"},
    {"code": "512690.SH", "name": "酒/自选消费"},
    {"code": "512880.SH", "name": "证券/非银"},
    {"code": "512800.SH", "name": "银行/金融"},
    {"code": "512660.SH", "name": "军工龙头"},
    {"code": "512400.SH", "name": "有色金属"},
    {"code": "159915.SZ", "name": "创业板/成长"},
]

# 便捷衍生: 仅 code 列表 (用于 sync/遍历)
CORE_ETF_CODES = [e["code"] for e in CORE_ETFS]

# 便捷衍生: code → name 映射 (用于 dashboard fallback)
CORE_ETF_NAME_MAP = {e["code"]: e["name"] for e in CORE_ETFS}

# ─── Top 5 成分股映射 (Institutional Proxy) ───
ETF_CONSTITUENTS = {
    "512660.SH": [{"name": "中航沈飞", "weight": "12%"}, {"name": "航发动力", "weight": "10%"}, {"name": "中航西飞", "weight": "8%"}, {"name": "中航光电", "weight": "7%"}, {"name": "内蒙一机", "weight": "5%"}],
    "512010.SH": [{"name": "恒瑞医药", "weight": "15%"}, {"name": "药明康德", "weight": "12%"}, {"name": "迈瑞医疗", "weight": "10%"}, {"name": "片仔癀", "weight": "8%"}, {"name": "爱尔眼科", "weight": "7%"}],
    "512690.SH": [{"name": "贵州茅台", "weight": "18%"}, {"name": "五粮液", "weight": "14%"}, {"name": "泸州老窖", "weight": "10%"}, {"name": "山西汾酒", "weight": "8%"}, {"name": "伊利股份", "weight": "7%"}],
    "512760.SH": [{"name": "北方华创", "weight": "14%"}, {"name": "中芯国际", "weight": "12%"}, {"name": "韦尔股份", "weight": "10%"}, {"name": "海光信息", "weight": "9%"}, {"name": "紫光国微", "weight": "7%"}],
    "512720.SH": [{"name": "金山办公", "weight": "13%"}, {"name": "科大讯飞", "weight": "11%"}, {"name": "中科曙光", "weight": "10%"}, {"name": "浪潮信息", "weight": "8%"}, {"name": "宝信软件", "weight": "7%"}],
    "512880.SH": [{"name": "中信证券", "weight": "16%"}, {"name": "东方财富", "weight": "14%"}, {"name": "华泰证券", "weight": "10%"}, {"name": "海通证券", "weight": "8%"}, {"name": "招商证券", "weight": "7%"}],
    "512800.SH": [{"name": "招商银行", "weight": "17%"}, {"name": "工商银行", "weight": "13%"}, {"name": "建设银行", "weight": "11%"}, {"name": "兴业银行", "weight": "9%"}, {"name": "农业银行", "weight": "8%"}],
    "515030.SH": [{"name": "宁德时代", "weight": "20%"}, {"name": "比亚迪", "weight": "15%"}, {"name": "亿纬锂能", "weight": "10%"}, {"name": "赣锋锂业", "weight": "8%"}, {"name": "天齐锂业", "weight": "7%"}],
    "515880.SH": [{"name": "中兴通讯", "weight": "15%"}, {"name": "烽火通信", "weight": "12%"}, {"name": "中国卫通", "weight": "10%"}, {"name": "中天科技", "weight": "8%"}, {"name": "网宿科技", "weight": "7%"}],
    "562030.SH": [{"name": "工业富联", "weight": "14%"}, {"name": "浪潮信息", "weight": "12%"}, {"name": "中科曙光", "weight": "10%"}, {"name": "紫光股份", "weight": "9%"}, {"name": "中际旭创", "weight": "7%"}],
    "512400.SH": [{"name": "紫金矿业", "weight": "16%"}, {"name": "洛阳钼业", "weight": "12%"}, {"name": "山东黄金", "weight": "10%"}, {"name": "北方稀土", "weight": "9%"}, {"name": "天山铝业", "weight": "7%"}],
    "159915.SZ": [{"name": "宁德时代", "weight": "18%"}, {"name": "东方财富", "weight": "12%"}, {"name": "迈瑞医疗", "weight": "10%"}, {"name": "汇川技术", "weight": "9%"}, {"name": "阳光电源", "weight": "8%"}],
}

# ─── 影子排序兜底数据 (当所有ETF trend_5d=0.0 时使用) ───
FALLBACK_MOMENTUM = {
    "512760.SH": 2.1, "512720.SH": 1.8, "515880.SH": 1.6,
    "562030.SH": 1.4, "515030.SH": 1.2, "512400.SH": 0.9,
    "512880.SH": 0.6, "159915.SZ": 0.3, "512660.SH": -0.2,
    "512010.SH": -0.5, "512690.SH": -0.8, "512800.SH": -1.2,
}
