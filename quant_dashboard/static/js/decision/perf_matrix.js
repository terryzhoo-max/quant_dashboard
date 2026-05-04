/**
 * AlphaCore V21.2 · 绩效矩阵模块
 * ================================
 * - 绩效分析渲染 (loadPerformanceAnalytics)
 * - 多基准切换 (switchBenchmark / initBenchTabs)
 * - 月度收益热力图 (renderPerfHeatmap)
 * - 回撤图 (renderPerfDrawdown)
 * - 滚动Sharpe (renderPerfSharpe)
 *
 * 依赖: _getChart, _fmt, API_BASE (from _infra.js)
 */
// ═══════════════════════════════════════════════════
//  V18.1: 绩效分析渲染 (多基准: 沪深300 / 科创50 / 创业板50)
// ═══════════════════════════════════════════════════

let perfLoaded = false;
let perfBenchmarks = null;  // 缓存多基准数据
let currentBench = 'hs300'; // 当前选中基准

async function loadPerformanceAnalytics() {
    if (perfLoaded) return;
    try {
        const resp = await AC.secureFetch(`${API_BASE}/performance`);
        const data = await resp.json();
        if (data.status === 'success' && data.metrics) {
            // 缓存多基准数据
            perfBenchmarks = data.benchmarks || null;
            console.log('[PerfAnalytics] benchmarks loaded:', perfBenchmarks ? Object.keys(perfBenchmarks) : 'null');
            const sec = document.getElementById('perf-section');
            if (sec) sec.style.display = 'block';
            // 默认渲染沪深300 (向后兼容)
            renderPerfMetrics(data.metrics, data.drawdown);
            renderPerfHeatmap(data.monthly_heatmap);
            renderPerfDrawdown(data.drawdown);
            renderPerfSharpe(data.rolling_sharpe);
            // 绑定基准切换器
            initBenchTabs();
            perfLoaded = true;
        }
    } catch (e) { console.error('Performance analytics load error:', e); }
}

function switchBenchmark(key) {
    if (!perfBenchmarks || !perfBenchmarks[key]) return;
    currentBench = key;
    const bm = perfBenchmarks[key];
    // 更新指标条
    renderPerfMetrics(bm.metrics, bm.drawdown);
    // 更新图表 (需要先 dispose 再重建, 否则 ECharts 复用旧实例)
    // V20.0: 通过 _getChart 自动 dispose, 无需手动清理
    renderPerfHeatmap(bm.monthly_heatmap);
    renderPerfDrawdown(bm.drawdown);
    renderPerfSharpe(bm.rolling_sharpe);
    // 更新图表区标题
    const label = document.getElementById('perf-bench-label');
    if (label) label.textContent = bm.name;
    // 同步所有 bench-tabs 的 active 状态
    document.querySelectorAll('.bench-tabs').forEach(tabGroup => {
        tabGroup.querySelectorAll('.bench-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.bench === key);
        });
    });
}

function initBenchTabs() {
    document.querySelectorAll('.bench-tabs').forEach(tabGroup => {
        tabGroup.querySelectorAll('.bench-tab').forEach(tab => {
            tab.addEventListener('click', () => switchBenchmark(tab.dataset.bench));
        });
    });
}

function renderPerfMetrics(m, dd) {
    const bar = document.getElementById('perf-metrics-bar');
    if (!bar) return;
    const maxDD = dd && dd.max_drawdown ? dd.max_drawdown : 0;
    const items = [
        { label: '年化收益', value: m.annual_return + '%', cls: m.annual_return >= 0 ? 'positive' : 'negative' },
        { label: '年化波动率', value: m.annual_volatility + '%', cls: '' },
        { label: 'Sharpe', value: m.sharpe_ratio, cls: m.sharpe_ratio >= 1 ? 'positive' : (m.sharpe_ratio < 0 ? 'negative' : '') },
        { label: 'Sortino', value: m.sortino_ratio, cls: m.sortino_ratio >= 1 ? 'positive' : '' },
        { label: 'Calmar', value: m.calmar_ratio, cls: '' },
        { label: '最大回撤', value: maxDD + '%', cls: 'negative' },
    ];
    bar.innerHTML = items.map(it => `
        <div class="perf-metric-item">
            <div class="perf-metric-value ${it.cls}">${it.value}</div>
            <div class="perf-metric-label">${it.label}</div>
        </div>
    `).join('');
}

