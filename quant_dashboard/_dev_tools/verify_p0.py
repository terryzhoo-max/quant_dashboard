"""P0 归一化修复验证脚本"""

thresholds = {
    "cn": [12.5, 17, 23, 30],
    "us": [15, 20, 27, 34],
    "jp": [10, 14, 20, 28],
    "hk": [8, 12, 18, 25],
}

def norm(v, r):
    t = thresholds[r]
    anchors = [(t[0], 20), (t[1], 40), (t[2], 60), (t[3], 80)]
    if v <= anchors[0][0]:
        return max(0, 20 * v / anchors[0][0]) if anchors[0][0] > 0 else 0
    for i in range(len(anchors) - 1):
        lo_v, lo_n = anchors[i]
        hi_v, hi_n = anchors[i + 1]
        if v <= hi_v:
            return lo_n + (hi_n - lo_n) * (v - lo_v) / (hi_v - lo_v)
    return min(100, 80 + 20 * (v - anchors[-1][0]) / max(anchors[-1][0] * 0.3, 1))

print("=== P0 Normalization Verification ===")
print(f"CN neutral(20): {norm(20, 'cn'):.1f}")
print(f"US neutral(23.5): {norm(23.5, 'us'):.1f}")
print(f"JP neutral(17): {norm(17, 'jp'):.1f}")
print(f"HK neutral(15): {norm(15, 'hk'):.1f}")
print()

print("=== AIAE=20 in each region (raw same, should differ) ===")
for r in ["cn", "us", "jp", "hk"]:
    print(f"  {r}: AIAE=20% -> temp={norm(20, r):.1f}")
print()

vals = {"cn": 22.0, "us": 25.0, "jp": 17.0, "hk": 14.0}
norms = {r: round(norm(v, r), 1) for r, v in vals.items()}
print(f"=== Cross-region: raw={vals} ===")
print(f"  Normalized: {norms}")
coldest = min(norms, key=norms.get)
hottest = max(norms, key=norms.get)
print(f"  Coldest: {coldest}  Hottest: {hottest}")
print()

# Old behavior: direct comparison
old_coldest = min(vals, key=vals.get)
old_hottest = max(vals, key=vals.get)
print(f"  OLD (raw): Coldest={old_coldest}  Hottest={old_hottest}")
print(f"  NEW (norm): Coldest={coldest}  Hottest={hottest}")
