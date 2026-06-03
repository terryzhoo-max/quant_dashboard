# -*- coding: utf-8 -*-
import sys
import os
import time

sys.path.insert(0, '.')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

from engines.audit_engine import audit_system_status, _TS_CHECK_CACHE

print("1. 运行首次检测（真实穿透）：")
t0 = time.time()
r1 = audit_system_status()
print(f"首次检测结束，耗时: {time.time() - t0:.2f}s")
c1 = [c for c in r1['checks'] if c['name'] == 'Tushare API'][0]
print(f"Status: {c1['status']}, Detail: {c1['detail']}, Score: {c1['score']}")

print("\n2. 运行二次检测（预期走缓存）：")
t0 = time.time()
r2 = audit_system_status()
print(f"二次检测结束，耗时: {time.time() - t0:.4f}s")
c2 = [c for c in r2['checks'] if c['name'] == 'Tushare API'][0]
print(f"Status: {c2['status']}, Detail: {c2['detail']}, Score: {c2['score']}")

print("\n3. 模拟超时测试：")
# 为了模拟超时，我们临时把 requests.post 搞坏
import requests
original_post = requests.post

def slow_post(url, **kwargs):
    print(f"[Mock Post] url={url}, kwargs={kwargs}")
    time.sleep(5) # 超过 2.5s
    raise requests.exceptions.Timeout("Mock timeout")

# 这里我们需要把 cache 清空，逼迫它穿透
import engines.audit_engine
engines.audit_engine._TS_CHECK_CACHE = None

# 劫持 requests.post
requests.post = slow_post
try:
    t0 = time.time()
    r3 = audit_system_status()
    print(f"超时检测结束，耗时: {time.time() - t0:.2f}s")
    c3 = [c for c in r3['checks'] if c['name'] == 'Tushare API'][0]
    print(f"Status: {c3['status']}, Detail: {c3['detail']}, Score: {c3['score']}")
finally:
    # 还原
    requests.post = original_post

print("\n4. 验证全局状态恢复：")
print(f"Current requests.post is slow_post? {requests.post == slow_post}")
