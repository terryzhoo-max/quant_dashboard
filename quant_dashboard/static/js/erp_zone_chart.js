/* AlphaCore · ERP 估值区间图 (共享模块)
 * 时点一致 (PIT) 五档区间: 区间由后端 engines/erp_zones.py 计算, 与综合评分 D2 同口径。
 * 使用方: strategy.html (strategy_erp.js) / index.html (renderers.js) — 修改此文件即两处同步。
 * 依赖: echarts, AC (alphacore_utils.js)
 */
// V4.1: 时点一致 (PIT) 五档区间渲染 — 区间由后端 erp_zones 计算 (与 D2 同口径, 无后视)
const _ERP_PIT_META = {
    strong:  { label: '🟢 强买区', color: '#10b981' },
    over:    { label: '🔵 超配区', color: '#34d399' },
    neutral: { label: '⚪ 中性区',       color: '#f59e0b' },
    under:   { label: '🟠 低配区', color: '#fb923c' },
    danger:  { label: '🔴 危险区', color: '#ef4444' },
};
const _ERP_BAND_NAME = '估值区间带';

function _erpPitEpisodes(zones, key, mergeGap) {
    const eps = []; let cur = null, gap = 0;
    for (let i = 0; i < zones.length; i++) {
        if (zones[i] === key) {
            if (!cur) cur = { s: i, e: i, n: 0 };
            cur.e = i; cur.n += 1; gap = 0;
        } else if (cur) {
            gap += 1;
            if (gap > mergeGap) { eps.push(cur); cur = null; gap = 0; }
        }
    }
    if (cur) eps.push(cur);
    eps.forEach(ep => { ep.ongoing = ep.e === zones.length - 1; });
    return eps;
}

/**
 * 共享渲染入口 (策略页 strategy_erp.js 与首页 renderers.js 共用, 保证两处显示完全一致)
 * @param chart        /api/v1/strategy/erp-timing 返回的 data.chart (需含 bands/pit)
 * @param signalData   data (用于综合信号与快照)
 * @param prevInstance 之前的 ECharts 实例 (会被销毁)
 * @returns 新的 ECharts 实例
 */
