import pandas as pd
import os

def check_latest_date(file_path):
    if os.path.exists(file_path):
        df = pd.read_parquet(file_path)
        print(f"File: {os.path.basename(file_path)}")
        print(f"Last 5 rows:\n{df.tail()}")
    else:
        print(f"File not found: {file_path}")

if __name__ == "__main__":
    check_latest_date("d:\\FIONA\\google AI\\quant_dashboard\\data_lake\\daily_prices\\000002.SZ.parquet")
