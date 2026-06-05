"""
AlphaCore · 全局锁注册表
========================
所有跨模块共享的 threading.Lock 统一在此定义。
避免同一逻辑锁在多个模块独立创建导致的竞态条件。

V26.1: 从 routers/aiae.py + services/warmup_pipeline.py 合并。
"""
import threading


# ── AIAE 全球报告 L1 缓存写入锁 ──
# 保护 cache_manager 中 "aiae_global_last_update" / "aiae_global_report_data" 的原子读写
# 消费者: routers/aiae.py (API 写入) + services/warmup_pipeline.py (预热写入)
AIAE_GLOBAL_LOCK = threading.Lock()

# ── 策略结果缓存锁 ──
# 保护 cache_manager 中 "strategy_results" 的原子读写
# 消费者: dashboard_builder.py + warmup_pipeline.py + strategy.py
STRATEGY_RESULTS_LOCK = threading.Lock()
