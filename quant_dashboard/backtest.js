/**
 * AlphaCore Backtest Terminal V8.0 — Professional Edition
 * - Dynamic Strategy Parameter Panel (Slider-based)
 * - Enhanced Charts: dataZoom, crosshair, buy/sell markers, percentage Y-axis
 * - Drawdown: line + areaStyle + markLine
 * - Monte Carlo: confidence bands (5%/95%)
 * - Monthly Returns Heatmap
 */

window.onerror = function(msg, url, line, col, error) {
    // Suppress benign browser warnings
    if (typeof msg === 'string' && msg.includes('ResizeObserver')) return true;
    const errStr = `[Runtime Error] ${msg} at ${line}:${col}`;
    console.error(errStr, error);
    if (window.showError) window.showError(errStr);
    return false;
};

document.addEventListener('DOMContentLoaded', function() {
    console.log(">>> [AlphaCore] V8.0 Ready (Professional Edition)");
    
    const runBtn = document.getElementById('run-backtest-btn');
    const overlay = document.getElementById('loading-overlay');
    const errorContainer = document.getElementById('error-container');
    const errorMessage = document.getElementById('error-message');
    const strategySelect = document.getElementById('strategy-select');
    
    let charts = { equity: null, drawdown: null, mc: null, heatmap: null };
    let isRunning = false; // 防抖锁

    // ===== Strategy Parameter Definitions =====
    const STRATEGY_PARAMS = {
        mr: {
            label: '均值回归 V2.0',
            params: [
                { key: 'rsi_period', label: 'RSI 周期', min: 2, max: 14, step: 1, default: 3 },
                { key: 'rsi_buy', label: 'RSI 买入阈值', min: 5, max: 40, step: 1, default: 10 },
                { key: 'rsi_sell', label: 'RSI 卖出阈值', min: 60, max: 95, step: 1, default: 85 },
                { key: 'boll_period', label: '布林带周期', min: 10, max: 40, step: 1, default: 20 },
                { key: 'ma_trend_period', label: '趋势MA周期', min: 20, max: 120, step: 5, default: 60 }
            ]
        },
        mom: {
            label: '动量轮动 V1.0',
            params: [
                { key: 'lookback', label: '动量回看窗口', min: 5, max: 60, step: 1, default: 20 },
                { key: 'top_n', label: 'Top N 持仓', min: 1, max: 20, step: 1, default: 5 }
            ]
        },
        div: {
            label: '红利防线 V1.0',
            params: [
                { key: 'ma_slow', label: '慢均线周期', min: 60, max: 250, step: 10, default: 120 },
                { key: 'ma_fast', label: '快均线周期', min: 5, max: 60, step: 1, default: 20 },
                { key: 'rsi_period', label: 'RSI 周期', min: 3, max: 21, step: 1, default: 9 },
                { key: 'rsi_buy', label: 'RSI 买入阈值', min: 20, max: 60, step: 1, default: 40 }
            ]
        }
    };

    // ===== Dynamic Strategy Panel =====
    function renderStrategyParams(stratKey) {
        const panel = document.getElementById('strategy-params-panel');
        const config = STRATEGY_PARAMS[stratKey];
        if (!panel || !config) return;

        panel.innerHTML = config.params.map(p => `
            <div class="param-row">
                <label>${p.label}</label>
                <input type="range" min="${p.min}" max="${p.max}" step="${p.step}" value="${p.default}"
                       id="param-${p.key}" data-key="${p.key}"
                       oninput="this.nextElementSibling.textContent=this.value">
                <span class="param-value">${p.default}</span>
            </div>
        `).join('');
    }

    function collectParams() {
        const params = {};
        document.querySelectorAll('#strategy-params-panel input[type="range"]').forEach(el => {
            params[el.dataset.key] = parseFloat(el.value);
        });
        return params;
    }

    // Init params panel for default strategy
    renderStrategyParams(strategySelect.value);
    strategySelect.addEventListener('change', () => renderStrategyParams(strategySelect.value));

    // ===== Error Display =====
    window.showError = function(msg) {
        console.error("!!! SURFACED ERROR:", msg);
        errorMessage.textContent = msg;
        errorContainer.style.display = 'block';
        if (overlay) overlay.style.display = 'none';
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // ===== Charts Init =====
    function initCharts() {
        if (typeof echarts === 'undefined') {
            window.showError("ECharts 库加载失败");
            return false;
        }
        try {
            ['equity-chart', 'drawdown-chart', 'mc-chart', 'monthly-heatmap'].forEach(id => {
                const el = document.getElementById(id);
                if (el && el.offsetHeight < 100) el.style.height = '400px';
            });
            if (!charts.equity) charts.equity = echarts.init(document.getElementById('equity-chart'));
            if (!charts.drawdown) charts.drawdown = echarts.init(document.getElementById('drawdown-chart'));
            if (!charts.mc) charts.mc = echarts.init(document.getElementById('mc-chart'));
            const hmEl = document.getElementById('monthly-heatmap');
            if (hmEl && !charts.heatmap) charts.heatmap = echarts.init(hmEl);
            return true;
        } catch (e) {
            console.error("ECharts Init Exception:", e);
            return false;
        }
    }

    // ===== ResizeObserver for auto-resize =====
    const ro = new ResizeObserver(() => {
        Object.values(charts).forEach(c => { if (c) c.resize(); });
    });
    const terminal = document.querySelector('.main-terminal');
    if (terminal) ro.observe(terminal);

    // ===== Run Backtest (with debounce) =====
    runBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        if (isRunning) return; // 防抖
        isRunning = true;
        console.log(">>> [Action] START");
        
        const tsCodeInput = document.getElementById('ts-code');
        const tsCodes = tsCodeInput.value.split(',').map(s => s.trim()).filter(s => s.length > 0);
        
        if (tsCodes.length === 0) {
            window.showError("请指定至少一个回测标的");
            isRunning = false;
            return;
        }

        const pkCheckbox = document.getElementById('pk-mode');
        let isPkMode = pkCheckbox.checked || tsCodes.length > 1;
        if (tsCodes.length > 1) pkCheckbox.checked = true;

        errorContainer.style.display = 'none';
        resetMetrics();
        if (!initCharts()) { isRunning = false; return; }

        const basePayload = {
            strategy: strategySelect.value,
            start_date: document.getElementById('start-date').value,
            end_date: document.getElementById('end-date').value,
            initial_cash: parseFloat(document.getElementById('initial-cash').value),
            order_pct: parseFloat(document.getElementById('order-pct').value),
            adj: document.getElementById('adj-select').value,
            benchmark_code: document.getElementById('benchmark-select').value,
            params: collectParams()
        };

        try {
            overlay.style.display = 'flex';
            
            if (isPkMode && tsCodes.length > 1) {
                const response = await fetch('/api/v1/batch-backtest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: tsCodes.map(code => ({ ...basePayload, ts_code: code })) })
                });
                const result = await response.json();
                if (result.status === 'success') renderPkResults(result.data, tsCodes);
                else window.showError(result.message);
            } else {
                const response = await fetch('/api/v1/backtest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...basePayload, ts_code: tsCodes[0] })
                });
                const result = await response.json();
                if (result.status === 'success') {
                    renderSingleResults(result.data);
                } else {
                    window.showError(result.message);
                }
            }
        } catch (err) {
            window.showError("连接故障: " + err.message);
        } finally {
            overlay.style.display = 'none';
            isRunning = false;
            console.log(">>> [Action] COMPLETE");
        }
    });

    // ===== Metrics Rendering =====
    function resetMetrics() {
        ['res-total-return', 'res-sharpe', 'res-mdd', 'res-kelly', 'res-win-rate',
         'res-skew', 'res-kurt', 'res-calmar'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.textContent = '--'; el.className = 'value'; }
        });
    }

    function animateValue(el, target, suffix = '', isPositive = null) {
        if (!el) return;
        const duration = 600;
        const start = 0;
        const startTime = performance.now();
        
        function step(now) {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
            const current = start + (target - start) * eased;
            el.textContent = current.toFixed(target % 1 === 0 ? 0 : 2) + suffix;
            if (isPositive === true) el.className = 'value pos';
            else if (isPositive === false) el.className = 'value neg';
            if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }

    // ===== Single Result Rendering =====
    function renderSingleResults(data) {
        if (!data || !data.metrics) {
            window.showError("回测引擎返回格式异常");
            return;
        }
        
        const label = data.ts_code || "Result";
        console.log(">>> Rendering Stage:", label);
        
        const m = data.metrics;
        animateValue(document.getElementById('res-total-return'), m.total_return * 100, '%', m.total_return >= 0);
        animateValue(document.getElementById('res-sharpe'), m.sharpe_ratio, '', m.sharpe_ratio > 0);
        animateValue(document.getElementById('res-mdd'), m.max_drawdown * 100, '%', false);
        animateValue(document.getElementById('res-kelly'), m.kelly_criterion || 0, '');
        animateValue(document.getElementById('res-win-rate'), m.win_rate * 100, '%');
        animateValue(document.getElementById('res-skew'), m.skew || 0, '');
        animateValue(document.getElementById('res-kurt'), m.kurtosis || 0, '');
        animateValue(document.getElementById('res-calmar'), m.calmar_ratio || 0, '');

        // Equity Chart (with buy/sell markers from trade_log)
        renderEquityChart(
            [{ name: '策略净值', data: data.equity_curve || [], color: '#3b82f6' },
             { name: '基准曲线', data: data.bench_curve || [], color: '#64748b', dashed: true }],
            data.dates || [],
            data.trade_log || [],
            data.equity_curve || []
        );
        
        renderDrawdownChart(data.drawdown || [], data.dates || [], m.max_drawdown);
        renderTradeLog(data.trade_log || []);
        renderMonteCarloChart(data.monte_carlo || [], data.equity_curve || []);
        renderMonthlyHeatmap(data.monthly_returns || {});
    }

    // ===== PK Mode =====
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
                series.push({ name: labels[i], data: d.equity_curve, color: colors[i % colors.length] });
                
                const row = document.createElement('tr');
                row.style.cssText = 'cursor:pointer; border-bottom: 1px solid rgba(255,255,255,0.05);';
                row.innerHTML = `
                    <td style="padding:10px; font-weight:600">${labels[i]}</td>
                    <td style="padding:10px; text-align:right; color:${m.total_return >= 0 ? '#10b981' : '#ef4444'}">${(m.total_return * 100).toFixed(2)}%</td>
                    <td style="padding:10px; text-align:right">${(m.annualized_return * 100).toFixed(2)}%</td>
                    <td style="padding:10px; text-align:right">${m.sharpe_ratio.toFixed(2)}</td>
                    <td style="padding:10px; text-align:right; color:#ef4444">${(m.max_drawdown * 100).toFixed(2)}%</td>
                    <td style="padding:10px; text-align:right"><button class="btn" style="padding:2px 8px; font-size:0.65rem">详情</button></td>
                `;
                row.onclick = (e) => { e.stopPropagation(); renderSingleResults(d); };
                pkTable.appendChild(row);
            }
        });
        
        const first = results.find(r => r.status === 'success');
        if (first) renderEquityChart(series, first.data.dates, [], []);
    }

    // ===== Enhanced Equity Chart =====
    function renderEquityChart(configs, dates, tradeLog, equityCurve) {
        if (!charts.equity) return;

        // Convert to percentage returns from initial value
        const baseSeries = configs.map(c => {
            const base = c.data[0] || 1;
            return {
                name: c.name, type: 'line', smooth: true, showSymbol: false,
                data: c.data.map(v => ((v / base - 1) * 100).toFixed(2)),
                lineStyle: { width: c.dashed ? 1.5 : 2.5, color: c.color, type: c.dashed ? 'dashed' : 'solid' },
                itemStyle: { color: c.color }
            };
        });

        // Buy/Sell markers from trade_log overlaid on the equity curve
        const baseVal = equityCurve[0] || 1;
        const buyPoints = [];
        const sellPoints = [];
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

        // Add markers to the first (strategy) series
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
                axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,0.2)' } },
                backgroundColor: 'rgba(20, 24, 34, 0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#f1f5f9', fontSize: 12 },
                formatter: function(params) {
                    let html = `<div style="font-weight:600; margin-bottom:6px">${params[0].axisValue}</div>`;
                    params.forEach(p => {
                        html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
                            <span style="width:8px;height:8px;border-radius:50%;background:${p.color};display:inline-block"></span>
                            ${p.seriesName}: <b>${p.value}%</b>
                        </div>`;
                    });
                    // Alpha difference
                    if (params.length >= 2) {
                        const diff = (parseFloat(params[0].value) - parseFloat(params[1].value)).toFixed(2);
                        const color = diff >= 0 ? '#10b981' : '#ef4444';
                        html += `<div style="margin-top:6px;border-top:1px solid rgba(255,255,255,0.1);padding-top:6px;color:${color};font-weight:700">Alpha: ${diff >= 0 ? '+' : ''}${diff}%</div>`;
                    }
                    return html;
                }
            },
            legend: { textStyle: { color: '#94a3b8', fontSize: 11 }, top: 5 },
            grid: { top: 50, bottom: 80, left: 65, right: 20 },
            xAxis: {
                type: 'category', data: dates, boundaryGap: false,
                axisLine: { lineStyle: { color: '#334155' } },
                axisLabel: { color: '#64748b', fontSize: 10 }
            },
            yAxis: {
                type: 'value', scale: true,
                axisLabel: { formatter: '{value}%', color: '#64748b', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            dataZoom: [
                { type: 'slider', height: 24, bottom: 10, borderColor: 'rgba(255,255,255,0.1)', fillerColor: 'rgba(59,130,246,0.15)',
                  textStyle: { color: '#64748b' }, handleStyle: { color: '#3b82f6' } },
                { type: 'inside' }
            ],
            series: baseSeries
        }, true);
        charts.equity.resize();
    }

    // ===== Enhanced Drawdown Chart =====
    function renderDrawdownChart(data, dates, maxDD) {
        if (!charts.drawdown) return;
        const ddPercent = data.map(v => (v * 100).toFixed(2));
        
        charts.drawdown.setOption({
            backgroundColor: 'transparent',
            title: { text: '📉 回撤水下图 (Underwater Curve)', textStyle: { color: '#94a3b8', fontSize: 13, fontWeight: 400 }, left: 10, top: 5 },
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'line' },
                backgroundColor: 'rgba(20, 24, 34, 0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#f1f5f9' },
                formatter: p => `${p[0].axisValue}<br/>回撤: <b style="color:#ef4444">${p[0].value}%</b>`
            },
            grid: { top: 40, bottom: 60, left: 65, right: 20 },
            xAxis: {
                type: 'category', data: dates, boundaryGap: false,
                axisLine: { lineStyle: { color: '#334155' } },
                axisLabel: { color: '#64748b', fontSize: 10 }
            },
            yAxis: {
                type: 'value', max: 0,
                axisLabel: { formatter: '{value}%', color: '#64748b', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            dataZoom: [
                { type: 'slider', height: 20, bottom: 5, borderColor: 'transparent', fillerColor: 'rgba(239,68,68,0.1)',
                  textStyle: { color: '#64748b' }, handleStyle: { color: '#ef4444' } },
                { type: 'inside' }
            ],
            series: [{
                type: 'line', data: ddPercent, smooth: true, showSymbol: false,
                lineStyle: { color: '#ef4444', width: 1.5 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(239,68,68,0.35)' }, { offset: 1, color: 'rgba(239,68,68,0.02)' }]
                }},
                markLine: {
                    silent: true,
                    symbol: 'none',
                    lineStyle: { color: '#dc2626', type: 'dashed', width: 1.5 },
                    data: [{ yAxis: (maxDD * 100).toFixed(2), label: { formatter: `最大回撤 ${(maxDD * 100).toFixed(2)}%`, color: '#ef4444', fontSize: 10, position: 'insideEndTop' } }]
                }
            }]
        }, true);
        charts.drawdown.resize();
    }

    // ===== Enhanced Monte Carlo =====
    function renderMonteCarloChart(mcData, equityCurve) {
        if (!charts.mc || !mcData || mcData.length === 0) return;

        const numPoints = mcData[0].length;
        const xData = Array.from({ length: numPoints }, (_, i) => i);
        
        // Calculate percentiles at each time step
        const p5 = [], p50 = [], p95 = [];
        for (let t = 0; t < numPoints; t++) {
            const vals = mcData.map(sim => sim[t]).sort((a, b) => a - b);
            p5.push(vals[Math.floor(vals.length * 0.05)]);
            p50.push(vals[Math.floor(vals.length * 0.5)]);
            p95.push(vals[Math.floor(vals.length * 0.95)]);
        }

        charts.mc.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(20,24,34,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#f1f5f9' }
            },
            legend: { data: ['5% 下界', '中位数', '95% 上界', '实际策略'], textStyle: { color: '#94a3b8', fontSize: 10 }, top: 0 },
            grid: { top: 35, bottom: 25, left: 55, right: 15 },
            xAxis: { type: 'category', data: xData, show: false },
            yAxis: {
                type: 'value', scale: true,
                axisLabel: { color: '#64748b', fontSize: 10, formatter: v => (v / 10000).toFixed(0) + '万' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            series: [
                // Confidence band (area between p5 and p95)
                { name: '95% 上界', type: 'line', data: p95, smooth: true, showSymbol: false,
                  lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(59,130,246,0.12)' }, stack: 'band' },
                { name: '5% 下界', type: 'line', data: p5, smooth: true, showSymbol: false,
                  lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(59,130,246,0.12)' }, stack: 'band' },
                // Median
                { name: '中位数', type: 'line', data: p50, smooth: true, showSymbol: false,
                  lineStyle: { color: '#60a5fa', width: 2, type: 'dashed' } },
                // Actual strategy
                { name: '实际策略', type: 'line', data: equityCurve, smooth: true, showSymbol: false,
                  lineStyle: { color: '#3b82f6', width: 3 } }
            ]
        }, true);
        charts.mc.resize();
    }

    // ===== Monthly Returns Heatmap =====
    function renderMonthlyHeatmap(monthlyReturns) {
        if (!charts.heatmap || !monthlyReturns || Object.keys(monthlyReturns).length === 0) return;

        // Parse data: { "2023-01": 0.02, "2023-02": -0.01, ... }
        const years = [...new Set(Object.keys(monthlyReturns).map(k => k.split('-')[0]))].sort();
        const months = ['01','02','03','04','05','06','07','08','09','10','11','12'];
        const monthLabels = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
        
        const heatData = [];
        let minVal = 0, maxVal = 0;
        years.forEach((year, yi) => {
            months.forEach((month, mi) => {
                const key = `${year}-${month}`;
                const val = monthlyReturns[key] !== undefined ? +(monthlyReturns[key] * 100).toFixed(2) : null;
                if (val !== null) {
                    heatData.push([mi, yi, val]);
                    minVal = Math.min(minVal, val);
                    maxVal = Math.max(maxVal, val);
                }
            });
        });

        charts.heatmap.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                formatter: p => `${years[p.value[1]]}年${monthLabels[p.value[0]]}<br/>收益率: <b style="color:${p.value[2] >= 0 ? '#10b981' : '#ef4444'}">${p.value[2]}%</b>`
            },
            grid: { top: 10, bottom: 30, left: 60, right: 30 },
            xAxis: { type: 'category', data: monthLabels, splitArea: { show: true, areaStyle: { color: ['rgba(255,255,255,0.02)', 'transparent'] } },
                     axisLabel: { color: '#64748b', fontSize: 10 } },
            yAxis: { type: 'category', data: years, axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 600 } },
            visualMap: {
                min: Math.min(minVal, -5), max: Math.max(maxVal, 5), calculable: false, orient: 'horizontal',
                left: 'center', bottom: 0, itemWidth: 12, itemHeight: 80,
                textStyle: { color: '#64748b', fontSize: 10 },
                inRange: { color: ['#dc2626', '#451a03', '#1a1a2e', '#064e3b', '#10b981'] }
            },
            series: [{
                type: 'heatmap', data: heatData,
                label: { show: true, color: '#e2e8f0', fontSize: 11, fontWeight: 600,
                         formatter: p => p.value[2] !== null ? p.value[2] + '%' : '' },
                itemStyle: { borderColor: 'rgba(0,0,0,0.3)', borderWidth: 2, borderRadius: 4 },
                emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(59,130,246,0.5)' } }
            }]
        }, true);
        charts.heatmap.resize();
    }

    // ===== Trade Log =====
    function renderTradeLog(log) {
        const body = document.getElementById('trade-log-body');
        if (!log || log.length === 0) {
            body.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--text-muted)">无成交记录</td></tr>';
            return;
        }
        body.innerHTML = log.map(t => `
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05)">
                <td style="padding: 10px;">${t.date}</td>
                <td style="padding: 10px;"><span style="background:${t.type === 'BUY' ? '#065f46' : '#991b1b'}; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600">${t.type}</span></td>
                <td style="padding: 10px; text-align: right; font-family: 'Outfit', monospace">${t.price.toFixed(3)}</td>
                <td style="padding: 10px; text-align: right;">${(t.position * 100).toFixed(0)}%</td>
            </tr>
        `).join('');
    }
});