function renderERPZoneChart(chart, signalData, prevInstance) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom || typeof echarts === 'undefined') return prevInstance || null;
    if (prevInstance) AC.disposeChart(prevInstance);
    const inst = AC.registerChart(echarts.init(dom));
    const stats = chart.stats || {}, pit = chart.pit || {}, b = chart.bands;
    const dates = chart.dates || [], erp = chart.erp || [];
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);
    const diff = (hi, lo) => hi.map((v, i) => (v == null || lo[i] == null) ? null : +(v - lo[i]).toFixed(2));
    const yrs = pit.window_years || 4;

    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) {
        const txt = ' ERP 估值走势 (近' + (stats.date_range_years || '?') + '年) · 近' + yrs + '年滚动分位五档 ';
        // 首页标题含 icon/pill 子元素: 只替换文本节点
        const textNodes = Array.from(titleEl.childNodes).filter(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
        if (titleEl.children.length && textNodes.length) { textNodes.forEach((n, k) => n.textContent = k ? '' : txt); }
        else titleEl.textContent = txt;
    }

    _renderERPChartKPIsPIT(stats, pit, signalData);
    _renderERPChartNotePIT(dom, pit);

    // ERP 曲线按区间分段着色 (强买绿 / 低配橙 / 危险红 / 其余琥珀)
    const pieces = [];
    [['strong', '#10b981'], ['under', '#fb923c'], ['danger', '#ef4444']].forEach(([k, c]) => {
        _erpPitEpisodes(b.zone, k, 0).forEach(ep => pieces.push({ gte: ep.s, lte: Math.min(ep.e + 1, dates.length - 1), color: c }));
    });

    // 纵向色带: 历史危险段 (红) 与强买段 (绿)
    const vBand = (key, rgba, rgbaNow, txt) => _erpPitEpisodes(b.zone, key, 3).map(ep => [
        { xAxis: dates[ep.s], itemStyle: { color: ep.ongoing ? rgbaNow : rgba },
          label: { show: ep.n >= 10 || ep.ongoing, position: 'insideTop', fontSize: 9, color: _ERP_PIT_META[key].color,
                   formatter: ep.ongoing ? '当前' + txt : dates[ep.s].substring(0, 7) } },
        { xAxis: dates[ep.e] }
    ]);
    const dangerAreas = vBand('danger', 'rgba(239,68,68,0.10)', 'rgba(239,68,68,0.22)', '危险');
    const strongAreas = vBand('strong', 'rgba(16,185,129,0.08)', 'rgba(16,185,129,0.20)', '强买');

    const zoneNow = _ERP_PIT_META[pit.current_zone] || { color: '#f59e0b', label: '--' };
    const markPointData = [];
    if (stats.current != null) markPointData.push({
        coord: [dates[dates.length - 1], stats.current], name: '当前', symbol: 'pin', symbolSize: 46,
        itemStyle: { color: zoneNow.color, borderColor: '#0f172a', borderWidth: 1 },
        label: { formatter: stats.current + '%', color: '#fff', fontSize: 10, fontWeight: 700 }
    });
    (stats.extremes || []).forEach(e => markPointData.push({
        coord: [e.date, e.value], name: e.type === 'max' ? '历史最高' : '历史最低',
        symbol: e.type === 'max' ? 'triangle' : 'arrow', symbolSize: 12, symbolRotate: e.type === 'min' ? 180 : 0,
        itemStyle: { color: e.type === 'max' ? '#10b981' : '#ef4444' },
        label: { show: true, formatter: e.value + '%', fontSize: 9, color: e.type === 'max' ? '#10b981' : '#ef4444', position: e.type === 'max' ? 'top' : 'bottom' }
    }));

    const endLbl = (txt, color) => ({ show: true, formatter: txt, color, fontSize: 9, distance: 4 });
    const line = (color, type, width, opacity) => ({ color, type: type || 'solid', width: width || 1, opacity: opacity == null ? 1 : opacity });
    const bandBase = { name: _ERP_BAND_NAME, type: 'line', yAxisIndex: 0, symbol: 'none', silent: true, z: 2,
                       emphasis: { disabled: true }, tooltip: { show: false } };
    const fmt = v => (v == null ? '--' : v + '%');

    const series = [
        { name: 'ERP', type: 'line', data: erp, yAxisIndex: 0, symbol: 'none', z: 10,
          lineStyle: { width: 2.5, shadowColor: 'rgba(0,0,0,0.35)', shadowBlur: 4 }, itemStyle: { color: '#f59e0b' },
          markPoint: { data: markPointData, animation: true, animationDuration: 600 } },
        // 危险带: 轴底 → 危险线
        Object.assign({}, bandBase, { data: b.danger, lineStyle: line('#ef4444', 'solid', 1.3),
          areaStyle: { origin: 'start', color: 'rgba(239,68,68,0.13)' },
          endLabel: endLbl('危险 ' + fmt(pit.danger_line) + (pit.floor_binding ? ' (绝对下限)' : ' (P20)'), '#ef4444') }),
        // 低配带: 危险线 → 低配线 (堆叠)
        Object.assign({}, bandBase, { data: b.danger, stack: 'erp_under', lineStyle: line('#000', 'solid', 0, 0) }),
        Object.assign({}, bandBase, { data: diff(b.under, b.danger), stack: 'erp_under', lineStyle: line('#fb923c', 'dashed', 1),
          areaStyle: { color: 'rgba(251,146,60,0.10)' }, endLabel: endLbl('低配 ' + fmt(pit.underweight_line) + ' (P40)', '#fb923c') }),
        // 超配带: 超配线 → 强买线 (堆叠)
        Object.assign({}, bandBase, { data: b.over, stack: 'erp_over', lineStyle: line('#34d399', 'dashed', 1, 0.7),
          endLabel: endLbl('超配 ' + fmt(pit.overweight_line) + ' (P60)', '#34d399') }),
        Object.assign({}, bandBase, { data: diff(b.strong, b.over), stack: 'erp_over', lineStyle: line('#000', 'solid', 0, 0),
          areaStyle: { color: 'rgba(52,211,153,0.06)' } }),
        // 强买带: 强买线 → 轴顶
        Object.assign({}, bandBase, { data: b.strong, lineStyle: line('#10b981', 'solid', 1.3),
          areaStyle: { origin: 'end', color: 'rgba(16,185,129,0.12)' },
          endLabel: endLbl('强买 ' + fmt(pit.strong_buy_line) + ' (P80)', '#10b981') }),
        // 长期中枢 (扩展窗口中位数): 危险/强买的第二重确认
        Object.assign({}, bandBase, { data: b.anchor || [], lineStyle: line('#cbd5e1', 'dotted', 1.2, 0.8),
          endLabel: endLbl('中枢 ' + fmt(pit.anchor), '#cbd5e1') }),
        { name: '危险区间', type: 'line', data: [], yAxisIndex: 0, symbol: 'none', itemStyle: { color: '#ef4444' },
          lineStyle: { opacity: 0 }, markArea: { silent: true, data: dangerAreas } },
        { name: '强买区间', type: 'line', data: [], yAxisIndex: 0, symbol: 'none', itemStyle: { color: '#10b981' },
          lineStyle: { opacity: 0 }, markArea: { silent: true, data: strongAreas } },
        { name: 'PE-TTM', type: 'line', data: chart.pe_ttm, yAxisIndex: 1, symbol: 'none',
          lineStyle: { color: '#3b82f6', width: 1.2, type: 'dashed', opacity: 0.8 }, itemStyle: { color: '#3b82f6' } },
        { name: '10Y国债', type: 'line', data: chart.yield_10y, yAxisIndex: 0, symbol: 'none',
          lineStyle: { color: '#94a3b8', width: 1, type: 'dotted' }, itemStyle: { color: '#94a3b8' } },
    ];
    if (hasM1) series.push({ name: 'M1同比', type: 'line', data: chart.m1_yoy, yAxisIndex: 2, symbol: 'none', smooth: true,
        lineStyle: { color: '#a78bfa', width: 1.6 }, itemStyle: { color: '#a78bfa' } });

    const legendData = ['ERP', _ERP_BAND_NAME, '危险区间', '强买区间', 'PE-TTM', '10Y国债'];
    if (hasM1) legendData.push('M1同比');

    inst.setOption({
        tooltip: {
            trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155',
            textStyle: { fontSize: 11, color: '#e2e8f0' },
            formatter: function(params) {
                const i = params[0].dataIndex;
                let r = '<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">' + params[0].axisValue + '</div>';
                params.forEach(p => {
                    if (p.value == null || p.seriesName === _ERP_BAND_NAME) return;
                    const unit = p.seriesName === 'PE-TTM' ? 'x' : '%';
                    r += '<div>' + p.marker + ' ' + p.seriesName + ': <b>' + p.value + unit + '</b></div>';
                });
                const z = _ERP_PIT_META[b.zone[i]];
                if (z) {
                    const v = erp[i], dl = b.danger[i];
                    r += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;">' +
                         '<span style="color:' + z.color + ';font-weight:700;">' + z.label + '</span>' +
                         ' <span style="color:#94a3b8;">· 近' + yrs + '年 P' + Math.round(b.pct[i]) + '</span></div>' +
                         '<div style="font-size:10px;color:#64748b;">危险线 ' + dl + '% · 缓冲 ' + (v - dl >= 0 ? '+' : '') + (v - dl).toFixed(2) + 'pp' +
                         (b.anchor && b.anchor[i] != null ? ' · 中枢 ' + b.anchor[i] + '%' : '') + '</div>' +
                         (b.zone[i] === 'under' && v < dl ? '<div style="font-size:10px;color:#fb923c;">跌破P20但高于长期中枢 → 降为低配</div>' : '') +
                         (b.zone[i] === 'over' && v >= b.strong[i] ? '<div style="font-size:10px;color:#34d399;">达P80但低于长期中枢 → 降为超配</div>' : '');
                } else {
                    r += '<div style="margin-top:3px;font-size:10px;color:#64748b;">历史不足1年, 不做区间判定</div>';
                }
                return r;
            }
        },
        legend: { data: legendData, top: 0, textStyle: { color: '#94a3b8', fontSize: 10 }, selected: { '10Y国债': false } },
        toolbox: { right: 8, top: 0, feature: {
            saveAsImage: { title: '保存', pixelRatio: 2, backgroundColor: '#0f172a' }, restore: { title: '重置' } },
            iconStyle: { borderColor: '#64748b' } },
        visualMap: { show: false, seriesIndex: 0, dimension: 0, pieces: pieces, outOfRange: { color: '#f59e0b' } },
        grid: { top: 40, bottom: 55, left: 50, right: hasM1 ? 150 : 110 },
        dataZoom: [
            { type: 'inside', start: 65, end: 100 },
            { type: 'slider', height: 16, bottom: 4, borderColor: 'rgba(255,255,255,0.06)',
              fillerColor: 'rgba(245,158,11,0.12)', handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
              textStyle: { color: '#64748b', fontSize: 9 },
              dataBackground: { lineStyle: { color: '#334155' }, areaStyle: { color: 'rgba(245,158,11,0.05)' } } }
        ],
        xAxis: { type: 'category', data: dates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 10, formatter: v => v.substring(0, 7) },
            axisLine: { lineStyle: { color: '#334155' } } },
        yAxis: [
            { type: 'value', name: 'ERP %', nameTextStyle: { color: '#64748b', fontSize: 10 },
              min: v => Math.max(0, Math.floor(v.min - 0.3)), max: v => Math.ceil(v.max + 0.3),
              axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
              splitLine: { lineStyle: { color: 'rgba(100,116,139,0.08)' } } },
            { type: 'value', name: 'PE-TTM', position: 'right', nameTextStyle: { color: '#3b82f6', fontSize: 10 },
              axisLabel: { color: '#3b82f680', fontSize: 9 }, splitLine: { show: false } },
            hasM1 ? { type: 'value', name: 'M1%', position: 'right', offset: 40, nameTextStyle: { color: '#a78bfa', fontSize: 10 },
              axisLabel: { color: '#a78bfa', fontSize: 9, formatter: '{value}%' }, splitLine: { show: false } } : null
        ].filter(Boolean),
        series: series
    });
    return inst;
}