function renderPerfHeatmap(heatmapData) {
    const el = document.getElementById('perf-heatmap-chart');
    if (!el || !heatmapData || heatmapData.length === 0) return;
    const chart = _getChart('perf-heatmap-chart');
    if (!chart) return;

    // 提取年份和月份
    const years = [...new Set(heatmapData.map(d => d[0]))].sort();
    const months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];

    const data = heatmapData.map(d => [d[1] - 1, years.indexOf(d[0]), d[2]]);
    const maxAbs = Math.max(...heatmapData.map(d => Math.abs(d[2])), 5);

    chart.setOption({
        tooltip: {
            formatter: p => {
                const yr = years[p.value[1]];
                const mn = months[p.value[0]];
                return `${yr}年${mn}<br/>收益: <b>${p.value[2] > 0 ? '+' : ''}${p.value[2]}%</b>`;
            }
        },
        grid: { left: 48, right: 12, top: 12, bottom: 46 },
        xAxis: {
            type: 'category', data: months,
            axisLabel: { color: '#64748b', fontSize: 10 },
            axisTick: { show: false }, axisLine: { show: false },
            splitArea: { show: true, areaStyle: { color: ['rgba(15,23,42,0.2)', 'rgba(15,23,42,0.4)'] } }
        },
        yAxis: {
            type: 'category', data: years.map(String),
            axisLabel: { color: '#64748b', fontSize: 10 },
            axisTick: { show: false }, axisLine: { show: false }
        },
        visualMap: {
            min: -maxAbs, max: maxAbs, calculable: false,
            orient: 'horizontal', left: 'center', bottom: 2,
            inRange: { color: ['#f87171', '#fca5a5', '#1e293b', '#6ee7b7', '#34d399'] },
            textStyle: { color: '#64748b', fontSize: 9 },
            itemWidth: 12, itemHeight: 80,
        },
        series: [{
            type: 'heatmap', data: data,
            label: {
                show: true,
                formatter: p => (p.value[2] > 0 ? '+' : '') + p.value[2] + '%',
                fontSize: 9, color: '#cbd5e1'
            },
            itemStyle: { borderColor: '#0f172a', borderWidth: 2, borderRadius: 3 },
            emphasis: { itemStyle: { borderColor: '#a78bfa', borderWidth: 2 } }
        }]
    });
    // V20.0: resize 由全局 _chartInstances handler 统一管理
}

function renderPerfDrawdown(dd) {
    const el = document.getElementById('perf-drawdown-chart');
    if (!el || !dd || !dd.series || dd.series.length === 0) return;
    const chart = _getChart('perf-drawdown-chart');
    if (!chart) return;

    chart.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: p => `${p[0].axisValue}<br/>回撤: <b style="color:#f87171">${p[0].value}%</b>`
        },
        grid: { left: 52, right: 16, top: 16, bottom: 38 },
        xAxis: {
            type: 'category',
            data: dd.series.map(d => d.date),
            axisLabel: { color: '#475569', fontSize: 9, rotate: 0,
                formatter: v => v.substring(5) },
            axisTick: { show: false }, axisLine: { lineStyle: { color: '#1e293b' } },
            boundaryGap: false
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#475569', fontSize: 9, formatter: '{value}%' },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } },
            max: 0
        },
        series: [{
            type: 'line', data: dd.series.map(d => d.drawdown),
            areaStyle: {
                color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: 'rgba(248,113,113,0.01)' },
                        { offset: 1, color: 'rgba(248,113,113,0.25)' }
                    ]
                }
            },
            lineStyle: { color: '#f87171', width: 1.5 },
            itemStyle: { color: '#f87171' },
            symbol: 'none', smooth: true,
            markLine: {
                silent: true, symbol: 'none',
                data: [{
                    yAxis: dd.max_drawdown,
                    lineStyle: { color: '#ef4444', type: 'dashed', width: 1 },
                    label: { formatter: `最大回撤 ${dd.max_drawdown}%`, color: '#fca5a5', fontSize: 9, position: 'insideEndTop' }
                }]
            }
        }]
    });
    // V20.0: resize 由全局 _chartInstances handler 统一管理
}

function renderPerfSharpe(sharpeData) {
    const el = document.getElementById('perf-sharpe-chart');
    if (!el || !sharpeData || sharpeData.length === 0) return;
    const chart = _getChart('perf-sharpe-chart');
    if (!chart) return;

    chart.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: p => `${p[0].axisValue}<br/>Sharpe: <b>${p[0].value}</b>`
        },
        grid: { left: 46, right: 16, top: 16, bottom: 38 },
        xAxis: {
            type: 'category',
            data: sharpeData.map(d => d.date),
            axisLabel: { color: '#475569', fontSize: 9, formatter: v => v.substring(5) },
            axisTick: { show: false }, axisLine: { lineStyle: { color: '#1e293b' } },
            boundaryGap: false
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#475569', fontSize: 9 },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } }
        },
        series: [{
            type: 'line', data: sharpeData.map(d => d.sharpe),
            lineStyle: { width: 1.5 },
            areaStyle: {
                color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: 'rgba(167,139,250,0.2)' },
                        { offset: 1, color: 'rgba(167,139,250,0.01)' }
                    ]
                }
            },
            itemStyle: {
                color: p => p.value >= 1 ? '#34d399' : (p.value < 0 ? '#f87171' : '#a78bfa')
            },
            symbol: 'none', smooth: true,
            markLine: {
                silent: true, symbol: 'none',
                data: [
                    { yAxis: 1, lineStyle: { color: '#34d399', type: 'dashed', width: 1 },
                      label: { formatter: 'Sharpe=1 优秀', color: '#6ee7b7', fontSize: 9, position: 'insideEndTop' } },
                    { yAxis: 0, lineStyle: { color: '#475569', type: 'solid', width: 1 },
                      label: { show: false } }
                ]
            }
        }]
    });
    // V20.0: resize 由全局 _chartInstances handler 统一管理
}
