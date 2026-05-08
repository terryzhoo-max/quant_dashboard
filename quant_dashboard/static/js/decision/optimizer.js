/**
 * AlphaCore V23.0 · 组合优化器前端模块 (生产级)
 * =================================================
 * - 权重对比条形图 (ECharts · 赛博主题)
 * - 有效前沿散点图 (ECharts · 能量发光)
 * - 调仓建议表 (行级微交互)
 * - 优化→调仓路径管道
 * - Shimmer 加载态 + Toast 集成
 */

/* global echarts, API_BASE, showToast */

const OPT_API = (window.API_BASE || '') + '/api/v1/decision';
let _optData = null;
let _optWeightChart = null;
let _optFrontierChart = null;

const _METHOD_LABELS = {
    'black_litterman': 'Black-Litterman',
    'mvo': '均值-方差 (MVO)',
    'equal_weight': '等权 (降级)',
};

const _METHOD_COLORS = {
    'black_litterman': '#60a5fa',
    'mvo': '#fbbf24',
    'equal_weight': '#94a3b8',
};

// ═══════════════════════════════════════
//  ECharts 赛博主题 (对齐系统)
// ═══════════════════════════════════════

const _CHART_THEME = {
    textColor: '#94a3b8',
    axisLine: { lineStyle: { color: 'rgba(148,163,184,0.1)' } },
    splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)', type: 'dashed' } },
    tooltip: {
        backgroundColor: 'rgba(15,23,42,0.92)',
        borderColor: 'rgba(255,255,255,0.08)',
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        extraCssText: 'backdrop-filter:blur(12px);border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,0.4);',
    },
};

// ═══════════════════════════════════════
//  一键优化 (含 shimmer 加载)
// ═══════════════════════════════════════

