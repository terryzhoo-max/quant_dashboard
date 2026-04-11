/**
 * AlphaCore Portfolio Manager V2.0 — Institutional Grade
 * =====================================================
 * - 集成全新 API: valuation / risk / nav / history
 * - Toast 通知系统 (替代 alert)
 * - 增强持仓表格 (仓位占比进度条)
 * - 风险 Gauge 三联仪表盘
 * - 净值走势对比图
 * - 交易记录面板
 * - 交易预估实时计算
 */

document.addEventListener('DOMContentLoaded', function () {
    const tradeModal = document.getElementById('trade-modal');
    const openTradeBtn = document.getElementById('open-trade-btn');
    const closeTradeBtn = document.getElementById('close-modal');
    const buyBtn = document.getElementById('buy-btn');
    const sellBtn = document.getElementById('sell-btn');
    const tradePrice = document.getElementById('trade-price');
    const tradeAmount = document.getElementById('trade-amount');
    const tradeEst = document.getElementById('trade-est');

    let charts = { sector: null, mctr: null, nav: null, sparkline: null };
    let gauges = { sharpe: null, maxdd: null, vol: null };

    const COLOR_PALETTE = [
        '#6366f1', '#3b82f6', '#10b981', '#f59e0b',
        '#ef4444', '#ec4899', '#06b6d4', '#8b5cf6'
    ];

    // ════════════════════════════════════
    //  Toast 通知系统
    // ════════════════════════════════════

    function showToast(message, type = 'success', duration = 3500) {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `pf-toast pf-toast-${type}`;

        const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
        toast.innerHTML = `<span class="pf-toast-icon">${icons[type] || '📌'}</span><span class="pf-toast-msg">${message}</span>`;
        container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('pf-toast-show'));

        setTimeout(() => {
            toast.classList.remove('pf-toast-show');
            toast.classList.add('pf-toast-hide');
            setTimeout(() => toast.remove(), 400);
        }, duration);
    }

    // ════════════════════════════════════
    //  交易预估实时计算
    // ════════════════════════════════════

    function updateTradeEstimate() {
        const p = parseFloat(tradePrice.value) || 0;
        const a = parseInt(tradeAmount.value) || 0;
        const total = p * a;
        tradeEst.textContent = '¥ ' + total.toLocaleString(undefined, { minimumFractionDigits: 2 });
    }

    tradePrice.addEventListener('input', updateTradeEstimate);
    tradeAmount.addEventListener('input', updateTradeEstimate);

    // ════════════════════════════════════
    //  Chart 初始化
    // ════════════════════════════════════

    function initCharts() {
        const sectorEl = document.getElementById('sector-pie-chart');
        const mctrEl = document.getElementById('mctr-chart');
        const navEl = document.getElementById('nav-chart');
        const sparkEl = document.getElementById('pf-sparkline');
        const gSharpe = document.getElementById('gauge-sharpe');
        const gMaxdd = document.getElementById('gauge-maxdd');
        const gVol = document.getElementById('gauge-vol');

        if (sectorEl && !charts.sector) charts.sector = echarts.init(sectorEl);
        if (mctrEl && !charts.mctr) charts.mctr = echarts.init(mctrEl);
        if (navEl && !charts.nav) charts.nav = echarts.init(navEl);
        if (sparkEl && !charts.sparkline) charts.sparkline = echarts.init(sparkEl);
        if (gSharpe && !gauges.sharpe) gauges.sharpe = echarts.init(gSharpe);
        if (gMaxdd && !gauges.maxdd) gauges.maxdd = echarts.init(gMaxdd);
        if (gVol && !gauges.vol) gauges.vol = echarts.init(gVol);
    }

    // ════════════════════════════════════
    //  数据加载: 估值
    // ════════════════════════════════════

    async function loadPortfolio() {
        try {
            const res = await fetch('/api/v1/portfolio/valuation');
            const result = await res.json();
            if (result.status === 'success') {
                renderValuation(result.data);
                loadRisk();
                loadNavCurve();
                loadHistory();
            }
        } catch (err) {
            console.error("Failed to load portfolio:", err);
            showToast('组合数据加载失败', 'error');
        }
    }

    function renderValuation(data) {
        // Hero KPI — 防御性: 兼容新旧 API
        document.getElementById('port-cash').textContent = '¥ ' + (data.cash || 0).toLocaleString(undefined, { minimumFractionDigits: 2 });
        document.getElementById('port-mv').textContent = '¥ ' + (data.market_value || 0).toLocaleString(undefined, { minimumFractionDigits: 2 });
        document.getElementById('nav-val').textContent = '¥ ' + (data.total_asset || 0).toLocaleString(undefined, { minimumFractionDigits: 2 });
        document.getElementById('pos-count').textContent = data.position_count || data.positions.length || 0;

        const cashWeight = data.cash_weight != null ? data.cash_weight : (data.total_asset > 0 ? (data.cash / data.total_asset * 100) : 0);
        document.getElementById('cash-weight').textContent = cashWeight.toFixed(1);

        // ROI — 使用后端统一计算的盈亏 (券商/Tushare 一致)
        let totalROI = data.total_pnl_pct != null ? data.total_pnl_pct : 0;
        // 向后兼容: 旧 API 可能无 total_pnl_pct 字段
        if (data.total_pnl_pct == null) {
            let originalCost = data.positions.reduce((acc, pos) => acc + (pos.amount * pos.cost), 0);
            if (originalCost > 0) {
                totalROI = ((data.market_value - originalCost) / originalCost) * 100;
            }
        }

        const roiEl = document.getElementById('port-roi');
        roiEl.textContent = (totalROI >= 0 ? '+' : '') + totalROI.toFixed(2) + '%';
        roiEl.className = 'pf-kpi-value ' + (totalROI >= 0 ? 'pf-up' : 'pf-danger');

        // Position count badge
        document.getElementById('pf-total-positions').textContent = (data.position_count || data.positions.length) + ' 只持仓';

        // Render table
        renderPositionsTable(data.positions);
    }

    function renderPositionsTable(positions) {
        const body = document.getElementById('positions-body');
        body.innerHTML = '';

        if (positions.length === 0) {
            body.innerHTML = '<tr><td colspan="9" class="pf-table-empty">当前组合无持仓头寸 (Empty Portfolio)</td></tr>';
            return;
        }

        positions.forEach(pos => {
            const row = document.createElement('tr');
            const pnlClass = pos.pnl >= 0 ? 'pf-up' : 'pf-danger';
            const parts = pos.ts_code.split('.');
            const codeNum = parts[0];
            const codeExt = parts.length > 1 ? parts[1] : '';

            // 仓位占比进度条颜色 (防御性: 旧 API 可能没有 weight)
            const weight = pos.weight != null ? pos.weight : 0;
            const weightColor = weight > 15 ? '#ef4444' : weight > 10 ? '#f59e0b' : '#3b82f6';

            row.innerHTML = `
                <td>
                    <div class="pf-code-cell">
                        <span class="pf-code-num">${codeNum}</span>
                        <span class="pf-code-ext">.${codeExt}</span>
                    </div>
                </td>
                <td>
                    <div class="pf-name-cell">${pos.name}</div>
                    <span class="pf-sector-tag">${pos.industry || '未知行业'}</span>
                </td>
                <td class="pf-mono">${pos.amount.toLocaleString()}</td>
                <td class="pf-mono pf-dim">¥${pos.cost.toFixed(2)}</td>
                <td class="pf-mono">¥${pos.price.toFixed(2)}${pos.price_source === 'broker' ? '<span class="pf-src-tag pf-src-broker" title="券商导入报价 (当日优先)">券</span>' : pos.price_source === 'cost' ? '<span class="pf-src-tag pf-src-cost" title="使用成本价兜底">成本</span>' : '<span class="pf-src-tag pf-src-ts" title="Tushare 收盘价">TS</span>'}</td>
                <td class="pf-mono pf-accent">¥${pos.market_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                <td>
                    <div class="pf-weight-cell">
                        <span class="pf-weight-num">${weight.toFixed(1)}%</span>
                        <div class="pf-weight-bar">
                            <div class="pf-weight-fill" style="width: ${Math.min(weight * 5, 100)}%; background: ${weightColor};"></div>
                        </div>
                    </div>
                </td>
                <td class="${pnlClass} pf-pnl-cell">
                    <span class="pf-pnl-val">${pos.pnl > 0 ? '+' : ''}${pos.pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                    <span class="pf-pnl-pct">${pos.pnl_pct > 0 ? '+' : ''}${pos.pnl_pct.toFixed(2)}%</span>
                </td>
                <td>
                    <button class="pf-btn-adjust" onclick="quickTrade('${pos.ts_code}', '${pos.name}')">调整仓位</button>
                </td>
            `;
            body.appendChild(row);
        });
    }

    // ════════════════════════════════════
    //  数据加载: 风险
    // ════════════════════════════════════

    async function loadRisk() {
        try {
            const res = await fetch('/api/v1/portfolio/risk');
            const result = await res.json();
            if (result.status === 'success' && result.data.status !== 'empty') {
                renderRiskCharts(result.data);
                renderRiskGauges(result.data);
            }
        } catch (err) {
            console.error("Failed to load risk metrics:", err);
        }
    }

    function renderRiskCharts(risk) {
        initCharts();

        // Vol KPI
        document.getElementById('port-vol').textContent = ((risk.portfolio_vol || 0) * 100).toFixed(2) + '%';

        // Sharpe KPI
        const sharpeEl = document.getElementById('port-sharpe');
        const sharpe = risk.sharpe_ratio || 0;
        sharpeEl.textContent = sharpe.toFixed(2);
        sharpeEl.className = 'pf-kpi-value ' + (sharpe >= 1 ? 'pf-up' : sharpe >= 0 ? '' : 'pf-danger');

        // Max DD KPI
        document.getElementById('port-maxdd').textContent = (risk.max_drawdown || 0).toFixed(2) + '%';

        // ── MCTR Bar Chart ──
        const sortedMCTR = [...risk.details].sort((a, b) => a.risk_contribution - b.risk_contribution);

        charts.mctr.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 },
                formatter: function (params) {
                    let d = sortedMCTR[params[0].dataIndex];
                    return `<strong>${d.name} (${d.ts_code})</strong><br>
                            MCTR: ${d.mctr.toFixed(4)}<br>
                            总风险贡献: ${d.risk_contribution.toFixed(2)}%<br>
                            仓位权重: ${d.weight.toFixed(2)}%`;
                }
            },
            grid: { left: '3%', right: '8%', bottom: '3%', top: '5%', containLabel: true },
            xAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontFamily: 'Outfit', fontSize: 11 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            yAxis: {
                type: 'category',
                data: sortedMCTR.map(d => d.name),
                axisLabel: { color: '#cbd5e1', fontWeight: 500, fontSize: 12 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            series: [{
                name: 'Risk %',
                type: 'bar',
                data: sortedMCTR.map(d => d.risk_contribution),
                itemStyle: {
                    color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [
                        { offset: 0, color: '#ef4444' },
                        { offset: 1, color: 'rgba(239, 68, 68, 0.08)' }
                    ]),
                    borderRadius: [0, 6, 6, 0]
                },
                barMaxWidth: 18
            }],
            animationDuration: 1000,
            animationEasing: 'cubicOut'
        });

        // ── Sector Pie Chart ──
        const pieData = risk.industry_exposure || risk.details.map(d => ({ name: d.name, value: d.weight }));

        charts.sector.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'item',
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 },
                formatter: '{b}: {c}%'
            },
            legend: {
                orient: 'vertical',
                right: '5%',
                top: 'middle',
                textStyle: { color: '#94a3b8', fontSize: 12 },
                icon: 'circle',
                itemWidth: 10,
                itemGap: 14
            },
            color: COLOR_PALETTE,
            series: [{
                type: 'pie',
                radius: ['52%', '82%'],
                center: ['38%', '50%'],
                avoidLabelOverlap: false,
                itemStyle: {
                    borderRadius: 8,
                    borderColor: 'rgba(15, 23, 42, 0.6)',
                    borderWidth: 3
                },
                label: { show: false },
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 16,
                        fontWeight: 'bold',
                        color: '#fff',
                        formatter: '{b}\n{d}%'
                    },
                    scaleSize: 8
                },
                labelLine: { show: false },
                data: pieData,
                animationType: 'scale',
                animationDuration: 1200,
                animationEasing: 'elasticOut'
            }]
        });
    }

    // ════════════════════════════════════
    //  风险 Gauge 仪表盘
    // ════════════════════════════════════

    function renderRiskGauges(risk) {
        initCharts();

        function makeGauge(chart, name, value, min, max, colors, suffix) {
            chart.setOption({
                backgroundColor: 'transparent',
                series: [{
                    type: 'gauge',
                    center: ['50%', '65%'],
                    radius: '90%',
                    min: min, max: max,
                    startAngle: 200, endAngle: -20,
                    splitNumber: 4,
                    axisLine: {
                        lineStyle: {
                            width: 12,
                            color: colors
                        }
                    },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false },
                    pointer: {
                        width: 4, length: '60%',
                        itemStyle: { color: '#e2e8f0' }
                    },
                    anchor: {
                        show: true, size: 8,
                        itemStyle: { borderWidth: 2, borderColor: '#e2e8f0' }
                    },
                    title: {
                        offsetCenter: [0, '90%'],
                        fontSize: 11,
                        color: '#94a3b8',
                        fontWeight: 600
                    },
                    detail: {
                        offsetCenter: [0, '55%'],
                        fontSize: 18,
                        fontWeight: 700,
                        fontFamily: 'Outfit',
                        color: '#fff',
                        formatter: '{value}' + suffix
                    },
                    data: [{ value: value, name: name }],
                    animationDuration: 1500,
                    animationEasing: 'bounceOut'
                }]
            });
        }

        // Sharpe Gauge: green=good
        makeGauge(gauges.sharpe, 'SHARPE', risk.sharpe_ratio || 0, -1, 3,
            [[0.33, '#ef4444'], [0.5, '#f59e0b'], [1, '#10b981']], '');

        // Max DD Gauge: red=bad (invert display)
        const ddAbs = Math.abs(risk.max_drawdown || 0);
        makeGauge(gauges.maxdd, 'MAX DD', ddAbs, 0, 30,
            [[0.33, '#10b981'], [0.66, '#f59e0b'], [1, '#ef4444']], '%');

        // Vol Gauge
        const volPct = (risk.portfolio_vol || 0) * 100;
        makeGauge(gauges.vol, 'VOL', parseFloat(volPct.toFixed(1)), 0, 50,
            [[0.4, '#10b981'], [0.7, '#f59e0b'], [1, '#ef4444']], '%');
    }

    // ════════════════════════════════════
    //  净值曲线
    // ════════════════════════════════════

    async function loadNavCurve() {
        try {
            const res = await fetch('/api/v1/portfolio/nav');
            const result = await res.json();
            if (result.status === 'success' && result.data.status === 'ok') {
                renderNavChart(result.data);
            }
        } catch (err) {
            console.error("Failed to load NAV:", err);
        }
    }

    function renderNavChart(navData) {
        initCharts();

        const series = [{
            name: '组合净值',
            type: 'line',
            data: navData.nav,
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 2.5, color: '#6366f1' },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(99, 102, 241, 0.25)' },
                    { offset: 1, color: 'rgba(99, 102, 241, 0.02)' }
                ])
            }
        }];

        if (navData.benchmark && navData.benchmark.length > 0) {
            series.push({
                name: navData.benchmark_name || '沪深300',
                type: 'line',
                data: navData.benchmark,
                smooth: true,
                showSymbol: false,
                lineStyle: { width: 1.5, color: '#64748b', type: 'dashed' },
                areaStyle: null
            });
        }

        charts.nav.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 }
            },
            legend: {
                right: '5%', top: '2%',
                textStyle: { color: '#94a3b8', fontSize: 11 },
                icon: 'roundRect', itemWidth: 14
            },
            grid: { left: '3%', right: '4%', bottom: '3%', top: '14%', containLabel: true },
            xAxis: {
                type: 'category',
                data: navData.dates,
                axisLabel: {
                    color: '#64748b', fontSize: 10, fontFamily: 'Outfit',
                    formatter: val => val.slice(5) // MM-DD
                },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
                splitLine: { show: false }
            },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontSize: 10, fontFamily: 'Outfit', formatter: v => v.toFixed(2) },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            series: series,
            animationDuration: 1200,
            animationEasing: 'cubicOut'
        });

        // Sparkline in Hero
        if (charts.sparkline && navData.nav.length > 0) {
            charts.sparkline.setOption({
                backgroundColor: 'transparent',
                grid: { left: 0, right: 0, top: 0, bottom: 0 },
                xAxis: { type: 'category', show: false, data: navData.dates },
                yAxis: { type: 'value', show: false, min: 'dataMin', max: 'dataMax' },
                series: [{
                    type: 'line', data: navData.nav, smooth: true, showSymbol: false,
                    lineStyle: { width: 2, color: '#6366f1' },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(99,102,241,0.3)' },
                            { offset: 1, color: 'rgba(99,102,241,0)' }
                        ])
                    }
                }],
                animation: true, animationDuration: 800
            });
        }
    }

    // ════════════════════════════════════
    //  交易记录
    // ════════════════════════════════════

    async function loadHistory() {
        try {
            const res = await fetch('/api/v1/portfolio/history');
            const result = await res.json();
            if (result.status === 'success') {
                renderHistory(result.data);
            }
        } catch (err) {
            console.error("Failed to load history:", err);
        }
    }

    function renderHistory(records) {
        const container = document.getElementById('trade-history-list');
        if (!records || records.length === 0) {
            container.innerHTML = '<div class="pf-history-empty">暂无交易记录</div>';
            return;
        }

        container.innerHTML = records.map(r => {
            const isBuy = r.action === 'buy';
            const isImport = r.action === 'import';
            const isReset = r.action === 'reset';
            let statusClass, icon, label;

            if (isReset) {
                statusClass = 'pf-hist-reset';
                icon = '🗑️';
                label = '清零';
            } else if (isImport) {
                statusClass = 'pf-hist-import';
                icon = '📥';
                label = '导入';
            } else if (r.success) {
                statusClass = isBuy ? 'pf-hist-buy' : 'pf-hist-sell';
                icon = isBuy ? '🟢' : '🔴';
                label = isBuy ? '买入' : '卖出';
            } else {
                statusClass = 'pf-hist-fail';
                icon = '⚪';
                label = isBuy ? '买入' : '卖出';
            }

            const detailText = (isImport || isReset)
                ? r.message || `${label} ${r.amount} 只持仓`
                : `${r.amount}股 × ¥${r.price.toFixed(2)} = ¥${r.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

            return `<div class="pf-history-item ${statusClass}">
                <span class="pf-hist-icon">${icon}</span>
                <div class="pf-hist-body">
                    <div class="pf-hist-title">
                        <strong>${label}</strong> ${r.name || r.ts_code}
                        <span class="pf-hist-code">${r.ts_code}</span>
                    </div>
                    <div class="pf-hist-detail">${detailText}</div>
                </div>
                <div class="pf-hist-meta">
                    <span class="pf-hist-status">${r.success ? '✓ 成功' : '✗ ' + r.message}</span>
                    <span class="pf-hist-time">${r.timestamp}</span>
                </div>
            </div>`;
        }).join('');
    }

    // ════════════════════════════════════
    //  交易执行
    // ════════════════════════════════════

    async function doTrade(action) {
        const payload = {
            ts_code: document.getElementById('trade-code').value.trim(),
            name: document.getElementById('trade-name').value.trim(),
            amount: parseInt(tradeAmount.value),
            price: parseFloat(tradePrice.value),
            action: action
        };

        if (!payload.ts_code) {
            showToast('请输入证券代码', 'warning');
            return;
        }
        if (isNaN(payload.amount) || payload.amount <= 0) {
            showToast('请输入有效的数量', 'warning');
            return;
        }
        if (isNaN(payload.price) || payload.price <= 0) {
            showToast('请输入有效的价格', 'warning');
            return;
        }

        try {
            const res = await fetch('/api/v1/portfolio/trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await res.json();

            if (result.status === 'success') {
                tradeModal.style.display = 'none';
                showToast(`${action === 'buy' ? '买入' : '卖出'} ${payload.name || payload.ts_code} 成功`, 'success');
                loadPortfolio();
            } else {
                showToast('交易失败: ' + result.message, 'error');
            }
        } catch (err) {
            showToast('网络错误，请重试', 'error');
        }
    }

    // ════════════════════════════════════
    //  TXT 持仓导入系统
    // ════════════════════════════════════

    const importBtn = document.getElementById('import-btn');
    const importFileInput = document.getElementById('import-file-input');
    const importModal = document.getElementById('import-modal');
    const importDropzone = document.getElementById('import-dropzone');
    const importPreview = document.getElementById('import-preview');
    const importSummary = document.getElementById('import-summary');
    const importPreviewBody = document.getElementById('import-preview-body');
    const importConfirmBtn = document.getElementById('import-confirm-btn');
    const importCloseBtn = document.getElementById('import-close-btn');
    const importWarning = document.getElementById('import-warning');

    let pendingImportFile = null;

    // 证券代码自动补全后缀 (客户端镜像)
    function autoSuffix(code) {
        code = code.trim();
        if (code.includes('.')) return code;
        if (code.length === 5) return code + '.HK';
        if (code.length === 6) {
            const p3 = code.substring(0, 3);
            if (p3 === '159') return code + '.SZ';
            if (['510','511','512','513','515','516','518','560','561','562','563','588'].includes(p3)) return code + '.SH';
            if (['000','001','002','003','300','301'].includes(p3)) return code + '.SZ';
            if (code[0] === '6') return code + '.SH';
            if (['688','689'].includes(p3)) return code + '.SH';
        }
        return code + '.SZ';
    }

    // 打开导入弹窗
    importBtn.onclick = () => {
        // 重置状态
        pendingImportFile = null;
        importPreview.style.display = 'none';
        importConfirmBtn.style.display = 'none';
        importWarning.style.display = 'none';
        importDropzone.style.display = 'flex';
        importPreviewBody.innerHTML = '';
        importFileInput.value = '';
        importModal.style.display = 'flex';
    };

    // 关闭导入弹窗
    importCloseBtn.onclick = () => importModal.style.display = 'none';
    importModal.addEventListener('click', (e) => {
        if (e.target === importModal) importModal.style.display = 'none';
    });

    // 点击拖放区 → 触发文件选择
    importDropzone.onclick = () => importFileInput.click();

    // 拖放支持
    importDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        importDropzone.classList.add('pf-dropzone-hover');
    });

    importDropzone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        importDropzone.classList.remove('pf-dropzone-hover');
    });

    importDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        importDropzone.classList.remove('pf-dropzone-hover');
        if (e.dataTransfer.files.length > 0) {
            handleImportFile(e.dataTransfer.files[0]);
        }
    });

    // 文件选择回调
    importFileInput.onchange = (e) => {
        if (e.target.files.length > 0) {
            handleImportFile(e.target.files[0]);
        }
    };

    // 客户端预解析 TXT
    function handleImportFile(file) {
        if (!file) return;
        pendingImportFile = file;

        const reader = new FileReader();
        reader.onload = function (e) {
            const text = e.target.result;
            parseAndPreview(text);
        };
        // 尝试用 GBK 读取 (浏览器默认支持)
        reader.readAsText(file, 'GBK');
    }

    function parseAndPreview(text) {
        const lines = text.split(/\r?\n/).filter(l => l.trim());
        const positions = [];
        let cash = 0;
        let totalAsset = 0;

        // 解析第一行汇总
        if (lines.length > 0) {
            const cashMatch = lines[0].match(/可用[:：\s]*([0-9,.]+)/);
            const assetMatch = lines[0].match(/资产[:：\s]*([0-9,.]+)/);
            if (cashMatch) cash = parseFloat(cashMatch[1].replace(/,/g, ''));
            if (assetMatch) totalAsset = parseFloat(assetMatch[1].replace(/,/g, ''));
        }

        // 找列头行
        let headerIdx = -1;
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes('证券代码')) { headerIdx = i; break; }
        }

        if (headerIdx < 0) {
            showToast('未检测到有效的列头行（需含"证券代码"关键字）', 'error');
            return;
        }

        // 解析列头
        const headerParts = lines[headerIdx].split(/\s+/).filter(Boolean);
        const colMap = {};
        const targets = {
            '证券代码': 'code', '证券名称': 'name', '证券数量': 'amount',
            '库存数量': 'amount_alt', '买入均价': 'cost', '参考成本价': 'cost_alt',
            '当前价': 'price', '最新市值': 'mv'
        };
        headerParts.forEach((h, i) => {
            for (const [key, field] of Object.entries(targets)) {
                if (h.includes(key)) { colMap[field] = i; break; }
            }
        });

        // 解析数据行
        for (let i = headerIdx + 1; i < lines.length; i++) {
            const parts = lines[i].split(/\s+/).filter(Boolean);
            if (parts.length < 4 || parts[0].includes('--') || parts[0].includes('合计')) continue;

            const rawCode = parts[colMap.code ?? 0];
            if (!rawCode || !/\d/.test(rawCode)) continue;

            const tsCode = autoSuffix(rawCode);
            const name = parts[colMap.name ?? 1] || '';
            const amtIdx = colMap.amount ?? colMap.amount_alt ?? 2;
            const amount = parseInt(parseFloat((parts[amtIdx] || '0').replace(/,/g, '')));
            if (amount <= 0) continue;

            const costIdx = colMap.cost ?? colMap.cost_alt ?? 5;
            let cost = Math.abs(parseFloat((parts[costIdx] || '0').replace(/,/g, '')));
            const priceIdx = colMap.price ?? 9;
            const price = parseFloat((parts[priceIdx] || '0').replace(/,/g, ''));

            if (cost <= 0) cost = price > 0 ? price : 1;

            positions.push({ tsCode, rawCode, name, amount, cost, price });
        }

        if (positions.length === 0) {
            showToast('未解析到有效持仓数据，请检查文件格式', 'error');
            return;
        }

        // 渲染预览
        importDropzone.style.display = 'none';
        importPreview.style.display = 'block';
        importConfirmBtn.style.display = 'block';
        importWarning.style.display = 'block';

        const totalMV = positions.reduce((s, p) => s + p.amount * p.price, 0);
        importSummary.innerHTML = `
            <div class="pf-import-stats">
                <span class="pf-import-stat">
                    <span class="pf-import-stat-label">检测到</span>
                    <span class="pf-import-stat-value pf-accent">${positions.length}</span>
                    <span class="pf-import-stat-label">只持仓</span>
                </span>
                <span class="pf-import-stat">
                    <span class="pf-import-stat-label">可用资金</span>
                    <span class="pf-import-stat-value pf-gold">¥${cash.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                </span>
                <span class="pf-import-stat">
                    <span class="pf-import-stat-label">持仓市值</span>
                    <span class="pf-import-stat-value">¥${totalMV.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                </span>
                <span class="pf-import-stat">
                    <span class="pf-import-stat-label">总资产</span>
                    <span class="pf-import-stat-value" style="color:#10b981;">¥${totalAsset.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                </span>
            </div>
        `;

        importPreviewBody.innerHTML = positions.map(p => {
            const pnlClass = p.price >= p.cost ? 'pf-up' : 'pf-danger';
            return `<tr>
                <td>
                    <div class="pf-code-cell">
                        <span class="pf-code-num">${p.rawCode}</span>
                        <span class="pf-code-ext">${p.tsCode.includes('.') ? '.' + p.tsCode.split('.')[1] : ''}</span>
                    </div>
                </td>
                <td class="pf-name-cell">${p.name}</td>
                <td class="pf-mono">${p.amount.toLocaleString()}</td>
                <td class="pf-mono pf-dim">¥${p.cost.toFixed(3)}</td>
                <td class="pf-mono ${pnlClass}">¥${p.price.toFixed(3)}</td>
            </tr>`;
        }).join('');
    }

    // 确认导入 → 上传到后端
    importConfirmBtn.onclick = async () => {
        if (!pendingImportFile) {
            showToast('请先选择文件', 'warning');
            return;
        }

        importConfirmBtn.disabled = true;
        importConfirmBtn.textContent = '⏳ 导入中...';

        try {
            const formData = new FormData();
            formData.append('file', pendingImportFile);

            const res = await fetch('/api/v1/portfolio/import', {
                method: 'POST',
                body: formData
            });
            const result = await res.json();

            if (result.status === 'success' && result.data.success) {
                importModal.style.display = 'none';
                showToast(`✅ 成功导入 ${result.data.imported} 只持仓，可用资金 ¥${result.data.cash.toLocaleString()}`, 'success', 5000);

                if (result.data.errors && result.data.errors.length > 0) {
                    setTimeout(() => {
                        showToast(`⚠️ ${result.data.errors.length} 条解析警告`, 'warning');
                    }, 1000);
                }

                // 刷新全部数据
                loadPortfolio();
            } else {
                const errMsg = result.data?.errors?.join('; ') || result.message || '未知错误';
                showToast('导入失败: ' + errMsg, 'error');
            }
        } catch (err) {
            showToast('网络错误，请重试: ' + err.message, 'error');
        } finally {
            importConfirmBtn.disabled = false;
            importConfirmBtn.textContent = '✅ 确认导入';
        }
    };

    // ════════════════════════════════════
    //  清零组合功能
    // ════════════════════════════════════

    const resetBtn = document.getElementById('reset-btn');
    const resetModal = document.getElementById('reset-modal');
    const resetCloseBtn = document.getElementById('reset-close-btn');
    const resetExecBtn = document.getElementById('reset-exec-btn');
    const resetConfirmInput = document.getElementById('reset-confirm-input');
    const resetSummary = document.getElementById('reset-summary');

    // 打开弹窗: 展示当前持仓概要
    resetBtn.onclick = async () => {
        try {
            const res = await fetch('/api/v1/portfolio/valuation');
            const result = await res.json();
            if (result.status === 'success') {
                const d = result.data;
                resetSummary.innerHTML = `
                    <div class="pf-reset-stats">
                        <div class="pf-reset-stat-row">
                            <span class="pf-reset-stat-label">当前持仓</span>
                            <span class="pf-reset-stat-value">${d.position_count || 0} 只</span>
                        </div>
                        <div class="pf-reset-stat-row">
                            <span class="pf-reset-stat-label">持仓市值</span>
                            <span class="pf-reset-stat-value pf-danger">¥${(d.market_value||0).toLocaleString(undefined,{minimumFractionDigits:2})}</span>
                        </div>
                        <div class="pf-reset-stat-row">
                            <span class="pf-reset-stat-label">可用现金</span>
                            <span class="pf-reset-stat-value pf-gold">¥${(d.cash||0).toLocaleString(undefined,{minimumFractionDigits:2})}</span>
                        </div>
                        <div class="pf-reset-stat-row">
                            <span class="pf-reset-stat-label">总资产</span>
                            <span class="pf-reset-stat-value" style="color:#ef4444;">¥${(d.total_asset||0).toLocaleString(undefined,{minimumFractionDigits:2})}</span>
                        </div>
                    </div>`;
            } else {
                resetSummary.innerHTML = '<div style="color:#64748b;text-align:center;padding:20px;">无法加载当前组合数据</div>';
            }
        } catch(e) {
            resetSummary.innerHTML = '<div style="color:#64748b;text-align:center;padding:20px;">数据加载失败</div>';
        }

        resetConfirmInput.value = '';
        resetExecBtn.disabled = true;
        resetModal.style.display = 'flex';
        setTimeout(() => resetConfirmInput.focus(), 100);
    };

    // 输入 RESET 激活按钮
    resetConfirmInput.addEventListener('input', () => {
        resetExecBtn.disabled = resetConfirmInput.value.trim().toUpperCase() !== 'RESET';
    });

    // 执行清零
    resetExecBtn.onclick = async () => {
        if (resetConfirmInput.value.trim().toUpperCase() !== 'RESET') return;

        resetExecBtn.disabled = true;
        resetExecBtn.textContent = '⏳ 清零中...';
        try {
            const res = await fetch('/api/v1/portfolio/reset', { method: 'POST' });
            const result = await res.json();
            if (result.status === 'success') {
                resetModal.style.display = 'none';
                showToast(`✅ 组合已清零: 共清除 ${result.data.cleared_positions} 只持仓`, 'success', 4000);
                loadPortfolio();
            } else {
                showToast('清零失败: ' + (result.message || '未知错误'), 'error');
            }
        } catch(e) {
            showToast('网络错误: ' + e.message, 'error');
        } finally {
            resetExecBtn.disabled = false;
            resetExecBtn.textContent = '🗑️ 确认清零';
        }
    };

    // 关闭弹窗
    resetCloseBtn.onclick = () => resetModal.style.display = 'none';
    resetModal.addEventListener('click', (e) => {
        if (e.target === resetModal) resetModal.style.display = 'none';
    });

    // ════════════════════════════════════
    //  同步行情数据
    // ════════════════════════════════════

    const syncBtn = document.getElementById('sync-btn');

    syncBtn.onclick = async () => {
        syncBtn.disabled = true;
        syncBtn.textContent = '⏳ 同步中...';
        syncBtn.classList.add('btn-sync-loading');

        showToast('正在从 Tushare 拉取最新行情数据...', 'info', 4000);

        try {
            const res = await fetch('/api/v1/portfolio/sync', { method: 'POST' });
            const result = await res.json();

            if (result.status === 'success' && result.data.success) {
                const d = result.data;
                showToast(
                    `✅ ${d.message}` +
                    (d.failed > 0 ? ` · ${d.failed} 只失败` : '') +
                    (d.freshness?.daily_latest ? ` · 最新: ${d.freshness.daily_latest}` : ''),
                    d.failed > 0 ? 'warning' : 'success',
                    5000
                );
                // 刷新全部数据
                loadPortfolio();
            } else {
                showToast('同步失败: ' + (result.message || '未知错误'), 'error');
            }
        } catch (err) {
            showToast('网络错误: ' + err.message, 'error');
        } finally {
            syncBtn.disabled = false;
            syncBtn.textContent = '🔄 同步数据';
            syncBtn.classList.remove('btn-sync-loading');
        }
    };

    // ════════════════════════════════════
    //  事件绑定
    // ════════════════════════════════════

    window.quickTrade = (code, name) => {
        document.getElementById('trade-code').value = code;
        document.getElementById('trade-name').value = name;
        tradeAmount.value = '';
        tradePrice.value = '';
        tradeEst.textContent = '¥ 0.00';
        tradeModal.style.display = 'flex';
    };

    openTradeBtn.onclick = () => {
        document.getElementById('trade-code').value = '';
        document.getElementById('trade-name').value = '';
        tradeAmount.value = '';
        tradePrice.value = '';
        tradeEst.textContent = '¥ 0.00';
        tradeModal.style.display = 'flex';
    };

    closeTradeBtn.onclick = () => tradeModal.style.display = 'none';
    buyBtn.onclick = () => doTrade('buy');
    sellBtn.onclick = () => doTrade('sell');

    // 弹窗外部点击关闭
    tradeModal.addEventListener('click', (e) => {
        if (e.target === tradeModal) tradeModal.style.display = 'none';
    });

    // ESC 关闭弹窗
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (tradeModal.style.display === 'flex') tradeModal.style.display = 'none';
            if (importModal.style.display === 'flex') importModal.style.display = 'none';
            if (resetModal.style.display === 'flex') resetModal.style.display = 'none';
        }
    });

    // Resize
    window.addEventListener('resize', function () {
        Object.values(charts).forEach(c => c && c.resize());
        Object.values(gauges).forEach(g => g && g.resize());
    });

    // ════════════════════════════════════
    //  启动
    // ════════════════════════════════════

    loadPortfolio();
});

