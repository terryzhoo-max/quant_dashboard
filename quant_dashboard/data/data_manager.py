import pandas as pd
import numpy as np
import tushare as ts
import os
import time
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger("alphacore.data_manager")

import config  # 导入config以触发Tushare全局连接修复(Monkey Patch)

# ====== 配置区 ======
TUSHARE_TOKEN = config.TUSHARE_TOKEN
DATA_DIR = "data_lake"
FINA_INDICATOR_DIR = os.path.join(DATA_DIR, "financials")
DAILY_PRICE_DIR = os.path.join(DATA_DIR, "daily_prices")
# 产业追踪只读取这一前复权命名空间。它与实时动量的未复权缓存物理隔离，
# 避免 fund_daily 覆盖 pro_bar(qfq) 历史后制造拆分式虚假涨跌。
INDUSTRY_DAILY_PRICE_DIR = os.path.join(DATA_DIR, "industry_prices_qfq")

# 初始化 Tushare。直接传递 token，避免模块导入时写用户目录 tk.csv。
pro = ts.pro_api(TUSHARE_TOKEN)

class FactorDataManager:
    def __init__(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        if not os.path.exists(FINA_INDICATOR_DIR):
            os.makedirs(FINA_INDICATOR_DIR)
        if not os.path.exists(DAILY_PRICE_DIR):
            os.makedirs(DAILY_PRICE_DIR)
        if not os.path.exists(INDUSTRY_DAILY_PRICE_DIR):
            os.makedirs(INDUSTRY_DAILY_PRICE_DIR)

    def get_all_stocks(self) -> pd.DataFrame:
        """获取全市场 A 股列表 — V6.0: 30天自动刷新 (覆盖新上市/退市)"""
        cache_path = os.path.join(DATA_DIR, "stock_list.parquet")
        if os.path.exists(cache_path):
            # V6.0: 检查文件修改时间, 超过30天自动重新拉取
            file_age_days = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_path))).days
            if file_age_days <= 30:
                logger.debug("加载本地股票列表缓存 (age=%d天)", file_age_days)
                return pd.read_parquet(cache_path)
            logger.info("stock_list.parquet 已过期 (%d天 > 30天), 自动刷新", file_age_days)
        
        logger.info("从 Tushare 获取全市场股票列表")
        try:
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
            df.to_parquet(cache_path)
            return df
        except Exception as e:
            logger.error("股票列表刷新失败: %s", e)
            # 刷新失败时仍返回过期的缓存数据
            if os.path.exists(cache_path):
                return pd.read_parquet(cache_path)
            raise

    def sync_financial_indicators(self, ts_codes: List[str], start_year: int = 2018, force: bool = False):
        """
        V5.0: 同步财务指标 (PIT 数据) — 支持增量更新
        force=True 时强制全量刷新, 否则增量拉取最近1年数据
        """
        current_year = datetime.now().year
        
        for code in ts_codes:
            file_path = os.path.join(FINA_INDICATOR_DIR, f"{code}.parquet")
            existing_df = None
            
            if os.path.exists(file_path) and not force:
                existing_df = pd.read_parquet(file_path)
                if not existing_df.empty and 'ann_date' in existing_df.columns:
                    last_ann = str(existing_df['ann_date'].max())
                    last_year = int(last_ann[:4]) if len(last_ann) >= 4 else start_year
                    # 增量: 只拉取最后公告年份至今的数据
                    start_year = max(start_year, last_year)

            logger.info("%s拉取 %s PIT 财务数据 (%d-%d)", '增量' if existing_df is not None else '全量', code, start_year, current_year)
            all_indicators = []
            
            for year in range(start_year, current_year + 1):
                try:
                    df = pro.fina_indicator(ts_code=code, start_date=f"{year}0101", end_date=f"{year}1231")
                    if df is not None and not df.empty:
                        all_indicators.append(df)
                    time.sleep(0.5)
                except Exception as e:
                    logger.error("%s %d年获取失败: %s", code, year, e)
                    break
            
            if all_indicators:
                valid_indicators = [d.dropna(how='all', axis=1) for d in all_indicators if not d.empty and not d.isna().all(axis=None)]
                new_df = pd.concat(valid_indicators, ignore_index=True) if valid_indicators else pd.DataFrame()
                if existing_df is not None:
                    dfs = [d.dropna(how='all', axis=1) for d in [existing_df, new_df] if not d.empty and not d.isna().all(axis=None)]
                    full_df = pd.concat(dfs, ignore_index=True).drop_duplicates(
                        subset=['ts_code', 'ann_date', 'end_date']
                    ).sort_values('ann_date')
                else:
                    full_df = new_df.drop_duplicates().sort_values('ann_date')
                full_df.to_parquet(file_path)
                logger.info("%s 同步完成 (%d 条记录)", code, len(full_df))
            elif existing_df is not None:
                logger.debug("%s 无新增财务数据", code)

    def get_factor_payload(self, ts_code: str, factor_names: List[str]) -> pd.DataFrame:
        """
        获取指定因子的 PIT 时间序列
        """
        file_path = os.path.join(FINA_INDICATOR_DIR, f"{ts_code}.parquet")
        if not os.path.exists(file_path):
            return pd.DataFrame()
        
        df = pd.read_parquet(file_path)
        # 仅保留 ann_date, end_date 和需要的因子字段
        cols = ["ts_code", "ann_date", "end_date"] + factor_names
        available_cols = [c for c in cols if c in df.columns]
        return df[available_cols]

    def sync_daily_prices(self, ts_codes: List[str], start_date: str = "20180101",
                          end_date: Optional[str] = None, asset: str = 'E',
                          price_dir: Optional[str] = None):
        """同步日线行情 (含复权因子)"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        target_dir = price_dir or DAILY_PRICE_DIR
        os.makedirs(target_dir, exist_ok=True)
            
        for code in ts_codes:
            file_path = os.path.join(target_dir, f"{code}.parquet")
            
            # 增量逻辑
            start_sync_date = start_date
            existing_df = None
            if os.path.exists(file_path):
                existing_df = pd.read_parquet(file_path)
                if not existing_df.empty:
                    last_date = existing_df['trade_date'].max()
                    # 如果 last_date 是 YYYYMMDD 字符串，转为 datetime 再加一天
                    last_dt = datetime.strptime(str(last_date), "%Y%m%d")
                    start_sync_date = (last_dt + timedelta(days=1)).strftime("%Y%m%d")
            
            if start_sync_date > end_date:
                logger.debug("%s 数据已是最新 (%s > %s)", code, start_sync_date, end_date)
                continue
                
            logger.info("增量拉取 %s 行情 (%s -> %s)", code, start_sync_date, end_date)
            try:
                new_df = ts.pro_bar(ts_code=code, asset=asset, adj='qfq', start_date=start_sync_date, end_date=end_date)
                if new_df is not None and not new_df.empty:
                    new_df = new_df.sort_values("trade_date")
                    if existing_df is not None:
                        dfs = [d.dropna(how='all', axis=1) for d in [existing_df, new_df] if not d.empty and not d.isna().all(axis=None)]
                        combined_df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=['trade_date']).sort_values("trade_date")
                    else:
                        combined_df = new_df
                    combined_df.to_parquet(file_path)
                    logger.info("%s 增量更新完成", code)
                else:
                    logger.debug("%s 无新数据", code)
                time.sleep(0.2)
            except Exception as e:
                logger.error("%s 行情获取失败: %s", code, e)

    def sync_industry_prices(self, ts_codes: List[str], start_date: str = "20180101",
                             end_date: Optional[str] = None):
        """同步产业 ETF，并按官方 pct_chg 重建拆分连续收盘序列。"""
        result = self.sync_daily_prices(
            ts_codes,
            start_date=start_date,
            end_date=end_date,
            asset='FD',
            price_dir=INDUSTRY_DAILY_PRICE_DIR,
        )
        for code in ts_codes:
            self._normalize_industry_split_adjustment(code)
        return result

    def _normalize_industry_split_adjustment(self, ts_code: str) -> None:
        """
        基金份额拆分时 close 会跳变，但 pct_chg 使用拆分后的 pre_close 计算。

        以最新真实收盘价为锚，按 pct_chg 反推连续历史 close；raw_close 永久保留
        原始价格用于审计。这样不删除公司行动日，也不把拆分误判为市场回撤。
        """
        file_path = os.path.join(INDUSTRY_DAILY_PRICE_DIR, f"{ts_code}.parquet")
        if not os.path.exists(file_path):
            return
        try:
            df = pd.read_parquet(file_path).sort_values("trade_date").reset_index(drop=True)
            if df.empty or "close" not in df.columns or "pct_chg" not in df.columns:
                logger.warning("%s 缺少 close/pct_chg，无法执行拆分连续化", ts_code)
                return

            current_close = pd.to_numeric(df["close"], errors="coerce")
            if "raw_close" in df.columns:
                raw_close = pd.to_numeric(df["raw_close"], errors="coerce").fillna(current_close)
            else:
                raw_close = current_close.copy()
            if raw_close.isna().any() or (raw_close <= 0).any():
                logger.warning("%s 原始 close 非法，跳过拆分连续化", ts_code)
                return

            reported_returns = pd.to_numeric(df["pct_chg"], errors="coerce") / 100.0
            raw_returns = raw_close.pct_change()
            reported_returns = reported_returns.where(
                np.isfinite(reported_returns) & (reported_returns > -0.99),
                raw_returns,
            )
            reported_returns.iloc[0] = 0.0
            growth = (1.0 + reported_returns.fillna(0.0)).cumprod()
            if growth.empty or not np.isfinite(growth.iloc[-1]) or growth.iloc[-1] <= 0:
                logger.warning("%s pct_chg 累计因子非法，跳过拆分连续化", ts_code)
                return

            adjusted_close = growth / growth.iloc[-1] * raw_close.iloc[-1]
            df["raw_close"] = raw_close.astype(float)
            df["close"] = adjusted_close.round(6)
            df["price_basis"] = "pct_chg_split_adjusted"
            df.to_parquet(file_path)
        except Exception as exc:
            logger.error("%s 拆分连续化失败: %s", ts_code, exc)

    def get_last_sync_date(self, ts_codes: List[str], price_dir: Optional[str] = None) -> str:
        """获取这些股票里最晚的一个交易日期"""
        target_dir = price_dir or DAILY_PRICE_DIR
        dates = []
        for code in ts_codes:
            file_path = os.path.join(target_dir, f"{code}.parquet")
            if os.path.exists(file_path):
                df = pd.read_parquet(file_path)
                if not df.empty:
                    dates.append(str(df['trade_date'].max()))
        return max(dates) if dates else "N/A"

    def get_price_payload(self, ts_code: str, price_dir: Optional[str] = None) -> pd.DataFrame:
        """读取行情数据并计算未来收益率"""
        target_dir = price_dir or DAILY_PRICE_DIR
        file_path = os.path.join(target_dir, f"{ts_code}.parquet")
        if not os.path.exists(file_path):
            return pd.DataFrame()
        
        df = pd.read_parquet(file_path)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date')
        
        # 计算未来 5 日收益率 (用于 IC 计算)
        df['next_5d_ret'] = df['close'].shift(-5) / df['close'] - 1
        # V2.0: 返回 amount 列供资金热度引擎使用
        cols = ['trade_date', 'close', 'next_5d_ret']
        if 'amount' in df.columns:
            cols.append('amount')
        if 'vol' in df.columns:
            cols.append('vol')
        return df[[c for c in cols if c in df.columns]]

    def get_industry_price_payload(self, ts_code: str) -> pd.DataFrame:
        """读取产业追踪专用的前复权行情。"""
        return self.get_price_payload(ts_code, price_dir=INDUSTRY_DAILY_PRICE_DIR)

    @staticmethod
    def _clean_trade_date(value) -> Optional[str]:
        """将字符串/Timestamp 统一为 YYYYMMDD；非法值返回 None。"""
        try:
            text = str(value).strip()
            if text.endswith(".0"):
                text = text[:-2]
            compact = text.replace("-", "").replace("/", "")
            if len(compact) >= 8 and compact[:8].isdigit() and compact[:4] in {
                str(year) for year in range(1990, 2101)
            }:
                return datetime.strptime(compact[:8], "%Y%m%d").strftime("%Y%m%d")
            parsed = pd.to_datetime(value)
            if pd.isna(parsed):
                return None
            return parsed.strftime("%Y%m%d")
        except Exception:
            return None

    def _load_open_trading_days(self) -> Optional[List[str]]:
        cal_path = os.path.join(DATA_DIR, "trading_calendar.json")
        if not os.path.exists(cal_path):
            return None
        try:
            with open(cal_path, "r", encoding="utf-8") as f:
                values = json.load(f)
            clean = sorted({str(v).replace("-", "")[:8] for v in values})
            return [v for v in clean if len(v) == 8 and v.isdigit()]
        except Exception as exc:
            logger.warning("交易日历读取失败: %s", exc)
            return None

    def _expected_trade_date(self, as_of=None) -> tuple:
        """返回最近已收盘交易日及日历来源。"""
        current = pd.Timestamp(as_of).to_pydatetime() if as_of is not None else datetime.now()
        target = current
        if as_of is None and current.hour < 15:
            target = current - timedelta(days=1)
        target_str = target.strftime("%Y%m%d")

        open_days = self._load_open_trading_days()
        if open_days:
            eligible = [d for d in open_days if d <= target_str]
            if eligible:
                return eligible[-1], open_days, "exchange_calendar"

        # 通用因子功能保留工作日降级；产业决策层会因缺少交易所日历而锁定。
        cursor = target
        while cursor.weekday() >= 5:
            cursor -= timedelta(days=1)
        return cursor.strftime("%Y%m%d"), None, "weekday_fallback"

    def check_data_freshness(self, ts_codes: List[str], price_dir: Optional[str] = None,
                             min_history_rows: int = 1,
                             max_abs_return: Optional[float] = None,
                             as_of=None, require_calendar: bool = False) -> dict:
        """
        全量检查行情新鲜度和基础完整性。

        向后兼容保留 daily_latest/fina_latest/is_stale/stale_days 字段，并新增
        每标的质量、交易日口径、覆盖率和 decision_locked。
        """
        target_dir = price_dir or DAILY_PRICE_DIR
        codes = list(dict.fromkeys(ts_codes))
        expected_date, open_days, calendar_source = self._expected_trade_date(as_of)
        expected_window = []
        if open_days:
            expected_window = [d for d in open_days if d <= expected_date][-max(1, min_history_rows):]

        daily_dates = []
        fina_dates = []
        items = {}
        missing_codes = []
        stale_codes = []
        insufficient_codes = []
        incomplete_codes = []
        anomalous_codes = []
        invalid_codes = []

        for code in codes:
            issues = []
            item = {
                "exists": False,
                "latest_trade_date": None,
                "rows": 0,
                "coverage_ratio": 0.0,
                "stale_trading_days": 999,
                "max_abs_return": None,
                "issues": issues,
                "is_usable": False,
            }
            dp = os.path.join(target_dir, f"{code}.parquet")
            if not os.path.exists(dp):
                issues.append("MISSING_DATA")
                missing_codes.append(code)
                items[code] = item
                continue

            item["exists"] = True
            try:
                df = pd.read_parquet(dp)
            except Exception:
                issues.append("UNREADABLE_DATA")
                invalid_codes.append(code)
                items[code] = item
                continue

            if df.empty or "trade_date" not in df.columns or "close" not in df.columns:
                issues.append("INVALID_SCHEMA")
                invalid_codes.append(code)
                items[code] = item
                continue

            work = df[["trade_date", "close"]].copy()
            work["trade_date_clean"] = work["trade_date"].map(self._clean_trade_date)
            if work["trade_date_clean"].isna().any():
                issues.append("INVALID_DATE")
            work = work.dropna(subset=["trade_date_clean"])
            if work["trade_date_clean"].duplicated().any():
                issues.append("DUPLICATE_TRADE_DATE")
            work = work.sort_values("trade_date_clean").drop_duplicates(
                subset=["trade_date_clean"], keep="last"
            )
            future_rows = int((work["trade_date_clean"] > expected_date).sum())
            # 历史 as-of 查询允许缓存中存在其后的正常行情；实时查询才把未来日期
            # 视为时钟/数据污染问题。
            if future_rows and as_of is None:
                issues.append("FUTURE_DATA")
            work = work[work["trade_date_clean"] <= expected_date]

            close_values = pd.to_numeric(work["close"], errors="coerce")
            if close_values.isna().any():
                issues.append("NON_FINITE_CLOSE")
            if (close_values.dropna() <= 0).any():
                issues.append("NON_POSITIVE_CLOSE")
            work = work.assign(close=close_values).dropna(subset=["close"])

            item["rows"] = int(len(work))
            if len(work) < min_history_rows:
                issues.append("INSUFFICIENT_HISTORY")
                insufficient_codes.append(code)

            present_dates = set(work["trade_date_clean"].tolist())
            if expected_window:
                item["coverage_ratio"] = round(
                    len(present_dates.intersection(expected_window)) / len(expected_window), 4
                )
                if item["coverage_ratio"] < 0.95:
                    issues.append("INCOMPLETE_RECENT_HISTORY")
                    incomplete_codes.append(code)
            elif len(work):
                item["coverage_ratio"] = 1.0

            if not work.empty:
                latest = work["trade_date_clean"].iloc[-1]
                item["latest_trade_date"] = latest
                daily_dates.append(latest)
                if open_days:
                    stale_days = len([d for d in open_days if latest < d <= expected_date])
                else:
                    latest_dt = datetime.strptime(latest, "%Y%m%d")
                    expected_dt = datetime.strptime(expected_date, "%Y%m%d")
                    stale_days = len(pd.bdate_range(latest_dt + timedelta(days=1), expected_dt))
                item["stale_trading_days"] = int(stale_days)
                if latest < expected_date:
                    issues.append("STALE_DATA")
                    stale_codes.append(code)

                returns = work["close"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
                max_jump = float(returns.abs().max()) if not returns.empty else 0.0
                item["max_abs_return"] = round(max_jump, 6)
                if max_abs_return is not None and max_jump > max_abs_return:
                    issues.append("PRICE_JUMP")
                    anomalous_codes.append(code)

            if any(issue in issues for issue in (
                "INVALID_SCHEMA", "INVALID_DATE", "DUPLICATE_TRADE_DATE",
                "FUTURE_DATA", "NON_FINITE_CLOSE", "NON_POSITIVE_CLOSE",
            )):
                invalid_codes.append(code)

            item["issues"] = list(dict.fromkeys(issues))
            item["is_usable"] = not item["issues"]
            items[code] = item

            # 财务数据
            fp = os.path.join(FINA_INDICATOR_DIR, f"{code}.parquet")
            if os.path.exists(fp):
                try:
                    fina_df = pd.read_parquet(fp)
                    if not fina_df.empty and 'ann_date' in fina_df.columns:
                        fina_dates.append(str(fina_df['ann_date'].max()))
                except Exception:
                    pass

        daily_latest = max(daily_dates) if daily_dates else 'N/A'
        daily_earliest_latest = min(daily_dates) if daily_dates else 'N/A'
        fina_latest = max(fina_dates) if fina_dates else 'N/A'

        missing_codes = list(dict.fromkeys(missing_codes))
        stale_codes = list(dict.fromkeys(stale_codes))
        insufficient_codes = list(dict.fromkeys(insufficient_codes))
        incomplete_codes = list(dict.fromkeys(incomplete_codes))
        anomalous_codes = list(dict.fromkeys(anomalous_codes))
        invalid_codes = list(dict.fromkeys(invalid_codes))
        reasons = []
        if require_calendar and calendar_source != "exchange_calendar":
            reasons.append("TRADING_CALENDAR_UNAVAILABLE")
        for label, values in (
            ("MISSING_DATA", missing_codes),
            ("STALE_DATA", stale_codes),
            ("INSUFFICIENT_HISTORY", insufficient_codes),
            ("INCOMPLETE_HISTORY", incomplete_codes),
            ("PRICE_ANOMALY", anomalous_codes),
            ("INVALID_DATA", invalid_codes),
        ):
            if values:
                reasons.append(f"{label}: {len(values)}/{len(codes)}")

        stale_values = [v["stale_trading_days"] for v in items.values()
                        if v["stale_trading_days"] != 999]
        stale_days = max(stale_values) if stale_values else 999
        decision_locked = bool(reasons)

        return {
            'daily_latest': daily_latest,
            'daily_earliest_latest': daily_earliest_latest,
            'fina_latest': fina_latest,
            'expected_trade_date': expected_date,
            'calendar_source': calendar_source,
            'is_stale': bool(missing_codes or stale_codes),
            'stale_days': stale_days,
            'checked_count': len(codes),
            'available_count': len(codes) - len(missing_codes),
            'usable_count': sum(1 for item in items.values() if item['is_usable']),
            'coverage_ratio': round(
                sum(1 for item in items.values() if item['is_usable']) / len(codes), 4
            ) if codes else 0.0,
            'missing_codes': missing_codes,
            'stale_codes': stale_codes,
            'insufficient_codes': insufficient_codes,
            'incomplete_codes': incomplete_codes,
            'anomalous_codes': anomalous_codes,
            'invalid_codes': invalid_codes,
            'is_usable': not decision_locked,
            'decision_locked': decision_locked,
            'reasons': reasons,
            'items': items,
            'checked_at': datetime.now().isoformat(timespec="seconds")
        }

    def check_industry_data_quality(self, ts_codes: List[str], as_of=None,
                                    min_history_rows: int = 60,
                                    max_abs_return: float = 0.35) -> dict:
        """产业追踪强质量门：全池、交易日历、前复权跳变均须通过。"""
        quality = self.check_data_freshness(
            ts_codes,
            price_dir=INDUSTRY_DAILY_PRICE_DIR,
            min_history_rows=min_history_rows,
            max_abs_return=max_abs_return,
            as_of=as_of,
            require_calendar=True,
        )
        quality["data_contract"] = {
            "namespace": os.path.basename(INDUSTRY_DAILY_PRICE_DIR),
            "source": "tushare.pro_bar",
            "asset": "FD",
            "adjustment": "qfq+fund_pct_chg_split_normalization",
        }
        return quality

    def smart_sync(self, ts_codes: List[str], force: bool = False):
        """
        V5.0: 智能同步 — 仅当数据过期时拉取
        返回: sync_result dict
        """
        freshness = self.check_data_freshness(ts_codes)
        if not freshness['is_stale'] and not force:
            logger.info("数据新鲜 (最新日线: %s), 跳过同步", freshness['daily_latest'])
            return {'synced': False, 'freshness': freshness}

        logger.info("数据过期 %d 天, 开始同步", freshness['stale_days'])
        # 同步日线行情
        self.sync_daily_prices(ts_codes)
        # 同步财务指标 (增量)
        self.sync_financial_indicators(ts_codes)
        # V6.6: 同步交易日历 (供审计引擎 Holiday 自维护使用)
        self.sync_trading_calendar()
        # 重新检查
        new_freshness = self.check_data_freshness(ts_codes)
        logger.info("同步完成, 最新日线: %s", new_freshness['daily_latest'])
        return {'synced': True, 'freshness': new_freshness}

    def sync_trading_calendar(self, years: int = 2):
        """V6.6: 同步 SSE 交易日历到 data_lake/trading_calendar.json
        供审计引擎 _is_trading_day() 使用，消除硬编码假期的年度维护。
        默认拉取当年 ± years 范围。
        """
        cal_path = os.path.join(DATA_DIR, "trading_calendar.json")
        try:
            now = datetime.now()
            start = f"{now.year - years}0101"
            end = f"{now.year + 1}1231"
            df = pro.trade_cal(exchange='SSE', start_date=start, end_date=end)
            if df is not None and not df.empty:
                open_days = df[df['is_open'] == 1]['cal_date'].tolist()
                with open(cal_path, 'w', encoding='utf-8') as f:
                    json.dump(open_days, f)
                logger.info("交易日历已同步: %d 个交易日 (%s~%s)", len(open_days), start, end)
            else:
                logger.warning("交易日历 API 返回空, 保留旧缓存")
        except Exception as e:
            logger.warning("交易日历同步失败 (不影响核心功能): %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manager = FactorDataManager()
    
    # 演示：同步前10只股票作为测试
    stocks = manager.get_all_stocks()
    test_codes = stocks["ts_code"].head(10).tolist()
    
    logger.info("开始测试同步 %d 只标的的财务数据", len(test_codes))
    manager.sync_financial_indicators(test_codes)
