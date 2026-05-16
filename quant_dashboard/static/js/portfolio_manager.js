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
 * - V26.0: 跨页持仓变更广播 (BroadcastChannel)
 */

// V26.0: 跨 Tab 持仓变更通知 (decision hub 自动刷新调仓路径)
function _broadcastPortfolioChange(action, detail) {
    const msg = { type: 'portfolio_updated', action, ts: Date.now(), ...detail };
    try {
        const bc = new BroadcastChannel('alphacore_portfolio');
        bc.postMessage(msg);
        bc.close();
    } catch(e) {
        // 降级: localStorage storage 事件 (跨 Tab 同样可触发)
        localStorage.setItem('_ac_portfolio_ts', Date.now().toString());
    }
}

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

        if (sectorEl && !charts.sector) charts.sector = AC.registerChart(echarts.init(sectorEl));
        if (mctrEl && !charts.mctr) charts.mctr = AC.registerChart(echarts.init(mctrEl));
        if (navEl && !charts.nav) charts.nav = AC.registerChart(echarts.init(navEl));
        if (sparkEl && !charts.sparkline) charts.sparkline = AC.registerChart(echarts.init(sparkEl));
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

        // 总仓位 (不含国债逆回购)
        // 国债逆回购代码: 131810/131811/131813 (深市), 204001/204002/204007 (沪市)
        const isRepo = (pos) => {
            const code = (pos.ts_code || '').split('.')[0];
            if (code.startsWith('131') || code.startsWith('204')) return true;
            const name = pos.name || '';
            return /逆回购|GC\d/.test(name);
        };
        const nonRepoMV = data.positions
            .filter(p => !isRepo(p))
            .reduce((sum, p) => sum + (p.market_value || 0), 0);
        const totalPosWeight = data.total_asset > 0 ? (nonRepoMV / data.total_asset * 100) : 0;
        const tpwEl = document.getElementById('total-position-weight');
        tpwEl.textContent = totalPosWeight.toFixed(1);
        // 颜色语义: >90% 过重(红), >80% 偏高(橙), 正常(紫)
        tpwEl.style.color = totalPosWeight > 90 ? '#f87171' : totalPosWeight > 80 ? '#fbbf24' : '#6366f1';

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
                if (result.data.skipped_codes && result.data.skipped_codes.length > 0) {
                    console.info('Risk: ' + result.data.skipped_codes.length + ' 只缺行情数据已跳过');
                }
            }
        } catch (err) {
            console.error('Failed to load risk metrics:', err);
            showToast('风控数据加载失败: ' + err.message, 'warning');
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
            console.error('Failed to load NAV:', err);
            showToast('净值曲线加载失败: ' + err.message, 'warning');
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
                textStyle: { color: '#f8fafc', fontSize: 12 },
                formatter: function(params) {
                    let html = `<strong>${params[0].axisValue}</strong>`;
                    let navVal = null, benchVal = null;
                    params.forEach(p => {
                        const marker = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px;"></span>`;
                        html += `<br>${marker}${p.seriesName}: ${p.value.toFixed(4)}`;
                        if (p.seriesName === '组合净值') navVal = p.value;
                        else benchVal = p.value;
                    });
                    if (navVal !== null && benchVal !== null) {
                        const alpha = ((navVal - benchVal) * 100).toFixed(2);
                        const alphaColor = alpha >= 0 ? '#10b981' : '#ef4444';
                        html += `<br><span style="color:${alphaColor};font-weight:700;">Alpha: ${alpha >= 0 ? '+' : ''}${alpha}%</span>`;
                    }
                    return html;
                }
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
            const res = await AC.secureFetch('/api/v1/portfolio/trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await res.json();

            if (result.status === 'success') {
                tradeModal.style.display = 'none';
                showToast(`${action === 'buy' ? '买入' : '卖出'} ${payload.name || payload.ts_code} 成功`, 'success');
                loadPortfolio();
                _broadcastPortfolioChange('trade', { code: payload.ts_code, side: action });
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

        // 解析第一行汇总 (V24.1: 对齐后端, 优先提取「余额」含冻结资金)
        let cashAvailable = 0;
        if (lines.length > 0) {
            const balanceMatch = lines[0].match(/余额[:：\s]*([0-9,.]+)/);
            const availMatch = lines[0].match(/可用[:：\s]*([0-9,.]+)/);
            const assetMatch = lines[0].match(/资产[:：\s]*([0-9,.]+)/);
            if (balanceMatch) cash = parseFloat(balanceMatch[1].replace(/,/g, ''));
            else if (availMatch) cash = parseFloat(availMatch[1].replace(/,/g, ''));
            if (availMatch) cashAvailable = parseFloat(availMatch[1].replace(/,/g, ''));
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
        const frozenNote = (cashAvailable > 0 && cash > cashAvailable)
            ? `<span style="font-size:0.7rem;color:#94a3b8;margin-left:4px;" title="可用 ¥${cashAvailable.toLocaleString(undefined,{minimumFractionDigits:2})}，差额为逆回购/冻结资金">(可用 ¥${cashAvailable.toLocaleString(undefined,{minimumFractionDigits:0})})</span>`
            : '';
        importSummary.innerHTML = `
            <div class="pf-import-stats">
                <span class="pf-import-stat">
                    <span class="pf-import-stat-label">检测到</span>
                    <span class="pf-import-stat-value pf-accent">${positions.length}</span>
                    <span class="pf-import-stat-label">只持仓</span>
                </span>
                <span class="pf-import-stat">
                    <span class="pf-import-stat-label">账户余额</span>
                    <span class="pf-import-stat-value pf-gold">¥${cash.toLocaleString(undefined, { minimumFractionDigits: 2 })}${frozenNote}</span>
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

            const res = await AC.secureFetch('/api/v1/portfolio/import', {
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
                _broadcastPortfolioChange('import', { count: result.data.imported });

                // V26.0: 异步获取调仓路径摘要 (不阻塞导入流程)
                fetch('/api/v1/decision/position-path')
                    .then(r => r.json())
                    .then(pp => {
                        if (pp.status === 'success' && Math.abs(pp.gap) > 3) {
                            const dir = pp.direction === 'decrease' ? '↓减仓' : '↑加仓';
                            showToast(
                                `🗺️ 调仓路径已更新: ${pp.current_cap}% → ${pp.target_cap}% (${dir}${Math.abs(pp.gap)}%)`,
                                'info', 6000
                            );
                        }
                    })
                    .catch(() => {});
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
            const res = await AC.secureFetch('/api/v1/portfolio/reset', { method: 'POST' });
            const result = await res.json();
            if (result.status === 'success') {
                resetModal.style.display = 'none';
                showToast(`✅ 组合已清零: 共清除 ${result.data.cleared_positions} 只持仓`, 'success', 4000);
                loadPortfolio();
                _broadcastPortfolioChange('reset', { cleared: result.data.cleared_positions });
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
            const res = await AC.secureFetch('/api/v1/portfolio/sync', { method: 'POST' });
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
                // 同步后延时重载风控/净值 (行情补齐后图表可能更完整)
                setTimeout(() => { loadRisk(); loadNavCurve(); }, 2500);
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

    // resize 由 AC (alphacore_utils.js) 统一管理

    // ════════════════════════════════════
    //  启动
    // ════════════════════════════════════

    loadPortfolio();

    // ════════════════════════════════════
    //  通用折叠面板系统 (V24.1)
    // ════════════════════════════════════

    document.querySelectorAll('.pf-collapsible-header[data-toggle]').forEach(header => {
        header.addEventListener('click', (e) => {
            // 不拦截 select/button 点击
            if (e.target.closest('select, button')) return;
            const bodyId = header.getAttribute('data-toggle');
            const body = document.getElementById(bodyId);
            const arrow = header.querySelector('.pf-collapse-arrow');
            const panel = header.closest('.glass-panel');
            if (!body) return;

            const isExpanded = body.classList.contains('pf-expanded');
            body.classList.toggle('pf-expanded', !isExpanded);
            if (arrow) arrow.classList.toggle('pf-arrow-open', !isExpanded);
            if (panel) panel.classList.toggle('pf-panel-collapsed', isExpanded);

            // 展开时触发 echarts resize (图表在 display:none 时尺寸为 0)
            if (!isExpanded) {
                setTimeout(() => {
                    body.querySelectorAll('[id$="-chart"]').forEach(el => {
                        const chart = echarts.getInstanceByDom(el);
                        if (chart) chart.resize();
                    });
                }, 420);
            }
        });
    });

    // 交易记录折叠/展开 (保留旧逻辑, 使用 display:none 而非 max-height)
    const historyToggle = document.getElementById('history-toggle');
    const historyList = document.getElementById('trade-history-list');
    const historyArrow = document.getElementById('history-arrow');
    if (historyToggle) {
        historyToggle.addEventListener('click', () => {
            const isHidden = historyList.style.display === 'none';
            historyList.style.display = isHidden ? 'block' : 'none';
            historyArrow.textContent = isHidden ? '▼' : '▶';
            historyArrow.classList.toggle('pf-arrow-open', isHidden);
        });
    }

    // ════════════════════════════════════
    //  ZONE 6: OMS 滑点归因面板 V2
    // ════════════════════════════════════

    let slipCharts = { trend: null, attr: null, gauge: null };
    let _slipAllOrders = [];

    function initSlippageCharts() {
        const trendEl = document.getElementById('slip-trend-chart');
        const attrEl = document.getElementById('slip-attr-chart');
        const gaugeEl = document.getElementById('slip-eqs-gauge');
        if (trendEl && !slipCharts.trend) slipCharts.trend = AC.registerChart(echarts.init(trendEl));
        if (attrEl && !slipCharts.attr) slipCharts.attr = AC.registerChart(echarts.init(attrEl));
        if (gaugeEl && !slipCharts.gauge) slipCharts.gauge = AC.registerChart(echarts.init(gaugeEl));
    }

    async function loadSlippagePanel() {
        try {
            const [eqsRes, summRes, histRes, attrRes, diagRes, ordRes] = await Promise.all([
                fetch('/api/v1/slippage/quality').then(r => r.json()),
                fetch('/api/v1/slippage/summary').then(r => r.json()),
                fetch('/api/v1/slippage/history?days=30').then(r => r.json()),
                fetch('/api/v1/slippage/attribution').then(r => r.json()),
                fetch('/api/v1/slippage/diagnose').then(r => r.json()),
                fetch('/api/v1/slippage/orders?days=90').then(r => r.json()),
            ]);
            if (eqsRes.status === 'success') renderSlipEQS(eqsRes.data);
            if (summRes.status === 'success') renderSlipSummary(summRes.data);
            if (histRes.status === 'success') renderSlipTrend(histRes.data);
            if (attrRes.status === 'success') renderSlipAttribution(attrRes.data);
            if (diagRes.status === 'success') renderSlipDiagnosis(diagRes.data);
            if (ordRes.status === 'success') renderSlipOrders(ordRes.data);
        } catch (err) {
            console.warn('Slippage panel load failed:', err);
        }
    }

    // ── EQS Gauge ──
    function renderSlipEQS(eqs) {
        initSlippageCharts();
        const avgEl = document.getElementById('slip-avg-bps');
        const trendEl = document.getElementById('slip-trend-label');
        const baselineNote = eqs.baseline_count > 0 ? ` (${eqs.baseline_count} 基线)` : '';
        const orderTotal = (eqs.order_count || 0) + (eqs.baseline_count || 0);
        document.getElementById('slip-order-count').textContent = `${orderTotal} 笔订单`;

        if (!eqs.has_data) {
            avgEl.innerHTML = '-- <small>bps</small>';
            trendEl.textContent = '待实盘数据' + baselineNote;
            trendEl.style.color = '#64748b';
            if (slipCharts.gauge) renderEQSGauge(0, '--', false);
            return;
        }
        avgEl.innerHTML = `${eqs.avg_slippage_bps.toFixed(1)} <small>bps</small>`;
        const tl = { improving: '📉 改善', deteriorating: '📈 恶化', stable: '➡️ 稳定', no_data: '--' };
        trendEl.textContent = tl[eqs.trend] || '--';
        trendEl.style.color = eqs.trend === 'improving' ? '#10b981' : eqs.trend === 'deteriorating' ? '#ef4444' : '#64748b';
        if (slipCharts.gauge) renderEQSGauge(eqs.score, eqs.grade, true);
        if (eqs.top_leakers && eqs.top_leakers.length > 0) renderTopLeakers(eqs.top_leakers);
    }

    function renderEQSGauge(score, grade, hasData) {
        const color = score >= 90 ? '#10b981' : score >= 80 ? '#34d399' : score >= 65 ? '#3b82f6' : score >= 50 ? '#f59e0b' : '#ef4444';
        slipCharts.gauge.setOption({
            backgroundColor: 'transparent',
            series: [{
                type: 'gauge', startAngle: 200, endAngle: -20,
                min: 0, max: 100, radius: '95%', center: ['50%', '60%'],
                progress: { show: true, width: 10, itemStyle: { color: hasData ? color : '#334155' } },
                axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(255,255,255,0.04)']] } },
                axisTick: { show: false }, splitLine: { show: false },
                axisLabel: { show: false },
                pointer: { show: false },
                title: { show: true, offsetCenter: [0, '30%'], fontSize: 11, color: hasData ? color : '#475569', fontWeight: 700 },
                detail: {
                    offsetCenter: [0, '-10%'], fontSize: 26, fontWeight: 800,
                    fontFamily: 'Outfit', color: hasData ? '#e2e8f0' : '#475569',
                    formatter: hasData ? '{value}' : '--',
                },
                data: [{ value: hasData ? score : 0, name: hasData ? grade : '待实盘' }],
                animationDuration: 1200, animationEasingUpdate: 'cubicOut',
            }],
        });
    }

    // ── Top Leakers ──
    function renderTopLeakers(leakers) {
        const section = document.getElementById('slip-leakers-section');
        const container = document.getElementById('slip-leakers-bars');
        if (!leakers || leakers.length === 0) { section.style.display = 'none'; return; }
        section.style.display = '';
        const maxCost = Math.max(...leakers.map(l => l.total_cost), 1);
        container.innerHTML = leakers.map(l => {
            const pct = Math.min(100, (l.total_cost / maxCost) * 100);
            return '<div class="slip-leaker-item">' +
                '<div class="slip-leaker-name">' + l.name + ' <small>' + l.ts_code + '</small></div>' +
                '<div class="slip-leaker-bar-wrap"><div class="slip-leaker-bar" style="width:' + pct + '%"></div></div>' +
                '<div class="slip-leaker-bps">' + l.avg_slip_bps + 'bps</div>' +
                '<div class="slip-leaker-cost">¥' + l.total_cost.toLocaleString() + '</div>' +
            '</div>';
        }).join('');
    }

    function renderSlipSummary(stats) {
        const p30 = stats.period_30d || {};
        document.getElementById('slip-total-cost').textContent = '¥ ' + (p30.total_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2});
        document.getElementById('slip-lifetime-cost').textContent = '历史累计 ¥ ' + ((stats.lifetime && stats.lifetime.total_cost) || 0).toLocaleString(undefined, {minimumFractionDigits: 2});
    }

    // ── Trend Chart + Empty State ──
    function renderSlipTrend(history) {
        initSlippageCharts();
        const emptyEl = document.getElementById('slip-trend-empty');
        if (!history || history.length === 0) {
            if (emptyEl) emptyEl.classList.remove('hidden');
            return;
        }
        if (emptyEl) emptyEl.classList.add('hidden');
        if (!slipCharts.trend) return;
        slipCharts.trend.setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: 'rgba(255,255,255,0.08)', textStyle: { color: '#f8fafc', fontSize: 12 } },
            legend: { right: '5%', top: '2%', textStyle: { color: '#94a3b8', fontSize: 11 } },
            grid: { left: '3%', right: '8%', bottom: '3%', top: '18%', containLabel: true },
            xAxis: { type: 'category', data: history.map(function(h) { return h.date.slice(5); }), axisLabel: { color: '#64748b', fontSize: 10 }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
            yAxis: [
                { type: 'value', name: 'bps', axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } } },
                { type: 'value', name: '¥', axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { show: false } }
            ],
            series: [{
                name: '滑点(bps)', type: 'line', data: history.map(function(h) { return h.avg_slippage_bps || 0; }),
                smooth: true, showSymbol: false, lineStyle: { width: 2.5, color: '#f59e0b' },
                areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: 'rgba(245,158,11,0.2)'}, {offset: 1, color: 'rgba(245,158,11,0.02)'}]) }
            }, {
                name: '损耗(¥)', type: 'bar', yAxisIndex: 1, data: history.map(function(h) { return h.total_slippage_cny || 0; }),
                itemStyle: { color: 'rgba(239,68,68,0.3)', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 16
            }],
            animationDuration: 1000,
        });
    }

    // ── Attribution Pie + Empty State ──
    function renderSlipAttribution(attr) {
        initSlippageCharts();
        const emptyEl = document.getElementById('slip-attr-empty');
        if (!attr.has_data) { if (emptyEl) emptyEl.classList.remove('hidden'); return; }
        if (emptyEl) emptyEl.classList.add('hidden');

        const mc = document.getElementById('slip-main-cause');
        const dt = document.getElementById('slip-cause-detail');
        if (attr.overnight_gap_pct > attr.intraday_drift_pct) {
            mc.textContent = '隔夜缺口';
            dt.textContent = '占比 ' + attr.overnight_gap_pct.toFixed(0) + '% · ' + attr.avg_overnight_bps.toFixed(1) + 'bps';
        } else {
            mc.textContent = '日内漂移';
            dt.textContent = '占比 ' + attr.intraday_drift_pct.toFixed(0) + '% · ' + attr.avg_intraday_bps.toFixed(1) + 'bps';
        }
        if (!slipCharts.attr) return;
        slipCharts.attr.setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'item', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: 'rgba(255,255,255,0.08)', textStyle: { color: '#f8fafc', fontSize: 12 } },
            legend: { bottom: '5%', textStyle: { color: '#94a3b8', fontSize: 11 } },
            series: [{
                type: 'pie', radius: ['45%', '75%'], center: ['50%', '42%'], avoidLabelOverlap: false,
                itemStyle: { borderRadius: 8, borderColor: 'rgba(15,23,42,0.6)', borderWidth: 3 },
                label: { show: true, formatter: '{b}\n{d}%', color: '#cbd5e1', fontSize: 12 },
                data: [
                    { value: attr.overnight_gap_pct, name: '隔夜缺口', itemStyle: { color: '#f59e0b' } },
                    { value: attr.intraday_drift_pct, name: '日内漂移', itemStyle: { color: '#ef4444' } }
                ],
                animationType: 'scale', animationDuration: 1200
            }],
        });
    }

    function renderSlipDiagnosis(findings) {
        const c = document.getElementById('slip-diag-cards');
        if (!findings || findings.length === 0) {
            c.innerHTML = '<div class="slip-diag-placeholder">暂无诊断结果</div>';
            return;
        }
        var icons = { warning: '⚠️', positive: '✅', info: 'ℹ️' };
        c.innerHTML = findings.map(function(f) {
            var cls = f.severity === 'warning' ? 'diag-warning' : f.severity === 'positive' ? 'diag-positive' : 'diag-info';
            return '<div class="slip-diag-card ' + cls + '">' +
                '<div class="slip-diag-title">' + (icons[f.severity] || '') + ' ' + f.title + '</div>' +
                '<div class="slip-diag-detail">' + f.detail + '</div></div>';
        }).join('');
    }

    // ── Orders Table with source badges + pagination ──
    function renderSlipOrders(orders) {
        _slipAllOrders = orders || [];
        _renderOrderPage(false);
    }

    function _renderOrderPage(showAll) {
        var body = document.getElementById('slip-orders-body');
        var moreWrap = document.getElementById('slip-show-more-wrap');
        var moreBtn = document.getElementById('slip-show-more-btn');
        if (!_slipAllOrders.length) {
            body.innerHTML = '<tr><td colspan="10" class="pf-table-empty">暂无执行记录 — 点击 Bootstrap 回填历史数据</td></tr>';
            if (moreWrap) moreWrap.style.display = 'none';
            return;
        }
        var display = showAll ? _slipAllOrders : _slipAllOrders.slice(0, 20);
        body.innerHTML = display.map(function(o) {
            var sl = o.side === 'buy' ? 'slip-side-buy' : 'slip-side-sell';
            var sd = o.side === 'buy' ? '买入' : o.side === 'sell' ? '卖出' : o.side;
            var bps = o.total_slippage_bps;
            var bc = bps > 0 ? 'slip-bps-positive' : bps < 0 ? 'slip-bps-negative' : 'slip-bps-zero';
            var src = o.exec_source === 'bootstrap' ? '<span class="slip-src-badge slip-src-baseline">BASELINE</span>'
                : o.exec_source === 'broker_import' ? '<span class="slip-src-badge slip-src-import">IMPORT</span>'
                : '<span class="slip-src-badge slip-src-live">LIVE</span>';
            var st = o.status === 'filled' ? '<span class="slip-status-filled">已成交</span>' : '<span class="slip-status-pending">待执行</span>';
            return '<tr>' +
                '<td class="pf-mono" style="font-size:0.82rem">' + (o.order_date || '--') + '</td>' +
                '<td><span style="font-weight:600">' + (o.name || '') + '</span> <span style="color:#475569;font-size:0.72rem">' + o.ts_code + '</span></td>' +
                '<td class="' + sl + '">' + sd + '</td>' +
                '<td class="pf-mono">' + (o.decision_price ? '¥' + o.decision_price.toFixed(3) : '--') + '</td>' +
                '<td class="pf-mono">' + (o.exec_price ? '¥' + o.exec_price.toFixed(3) : '--') + '</td>' +
                '<td class="pf-mono">' + (o.exec_amount ? o.exec_amount.toLocaleString() : '--') + '</td>' +
                '<td class="' + bc + '">' + (bps != null ? bps.toFixed(1) : '--') + '</td>' +
                '<td class="pf-mono" style="color:#f59e0b">' + (o.total_slippage_cny != null ? '¥' + Math.abs(o.total_slippage_cny).toFixed(2) : '--') + '</td>' +
                '<td>' + src + '</td>' +
                '<td>' + st + '</td></tr>';
        }).join('');

        if (_slipAllOrders.length > 20 && !showAll) {
            if (moreWrap) moreWrap.style.display = '';
            if (moreBtn) moreBtn.textContent = '展开全部 ' + _slipAllOrders.length + ' 笔';
        } else {
            if (moreWrap) moreWrap.style.display = 'none';
        }
    }

    // Show more button
    var showMoreBtn = document.getElementById('slip-show-more-btn');
    if (showMoreBtn) showMoreBtn.onclick = function() { _renderOrderPage(true); };

    // Refresh button
    var refreshBtn = document.getElementById('slip-refresh-btn');
    if (refreshBtn) {
        refreshBtn.onclick = function() {
            refreshBtn.classList.add('spinning');
            loadSlippagePanel().finally(function() { setTimeout(function() { refreshBtn.classList.remove('spinning'); }, 500); });
        };
    }

    // Bootstrap button
    var bootstrapBtn = document.getElementById('slippage-bootstrap-btn');
    if (bootstrapBtn) {
        bootstrapBtn.onclick = async function() {
            bootstrapBtn.disabled = true;
            bootstrapBtn.textContent = '⏳ 回填中...';
            try {
                var res = await AC.secureFetch('/api/v1/slippage/bootstrap', { method: 'POST' });
                var result = await res.json();
                if (result.status === 'success') {
                    showToast('Bootstrap: ' + (result.data.created || 0) + ' 笔回填, ' + (result.data.daily_summaries || 0) + ' 日汇总', 'success');
                    loadSlippagePanel();
                } else {
                    showToast((result.data && result.data.message) || 'Bootstrap 跳过', 'info');
                }
            } catch (err) { showToast('Bootstrap 失败', 'error'); }
            bootstrapBtn.disabled = false;
            bootstrapBtn.textContent = '📥 Bootstrap';
        };
    }

    setTimeout(loadSlippagePanel, 1500);
});


// ════════════════════════════════════════════════
//  V24.0: Brinson-Fachler 收益归因面板
// ════════════════════════════════════════════════

(function () {
    let brinsonWaterfall = null;
    let brinsonSector = null;

    function fmtPct(v) {
        if (v == null || isNaN(v)) return '--';
        const sign = v >= 0 ? '+' : '';
        return sign + v.toFixed(2) + '%';
    }
    function pctColor(v) { return v > 0 ? '#10b981' : v < 0 ? '#ef4444' : '#94a3b8'; }

    async function loadBrinson() {
        const period = document.getElementById('brinson-period')?.value || 20;
        try {
            const res = await fetch(`/api/v1/portfolio/brinson?days=${period}`);
            const result = await res.json();
            if (result.status === 'success' && result.data?.status === 'success') {
                renderBrinson(result.data);
            } else {
                console.warn('Brinson:', result.data?.error || result.message);
            }
        } catch (err) {
            console.error('Brinson load error:', err);
        }
    }

    function renderBrinson(d) {
        // KPI
        const portEl = document.getElementById('brinson-port-ret');
        const benchEl = document.getElementById('brinson-bench-ret');
        const alphaEl = document.getElementById('brinson-alpha');
        const allocEl = document.getElementById('brinson-alloc');
        const selectEl = document.getElementById('brinson-select');
        const interEl = document.getElementById('brinson-interact');
        const periodLabel = document.getElementById('brinson-period-label');
        const alphaLabel = document.getElementById('brinson-alpha-label');

        if (portEl) { portEl.textContent = fmtPct(d.portfolio_return); portEl.style.color = pctColor(d.portfolio_return); }
        if (benchEl) { benchEl.textContent = fmtPct(d.benchmark_return); }
        if (alphaEl) { alphaEl.textContent = fmtPct(d.excess_return); alphaEl.style.color = pctColor(d.excess_return); }
        if (allocEl) { allocEl.textContent = fmtPct(d.effects.allocation); allocEl.style.color = pctColor(d.effects.allocation); }
        if (selectEl) { selectEl.textContent = fmtPct(d.effects.selection); selectEl.style.color = pctColor(d.effects.selection); }
        if (interEl) { interEl.textContent = fmtPct(d.effects.interaction); interEl.style.color = pctColor(d.effects.interaction); }
        if (periodLabel) { periodLabel.textContent = `近${d.period_days}日`; }
        if (alphaLabel) {
            const desc = d.excess_return >= 0 ? '跑赢基准' : '跑输基准';
            alphaLabel.textContent = desc;
            alphaLabel.style.color = pctColor(d.excess_return);
        }

        renderWaterfall(d);
        renderSectorChart(d);
        renderSectorTable(d);
    }

    function renderWaterfall(d) {
        const el = document.getElementById('brinson-waterfall-chart');
        if (!el) return;
        if (!brinsonWaterfall) brinsonWaterfall = AC.registerChart(echarts.init(el));

        const e = d.effects;
        const cats = ['基准收益', '配置效应', '选股效应', '交互效应', '组合收益'];
        const benchVal = d.benchmark_return;

        // 瀑布图: 用堆叠 bar 模拟
        const transparent = [0, benchVal, benchVal + e.allocation, benchVal + e.allocation + e.selection, 0];
        const values = [benchVal, e.allocation, e.selection, e.interaction, d.portfolio_return];

        brinsonWaterfall.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis', axisPointer: { type: 'shadow' },
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 },
                formatter: p => `<strong>${p[0].axisValue}</strong><br/>贡献: ${p[1]?.value >= 0 ? '+' : ''}${(p[1]?.value || 0).toFixed(3)}%`
            },
            grid: { left: '3%', right: '5%', bottom: '5%', top: '8%', containLabel: true },
            xAxis: {
                type: 'category', data: cats,
                axisLabel: { color: '#cbd5e1', fontSize: 12 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontSize: 11, fontFamily: 'Outfit', formatter: v => v.toFixed(1) + '%' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            series: [
                {
                    name: 'base', type: 'bar', stack: 'w', data: transparent.map(v => Math.max(0, v)),
                    itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }
                },
                {
                    name: '贡献', type: 'bar', stack: 'w', data: values,
                    itemStyle: {
                        color: p => {
                            if (p.dataIndex === 0 || p.dataIndex === 4) return 'rgba(99,102,241,0.8)';
                            return p.value >= 0 ? 'rgba(16,185,129,0.8)' : 'rgba(239,68,68,0.8)';
                        },
                        borderRadius: [4, 4, 0, 0]
                    },
                    barMaxWidth: 48,
                    label: {
                        show: true, position: 'top',
                        formatter: p => (p.value >= 0 ? '+' : '') + p.value.toFixed(2) + '%',
                        color: '#e2e8f0', fontSize: 11, fontFamily: 'Outfit'
                    }
                }
            ],
            animationDuration: 1000, animationEasing: 'cubicOut'
        });
    }

    function renderSectorChart(d) {
        const el = document.getElementById('brinson-sector-chart');
        if (!el) return;
        if (!brinsonSector) brinsonSector = AC.registerChart(echarts.init(el));

        // Top 10 sectors by absolute total_effect
        const sectors = d.sector_detail.slice(0, 10).reverse();

        brinsonSector.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis', axisPointer: { type: 'shadow' },
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 },
                formatter: p => {
                    const s = sectors[p[0].dataIndex];
                    return `<strong>${s.sector}</strong><br/>
                        组合权重: ${s.portfolio_weight}%<br/>
                        基准权重: ${s.benchmark_weight}%<br/>
                        超配: ${s.weight_diff > 0 ? '+' : ''}${s.weight_diff}pp<br/>
                        总效应: ${s.total_effect > 0 ? '+' : ''}${s.total_effect}%`;
                }
            },
            grid: { left: '3%', right: '8%', bottom: '5%', top: '5%', containLabel: true },
            xAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontFamily: 'Outfit', fontSize: 11, formatter: v => v.toFixed(2) + '%' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            yAxis: {
                type: 'category', data: sectors.map(s => s.sector),
                axisLabel: { color: '#cbd5e1', fontWeight: 500, fontSize: 12 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            series: [{
                name: '总效应', type: 'bar',
                data: sectors.map(s => s.total_effect),
                itemStyle: {
                    color: p => p.value >= 0 ? 'rgba(16,185,129,0.8)' : 'rgba(239,68,68,0.75)',
                    borderRadius: [0, 6, 6, 0]
                },
                barMaxWidth: 18,
                label: {
                    show: true, position: 'right',
                    formatter: p => (p.value >= 0 ? '+' : '') + p.value.toFixed(3) + '%',
                    color: '#94a3b8', fontSize: 10, fontFamily: 'Outfit'
                }
            }],
            animationDuration: 1000, animationEasing: 'cubicOut'
        });
    }

    function renderSectorTable(d) {
        const body = document.getElementById('brinson-sector-body');
        if (!body) return;

        if (!d.sector_detail || d.sector_detail.length === 0) {
            body.innerHTML = '<tr><td colspan="8" class="pf-table-empty">无板块归因数据</td></tr>';
            return;
        }

        body.innerHTML = d.sector_detail.map(s => {
            const wdClass = s.weight_diff > 0 ? 'pf-up' : s.weight_diff < 0 ? 'pf-danger' : '';
            const teClass = s.total_effect > 0 ? 'pf-up' : s.total_effect < 0 ? 'pf-danger' : '';
            return `<tr>
                <td><strong>${s.sector}</strong></td>
                <td class="pf-mono">${s.portfolio_weight.toFixed(1)}%</td>
                <td class="pf-mono pf-dim">${s.benchmark_weight.toFixed(1)}%</td>
                <td class="pf-mono ${wdClass}">${s.weight_diff > 0 ? '+' : ''}${s.weight_diff.toFixed(1)}pp</td>
                <td class="pf-mono" style="color:${pctColor(s.portfolio_return)}">${fmtPct(s.portfolio_return)}</td>
                <td class="pf-mono" style="color:${pctColor(s.allocation_effect)}">${s.allocation_effect.toFixed(3)}%</td>
                <td class="pf-mono" style="color:${pctColor(s.selection_effect)}">${s.selection_effect.toFixed(3)}%</td>
                <td class="pf-mono ${teClass}" style="font-weight:600">${s.total_effect > 0 ? '+' : ''}${s.total_effect.toFixed(3)}%</td>
            </tr>`;
        }).join('');
    }

    // Bind events
    const refreshBtn = document.getElementById('brinson-refresh-btn');
    if (refreshBtn) {
        refreshBtn.onclick = () => {
            refreshBtn.classList.add('spinning');
            loadBrinson().finally(() => setTimeout(() => refreshBtn.classList.remove('spinning'), 500));
        };
    }

    const periodSelect = document.getElementById('brinson-period');
    if (periodSelect) {
        periodSelect.onchange = () => loadBrinson();
    }

    // Auto-load after portfolio data
    setTimeout(loadBrinson, 2500);

    // Resize
    window.addEventListener('resize', () => {
        if (brinsonWaterfall) brinsonWaterfall.resize();
        if (brinsonSector) brinsonSector.resize();
    });
})();


// ════════════════════════════════════════════════
//  V24.0: 多因子风险归因面板
// ════════════════════════════════════════════════

(function () {
    let factorRadar = null;
    let factorContrib = null;

    function fmtPct(v) {
        if (v == null || isNaN(v)) return '--';
        return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
    }
    function pctColor(v) { return v > 0 ? '#10b981' : v < 0 ? '#ef4444' : '#94a3b8'; }

    // Heatmap color: 0 → blue, 0.5 → neutral, 1 → green
    function heatColor(v) {
        if (v > 0.7) return 'rgba(16,185,129,0.25)';
        if (v > 0.5) return 'rgba(16,185,129,0.1)';
        if (v < 0.3) return 'rgba(239,68,68,0.2)';
        if (v < 0.5) return 'rgba(239,68,68,0.08)';
        return 'transparent';
    }
    function scoreLabel(v) {
        if (v >= 0.8) return '极高';
        if (v >= 0.6) return '偏高';
        if (v >= 0.4) return '中性';
        if (v >= 0.2) return '偏低';
        return '极低';
    }

    async function loadFactorAttr() {
        const period = document.getElementById('factor-period')?.value || 60;
        try {
            const res = await fetch(`/api/v1/portfolio/factor-attribution?days=${period}`);
            const result = await res.json();
            if (result.status === 'success' && result.data?.status === 'success') {
                renderFactorAttr(result.data);
            } else {
                console.warn('FactorAttr:', result.data?.error || result.message);
            }
        } catch (err) {
            console.error('FactorAttr load error:', err);
        }
    }

    function renderFactorAttr(d) {
        // KPI
        const r2El = document.getElementById('factor-r2');
        const r2Label = document.getElementById('factor-r2-label');
        const alphaEl = document.getElementById('factor-alpha');
        const alphaLabel = document.getElementById('factor-alpha-label');
        const sysEl = document.getElementById('factor-systematic');
        const betaEl = document.getElementById('factor-beta');

        if (r2El) {
            r2El.textContent = d.regression.r_squared_pct + '%';
            r2El.style.color = d.regression.r_squared > 0.6 ? '#10b981' : d.regression.r_squared > 0.3 ? '#f59e0b' : '#ef4444';
        }
        if (r2Label) {
            const q = d.regression.r_squared > 0.7 ? '高解释力' : d.regression.r_squared > 0.4 ? '中等解释力' : '低解释力';
            r2Label.textContent = q + ' · ' + d.lookback_days + '日窗口';
        }
        if (alphaEl) {
            alphaEl.textContent = fmtPct(d.regression.alpha_annual);
            alphaEl.style.color = pctColor(d.regression.alpha_annual);
        }
        if (alphaLabel) {
            alphaLabel.textContent = `日均 ${d.regression.alpha_daily} bps`;
        }
        if (sysEl) {
            sysEl.textContent = d.portfolio_decomposition.systematic_pct + '%';
            sysEl.style.color = d.portfolio_decomposition.systematic_pct > 70 ? '#ef4444' : '#10b981';
        }
        if (betaEl) {
            const mktFactor = d.factors.find(f => f.name === 'market');
            if (mktFactor) {
                betaEl.textContent = mktFactor.beta.toFixed(3);
                betaEl.style.color = mktFactor.beta > 1.1 ? '#ef4444' : mktFactor.beta < 0.8 ? '#3b82f6' : '#6366f1';
            }
        }

        renderRadar(d);
        renderContrib(d);
        renderStockTable(d);
    }

    function renderRadar(d) {
        const el = document.getElementById('factor-radar-chart');
        if (!el) return;
        if (!factorRadar) factorRadar = AC.registerChart(echarts.init(el));

        const factors = d.factors;
        // 统一 max=2.0, 保证各因子轴刻度一致且低暴露因子仍可见
        const indicators = factors.map(f => ({
            name: f.icon + ' ' + f.cn,
            max: 2.0,
        }));
        const values = factors.map(f => Math.abs(f.beta));

        factorRadar.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 },
            },
            radar: {
                indicator: indicators,
                shape: 'polygon',
                radius: '65%',
                axisName: { color: '#cbd5e1', fontSize: 12 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
                splitArea: { areaStyle: { color: ['rgba(99,102,241,0.02)', 'rgba(99,102,241,0.05)'] } },
            },
            series: [{
                type: 'radar',
                data: [{
                    value: values,
                    name: 'Factor Beta',
                    areaStyle: { color: 'rgba(99,102,241,0.2)' },
                    lineStyle: { color: '#6366f1', width: 2 },
                    itemStyle: { color: '#6366f1' },
                    symbol: 'circle', symbolSize: 6,
                }],
                tooltip: {
                    formatter: p => {
                        let html = '<strong>因子载荷 (|β|)</strong>';
                        factors.forEach((f, i) => {
                            html += `<br/>${f.icon} ${f.cn}: ${f.beta.toFixed(4)} (${f.exposure_level === 'high' ? '⚠️高暴露' : f.exposure_level === 'low' ? '✅低暴露' : '中性'})`;
                        });
                        return html;
                    }
                }
            }],
            animationDuration: 1200, animationEasing: 'elasticOut'
        });
    }

    function renderContrib(d) {
        const el = document.getElementById('factor-contrib-chart');
        if (!el) return;
        if (!factorContrib) factorContrib = AC.registerChart(echarts.init(el));

        const factors = [...d.factors].reverse();

        factorContrib.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis', axisPointer: { type: 'shadow' },
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                borderColor: 'rgba(255,255,255,0.08)',
                textStyle: { color: '#f8fafc', fontSize: 12 },
                formatter: p => {
                    const f = factors[p[0].dataIndex];
                    return `<strong>${f.icon} ${f.cn}</strong><br/>
                        Beta: ${f.beta.toFixed(4)}<br/>
                        因子年化收益: ${f.factor_return}%<br/>
                        期间贡献: ${f.contribution > 0 ? '+' : ''}${f.contribution}%<br/>
                        暴露等级: ${f.exposure_level === 'high' ? '⚠️高' : f.exposure_level === 'low' ? '✅低' : '中性'}`;
                }
            },
            grid: { left: '3%', right: '10%', bottom: '5%', top: '5%', containLabel: true },
            xAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontFamily: 'Outfit', fontSize: 11, formatter: v => v.toFixed(2) + '%' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }
            },
            yAxis: {
                type: 'category', data: factors.map(f => f.icon + ' ' + f.cn),
                axisLabel: { color: '#cbd5e1', fontWeight: 500, fontSize: 12 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            series: [{
                name: '贡献', type: 'bar',
                data: factors.map(f => f.contribution),
                itemStyle: {
                    // 方向色: 绿正红负, 不用因子品牌色 (品牌色保留给雷达图)
                    color: p => p.value >= 0 ? 'rgba(16,185,129,0.8)' : 'rgba(239,68,68,0.75)',
                    borderRadius: [0, 6, 6, 0]
                },
                barMaxWidth: 22,
                label: {
                    show: true, position: 'right',
                    formatter: p => (p.value >= 0 ? '+' : '') + p.value.toFixed(3) + '%',
                    color: '#94a3b8', fontSize: 10, fontFamily: 'Outfit'
                }
            }],
            animationDuration: 1000, animationEasing: 'cubicOut'
        });
    }

    function renderStockTable(d) {
        const body = document.getElementById('factor-stock-body');
        if (!body) return;

        if (!d.stock_exposures || d.stock_exposures.length === 0) {
            body.innerHTML = '<tr><td colspan="6" class="pf-table-empty">无个股因子数据</td></tr>';
            return;
        }

        body.innerHTML = d.stock_exposures.map(s => {
            return `<tr>
                <td><strong>${s.name}</strong> <span class="pf-dim" style="font-size:0.72rem">${s.ts_code}</span></td>
                <td class="pf-mono">${s.weight.toFixed(1)}%</td>
                <td><span class="pf-sector-tag">${s.industry}</span></td>
                <td class="pf-mono" style="background:${heatColor(s.momentum)}">${scoreLabel(s.momentum)} <small style="opacity:0.6">${(s.momentum * 100).toFixed(0)}%</small></td>
                <td class="pf-mono" style="background:${heatColor(1 - s.volatility)}" title="低波偏好: 越高表示该标的波动率越低">${scoreLabel(1 - s.volatility)} <small style="opacity:0.6">${(s.volatility * 100).toFixed(0)}%</small></td>
                <td class="pf-mono" style="background:${heatColor(s.quality)}">${scoreLabel(s.quality)} <small style="opacity:0.6">${(s.quality * 100).toFixed(0)}%</small></td>
            </tr>`;
        }).join('');
    }

    // Bind events
    const refreshBtn = document.getElementById('factor-refresh-btn');
    if (refreshBtn) {
        refreshBtn.onclick = () => {
            refreshBtn.classList.add('spinning');
            loadFactorAttr().finally(() => setTimeout(() => refreshBtn.classList.remove('spinning'), 500));
        };
    }

    const periodSelect = document.getElementById('factor-period');
    if (periodSelect) {
        periodSelect.onchange = () => loadFactorAttr();
    }

    // Auto-load after Brinson
    setTimeout(loadFactorAttr, 3500);

    // Resize
    window.addEventListener('resize', () => {
        if (factorRadar) factorRadar.resize();
        if (factorContrib) factorContrib.resize();
    });
})();