async function runOptimizer() {
    const btn = document.getElementById('btn-run-optimizer');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 优化计算中...'; }

    // Show shimmer loading
    const empty = document.getElementById('opt-empty');
    if (empty) {
        empty.innerHTML = '<div class="opt-loading">⏳ Black-Litterman 优化计算中<br><span style="font-size:0.72rem;color:#64748b;">协方差估计 → 观点融合 → 约束求解</span></div>';
    }

    try {
        const res = await fetch(OPT_API + '/optimize');
        const data = await res.json();

        if (data.status !== 'success') {
            _showOptError(data.error || '优化失败');
            return;
        }

        _optData = data;
        _renderOptResults(data);
        if (typeof showToast === 'function') {
            const emoji = data.method === 'black_litterman' ? '🧠' : '📊';
            showToast(emoji + ' 组合优化完成 · ' + (_METHOD_LABELS[data.method] || data.method), 'success');
        }

    } catch (e) {
        _showOptError('优化请求失败: ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '▶ 一键优化'; }
    }
}

function _showOptError(msg) {
    if (typeof showToast === 'function') showToast(msg, 'error');
    const empty = document.getElementById('opt-empty');
    if (empty) {
        empty.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p style="color:#fca5a5;">${msg}</p></div>`;
        empty.style.display = 'block';
    }
}

function _renderOptResults(d) {
    // Hide empty
    const empty = document.getElementById('opt-empty');
    if (empty) empty.style.display = 'none';

    // ── Meta row (技术参数) ──
    const meta = document.getElementById('opt-meta-row');
    if (meta) {
        meta.style.display = 'flex';
        const methodColor = _METHOD_COLORS[d.method] || '#94a3b8';
        meta.innerHTML = `
            <span class="opt-meta-item" style="border-left:3px solid ${methodColor};padding-left:10px;">
                🔬 ${_METHOD_LABELS[d.method] || d.method}
            </span>
            <span class="opt-meta-item">📊 ${d.data_days}日数据</span>
            <span class="opt-meta-item">🧬 收缩 ${(d.shrinkage_intensity * 100).toFixed(0)}%</span>
            <span class="opt-meta-item">👁️ ${d.view_count}个观点</span>
            <span class="opt-meta-item">🎯 仓位≤${d.total_cap}%</span>
            <span class="opt-meta-item">δ=${d.risk_aversion}</span>
        `;
    }

    // ── KPI 能量矩阵 ──
    const comp = document.getElementById('opt-comparison');
    if (comp) { comp.style.display = 'grid'; }

    const sharpeImproved = d.optimal.sharpe > d.current.sharpe;
    _setText('opt-cur-sharpe', d.current.sharpe.toFixed(2));

    const newSharpeEl = document.getElementById('opt-new-sharpe');
    if (newSharpeEl) {
        newSharpeEl.textContent = d.optimal.sharpe.toFixed(2);
        newSharpeEl.style.color = sharpeImproved ? '#6ee7b7' : '#fca5a5';
        newSharpeEl.style.textShadow = sharpeImproved
            ? '0 0 16px rgba(16,185,129,0.5)'
            : '0 0 16px rgba(239,68,68,0.5)';
    }

    _setText('opt-turnover', (d.turnover || 0).toFixed(1) + '%');
    _setText('opt-cost', (d.estimated_cost || 0).toFixed(2) + '%');

    const methodEl = document.getElementById('opt-method');
    if (methodEl) {
        const shortLabel = d.method === 'black_litterman' ? 'BL' : d.method === 'mvo' ? 'MVO' : 'EW';
        methodEl.textContent = shortLabel;
        methodEl.style.color = _METHOD_COLORS[d.method] || '#94a3b8';
    }

    // ── Charts ──
    const chartsRow = document.getElementById('opt-charts-row');
    if (chartsRow) chartsRow.style.display = 'grid';

    // Delay chart render to let layout settle
    requestAnimationFrame(() => {
        _renderWeightChart(d.rebalance);
        _renderFrontierChart(d.frontier, d.current, d.optimal);
    });

    // ── Rebalance table ──
    _renderRebalanceTable(d.rebalance);

    // ── Compliance & warnings ──
    _renderCompliance(d.compliance);
    _renderWarnings(d.warnings);

    // ── Show path button ──
    const pathBtn = document.getElementById('btn-apply-path');
    if (pathBtn) pathBtn.style.display = 'inline-block';
}

// ═══════════════════════════════════════
//  权重对比 (水平对称条形图)
// ═══════════════════════════════════════

function _renderWeightChart(rebalance) {
    const dom = document.getElementById('opt-weight-chart');
    if (!dom || !rebalance || !rebalance.length) return;

    if (_optWeightChart) _optWeightChart.dispose();
    _optWeightChart = echarts.init(dom);

    // Sort by delta magnitude (biggest change first)
    const sorted = [...rebalance].sort((a, b) => Math.abs(b.delta_weight) - Math.abs(a.delta_weight));
    const names = sorted.map(r => r.name.length > 8 ? r.name.slice(0, 8) + '..' : r.name);
    const curW = sorted.map(r => r.current_weight);
    const optW = sorted.map(r => r.optimal_weight);

    _optWeightChart.setOption({
        tooltip: {
            ..._CHART_THEME.tooltip,
            trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: params => {
                const idx = params[0]?.dataIndex;
                if (idx === undefined) return '';
                const r = sorted[idx];
                const dc = r.delta_weight > 0 ? '#6ee7b7' : r.delta_weight < 0 ? '#fca5a5' : '#94a3b8';
                const sign = r.delta_weight > 0 ? '+' : '';
                return `<b>${r.name}</b> <span style="color:#64748b;font-size:0.72rem;">${r.code}</span><br>`
                    + `当前: ${r.current_weight.toFixed(1)}%<br>`
                    + `最优: <b style="color:#60a5fa">${r.optimal_weight.toFixed(1)}%</b><br>`
                    + `<span style="color:${dc}">Δ ${sign}${r.delta_weight.toFixed(1)}%</span> · `
                    + `${r.action === 'increase' ? '🟢 加仓' : r.action === 'reduce' ? '🔴 减仓' : '⚪ 持有'}`;
            }
        },
        legend: {
            data: ['当前权重', '最优权重'],
            textStyle: { color: '#94a3b8', fontSize: 11 },
            top: 0, right: 10,
        },
        grid: { left: 10, right: 20, top: 36, bottom: 4, containLabel: true },
        xAxis: {
            type: 'value',
            axisLabel: { formatter: '{value}%', color: '#64748b', fontSize: 10 },
            axisLine: _CHART_THEME.axisLine,
            splitLine: _CHART_THEME.splitLine,
        },
        yAxis: {
            type: 'category', data: names,
            axisLabel: { color: '#cbd5e1', fontSize: 11, fontWeight: 500 },
            axisLine: { show: false }, axisTick: { show: false },
            inverse: true,
        },
        series: [
            {
                name: '当前权重', type: 'bar', barWidth: 10, barGap: '30%',
                data: curW,
                itemStyle: {
                    color: 'rgba(100,116,139,0.4)',
                    borderRadius: [0, 4, 4, 0],
                    borderColor: 'rgba(148,163,184,0.2)', borderWidth: 1,
                },
            },
            {
                name: '最优权重', type: 'bar', barWidth: 10,
                data: optW.map((v, i) => ({
                    value: v,
                    itemStyle: {
                        color: sorted[i].delta_weight > 0.3
                            ? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
                                colorStops: [{ offset: 0, color: 'rgba(59,130,246,0.6)' }, { offset: 1, color: 'rgba(99,102,241,0.8)' }] }
                            : sorted[i].delta_weight < -0.3
                            ? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
                                colorStops: [{ offset: 0, color: 'rgba(239,68,68,0.5)' }, { offset: 1, color: 'rgba(239,68,68,0.7)' }] }
                            : 'rgba(148,163,184,0.3)',
                        borderRadius: [0, 4, 4, 0],
                    }
                })),
                label: {
                    show: true, position: 'right',
                    formatter: p => {
                        const r = sorted[p.dataIndex];
                        const sign = r.delta_weight > 0 ? '+' : '';
                        return Math.abs(r.delta_weight) > 0.3 ? `${sign}${r.delta_weight.toFixed(1)}` : '';
                    },
                    fontSize: 9, fontWeight: 700,
                    color: p => sorted[p.dataIndex]?.delta_weight > 0 ? '#6ee7b7' : '#fca5a5',
                }
            }
        ],
        animationDuration: 800,
        animationEasing: 'cubicOut',
    });

    const ro = new ResizeObserver(() => _optWeightChart && _optWeightChart.resize());
    ro.observe(dom);
}

// ═══════════════════════════════════════
//  有效前沿 (能量发光散点图)
// ═══════════════════════════════════════

function _renderFrontierChart(frontier, current, optimal) {
    const dom = document.getElementById('opt-frontier-chart');
    if (!dom) return;

    if (_optFrontierChart) _optFrontierChart.dispose();
    _optFrontierChart = echarts.init(dom);

    const fData = (frontier || []).map(p => [p.volatility, p['return']]);

    _optFrontierChart.setOption({
        tooltip: {
            ..._CHART_THEME.tooltip,
            formatter: p => {
                if (p.componentType !== 'series') return '';
                if (p.seriesName === '有效前沿') return `波动率: ${p.data[0]}%<br>年化收益: ${p.data[1]}%`;
                return `<b>${p.seriesName}</b><br>波动率: ${p.data[0]}%<br>收益: ${p.data[1]}%`;
            }
        },
        legend: {
            data: ['有效前沿', '当前组合', '最优组合'],
            textStyle: { color: '#94a3b8', fontSize: 11 },
            top: 0, right: 10,
        },
        grid: { left: 50, right: 30, top: 40, bottom: 40 },
        xAxis: {
            name: '波动率 (%)', nameTextStyle: { color: '#64748b', fontSize: 11 },
            axisLabel: { color: '#64748b', fontSize: 10 },
            axisLine: _CHART_THEME.axisLine,
            splitLine: _CHART_THEME.splitLine,
        },
        yAxis: {
            name: '年化收益 (%)', nameTextStyle: { color: '#64748b', fontSize: 11 },
            axisLabel: { color: '#64748b', fontSize: 10 },
            axisLine: _CHART_THEME.axisLine,
            splitLine: _CHART_THEME.splitLine,
        },
        series: [
            {
                name: '有效前沿', type: 'line', smooth: true, data: fData,
                symbolSize: 6, showSymbol: true,
                lineStyle: { color: 'rgba(99,102,241,0.6)', width: 2 },
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(99,102,241,0.15)' },
                            { offset: 1, color: 'rgba(99,102,241,0.01)' }
                        ]
                    }
                },
                itemStyle: { color: '#818cf8', borderColor: 'rgba(129,140,248,0.3)', borderWidth: 4 },
            },
            {
                name: '当前组合', type: 'scatter',
                data: current ? [[current.volatility, current.expected_return]] : [],
                symbolSize: 18, symbol: 'diamond',
                itemStyle: {
                    color: '#f97316', borderColor: 'rgba(249,115,22,0.3)', borderWidth: 6,
                    shadowColor: 'rgba(249,115,22,0.5)', shadowBlur: 16,
                },
                label: {
                    show: true, position: 'right', formatter: '当前',
                    fontSize: 10, fontWeight: 700, color: '#fb923c',
                },
            },
            {
                name: '最优组合', type: 'scatter',
                data: optimal ? [[optimal.volatility, optimal.expected_return]] : [],
                symbolSize: 20, symbol: 'pin',
                itemStyle: {
                    color: '#10b981', borderColor: 'rgba(16,185,129,0.3)', borderWidth: 6,
                    shadowColor: 'rgba(16,185,129,0.5)', shadowBlur: 16,
                },
                label: {
                    show: true, position: 'right', formatter: '最优',
                    fontSize: 10, fontWeight: 700, color: '#6ee7b7',
                },
            }
        ],
        animationDuration: 1000,
        animationEasing: 'cubicOut',
    });

    const ro = new ResizeObserver(() => _optFrontierChart && _optFrontierChart.resize());
    ro.observe(dom);
}

// ═══════════════════════════════════════
//  调仓建议表 (机构级)
// ═══════════════════════════════════════

function _renderRebalanceTable(rebalance) {
    const card = document.getElementById('opt-rebalance-card');
    const table = document.getElementById('opt-rebalance-table');
    if (!card || !table || !rebalance) return;

    card.style.display = 'block';

    const actionMap = {
        increase: { icon: '▲', label: '加仓', color: '#6ee7b7', bg: 'rgba(16,185,129,0.06)' },
        reduce:   { icon: '▼', label: '减仓', color: '#fca5a5', bg: 'rgba(239,68,68,0.06)' },
        hold:     { icon: '━', label: '持有', color: '#64748b', bg: 'transparent' },
    };

    let html = `<thead><tr>
        <th style="width:22%">标的</th>
        <th style="width:12%">行业</th>
        <th style="width:10%;text-align:right">当前%</th>
        <th style="width:10%;text-align:right">最优%</th>
        <th style="width:10%;text-align:right">Δ权重</th>
        <th style="width:14%;text-align:right">Δ金额</th>
        <th style="width:10%;text-align:center">操作</th>
    </tr></thead><tbody>`;

    for (const r of rebalance) {
        const a = actionMap[r.action] || actionMap.hold;
        const deltaColor = r.delta_weight > 0 ? '#6ee7b7' : r.delta_weight < 0 ? '#fca5a5' : '#64748b';
        const deltaSign = r.delta_weight > 0 ? '+' : '';
        const deltaVal = Math.abs(r.delta_value) >= 10000
            ? (r.delta_value / 10000).toFixed(1) + '万'
            : Math.round(r.delta_value).toLocaleString();

        html += `<tr style="background:${a.bg}">
            <td>
                <b style="color:#e2e8f0">${r.name}</b><br>
                <span style="color:#475569;font-size:0.65rem;font-family:monospace;">${r.code}</span>
            </td>
            <td style="color:#94a3b8;font-size:0.72rem;">${r.industry}</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums;">${r.current_weight.toFixed(1)}</td>
            <td style="text-align:right;color:#60a5fa;font-weight:700;font-variant-numeric:tabular-nums;">${r.optimal_weight.toFixed(1)}</td>
            <td style="text-align:right;color:${deltaColor};font-weight:700;font-variant-numeric:tabular-nums;">${deltaSign}${r.delta_weight.toFixed(1)}</td>
            <td style="text-align:right;color:${deltaColor};font-variant-numeric:tabular-nums;">${r.delta_value > 0 ? '+' : ''}${deltaVal}</td>
            <td style="text-align:center;">
                <span style="color:${a.color};font-weight:700;font-size:0.75rem;">
                    ${a.icon} ${a.label}
                </span>
            </td>
        </tr>`;
    }

    html += '</tbody>';
    table.innerHTML = html;
}

// ═══════════════════════════════════════
//  合规 & 警告
// ═══════════════════════════════════════

function _renderCompliance(comp) {
    const el = document.getElementById('opt-compliance');
    if (!el || !comp) return;

    if (comp.status === 'passed') {
        el.innerHTML = '<div class="opt-compliance-pass">🟢 全部合规规则审查通过 · 无违规项</div>';
    } else if (comp.status === 'blocked') {
        const blocks = (comp.blocks || []).map(b =>
            `<div class="opt-block-item">🛑 <b>${b.rule}</b>: ${b.detail}</div>`
        ).join('');
        el.innerHTML = `<div class="opt-compliance-block">${blocks}</div>`;
    } else {
        el.innerHTML = `<div class="opt-compliance-warn">⚠️ 合规状态: ${comp.status}</div>`;
    }
}

function _renderWarnings(warnings) {
    const el = document.getElementById('opt-warnings');
    if (!el) return;
    if (!warnings || !warnings.length) { el.innerHTML = ''; return; }
    el.innerHTML = warnings.map(w => `<div class="opt-warn-item">⚠️ ${w}</div>`).join('');
}

// ═══════════════════════════════════════
//  优化→调仓路径管道
// ═══════════════════════════════════════

async function applyOptToPath() {
    const btn = document.getElementById('btn-apply-path');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }

    try {
        const res = await fetch(OPT_API + '/optimize-path');
        const data = await res.json();

        if (data.status !== 'success') {
            if (typeof showToast === 'function') showToast(data.error || '路径生成失败', 'error');
            return;
        }

        const card = document.getElementById('opt-path-card');
        const body = document.getElementById('opt-path-body');
        const gap = document.getElementById('opt-path-gap');
        if (!card || !body) return;

        card.style.display = 'block';

        const path = data.path;
        if (gap) {
            const g = path.gap || 0;
            gap.textContent = (g > 0 ? '+' : '') + g.toFixed(1) + '%';
            gap.className = 'pp-gap-badge ' + (g > 0 ? 'pp-gap-up' : g < 0 ? 'pp-gap-down' : '');
        }

        let html = '';
        for (const step of (path.steps || [])) {
            const stepColor = step.step_cap > 70 ? '#34d399' : step.step_cap > 40 ? '#fbbf24' : '#f87171';
            html += `<div class="pp-step" style="--step-color:${stepColor}">
                <div class="pp-step-header">
                    <div class="pp-step-hdr-left">
                        <span class="pp-step-icon">📅</span>
                        <span class="pp-step-day">${step.day}</span>
                        ${step.note ? `<span class="pp-step-note">${step.note}</span>` : ''}
                    </div>
                    <div class="pp-step-hdr-right">
                        <span class="pp-step-cap" style="color:${stepColor}">→ ${step.step_cap}%</span>
                    </div>
                </div>
                <div class="pp-step-actions">`;

            for (const a of (step.actions || [])) {
                const color = a.action === 'reduce' ? '#fca5a5' : a.action === 'increase' ? '#6ee7b7' : '#94a3b8';
                const sign = a.delta > 0 ? '+' : '';
                const icon = a.action === 'reduce' ? '▼' : a.action === 'increase' ? '▲' : '━';
                html += `<div class="pp-action-row pp-action-${a.action || 'hold'}">
                    <span class="pp-action-icon" style="color:${color}">${icon}</span>
                    <span class="pp-action-name">${a.name}</span>
                    <span class="pp-action-weights">${a.current_weight.toFixed(1)} → ${a.target_weight.toFixed(1)}%</span>
                    <span class="pp-action-delta" style="color:${color}">${sign}${a.delta.toFixed(1)}%</span>
                    <span class="pp-action-reason">${a.reason}</span>
                    <span class="pp-action-cost" title="预估成本">${(Math.abs(a.delta) * 0.003).toFixed(2)}%</span>
                </div>`;
            }

            if (!step.actions || !step.actions.length) {
                html += '<div class="pp-no-action">━ 无操作</div>';
            }
            html += '</div></div>';
        }

        // Warnings
        if (path.warnings && path.warnings.length) {
            html += '<div class="pp-warnings">' +
                path.warnings.map(w => `<div class="pp-warn-item">⚠️ ${w}</div>`).join('') +
                '</div>';
        }

        body.innerHTML = html;
        if (typeof showToast === 'function') showToast('🗺️ 调仓路径已生成', 'success');

    } catch (e) {
        if (typeof showToast === 'function') showToast('路径请求失败: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🗺️ 生成调仓路径'; }
    }
}

// ═══════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════

function _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}
