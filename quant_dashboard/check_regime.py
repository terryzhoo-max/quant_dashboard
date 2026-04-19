import json
with open("aiae_backtest_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)
regimes = data["regime_values"]
from collections import Counter
print("Regime distribution:", Counter(regimes))