function _renderERPChartNotePIT(dom, pit) {
    let note = document.getElementById('erp-chart-note');
    if (!note) {
        note = document.createElement('div');
        note.id = 'erp-chart-note';
        note.style.cssText = 'margin-top:6px;font-size:0.65rem;line-height:1.5;color:#64748b;';
        dom.parentNode.insertBefore(note, dom.nextSibling);
    }
    const share = pit.zone_share_pct || {};
    note.textContent = '区间口径: 每个时点仅用其前 ' + pit.window_years + ' 年 (' + pit.window_days +
        ' 个交易日) 的 ERP 滚动分位, 无后视, 与综合评分 D2 同口径: ≥P80 强买 / P60–80 超配 / P40–60 中性 / P20–40 低配 / <P20 危险。' +
        '危险/强买需双重确认: 同时低于/高于长期中枢 (自2015年扩展中位数, 当前 ' + pit.anchor + '%), 否则降一档; ' +
        'ERP<' + pit.abs_floor + '% 无条件危险 (长期泡沫的硬约束)。' +
        '样本内时间占比' + (pit.zone_share_since ? ' (' + pit.zone_share_since + ' 起, 仅统计已满' + pit.window_years + '年窗口的交易日)' : '') +
        ': 危险 ' + (share.danger ?? '--') + '% · 低配 ' + (share.under ?? '--') + '% · 强买 ' + (share.strong ?? '--') +
        '%。估值区间≠交易信号, 仓位以综合信号为准。';
}

