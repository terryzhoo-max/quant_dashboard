/**
 * AlphaCore V27 · 多资产配置雷达模块 (Multi-Asset Radar)
 * ========================================================
 * 机构级生产视觉:
 *   - 信号强度仪表盘 (ECharts gauge 半圆)
 *   - 四象限资产卡片 (方向色标 + 配比条 + 信号徽章)
 *   - ECharts 雷达图 (双层: 信号强度 + 配置比例)
 *   - 黄金三维信号拆解 (实际利率/美元/通胀)
 *   - 配比环形图 (ECharts pie)
 *
 * 依赖: API_BASE, _getChart, _fmt, _safeFetch (from _infra.js)
 */

// ═══════════════════════════════════════════════════
//  工具函数
// ═══════════════════════════════════════════════════

/** HTML 转义 (防 XSS) */
function _maEscape(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

/** 信号值 → 文字标签 */
function _maSignalLabel(signal) {
    const abs = Math.abs(signal);
    if (abs >= 60) return '强';
    if (abs >= 30) return '中';
    return '弱';
}

// ═══════════════════════════════════════════════════
//  数据层
// ═══════════════════════════════════════════════════

let _multiAssetCache = null;

async function loadMultiAssetRadar() {
    const container = document.getElementById('multi-asset-body');
    if (!container) return;

    // 骨架屏加载态
    container.innerHTML = `
        <div class="ma-loading-state">
            <div class="ma-loading-ring"></div>
            <div class="ma-loading-text">多资产信号聚合中...</div>
        </div>`;

    try {
        const data = await _safeFetch(`${API_BASE}/multi-asset`);

        if (data.status === 'success' && data.assets) {
            _multiAssetCache = data;
            renderMultiAssetRadar(data);
            _updateMultiAssetSummary(data);
        } else {
            container.innerHTML = `<div class="ma-error">⚠️ ${_maEscape(data.error || '数据加载失败')}</div>`;
        }
    } catch (e) {
        console.warn('Multi-Asset Radar load error:', e);
        const errMsg = _maEscape(e.message || '');
        container.innerHTML = `<div class="ma-error">
            <span class="ma-error-icon">⚠️</span>
            <span>多资产信号暂时不可用</span>
            <span class="ma-error-detail">${errMsg}</span>
            <button class="ma-retry-btn" onclick="loadMultiAssetRadar()">↻ 重试</button>
        </div>`;
    }
}

// ═══════════════════════════════════════════════════
//  折叠态摘要行
// ═══════════════════════════════════════════════════

function _updateMultiAssetSummary(data) {
    const el = document.getElementById('multi-asset-summary');
    if (!el || !data.assets) return;

    const order = ['equity_cn', 'bond', 'gold', 'cash'];
    const parts = order
        .map(key => data.assets[key])
        .filter(Boolean)
        .map(a => `${a.icon} ${a.label} ${a.allocation || 0}%`)
        .slice(0, 4);
    el.textContent = parts.join(' · ') || '加载中...';
}

// ═══════════════════════════════════════════════════
//  主渲染 — 机构级视觉
// ═══════════════════════════════════════════════════

const _MA_DIR_COLORS = {
    bullish: { main: '#34d399', bg: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.2)' },
    bearish: { main: '#f87171', bg: 'rgba(248,113,113,0.08)', border: 'rgba(248,113,113,0.2)' },
    neutral: { main: '#94a3b8', bg: 'rgba(148,163,184,0.06)', border: 'rgba(148,163,184,0.12)' },
};
const _MA_DIR_ICONS = { bullish: '▲', bearish: '▼', neutral: '━' };
const _MA_ASSET_COLORS = {
    equity_cn: '#3b82f6',
    bond:      '#a78bfa',
    gold:      '#fbbf24',
    cash:      '#6ee7b7',
};

function renderMultiAssetRadar(data) {
    const container = document.getElementById('multi-asset-body');
    if (!container || !data.assets) return;

    const assets = data.assets;
    const order = ['equity_cn', 'bond', 'gold', 'cash'];

    // ── 四资产卡片 ──
    let cardsHtml = '';
    order.forEach((key, idx) => {
        const a = assets[key];
        if (!a) return;

        const dir = a.direction || 'neutral';
        const dc = _MA_DIR_COLORS[dir] || _MA_DIR_COLORS.neutral;
        const dirIcon = _MA_DIR_ICONS[dir] || '━';
        const dirCn = a.direction_cn || '—';
        const alloc = a.allocation != null ? a.allocation : 0;
        const allocLabel = a.allocation_label || `${alloc}%`;
        const signal = a.signal || 0;
        const sigLabel = _maSignalLabel(signal);
        const hasError = !!a.error;
        const accentColor = _MA_ASSET_COLORS[key] || '#94a3b8';

        let cardDesc = '';
        if (key === 'cash') {
            cardDesc = `<div class="ma-card-desc">🛡️ 战术流动性缓冲，保障保证金安全与潜在建仓额度</div>`;
        } else if (key === 'equity_cn') {
            cardDesc = `<div class="ma-card-desc">📊 A股权益核心仓位，根据 JCS 联合评分动态配置</div>`;
        } else if (key === 'bond') {
            cardDesc = `<div class="ma-card-desc">📋 债券策略配额，平滑组合净值并对冲权益资产波动</div>`;
        } else if (key === 'gold') {
            cardDesc = `<div class="ma-card-desc">🥇 黄金多因子择时，对冲宏观不确定性及通胀风险</div>`;
        }

        cardsHtml += `
        <div class="ma-card ${hasError ? 'ma-card-err' : ''}" data-asset="${key}"
             style="--ma-accent:${accentColor};--ma-dir:${dc.main};animation-delay:${idx * 0.08}s">
            <div class="ma-card-accent"></div>
            <div class="ma-card-top">
                <span class="ma-card-icon">${a.icon || '●'}</span>
                <div class="ma-card-meta">
                    <span class="ma-card-name">${a.label}</span>
                    <span class="ma-card-sublabel">${allocLabel}</span>
                </div>
                <div class="ma-card-signal-badge" style="color:${dc.main};border-color:${dc.border};background:${dc.bg}">
                    ${dirIcon} ${dirCn} · ${sigLabel}
                </div>
            </div>
            <div class="ma-card-bar-wrap">
                <div class="ma-card-bar-track">
                    <div class="ma-card-bar-fill" style="width:${Math.min(alloc, 100)}%;background:linear-gradient(90deg,${accentColor},${dc.main})"></div>
                </div>
                <span class="ma-card-pct">${alloc}%</span>
            </div>
            ${cardDesc}
            ${hasError ? `<div class="ma-card-err-msg">${_maEscape(a.error)}</div>` : ''}
        </div>`;
    });

    // ── 黄金三维信号 ──
    let goldHtml = '';
    const gold = assets.gold;
    if (gold && gold.components && !gold.error) {
        const comps = gold.components;
        const compItems = [
            { key: 'real_rate', label: '实际利率', icon: '📉', desc: '利率下行 → 利好黄金' },
            { key: 'dollar',    label: '美元强弱', icon: '💲', desc: '美元走弱 → 利好黄金' },
            { key: 'inflation', label: '通胀预期', icon: '🔥', desc: '通胀上行 → 利好黄金' },
        ];

        let compRows = '';
        compItems.forEach(ci => {
            const comp = comps[ci.key];
            if (!comp) return;
            const val = comp.contribution != null ? comp.contribution : (comp.score || 0);
            const dir = comp.direction || 'neutral';
            const dc = _MA_DIR_COLORS[dir] || _MA_DIR_COLORS.neutral;

            const absVal = Math.abs(val);
            const barWidth = Math.min(50, absVal / 2);
            const isPos = val >= 0;
            const barStyle = isPos 
                ? `left:50%;width:${barWidth}%;background:#10b981;`
                : `right:50%;width:${barWidth}%;background:#ef4444;`;

            compRows += `
            <div class="ma-gold-row">
                <span class="ma-gold-icon">${ci.icon}</span>
                <div class="ma-gold-info" style="flex:0 0 110px;">
                    <span class="ma-gold-label">${comp.label || ci.label}</span>
                    <span class="ma-gold-desc">${ci.desc}</span>
                </div>
                <!-- 横向双向条形图 -->
                <div class="ma-gold-diverging-wrap">
                    <div class="ma-gold-diverging-center"></div>
                    <div class="ma-gold-diverging-bar" style="${barStyle}"></div>
                </div>
                <span class="ma-gold-val" style="color:${dc.main}; min-width:44px; text-align:right;">${val > 0 ? '+' : ''}${_fmt(val, 1)}</span>
                <span class="ma-gold-tag" style="color:${dc.main};border-color:${dc.border};background:${dc.bg}; min-width:38px; text-align:center;">
                    ${comp.direction_cn || dir}
                </span>
            </div>`;
        });

        if (compRows) {
            goldHtml = `
            <div class="ma-gold-panel">
                <div class="ma-gold-header">
                    <span>🥇 黄金信号拆解</span>
                    <span class="ma-gold-total" style="color:${(_MA_DIR_COLORS[gold.direction] || _MA_DIR_COLORS.neutral).main}">
                        综合 ${gold.signal > 0 ? '+' : ''}${_fmt(gold.signal, 0)}
                    </span>
                </div>
                ${compRows}
            </div>`;
        }
    }

    // ── 时间戳 + 刷新 ──
    const ts = data.timestamp ? data.timestamp.replace('T', ' ').slice(0, 16) : '--';

    container.innerHTML = `
    <div class="ma-layout">
        <div class="ma-left">
            <div class="ma-section-label">信号强度 · 配置比例</div>
            <div id="ma-radar-chart" class="ma-radar-box"></div>
            <div class="ma-ts-row">
                <span>📡 ${ts}</span>
                <button class="ma-refresh-btn" onclick="loadMultiAssetRadar()">↻ 刷新</button>
            </div>
            <div class="ma-section-label" style="margin-top:20px;">配置结构偏离 (SAA 战略基准 vs TAA 当前战术)</div>
            <div id="ma-alloc-pie" class="ma-pie-box"></div>
        </div>
        <div class="ma-right">
            <div class="ma-section-label">资产配置建议</div>
            <div class="ma-cards-wrap">${cardsHtml}</div>
            ${goldHtml}
        </div>
    </div>`;

    // ── 渲染图表 ──
    requestAnimationFrame(() => {
        _drawMARadar(assets, order);
        _drawMASaaTaaBar(assets, order);
    });
}

// ═══════════════════════════════════════════════════
//  ECharts 雷达图
// ═══════════════════════════════════════════════════

function _drawMARadar(assets, order) {
    const chart = _getChart('ma-radar-chart');
    if (!chart) return;
    if (typeof AC !== 'undefined' && AC.registerChart) AC.registerChart(chart);

    const labels = order.map(k => assets[k]?.label || k);
    const signals = order.map(k => {
        const a = assets[k];
        if (!a) return 0;
        return Math.max(0, Math.min(100, (a.signal || 0) / 2 + 50));
    });
    const allocations = order.map(k => assets[k]?.allocation || 0);

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'item',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(255,255,255,0.08)',
            borderRadius: 10,
            padding: [12, 16],
            textStyle: { color: '#e2e8f0', fontSize: 12 },
            formatter: function(params) {
                if (!params.data || !params.data.value) return '';
                return order.map((k, i) => {
                    const a = assets[k];
                    if (!a) return '';
                    const sig = a.signal || 0;
                    const alloc = a.allocation || 0;
                    const color = _MA_ASSET_COLORS[k] || '#94a3b8';
                    return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px;"></span>${a.icon} ${a.label}: 信号 ${sig > 0 ? '+' : ''}${_fmt(sig, 1)} · 配比 ${alloc}%`;
                }).join('<br>');
            },
        },
        radar: {
            shape: 'polygon',
            indicator: labels.map((l, i) => ({
                name: `{icon|${order.map(k => assets[k]?.icon || '')[i]}} ${l}`,
                max: 100,
            })),
            center: ['50%', '46%'],
            radius: '62%',
            axisName: {
                color: '#cbd5e1',
                fontSize: 12,
                fontWeight: 600,
                rich: { icon: { fontSize: 14 } },
            },
            splitArea: {
                areaStyle: {
                    color: [
                        'rgba(59,130,246,0.01)', 'rgba(59,130,246,0.03)',
                        'rgba(59,130,246,0.05)', 'rgba(59,130,246,0.07)',
                        'rgba(59,130,246,0.09)',
                    ],
                },
            },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.12)', type: 'dashed' } },
            axisLine:  { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
        },
        series: [{
            name: '多资产雷达',
            type: 'radar',
            data: [
                {
                    value: signals,
                    name: '信号强度',
                    areaStyle: {
                        color: {
                            type: 'radial', x: 0.5, y: 0.5, r: 0.7,
                            colorStops: [
                                { offset: 0, color: 'rgba(59,130,246,0.3)' },
                                { offset: 1, color: 'rgba(59,130,246,0.05)' },
                            ],
                        },
                    },
                    lineStyle: { color: '#3b82f6', width: 2.5, shadowBlur: 8, shadowColor: 'rgba(59,130,246,0.4)' },
                    itemStyle: { color: '#3b82f6', borderWidth: 2, borderColor: '#1d4ed8' },
                    symbol: 'circle',
                    symbolSize: 7,
                },
                {
                    value: allocations,
                    name: '配置比例',
                    areaStyle: { color: 'rgba(52,211,153,0.1)' },
                    lineStyle: { color: '#34d399', width: 2, type: 'dashed' },
                    itemStyle: { color: '#34d399', borderWidth: 2, borderColor: '#059669' },
                    symbol: 'diamond',
                    symbolSize: 7,
                },
            ],
        }],
        legend: {
            data: ['信号强度', '配置比例'],
            bottom: 2,
            textStyle: { color: '#94a3b8', fontSize: 11 },
            itemWidth: 14, itemHeight: 10,
            itemGap: 20,
        },
    });
}

