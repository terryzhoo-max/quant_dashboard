"""
AlphaCore OMS Slippage Attribution Engine V1.0
===============================================
核心职责:
  1. 两层归因模型 (精确层: 执行偏差 / 估算层: 隔夜缺口+日内漂移)
  2. 自适应 EQS 执行质量评分 (基于自身历史中位数)
  3. 决策→执行自动匹配 (时间窗口+方向)
  4. 历史 Bootstrap (从 trade_history 回填)
  5. 智能诊断规则

数据来源: SQLite (execution_orders + slippage_daily)
价格数据: Tushare (open/close) via FactorDataManager
"""

import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from services.logger import get_logger
from services import db as ac_db

logger = get_logger("ac.slippage")

# ─── 全局单例 ───
_engine_instance = None


def get_slippage_engine():
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SlippageEngine()
    return _engine_instance


def _safe_round(val, n=2):
    try:
        return round(float(val), n)
    except (TypeError, ValueError):
        return 0.0


# ── 交易成本常量 (A股) ──
COMMISSION_RATE = 0.00025   # 佣金万2.5
STAMP_TAX_RATE = 0.001     # 印花税千1 (仅卖出)
TRANSFER_FEE_RATE = 0.00002  # 过户费十万分之2


class SlippageEngine:
    """AlphaCore 滑点归因引擎"""

    MATCH_WINDOW_DAYS = 3   # 决策→执行匹配窗口

    def __init__(self):
        self._dm = None  # lazy init

    @property
    def dm(self):
        if self._dm is None:
            from data_manager import FactorDataManager
            self._dm = FactorDataManager()
        return self._dm

    # ═══════════════════════════════════════════════════
    #  决策快照 (Decision Hub 信号发出时调用)
    # ═══════════════════════════════════════════════════

    def snapshot_decision_point(self, snapshot: dict, action_plan: dict,
                                suggested_position: float):
        """
        当 Decision Hub 生成建议时, 快照当前决策点.
        去重: 同一天+相同仓位建议(±10pp) 不重复创建.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        now_ts = datetime.now().isoformat()

        # 去重检查
        existing = ac_db.get_today_decision_snapshot(today)
        if existing:
            old_pos = existing.get("target_position_pct") or 0
            if abs(old_pos - suggested_position) < 10:
                return  # 今日已有且仓位变化 < 10pp

        # 创建组合级决策快照 (ts_code = PORTFOLIO)
        ac_db.create_execution_order({
            "order_date": today,
            "ts_code": "PORTFOLIO",
            "name": "组合仓位信号",
            "side": "rebalance",
            "decision_time": now_ts,
            "decision_price": snapshot.get("hub_composite", 50),
            "decision_regime": snapshot.get("aiae_regime", 3),
            "decision_jcs": snapshot.get("jcs_score"),
            "target_position_pct": suggested_position,
            "status": "pending",
            "notes": action_plan.get("action_label", ""),
        })
        logger.info("决策快照已创建: pos=%.0f%% regime=%s",
                     suggested_position, snapshot.get("aiae_regime"))

    # ═══════════════════════════════════════════════════
    #  交易执行记录 (买卖成交时调用)
    # ═══════════════════════════════════════════════════

    def record_execution_from_trade(self, ts_code: str, side: str,
                                     exec_price: float, exec_amount: int,
                                     name: str = ""):
        """
        交易成交后调用. 尝试匹配 pending 决策指令,
        匹配不到则创建独立执行记录.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 计算交易成本
        turnover = exec_price * exec_amount
        commission = max(turnover * COMMISSION_RATE, 5.0)  # 最低5元
        tax = turnover * STAMP_TAX_RATE if side == "sell" else 0
        currency = "HKD" if ts_code.endswith(".HK") else "CNY"

        # 获取决策参考价 (前一日收盘)
        decision_price = self._get_prev_close(ts_code)
        arrival_price = self._get_today_open(ts_code)

        order_data = {
            "order_date": today,
            "ts_code": ts_code,
            "name": name,
            "side": side,
            "decision_time": datetime.now().isoformat(),
            "decision_price": decision_price,
            "arrival_price": arrival_price,
            "exec_price": exec_price,
            "exec_amount": exec_amount,
            "exec_time": datetime.now().isoformat(),
            "exec_source": "manual",
            "commission": _safe_round(commission),
            "tax": _safe_round(tax),
            "currency": currency,
            "status": "filled",
        }

        order_id = ac_db.create_execution_order(order_data)

        # 计算归因
        self._compute_attribution(order_id)

        # P0: 触发当日汇总更新
        self.compute_daily_summary(today)

        logger.info("执行记录: %s %s %s@%.3f → order=%s",
                     side, ts_code, exec_amount, exec_price, order_id)

    # ═══════════════════════════════════════════════════
    #  券商导入自动匹配
    # ═══════════════════════════════════════════════════

    def auto_match_from_import(self, import_result: dict):
        """
        从券商 TXT 导入结果中检测仓位变化,
        对比前后持仓差异生成执行记录.
        """
        if not import_result.get("success"):
            return

        try:
            from portfolio_engine import get_portfolio_engine
            # 当前持仓快照已被覆盖, 无法对比差异
            # 仅记录导入事件本身
            today = datetime.now().strftime("%Y-%m-%d")
            count = import_result.get("imported", 0)
            ac_db.create_execution_order({
                "order_date": today,
                "ts_code": "IMPORT",
                "name": f"券商导入 {count} 只持仓",
                "side": "import",
                "exec_amount": count,
                "exec_source": "broker_import",
                "status": "filled",
                "notes": f"可用资金 ¥{import_result.get('cash', 0):,.2f}",
            })
        except Exception as e:
            logger.warning("导入匹配失败: %s", e)

    # ═══════════════════════════════════════════════════
    #  两层归因计算
    # ═══════════════════════════════════════════════════

    def _compute_attribution(self, order_id: str):
        """
        两层归因模型:
          Layer 1 (精确): total_slippage = exec_price - decision_price
          Layer 2 (估算): overnight_gap + intraday_drift = total_slippage

        符号约定:
          买入: exec > decision → 正值 (不利)
          卖出: exec < decision → 正值 (不利)
        """
        order = ac_db.get_execution_order_by_id(order_id)
        if not order or order.get("status") != "filled":
            return

        dp = order.get("decision_price")
        ep = order.get("exec_price")
        ap = order.get("arrival_price")
        amount = order.get("exec_amount") or 0

        if not dp or not ep or dp <= 0:
            return

        side = order.get("side", "buy")

        # Layer 1: 总执行偏差
        if side == "sell":
            raw_slip = (dp - ep) / dp * 10000  # 卖出: 决策价更高=有利
        else:
            raw_slip = (ep - dp) / dp * 10000  # 买入: 成交价更高=不利

        total_bps = _safe_round(raw_slip, 2)
        total_cny = _safe_round(abs(ep - dp) * amount, 2)

        # Layer 2: 隔夜缺口 + 日内漂移 (估算)
        overnight_bps = 0.0
        intraday_bps = 0.0
        if ap and ap > 0:
            if side == "sell":
                overnight_bps = _safe_round((dp - ap) / dp * 10000, 2)
                intraday_bps = _safe_round((ap - ep) / ap * 10000, 2)
            else:
                overnight_bps = _safe_round((ap - dp) / dp * 10000, 2)
                intraday_bps = _safe_round((ep - ap) / ap * 10000, 2)

        # 基准收盘价
        benchmark = self._get_today_close(order.get("ts_code", ""))

        ac_db.update_execution_fill(order_id, {
            "total_slippage_bps": total_bps,
            "total_slippage_cny": total_cny,
            "overnight_gap_bps": overnight_bps,
            "intraday_drift_bps": intraday_bps,
            "benchmark_close": benchmark,
        })

    # ═══════════════════════════════════════════════════
    #  EQS 执行质量评分 (自适应基准)
    # ═══════════════════════════════════════════════════

    def get_execution_quality_score(self, days: int = 30) -> dict:
        """
        EQS = 100 - (recent_avg / adaptive_benchmark * 50)
        自适应基准: 自身近90日滑点中位数 (无历史时默认20bps)
        """
        orders = ac_db.get_execution_orders(days=days)
        # P0: 分离 baseline 和 live 订单
        all_filled = [o for o in orders
                      if o.get("status") == "filled"
                      and o.get("total_slippage_bps") is not None
                      and o.get("ts_code") not in ("PORTFOLIO", "IMPORT")]
        baseline_orders = [o for o in all_filled if o.get("exec_source") == "bootstrap"]
        filled = [o for o in all_filled if o.get("exec_source") != "bootstrap"]

        if not filled:
            return {
                "score": 0, "grade": "--", "has_data": False,
                "avg_slippage_bps": 0, "benchmark_bps": 20,
                "total_cost_cny": 0, "trend": "no_data",
                "order_count": 0, "top_leakers": [],
                "baseline_count": len(baseline_orders),
            }

        slippages = [abs(o["total_slippage_bps"]) for o in filled]
        avg_bps = statistics.mean(slippages)

        # 自适应基准: 近90日中位数, 最低10bps
        all_90 = ac_db.get_execution_orders(days=90)
        all_slips = [abs(o["total_slippage_bps"])
                     for o in all_90
                     if o.get("total_slippage_bps") is not None
                     and o.get("ts_code") not in ("PORTFOLIO", "IMPORT")]
        if len(all_slips) >= 5:
            benchmark = max(10.0, statistics.median(all_slips))
        else:
            benchmark = 20.0  # 冷启动默认

        # EQS 计算
        ratio = avg_bps / benchmark if benchmark > 0 else 1
        eqs = max(0, min(100, round(100 - ratio * 50)))

        # 评级
        if eqs >= 90:
            grade = "A+"
        elif eqs >= 80:
            grade = "A"
        elif eqs >= 65:
            grade = "B"
        elif eqs >= 50:
            grade = "C"
        else:
            grade = "D"

        # 趋势: 近7日 vs 前23日
        recent_7 = [abs(o["total_slippage_bps"]) for o in filled
                     if o.get("order_date", "") >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
        older = [abs(o["total_slippage_bps"]) for o in filled
                 if o.get("order_date", "") < (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
        if recent_7 and older:
            trend = "improving" if statistics.mean(recent_7) < statistics.mean(older) else "deteriorating"
        else:
            trend = "stable"

        total_cost = sum(abs(o.get("total_slippage_cny", 0)) for o in filled)

        # Top leakers (按标的聚合)
        leaker_map = {}
        for o in filled:
            code = o.get("ts_code", "")
            if code not in leaker_map:
                leaker_map[code] = {"ts_code": code, "name": o.get("name", ""),
                                     "slips": [], "cost": 0}
            leaker_map[code]["slips"].append(abs(o["total_slippage_bps"]))
            leaker_map[code]["cost"] += abs(o.get("total_slippage_cny", 0))

        top_leakers = sorted(
            [{"ts_code": v["ts_code"], "name": v["name"],
              "avg_slip_bps": _safe_round(statistics.mean(v["slips"])),
              "total_cost": _safe_round(v["cost"])}
             for v in leaker_map.values()],
            key=lambda x: x["total_cost"], reverse=True
        )[:5]

        return {
            "score": eqs,
            "grade": grade,
            "has_data": True,
            "avg_slippage_bps": _safe_round(avg_bps),
            "benchmark_bps": _safe_round(benchmark),
            "total_cost_cny": _safe_round(total_cost),
            "trend": trend,
            "order_count": len(filled),
            "top_leakers": top_leakers,
        }

    # ═══════════════════════════════════════════════════
    #  归因报告
    # ═══════════════════════════════════════════════════

    def get_attribution_report(self, days: int = 30) -> dict:
        """生成滑点归因分解报告"""
        orders = ac_db.get_execution_orders(days=days)
        filled = [o for o in orders
                  if o.get("status") == "filled"
                  and o.get("total_slippage_bps") is not None
                  and o.get("ts_code") not in ("PORTFOLIO", "IMPORT")]

        if not filled:
            return {"has_data": False, "orders": 0}

        total_overnight = sum(abs(o.get("overnight_gap_bps", 0)) for o in filled)
        total_intraday = sum(abs(o.get("intraday_drift_bps", 0)) for o in filled)
        total_all = total_overnight + total_intraday

        return {
            "has_data": True,
            "orders": len(filled),
            "overnight_gap_pct": _safe_round(total_overnight / total_all * 100 if total_all > 0 else 0),
            "intraday_drift_pct": _safe_round(total_intraday / total_all * 100 if total_all > 0 else 0),
            "avg_overnight_bps": _safe_round(statistics.mean([o.get("overnight_gap_bps", 0) for o in filled])),
            "avg_intraday_bps": _safe_round(statistics.mean([o.get("intraday_drift_bps", 0) for o in filled])),
            "by_side": {
                "buy": self._side_summary([o for o in filled if o.get("side") == "buy"]),
                "sell": self._side_summary([o for o in filled if o.get("side") == "sell"]),
            },
        }

    @staticmethod
    def _side_summary(orders: list) -> dict:
        if not orders:
            return {"count": 0, "avg_bps": 0}
        return {
            "count": len(orders),
            "avg_bps": _safe_round(statistics.mean([o.get("total_slippage_bps", 0) for o in orders])),
        }

    # ═══════════════════════════════════════════════════
    #  智能诊断
    # ═══════════════════════════════════════════════════

    def diagnose(self, days: int = 30) -> list:
        """运行诊断规则, 返回诊断建议列表"""
        orders = ac_db.get_execution_orders(days=days)
        filled = [o for o in orders
                  if o.get("status") == "filled"
                  and o.get("total_slippage_bps") is not None
                  and o.get("ts_code") not in ("PORTFOLIO", "IMPORT")]

        findings = []
        if len(filled) < 3:
            findings.append({
                "rule": "INSUFFICIENT_DATA",
                "severity": "info",
                "title": "数据不足",
                "detail": f"仅有 {len(filled)} 笔成交记录, 需要更多数据才能诊断",
            })
            return findings

        # Rule 1: 延迟过大
        high_overnight = [o for o in filled if abs(o.get("overnight_gap_bps", 0)) > 15]
        if len(high_overnight) >= 3:
            findings.append({
                "rule": "DELAY_CHRONIC",
                "severity": "warning",
                "title": "执行延迟偏大",
                "detail": f"{len(high_overnight)} 笔隔夜缺口 > 15bps, 建议缩短决策到执行窗口",
            })

        # Rule 2: 滑点集中
        leaker_map = {}
        total_cost = sum(abs(o.get("total_slippage_cny", 0)) for o in filled)
        for o in filled:
            code = o.get("ts_code", "")
            leaker_map[code] = leaker_map.get(code, 0) + abs(o.get("total_slippage_cny", 0))
        for code, cost in leaker_map.items():
            if total_cost > 0 and cost / total_cost > 0.4:
                findings.append({
                    "rule": "CONCENTRATION",
                    "severity": "warning",
                    "title": f"滑点集中在 {code}",
                    "detail": f"该标的占总滑点 {cost/total_cost*100:.0f}%, 关注流动性",
                })

        # Rule 3: 趋势改善
        recent = [o for o in filled
                  if o.get("order_date", "") >= (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")]
        older = [o for o in filled
                 if o.get("order_date", "") < (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")]
        if recent and older:
            r_avg = statistics.mean([abs(o.get("total_slippage_bps", 0)) for o in recent])
            o_avg = statistics.mean([abs(o.get("total_slippage_bps", 0)) for o in older])
            if r_avg < o_avg * 0.8:
                findings.append({
                    "rule": "IMPROVING",
                    "severity": "positive",
                    "title": "执行质量改善中 ✅",
                    "detail": f"近10日均值 {r_avg:.1f}bps < 历史 {o_avg:.1f}bps",
                })

        if not findings:
            findings.append({
                "rule": "ALL_CLEAR",
                "severity": "positive",
                "title": "执行质量正常",
                "detail": "未发现系统性问题",
            })

        return findings

    # ═══════════════════════════════════════════════════
    #  日度汇总 (收盘后由调度器调用)
    # ═══════════════════════════════════════════════════

    def compute_daily_summary(self, date: str = None):
        """计算并持久化指定日期的滑点汇总"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        orders = ac_db.get_execution_orders(days=1)
        filled = [o for o in orders
                  if o.get("order_date") == date
                  and o.get("status") == "filled"
                  and o.get("total_slippage_bps") is not None
                  and o.get("ts_code") not in ("PORTFOLIO", "IMPORT")]

        if not filled:
            return

        slippages = [o["total_slippage_bps"] for o in filled]
        turnovers = [abs(o.get("exec_price", 0) * (o.get("exec_amount", 0))) for o in filled]
        total_turn = sum(turnovers)

        # 加权平均滑点
        if total_turn > 0:
            avg_bps = sum(s * t for s, t in zip(slippages, turnovers)) / total_turn
        else:
            avg_bps = statistics.mean(slippages) if slippages else 0

        total_cny = sum(abs(o.get("total_slippage_cny", 0)) for o in filled)

        # 归因占比
        ong = [abs(o.get("overnight_gap_bps", 0)) for o in filled]
        idr = [abs(o.get("intraday_drift_bps", 0)) for o in filled]
        total_attr = sum(ong) + sum(idr)
        ong_pct = sum(ong) / total_attr * 100 if total_attr > 0 else 0
        idr_pct = sum(idr) / total_attr * 100 if total_attr > 0 else 0

        # 最差订单
        worst = max(filled, key=lambda o: abs(o.get("total_slippage_bps", 0)))

        eqs = self.get_execution_quality_score(30).get("score", 0)

        ac_db.upsert_slippage_daily(date, {
            "order_count": len(filled),
            "total_turnover": _safe_round(total_turn),
            "avg_slippage_bps": _safe_round(avg_bps),
            "total_slippage_cny": _safe_round(total_cny),
            "overnight_gap_pct": _safe_round(ong_pct),
            "intraday_drift_pct": _safe_round(idr_pct),
            "worst_order_id": worst.get("order_id"),
            "worst_slippage_bps": worst.get("total_slippage_bps"),
            "eqs_score": eqs,
        })
        logger.info("滑点日汇总: %s · %d笔 · avg=%.1fbps · EQS=%d",
                     date, len(filled), avg_bps, eqs)

    # ═══════════════════════════════════════════════════
    #  Bootstrap (从历史交易回填)
    # ═══════════════════════════════════════════════════

    def bootstrap_from_history(self, days: int = 60) -> dict:
        """从 trade_history 回填历史执行记录 (幂等, 标记 source=bootstrap)"""
        existing = ac_db.get_execution_order_count()
        if existing > 5:
            return {"status": "skip", "message": f"已有 {existing} 条记录, 跳过 bootstrap"}

        trades = ac_db.get_trades(limit=200)
        created = 0
        for t in trades:
            if t.get("action") not in ("buy", "sell"):
                continue
            if not t.get("success"):
                continue

            ts_code = t.get("ts_code", "")
            price = t.get("price", 0)
            if not ts_code or price <= 0:
                continue

            # 用前一日收盘近似决策价
            decision_price = self._get_prev_close_for_date(ts_code, t.get("timestamp", ""))

            ac_db.create_execution_order({
                "order_date": t.get("timestamp", "")[:10],
                "ts_code": ts_code,
                "name": t.get("name", ""),
                "side": t.get("action"),
                "decision_price": decision_price or price,
                "exec_price": price,
                "exec_amount": t.get("amount", 0),
                "exec_time": t.get("timestamp"),
                "exec_source": "bootstrap",
                "status": "filled",
                "notes": "历史回填",
            })
            created += 1

        # 回填归因
        if created > 0:
            for o in ac_db.get_execution_orders(days=days):
                if o.get("exec_source") == "bootstrap" and o.get("total_slippage_bps") is None:
                    self._compute_attribution(o["order_id"])

        # P0: 批量日汇总
        daily_count = 0
        if created > 0:
            dates_set = set()
            for o in ac_db.get_execution_orders(days=days):
                d = o.get("order_date", "")[:10]
                if d:
                    dates_set.add(d)
            for d in sorted(dates_set):
                self.compute_daily_summary(d)
                daily_count += 1
            logger.info("Bootstrap 日汇总: %d 日", daily_count)

        logger.info("Bootstrap 完成: 回填 %d 笔历史交易", created)
        return {"status": "ok", "created": created, "daily_summaries": daily_count}

    # ═══════════════════════════════════════════════════
    #  价格辅助函数
    # ═══════════════════════════════════════════════════

    def _get_prev_close(self, ts_code: str) -> Optional[float]:
        """获取前一交易日收盘价"""
        try:
            df = self.dm.get_price_payload(ts_code)
            if df is not None and not df.empty and len(df) >= 2:
                return float(df['close'].iloc[-2])
        except Exception:
            pass
        return None

    def _get_today_open(self, ts_code: str) -> Optional[float]:
        """获取当日开盘价 (arrival price 近似)"""
        try:
            df = self.dm.get_price_payload(ts_code)
            if df is not None and not df.empty:
                return float(df['open'].iloc[-1])
        except Exception:
            pass
        return None

    def _get_today_close(self, ts_code: str) -> Optional[float]:
        """获取当日收盘价 (benchmark)"""
        try:
            df = self.dm.get_price_payload(ts_code)
            if df is not None and not df.empty:
                return float(df['close'].iloc[-1])
        except Exception:
            pass
        return None

    def _get_prev_close_for_date(self, ts_code: str, date_str: str) -> Optional[float]:
        """获取指定日期前一日的收盘价 (bootstrap 用)"""
        try:
            df = self.dm.get_price_payload(ts_code)
            if df is not None and not df.empty:
                target = date_str[:10].replace("-", "")
                if 'trade_date' in df.columns:
                    mask = df['trade_date'].astype(str) < target
                    prev = df[mask]
                    if not prev.empty:
                        return float(prev['close'].iloc[-1])
                # fallback: 用倒数第二行
                if len(df) >= 2:
                    return float(df['close'].iloc[-2])
        except Exception:
            pass
        return None