function _renderERPChartKPIsPIT(stats, pit, signalData) {
    const container = document.getElementById('erp-chart-kpis');
    if (!container) return;
    const signal = (signalData || {}).signal || {};
    const z = _ERP_PIT_META[pit.current_zone] || { label: '--', color: '#94a3b8' };
    const buf = pit.buffer_to_danger_pp, bufU = pit.buffer_to_under_pp;
    const bufColor = buf == null ? '#94a3b8' : (buf < 0 ? '#ef4444' : (buf < 0.5 ? '#fb923c' : '#10b981'));
    const pct = pit.current_pct;
    const sigText = signal.label ? ('综合信号: ' + (signal.emoji || '') + signal.label +
        (signal.score != null ? ' ' + signal.score : '') + (signal.position ? ' · ' + signal.position : '')) : '';
    const card = (label, value, color, sub, flex) => `<div style="flex:${flex || 1};min-width:0;background:rgba(15,23,42,0.6);border:1px solid ${flex ? color + '55' : 'rgba(255,255,255,0.06)'};border-radius:8px;padding:8px 10px;text-align:center;">
        <div style="font-size:0.65rem;color:#64748b;margin-bottom:3px;">${label}</div>
        <div style="font-size:1.05rem;font-weight:800;color:${color};">${value}</div>
        ${sub ? `<div style="font-size:0.6rem;color:#94a3b8;margin-top:2px;">${sub}</div>` : ''}
    </div>`;
    container.innerHTML = [
        card('估值区间', z.label, z.color, ['近' + pit.window_years + '年 P' + (pct != null ? Math.round(pct) : '--') +
             (pit.current_zone_days ? ' · 已持续 ' + pit.current_zone_days + ' 个交易日' : ''), sigText].filter(Boolean).join('<br>'), 1.8),
        card('当前 ERP', (stats.current != null ? stats.current : '--') + '%', z.color),
        card('距危险线', buf == null ? '--' : ((buf >= 0 ? '+' : '') + buf + 'pp'), bufColor,
             '危险线 ' + (pit.danger_line ?? '--') + '%' + (pit.floor_binding ? ' (绝对下限)' : '')),
        card('距低配线', bufU == null ? '--' : ((bufU >= 0 ? '+' : '') + bufU + 'pp'), bufU != null && bufU < 0 ? '#fb923c' : '#94a3b8',
             '低配线 ' + (pit.underweight_line ?? '--') + '%'),
        card('危险区时间占比', ((pit.zone_share_pct || {}).danger ?? '--') + '%', '#ef4444',
             (pit.danger_episodes || []).length + ' 段'),
    ].join('');
}