// ═══════════════════════════════════════════════════
//  配置比例环形图
// ═══════════════════════════════════════════════════

function _drawMASaaTaaBar(assets, order) {
    const chart = _getChart('ma-alloc-pie');
    if (!chart) return;
    if (typeof AC !== 'undefined' && AC.registerChart) AC.registerChart(chart);

    const saaWeights = {
        equity_cn: 50,
        bond: 30,
        gold: 10,
        cash: 10
    };

    const categories = order.map(k => assets[k]?.label || k);
    const saaData = order.map(k => saaWeights[k] || 0);
    const taaData = order.map(k => assets[k]?.allocation || 0);

    chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(255,255,255,0.08)',
            textStyle: { color: '#e2e8f0', fontSize: 11 },
            formatter: function(params) {
                let html = `<div style="font-weight:600;margin-bottom:4px;">${params[0].name}</div>`;
                params.forEach(p => {
                    html += `<div>${p.marker} ${p.seriesName}: <span style="font-weight:700">${p.value}%</span></div>`;
                });
                return html;
            }
        },
        legend: {
            data: ['战略基准 (SAA)', '当前战术 (TAA)'],
            top: 4,
            textStyle: { color: '#94a3b8', fontSize: 10 }
        },
        grid: {
            left: 35, right: 10, top: 35, bottom: 25
        },
        xAxis: {
            type: 'category',
            data: categories,
            axisLabel: { color: '#94a3b8', fontSize: 10 },
            axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
            axisTick: { show: false }
        },
        yAxis: {
            type: 'value',
            max: 100,
            axisLabel: { color: '#94a3b8', fontSize: 9, formatter: '{value}%' },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.08)' } },
            axisLine: { show: false }
        },
        series: [
            {
                name: '战略基准 (SAA)',
                type: 'bar',
                data: saaData,
                itemStyle: { color: 'rgba(148, 163, 184, 0.25)', borderRadius: [3, 3, 0, 0] },
                barMaxWidth: 16
            },
            {
                name: '当前战术 (TAA)',
                type: 'bar',
                data: taaData,
                itemStyle: {
                    color: function(params) {
                        const keys = ['equity_cn', 'bond', 'gold', 'cash'];
                        const k = keys[params.dataIndex];
                        return _MA_ASSET_COLORS[k] || '#3b82f6';
                    },
                    borderRadius: [3, 3, 0, 0]
                },
                barMaxWidth: 16
            }
        ]
    });
}
