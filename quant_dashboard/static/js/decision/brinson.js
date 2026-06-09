/**
 * AlphaCore · Brinson 收益归因模块
 * ==================================
 * - 三大效应概览卡片 (配置/选股/交互)
 * - ECharts 堆叠柱状图 (行业 × 三效应)
 * - 行业明细表格
 * - TOP5 贡献/拖累标的
 * - 期间选择器 (20/60/120 日)
 *
 * 依赖: _safeFetch, _getChart, _fmt (from _infra.js)
 */

// ═══════════════════════════════════════════════════
//  状态
// ═══════════════════════════════════════════════════

let _brinsonLookback = 20;
let _brinsonData = null;
let _brinsonLoading = false;

// ═══════════════════════════════════════════════════
//  入口: 加载 Brinson 归因
// ═══════════════════════════════════════════════════

async function loadBrinsonAttribution(lookback) {
    if (_brinsonLoading) return;
    _brinsonLoading = true;

    if (lookback != null) _brinsonLookback = lookback;

    const container = document.getElementById('brinson-container');
    if (!container) { _brinsonLoading = false; return; }

    // 加载态
    container.innerHTML = `
        <div class="brinson-loading">
            <div class="loading-spinner">⏳ 加载 Brinson 归因 (近${_brinsonLookback}日)...</div>
        </div>`;

    try {
        const data = await _safeFetch(`${API_BASE}/brinson?lookback=${_brinsonLookback}`);
        _brinsonData = data;

        if (data.status === 'success') {
            renderBrinson(data);
        } else {
            container.innerHTML = `<div class="brinson-error">⚠️ ${data.error || data.message || '归因计算失败'}</div>`;
        }
    } catch (e) {
        console.warn('[Brinson] load error:', e);
        container.innerHTML = `
            <div class="brinson-error">
                ⚠️ Brinson 归因加载失败
                <button class="sg-refresh-btn" style="margin-left:8px;font-size:0.72rem;"
                    onclick="loadBrinsonAttribution()">↻ 重试</button>
            </div>`;
    } finally {
        _brinsonLoading = false;
    }
}

// ═══════════════════════════════════════════════════
//  主渲染
// ═══════════════════════════════════════════════════

function renderBrinson(d) {
    const container = document.getElementById('brinson-container');
    if (!container) return;

    const eff = d.effects || {};
    const sectors = d.sector_detail || [];

    // 计算双向数据条的最大基准绝对值
    const maxWeightDiff = Math.max(...sectors.map(s => Math.abs(s.weight_diff || 0))) || 1;
    const maxTotalEffect = Math.max(...sectors.map(s => Math.abs(s.total_effect || 0))) || 1;

    container.innerHTML = `
        <!-- 概览行: 组合 vs 基准 + 期间选择器 -->
        <div class="brinson-overview-row">
            <div class="brinson-overview-left">
                <span class="brinson-overview-item">
                    <span class="brinson-label">组合收益</span>
                    <span class="brinson-val ${d.portfolio_return >= 0 ? 'positive' : 'negative'}">
                        ${d.portfolio_return >= 0 ? '+' : ''}${_fmt(d.portfolio_return, 2)}%
                    </span>
                </span>
                <span class="brinson-overview-item">
                    <span class="brinson-label">基准 (${d.benchmark || '沪深300'})</span>
                    <span class="brinson-val">${d.benchmark_return >= 0 ? '+' : ''}${_fmt(d.benchmark_return, 2)}%</span>
                </span>
                <span class="brinson-overview-item">
                    <span class="brinson-label">超额收益</span>
                    <span class="brinson-val excess ${d.excess_return >= 0 ? 'positive' : 'negative'}">
                        ${d.excess_return >= 0 ? '+' : ''}${_fmt(d.excess_return, 2)}%
                    </span>
                </span>
            </div>
            <div class="brinson-lookback-select">
                <select id="brinson-lookback" onchange="loadBrinsonAttribution(+this.value)">
                    <option value="20" ${_brinsonLookback === 20 ? 'selected' : ''}>近 20 日</option>
                    <option value="60" ${_brinsonLookback === 60 ? 'selected' : ''}>近 60 日</option>
                    <option value="120" ${_brinsonLookback === 120 ? 'selected' : ''}>近 120 日</option>
                </select>
            </div>
        </div>

        <!-- 三大效应卡片 -->
        <div class="brinson-effects-grid">
            ${_renderEffectCard('配置效应', eff.allocation, '行业选择贡献', 'allocation')}
            ${_renderEffectCard('选股效应', eff.selection, '个股选择贡献', 'selection')}
            ${_renderEffectCard('交互效应', eff.interaction, '交叉叠加效应', 'interaction')}
        </div>

        <!-- ECharts 时序归因折线图 + 行业效应柱状图 -->
        <div class="brinson-charts-container">
            <div class="brinson-chart-wrap flex-chart">
                <h4 class="brinson-section-title">📈 累计超额收益与归因时序</h4>
                <div id="brinson-timeline-chart" style="width:100%;height:300px;"></div>
            </div>
            <div class="brinson-chart-wrap flex-chart">
                <h4 class="brinson-section-title">📊 行业归因效应分解 (BHB)</h4>
                <div id="brinson-sector-chart" style="width:100%;height:300px;"></div>
            </div>
        </div>

        <!-- 行业明细表格 -->
        <div class="brinson-table-wrap">
            <h4 class="brinson-section-title">📊 行业明细</h4>
            <div class="brinson-table-scroll">
                <table class="brinson-table" id="brinson-sector-table">
                    <thead>
                        <tr>
                            <th>行业</th>
                            <th>组合权重</th>
                            <th>基准权重</th>
                            <th>超配</th>
                            <th>组合收益</th>
                            <th>基准收益</th>
                            <th>配置</th>
                            <th>选股</th>
                            <th>交互</th>
                            <th>总效应</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${sectors.map(s => _renderSectorRow(s, maxWeightDiff, maxTotalEffect)).join('')}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- TOP5 贡献/拖累 -->
        <div class="brinson-top-grid">
            ${_renderTopList('🏆 TOP5 贡献', d.top_contributors, 'positive')}
            ${_renderTopList('⚠️ TOP5 拖累', d.top_detractors, 'negative')}
        </div>
    `;

    // 渲染 ECharts
    _renderBrinsonTimelineChart(d.timeline);
    _renderBrinsonChart(sectors);
}

