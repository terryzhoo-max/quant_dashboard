import sys, subprocess, os
sys.stdout.reconfigure(encoding='utf-8')

files = [
    'main.py',
    'mean_reversion_engine.py',
    'momentum_rotation_engine.py',
    'dividend_trend_engine.py',
    'mr_per_regime_optimizer.py',
    'mr_auto_optimize.py',
]

all_ok = True
for f in files:
    if not os.path.exists(f):
        print(f'SKIP  {f} (not found)')
        continue
    r = subprocess.run([sys.executable, '-m', 'py_compile', f], capture_output=True, text=True)
    if r.returncode == 0:
        print(f'OK    {f}')
    else:
        print(f'ERROR {f}: {r.stderr.strip()}')
        all_ok = False

print()
print('=== RESULT: ' + ('ALL SYNTAX OK' if all_ok else 'SYNTAX ERRORS FOUND') + ' ===')
