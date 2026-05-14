"""
AlphaCore · 策略 CI/CD 管道 V1.0 (P1-3)
==========================================
触发: APScheduler 月度任务 / 手动 API 调用
流程:
  1. 读取当前生产参数 (mr_per_regime_params.json / erp_optimization_results.json)
  2. 运行参数优化 (复用已有优化器)
  3. 用新参数跑回测, 获取 KPI
  4. 质量门检查 (Quality Gate)
  5. A/B 对比 (新参数 vs 旧参数)
  6. 决策: ACCEPT / REJECT / REVIEW
  7. 归档: SQLite ci_runs 表
"""

import json
import os
import uuid
import gc
import traceback
from datetime import datetime
from typing import Dict, Optional

from services.logger import get_logger
from services import db as ac_db

logger = get_logger("ci.pipeline")

# ── 质量门阈值 ──
QUALITY_GATE = {
    "sharpe_min":       0.5,       # Sharpe ≥ 0.5 (生产最低线)
    "max_dd_ceil":      -25.0,     # MaxDD ≤ -25% (百分比)
    "calmar_min":       0.3,       # Calmar ≥ 0.3
    "coverage_min":     15.0,      # 信号覆盖率 ≥ 15%
    "regression_tol":   0.10,      # 回归容忍: Sharpe 下降不超过 10%
    "min_trades":       5,         # 最少交易轮次
}

# 参数文件路径
MR_PARAMS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mr_per_regime_params.json"
)
ERP_PARAMS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "erp_optimization_results.json"
)


