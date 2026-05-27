# -*- coding: utf-8 -*-
"""
AIAE 基金仓位自动化抓取调度服务 (同花顺 + AKShare 双通道集成)
=====================================================
主通道：同花顺 H5 API，时效性为 T-1 天，精度高、更新快。
备用通道：AKShare / 乐咕乐股，作为容灾降级数据源。
在每天 16:00 (交易日) 触发执行，更新 data_lake/aiae_fund_position.json，支持延迟退避重试。
"""
import sys
import os
import json
import urllib.request
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engines.aiae_engine import get_aiae_engine

def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 严格使用 ASCII 字符日志输出，防止 Windows 控制台 GBK 编码崩溃
    print(f"[{ts_str}] [{level}] [AIAE_SCHEDULER] {msg}")

def fetch_ths_position() -> dict:
    """从同花顺日频基金仓位估算接口获取数据"""
    url = "https://fund.10jqka.com.cn/quotation/wealth_page/query/v2/fund_pos?timeInterval=ONE_YEAR"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://fund.10jqka.com.cn/ifundapp_web/public/m/FundPosition/dist/index.html"
    }
    
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = response.read().decode("utf-8")
        if not res_data:
            raise ValueError("Tonghuashun response is empty")
        js_obj = json.loads(res_data)
        if js_obj.get("status_code") != 0 or not js_obj.get("data"):
            raise ValueError(f"Tonghuashun API error, code: {js_obj.get('status_code')}")
            
        data = js_obj["data"]
        pos_val_raw = data.get("fundPosPercent")
        if pos_val_raw is None:
            raise ValueError("Tonghuashun fundPosPercent is missing")
        pos_val = round(float(pos_val_raw) * 100, 2)
        
        fund_list = data.get("fundPosList", [])
        if not fund_list:
            raise ValueError("Tonghuashun fundPosList is empty")
            
        latest_item = fund_list[-1]
        raw_date = str(latest_item.get("posDate"))
        if not raw_date or len(raw_date) != 8:
            raise ValueError(f"Tonghuashun date format invalid: {raw_date}")
            
        fmt_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        return {"date": fmt_date, "position": pos_val}

def fetch_lg_position() -> dict:
    """备用通道：从 AKShare / 乐咕乐股接口获取数据"""
    import akshare as ak
    df = ak.fund_stock_position_lg()
    if df is None or df.empty:
        raise ValueError("AKShare fund position returns empty")
        
    latest_record = df.iloc[-1]
    latest_date = str(latest_record['date'])       # 格式: 'YYYY-MM-DD'
    latest_pos = float(latest_record['position'])  # 格式: 浮点数 (如 95.67)
    return {"date": latest_date, "position": latest_pos}

def run_delayed_retry(retry_count: int, delay_seconds: int = 600):
    """开启后台单次守护线程，进行非阻塞延时重试"""
    def _retry_worker():
        _log(f"延时 {delay_seconds} 秒后启动重试任务...")
        time.sleep(delay_seconds)
        _log(f"开始执行第 {retry_count} 次延时重试...")
        update_aiae_fund_position_task(retry_count=retry_count)
        
    t = threading.Thread(target=_retry_worker, daemon=True)
    t.start()

def update_aiae_fund_position_task(retry_count: int = 0):
    """基金仓位自动抓取调度任务 (主备双通道 + 容灾降级)"""
    _log(f"开始执行基金仓位抓取流水线 (重试层级: {retry_count})...")
    
    latest_date = None
    latest_pos = None
    source = "degraded_cache"
    
    # 1. 尝试主通道 (同花顺 API)
    try:
        _log("尝试 [同花顺 API] (主通道)...")
        res = fetch_ths_position()
        latest_date = res["date"]
        latest_pos = res["position"]
        source = "ths_api"
        _log(f"[SUCCESS] 主通道获取成功: {latest_pos}% (日期: {latest_date})")
    except Exception as e:
        _log(f"[WARNING] 主通道抓取异常: {e}", "WARN")
        
        # 2. 尝试备用通道 (AKShare / 乐咕乐股)
        try:
            _log("自动切换到 [AKShare/乐咕乐股] (备用通道)...")
            res = fetch_lg_position()
            latest_date = res["date"]
            latest_pos = res["position"]
            source = "lg_api"
            _log(f"[SUCCESS] 备用通道获取成功: {latest_pos}% (日期: {latest_date})")
        except Exception as lg_err:
            _log(f"[FAIL] 备份通道也抓取失败: {lg_err}", "ERROR")
            
    # 3. 结果处理
    if latest_date is not None and latest_pos is not None:
        try:
            # 校验数据合理性
            if not (50 <= latest_pos <= 100):
                raise ValueError(f"估算仓位 {latest_pos}% 超出合理阈值 [50, 100]")
                
            engine = get_aiae_engine()
            current_date = engine._fund_position_date
            current_pos = engine._fund_position
            
            # 判断是否产生数据更新
            if latest_date != current_date or abs(latest_pos - current_pos) > 0.01:
                _log(f"检测到仓位数据变动: 原 [{current_pos}% ({current_date})] -> 新 [{latest_pos}% ({latest_date})]")
                res_engine = engine.update_fund_position(latest_pos, latest_date, source=source)
                if res_engine.get("success"):
                    _log(f"[SUCCESS] 成功更新数据湖且已落库: {res_engine.get('message')}")
                    # 强制重新加载，确保 API 与计算端点读到最新值
                    engine.refresh()
                else:
                    _log(f"[FAIL] 引擎接口更新失败: {res_engine.get('message')}", "ERROR")
            else:
                _log(f"当前数据湖中基金仓位 [{current_pos}% ({current_date})] 已经是最新，无增量变化")
                
                # 如果获取到的是最新日期，但日期依旧不是今天，且处于定时任务触发时间点，执行延迟重试
                today_str = datetime.today().strftime("%Y-%m-%d")
                if latest_date != today_str and retry_count < 2:
                    _log(f"未检测到今日 ({today_str}) 新数据，已注册 10 分钟后延迟重试")
                    run_delayed_retry(retry_count=retry_count + 1, delay_seconds=600)
                    
            return {"status": "success", "date": latest_date, "position": latest_pos, "source": source}
        except Exception as update_err:
            _log(f"[WARNING] 处理抓取数据时发生异常: {update_err}", "WARN")
            return {"status": "degraded", "error": str(update_err)}
    else:
        _log("[WARNING] 所有抓取通道全部不可用，已安全降级使用本地缓存，不阻塞系统运行", "WARN")
        return {"status": "degraded", "error": "All channels failed"}

if __name__ == "__main__":
    # 本地测试自检
    res = update_aiae_fund_position_task()
    print("Self-test result:", res)