// ═══════════════════════════════════════════════════
//  效应卡片
// ═══════════════════════════════════════════════════

function _renderEffectCard(title, value, desc, type) {
    const colorMap = {
        allocation: { pos: '#3b82f6', neg: '#60a5fa' },
        selection:  { pos: '#10b981', neg: '#34d399' },
        interaction:{ pos: '#f59e0b', neg: '#fbbf24' },
    };
    const colors = colorMap[type] || { pos: '#94a3b8', neg: '#94a3b8' };
    const color = value >= 0 ? colors.pos : colors.neg;
    const sign = value >= 0 ? '+' : '';

    return `
    <div class="brinson-effect-card" style="--effect-color: ${color}">
        <div class="brinson-effect-title">${title}</div>
        <div class="brinson-effect-value" style="color: ${color}">
            ${sign}${_fmt(value, 3)}%
        </div>
        <div class="brinson-effect-desc">${desc}</div>
    </div>`;
}

// ═══════════════════════════════════════════════════
//  行业表格行
// ═══════════════════════════════════════════════════

function _renderSectorRow(s, maxWd, maxTe) {
    const wd = s.weight_diff || 0;
    const te = s.total_effect || 0;

    // Excel 风格的双向微型渐变背景数据条 (50% 居中)
    let wdBar = '';
    if (wd > 0) {
        const pct = (wd / maxWd) * 45; // 保留一些边缘空白
        wdBar = `background: linear-gradient(90deg, transparent 50%, rgba(16,185,129,0.1) 50%, rgba(16,185,129,0.1) ${50 + pct}%, transparent ${50 + pct}%)`;
    } else if (wd < 0) {
        const pct = (Math.abs(wd) / maxWd) * 45;
        wdBar = `background: linear-gradient(90deg, transparent ${50 - pct}%, rgba(239,68,68,0.1) ${50 - pct}%, rgba(239,68,68,0.1) 50%, transparent 50%)`;
    }

    let teBar = '';
    if (te > 0) {
        const pct = (te / maxTe) * 45;
        teBar = `background: linear-gradient(90deg, transparent 50%, rgba(16,185,129,0.12) 50%, rgba(16,185,129,0.12) ${50 + pct}%, transparent ${50 + pct}%)`;
    } else if (te < 0) {
        const pct = (Math.abs(te) / maxTe) * 45;
        teBar = `background: linear-gradient(90deg, transparent ${50 - pct}%, rgba(239,68,68,0.12) ${50 - pct}%, rgba(239,68,68,0.12) 50%, transparent 50%)`;
    }

    const wdColor = wd > 0 ? '#34d399' : (wd < 0 ? '#f87171' : '#94a3b8');
    const totalColor = te > 0 ? '#34d399' : (te < 0 ? '#f87171' : '#cbd5e1');

    const fmtEffect = (v) => {
        if (v == null || isNaN(v)) return '<span class="brinson-cell-na">--</span>';
        const color = v > 0 ? '#34d399' : (v < 0 ? '#f87171' : '#64748b');
        return `<span style="color:${color}">${v >= 0 ? '+' : ''}${v.toFixed(3)}</span>`;
    };

    return `
    <tr>
        <td class="brinson-cell-sector">${s.sector}</td>
        <td>${_fmt(s.portfolio_weight, 1)}%</td>
        <td>${_fmt(s.benchmark_weight, 1)}%</td>
        <td style="${wdBar}; color:${wdColor}; font-weight:600">
            ${wd > 0 ? '+' : ''}${_fmt(wd, 1)}
        </td>
        <td>${s.portfolio_return != null ? (s.portfolio_return >= 0 ? '+' : '') + _fmt(s.portfolio_return, 2) + '%' : '--'}</td>
        <td>${s.benchmark_return != null ? (s.benchmark_return >= 0 ? '+' : '') + _fmt(s.benchmark_return, 2) + '%' : '--'}</td>
        <td>${fmtEffect(s.allocation_effect)}</td>
        <td>${fmtEffect(s.selection_effect)}</td>
        <td>${fmtEffect(s.interaction_effect)}</td>
        <td style="${teBar}; color:${totalColor}; font-weight:700">
            ${te >= 0 ? '+' : ''}${_fmt(te, 3)}
        </td>
    </tr>`;
}

