import tushare as ts
import pandas as pd
pro = ts.pro_api('5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6')
df = pro.index_daily(ts_code='801730.SI', limit=1)
print("Data for 801730.SI (Electricity Equipment):")
print(df)
