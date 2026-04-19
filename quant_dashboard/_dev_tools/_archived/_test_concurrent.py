import asyncio
import time
from main import _build_dashboard_data_full

async def run_test():
    t0 = time.time()
    print("=== 开始并发预热测试 ===")
    res = await _build_dashboard_data_full()
    t1 = time.time()
    print("========================")
    print(f"预热总耗时: {t1 - t0:.2f} 秒")
    print("========================")
    if isinstance(res, dict):
        print(f"返回状态: {res.get('status')}")
        print(f"数据键值: {list(res.keys())}")
    else:
        print("返回结果不是字典，可能报错了:", res)

if __name__ == "__main__":
    asyncio.run(run_test())
