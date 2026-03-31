/**
 * AlphaCore Backtest Terminal V5.0 — Premium Upgrade
 * - Production-grade strategy params (MR V4.2 / Div V4.0 / Mom V3.0)
 * - Regime Preset Buttons (BEAR / RANGE / BULL one-click)
 * - Auto-ticker fill on strategy switch
 * - Radar 6-Dimension Grade Visualization
 * - Structured Diagnosis Cards (success/warning/danger)
 * - Alpha / Information Ratio metric cards
 * - Trade Log with per-SELL PnL + CSV Export
 * - Monthly Heatmap with Annual Summary Column
 * - Annual Statistics Bar Chart (V5.0)
 * - Block Bootstrap Monte Carlo 500x with Ruin Probability (FIXED rendering)
 * - Chart linking (equity ↔ drawdown bidirectional sync)
 * - Premium stagger entrance animations & glow effects
 * - Multi-step loading progress bar
 */

window.onerror = function(msg, url, line, col, error) {
    if (typeof msg === 'string' && msg.includes('ResizeObserver')) return true;
    console.error(`[Runtime Error] ${msg} at ${line}:${col}`, error);
    return false;
};

document.addEventListener('DOMContentLoaded', function() {
    console.log(">>> [AlphaCore] Backtest V5.0 Ready — Premium Terminal");

    // === DOM References ===
    const runBtn = document.getElementById('run-backtest-btn');
    const overlay = document.getElementById('loading-overlay');
    const errorContainer = document.getElementById('error-container');
    const errorMessage = document.getElementById('error-message');
    const strategySelect = document.getElementById('strategy-select');
    const emptyState = document.getElementById('empty-state');
    const resultsArea = document.getElementById('results-area');
    const drawerOverlay = document.getElementById('drawer-overlay');
    const configDrawer = document.getElementById('config-drawer');
    const drawerToggle = document.getElementById('drawer-toggle-btn');
    const drawerClose = document.getElementById('drawer-close-btn');

    let charts = { equity: null, drawdown: null, mc: null, heatmap: null, radar: null, annual: null };
    let isRunning = false;
    let currentTradeLog = []; // V5.0: store for CSV export

    // === Strategy Parameter Definitions (V4.0: 与策略中心生产引擎完全对齐) ===
    const STRATEGY_PARAMS = {
        mr: {
            label: '均值回归 V4.2',
            icon: '📐',
            desc: 'RSI(14) 超卖 + BIAS 乖离率 + 趋势过滤 + 硬止损',
            defaultTicker: '510300.SH',
            params: [
                { key: 'N_trend',    label: '趋势均线周期', min: 20, max: 200, step: 10, default: 90 },
                { key: 'rsi_period', label: 'RSI 周期',     min: 7,  max: 21,  step: 1,  default: 14 },
                { key: 'rsi_buy',    label: 'RSI 买入 ≤',   min: 20, max: 50,  step: 1,  default: 35 },
                { key: 'rsi_sell',   label: 'RSI 卖出 ≥',   min: 55, max: 90,  step: 1,  default: 70 },
                { key: 'bias_buy',   label: 'BIAS 乖离 ≤',  min: -50, max: 0,  step: 5,  default: -20 },
                { key: 'stop_loss',  label: '止损线 %',      min: 3,  max: 15,  step: 1,  default: 7 }
            ],
            presets: {
                BEAR:  { N_trend: 40,  rsi_period: 14, rsi_buy: 45, rsi_sell: 65, bias_buy: -30, stop_loss: 5 },
                RANGE: { N_trend: 90,  rsi_period: 14, rsi_buy: 35, rsi_sell: 70, bias_buy: -20, stop_loss: 7 },
                BULL:  { N_trend: 120, rsi_period: 14, rsi_buy: 45, rsi_sell: 75, bias_buy: -15, stop_loss: 6 }
            }
        },
        div: {
            label: '红利趋势 V4.0',
            icon: '💰',
            desc: 'RSI(9) 超卖 + 股息托底 + 布林带 + 四态自适应',
            defaultTicker: '515100.SH',
            params: [
                { key: 'ma_trend',   label: '趋势均线',     min: 30, max: 120, step: 10, default: 60 },
                { key: 'rsi_period', label: 'RSI 周期',     min: 5,  max: 14,  step: 1,  default: 9 },
                { key: 'rsi_buy',    label: 'RSI 买入 ≤',   min: 20, max: 45,  step: 1,  default: 35 },
                { key: 'rsi_sell',   label: 'RSI 卖出 ≥',   min: 65, max: 90,  step: 1,  default: 75 },
                { key: 'bias_buy',   label: 'BIAS 乖离 ≤',  min: -50, max: 0,  step: 5,  default: -20 },
                { key: 'ma_defend',  label: '防守均线',      min: 10, max: 60,  step: 5,  default: 30 },
                { key: 'stop_loss',  label: '止损线 %',      min: 3,  max: 12,  step: 1,  default: 6 }
            ],
            presets: {
                BEAR:  { ma_trend: 90, rsi_period: 9, rsi_buy: 30, rsi_sell: 70, bias_buy: -30, ma_defend: 40, stop_loss: 5 },
                RANGE: { ma_trend: 60, rsi_period: 9, rsi_buy: 35, rsi_sell: 75, bias_buy: -20, ma_defend: 30, stop_loss: 6 },
                BULL:  { ma_trend: 60, rsi_period: 9, rsi_buy: 40, rsi_sell: 80, bias_buy: -15, ma_defend: 20, stop_loss: 6 }
            }
        },
        mom: {
            label: '动量轮动 V3.0',
            icon: '🚀',
            desc: '短期+中期动量 + 趋势斜率 + 波动率过滤',
            defaultTicker: '512480.SH',
            params: [
                { key: 'lookback_s',          label: '短期动量窗口', min: 5,  max: 40, step: 5,  default: 20 },
                { key: 'lookback_m',          label: '中期动量窗口', min: 20, max: 120,step: 10, default: 60 },
                { key: 'momentum_threshold',  label: '动量入场 %',   min: 0,  max: 10, step: 1,  default: 2 },
                { key: 'stop_loss',           label: '止损线 %',     min: 3,  max: 12, step: 1,  default: 7 }
            ],
            presets: {
                BEAR:  { lookback_s: 20, lookback_m: 60, momentum_threshold: 5, stop_loss: 5 },
                RANGE: { lookback_s: 20, lookback_m: 60, momentum_threshold: 2, stop_loss: 7 },
                BULL:  { lookback_s: 20, lookback_m: 60, momentum_threshold: 0, stop_loss: 8 }
            }
        }
    };

    // === Drawer Toggle ===
    function openDrawer() {
        configDrawer.classList.add('open');
        drawerOverlay.classList.add('open');
    }
    function closeDrawer() {
        configDrawer.classList.remove('open');
        drawerOverlay.classList.remove('open');
    }
    drawerToggle.addEventListener('click', openDrawer);
    drawerClose.addEventListener('click', closeDrawer);
    drawerOverlay.addEventListener('click', closeDrawer);

    // === Strategy Params Panel (V4.0: Regime 预设 + 策略描述) ===
    function renderStrategyParams(stratKey) {
        const panel = document.getElementById('strategy-params-panel');
        const config = STRATEGY_PARAMS[stratKey];
        if (!panel || !config) return;

        // Strategy description bar
        let html = `<div class="strategy-desc-bar">
            <span class="strategy-icon">${config.icon || '📊'}</span>
            <span class="strategy-desc-text">${config.desc || ''}</span>
        </div>`;

        // Regime preset buttons
        if (config.presets) {
            html += `<div class="regime-presets">
                <span class="preset-label">Regime 预设</span>
                <button class="preset-btn preset-bear" onclick="applyPreset('BEAR')">🐻 BEAR</button>
                <button class="preset-btn preset-range active" onclick="applyPreset('RANGE')">📊 RANGE</button>
                <button class="preset-btn preset-bull" onclick="applyPreset('BULL')">🐂 BULL</button>
            </div>`;
        }

        // Parameter sliders
        html += config.params.map(p => `
            <div class="param-row">
                <label>${p.label}</label>
                <input type="range" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}"
                       id="param-${p.key}" data-key="${p.key}"
                       oninput="handleParamChange(this)">
                <span class="param-value" style="color: ${p.default < 0 ? '#ef4444' : 'var(--bt-blue)'}">${p.default}</span>
            </div>
        `).join('');
        panel.innerHTML = html;
    }

    window.applyPreset = function(regime) {
        const stratKey = strategySelect.value;
        const config = STRATEGY_PARAMS[stratKey];
        if (!config || !config.presets || !config.presets[regime]) return;
        const preset = config.presets[regime];
        Object.entries(preset).forEach(([key, val]) => {
            const input = document.getElementById(`param-${key}`);
            if (input) {
                input.value = val;
                handleParamChange(input);
            }
        });
        // Highlight active preset button
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
        const activeBtn = document.querySelector(`.preset-${regime.toLowerCase()}`);
        if (activeBtn) activeBtn.classList.add('active');
    };

    window.handleParamChange = function(el) {
        const val = parseFloat(el.value);
        const span = el.nextElementSibling;
        if (span) {
            span.textContent = val;
            span.style.color = val < 0 ? '#ef4444' : 'var(--bt-blue)';
        }
        // Clear preset highlight on manual change
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    };

    function resetToDefaults() {
        applyPreset('RANGE'); // Reset = apply RANGE defaults
    }

    function collectParams() {
        const params = {};
        document.querySelectorAll('#strategy-params-panel input[type="range"]').forEach(el => {
            params[el.dataset.key] = parseFloat(el.value);
        });
        return params;
    }

    renderStrategyParams(strategySelect.value);
    // Auto-fill recommended ticker on strategy switch
    strategySelect.addEventListener('change', () => {
        const config = STRATEGY_PARAMS[strategySelect.value];
        if (config && config.defaultTicker) {
            document.getElementById('ts-code').value = config.defaultTicker;
        }
        renderStrategyParams(strategySelect.value);
    });
    document.getElementById('reset-params-btn').addEventListener('click', resetToDefaults);

    // === Error Display ===
    function showError(msg) {
        errorMessage.textContent = msg;
        errorContainer.classList.add('show');
        overlay.classList.remove('show');
    }
    function hideError() { errorContainer.classList.remove('show'); }

    // === Charts Init ===
    function initCharts() {
        if (typeof echarts === 'undefined') { showError("ECharts 库加载失败"); return false; }
        try {
            if (!charts.equity) charts.equity = echarts.init(document.getElementById('equity-chart'));
            if (!charts.drawdown) charts.drawdown = echarts.init(document.getElementById('drawdown-chart'));
            if (!charts.mc) charts.mc = echarts.init(document.getElementById('mc-chart'));
            const hmEl = document.getElementById('monthly-heatmap');
            if (!charts.heatmap) charts.heatmap = echarts.init(hmEl);
            const radarEl = document.getElementById('grade-radar');
            if (radarEl && !charts.radar) charts.radar = echarts.init(radarEl);
            const annualEl = document.getElementById('annual-chart');
            if (annualEl && !charts.annual) charts.annual = echarts.init(annualEl);
            return true;
        } catch (e) {
            console.error("ECharts Init:", e);
            return false;
        }
    }

    // Resize observer
    const ro = new ResizeObserver(() => {
        Object.values(charts).forEach(c => { if (c) c.resize(); });
    });
    const terminal = document.querySelector('.bt-terminal');
    if (terminal) ro.observe(terminal);

    // === V5.0: Loading Progress Bar ===
    function setProgress(pct, activeStep) {
        const fill = document.getElementById('progress-fill');
        if (fill) fill.style.width = pct + '%';
        ['step-data', 'step-backtest', 'step-analysis', 'step-mc'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.classList.remove('active', 'done');
        });
        const steps = ['step-data', 'step-backtest', 'step-analysis', 'step-mc'];
        const activeIdx = steps.indexOf(activeStep);
        steps.forEach((id, i) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (i < activeIdx) el.classList.add('done');
            else if (i === activeIdx) el.classList.add('active');
        });
    }

    // === Run Backtest ===
    runBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        if (isRunning) return;
        isRunning = true;
        runBtn.disabled = true;

        const tsCodes = document.getElementById('ts-code').value.split(',').map(s => s.trim()).filter(s => s.length > 0);
        if (tsCodes.length === 0) { showError("请指定至少一个回测标的"); isRunning = false; runBtn.disabled = false; return; }

        const pkCheckbox = document.getElementById('pk-mode');
        let isPkMode = pkCheckbox.checked || tsCodes.length > 1;
        if (tsCodes.length > 1) pkCheckbox.checked = true;

        hideError();
        emptyState.style.display = 'none';
        resultsArea.style.display = 'block';
        if (!initCharts()) { isRunning = false; runBtn.disabled = false; return; }

        const basePayload = {
            strategy: strategySelect.value,
            start_date: document.getElementById('start-date').value.replace(/-/g, ''),
            end_date: document.getElementById('end-date').value.replace(/-/g, ''),
            initial_cash: parseFloat(document.getElementById('initial-cash').value),
            order_pct: parseFloat(document.getElementById('order-pct').value),
            adj: document.getElementById('adj-select').value,
            benchmark_code: document.getElementById('benchmark-select').value,
            params: collectParams()
        };

        try {
            overlay.classList.add('show');
            setProgress(10, 'step-data');

            if (isPkMode && tsCodes.length > 1) {
                setProgress(30, 'step-backtest');
                const response = await fetch('/api/v1/batch-backtest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: tsCodes.map(code => ({ ...basePayload, ts_code: code })) })
                });
                setProgress(70, 'step-analysis');
                const result = await response.json();
                setProgress(90, 'step-mc');
                if (result.status === 'success') renderPkResults(result.data, tsCodes);
                else showError(result.message);
            } else {
                setProgress(25, 'step-backtest');
                const response = await fetch('/api/v1/backtest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...basePayload, ts_code: tsCodes[0] })
                });
                setProgress(60, 'step-analysis');
                const result = await response.json();
                setProgress(85, 'step-mc');
                if (result.status === 'success') renderSingleResults(result.data);
                else showError(result.message);
            }
            setProgress(100, 'step-mc');
        } catch (err) {
            showError("连接故障: " + err.message);
        } finally {
            overlay.classList.remove('show');
            setProgress(0, '');
            isRunning = false;
            runBtn.disabled = false;
        }
    });

    // ========== RENDERING ==========

    // === Threshold Color Logic ===
    function getBarClass(metric, value) {
        const thresholds = {
            sharpe: { green: 1.0, amber: 0.5 },
            calmar: { green: 1.0, amber: 0.5 },
            sortino: { green: 1.5, amber: 0.5 },
            mdd: { green: -0.15, amber: -0.25 }, // inverted
            winrate: { green: 0.55, amber: 0.50 },
            pf: { green: 1.5, amber: 1.0 },
            kelly: { green: 0.1, amber: 0.0 },
            total: { green: 0.1, amber: 0.0 }
        };
        const t = thresholds[metric];
        if (!t) return '';
        if (metric === 'mdd') {
            if (value > t.green) return 'bar-green';
            if (value > t.amber) return 'bar-amber';
            return 'bar-red';
        }
        if (value >= t.green) return 'bar-green';
        if (value >= t.amber) return 'bar-amber';
        return 'bar-red';
    }

    function setMetric(id, value, suffix, metric, colorOverride) {
        const el = document.getElementById(id);
        if (!el) return;
        const parent = el.closest('.bt-metric-card');
        const bar = parent ? parent.querySelector('.mc-bar') : null;

        // Animate
        animateValue(el, value, suffix, colorOverride);

        // Threshold bar
        if (bar && metric) {
            bar.className = 'mc-bar ' + getBarClass(metric, value / (suffix === '%' ? 100 : 1));
        }
    }

    function animateValue(el, target, suffix = '', colorClass = null) {
        if (!el) return;
        const duration = 500;
        const startTime = performance.now();
        function step(now) {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = target * eased;
            el.textContent = current.toFixed(2) + suffix;
            if (colorClass === 'pos') el.className = 'mc-value pos';
            else if (colorClass === 'neg') el.className = 'mc-value neg';
            else el.className = 'mc-value';
            if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }

    // === Grade + Radar Rendering ===
    function renderGrade(gradeInfo) {
        const badge = document.getElementById('grade-badge');
        const scoreEl = document.getElementById('grade-score');
        if (!gradeInfo) return;

        badge.textContent = gradeInfo.grade;
        badge.className = 'bt-grade-badge grade-' + gradeInfo.grade;
        // V5.0: Animated score counter
        const targetScore = gradeInfo.score;
        const duration = 600;
        const start = performance.now();
        function countUp(now) {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            scoreEl.textContent = Math.round(targetScore * eased);
            if (progress < 1) requestAnimationFrame(countUp);
        }
        requestAnimationFrame(countUp);

        // Radar Chart for breakdown
        if (charts.radar && gradeInfo.breakdown) {
            const bd = gradeInfo.breakdown;
            charts.radar.setOption({
                backgroundColor: 'transparent',
                radar: {
                    indicator: [
                        { name: 'Sharpe', max: 100 },
                        { name: 'Calmar', max: 100 },
                        { name: 'MDD', max: 100 },
                        { name: 'Sortino', max: 100 },
                        { name: '胜率', max: 100 },
                        { name: '盈亏比', max: 100 }
                    ],
                    shape: 'polygon',
                    radius: '65%',
                    center: ['50%', '55%'],
                    axisName: { color: '#64748b', fontSize: 9 },
                    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                    splitArea: { areaStyle: { color: ['rgba(59,130,246,0.02)', 'rgba(59,130,246,0.04)'] } },
                    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
                },
                series: [{
                    type: 'radar',
                    data: [{
                        value: [bd.sharpe || 0, bd.calmar || 0, bd.drawdown || 0, bd.sortino || 0, bd.win_rate || 0, bd.profit_loss || 0],
                        name: '策略评分',
                        areaStyle: { color: 'rgba(59,130,246,0.15)' },
                        lineStyle: { color: '#3b82f6', width: 2 },
                        itemStyle: { color: '#3b82f6' },
                        symbol: 'circle',
                        symbolSize: 5
                    }]
                }]
            }, true);
            charts.radar.resize();
        }
    }

    // === Single Result ===
    function renderSingleResults(data) {
        if (!data || !data.metrics) { showError("回测引擎返回格式异常"); return; }

        const m = data.metrics;

        // Grade
        renderGrade(data.grade);

        // Metrics (V3.0: replaced win_rate with alpha)
        setMetric('m-total-return', m.total_return * 100, '%', 'total', m.total_return >= 0 ? 'pos' : 'neg');
        setMetric('m-sharpe', m.sharpe_ratio, '', 'sharpe', m.sharpe_ratio > 0 ? 'pos' : 'neg');
        setMetric('m-mdd', m.max_drawdown * 100, '%', 'mdd', 'neg');
        setMetric('m-calmar', m.calmar_ratio, '', 'calmar', m.calmar_ratio > 0 ? 'pos' : null);
        setMetric('m-sortino', m.sortino_ratio, '', 'sortino', m.sortino_ratio > 0 ? 'pos' : null);
        setMetric('m-alpha', (m.alpha || 0) * 100, '%', 'total', (m.alpha || 0) >= 0 ? 'pos' : 'neg');
        setMetric('m-pf', m.profit_factor, '', 'pf', m.profit_factor > 1 ? 'pos' : 'neg');
        setMetric('m-kelly', m.kelly_criterion, '', 'kelly', m.kelly_criterion > 0 ? 'pos' : 'neg');

        // V3.0: Diagnosis Card Grid
        renderDiagnosisCards(data.diagnosis);

        // Round Trips
        renderRoundTrips(data.round_trips);

        // Charts
        renderEquityChart(
            [{ name: '策略净值', data: data.equity_curve || [], color: '#3b82f6' },
             { name: '基准曲线', data: data.bench_curve || [], color: '#64748b', dashed: true }],
            data.dates || [],
            data.trade_log || [],
            data.equity_curve || []
        );
        renderDrawdownChart(data.drawdown || [], data.dates || [], m.max_drawdown);
        renderMonteCarloChart(data.monte_carlo, data.equity_curve || []);
        renderTradeLog(data.trade_log || []);
        currentTradeLog = data.trade_log || [];
        renderMonthlyHeatmap(data.monthly_returns || {});
        renderAnnualChart(data.monthly_returns || {});

        // V5.0: Stagger entrance animations
        applyStaggerAnimations();
    }

    // === Round-Trip Stats ===
    function renderRoundTrips(rt) {
        if (!rt) return;
        const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        const setClass = (id, cls) => { const el = document.getElementById(id); if (el) el.className = 'stat-value ' + cls; };

        setText('rt-total', rt.total_trades);
        setText('rt-winrate', rt.win_rate + '%');
        setClass('rt-winrate', rt.win_rate >= 55 ? 'pos' : rt.win_rate >= 45 ? 'warn' : 'neg');

        setText('rt-plr', rt.profit_loss_ratio + ':1');
        setClass('rt-plr', rt.profit_loss_ratio >= 1.5 ? 'pos' : rt.profit_loss_ratio >= 1.0 ? 'warn' : 'neg');

        setText('rt-avgwin', '+' + rt.avg_win_pct + '%');
        setText('rt-avgloss', '-' + rt.avg_loss_pct + '%');
        setText('rt-holddays', rt.median_hold_days + '天');
        setText('rt-maxconsec', rt.max_consecutive_loss + '笔');
        setClass('rt-maxconsec', rt.max_consecutive_loss >= 7 ? 'neg' : rt.max_consecutive_loss >= 4 ? 'warn' : '');
        setText('rt-maxloss', rt.max_single_loss + '%');
    }

    // === PK Mode ===
    function renderPkResults(results, labels) {
        const pkPanel = document.getElementById('pk-comparison-panel');
        const pkTable = document.getElementById('pk-table-body');
        pkPanel.style.display = 'block';
        pkTable.innerHTML = '';

        const series = [];
        const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

        results.forEach((res, i) => {
            if (res.status === 'success') {
                const d = res.data;
                const m = d.metrics;
                const g = d.grade || {};
                series.push({ name: labels[i], data: d.equity_curve, color: colors[i % colors.length] });

                const row = document.createElement('tr');
                row.style.cssText = 'cursor:pointer; border-bottom: 1px solid rgba(255,255,255,0.05);';
                row.innerHTML = `
                    <td style="padding:10px; font-weight:600">${labels[i]}</td>
                    <td style="padding:10px; text-align:right"><span class="bt-grade-badge grade-${g.grade || 'F'}" style="font-size:1rem">${g.grade || '--'}</span></td>
                    <td style="padding:10px; text-align:right; color:${m.total_return >= 0 ? '#10b981' : '#ef4444'}">${(m.total_return * 100).toFixed(2)}%</td>
                    <td style="padding:10px; text-align:right">${(m.annualized_return * 100).toFixed(2)}%</td>
                    <td style="padding:10px; text-align:right">${m.sharpe_ratio.toFixed(2)}</td>
                    <td style="padding:10px; text-align:right; color:#ef4444">${(m.max_drawdown * 100).toFixed(2)}%</td>
                    <td style="padding:10px; text-align:right"><button class="bt-drawer-toggle" style="padding:2px 8px; font-size:0.65rem">详情</button></td>
                `;
                row.onclick = (e) => { e.stopPropagation(); renderSingleResults(d); };
                pkTable.appendChild(row);
            }
        });

        const first = results.find(r => r.status === 'success');
        if (first) renderEquityChart(series, first.data.dates, [], []);
    }

    // ========== CHARTS ==========

    // === Equity Chart ===
    function renderEquityChart(configs, dates, tradeLog, equityCurve) {
        if (!charts.equity) return;

        const baseSeries = configs.map(c => {
            const base = c.data[0] || 1;
            return {
                name: c.name, type: 'line', smooth: true, showSymbol: false,
                data: c.data.map(v => ((v / base - 1) * 100).toFixed(2)),
                lineStyle: { width: c.dashed ? 1.5 : 2.5, color: c.color, type: c.dashed ? 'dashed' : 'solid' },
                itemStyle: { color: c.color }
            };
        });

        // Buy/Sell markers
        const baseVal = equityCurve[0] || 1;
        const buyPoints = [], sellPoints = [];
        if (tradeLog && tradeLog.length > 0) {
            tradeLog.forEach(t => {
                const idx = dates.indexOf(t.date);
                if (idx >= 0) {
                    const pctVal = ((equityCurve[idx] / baseVal - 1) * 100).toFixed(2);
                    if (t.type === 'BUY') buyPoints.push({ coord: [idx, pctVal], symbol: 'triangle', symbolSize: 10 });
                    else sellPoints.push({ coord: [idx, pctVal], symbol: 'pin', symbolSize: 12 });
                }
            });
        }

        if (baseSeries.length > 0) {
            baseSeries[0].markPoint = {
                data: [
                    ...buyPoints.map(p => ({ ...p, itemStyle: { color: '#10b981' }, symbolRotate: 0 })),
                    ...sellPoints.map(p => ({ ...p, itemStyle: { color: '#ef4444' }, symbolRotate: 180 }))
                ],
                label: { show: false },
                animation: true
            };
        }

        charts.equity.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,0.15)' } },
                backgroundColor: 'rgba(15, 18, 25, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f1f5f9', fontSize: 11 },
                formatter: function(params) {
                    let html = `<div style="font-weight:600; margin-bottom:4px; font-size:0.75rem">${params[0].axisValue}</div>`;
                    params.forEach(p => {
                        html += `<div style="display:flex;align-items:center;gap:5px;margin:2px 0;font-size:0.75rem">
                            <span style="width:7px;height:7px;border-radius:50%;background:${p.color};display:inline-block"></span>
                            ${p.seriesName}: <b>${p.value}%</b>
                        </div>`;
                    });
                    if (params.length >= 2) {
                        const diff = (parseFloat(params[0].value) - parseFloat(params[1].value)).toFixed(2);
                        const color = diff >= 0 ? '#10b981' : '#ef4444';
                        html += `<div style="margin-top:4px;border-top:1px solid rgba(255,255,255,0.08);padding-top:4px;color:${color};font-weight:700;font-size:0.78rem">Alpha: ${diff >= 0 ? '+' : ''}${diff}%</div>`;
                    }
                    return html;
                }
            },
            legend: { textStyle: { color: '#64748b', fontSize: 10 }, top: 0 },
            grid: { top: 30, bottom: 65, left: 55, right: 15 },
            xAxis: {
                type: 'category', data: dates, boundaryGap: false,
                axisLine: { lineStyle: { color: '#1e293b' } },
                axisLabel: { color: '#475569', fontSize: 10 }
            },
            yAxis: {
                type: 'value', scale: true,
                axisLabel: { formatter: '{value}%', color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            dataZoom: [
                { type: 'slider', height: 22, bottom: 8, borderColor: 'rgba(255,255,255,0.06)', fillerColor: 'rgba(59,130,246,0.12)',
                  textStyle: { color: '#475569' }, handleStyle: { color: '#3b82f6' },
                  id: 'equityZoom' },
                { type: 'inside' }
            ],
            series: baseSeries
        }, true);
        charts.equity.resize();

        // V5.0: Bidirectional zoom sync (equity ↔ drawdown)
        charts.equity.on('datazoom', function(params) {
            if (charts.drawdown && params.batch) {
                charts.drawdown.dispatchAction({
                    type: 'dataZoom',
                    start: params.batch[0].start,
                    end: params.batch[0].end
                });
            }
        });
    }

    // === Drawdown Chart ===
    function renderDrawdownChart(data, dates, maxDD) {
        if (!charts.drawdown) return;
        const ddPercent = data.map(v => (v * 100).toFixed(2));

        charts.drawdown.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'line' },
                backgroundColor: 'rgba(15,18,25,0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f1f5f9', fontSize: 11 },
                formatter: p => `<span style="font-size:0.75rem">${p[0].axisValue}<br/>回撤: <b style="color:#ef4444">${p[0].value}%</b></span>`
            },
            grid: { top: 15, bottom: 50, left: 55, right: 15 },
            xAxis: {
                type: 'category', data: dates, boundaryGap: false,
                axisLine: { lineStyle: { color: '#1e293b' } },
                axisLabel: { color: '#475569', fontSize: 10 }
            },
            yAxis: {
                type: 'value', max: 0,
                axisLabel: { formatter: '{value}%', color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            dataZoom: [
                { type: 'slider', height: 18, bottom: 4, borderColor: 'transparent', fillerColor: 'rgba(239,68,68,0.08)',
                  textStyle: { color: '#475569' }, handleStyle: { color: '#ef4444' } },
                { type: 'inside' }
            ],
            series: [{
                type: 'line', data: ddPercent, smooth: true, showSymbol: false,
                lineStyle: { color: '#ef4444', width: 1.5 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(239,68,68,0.25)' }, { offset: 1, color: 'rgba(239,68,68,0.01)' }]
                }},
                markLine: {
                    silent: true, symbol: 'none',
                    lineStyle: { color: '#dc2626', type: 'dashed', width: 1.5 },
                    data: [{ yAxis: (maxDD * 100).toFixed(2),
                        label: { formatter: `MDD ${(maxDD * 100).toFixed(2)}%`, color: '#ef4444', fontSize: 10, position: 'insideEndTop' } }]
                }
            }]
        }, true);
        charts.drawdown.resize();

        // V5.0: Bidirectional sync (drawdown → equity)
        charts.drawdown.on('datazoom', function(params) {
            if (charts.equity && params.batch) {
                charts.equity.dispatchAction({
                    type: 'dataZoom',
                    start: params.batch[0].start,
                    end: params.batch[0].end
                });
            }
        });
    }

    // === Monte Carlo (V5.0: FIXED confidence band rendering) ===
    function renderMonteCarloChart(mcData, equityCurve) {
        if (!charts.mc || !mcData) return;

        const p5 = mcData.p5 || [];
        const p50 = mcData.p50 || [];
        const p95 = mcData.p95 || [];
        if (p5.length === 0) return;

        const xData = Array.from({ length: p5.length }, (_, i) => i);

        // Set summary stats
        const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        setTxt('mc-ruin', (mcData.ruin_pct || 0) + '%');
        setTxt('mc-t5', ((mcData.terminal_p5 || 0) / 10000).toFixed(1) + '万');
        setTxt('mc-t50', ((mcData.terminal_median || 0) / 10000).toFixed(1) + '万');
        setTxt('mc-t95', ((mcData.terminal_p95 || 0) / 10000).toFixed(1) + '万');

        // Color ruin
        const ruinEl = document.getElementById('mc-ruin');
        if (ruinEl) ruinEl.style.color = mcData.ruin_pct > 20 ? '#ef4444' : mcData.ruin_pct > 5 ? '#f59e0b' : '#10b981';

        // V5.0 FIX: Proper confidence band using background-masking approach
        // p95 fills area down to 0, p5 covers/masks the bottom portion with bg color
        charts.mc.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,18,25,0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f1f5f9', fontSize: 10 },
                formatter: function(params) {
                    let html = '';
                    params.forEach(p => {
                        html += `<div style="font-size:0.7rem">${p.marker}${p.seriesName}: <b>${(p.value/10000).toFixed(1)}万</b></div>`;
                    });
                    return html;
                }
            },
            legend: { data: ['95%上界', '5%下界', '中位数', '实际策略'], textStyle: { color: '#475569', fontSize: 9 }, top: 0 },
            grid: { top: 25, bottom: 10, left: 45, right: 10 },
            xAxis: { type: 'category', data: xData, show: false },
            yAxis: {
                type: 'value', scale: true,
                axisLabel: { color: '#475569', fontSize: 9, formatter: v => (v / 10000).toFixed(0) + '万' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            series: [
                {
                    name: '95%上界', type: 'line', data: p95, smooth: true, showSymbol: false,
                    lineStyle: { color: 'rgba(59,130,246,0.25)', width: 1 },
                    areaStyle: { color: 'rgba(59,130,246,0.06)' },
                    z: 1
                },
                {
                    name: '5%下界', type: 'line', data: p5, smooth: true, showSymbol: false,
                    lineStyle: { color: 'rgba(59,130,246,0.25)', width: 1 },
                    areaStyle: { color: '#0f1219' },  // Mask below p5 with background color
                    z: 2
                },
                {
                    name: '中位数', type: 'line', data: p50, smooth: true, showSymbol: false,
                    lineStyle: { color: '#60a5fa', width: 1.5, type: 'dashed' },
                    z: 3
                },
                {
                    name: '实际策略', type: 'line', data: equityCurve, smooth: true, showSymbol: false,
                    lineStyle: { color: '#3b82f6', width: 2.5 },
                    z: 4
                }
            ]
        }, true);
        charts.mc.resize();
    }

    // === Monthly Heatmap (V3.0: +Annual Summary Column) ===
    function renderMonthlyHeatmap(monthlyReturns) {
        if (!charts.heatmap || !monthlyReturns || Object.keys(monthlyReturns).length === 0) return;

        const years = [...new Set(Object.keys(monthlyReturns).map(k => k.split('-')[0]))].sort();
        const months = ['01','02','03','04','05','06','07','08','09','10','11','12'];
        const monthLabels = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月','年度'];

        const heatData = [];
        let minVal = 0, maxVal = 0;
        years.forEach((year, yi) => {
            let yearTotal = 1;
            months.forEach((month, mi) => {
                const key = `${year}-${month}`;
                const val = monthlyReturns[key] !== undefined ? +(monthlyReturns[key] * 100).toFixed(2) : null;
                if (val !== null) {
                    heatData.push([mi, yi, val]);
                    minVal = Math.min(minVal, val);
                    maxVal = Math.max(maxVal, val);
                    yearTotal *= (1 + monthlyReturns[key]);
                }
            });
            // Annual summary column (index 12)
            const annualPct = +((yearTotal - 1) * 100).toFixed(2);
            heatData.push([12, yi, annualPct]);
            minVal = Math.min(minVal, annualPct);
            maxVal = Math.max(maxVal, annualPct);
        });

        charts.heatmap.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                formatter: p => `<span style="font-size:0.78rem">${years[p.value[1]]}年${monthLabels[p.value[0]]}<br/>收益: <b style="color:${p.value[2] >= 0 ? '#10b981' : '#ef4444'}">${p.value[2]}%</b></span>`
            },
            grid: { top: 5, bottom: 30, left: 50, right: 25 },
            xAxis: { type: 'category', data: monthLabels,
                splitArea: { show: true, areaStyle: { color: ['rgba(255,255,255,0.015)', 'transparent'] } },
                axisLabel: { color: '#475569', fontSize: 9, formatter: function(v) { return v === '年度' ? v : v; },
                    rich: { bold: { fontWeight: 700, color: '#f59e0b', fontSize: 10 } } } },
            yAxis: { type: 'category', data: years, axisLabel: { color: '#475569', fontSize: 10, fontWeight: 600 } },
            visualMap: {
                min: Math.min(minVal, -5), max: Math.max(maxVal, 5), calculable: false, orient: 'horizontal',
                left: 'center', bottom: 0, itemWidth: 10, itemHeight: 70,
                textStyle: { color: '#475569', fontSize: 9 },
                inRange: { color: ['#dc2626', '#451a03', '#1a1a2e', '#064e3b', '#10b981'] }
            },
            series: [{
                type: 'heatmap', data: heatData,
                label: { show: true, color: '#e2e8f0', fontSize: 10, fontWeight: 600,
                    formatter: function(p) {
                        if (p.value[2] === null) return '';
                        if (p.value[0] === 12) return '{annual|' + p.value[2] + '%}';
                        return p.value[2] + '%';
                    },
                    rich: { annual: { fontWeight: 900, fontSize: 11, color: '#f59e0b' } } },
                itemStyle: { borderColor: 'rgba(0,0,0,0.3)', borderWidth: 2, borderRadius: 3 },
                emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(59,130,246,0.4)' } }
            }]
        }, true);
        charts.heatmap.resize();
    }

    // === V3.0: Diagnosis Card Grid ===
    function renderDiagnosisCards(diagnosisData) {
        const grid = document.getElementById('diagnosis-grid');
        if (!grid || !diagnosisData || !Array.isArray(diagnosisData)) return;

        grid.innerHTML = diagnosisData.map(card => `
            <div class="bt-diag-card level-${card.level || 'info'}">
                <div class="diag-label">${card.label || ''}</div>
                <div>${card.text || ''}</div>
            </div>
        `).join('');
        grid.classList.add('show');
    }

    // === Trade Log (V3.0: +PnL column) ===
    function renderTradeLog(log) {
        const body = document.getElementById('trade-log-body');
        if (!log || log.length === 0) {
            body.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted)">无成交记录</td></tr>';
            return;
        }
        const recent = log.slice(-100);
        body.innerHTML = recent.map(t => {
            let pnlCell = '<td style="text-align:right">--</td>';
            if (t.type === 'SELL' && t.pnl_pct !== undefined && t.pnl_pct !== null) {
                const color = t.pnl_pct >= 0 ? 'var(--bt-green)' : 'var(--bt-red)';
                const sign = t.pnl_pct >= 0 ? '+' : '';
                pnlCell = `<td style="text-align:right; color:${color}; font-weight:600; font-family:'Outfit',monospace">${sign}${t.pnl_pct.toFixed(2)}%</td>`;
            } else if (t.type === 'BUY') {
                pnlCell = '<td style="text-align:right; color:var(--text-muted); font-size:0.65rem">\u2014</td>';
            }
            return `
                <tr>
                    <td>${t.date}</td>
                    <td><span class="${t.type === 'BUY' ? 'tag-buy' : 'tag-sell'}">${t.type}</span></td>
                    <td style="text-align:right; font-family: 'Outfit', monospace">${t.price.toFixed(3)}</td>
                    ${pnlCell}
                    <td style="text-align:right; font-family: 'Outfit', monospace">${t.equity ? (t.equity / 10000).toFixed(1) + '万' : '--'}</td>
                </tr>
            `;
        }).join('');
    }

    // === V5.0: Annual Statistics Bar Chart ===
    function renderAnnualChart(monthlyReturns) {
        if (!charts.annual || !monthlyReturns || Object.keys(monthlyReturns).length === 0) return;

        const years = [...new Set(Object.keys(monthlyReturns).map(k => k.split('-')[0]))].sort();
        const months = ['01','02','03','04','05','06','07','08','09','10','11','12'];

        const yearlyData = years.map(year => {
            let cumReturn = 1;
            months.forEach(month => {
                const key = `${year}-${month}`;
                if (monthlyReturns[key] !== undefined) {
                    cumReturn *= (1 + monthlyReturns[key]);
                }
            });
            return +((cumReturn - 1) * 100).toFixed(2);
        });

        charts.annual.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,18,25,0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f1f5f9', fontSize: 11 },
                formatter: p => `<span style="font-size:0.8rem">${p[0].name}年<br/>收益: <b style="color:${p[0].value >= 0 ? '#10b981' : '#ef4444'}">${p[0].value >= 0 ? '+' : ''}${p[0].value}%</b></span>`
            },
            grid: { top: 15, bottom: 30, left: 50, right: 15 },
            xAxis: {
                type: 'category', data: years,
                axisLabel: { color: '#94a3b8', fontSize: 11, fontWeight: 600 },
                axisLine: { lineStyle: { color: '#1e293b' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { formatter: '{value}%', color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            series: [{
                type: 'bar',
                data: yearlyData.map(v => ({
                    value: v,
                    itemStyle: {
                        color: v >= 0
                            ? { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#10b981' }, { offset: 1, color: 'rgba(16,185,129,0.3)' }] }
                            : { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(239,68,68,0.3)' }, { offset: 1, color: '#ef4444' }] },
                        borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4]
                    }
                })),
                barWidth: '45%',
                label: {
                    show: true, position: 'top',
                    formatter: p => `${p.value >= 0 ? '+' : ''}${p.value}%`,
                    color: '#94a3b8', fontSize: 10, fontWeight: 600, fontFamily: 'Outfit'
                }
            }]
        }, true);
        charts.annual.resize();
    }

    // === V5.0: Stagger Entrance Animations ===
    function applyStaggerAnimations() {
        const panels = document.querySelectorAll('#results-area > .bt-grade-row, #results-area > .bt-diagnosis-grid, #results-area > .bt-chart-panel, #results-area > .bt-bottom-row, #results-area > .bt-heatmap-panel, #results-area > .bt-annual-panel, #results-area > #pk-comparison-panel');
        panels.forEach((panel, i) => {
            panel.classList.remove('bt-fade-in');
            void panel.offsetWidth; // force reflow
            panel.style.animationDelay = (i * 0.08) + 's';
            panel.classList.add('bt-fade-in');
        });
    }

    // === V5.0: CSV Export for Trade Log ===
    const exportBtn = document.getElementById('export-trades-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            if (!currentTradeLog || currentTradeLog.length === 0) return;
            const headers = ['日期', '方向', '价格', '盈亏%', '净值'];
            const rows = currentTradeLog.map(t => [
                t.date,
                t.type,
                t.price.toFixed(4),
                t.type === 'SELL' && t.pnl_pct != null ? t.pnl_pct.toFixed(2) : '',
                t.equity ? (t.equity / 10000).toFixed(1) : ''
            ]);
            const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
            const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `backtest_trades_${new Date().toISOString().slice(0,10)}.csv`;
            a.click();
            URL.revokeObjectURL(url);
        });
    }

});
