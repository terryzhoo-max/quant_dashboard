import tushare as ts
ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
pro = ts.pro_api()
codes = ["801730.SI", "801150.SI", "801120.SI", "801080.SI", "801750.SI"]
df = pro.index_basic(market='SW')
print(df[df['ts_code'].isin(codes)])
