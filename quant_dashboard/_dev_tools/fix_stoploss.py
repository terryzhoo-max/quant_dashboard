import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('mr_per_regime_params.json','r',encoding='utf-8') as f:
    data = json.load(f)
# 统一 stop_loss 为负数（实盘惯例）
for regime in ['BEAR','RANGE','BULL']:
    for section in ['regimes','summary']:
        sl = abs(data[section][regime]['params']['stop_loss'])
        data[section][regime]['params']['stop_loss'] = -sl
with open('mr_per_regime_params.json','w',encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('stop_loss updated to negative')
with open('mr_per_regime_params.json','r',encoding='utf-8') as f:
    d2 = json.load(f)
for r in ['BEAR','RANGE','BULL']:
    sl_val = d2['regimes'][r]['params']['stop_loss']
    print('  ' + r + ': stop_loss = ' + str(sl_val))
