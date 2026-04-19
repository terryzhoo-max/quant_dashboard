import tushare as ts
from config import TUSHARE_TOKEN
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# try index_dailybasic for CSI All Share (000985.CSI) or SSE (000001.SH)
try:
    df = pro.index_dailybasic(ts_code='000985.CSI', start_date='20230101', end_date='20230110')
    if df is not None and not df.empty:
        print("000985.CSI:")
        print(df[['trade_date', 'total_mv']])
except Exception as e:
    print(e)
    
try:
    df = pro.index_dailybasic(ts_code='000002.SH', start_date='20230101', end_date='20230110')
    if df is not None and not df.empty:
        print("000002.SH (A股指数):")
        print(df[['trade_date', 'total_mv']])
except Exception as e:
    print(e)
