"""
AlphaCore · HF 代理权重 OLS 校准引擎 V1.0
============================================
校准 HF Proxy Engine 的三子指标权重。

方法: OLS 回归 + 走查前检验 + A/B 影子模式
目标: 最大化 R² (HF delta vs 实际 AIAE 月度变化)

V1.0 2026-05-27
"""

import os
import json
import threading
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from services.logger import get_logger

logger = get_logger("hf_calibration")

CACHE_DIR = "data_lake"
CALIBRATION_FILE = os.path.join(CACHE_DIR, "hf_calibration_result.json")

# 当前经验权重 (基线)
BASELINE_WEIGHTS = {"turnover": 0.35, "etf_flow": 0.35, "margin_delta": 0.30}

# 权重约束
WEIGHT_MIN = 0.15
WEIGHT_MAX = 0.50
MIN_SAMPLES = 30


class HFCalibrationEngine:
    """HF 代理权重 OLS 校准引擎"""

    VERSION = "1.0"

    def __init__(self):
        self._last_result = self._load_result()
        logger.info(f"HFCalibrationEngine V{self.VERSION} 初始化")

    def _load_result(self) -> Optional[dict]:
        if os.path.exists(CALIBRATION_FILE):
            try:
                with open(CALIBRATION_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_result(self, result: dict):
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CALIBRATION_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CALIBRATION_FILE)

    # ═══════════════════════════════════════════
    #  数据收集
    # ═══════════════════════════════════════════

    def _collect_data(self) -> Tuple[Optional[list], Optional[list]]:
        """
        收集 X (3子指标归一化值) 和 Y (AIAE 实际变化)。
        
        X 来源: aiae_factor_history.json (因子趋势引擎日频快照)
        Y 来源: aiae_monthly_history / SQLite (月度 AIAE V1)
        """
        factor_file = os.path.join(CACHE_DIR, "aiae_factor_history.json")
        if not os.path.exists(factor_file):
            return None, None

        try:
            with open(factor_file, 'r', encoding='utf-8') as f:
                snapshots = json.load(f)
        except Exception:
            return None, None

        if len(snapshots) < MIN_SAMPLES:
            return None, None

        # 收集 HF proxy 日频缓存
        hf_file = os.path.join(CACHE_DIR, "hf_proxy_cache.json")
        hf_data = {}
        if os.path.exists(hf_file):
            try:
                with open(hf_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    if "breakdown" in cache:
                        hf_data = cache
            except Exception:
                pass

        # 构建 X, Y 数据对
        X_rows = []
        Y_vals = []

        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]
            curr = snapshots[i]

            prev_v1 = prev.get("aiae_v1")
            curr_v1 = curr.get("aiae_v1")

            if prev_v1 is None or curr_v1 is None:
                continue

            # Y = delta AIAE
            y = curr_v1 - prev_v1

            # X = 因子贡献变化
            prev_f = prev.get("factors", {})
            curr_f = curr.get("factors", {})

            x_turnover = (curr_f.get("aiae_simple", {}).get("contribution", 0)
                         - prev_f.get("aiae_simple", {}).get("contribution", 0))
            x_etf = (curr_f.get("fund_position", {}).get("contribution", 0)
                     - prev_f.get("fund_position", {}).get("contribution", 0))
            x_margin = (curr_f.get("margin_heat", {}).get("contribution", 0)
                       - prev_f.get("margin_heat", {}).get("contribution", 0))

            X_rows.append([x_turnover, x_etf, x_margin])
            Y_vals.append(y)

        return X_rows, Y_vals

    # ═══════════════════════════════════════════
    #  OLS 回归 (纯 Python, 无 numpy/scipy 依赖)
    # ═══════════════════════════════════════════

    def _ols_regression(self, X: list, Y: list) -> dict:
        """最小二乘回归 (无截距, 权重约束)"""
        n = len(Y)
        k = len(X[0]) if X else 0

        if n < MIN_SAMPLES or k == 0:
            return {"status": "insufficient_data", "n": n, "min_required": MIN_SAMPLES}

        # XᵀX
        XtX = [[0.0] * k for _ in range(k)]
        for row in X:
            for i in range(k):
                for j in range(k):
                    XtX[i][j] += row[i] * row[j]

        # XᵀY
        XtY = [0.0] * k
        for idx, row in enumerate(X):
            for i in range(k):
                XtY[i] += row[i] * Y[idx]

        # 解 XᵀX β = XᵀY (3×3 直接求解)
        try:
            beta = self._solve_3x3(XtX, XtY)
        except Exception as e:
            return {"status": "singular_matrix", "error": str(e)}

        # 预测值 + 残差
        Y_pred = [sum(X[i][j] * beta[j] for j in range(k)) for i in range(n)]
        residuals = [Y[i] - Y_pred[i] for i in range(n)]

        # R²
        y_mean = sum(Y) / n
        ss_tot = sum((y - y_mean) ** 2 for y in Y)
        ss_res = sum(r ** 2 for r in residuals)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Adjusted R²
        adj_r2 = 1 - (1 - r_squared) * (n - 1) / (n - k) if n > k else r_squared

        # Durbin-Watson
        dw = sum((residuals[i] - residuals[i - 1]) ** 2 for i in range(1, n)) / max(ss_res, 1e-10)

        # 标准误 + t-stat
        mse = ss_res / max(n - k, 1)
        try:
            XtX_inv = self._invert_3x3(XtX)
            se = [math.sqrt(max(mse * XtX_inv[i][i], 0)) for i in range(k)]
            t_stats = [beta[i] / se[i] if se[i] > 1e-10 else 0 for i in range(k)]
        except Exception:
            se = [0] * k
            t_stats = [0] * k

        return {
            "status": "success",
            "n": n,
            "k": k,
            "beta": beta,
            "r_squared": round(r_squared, 4),
            "adj_r_squared": round(adj_r2, 4),
            "durbin_watson": round(dw, 4),
            "se": [round(s, 6) for s in se],
            "t_stats": [round(t, 4) for t in t_stats],
            "mse": round(mse, 6),
        }

    def _solve_3x3(self, A, b):
        """Cramer 法则解 3×3 线性方程组"""
        def det3(m):
            return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                  - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                  + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

        n = len(b)
        if n != 3:
            # 退化到 2×2 或 1×1
            if n == 1:
                return [b[0] / A[0][0]] if A[0][0] != 0 else [0]
            elif n == 2:
                d = A[0][0] * A[1][1] - A[0][1] * A[1][0]
                if abs(d) < 1e-12:
                    return [0, 0]
                return [(b[0] * A[1][1] - b[1] * A[0][1]) / d,
                        (A[0][0] * b[1] - A[1][0] * b[0]) / d]

        D = det3(A)
        if abs(D) < 1e-12:
            raise ValueError("Singular matrix")

        result = []
        for i in range(3):
            M = [row[:] for row in A]
            for j in range(3):
                M[j][i] = b[j]
            result.append(det3(M) / D)
        return result

    def _invert_3x3(self, A):
        """3×3 矩阵求逆"""
        def det3(m):
            return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                  - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                  + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

        D = det3(A)
        if abs(D) < 1e-12:
            raise ValueError("Singular matrix")

        cofactors = [[0.0] * 3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                minor = []
                for r in range(3):
                    if r == i:
                        continue
                    row = []
                    for c in range(3):
                        if c == j:
                            continue
                        row.append(A[r][c])
                    minor.append(row)
                cofactors[i][j] = ((-1) ** (i + j)) * (minor[0][0] * minor[1][1] - minor[0][1] * minor[1][0])

        # 转置 + 除以行列式
        inv = [[cofactors[j][i] / D for j in range(3)] for i in range(3)]
        return inv

    # ═══════════════════════════════════════════
    #  权重归一化 + 钳位
    # ═══════════════════════════════════════════

    def _normalize_weights(self, beta: list) -> dict:
        """将回归系数归一化为权重, 带钳位约束"""
        abs_beta = [abs(b) for b in beta]
        total = sum(abs_beta)

        if total < 1e-10:
            return BASELINE_WEIGHTS.copy()

        raw_w = [b / total for b in abs_beta]

        # 钳位
        clamped = [max(WEIGHT_MIN, min(WEIGHT_MAX, w)) for w in raw_w]

        # 重新归一化
        c_total = sum(clamped)
        final = [w / c_total for w in clamped]

        names = ["turnover", "etf_flow", "margin_delta"]
        return {names[i]: round(final[i], 4) for i in range(len(final))}

    # ═══════════════════════════════════════════
    #  走查前检验
    # ═══════════════════════════════════════════

    def _validate(self, ols_result: dict) -> dict:
        """走查前检验"""
        checks = []

        # 1. R² > 0.15
        r2 = ols_result.get("r_squared", 0)
        checks.append({
            "name": "R² 解释力",
            "value": r2,
            "threshold": 0.15,
            "pass": r2 > 0.15,
            "comment": "HF代理至少应解释15%的AIAE方差" if r2 <= 0.15 else "解释力充分",
        })

        # 2. 所有系数同号 (期望正)
        beta = ols_result.get("beta", [])
        all_positive = all(b >= 0 for b in beta)
        checks.append({
            "name": "系数同向性",
            "value": [round(b, 4) for b in beta],
            "pass": all_positive,
            "comment": "所有因子应与AIAE同向(正)" if not all_positive else "符合经济学约束",
        })

        # 3. DW ∈ [1.5, 2.5]
        dw = ols_result.get("durbin_watson", 2.0)
        checks.append({
            "name": "DW自相关检验",
            "value": dw,
            "threshold": "[1.5, 2.5]",
            "pass": 1.5 <= dw <= 2.5,
            "comment": "残差存在自相关" if dw < 1.5 or dw > 2.5 else "残差独立",
        })

        all_pass = all(c["pass"] for c in checks)

        return {
            "all_pass": all_pass,
            "checks": checks,
            "verdict": "通过" if all_pass else "需人工审查",
        }

    # ═══════════════════════════════════════════
    #  A/B 影子模式对比
    # ═══════════════════════════════════════════

    def _shadow_compare(self, X: list, Y: list, new_weights: dict) -> dict:
        """A/B 对比: 基线权重 vs 新权重的 MAE"""
        base_w = [BASELINE_WEIGHTS["turnover"], BASELINE_WEIGHTS["etf_flow"], BASELINE_WEIGHTS["margin_delta"]]
        new_w = [new_weights["turnover"], new_weights["etf_flow"], new_weights["margin_delta"]]

        mae_base = 0
        mae_new = 0
        n = len(Y)

        for i in range(n):
            pred_base = sum(X[i][j] * base_w[j] for j in range(3))
            pred_new = sum(X[i][j] * new_w[j] for j in range(3))
            mae_base += abs(Y[i] - pred_base)
            mae_new += abs(Y[i] - pred_new)

        mae_base /= max(n, 1)
        mae_new /= max(n, 1)

        improvement = (mae_base - mae_new) / max(mae_base, 1e-10) * 100

        return {
            "mae_baseline": round(mae_base, 6),
            "mae_calibrated": round(mae_new, 6),
            "improvement_pct": round(improvement, 2),
            "recommend_switch": improvement > 5,  # >5% 改善才建议切换
        }

    # ═══════════════════════════════════════════
    #  主入口
    # ═══════════════════════════════════════════

    def calibrate(self) -> dict:
        """执行完整校准流程"""
        logger.info("开始 HF 权重校准...")

        # 1. 收集数据
        X, Y = self._collect_data()
        if X is None or len(X) < MIN_SAMPLES:
            n = len(X) if X else 0
            result = {
                "status": "insufficient_data",
                "n": n,
                "min_required": MIN_SAMPLES,
                "message": f"数据不足: 需 {MIN_SAMPLES} 天, 当前仅 {n} 天",
                "current_weights": BASELINE_WEIGHTS,
                "calibrated_at": datetime.now().isoformat(),
            }
            self._save_result(result)
            logger.info(f"校准中止: 数据不足 ({n}/{MIN_SAMPLES})")
            return result

        # 2. OLS 回归
        ols = self._ols_regression(X, Y)
        if ols["status"] != "success":
            result = {"status": ols["status"], **ols, "current_weights": BASELINE_WEIGHTS,
                      "calibrated_at": datetime.now().isoformat()}
            self._save_result(result)
            return result

        # 3. 归一化权重
        new_weights = self._normalize_weights(ols["beta"])

        # 4. 走查前检验
        validation = self._validate(ols)

        # 5. A/B 影子对比
        shadow = self._shadow_compare(X, Y, new_weights)

        # 6. 综合判定
        if validation["all_pass"] and shadow["recommend_switch"]:
            recommendation = "SWITCH"
            message = f"建议切换到校准权重 (MAE改善 {shadow['improvement_pct']}%)"
        elif validation["all_pass"]:
            recommendation = "HOLD"
            message = "检验通过但改善不显著, 保持经验权重"
        else:
            recommendation = "REVIEW"
            message = "走查前检验未通过, 需人工审查"

        result = {
            "status": "success",
            "n": len(Y),
            "calibrated_at": datetime.now().isoformat(),
            "current_weights": BASELINE_WEIGHTS,
            "calibrated_weights": new_weights,
            "recommendation": recommendation,
            "message": message,
            "ols": {
                "r_squared": ols["r_squared"],
                "adj_r_squared": ols["adj_r_squared"],
                "durbin_watson": ols["durbin_watson"],
                "beta": [round(b, 6) for b in ols["beta"]],
                "t_stats": ols["t_stats"],
            },
            "validation": validation,
            "shadow_compare": shadow,
        }

        self._save_result(result)
        logger.info(f"校准完成: {recommendation} | R²={ols['r_squared']} | 改善={shadow['improvement_pct']}%")
        return result

    def get_latest_result(self) -> Optional[dict]:
        """获取最新校准结果"""
        return self._last_result


# ===== 引擎单例 =====
_cal_instance = None
_cal_lock = threading.Lock()


def get_calibration_engine() -> HFCalibrationEngine:
    global _cal_instance
    if _cal_instance is None:
        with _cal_lock:
            if _cal_instance is None:
                _cal_instance = HFCalibrationEngine()
    return _cal_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  HF Calibration Engine V1.0 · Self-Test")
    print("=" * 60)

    engine = HFCalibrationEngine()

    # 测试 OLS (mock 数据)
    print("\n[1] Mock OLS 回归")
    X_mock = [[0.3, 0.5, 0.2]] * 15 + [[-0.2, -0.4, -0.1]] * 15 + [[0.1, 0.2, 0.3]] * 10
    Y_mock = [0.3 * 0.35 + 0.5 * 0.35 + 0.2 * 0.30 + (i % 3) * 0.01 for i, x in enumerate(X_mock)]

    ols = engine._ols_regression(X_mock, Y_mock)
    print(f"  R² = {ols.get('r_squared', 'N/A')}")
    print(f"  Beta = {[round(b, 4) for b in ols.get('beta', [])]}")
    print(f"  DW = {ols.get('durbin_watson', 'N/A')}")

    # 权重归一化
    if ols.get("beta"):
        w = engine._normalize_weights(ols["beta"])
        print(f"  归一化权重: {w}")
        w_sum = sum(w.values())
        print(f"  权重和: {w_sum:.4f} (应为 1.0)")
        assert abs(w_sum - 1.0) < 0.01, f"权重和 ≠ 1.0: {w_sum}"

    # 走查前检验
    v = engine._validate(ols)
    print(f"\n[2] 走查前检验: {v['verdict']}")
    for c in v["checks"]:
        mark = "✅" if c["pass"] else "❌"
        print(f"  {mark} {c['name']}: {c['value']}")

    # 实际校准 (可能数据不足)
    print(f"\n[3] 实际数据校准")
    result = engine.calibrate()
    print(f"  状态: {result['status']}")
    if result['status'] == 'insufficient_data':
        print(f"  {result['message']}")
    elif result['status'] == 'success':
        print(f"  建议: {result['recommendation']}")
        print(f"  当前权重: {result['current_weights']}")
        print(f"  校准权重: {result['calibrated_weights']}")

    print(f"\n{'='*60}")
