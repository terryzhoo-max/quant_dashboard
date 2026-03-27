import tushare as ts
from datetime import datetime

ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
pro = ts.pro_api()
today_str = datetime.now().strftime('%Y%m%d')
df = pro.moneyflow_hsgt(start_date='20260301', end_date=today_str, limit=5)
print(df)