// ═══════════════════════════════════════════════════
//  TOP5 贡献/拖累列表
// ═══════════════════════════════════════════════════

function _renderTopList(title, items, cls) {
    if (!items || items.length === 0) {
        return `<div class="brinson-top-col ${cls}">
            <h4 class="brinson-top-title">${title}</h4>
            <div class="brinson-top-empty">暂无数据</div>
        </div>`;
    }

    const rows = items.slice(0, 5).map((item, i) => {
        const effect = item.total_effect || item.contribution || 0;
        const color = effect >= 0 ? '#34d399' : '#f87171';
        const sign = effect >= 0 ? '+' : '';
        return `
        <div class="brinson-top-item">
            <span class="brinson-top-rank">${i + 1}</span>
            <span class="brinson-top-name">${item.name || item.sector || '--'}</span>
            <span class="brinson-top-code">${item.code || ''}</span>
            <span class="brinson-top-effect" style="color:${color}">
                ${sign}${effect.toFixed(3)}%
            </span>
        </div>`;
    }).join('');

    return `
    <div class="brinson-top-col ${cls}">
        <h4 class="brinson-top-title">${title}</h4>
        ${rows}
    </div>`;
}

// ═══════════════════════════════════════════════════
//  ECharts 堆叠柱状图
// ═══════════════════════════════════════════════════

function _renderBrinsonChart(sectors) {
    if (!sectors || sectors.length === 0) return;

    const chart = _getChart('brinson-sector-chart');
    if (!chart) return;

    // 按总效应绝对值排序, 取 top 15
    const sorted = [...sectors]
        .sort((a, b) => Math.abs(b.total_effect || 0) - Math.abs(a.total_effect || 0))
        .slice(0, 15);

    const categories = sorted.map(s => s.sector);
    const allocation = sorted.map(s => +(s.allocation_effect || 0).toFixed(4));
    const selection = sorted.map(s => +(s.selection_effect || 0).toFixed(4));
    const interaction = sorted.map(s => +(s.interaction_effect || 0).toFixed(4));

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            backgroundColor: 'rgba(15,23,42,0.92)',
            borderColor: 'rgba(255,255,255,0.08)',
            textStyle: { color: '#e2e8f0', fontSize: 12 },
            formatter: (params) => {
                let html = `<div style="font-weight:600;margin-bottom:4px;">${params[0].axisValue}</div>`;
                let total = 0;
                params.forEach(p => {
                    total += p.value;
                    html += `<div style="display:flex;justify-content:space-between;gap:12px;">
                        <span>${p.marker} ${p.seriesName}</span>
                        <span style="font-weight:600;color:${p.value >= 0 ? '#34d399' : '#f87171'}">
                            ${p.value >= 0 ? '+' : ''}${p.value.toFixed(3)}%
                        </span>
                    </div>`;
                });
                html += `<div style="border-top:1px solid rgba(255,255,255,0.1);margin-top:4px;padding-top:4px;display:flex;justify-content:space-between;">
                    <span>总效应</span>
                    <span style="font-weight:700;color:${total >= 0 ? '#34d399' : '#f87171'}">
                        ${total >= 0 ? '+' : ''}${total.toFixed(3)}%
                    </span>
                </div>`;
                return html;
            },
        },
        legend: {
            data: ['配置效应', '选股效应', '交互效应'],
            top: 4,
            textStyle: { color: '#94a3b8', fontSize: 11 },
            itemWidth: 12, itemHeight: 8,
        },
        grid: {
            left: 60, right: 20, top: 40, bottom: 60,
        },
        xAxis: {
            type: 'category',
            data: categories,
            axisLabel: {
                color: '#94a3b8', fontSize: 10,
                rotate: categories.length > 8 ? 35 : 0,
            },
            axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
            axisTick: { show: false },
        },
        yAxis: {
            type: 'value',
            name: '效应值 (%)',
            nameTextStyle: { color: '#64748b', fontSize: 10 },
            axisLabel: {
                color: '#94a3b8', fontSize: 10,
                formatter: v => v.toFixed(2),
            },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.08)' } },
            axisLine: { show: false },
        },
        series: [
            {
                name: '配置效应',
                type: 'bar',
                stack: 'effect',
                data: allocation,
                itemStyle: { color: 'rgba(59,130,246,0.85)', borderRadius: [0, 0, 0, 0] },
                barMaxWidth: 28,
            },
            {
                name: '选股效应',
                type: 'bar',
                stack: 'effect',
                data: selection,
                itemStyle: { color: 'rgba(16,185,129,0.85)' },
            },
            {
                name: '交互效应',
                type: 'bar',
                stack: 'effect',
                data: interaction,
                itemStyle: { color: 'rgba(245,158,11,0.85)', borderRadius: [2, 2, 0, 0] },
            },
        ],
    });
}