def _load_json_safe(path: str) -> dict:
    """安全加载 JSON, 文件不存在返回空 dict"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _check_quality_gate(metrics: dict) -> list:
    """
    对回测指标执行质量门检查
    返回: [{rule, expected, actual, passed}]
    """
    checks = []

    # Sharpe
    sharpe = metrics.get("sharpe", metrics.get("sharpe_ratio", 0))
    checks.append({
        "rule": "Sharpe ≥ {:.1f}".format(QUALITY_GATE["sharpe_min"]),
        "expected": QUALITY_GATE["sharpe_min"],
        "actual": round(sharpe, 3),
        "passed": sharpe >= QUALITY_GATE["sharpe_min"],
    })

    # MaxDD
    max_dd = metrics.get("max_dd", metrics.get("max_drawdown", 0))
    # 统一为百分比 (可能是小数或百分比)
    if isinstance(max_dd, (int, float)) and abs(max_dd) < 1:
        max_dd = max_dd * 100  # 小数 → 百分比
    checks.append({
        "rule": "MaxDD ≥ {:.0f}%".format(QUALITY_GATE["max_dd_ceil"]),
        "expected": QUALITY_GATE["max_dd_ceil"],
        "actual": round(max_dd, 2),
        "passed": max_dd >= QUALITY_GATE["max_dd_ceil"],
    })

    # Calmar
    calmar = metrics.get("calmar", metrics.get("calmar_ratio", 0))
    checks.append({
        "rule": "Calmar ≥ {:.1f}".format(QUALITY_GATE["calmar_min"]),
        "expected": QUALITY_GATE["calmar_min"],
        "actual": round(calmar, 3),
        "passed": calmar >= QUALITY_GATE["calmar_min"],
    })

    # Coverage (仅 MR 策略)
    coverage = metrics.get("coverage", 100)
    if coverage < 100:
        checks.append({
            "rule": "Coverage ≥ {:.0f}%".format(QUALITY_GATE["coverage_min"]),
            "expected": QUALITY_GATE["coverage_min"],
            "actual": round(coverage, 1),
            "passed": coverage >= QUALITY_GATE["coverage_min"],
        })

    return checks


def _compute_ab_decision(old_metrics: dict, new_metrics: dict, gate_results: list) -> str:
    """
    根据质量门 + A/B 对比判定:
    - ACCEPT: 所有质量门通过 + 新参数不劣于旧参数
    - REJECT: 有质量门失败 或 显著退步
    - REVIEW: 边界情况, 需人工审查
    """
    gate_passed = all(g["passed"] for g in gate_results)

    if not gate_passed:
        # 有质量门未通过
        return "REJECT"

    old_sharpe = old_metrics.get("sharpe", old_metrics.get("sharpe_ratio", 0))
    new_sharpe = new_metrics.get("sharpe", new_metrics.get("sharpe_ratio", 0))

    if old_sharpe > 0:
        regression = (old_sharpe - new_sharpe) / old_sharpe
        if regression > QUALITY_GATE["regression_tol"]:
            # 新参数 Sharpe 下降超过容忍度
            return "REJECT"
        elif regression > 0:
            # 轻微下降, 需要人工确认
            return "REVIEW"

    # 新参数不差于旧参数, 且质量门全通过
    return "ACCEPT"


def _build_diff_summary(strategy: str, old_params: dict, new_params: dict) -> str:
    """生成人可读的参数变更摘要"""
    lines = [f"策略: {strategy}", "参数变更:"]
    all_keys = sorted(set(list(old_params.keys()) + list(new_params.keys())))
    changed = 0
    for k in all_keys:
        old_v = old_params.get(k, "N/A")
        new_v = new_params.get(k, "N/A")
        if old_v != new_v:
            lines.append(f"  {k}: {old_v} → {new_v}")
            changed += 1

    if changed == 0:
        lines.append("  (无变更)")
    else:
        lines.append(f"共 {changed} 项变更")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  MR 均值回归 CI (三态分别优化)
# ═══════════════════════════════════════════════════════════

def run_mr_ci(regime: str = None) -> list:
    """
    运行 MR 策略 CI
    如果 regime 为 None, 则全部三态都跑
    返回: [ci_run_dict, ...]
    """
    results = []
    old_data = _load_json_safe(MR_PARAMS_FILE)
    old_regimes = old_data.get("regimes", {})

    regimes_to_run = [regime] if regime else ["BEAR", "RANGE", "BULL"]

    for r in regimes_to_run:
        run_id = str(uuid.uuid4())[:12]
        logger.info("[CI] MR-%s 开始优化 (run_id=%s)", r, run_id)

        try:
            # 读取旧参数
            old_regime = old_regimes.get(r, {})
            old_params = old_regime.get("params", {})
            old_kpi = old_regime.get("train_kpi", old_regime.get("valid_kpi", {}))

            # 调用已有优化器 (内存安全)
            from strategies.mr_per_regime_optimizer import (
                optimize_regime, REGIME_PERIODS, REGIME_GRIDS
            )

            if r not in REGIME_PERIODS:
                logger.warning("[CI] MR-%s: 无对应 REGIME_PERIODS, 跳过", r)
                continue

            new_result = optimize_regime(r, REGIME_PERIODS[r], REGIME_GRIDS[r])
            gc.collect()  # 释放回测 DataFrame

            if not new_result:
                logger.warning("[CI] MR-%s: 优化器返回空结果", r)
                continue

            new_params = new_result.get("params", {})
            new_kpi = new_result.get("valid_kpi", new_result.get("train_kpi", {}))

            # 质量门检查
            gate_results = _check_quality_gate(new_kpi)
            status = _compute_ab_decision(old_kpi, new_kpi, gate_results)

            ci_run = {
                "run_id": run_id,
                "strategy": "mr",
                "regime": r,
                "status": status,
                "old_params": old_params,
                "new_params": new_params,
                "old_metrics": old_kpi,
                "new_metrics": new_kpi,
                "quality_gate": gate_results,
                "diff_summary": _build_diff_summary(f"MR-{r}", old_params, new_params),
            }

            ac_db.save_ci_run(ci_run)
            results.append(ci_run)
            logger.info("[CI] MR-%s 完成: status=%s, sharpe=%.3f",
                        r, status, new_kpi.get("sharpe", 0))

        except Exception as e:
            logger.error("[CI] MR-%s 失败: %s\n%s", r, e, traceback.format_exc())
            ci_run = {
                "run_id": run_id,
                "strategy": "mr",
                "regime": r,
                "status": "ERROR",
                "old_params": {},
                "new_params": {},
                "old_metrics": {},
                "new_metrics": {},
                "quality_gate": [{"rule": "执行", "passed": False, "actual": str(e)}],
                "diff_summary": f"CI 执行异常: {e}",
            }
            ac_db.save_ci_run(ci_run)
            results.append(ci_run)

    return results


# ═══════════════════════════════════════════════════════════
#  ERP 择时 CI
# ═══════════════════════════════════════════════════════════

def run_erp_ci() -> dict:
    """运行 ERP 策略 CI"""
    run_id = str(uuid.uuid4())[:12]
    logger.info("[CI] ERP 开始优化 (run_id=%s)", run_id)

    try:
        old_data = _load_json_safe(ERP_PARAMS_FILE)
        old_params = old_data.get("best_params", {})
        old_kpi = old_data.get("best_out_sample", old_data.get("best_in_sample", {}))

        # 调用 ERP 优化器
        from strategies.erp_backtest_optimizer import run_optimization
        new_result = run_optimization()
        gc.collect()

        if not new_result:
            logger.warning("[CI] ERP: 优化器返回空结果")
            return {"run_id": run_id, "status": "ERROR"}

        new_params = new_result.get("best_params", {})
        new_kpi = new_result.get("best_out_sample", new_result.get("best_in_sample", {}))

        gate_results = _check_quality_gate(new_kpi)
        status = _compute_ab_decision(old_kpi, new_kpi, gate_results)

        ci_run = {
            "run_id": run_id,
            "strategy": "erp",
            "regime": None,
            "status": status,
            "old_params": old_params,
            "new_params": new_params,
            "old_metrics": old_kpi,
            "new_metrics": new_kpi,
            "quality_gate": gate_results,
            "diff_summary": _build_diff_summary("ERP", old_params, new_params),
        }

        ac_db.save_ci_run(ci_run)
        logger.info("[CI] ERP 完成: status=%s", status)
        return ci_run

    except Exception as e:
        logger.error("[CI] ERP 失败: %s\n%s", e, traceback.format_exc())
        ci_run = {
            "run_id": run_id,
            "strategy": "erp",
            "regime": None,
            "status": "ERROR",
            "old_params": {},
            "new_params": {},
            "old_metrics": {},
            "new_metrics": {},
            "quality_gate": [{"rule": "执行", "passed": False, "actual": str(e)}],
            "diff_summary": f"CI 执行异常: {e}",
        }
        ac_db.save_ci_run(ci_run)
        return ci_run


# ═══════════════════════════════════════════════════════════
#  全策略 CI 入口 (月度定时任务调用)
# ═══════════════════════════════════════════════════════════

def run_full_ci() -> dict:
    """
    月度全策略 CI
    按内存安全顺序执行: MR(三态串行) → ERP
    """
    logger.info("═══ 策略 CI/CD 月度管道启动 ═══")
    t0 = datetime.now()

    all_results = {
        "timestamp": t0.isoformat(),
        "mr_results": [],
        "erp_result": None,
        "summary": {},
    }

    # Phase 1: MR 三态 (串行, 每态完成后 gc)
    try:
        mr_runs = run_mr_ci()
        all_results["mr_results"] = mr_runs
    except Exception as e:
        logger.error("[CI] MR 全局异常: %s", e)

    # Phase 2: ERP
    try:
        erp_run = run_erp_ci()
        all_results["erp_result"] = erp_run
    except Exception as e:
        logger.error("[CI] ERP 全局异常: %s", e)

    # 汇总
    total_runs = len(all_results["mr_results"]) + (1 if all_results["erp_result"] else 0)
    accepted = sum(1 for r in all_results["mr_results"] if r.get("status") == "ACCEPT")
    if all_results.get("erp_result", {}).get("status") == "ACCEPT":
        accepted += 1

    elapsed = (datetime.now() - t0).total_seconds()
    all_results["summary"] = {
        "total_runs": total_runs,
        "accepted": accepted,
        "elapsed_seconds": round(elapsed, 1),
    }

    logger.info("═══ CI/CD 月度管道完成: %d/%d ACCEPT · %.0fs ═══",
                accepted, total_runs, elapsed)
    return all_results
