import tushare as ts
ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
pro = ts.pro_api()
df = pro.index_daily(ts_code="000300.SH", start_date='20250101', limit=5)
print(df)
