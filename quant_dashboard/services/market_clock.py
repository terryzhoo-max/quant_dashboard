"""A 股市场时钟 — 所有"是否开盘 / 交易日 / 盘中盘后"判断的统一时区。

服务器可能运行在任意时区 (例如美国中部时间)。A 股交易时段、交易日和
收盘时点都以北京时间定义, 因此市场判断绝不能使用本机 datetime.now()。
中国不实行夏令时, 固定 UTC+8 即可, 无需依赖 tzdata。

用法: datetime.now(CN_TZ).replace(tzinfo=None)
(保持各模块自己的 datetime 引用, 以兼容测试中对模块 datetime 的 mock)
"""
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def cn_now() -> datetime:
    """当前北京时间 (naive, 便于与项目内既有 naive datetime 比较/运算)。"""
    return datetime.now(CN_TZ).replace(tzinfo=None)