// ═══════════════════════════════════════════════════
//  ECharts 累计归因时序图
// ═══════════════════════════════════════════════════

function _renderBrinsonTimelineChart(timeline) {
    if (!timeline || timeline.length === 0) return;
    const chart = _getChart('brinson-timeline-chart');
    if (!chart) return;
    if (typeof AC !== 'undefined' && AC.registerChart) AC.registerChart(chart);

    const dates = timeline.map(t => {
        const dStr = String(t.date);
        if (dStr.length === 8) {
            return dStr.slice(4, 6) + '-' + dStr.slice(6, 8);
        }
        return t.date;
    });
    const allocation = timeline.map(t => t.allocation);
    const selection = timeline.map(t => t.selection);
    const excess = timeline.map(t => t.excess);

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.92)',
            borderColor: 'rgba(255,255,255,0.08)',
            textStyle: { color: '#e2e8f0', fontSize: 11 },
            formatter: function(params) {
                let html = `<div style="font-weight:600;margin-bottom:4px;">日期: ${params[0].axisValue}</div>`;
                params.forEach(p => {
                    const color = p.value >= 0 ? '#34d399' : '#f87171';
                    html += `<div style="display:flex;justify-content:space-between;gap:12px;">
                        <span>${p.marker} ${p.seriesName}</span>
                        <span style="font-weight:700;color:${color}">${p.value > 0 ? '+' : ''}${p.value.toFixed(3)}%</span>
                    </div>`;
                });
                return html;
            }
        },
        legend: {
            data: ['累计超额 (Excess)', '配置效应 (Alloc)', '选股效应 (Select)'],
            top: 4,
            textStyle: { color: '#94a3b8', fontSize: 10 }
        },
        grid: {
            left: 50, right: 15, top: 35, bottom: 25
        },
        xAxis: {
            type: 'category',
            data: dates,
            axisLabel: { color: '#94a3b8', fontSize: 9 },
            axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
            axisTick: { show: false }
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#94a3b8', fontSize: 9, formatter: '{value}%' },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.08)' } },
            axisLine: { show: false }
        },
        series: [
            {
                name: '累计超额 (Excess)',
                type: 'line',
                data: excess,
                symbol: 'circle',
                symbolSize: 6,
                showSymbol: false,
                lineStyle: { color: '#eab308', width: 2.5 },
                itemStyle: { color: '#eab308' }
            },
            {
                name: '配置效应 (Alloc)',
                type: 'line',
                data: allocation,
                symbol: 'circle',
                symbolSize: 5,
                showSymbol: false,
                lineStyle: { color: '#3b82f6', width: 1.8 },
                itemStyle: { color: '#3b82f6' }
            },
            {
                name: '选股效应 (Select)',
                type: 'line',
                data: selection,
                symbol: 'circle',
                symbolSize: 5,
                showSymbol: false,
                lineStyle: { color: '#10b981', width: 1.8 },
                itemStyle: { color: '#10b981' }
            }
        ]
    });
}

