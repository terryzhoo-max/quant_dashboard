document.addEventListener('DOMContentLoaded', function() {
    const navContainer = document.getElementById('sector-nav-container');
    const datePicker = document.getElementById('data-date-picker');
    const syncBtn = document.getElementById('sync-btn');
    const overlay = document.getElementById('loading-overlay');

    let charts = { rps: null, value: null, risk: null, rsLine: null, heatmap: null };
    let currentCode = null;
    let allSectorData = [];
    let _lastExecutionContext = null;

    const VALIDATION_REASON_LABELS = {
        VALIDATION_ARTIFACT_MISSING: '验证产物缺失',
        VALIDATION_ARTIFACT_INVALID: '验证产物无效',
        VALIDATION_ARTIFACT_STALE: '验证产物已过期',
        VALIDATION_DATA_STALE: '验证基准数据滞后',
        POLICY_FINGERPRINT_MISMATCH: '当前策略与验证版本不一致',
        UNIVERSE_FINGERPRINT_MISMATCH: '行业池血缘与验证版本不一致',
        POINT_IN_TIME_UNIVERSE_UNAVAILABLE: '缺少完整点时行业池',
        OOS_SAMPLE_TOO_SMALL: '样本外信号不足',
        OOS_WIN_RATE_BELOW_GATE: '样本外胜率未达标',
        OOS_PROFIT_FACTOR_BELOW_GATE: '样本外盈亏因子未达标',
        OOS_EXCESS_RETURN_BELOW_GATE: '样本外超额收益未达标',
        OOS_DRAWDOWN_ABOVE_LIMIT: '样本外回撤超限',
        OOS_BEAR_SAMPLE_TOO_SMALL: '熊市样本不足',
        OOS_RANGE_SAMPLE_TOO_SMALL: '震荡市样本不足',
        OOS_BULL_SAMPLE_TOO_SMALL: '牛市样本不足'
    };

    ['BEAR', 'RANGE', 'BULL'].forEach(regime => {
        const cn = { BEAR: '熊市', RANGE: '震荡市', BULL: '牛市' }[regime];
        VALIDATION_REASON_LABELS[`OOS_${regime}_WIN_RATE_BELOW_GATE`] = `${cn}胜率未达标`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_PROFIT_FACTOR_BELOW_GATE`] = `${cn}盈亏因子未达标`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_EXCESS_RETURN_BELOW_GATE`] = `${cn}超额收益未达标`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_PORTFOLIO_PERIODS_TOO_SMALL`] = `${cn}独立调仓期不足`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_POSITIVE_PERIOD_RATE_BELOW_GATE`] = `${cn}组合期胜率未达标`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_WIN_RATE_CONFIDENCE_BELOW_GATE`] = `${cn}胜率置信下限不足`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_PERIOD_PROFIT_FACTOR_BELOW_GATE`] = `${cn}组合期盈亏因子未达标`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_PERIOD_EXCESS_RETURN_BELOW_GATE`] = `${cn}组合期超额收益未达标`;
        VALIDATION_REASON_LABELS[`OOS_${regime}_PERIOD_DRAWDOWN_ABOVE_LIMIT`] = `${cn}组合期回撤超限`;
    });

    function escapeText(value) {
        return String(value ?? '').replace(/[&<>'"]/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        })[c]);
    }

    function formatPercent(value, digits = 1) {
        return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : '—';
    }

    function renderValidationStrip(context) {
        const panel = document.getElementById('industry-validation-strip');
        if (!panel) return;
        const validation = context?.model_validation || {};
        const holdout = validation.holdout || {};
        const portfolio = holdout.portfolio || {};
        const ready = validation.ready === true;
        const reasons = Array.isArray(validation.reasons) ? validation.reasons : [];
        const reasonLabels = reasons.map(reason => VALIDATION_REASON_LABELS[reason] || reason);
        const stateText = ready ? '已晋升 · 可进入执行资格审查' : '影子验证 · 禁止执行';
        const stateClass = ready ? 'is-ready' : 'is-blocked';
        const dataEnd = validation.data_end_date || '—';
        const signals = Number.isFinite(Number(holdout.signals)) ? Number(holdout.signals) : '—';
        const profitFactor = Number.isFinite(Number(portfolio.profit_factor)) ? Number(portfolio.profit_factor).toFixed(2) : '—';
        const regimes = holdout.by_regime || {};
        const regimeCards = ['BEAR', 'RANGE', 'BULL'].map(regime => {
            const metrics = regimes[regime] || {};
            const period = metrics.portfolio || {};
            const regimeStatus = validation.regime_statuses?.[regime] || {};
            const statisticalReady = regimeStatus.statistical_ready === true;
            const lifecycle = regimeStatus.lifecycle || 'disabled';
            const names = { BEAR: '熊市', RANGE: '震荡市', BULL: '牛市' };
            const lifecycleNames = { disabled: '已禁用', shadow: '影子', enabled: '已启用' };
            const pf = Number.isFinite(Number(period.profit_factor)) ? Number(period.profit_factor).toFixed(2) : '—';
            return `
                <div class="validation-regime lifecycle-${escapeText(lifecycle)} ${statisticalReady ? 'is-pass' : 'is-fail'}">
                    <strong>${statisticalReady ? '✓' : '×'} ${names[regime]} · ${lifecycleNames[lifecycle] || lifecycle}</strong>
                    <span>${escapeText(period.periods ?? '—')}期 / ${escapeText(metrics.signals ?? '—')}笔</span>
                    <span>期胜率 ${formatPercent(period.positive_period_rate)}</span>
                    <span>95%下限 ${formatPercent(period.wilson_lower_95)}</span>
                    <span>PF ${escapeText(pf)}</span>
                    <span>超额 ${formatPercent(period.avg_excess_return, 2)}</span>
                    <span>回撤 ${formatPercent(period.max_drawdown)}</span>
                </div>
            `;
        }).join('');
        panel.className = `validation-strip glass-panel ${stateClass}`;
        panel.innerHTML = `
            <div class="validation-strip__status">
                <span class="validation-strip__eyebrow">MODEL VALIDATION</span>
                <strong>${ready ? '✅' : '🔒'} ${stateText}</strong>
                <span>证据截止 ${escapeText(dataEnd)}</span>
            </div>
            <div class="validation-strip__metrics">
                <span>OOS样本 <b>${escapeText(portfolio.periods ?? '—')}期 / ${escapeText(signals)}笔</b></span>
                <span>组合期胜率 <b>${formatPercent(portfolio.positive_period_rate)}</b></span>
                <span>95%下限 <b>${formatPercent(portfolio.wilson_lower_95)}</b></span>
                <span>盈亏因子 <b>${escapeText(profitFactor)}</b></span>
                <span>平均超额 <b>${formatPercent(portfolio.avg_excess_return, 2)}</b></span>
                <span>最大回撤 <b>${formatPercent(portfolio.max_drawdown)}</b></span>
            </div>
            <div class="validation-strip__reasons" title="${escapeText(reasonLabels.join('；'))}">
                ${ready ? '全部晋升闸门已通过' : escapeText(reasonLabels.slice(0, 4).join(' · ') || '暂无有效验证证据')}
            </div>
            <div class="validation-strip__regimes" aria-label="分市场环境样本外证据">
                ${regimeCards}
            </div>
        `;
    }

    const DECISION_LOCK_LABELS = {
        REGIME_MODEL_DISABLED: '当前市场环境模型已禁用，须经预注册证据审查后显式启用',
        REGIME_MODEL_SHADOW: '当前市场环境模型仅处于影子观察期',
        MODEL_VALIDATION_PENDING: '样本外验证尚未完成',
        REGIME_CRASH_LOCK: '极端风险环境禁止新开行业仓位',
        ZERO_POSITION_CAP: '组合风险预算已降至零',
        AIAE_CONTEXT_MISSING: 'AIAE 风控上下文缺失',
        AIAE_STALE: 'AIAE 风控数据已过期',
        AIAE_DECISION_LOCKED: 'AIAE 已触发强制锁定',
        AIAE_TIMESTAMP_INVALID: 'AIAE 时间戳无效',
        AIAE_UNUSABLE: 'AIAE 风控状态不可用',
        REGIME_UNAVAILABLE: '市场环境不可用',
        REGIME_INVALID: '市场环境分类无效',
        REGIME_DATA_STALE: '市场环境数据落后于行业数据',
        HISTORICAL_QUERY_RESEARCH_ONLY: '历史查询仅供研究，不具备执行资格'
    };

    const WATCH_TIER_LABELS = {
        NEAR_TRIGGER: '临近个股条件',
        LEADING_WATCH: '领先观察',
        TREND_REPAIR: '等待趋势修复',
        LIQUIDITY_CONSTRAINED: '成交容量不足',
        RISK_VETO: '风险否决'
    };

    function formatCny(value) {
        const amount = Number(value);
        if (!Number.isFinite(amount)) return '—';
        if (amount >= 100000000) return `${(amount / 100000000).toFixed(2)}亿`;
        if (amount >= 10000) return `${(amount / 10000).toFixed(0)}万`;
        return `${amount.toFixed(0)}元`;
    }

    function candidateConditionLabel(condition, item) {
        const score = Number(item?.research_score);
        const gate = Number(item?.score_gate);
        const gap = Number(item?.score_gap);
        if (condition === 'SCORE_BELOW_REGIME_GATE') {
            const scoreText = Number.isFinite(score) ? score.toFixed(1) : '—';
            const gateText = Number.isFinite(gate) ? gate.toFixed(1) : '—';
            const gapText = Number.isFinite(gap) ? `，尚差 ${Math.abs(gap).toFixed(1)} 分` : '';
            return `研究分达到 ${gateText}（当前 ${scoreText}${gapText}）`;
        }
        return ({
            BELOW_MA20: '收盘重新站上 MA20',
            BELOW_MA60: '收盘重新站上 MA60',
            MA20_SLOPE_NEGATIVE: 'MA20 斜率转为非负',
            DANGER_RISK_ALERT: '危险级拥挤或风险警报解除',
            LIQUIDITY_DATA_INCOMPLETE: '补齐20个交易日的有效成交额数据',
            MEDIAN_TURNOVER_20D_BELOW_MINIMUM: `20日中位成交额达到 ${formatCny(item?.min_median_turnover_cny || 50000000)}`
        })[condition] || condition;
    }

    function renderAbstentionPlan(plan, context) {
        const panel = document.getElementById('industry-abstention-panel');
        if (!panel) return;
        const packet = plan || {};
        const noTrade = packet.action !== 'EXECUTION_CANDIDATES_PRESENT';
        const lockReasons = Array.isArray(packet.decision_lock_reasons)
            ? packet.decision_lock_reasons
            : [];
        const reasonLabels = lockReasons.map(reason => DECISION_LOCK_LABELS[reason] || reason);
        const watchlist = Array.isArray(packet.watchlist) ? packet.watchlist : [];
        const regime = packet.regime || context?.regime || 'UNKNOWN';

        if (!noTrade) {
            panel.className = 'abstention-panel glass-panel has-candidates';
            panel.innerHTML = `
                <div class="abstention-panel__headline">
                    <div><span>INSTITUTIONAL ACTION</span><strong>条件候选已出现</strong></div>
                    <b>${escapeText(regime)} · ${escapeText(packet.eligible_buy_count || 0)} 个执行候选</b>
                </div>
                <div class="abstention-panel__disclaimer">仍须逐项核对 execution.allowed、仓位上限和止损参数；本面板不替代交易审批。</div>
            `;
            return;
        }

        const cards = watchlist.map((item, index) => {
            const tier = item.readiness_tier || 'TREND_REPAIR';
            const conditions = Array.isArray(item.remaining_conditions) ? item.remaining_conditions : [];
            const conditionHtml = conditions.length
                ? conditions.map(condition => `<li>${escapeText(candidateConditionLabel(condition, item))}</li>`).join('')
                : '<li>个体条件已满足，但全局模型锁仍未解除</li>';
            const gap = Number(item.score_gap);
            const gapText = Number.isFinite(gap) ? `${gap >= 0 ? '+' : ''}${gap.toFixed(1)}` : '—';
            return `
                <article class="abstention-watch tier-${escapeText(tier.toLowerCase())}">
                    <div class="abstention-watch__top">
                        <span>#${index + 1} ${escapeText(WATCH_TIER_LABELS[tier] || tier)}</span>
                        <b>观察，不执行</b>
                    </div>
                    <div class="abstention-watch__name">
                        <strong>${escapeText(item.name || '未知行业')}</strong>
                        <code>${escapeText(item.code || '—')}</code>
                    </div>
                    <div class="abstention-watch__metrics">
                        <span>研究分 <b>${escapeText(item.research_score ?? '—')}</b></span>
                        <span>门槛 <b>${escapeText(item.score_gate ?? '—')}</b></span>
                        <span>差值 <b>${escapeText(gapText)}</b></span>
                        <span>个体检查 <b>${escapeText(item.passed_checks ?? 0)}/${escapeText(item.total_checks ?? 5)}</b></span>
                    </div>
                    <div class="abstention-watch__liquidity">
                        20日中位额 ${escapeText(formatCny(item.median_turnover_cny))} ·
                        2%保守单次容量 ${escapeText(formatCny(item.capacity_at_participation_cny))}
                    </div>
                    <ul>${conditionHtml}</ul>
                </article>
            `;
        }).join('');

        panel.className = 'abstention-panel glass-panel is-no-trade';
        panel.innerHTML = `
            <div class="abstention-panel__headline">
                <div><span>INSTITUTIONAL ACTION</span><strong>🔒 NO TRADE · 当前无可执行行业</strong></div>
                <b>${escapeText(regime)} · 仓位建议 0%</b>
            </div>
            <div class="abstention-panel__global-lock">
                <strong>全局前置条件</strong>
                <span>${escapeText(reasonLabels.join('；') || '当前没有行业通过全部执行闸门')}</span>
            </div>
            <div class="abstention-panel__watch-heading">
                <strong>领先观察清单</strong>
                <span>仅用于安排下一次复核优先级，不代表接近买点</span>
            </div>
            <div class="abstention-panel__watchlist">
                ${cards || '<div class="abstention-panel__empty">暂无具备完整数据的观察对象</div>'}
            </div>
            <div class="abstention-panel__disclaimer">⚠️ 观察清单 ≠ 买入建议；全局模型解锁与个体条件必须同时通过，且不会自动获得交易权限。</div>
        `;
    }

    const CHALLENGER_REASON_LABELS = {
        CHALLENGER_POINT_IN_TIME_UNIVERSE_UNAVAILABLE: '点时行业池仍不完整',
        CHALLENGER_CONFIRMATION_SAMPLE_TOO_SMALL: '2026确认期不足',
        CHALLENGER_CONFIRMATION_WIN_RATE_BELOW_GATE: '确认期胜率未达标',
        CHALLENGER_CONFIRMATION_CONFIDENCE_BELOW_GATE: '确认期置信下限不足',
        CHALLENGER_CONFIRMATION_PROFIT_FACTOR_BELOW_GATE: '确认期盈亏因子未达标',
        CHALLENGER_CONFIRMATION_EXCESS_BELOW_GATE: '确认期超额收益未达标',
        CHALLENGER_CONFIRMATION_DRAWDOWN_ABOVE_LIMIT: '确认期回撤超限',
        CHALLENGER_SHADOW_ONLY: '生命周期仅为影子观察'
    };

    function challengerPhaseCard(label, data, emphasis = false) {
        const metrics = data || {};
        const pf = Number.isFinite(Number(metrics.profit_factor)) ? Number(metrics.profit_factor).toFixed(2) : '—';
        return `
            <div class="challenger-phase ${emphasis ? 'is-confirmation' : ''}">
                <strong>${label}</strong>
                <span>${escapeText(metrics.periods ?? '—')}期</span>
                <span>胜率 ${formatPercent(metrics.positive_period_rate)}</span>
                <span>95%下限 ${formatPercent(metrics.wilson_lower_95)}</span>
                <span>PF ${escapeText(pf)}</span>
                <span>超额 ${formatPercent(metrics.avg_excess_return, 2)}</span>
                <span>回撤 ${formatPercent(metrics.max_drawdown)}</span>
            </div>
        `;
    }

    async function loadChallengerPanel() {
        const panel = document.getElementById('industry-challenger-panel');
        if (!panel) return;
        try {
            const [response, forwardResponse] = await Promise.all([
                fetch('/api/v1/industry-challenger'),
                fetch('/api/v1/industry-forward-monitor')
            ]);
            const [payload, forwardPayload] = await Promise.all([
                response.json(),
                forwardResponse.json()
            ]);
            if (!response.ok || payload.status !== 'success') {
                throw new Error(payload.message || '挑战者状态不可用');
            }
            if (!forwardResponse.ok || forwardPayload.status !== 'success') {
                throw new Error(forwardPayload.message || '前向证据账本不可用');
            }
            const data = payload.data || {};
            const forward = forwardPayload.data || {};
            const latest = data.latest_snapshot || {};
            const candidates = Array.isArray(latest.candidates) ? latest.candidates : [];
            const forwardPortfolio = forward.forward_portfolio || {};
            const forwardPf = Number.isFinite(Number(forwardPortfolio.profit_factor))
                ? Number(forwardPortfolio.profit_factor).toFixed(2)
                : '—';
            const maturityPeriods = Number(forward.maturity_periods || 0);
            const maturityTarget = Number(forward.maturity_target_periods || 8);
            const maturityPercent = Math.min(100, Math.max(0, Number(forward.maturity_ratio || 0) * 100));
            const integrityOk = forward.integrity_ok === true;
            const reasonText = (data.reasons || [])
                .map(reason => CHALLENGER_REASON_LABELS[reason] || reason)
                .join(' · ');
            const currentText = latest.regime === 'BULL'
                ? (candidates.length
                    ? `影子候选：${candidates.map(item => escapeText(item.code)).join('、')}`
                    : 'BULL环境下无行业通过挑战者过滤')
                : `${escapeText(latest.regime || '未知')}环境不运行BULL挑战者`;
            panel.innerHTML = `
                <div class="challenger-panel__header">
                    <div><span>PRE-REGISTERED CHALLENGER</span><strong>相对强度挑战者 V1</strong></div>
                    <b>影子研究 · 永不直接下单</b>
                    <em>${currentText}</em>
                </div>
                <div class="challenger-panel__phases">
                    ${challengerPhaseCard('设计区 ≤2023', data.design)}
                    ${challengerPhaseCard('验证区 2024–2025', data.validation)}
                    ${challengerPhaseCard('确认区 2026+', data.confirmation, true)}
                </div>
                <div class="challenger-panel__reasons" title="${escapeText(reasonText)}">${escapeText(reasonText || '等待验证证据')}</div>
                <div class="challenger-forward ${integrityOk ? 'is-healthy' : 'is-damaged'}">
                    <div class="challenger-forward__heading">
                        <div>
                            <span>FORWARD-ONLY EVIDENCE</span>
                            <strong>${integrityOk ? '✓ 哈希链完整' : '× 账本完整性失败 · 已锁定'}</strong>
                        </div>
                        <b>${forward.evidence_mature === true ? '前向样本已达最低期数' : `样本成熟度 ${escapeText(maturityPeriods)}/${escapeText(maturityTarget)}期`}</b>
                    </div>
                    <div class="challenger-forward__progress" aria-label="前向样本成熟度">
                        <i style="width:${maturityPercent.toFixed(1)}%"></i>
                    </div>
                    <div class="challenger-forward__metrics">
                        <span>快照日 <b>${escapeText(forward.snapshot_days ?? 0)}</b></span>
                        <span>无信号日 <b>${escapeText(forward.no_signal_days ?? 0)}</b></span>
                        <span>待结算 <b>${escapeText(forward.open_signals ?? 0)}</b></span>
                        <span>已结算 <b>${escapeText(forward.settled_signals ?? 0)}</b></span>
                        <span>期胜率 <b>${formatPercent(forwardPortfolio.positive_period_rate)}</b></span>
                        <span>95%下限 <b>${formatPercent(forwardPortfolio.wilson_lower_95)}</b></span>
                        <span>PF <b>${escapeText(forwardPf)}</b></span>
                        <span>最近快照 <b>${escapeText(forward.last_trade_date || '—')} · ${escapeText(forward.last_regime || '—')}</b></span>
                    </div>
                    <div class="challenger-forward__coverage">
                        PIT研究池：${escapeText(forward.universe_complete_from || '尚未冻结')} 起前瞻完整 ·
                        最近快照${forward.last_snapshot_universe_covered === true ? '已覆盖' : '早于冻结日/未覆盖'} ·
                        2020年以来历史仍不完整
                    </div>
                    <div class="challenger-forward__lock">🔒 仅作影子验证；前向样本达标也不自动获得交易权限</div>
                </div>
            `;
        } catch (error) {
            panel.innerHTML = `<div class="challenger-panel__loading">⚠️ 挑战者状态读取失败：${escapeText(error.message)}</div>`;
        }
    }

    const SECTORS = [
        // ── 硬科技·芯片算力 ──
        { code: "512760.SH", name: "半导体/芯片" },
        { code: "512720.SH", name: "计算机/AI" },
        { code: "562030.SH", name: "算力/AI基建" },
        // ── 通信·星际 ──
        { code: "515880.SH", name: "通信设备/卫星互联" },
        { code: "159218.SZ", name: "卫星/商业航天" },
        // ── 智造·装备 ──
        { code: "562500.SH", name: "人形机器人/智能制造" },
        { code: "159663.SZ", name: "工业母机/自主可控" },
        // ── 新能源·新材料 ──
        { code: "515030.SH", name: "新能源车" },
        { code: "516360.SH", name: "前沿新材料" },
        { code: "512400.SH", name: "有色金属" },
        // ── 生物·医药 ──
        { code: "512010.SH", name: "医药生物" },
        { code: "159992.SZ", name: "创新药/生物制造" },
        // ── 数字经济 ──
        { code: "515400.SH", name: "数据要素/数字经济" },
        // ── 国防·金融·成长 ──
        { code: "512660.SH", name: "军工龙头" },
        { code: "512880.SH", name: "证券/非银" },
        { code: "159915.SZ", name: "创业板/成长" }
    ];

    // === 指标百科数据 V4.0 ===
    const GLOSSARY = [
        { name: "Alpha Score (研究排序)", desc: "四因子研究评分：热度30% + 动量25% + 价格位置安全25% + 趋势强度20%。只用于横向排序，不等同于可执行买入信号。", range: "越高代表研究排序越靠前", warn: "仍须通过 Regime、AIAE、趋势与风险闸门" },
        { name: "RPS (动态相对强度)", desc: "该行业ETF近20日收益率在全部核心ETF池中的排名百分位。反映板块在同类中的相对表现。", range: "> 80 优秀", warn: "< 30 极弱，谨慎追入" },
        { name: "5年价格位置", desc: "当前复权价格在过去1250个交易日价格分布中的百分位，仅衡量历史位置，不代表PE/PB估值。", range: "20-60 中部区间", warn: "> 80 位置延伸，回撤风险上升" },
        { name: "成交拥挤度", desc: "当日成交额与20日平均成交额的比值。衡量场内资金的拥挤程度，过高表示追涨情绪浓厚。", range: "0.8-1.5x 健康", warn: "> 2.0x 极度拥挤，追高危险" },
        { name: "热度分 (Heat Score)", desc: "资金关注度综合评分。成交放量比40% + 5日动量35% + 拥挤度修正25%。反映市场资金对该行业的关注热情。", range: "45-70 活跃", warn: "> 85 过热，可能见顶" },
        { name: "放量比 (Vol Ratio)", desc: "当日成交金额与20日均量的比值，>1表示放量。配合价格方向判断：放量上涨=强势，放量下跌=出货。", range: "0.8-1.5x", warn: "> 2.5x 可能见顶放量" },
        { name: "MA20 / MA60", desc: "20日/60日均线。站上MA20=短期趋势向好，站上MA60=中期趋势健康。MA20斜率向上=趋势加速。", range: "站上MA20+MA60 最佳", warn: "跌破MA60 → 中线止损" },
        { name: "20D 动量趋势", desc: "近20日的累计涨跌幅。替代原北向资金卡(北向数据需要申万行业对照)。正值=上涨趋势，负值=下跌趋势。", range: "+2~8% 健康上行", warn: "> +12% 短期严重过热" }
    ];

    // === 颜色工具 ===
    function gradeColor(grade) {
        return { A: '#10b981', B: '#3b82f6', C: '#64748b', D: '#f59e0b', F: '#ef4444' }[grade] || '#64748b';
    }
    function trendColor(v) { return v > 0 ? '#f87171' : (v < 0 ? '#34d399' : '#94a3b8'); }
    function momTrendColor(trend) {
        return { strong_up: '#f87171', up: '#fb923c', neutral: '#94a3b8', down: '#34d399', strong_down: '#10b981' }[trend] || '#94a3b8';
    }

    // === 初始化 ===
    async function initPage() {
        datePicker.value = new Date().toISOString().split('T')[0];
        initCharts();
        renderGlossary();
        initGlossaryToggle();
        // V5.1 Fix P1#7: 先 loadRotationMatrix 获取 _lastFreshness，再 loadRegimeBanner
        await loadRotationMatrix();
        await loadChallengerPanel();
        loadRegimeBanner();
        if (currentCode) loadIndustryDetail(currentCode);
    }

    function initCharts() {
        charts.rps = AC.registerChart(echarts.init(document.getElementById('gauge-rps')));
        charts.value = AC.registerChart(echarts.init(document.getElementById('gauge-value')));
        charts.risk = AC.registerChart(echarts.init(document.getElementById('gauge-risk')));
        charts.rsLine = AC.registerChart(echarts.init(document.getElementById('rs-line-chart')));
        charts.heatmap = AC.registerChart(echarts.init(document.getElementById('heatmap-chart')));
    }

    // === V4.0 Regime Banner + V5.0 Data Freshness Badge (Fix5) ===
    let _lastFreshness = null;  // Fix5: 缓存 freshness 数据供 banner 使用

    async function loadRegimeBanner() {
        try {
            const res = await fetch('/api/v1/market/regime');
            const result = await res.json();
            if (result.status === 'ok') {
                const r = result;
                const banner = document.getElementById('regime-banner');
                if (!banner) return;
                const colorMap = { BULL: '#10b981', RANGE: '#f59e0b', BEAR: '#ef4444', CRASH: '#dc2626' };
                const bgMap = { BULL: 'rgba(16,185,129,0.08)', RANGE: 'rgba(245,158,11,0.08)', BEAR: 'rgba(239,68,68,0.08)', CRASH: 'rgba(220,38,38,0.12)' };
                const bc = colorMap[r.regime] || '#94a3b8';
                banner.style.borderColor = bc;
                banner.style.background = bgMap[r.regime] || 'rgba(148,163,184,0.05)';

                // Fix5: 数据新鲜度 badge
                let freshBadge = '';
                if (_lastFreshness && _lastFreshness.last_calc) {
                    const calcTime = new Date(_lastFreshness.last_calc);
                    const ageMin = isNaN(calcTime.getTime()) ? -1 : Math.round((Date.now() - calcTime.getTime()) / 60000);
                    const isStale = ageMin > 30;
                    const freshColor = ageMin < 0 ? '#94a3b8' : (isStale ? '#f59e0b' : '#10b981');
                    const freshIcon = ageMin < 0 ? '⏳' : (isStale ? '⚠️' : '✅');
                    const ageText = ageMin < 0 ? '计算中...' : (ageMin < 1 ? '刚刚' : (ageMin < 60 ? `${ageMin}分钟前` : `${Math.round(ageMin/60)}小时前`));
                    freshBadge = `<span style="font-size:0.72rem; padding:2px 10px; border-radius:6px; background:rgba(${ageMin < 0 ? '148,163,184' : (isStale ? '245,158,11' : '16,185,129')},0.1); color:${freshColor}; font-weight:600; margin-left:auto;">${freshIcon} 数据 ${ageText}</span>`;
                }

                const posLabel = r.decision_locked ? '仓位锁定' : '严格上限';
                const posColor = r.decision_locked ? '#ef4444' : bc;
                const posBg = r.decision_locked ? 'rgba(239,68,68,0.12)' : bgMap[r.regime];
                // 分层 tooltip: Regime Cap / AIAE Cap / 审计天花板
                let layerTooltip = `Regime: ${r.regime_cap ?? '--'}%`;
                if (r.aiae_cap != null) layerTooltip += ` · AIAE: ${r.aiae_cap}%`;
                layerTooltip += ` · 天花板: ${r.audit_cap ?? 95}%`;

                const policyLocked = _lastExecutionContext && _lastExecutionContext.decision_locked;
                const policyReason = policyLocked
                    ? (_lastExecutionContext.decision_lock_reasons || []).join(' / ')
                    : '';
                const regimeLifecycle = _lastExecutionContext?.regime_model_validation?.lifecycle;
                const policyText = regimeLifecycle === 'disabled'
                    ? '当前环境已禁用'
                    : (regimeLifecycle === 'shadow' ? '影子观察 · 不可执行' : '研究模式 · 不可执行');
                const policyBadge = policyLocked
                    ? `<span title="${escapeText(policyReason)}" style="font-size:0.72rem;padding:3px 9px;border-radius:6px;background:rgba(245,158,11,.12);color:#fbbf24;font-weight:700;">${policyText}</span>`
                    : '';
                banner.innerHTML = `
                    <span style="font-weight:800; color:${bc}; font-size:0.9rem;">${r.regime_icon || '🟡'} ${r.regime_cn || r.regime}</span>
                    <span style="color:#94a3b8; font-size:0.82rem;">CSI300 <b style="color:#e2e8f0">${r.csi300}</b> · MA120 ${r.ma120}</span>
                    <span style="color:#94a3b8; font-size:0.82rem;">5D <b style="color:${(r.ret5d || 0) < 0 ? '#34d399':'#e2e8f0'}">${r.ret5d !== undefined ? r.ret5d + '%' : '--'}</b></span>
                    <span style="color:#94a3b8; font-size:0.78rem;">门槛 ${r.score_gate ?? '--'} · 单行业 ${r.single_position_cap ?? '--'}% · 止损 -${r.stop_loss_pct ?? '--'}%</span>
                    <span title="${layerTooltip}" style="font-size:0.78rem; padding:3px 10px; border-radius:6px; background:${posBg}; color:${posColor}; font-weight:600; cursor:help;">${posLabel} ${r.pos_cap}%</span>
                    ${policyBadge}
                    ${freshBadge}
                `;
            }
        } catch(e) { console.log('Regime banner skipped:', e); }
    }

    // === V3.0 指标百科 ===
    function renderGlossary() {
        const grid = document.getElementById('glossary-grid');
        grid.innerHTML = GLOSSARY.map(g => `
            <div class="glossary-item">
                <div class="glossary-item-header">
                    <span class="glossary-item-name">${g.name}</span>
                    <span class="glossary-item-range">${g.range}</span>
                </div>
                <div class="glossary-item-desc">${g.desc}</div>
                <div class="glossary-item-warn">⚠️ 警示: ${g.warn}</div>
            </div>
        `).join('');
    }

    function initGlossaryToggle() {
        const toggle = document.getElementById('glossary-toggle');
        const drawer = document.getElementById('glossary-drawer');
        const drawerOverlay = document.getElementById('glossary-overlay');
        const closeBtn = document.getElementById('glossary-close');

        if (!localStorage.getItem('alphacore_glossary_seen')) {
            toggle.classList.add('pulse-hint');
            setTimeout(() => {
                toggle.classList.remove('pulse-hint');
                localStorage.setItem('alphacore_glossary_seen', '1');
            }, 6000);
        }

        function openDrawer() { drawer.classList.add('open'); drawerOverlay.classList.add('open'); }
        function closeDrawer() { drawer.classList.remove('open'); drawerOverlay.classList.remove('open'); }

        toggle.addEventListener('click', openDrawer);
        closeBtn.addEventListener('click', closeDrawer);
        drawerOverlay.addEventListener('click', closeDrawer);
        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
    }

    // === V4.0 导航条渲染 + 自动滚动聚焦 ===
    function renderSectorNav(rankData = []) {
        if (rankData.length > 0) {
            rankData.sort((a, b) => (b.alpha_score || 0) - (a.alpha_score || 0));
            if (!currentCode) currentCode = rankData[0]?.ts_code || rankData[0]?.code || SECTORS[0].code;
        }

        const orderedSectors = rankData.length > 0
            ? rankData.map(d => ({ code: d.ts_code || d.code, name: d.name }))
            : SECTORS;

        const rankMedals = ['🥇', '🥈', '🥉'];

        navContainer.innerHTML = orderedSectors.map((s, idx) => {
            const d = rankData.find(r => (r.ts_code === s.code || r.code === s.code)) || {};
            const trend = d.trend_5d || 0;
            const alpha = d.alpha_score || 0;
            const grade = d.alpha_grade || 'C';
            const heat = d.heat_score || 0;
            const gc = gradeColor(grade);
            const tc = trendColor(trend);
            const rankClass = idx < 3 ? `rank-top rank-${idx+1}` : '';
            const rankLabel = idx < 3 ? `${rankMedals[idx]}` : `#${idx+1}`;

            return `
                <div class="sector-tile ${s.code === currentCode ? 'active' : ''}" data-code="${s.code}" style="--tile-heat-color: ${gc};">
                    <span class="tile-rank ${rankClass}">${rankLabel}</span>
                    <div class="tile-alpha">
                        <span class="tile-alpha-score">${alpha.toFixed(0)}</span>
                        <span class="tile-grade grade-${grade}">${grade}</span>
                    </div>
                    <span class="tile-name">${s.name}</span>
                    <div class="tile-bottom">
                        <span class="tile-trend" style="color:${tc};">${trend > 0 ? '+' : ''}${trend.toFixed(1)}%</span>
                        <span class="tile-heat-label"><span class="tile-heat-dot"></span>${heat.toFixed(0)}</span>
                    </div>
                    <div class="tile-heat-bar"><div class="tile-heat-fill" style="width:${Math.min(100, alpha)}%; background:${gc};"></div></div>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.sector-tile').forEach(tile => {
            tile.addEventListener('click', () => {
                const code = tile.getAttribute('data-code');
                if (code === currentCode) return;
                document.querySelectorAll('.sector-tile').forEach(t => t.classList.remove('active'));
                tile.classList.add('active');
                currentCode = code;
                updateActiveCard();
                renderStrategyCard(code);
                loadIndustryDetail(code);
            });
        });
    }

    // V4.0: 自动滚动到选中tile
    function scrollToActiveTile() {
        const activeTile = document.querySelector('.sector-tile.active');
        if (activeTile) {
            activeTile.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
    }

    // === V4.0 Alpha Score 排行榜 (带stagger动画) ===
    function renderAlphaRanking(data) {
        const container = document.getElementById('alpha-ranking-list');
        const qualifiedCount = data.filter(d => d.policy_qualified).length;
        document.getElementById('alpha-a-count').textContent = `${qualifiedCount} 个条件达标`;

        container.innerHTML = data.map((d, idx) => {
            const gc = gradeColor(d.alpha_grade || 'C');
            const tc5 = trendColor(d.trend_5d);
            const tc20 = trendColor(d.ret_20d || 0);
            const code = d.ts_code || d.code;
            const circumference = 2 * Math.PI * 20;
            const offset = circumference - (circumference * (d.alpha_score || 0) / 100);
            const isActive = code === currentCode;

            // 风险警示标签
            const alertsHtml = (d.risk_alerts || []).map(a =>
                `<span class="risk-tag ${a.level}">${a.icon} ${a.text}</span>`
            ).join('');

            // V4.0: Mini factor bars (紧凑模式可见)
            const fBars = [
                { label: '热', val: d.f_heat || 0, color: '#f87171' },
                { label: '动', val: d.f_momentum || 0, color: '#3b82f6' },
                { label: '位', val: d.f_price_position_safety ?? d.f_valuation ?? 0, color: '#10b981' },
                { label: '趋', val: d.f_trend || 0, color: '#a78bfa' }
            ];
            const miniBarsHtml = `<div class="mini-factor-bars">
                ${fBars.map(f => `<div class="mini-bar-item">
                    <span class="mini-bar-label">${f.label}</span>
                    <div class="mini-bar-track"><div class="mini-bar-fill" style="width:${Math.min(100,f.val)}%;background:${f.color};opacity:${f.val>=60?1:0.4}"></div></div>
                    <span class="mini-bar-val" style="color:${f.val>=60?f.color:'#64748b'}">${f.val.toFixed(0)}</span>
                </div>`).join('')}
            </div>`;

            return `
                <div class="alpha-card grade-${d.alpha_grade || 'C'} ${isActive ? 'active-card' : ''}" data-code="${code}" style="animation-delay:${idx * 60}ms">
                    <div class="alpha-card-top">
                        <div class="alpha-card-info">
                            <span class="alpha-card-rank">#${idx+1}</span>
                            <span class="alpha-card-name">${d.name}</span>
                            <div class="alpha-card-trends">
                                <span style="color:${tc5};">${d.trend_5d > 0 ? '+' : ''}${d.trend_5d.toFixed(1)}%<small style="opacity:0.5">5D</small></span>
                                <span style="color:${tc20};">${(d.ret_20d||0) > 0 ? '+' : ''}${(d.ret_20d||0).toFixed(1)}%<small style="opacity:0.5">20D</small></span>
                            </div>
                        </div>
                        <div class="alpha-ring-wrap">
                            <svg viewBox="0 0 48 48">
                                <circle class="alpha-ring-bg" cx="24" cy="24" r="20" />
                                <circle class="alpha-ring-fill" cx="24" cy="24" r="20"
                                    stroke="${gc}"
                                    stroke-dasharray="${circumference}"
                                    stroke-dashoffset="${offset}" />
                            </svg>
                            <span class="alpha-ring-text">${(d.alpha_score||0).toFixed(0)}</span>
                            <span class="alpha-ring-grade" style="background:${gc};">${d.alpha_grade||'C'}</span>
                        </div>
                    </div>

                    ${miniBarsHtml}

                    <div class="alpha-strategy">
                        <div class="alpha-strat-row">
                            <span class="alpha-strat-icon">💡</span>
                            <span class="alpha-strat-text"><b>资格:</b> ${d.buy_strategy || '—'}</span>
                        </div>
                        <div class="alpha-strat-row">
                            <span class="alpha-strat-icon">🎯</span>
                            <span class="alpha-strat-text"><b>止盈:</b> ${d.take_profit || '—'}</span>
                        </div>
                    </div>

                    ${alertsHtml ? `<div class="risk-tags">${alertsHtml}</div>` : ''}

                    <div class="alpha-advice-row" style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:0.75rem; color:#94a3b8; font-style:italic;">${d.advice || ''}</span>
                        <span class="alpha-advice-label ${d.advice_action || 'neutral'}">${d.advice_label || ''}</span>
                    </div>
                </div>
            `;
        }).join('');

        // 卡片点击事件
        document.querySelectorAll('.alpha-card').forEach(card => {
            card.addEventListener('click', () => {
                const code = card.getAttribute('data-code');
                if (code === currentCode) return;
                currentCode = code;
                document.querySelectorAll('.sector-tile').forEach(t => {
                    t.classList.toggle('active', t.getAttribute('data-code') === code);
                });
                updateActiveCard();
                renderStrategyCard(code);
                loadIndustryDetail(code);
                scrollToActiveTile();
            });
        });
    }

    function updateActiveCard() {
        document.querySelectorAll('.alpha-card').forEach(c => {
            c.classList.toggle('active-card', c.getAttribute('data-code') === currentCode);
        });
    }

    // === V3.1 因子进度条可视化 ===
    function renderFactorBars(d) {
        const factors = [
            { label: '热度', value: d.f_heat || 0, color: '#f87171', weight: '30%' },
            { label: '动量', value: d.f_momentum || 0, color: '#3b82f6', weight: '25%' },
            { label: '价格位置安全', value: d.f_price_position_safety ?? d.f_valuation ?? 0, color: '#10b981', weight: '25%' },
            { label: '趋势', value: d.f_trend || 0, color: '#a78bfa', weight: '20%' }
        ];
        return factors.map(f => {
            const v = Math.min(100, Math.max(0, f.value));
            const opacity = v >= 60 ? 1 : 0.5;
            return `<div class="factor-bar-wrap">
                <span class="factor-bar-label">${f.label} <small style="opacity:0.5">${f.weight}</small></span>
                <div class="factor-bar-track">
                    <div class="factor-bar-fill" style="width:${v}%; background:${f.color}; opacity:${opacity};"></div>
                </div>
                <span class="factor-bar-value" style="color:${v>=60?f.color:'#64748b'}">${v.toFixed(0)}</span>
            </div>`;
        }).join('');
    }

    // === V3.1 策略操作卡 ===
    function renderStrategyCard(code) {
        const d = allSectorData.find(s => (s.ts_code === code || s.code === code));
        if (!d) return;

        const gc = gradeColor(d.alpha_grade || 'C');
        const badge = document.getElementById('soc-grade-badge');
        badge.textContent = `${d.alpha_grade || 'C'} · ${(d.alpha_score||0).toFixed(0)}分`;
        badge.className = `soc-grade-badge grade-${d.alpha_grade || 'C'}`;
        document.getElementById('soc-sector-name').textContent = `📋 ${d.name} · 执行资格审查`;
        document.getElementById('strategy-ops-card').style.setProperty('--grade-color', gc);

        const alerts = (d.risk_alerts || []).map(a =>
            `<li style="color:${a.level==='danger'?'#f87171':(a.level==='positive'?'#34d399':'#fbbf24')}">${a.icon} ${a.text}</li>`
        ).join('') || '<li style="color:#34d399">✅ 暂无风险警示</li>';
        const ex = d.execution || {};
        const checks = d.eligibility_checks || {};
        const pass = value => value ? '✅' : '❌';
        const vetoes = (d.veto_reasons || []).length
            ? (d.veto_reasons || []).map(reason => candidateConditionLabel(reason, {
                ...d,
                min_median_turnover_cny: ex.min_median_turnover_cny
            })).join(' / ')
            : '无';
        const lockReasons = (d.decision_lock_reasons || []).length
            ? (d.decision_lock_reasons || []).join(' / ')
            : '无';

        document.getElementById('soc-body').innerHTML = `
            <div class="soc-fade-in">
            <div class="soc-section">
                <div class="soc-section-title buy">🧭 执行资格</div>
                <ul class="soc-content">
                    <li><b>当前结论:</b> ${d.advice_label || '—'} · ${d.advice || '—'}</li>
                    <li><b>动态门槛:</b> ${ex.regime || '--'} / Alpha ${checks.score ?? '--'} ≥ ${ex.score_gate ?? '--'} ${pass(checks.score_pass)}</li>
                    <li><b>趋势确认:</b> MA20 ${pass(checks.above_ma20)} · MA60 ${pass(checks.above_ma60)} · MA20斜率 ${pass(checks.ma20_slope_pass)}</li>
                    <li><b>成交容量:</b> 20日中位额 ${formatCny(ex.median_turnover_cny)} ${pass(checks.liquidity_median_turnover_pass)} · 2%参与率单次上限 ${formatCny(ex.capacity_at_participation_cny)}</li>
                    <li><b>订单放行:</b> ${ex.order_release_allowed ? '✅ 已放行' : '⏸️ 未放行'}${ex.pretrade_quote_required ? ' · 须在下单前核验实时价格、停牌与申赎状态' : ''}</li>
                    <li><b>否决原因:</b> ${vetoes}</li>
                    <li><b>系统锁:</b> ${lockReasons}</li>
                    <li><b>建仓规则:</b> ${d.buy_strategy || '—'}</li>
                    <li><b>仓位上限:</b> ${d.position_cap || '—'}；组合上限 ${ex.effective_total_cap ?? 0}%</li>
                </ul>
            </div>
            <div class="soc-divider"></div>
            <div class="soc-section">
                <div class="soc-section-title profit">🎯 止盈策略</div>
                <ul class="soc-content">
                    <li>${d.take_profit || '—'}</li>
                </ul>
            </div>
            <div class="soc-divider"></div>
            <div class="soc-section">
                <div class="soc-section-title profit" style="color:#f59e0b;">🛑 止损策略</div>
                <ul class="soc-content">
                    <li>${d.stop_loss || '—'}</li>
                </ul>
            </div>
            <div class="soc-divider"></div>
            <div class="soc-section">
                <div class="soc-section-title risk">⚠️ 风险警示</div>
                <ul class="soc-content">${alerts}</ul>
            </div>
            <div style="margin-top:12px; padding:14px; border-radius:10px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04);">
                <div style="font-size:0.72rem; color:#64748b; margin-bottom:10px;">Alpha Score 因子拆解</div>
                ${renderFactorBars(d)}
            </div>
            </div>
        `;
    }

    // === V5.0 热力矩阵 (5维: +趋势强度) — Fix4 ===
    function renderHeatmapChart(data) {
        if (!data || data.length === 0) return;
        // V6.0: 热力矩阵使用短名，避免16+标签在X轴挤压重叠
        const names = data.map(d => {
            const n = d.name;
            if (n.includes('/')) return n.split('/')[0];
            return n.length > 4 ? n.substring(0, 4) : n;
        });
        const fullNames = data.map(d => d.name);  // tooltip 用全名
        const dims = ['Alpha研究分', '热度', '动量', '价格位置安全', '趋势强度'];
        const gradeLabels = { 0: '极弱', 20: '弱', 40: '偏弱', 50: '中性', 60: '偏强', 75: '强', 90: '极强' };
        const heatData = [];

        function getGradeLabel(val) {
            const thresholds = [90, 75, 60, 50, 40, 20, 0];
            for (const t of thresholds) { if (val >= t) return gradeLabels[t]; }
            return '极弱';
        }

        data.forEach((d, xi) => {
            const scores = [
                d.alpha_score || 0,
                d.heat_score || 0,
                d.f_momentum || 50,
                d.f_price_position_safety ?? d.f_valuation ?? 50,
                d.f_trend || 0    // Fix4: 新增趋势强度维度
            ];
            scores.forEach((val, yi) => {
                heatData.push([xi, yi, Math.round(val)]);
            });
        });

        charts.heatmap.setOption({
            tooltip: {
                position: 'top',
                backgroundColor: 'rgba(10, 10, 10, 0.92)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#fff', fontSize: 12 },
                formatter: p => {
                    const val = p.data[2];
                    const grade = getGradeLabel(val);
                    return `<b>${fullNames[p.data[0]]}</b><br/>${dims[p.data[1]]}: <b>${val}</b> <span style="opacity:0.6">(${grade})</span>`;
                }
            },
            grid: { top: 10, bottom: 70, left: 80, right: 20 },
            xAxis: {
                type: 'category',
                data: names,
                axisLabel: { color: '#cbd5e1', fontSize: 9, rotate: 45, interval: 0 },
                splitArea: { show: false }
            },
            yAxis: {
                type: 'category',
                data: dims,
                axisLabel: { color: '#cbd5e1', fontSize: 11 },
                splitArea: { show: false }
            },
            visualMap: {
                min: 0, max: 100,
                calculable: false,
                orient: 'horizontal',
                left: 'center',
                bottom: 0,
                itemWidth: 14, itemHeight: 100,
                textStyle: { color: '#94a3b8', fontSize: 10 },
                inRange: {
                    color: ['#1e293b', '#1e3a5f', '#1d4ed8', '#059669', '#10b981', '#fbbf24', '#ef4444']
                }
            },
            series: [{
                type: 'heatmap',
                data: heatData,
                label: {
                    show: true,
                    color: '#fff',
                    fontSize: 11,
                    fontWeight: 700,
                    fontFamily: 'Outfit'
                },
                emphasis: {
                    itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' }
                },
                itemStyle: { borderColor: 'rgba(7,9,14,0.8)', borderWidth: 3, borderRadius: 4 }
            }]
        });
        // V6.0: 延迟触发 resize 确保 16 只 ETF 尺寸计算准确
        setTimeout(() => charts.heatmap.resize(), 200);
    }

    // === ECharts 仪表盘配置 (AIAE 温度计风格) ===
    function getGaugeOption(name, value, color, unit = '') {
        // 各指标专属色段与量程
        const gaugeProfiles = {
            RPS: {
                max: 100,
                colors: [
                    [0.30, '#ef4444'],  // 0-30: 极弱 (红)
                    [0.50, '#f97316'],  // 30-50: 偏弱 (橙)
                    [0.70, '#eab308'],  // 50-70: 中性 (黄)
                    [0.80, '#3b82f6'],  // 70-80: 偏强 (蓝)
                    [1.00, '#10b981']   // 80-100: 极强 (绿)
                ],
                splitNumber: 5,
                labels: {0:'0',20:'20',40:'40',60:'60',80:'80',100:'100'}
            },
            Value: {
                max: 100,
                colors: [
                    [0.20, '#10b981'],  // 0-20: 极度低估 (绿)
                    [0.30, '#3b82f6'],  // 20-30: 低估 (蓝)
                    [0.60, '#eab308'],  // 30-60: 合理 (黄)
                    [0.80, '#f97316'],  // 60-80: 偏高 (橙)
                    [1.00, '#ef4444']   // 80-100: 极贵 (红)
                ],
                splitNumber: 5,
                labels: {0:'0',20:'20',40:'40',60:'60',80:'80',100:'100'}
            },
            Risk: {
                max: 3,
                colors: [
                    [0.27, '#10b981'],  // 0-0.8: 健康 (绿)
                    [0.50, '#3b82f6'],  // 0.8-1.5: 正常 (蓝)
                    [0.67, '#eab308'],  // 1.5-2.0: 偏热 (黄)
                    [0.83, '#f97316'],  // 2.0-2.5: 拥挤 (橙)
                    [1.00, '#ef4444']   // 2.5-3.0: 极度拥挤 (红)
                ],
                splitNumber: 6,
                labels: {0:'0',0.5:'0.5',1:'1',1.5:'1.5',2:'2',2.5:'2.5',3:'3'}
            }
        };

        const profile = gaugeProfiles[name] || gaugeProfiles.RPS;
        const clampedValue = Math.min(Math.max(value, 0), profile.max);

        return {
            series: [{
                type: 'gauge',
                startAngle: 200,
                endAngle: -20,
                min: 0,
                max: profile.max,
                radius: '92%',
                center: ['50%', '68%'],
                pointer: {
                    show: true,
                    length: '55%',
                    width: 3.5,
                    itemStyle: {
                        color: color,
                        shadowColor: color,
                        shadowBlur: 8
                    },
                    icon: 'triangle'
                },
                anchor: {
                    show: true,
                    size: 7,
                    itemStyle: {
                        color: '#0f172a',
                        borderColor: color,
                        borderWidth: 2
                    }
                },
                axisLine: {
                    lineStyle: {
                        width: 12,
                        color: profile.colors
                    }
                },
                axisTick: {
                    length: 5,
                    distance: -12,
                    lineStyle: { color: 'auto', width: 1 }
                },
                splitLine: {
                    length: 9,
                    distance: -12,
                    lineStyle: { color: 'auto', width: 1.5 }
                },
                splitNumber: profile.splitNumber,
                axisLabel: {
                    distance: -28,
                    color: '#64748b',
                    fontSize: 8,
                    fontFamily: 'Outfit',
                    // Fix2: 容差匹配，解决浮点精度导致轴标签消失的问题
                    formatter: function(val) {
                        const keys = Object.keys(profile.labels).map(Number);
                        for (let i = 0; i < keys.length; i++) {
                            if (Math.abs(val - keys[i]) < 0.01) return profile.labels[keys[i]];
                        }
                        return '';
                    }
                },
                detail: {
                    valueAnimation: true,
                    offsetCenter: [0, '30%'],
                    fontSize: 20,
                    fontWeight: '800',
                    color: '#fff',
                    fontFamily: 'Outfit',
                    formatter: `{value}${unit}`
                },
                data: [{ value: clampedValue }],
                animationDuration: 1000,
                animationEasingUpdate: 'cubicOut'
            }]
        };
    }

    // === V5.0 加载行业详情 (Fix6: skeleton loading + 适配新数据结构) ===
    function showDetailSkeleton() {
        // Fix6: 在 fetch 前显示骨架屏，避免旧数据→新数据的跳变
        document.querySelectorAll('.metric-row .metric-card').forEach(card => {
            card.classList.add('skeleton-loading');
        });
        const rsChart = document.getElementById('rs-line-chart');
        if (rsChart) rsChart.style.opacity = '0.3';
        const listEl = document.getElementById('list-constituents');
        if (listEl) listEl.style.opacity = '0.3';
    }
    function hideDetailSkeleton() {
        document.querySelectorAll('.metric-row .metric-card').forEach(card => {
            card.classList.remove('skeleton-loading');
        });
        const rsChart = document.getElementById('rs-line-chart');
        if (rsChart) rsChart.style.opacity = '1';
        const listEl = document.getElementById('list-constituents');
        if (listEl) listEl.style.opacity = '1';
    }

    async function loadIndustryDetail(code) {
        showDetailSkeleton();  // Fix6: 进入 loading 态
        try {
            const res = await fetch(`/api/v1/industry-detail?code=${code}`);
            const result = await res.json();
            if (result.status === 'success') {
                const data = result.data;
                const m = data.metrics;

                charts.rps.setOption(getGaugeOption('RPS', m.rps, m.rps > 80 ? '#3b82f6' : (m.rps < 30 ? '#ef4444' : '#94a3b8')));
                const pricePct = m.price_percentile ?? m.pe_percentile;
                charts.value.setOption(getGaugeOption('Price Pos.', pricePct, pricePct > 70 ? '#ef4444' : (pricePct < 30 ? '#10b981' : '#f59e0b'), '%'));
                charts.risk.setOption(getGaugeOption('Risk', m.crowding, m.crowding > 1.5 ? '#ef4444' : '#6366f1', 'x'));

                // V4.0: 20D动量趋势卡 (替代北向资金)
                const mom20d = m.momentum_20d || {};
                const momEl = document.getElementById('val-mom20d');
                const momDescEl = document.getElementById('desc-mom20d');
                if (momEl) {
                    const momColor = momTrendColor(mom20d.trend);
                    momEl.textContent = mom20d.ret_20d !== undefined ? `${mom20d.ret_20d > 0 ? '+' : ''}${mom20d.ret_20d.toFixed(1)}%` : '--';
                    momEl.style.color = momColor;
                }
                if (momDescEl) {
                    momDescEl.textContent = mom20d.label || '—';
                }

                document.getElementById('desc-rps').innerHTML = `<span style="color:${m.rps > 80 ? '#3b82f6' : (m.rps < 30 ? '#ef4444':'#94a3b8')}">${m.rps > 80 ? "🔥 强势领涨" : (m.rps < 30 ? "⚠️ 极度弱势" : "🛡️ 震荡蓄势")}</span>`;
                document.getElementById('desc-value').innerHTML = `<span style="color:${pricePct < 30 ? '#10b981' : (pricePct > 70 ? '#ef4444' : '#f59e0b')}">${pricePct < 30 ? "📉 历史低位" : (pricePct > 70 ? "⚠️ 位置偏高" : "⚖️ 中部区间")}</span>`;
                document.getElementById('desc-risk').innerHTML = `<span style="color:${m.crowding > 1.5 ? '#ef4444' : '#6366f1'}">${m.crowding > 1.5 ? "🚫 极其拥挤" : "✅ 筹码健康"}</span>`;

                // V3.1: 仪表盘动态风险边框
                const metricCards = document.querySelectorAll('.metric-row .metric-card');
                if (metricCards[0]) {
                    metricCards[0].classList.remove('metric-danger','metric-safe','metric-warn');
                    if (m.rps > 80) metricCards[0].classList.add('metric-safe');
                    else if (m.rps < 30) metricCards[0].classList.add('metric-danger');
                }
                if (metricCards[1]) {
                    metricCards[1].classList.remove('metric-danger','metric-safe','metric-warn');
                    if (pricePct > 70) metricCards[1].classList.add('metric-danger');
                    else if (pricePct < 30) metricCards[1].classList.add('metric-safe');
                    else metricCards[1].classList.add('metric-warn');
                }
                if (metricCards[2]) {
                    metricCards[2].classList.remove('metric-danger','metric-safe','metric-warn');
                    if (m.crowding > 1.5) metricCards[2].classList.add('metric-danger');
                    else if (m.crowding > 1.2) metricCards[2].classList.add('metric-warn');
                    else metricCards[2].classList.add('metric-safe');
                }

                // RS Line Chart
                if (data.chart_data && data.chart_data.dates.length > 0) {
                    charts.rsLine.setOption({
                        tooltip: { trigger: 'axis', backgroundColor: 'rgba(10,10,10,0.85)', borderColor: 'rgba(255,255,255,0.1)', textStyle: { color: '#fff' } },
                        grid: { top: 30, bottom: 30, left: 45, right: 20 },
                        xAxis: { type: 'category', data: data.chart_data.dates.map(d => String(d).substring(4)), axisLabel: { color: '#64748b', fontSize: 10 } },
                        yAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
                        legend: { data: ['中枢价格', '相对强度(RS)'], textStyle: { color: '#94a3b8', fontSize: 10 }, right: 0, icon: 'circle' },
                        series: [
                            { name: '中枢价格', type: 'line', data: data.chart_data.prices, itemStyle: { color: '#3b82f6' }, smooth: true, showSymbol: false, areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [{offset:0, color:'rgba(59,130,246,0.15)'},{offset:1, color:'transparent'}]) } },
                            { name: '相对强度(RS)', type: 'line', data: data.chart_data.relative_strength, itemStyle: { color: '#10b981' }, smooth: true, showSymbol: false }
                        ]
                    });
                }

                // 官方跟踪指数成分；失效时禁止回退到静态猜测。
                const listEl = document.getElementById('list-constituents');
                const constituentSnapshot = m.constituent_snapshot || {};
                const constituents = Array.isArray(m.constituents) ? m.constituents : [];
                const constituentIssueLabels = {
                    CONSTITUENT_SNAPSHOT_MISSING: '官方成分快照尚未生成',
                    CONSTITUENT_SNAPSHOT_INVALID: '官方成分快照不可读',
                    CONSTITUENT_SNAPSHOT_INTEGRITY_FAILED: '成分快照完整性校验失败',
                    CONSTITUENT_ETF_NOT_FOUND: '快照中缺少该ETF',
                    TRACKING_INDEX_MISSING: '缺少真实跟踪指数代码',
                    INDEX_WEIGHT_UNAVAILABLE: '官方指数权重暂不可用',
                    INDEX_WEIGHT_SCHEMA_INVALID: '官方权重字段不完整',
                    INDEX_WEIGHT_DATE_INVALID: '官方权重日期无效',
                    INDEX_CONSTITUENT_CODE_INVALID: '成分证券代码无效',
                    INDEX_CONSTITUENT_DUPLICATE: '成分证券存在重复',
                    INDEX_WEIGHT_VALUE_INVALID: '成分权重存在非法值',
                    INDEX_CONSTITUENT_COUNT_TOO_SMALL: '成分数量异常不足',
                    INDEX_WEIGHT_SUM_INVALID: '权重合计未通过完整性门槛',
                    INDEX_WEIGHT_STALE: '官方指数权重已超过45天'
                };
                const identityHtml = `
                    <div class="constituent-lineage ${constituentSnapshot.is_verified ? 'is-verified' : 'is-unverified'}">
                        <strong>${escapeText(constituentSnapshot.instrument_name || 'ETF身份待核验')}</strong>
                        <span>跟踪：${escapeText(constituentSnapshot.tracking_index_name || '—')} · ${escapeText(constituentSnapshot.tracking_index_code || '—')}</span>
                        <span>${constituentSnapshot.is_verified ? '✓ 官方月度权重' : '× 权重不可验证'} · 截至 ${escapeText(constituentSnapshot.as_of || '—')}</span>
                    </div>
                `;
                if (constituentSnapshot.is_verified === true && constituents.length) {
                    listEl.innerHTML = identityHtml + constituents.map(c => `
                        <div class="constituent-item">
                            <span class="constituent-name">● ${escapeText(c.name)} <small>${escapeText(c.code)}</small></span>
                            <span class="constituent-weight">${escapeText(Number(c.weight_pct).toFixed(2))}%</span>
                        </div>
                    `).join('') + `<div class="constituent-source">来源：指数公司公开月度权重，经 Tushare index_weight 获取并通过哈希校验</div>`;
                } else {
                    const issues = (constituentSnapshot.issues || [])
                        .map(reason => constituentIssueLabels[reason] || reason)
                        .join('；');
                    listEl.innerHTML = identityHtml + `
                        <div class="constituent-unavailable">🔒 ${escapeText(issues || '成分数据不可验证')}<br><small>已停止展示代码内静态权重，避免形成错误持仓判断。</small></div>
                    `;
                }
            }
        } catch (err) { console.error('Detail load error:', err); }
        finally { hideDetailSkeleton(); }  // Fix6: 无论成功失败都移除骨架屏
    }

    // === 加载轮动矩阵 + Alpha 排行 (Fix5: 抓取 freshness) ===
    async function loadRotationMatrix() {
        try {
            // V5.1 Fix P1#14: 将日期选择器的值传递到 API
            const dateParam = datePicker.value ? `?date=${datePicker.value}` : '';
            const res = await fetch(`/api/v1/industry-tracking${dateParam}`);
            const result = await res.json();
            if (result.status === 'success') {
                allSectorData = result.data.sector_heatmap;
                _lastExecutionContext = result.data.execution_context || null;
                renderValidationStrip(_lastExecutionContext);
                renderAbstentionPlan(result.data.abstention_plan, _lastExecutionContext);

                // Fix5: 缓存 freshness 供 regime banner 使用
                if (result.data_freshness) {
                    _lastFreshness = result.data_freshness;
                    loadRegimeBanner();  // 刷新 banner 以显示最新 freshness
                }

                // V4.0: 渲染四大组件
                renderSectorNav(allSectorData);
                renderAlphaRanking(allSectorData);
                renderHeatmapChart(allSectorData);

                // 自动选中排名第一并渲染策略卡
                if (allSectorData.length > 0 && currentCode) {
                    renderStrategyCard(currentCode);
                }
            }
        } catch (err) {
            console.error('Rotation load error:', err);
            const panel = document.getElementById('industry-abstention-panel');
            if (panel) {
                panel.innerHTML = `<div class="abstention-panel__loading">⚠️ 不交易决策包读取失败：${escapeText(err.message)}</div>`;
            }
        }
    }

    // === 同步数据 (V6.1: 简化认证流, 增强反馈) ===
    async function syncData() {
        if (!confirm(`确定要同步全量产业情报？\n将触发 ${SECTORS.length} 个核心 ETF 数据深度抓取，约需 15-30 秒。`)) return;

        overlay.style.display = 'flex';
        syncBtn.disabled = true;
        syncBtn.textContent = '⏳ 同步中...';
        try {
            // V6.1: 直接 fetch，从 localStorage 读取 API Key（如有）
            const headers = {};
            let apiKey = localStorage.getItem('alphacore_api_key');
            if (!apiKey) {
                apiKey = prompt("🔐 首次同步需要输入系统 API Key：\n（输入后会自动保存，后续无需重复输入）");
                if (!apiKey) {
                    alert("操作已取消：未提供 API Key。");
                    return;
                }
                localStorage.setItem('alphacore_api_key', apiKey);
            }
            headers['X-API-Key'] = apiKey;

            const res = await fetch('/api/v1/sync/industry', {
                method: 'POST',
                headers: headers
            });

            if (res.status === 401 || res.status === 403) {
                localStorage.removeItem('alphacore_api_key');
                alert("🔒 API Key 无效，已清除缓存。请重新点击同步并输入正确的 Key。");
                return;
            }

            const result = await res.json();
            if (result.status === 'success') {
                alert(`✅ 同步成功！最新数据截至: ${result.last_date || '—'}`);
            } else {
                alert("⚠️ 同步完成但返回异常，请刷新页面查看。");
            }
            await loadRotationMatrix();
            loadIndustryDetail(currentCode);
        } catch (err) {
            console.error("同步异常", err);
            alert("❌ 同步失败: " + (err.message || err));
        } finally {
            overlay.style.display = 'none';
            syncBtn.disabled = false;
            syncBtn.textContent = '⚡ 同步情报';
        }
    }

    syncBtn.addEventListener('click', syncData);
    initPage();
    // resize 由 AC (alphacore_utils.js) 统一管理
});
