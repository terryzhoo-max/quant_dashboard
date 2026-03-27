import pandas as pd
import numpy as np

def test_logic():
    # Mock data for 12 ETFs
    comparison_list = []
    names = ["军工", "医药", "白酒", "芯片", "AI", "证券", "银行", "新能车", "传媒", "有色", "主板", "创业板"]
    for i in range(12):
        # Generate some mock returns
        ret_20d = (i - 6) * 2.0  # -12% to +10%
        trend_5d = (i - 4) * 1.5 # -6% to +10.5%
        chg_1d = (i - 8) * 0.5   # -4% to +1.5%
        
        comparison_list.append({
            "name": names[i],
            "change": round(chg_1d, 2),
            "trend_5d": round(trend_5d, 2),
            "ret_20d": ret_20d,
            "status": "up" if chg_1d >= 0 else "down"
        })

    # 1. 计算 RPS (基于 20D 收益率的横向排名)
    comparison_list.sort(key=lambda x: x['ret_20d'])
    for i, item in enumerate(comparison_list):
        item["rps"] = int(((i + 1) / len(comparison_list)) * 100)
    
    # 2. 最终按 5D Trend 降序排列
    comparison_list.sort(key=lambda x: x['trend_5d'], reverse=True)
    
    # Verify
    print(f"Total: {len(comparison_list)}")
    print(f"Top 1 (5D): {comparison_list[0]['name']} | 5D Trend: {comparison_list[0]['trend_5d']}% | RPS: {comparison_list[0]['rps']}")
    print(f"Last 1 (5D): {comparison_list[-1]['name']} | 5D Trend: {comparison_list[-1]['trend_5d']}% | RPS: {comparison_list[-1]['rps']}")
    
    # Check if sorted by 5D
    trends = [s['trend_5d'] for s in comparison_list]
    is_sorted = all(trends[i] >= trends[i+1] for i in range(len(trends)-1))
    print(f"Sorted by 5D: {is_sorted}")

if __name__ == "__main__":
    test_logic()
