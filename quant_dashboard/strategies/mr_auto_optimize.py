"""
AlphaCore · 均值回归 V4.0 · 60天滚动重优化调度器
==================================================
用法：
  手动触发：python mr_auto_optimize.py
  集成到每日定时任务：在 after_close.bat 中调用

逻辑：
  - 检查 mr_per_regime_params.json 中的 next_optimize_after
  - 若当前日期 >= next_optimize_after，运行三态专属参数搜索
  - 否则打印剩余天数并退出
"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from datetime import datetime
from mr_per_regime_optimizer import run_per_regime_optimization

PARAMS_FILE = "mr_per_regime_params.json"
FORCE_FLAG  = "--force" in sys.argv

def check_needs_reoptimize() -> tuple[bool, int]:
    """
    返回 (是否需要重优化, 距下次优化剩余天数)
    """
    if FORCE_FLAG:
        return (True, 0)
    if not os.path.exists(PARAMS_FILE):
        print("[INFO] mr_per_regime_params.json 不存在，触发首次优化")
        return (True, 0)
    try:
        with open(PARAMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        next_date = pd.to_datetime(data.get("next_optimize_after", "2000-01-01"))
        today     = pd.Timestamp.now()
        remaining = (next_date - today).days
        return (today >= next_date, max(0, remaining))
    except Exception as e:
        print(f"[WARN] 读取参数文件异常：{e}，触发重优化")
        return (True, 0)


def main():
    print("\n" + "="*55)
    print("  AlphaCore MR V4.0 · 60天滚动重优化调度器")
    print(f"  当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*55)

    needs, remaining = check_needs_reoptimize()

    if not needs:
        print(f"\n  ✅ 参数仍在有效期内，距下次优化还有 {remaining} 天")
        print("  （如需强制重优化，运行：python mr_auto_optimize.py --force）\n")
        return

    print("\n  ⚡ 触发参数重优化...")
    if FORCE_FLAG:
        print("  原因：用户手动强制 (--force)")
    else:
        print("  原因：已超过60天有效期")

    # 备份旧参数
    if os.path.exists(PARAMS_FILE):
        backup_name = f"mr_per_regime_params_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        import shutil
        shutil.copy(PARAMS_FILE, backup_name)
        print(f"  [备份] 已保存旧参数至 {backup_name}")

    # 运行优化
    result = run_per_regime_optimization()

    # 写入优化日志
    log_entry = {
        "triggered_at":      datetime.now().isoformat(),
        "trigger_reason":    "force" if FORCE_FLAG else "60-day-schedule",
        "regimes_optimized": list(result.get("regimes", {}).keys()),
        "next_optimize":     result.get("next_optimize_after"),
        "summary":           result.get("summary", {}),
    }
    log_file = "mr_optimize_history.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    print(f"\n  📋 优化日志已追加至 {log_file}")
    print("  ✅ 参数已更新，实盘引擎将在下次调用时自动加载（无需重启服务器）")
    print()


if __name__ == "__main__":
    main()
