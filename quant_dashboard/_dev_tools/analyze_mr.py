import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('mr_optimization_results.json', 'r', encoding='utf-8') as f:
    r = json.load(f)

print('=== Top 10 ===')
for item in r['top10']:
    p = item['params']
    print(
        f"#{item['rank']:2d} N={p['N_trend']:3d} RSI{p['rsi_period']} "
        f"buy={p['rsi_buy']} sell={p['rsi_sell']} "
        f"bias={p['bias_buy']:5.1f} sl={p['stop_loss']:.0%} | "
        f"IS={item['train_alpha']:+6.1f}% "
        f"OOS={item['valid_alpha']:+6.1f}% "
        f"Sharpe={item['valid_sharpe']:.3f} "
        f"DD={item['valid_max_dd']:.1f}% "
        f"Score={item['combined_score']:.4f}"
    )

print()
print('best_params:', r['best_params'])
print('train:', json.dumps(r['best_train'], ensure_ascii=False))
print('valid:', json.dumps(r['best_valid'], ensure_ascii=False))
