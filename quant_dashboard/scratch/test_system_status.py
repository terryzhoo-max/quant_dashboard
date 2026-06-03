# -*- coding: utf-8 -*-
"""
验证 V6.5 系统状态审计 (Tushare 探测强超时与防风暴穿透) 的测试脚本
"""
import sys
import os
import time
import requests
import unittest
from unittest.mock import patch, MagicMock

# 确保能加载包
sys.path.insert(0, '.')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

import tushare.pro.client
from engines import audit_engine

class TestSystemStatusAudit(unittest.TestCase):
    def setUp(self):
        # 每次测试前清空缓存
        audit_engine._TS_CHECK_CACHE = None
        self.original_post = requests.post

    def tearDown(self):
        # 确保全局 Monkey Patch 被恢复
        requests.post = self.original_post

    def test_01_cache_flow(self):
        """测试 120s 冷却缓存是否生效"""
        print("\n--- 1. 测试冷却缓存机制 ---")
        
        # 运行第一次（由于是真实网络探测或本地依赖，应该穿透）
        t0 = time.time()
        r1 = audit_engine.audit_system_status()
        elapsed1 = time.time() - t0
        print(f"首次检测耗时: {elapsed1:.2f}s")
        
        c1 = [c for c in r1['checks'] if c['name'] == 'Tushare API'][0]
        print(f"首次检测 Detail: {c1['detail']}, Score: {c1['score']}, Status: {c1['status']}")
        self.assertNotIn("(缓存读取)", c1['detail'])
        
        # 立即运行第二次，应当走缓存
        t0 = time.time()
        r2 = audit_engine.audit_system_status()
        elapsed2 = time.time() - t0
        print(f"二次检测 (期望命中缓存) 耗时: {elapsed2:.4f}s")
        
        c2 = [c for c in r2['checks'] if c['name'] == 'Tushare API'][0]
        print(f"二次检测 Detail: {c2['detail']}, Score: {c2['score']}, Status: {c2['status']}")
        self.assertIn("(缓存读取)", c2['detail'])
        self.assertEqual(c1['score'], c2['score'])
        self.assertEqual(c1['status'], c2['status'])
        # 缓存命中时耗时应当几乎为 0 毫秒级
        self.assertLess(elapsed2, 0.1)
        
        # 模拟缓存过期，强行把时间戳推移到 130 秒前
        if audit_engine._TS_CHECK_CACHE:
            audit_engine._TS_CHECK_CACHE['timestamp'] -= 130
            
        # 再次运行，应当重新穿透检测
        t0 = time.time()
        r3 = audit_engine.audit_system_status()
        elapsed3 = time.time() - t0
        print(f"三次检测 (期望缓存过期重新穿透) 耗时: {elapsed3:.2f}s")
        c3 = [c for c in r3['checks'] if c['name'] == 'Tushare API'][0]
        self.assertNotIn("(缓存读取)", c3['detail'])

    def test_02_timeout_guard(self):
        """测试 2.5 秒探测超时熔断"""
        print("\n--- 2. 测试 2.5秒 强超时保护 ---")
        
        # 我们 mock 掉实际的 requests.post，使其模拟长挂死
        # 如果 timeout 参数被正确传入，requests.post 遇到 timeout 会直接抛出 Timeout 异常
        # 我们的拦截器 timeout_patched_post 应当能把 timeout 限制在 2.5
        
        def slow_post(url, **kwargs):
            timeout = kwargs.get('timeout')
            print(f"[Mock] 收到请求, timeout={timeout}")
            if timeout is not None:
                # 模拟阻塞 timeout 时间，然后抛出异常
                time.sleep(timeout)
                raise requests.exceptions.Timeout(f"Mocked timeout after {timeout}s")
            else:
                # 若无超时则永久阻塞，以检验是否强设了 timeout
                time.sleep(10)
                raise requests.exceptions.Timeout("Blocked forever without timeout")

        # 临时替换 requests.post 以检测超时传参
        with patch('requests.post', side_effect=slow_post):
            t0 = time.time()
            r = audit_engine.audit_system_status()
            elapsed = time.time() - t0
            print(f"挂死检测实际耗时: {elapsed:.2f}s")
            
            c = [c for c in r['checks'] if c['name'] == 'Tushare API'][0]
            print(f"超时挂死 Detail: {c['detail']}, Score: {c['score']}, Status: {c['status']}")
            
            # 应该在 2.5s 超时 + 少量额外开销内退出
            self.assertLess(elapsed, 4.0, "未能及时在 2.5s (带缓冲) 内退出挂死")
            self.assertEqual(c['status'], 'fail')
            self.assertEqual(c['score'], 0)
            self.assertIn("连接失败", c['detail'])
            
            # 失败后同样应当建立 120s 冷却，防止后续刷新频繁被挂起
            self.assertIsNotNone(audit_engine._TS_CHECK_CACHE)
            self.assertEqual(audit_engine._TS_CHECK_CACHE['score'], 0)
            
            # 二次调用应当瞬间命中 fail 缓存
            t0 = time.time()
            r_cache = audit_engine.audit_system_status()
            elapsed_cache = time.time() - t0
            c_cache = [c for c in r_cache['checks'] if c['name'] == 'Tushare API'][0]
            print(f"二次挂死检测 (命中 fail 缓存) 耗时: {elapsed_cache:.4f}s")
            self.assertIn("(缓存读取)", c_cache['detail'])
            self.assertEqual(c_cache['status'], 'fail')
            self.assertLess(elapsed_cache, 0.05)

    def test_03_monkey_patch_restored(self):
        """测试 patch 在退出后 100% 还原"""
        print("\n--- 3. 测试 Patch 状态还原 ---")
        post_before = requests.post
        audit_engine.audit_system_status()
        post_after = requests.post
        
        self.assertEqual(post_before, post_after, "Monkey patch 未能完全还原")
        print("还原性验证通过")

if __name__ == '__main__':
    # 强制将标准输出切换为 utf-8 以防 Windows 报错
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    unittest.main()
