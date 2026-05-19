/**
 * AlphaCore · 盘中实时P&L模块 (V27.0 P1-A)
 * ============================================
 * 自动加载今日P&L数据，渲染KPI卡片 + 瀑布图 + 行业归因。
 * 依赖: ECharts, portfolio.css 中的 slip-* 样式
 */
(function () {
    'use strict';

    const API = '/api/v1/portfolio/intraday-pnl';

    // ── 颜色常量 ──
    const CLR_UP   = '#34d399';
    const CLR_DOWN = '#f87171';
    const CLR_FLAT = '#64748b';
    const CLR_BG   = 'rgba(15, 17, 28, 0.85)';

    // ── 工具函数 ──
    function fmtMoney(v) {
        if (v === null || v === undefined) return '--';
        const abs = Math.abs(v);
        const sign = v >= 0 ? '+' : '-';
        if (abs >= 10000) return sign + '¥' + (abs / 10000).toFixed(2) + '万';
        return sign + '¥' + abs.toFixed(2);
    }

    function fmtPct(v) {
        if (v === null || v === undefined) return '--';
        return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
    }

    function pnlColor(v) {
        if (v > 0.01) return CLR_UP;
        if (v < -0.01) return CLR_DOWN;
        return CLR_FLAT;
    }

    // ── 主渲染 ──
    async function loadPnL() {
        try {
            const resp = await fetch(API);
            const json = await resp.json();
            if (json.code !== 0 || !json.data) return;
            const d = json.data;
            if (d.status === 'empty') {
                document.getElementById('pnl-total').textContent = '无持仓';
                return;
            }

            renderKPIs(d);
            renderWaterfallChart(d.positions);
            renderSectorChart(d.by_sector);

        } catch (err) {
            console.warn('[P&L] Load error:', err);
        }
    }

    function renderKPIs(d) {
        // Total P&L
        const totalEl = document.getElementById('pnl-total');
        totalEl.textContent = fmtMoney(d.total_daily_pnl);
        totalEl.style.color = pnlColor(d.total_daily_pnl);

        const totalPctEl = document.getElementById('pnl-total-pct');
        totalPctEl.textContent = fmtPct(d.total_daily_pnl_pct);
        totalPctEl.style.color = pnlColor(d.total_daily_pnl_pct);

        // Top Gainer
        const positions = d.positions || [];
        if (positions.length > 0) {
            const sorted = [...positions].sort((a, b) => b.daily_pnl - a.daily_pnl);
            const gainer = sorted[0];
            const loser = sorted[sorted.length - 1];

            if (gainer.daily_pnl > 0) {
                document.getElementById('pnl-top-gainer').textContent = fmtMoney(gainer.daily_pnl);
                document.getElementById('pnl-top-gainer-sub').textContent =
                    `${gainer.name} ${fmtPct(gainer.daily_pnl_pct)}`;
            }
            if (loser.daily_pnl < 0) {
                document.getElementById('pnl-top-loser').textContent = fmtMoney(loser.daily_pnl);
                document.getElementById('pnl-top-loser-sub').textContent =
                    `${loser.name} ${fmtPct(loser.daily_pnl_pct)}`;
            }

            // Up/Down count
            const upCount = positions.filter(p => p.daily_pnl > 0.01).length;
            const downCount = positions.filter(p => p.daily_pnl < -0.01).length;
            const flatCount = positions.length - upCount - downCount;
            document.getElementById('pnl-pos-count').textContent = positions.length;
            document.getElementById('pnl-up-down').innerHTML =
                `<span style="color:${CLR_UP}">▲${upCount}</span> · ` +
                `<span style="color:${CLR_FLAT}">—${flatCount}</span> · ` +
                `<span style="color:${CLR_DOWN}">▼${downCount}</span>`;
        }

        // Updated at
        document.getElementById('pnl-updated-at').textContent = d.updated_at || '--';
    }

    // ── 标的P&L瀑布图 ──
    function renderWaterfallChart(positions) {
        const container = document.getElementById('pnl-waterfall-chart');
        if (!container || !window.echarts) return;

        const chart = echarts.init(container, null, { renderer: 'canvas' });
        const sorted = [...positions].sort((a, b) => a.daily_pnl - b.daily_pnl);

        const names = sorted.map(p => p.name.length > 4 ? p.name.slice(0, 4) + '..' : p.name);
        const values = sorted.map(p => p.daily_pnl);
        const colors = values.map(v => pnlColor(v));

        chart.setOption({
            tooltip: {
                trigger: 'axis',
                backgroundColor: CLR_BG,
                borderColor: 'rgba(99,102,241,0.2)',
                textStyle: { color: '#e2e8f0', fontSize: 12 },
                formatter: function(params) {
                    const p = sorted[params[0].dataIndex];
                    return `<b>${p.name}</b> (${p.ts_code})<br/>` +
                           `日内P&L: <b style="color:${pnlColor(p.daily_pnl)}">${fmtMoney(p.daily_pnl)}</b><br/>` +
                           `涨跌幅: ${fmtPct(p.daily_pnl_pct)}<br/>` +
                           `现价: ¥${p.current_price} ← 昨收: ¥${p.prev_close}`;
                }
            },
            grid: { left: 60, right: 20, top: 10, bottom: 40 },
            xAxis: {
                type: 'category',
                data: names,
                axisLabel: { color: 'rgba(255,255,255,0.5)', fontSize: 10, rotate: 30 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
            },
            yAxis: {
                type: 'value',
                axisLabel: {
                    color: 'rgba(255,255,255,0.4)',
                    fontSize: 10,
                    formatter: v => v >= 10000 || v <= -10000 ? (v / 10000).toFixed(1) + '万' : v.toFixed(0)
                },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
            },
            series: [{
                type: 'bar',
                data: values.map((v, i) => ({
                    value: v,
                    itemStyle: {
                        color: colors[i],
                        borderRadius: v >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3]
                    }
                })),
                barMaxWidth: 28,
                label: {
                    show: values.length <= 12,
                    position: 'top',
                    color: 'rgba(255,255,255,0.5)',
                    fontSize: 9,
                    formatter: p => {
                        const v = p.value;
                        if (Math.abs(v) >= 1000) return (v / 10000 * 10).toFixed(1) + 'k';
                        return v.toFixed(0);
                    }
                }
            }]
        });

        window.addEventListener('resize', () => chart.resize());
    }

    // ── 行业P&L归因图 ──
    function renderSectorChart(sectors) {
        const container = document.getElementById('pnl-sector-chart');
        if (!container || !window.echarts || !sectors || !sectors.length) return;

        const chart = echarts.init(container, null, { renderer: 'canvas' });
        const names = sectors.map(s => s.sector);
        const values = sectors.map(s => s.daily_pnl);
        const colors = values.map(v => pnlColor(v));

        chart.setOption({
            tooltip: {
                trigger: 'axis',
                backgroundColor: CLR_BG,
                borderColor: 'rgba(99,102,241,0.2)',
                textStyle: { color: '#e2e8f0', fontSize: 12 },
                formatter: params => `${params[0].name}: <b style="color:${pnlColor(params[0].value)}">${fmtMoney(params[0].value)}</b>`
            },
            grid: { left: 80, right: 20, top: 10, bottom: 20 },
            xAxis: {
                type: 'value',
                axisLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
            },
            yAxis: {
                type: 'category',
                data: names,
                axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 11 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
            },
            series: [{
                type: 'bar',
                data: values.map((v, i) => ({
                    value: v,
                    itemStyle: {
                        color: colors[i],
                        borderRadius: v >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3]
                    }
                })),
                barMaxWidth: 20,
            }]
        });

        window.addEventListener('resize', () => chart.resize());
    }

    // ── 绑定刷新按钮 ──
    function init() {
        loadPnL();
        const btn = document.getElementById('pnl-refresh-btn');
        if (btn) btn.addEventListener('click', loadPnL);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
