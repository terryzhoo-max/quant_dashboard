"""
AlphaCore Phase N · OpenBB POC 多源数据实验
============================================
独立沙盒脚本 — 零生产代码侵入。
测试 OpenBB 作为 Tushare 备用/补充数据源的可行性。

测试用例:
  1. 沪深300日线 (对标 Tushare index_daily)
  2. VIX 指数 (对标 FRED 直接调用)
  3. FRED M2 货币供应 (对标 fetch_macro.py)

运行: python _dev_tools/openbb_poc.py
输出: _dev_tools/openbb_poc_report.json
"""

import json
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path


def _test_hs300_daily():
    """测试 1: 沪深300 日线 via yfinance"""
    from openbb import obb

    start = time.time()
    try:
        # 雅虎财经的 A 股代码: 000300.SS (上证) 
        result = obb.index.price.historical(
            symbol="000300.SS",
            provider="yfinance",
            start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
            end_date=datetime.now().strftime("%Y-%m-%d"),
        )
        elapsed = round((time.time() - start) * 1000)
        df = result.to_df()

        if df.empty:
            return {"status": "fail", "reason": "DataFrame 为空", "latency_ms": elapsed}

        # 数据质量检查
        rows = len(df)
        latest_close = float(df["close"].iloc[-1])
        latest_date = str(df.index[-1])[:10] if hasattr(df.index[-1], 'strftime') else str(df.index[-1])[:10]

        # 尝试用 Tushare 交叉验证
        price_diff_pct = None
        try:
            import tushare as ts
            pro = ts.pro_api()
            ts_df = pro.index_daily(
                ts_code="000300.SH",
                start_date=(datetime.now() - timedelta(days=10)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                fields="trade_date,close"
            )
            if ts_df is not None and not ts_df.empty:
                ts_close = float(ts_df.sort_values("trade_date").iloc[-1]["close"])
                price_diff_pct = round(abs(latest_close - ts_close) / ts_close * 100, 3)
        except Exception as e:
            price_diff_pct = f"Tushare 验证失败: {e}"

        return {
            "status": "pass",
            "rows": rows,
            "latest_date": latest_date,
            "latest_close": round(latest_close, 2),
            "latency_ms": elapsed,
            "price_diff_vs_tushare_pct": price_diff_pct,
            "columns": list(df.columns),
        }
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return {"status": "fail", "reason": str(e), "latency_ms": elapsed, "traceback": traceback.format_exc()[:500]}


def _test_vix_index():
    """测试 2: VIX 指数 via yfinance"""
    from openbb import obb

    start = time.time()
    try:
        result = obb.index.price.historical(
            symbol="^VIX",
            provider="yfinance",
            start_date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
            end_date=datetime.now().strftime("%Y-%m-%d"),
        )
        elapsed = round((time.time() - start) * 1000)
        df = result.to_df()

        if df.empty:
            return {"status": "fail", "reason": "DataFrame 为空", "latency_ms": elapsed}

        rows = len(df)
        latest_vix = float(df["close"].iloc[-1])
        latest_date = str(df.index[-1])[:10] if hasattr(df.index[-1], 'strftime') else str(df.index[-1])[:10]

        return {
            "status": "pass",
            "rows": rows,
            "latest_date": latest_date,
            "latest_vix": round(latest_vix, 2),
            "latency_ms": elapsed,
        }
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return {"status": "fail", "reason": str(e), "latency_ms": elapsed, "traceback": traceback.format_exc()[:500]}


def _test_macro_m2():
    """测试 3: FRED M2 货币供应 via OpenBB fred provider"""
    from openbb import obb

    # 从 .env 读取 FRED key 并注入 OpenBB
    try:
        import os, sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import FRED_API_KEY
        if FRED_API_KEY:
            obb.user.credentials.fred_api_key = FRED_API_KEY
    except Exception:
        pass  # 无 key 则让测试自然失败

    start = time.time()
    try:
        result = obb.economy.fred_series(
            symbol="M2SL",
            provider="fred",
            start_date=(datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d"),
        )
        elapsed = round((time.time() - start) * 1000)
        df = result.to_df()

        if df.empty:
            return {"status": "fail", "reason": "DataFrame 为空", "latency_ms": elapsed}

        rows = len(df)
        latest_val = float(df.iloc[-1].values[0]) if len(df.columns) > 0 else None

        return {
            "status": "pass",
            "rows": rows,
            "latest_m2_billion": round(latest_val, 1) if latest_val else None,
            "latency_ms": elapsed,
            "columns": list(df.columns),
        }
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        # FRED 可能需要 API key — 尝试备用方法
        try:
            result2 = obb.economy.indicators(
                symbol="M2SL",
                provider="fred",
            )
            elapsed2 = round((time.time() - start) * 1000)
            df2 = result2.to_df()
            return {
                "status": "pass (fallback)",
                "rows": len(df2),
                "latency_ms": elapsed2,
                "note": f"Primary failed ({e}), fallback succeeded",
            }
        except Exception as e2:
            return {"status": "fail", "reason": f"Primary: {e} | Fallback: {e2}", "latency_ms": elapsed, "traceback": traceback.format_exc()[:500]}


def _count_new_packages():
    """统计 OpenBB 引入的新包数量"""
    try:
        import subprocess
        result = subprocess.run(
            ["pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=10
        )
        packages = json.loads(result.stdout)
        openbb_pkgs = [p for p in packages if p["name"].startswith("openbb")]
        return {
            "total_packages": len(packages),
            "openbb_packages": len(openbb_pkgs),
            "openbb_package_names": [p["name"] for p in openbb_pkgs],
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("  AlphaCore Phase N · OpenBB POC 多源数据实验")
    print("=" * 60)
    print()

    report = {
        "timestamp": datetime.now().isoformat(),
        "python_env": {},
        "tests": {},
        "dependency_footprint": {},
        "verdict": "",
    }

    # 环境信息
    import sys
    report["python_env"] = {
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }

    # 测试 1: 沪深300
    print("[1/3] 测试沪深300日线 (yfinance) ...")
    report["tests"]["hs300_daily"] = _test_hs300_daily()
    status1 = report["tests"]["hs300_daily"]["status"]
    print(f"      → {status1}")
    if status1 == "pass":
        t = report["tests"]["hs300_daily"]
        print(f"        {t['rows']} 行 | 最新: {t['latest_close']} ({t['latest_date']}) | {t['latency_ms']}ms")
        if isinstance(t.get("price_diff_vs_tushare_pct"), (int, float)):
            print(f"        Tushare 交叉验证: 价差 {t['price_diff_vs_tushare_pct']}%")

    # 测试 2: VIX
    print("\n[2/3] 测试 VIX 指数 (yfinance) ...")
    report["tests"]["vix_index"] = _test_vix_index()
    status2 = report["tests"]["vix_index"]["status"]
    print(f"      → {status2}")
    if status2 == "pass":
        t = report["tests"]["vix_index"]
        print(f"        {t['rows']} 行 | 最新VIX: {t['latest_vix']} ({t['latest_date']}) | {t['latency_ms']}ms")

    # 测试 3: FRED M2
    print("\n[3/3] 测试 FRED M2 货币供应 ...")
    report["tests"]["macro_m2"] = _test_macro_m2()
    status3 = report["tests"]["macro_m2"]["status"]
    print(f"      → {status3}")

    # 依赖统计
    print("\n[*] 统计依赖包 ...")
    report["dependency_footprint"] = _count_new_packages()
    dep = report["dependency_footprint"]
    if "openbb_packages" in dep:
        print(f"      OpenBB 子包: {dep['openbb_packages']} 个")

    # Go/No-Go 判定
    pass_count = sum(1 for t in report["tests"].values() if "pass" in str(t.get("status", "")))
    total = len(report["tests"])

    if pass_count >= 2:
        report["verdict"] = f"[GO] — {pass_count}/{total} 通过。OpenBB 适合作为备用数据源。建议 Phase O 实现 DataAdapter 抽象层。"
    else:
        report["verdict"] = f"[NO-GO] — 仅 {pass_count}/{total} 通过。维持 Tushare 单一数据源。"

    print(f"\n{'=' * 60}")
    print(f"  判定: {report['verdict']}")
    print(f"{'=' * 60}")

    # 保存报告
    report_path = Path(__file__).parent / "openbb_poc_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
