import tushare as ts
from datetime import datetime

ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
pro = ts.pro_api()

sector_map = {"801730.SI": "电力设备", "801150.SI": "医药生物", "801120.SI": "食品饮料", "801080.SI": "电子", "801750.SI": "计算机"}
try:
    df_sectors = pro.index_daily(ts_code=",".join(sector_map.keys()), start_date='20250101', limit=50)
    print("DataFrame shape:", df_sectors.shape)
    if not df_sectors.empty:
        print(df_sectors.head())
    else:
        print("DataFrame is empty")
except Exception as e:
    print("Error:", e)
