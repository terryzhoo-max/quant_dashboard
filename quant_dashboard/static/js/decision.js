/**
 * AlphaCore V17.1 · 决策中枢 JS
 * ================================
 * - JCS 环形仪表盘 (Canvas)
 * - 矛盾矩阵渲染
 * - 执行建议卡片 (V17.0)
 * - 情景模拟器交互
 * - 决策时间线图 (ECharts) + AIAE Regime 色带
 */

const API_BASE = '/api/v1/decision';

// ═══════════════════════════════════════════════════
//  Tab 切换
// ═══════════════════════════════════════════════════

function initTabs() {
    document.querySelectorAll('.decision-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.decision-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tab);
            if (target) target.classList.add('active');

            // 切到对应 tab 时懒加载数据
            if (tab.dataset.tab === 'tab-timeline') loadTimeline();
            if (tab.dataset.tab === 'tab-risk') loadRiskMatrix();
            if (tab.dataset.tab === 'tab-calendar') loadCalendar();
        });
    });
}

// ═══════════════════════════════════════════════════
//  JCS 环形图 (Canvas)
// ═══════════════════════════════════════════════════

function drawJCSRing(score, level) {
    const canvas = document.getElementById('jcs-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const size = 180;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = size + 'px';
    canvas.style.height = size + 'px';
    ctx.scale(dpr, dpr);

    const cx = size / 2, cy = size / 2, r = 72, lw = 10;
    const colors = { high: '#34d399', medium: '#fbbf24', low: '#f87171' };
    const color = colors[level] || '#94a3b8';
    const targetPct = Math.min(score / 100, 1);
    const startAngle = -Math.PI / 2;
    const el = document.getElementById('jcs-value');
    const badge = document.getElementById('jcs-badge');
    if (badge) {
        badge.className = 'jcs-level-badge ' + level;
        const labels = { high: '高置信', medium: '中置信', low: '低置信' };
        badge.textContent = labels[level] || level;
    }
    // A4: 缓动动画
    let current = 0;
    const duration = 800;
    const startTime = performance.now();
    function animate(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 3); // easeOutCubic
        current = targetPct * ease;
        ctx.clearRect(0, 0, size, size);
        // 背景轨道
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI);
        ctx.strokeStyle = 'rgba(148,163,184,0.08)'; ctx.lineWidth = lw; ctx.stroke();
        // 进度弧
        const endAngle = startAngle + current * 2 * Math.PI;
        ctx.beginPath(); ctx.arc(cx, cy, r, startAngle, endAngle);
        ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.stroke();
        // 发光
        ctx.beginPath(); ctx.arc(cx, cy, r, startAngle, endAngle);
        ctx.strokeStyle = color; ctx.lineWidth = lw + 6; ctx.globalAlpha = 0.15; ctx.stroke(); ctx.globalAlpha = 1;
        if (el) el.textContent = (score * ease).toFixed(1);
        if (progress < 1) requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
}

// ═══════════════════════════════════════════════════
//  矛盾矩阵渲染
// ═══════════════════════════════════════════════════

function renderConflicts(data) {
    const panel = document.getElementById('conflict-list');
    const summary = document.getElementById('conflict-summary');
    if (!panel || !summary) return;
    const cls = data.has_severe ? 'danger' : (data.conflict_count > 0 ? 'warn' : 'ok');
    summary.className = 'conflict-summary ' + cls;
    summary.textContent = data.matrix_summary;
    if (data.conflicts.length === 0) {
        // V20.0: 紧凑无矛盾状态 — 一行徽章替代4行列表
        panel.innerHTML = `<div class="no-conflict-badge"><span class="pulse-dot"></span> 所有引擎信号对齐，零矛盾</div>`;
        return;
    }
    panel.innerHTML = data.conflicts.map(c => `
        <div class="conflict-item">
            <div class="conflict-color-band ${c.severity}"></div>
            <div class="conflict-body">
                <div class="conflict-desc">${c.desc}</div>
                <div class="conflict-action">💡 ${c.action}</div>
            </div>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════
//  方向指示器
// ═══════════════════════════════════════════════════

function renderDirections(directions, snapshot) {
    const grid = document.getElementById('direction-grid');
    if (!grid) return;

    const engines = {
        aiae: { label: 'AIAE', weight: 35, unit: '%',
            val: snapshot ? snapshot.aiae_v1 : null,
            fmt: v => v != null ? v.toFixed(1) + '%' : '--' },
        erp:  { label: 'ERP', weight: 25, unit: '%',
            val: snapshot ? snapshot.erp_val : null,
            fmt: v => v != null ? v.toFixed(2) + '%' : '--' },
        vix:  { label: 'VIX', weight: 15, unit: '',
            val: snapshot ? snapshot.vix_val : null,
            fmt: v => v != null ? v.toFixed(1) : '--' },
        mr:   { label: 'MR', weight: 15, unit: '',
            val: snapshot ? snapshot.mr_regime : null,
            fmt: v => v || '--' },
    };
    const arrows = { '1': '▲', '-1': '▼', '0': '━' };
    const cls = { '1': 'up', '-1': 'down', '0': 'neutral' };
    const meanings = {
        aiae: { '1': '冷配加仓', '-1': '过热减仓', '0': '中性均衡' },
        erp:  { '1': '估值偏低', '-1': '估值偏高', '0': '估值中性' },
        vix:  { '1': '恐慌低迷', '-1': '恐慌较高', '0': '波动正常' },
        mr:   { '1': '技术看多', '-1': '技术看空', '0': '区间震荡' },
    };

    grid.innerHTML = Object.entries(directions).map(([key, dir]) => {
        const eng = engines[key] || {};
        const dirStr = String(dir);
        const arrowCls = cls[dirStr] || 'neutral';
        return `
        <div class="direction-item dir-${arrowCls}">
            <div class="dir-header">
                <span class="direction-label">${eng.label || key}</span>
                <span class="dir-weight">${eng.weight || 10}%</span>
            </div>
            <div class="dir-center">
                <div class="direction-arrow ${arrowCls}">${arrows[dirStr] || '●'}</div>
                <div class="dir-realval">${eng.fmt ? eng.fmt(eng.val) : '--'}</div>
            </div>
            <div class="direction-meaning">${(meanings[key] || {})[dirStr] || ''}</div>
        </div>`;
    }).join('');
}


// ═══════════════════════════════════════════════════
//  情景模拟器
// ═══════════════════════════════════════════════════

let currentScenarios = {};

function renderScenarioCards(scenarios) {
    currentScenarios = scenarios;
    const grid = document.getElementById('scenario-grid');
    if (!grid) return;

    grid.innerHTML = Object.entries(scenarios).map(([id, s]) => `
        <div class="scenario-card sev-${s.severity}" data-id="${id}" onclick="runSimulation('${id}')">
            <div class="scenario-icon">${s.icon}</div>
            <div class="scenario-name">${s.name}</div>
            <div class="scenario-desc">${s.desc}</div>
            <span class="scenario-badge ${s.severity}">${s.severity === 'extreme' ? '极端' : (s.severity === 'positive' ? '积极' : '高影响')}</span>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════
//  V20.0: 内联执行指令渲染 (合并至决策面板)
// ═══════════════════════════════════════════════════

function renderActionPlan(plan) {
    const el = document.getElementById('action-inline');
    if (!el || !plan) return;

    // 置信度色带 (左边框)
    const confColors = { high: '#10b981', medium: '#f59e0b', low: '#ef4444' };
    el.style.borderLeftColor = confColors[plan.confidence] || confColors.medium;
    el.style.display = 'block';

    const iconEl = document.getElementById('action-icon');
    const labelEl = document.getElementById('action-label');
    const confEl = document.getElementById('action-confidence');
    const reasonEl = document.getElementById('action-reasoning');
    const nextEl = document.getElementById('action-next-val');
    const posEl = document.getElementById('action-pos-val');
    const riskEl = document.getElementById('action-risk');

    if (iconEl) iconEl.textContent = plan.action_icon || '👁️';
    if (labelEl) labelEl.textContent = plan.action_label || '--';
    if (confEl) {
        const confMap = { high: '高置信', medium: '中置信', low: '低置信' };
        confEl.innerHTML = `<span class="conf-dot ${plan.confidence}"></span> ${confMap[plan.confidence] || '中置信'}`;
    }
    if (reasonEl) reasonEl.textContent = plan.reasoning || '';
    if (nextEl) nextEl.textContent = plan.next_check || '--';
    if (posEl) posEl.textContent = (plan.position_target != null ? plan.position_target + '%' : '--%');
    if (riskEl) riskEl.textContent = '⚠️ ' + (plan.risk_note || '');
}

// ═══════════════════════════════════════════════════
//  V17.3 I: 警示卡片渲染
// ═══════════════════════════════════════════════════

function renderAlerts(alerts) {
    const container = document.getElementById('alert-container');
    if (!container) return;
    if (!alerts || alerts.length === 0) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = alerts.map(a => `
        <div class="alert-card alert-${a.severity}">
            <div class="alert-header">
                <span class="alert-icon">${a.icon}</span>
                <span class="alert-title">${a.title}</span>
            </div>
            <div class="alert-detail">${a.detail}</div>
            <span class="alert-rule">${a.rule}</span>
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════
//  V17.5 K: AIAE 宏观仓位管控仪表
// ═══════════════════════════════════════════════════

const _REGIME_DEFS = [
    { r: 1, emoji: '🟢', name: 'Ⅰ级', cn: '极度恐慌', range: '<12.5%', pos: '90-95%', color: '#10b981' },
    { r: 2, emoji: '🟥', name: 'Ⅱ级', cn: '低配置区', range: '12.5-17%', pos: '70-85%', color: '#3b82f6' },
    { r: 3, emoji: '🟡', name: 'Ⅲ级', cn: '中性均衡', range: '17-23%', pos: '50-65%', color: '#eab308' },
    { r: 4, emoji: '🟠', name: 'Ⅳ级', cn: '偏热区域', range: '23-30%', pos: '25-40%', color: '#f97316' },
    { r: 5, emoji: '🔴', name: 'Ⅴ级', cn: '极度过热', range: '>30%', pos: '0-15%', color: '#ef4444' },
];

function renderAIAEHub(snapshot) {
    const panel = document.getElementById('aiae-hub-panel');
    if (!panel) return;

    const regime = snapshot.aiae_regime || 3;
    const v1 = snapshot.aiae_v1 || 22;
    const regimeCn = snapshot.aiae_regime_cn || '中性均衡';
    const cap = snapshot.aiae_cap || 55;
    const slope = snapshot.aiae_slope || 0;
    const slopeDir = snapshot.aiae_slope_dir || 'flat';
    const marginHeat = snapshot.margin_heat || 2.0;
    const fundPos = snapshot.fund_position || 80;
    const rd = _REGIME_DEFS.find(d => d.r === regime) || _REGIME_DEFS[2];

    panel.style.display = 'block';

    // ── ECharts 半环仪表 ──
    const chartEl = document.getElementById('aiae-hub-gauge-chart');
    if (chartEl && typeof echarts !== 'undefined') {
        const chart = echarts.init(chartEl);
        chart.setOption({
            series: [{
                type: 'gauge',
                startAngle: 200,
                endAngle: -20,
                min: 0,
                max: 40,
                radius: '90%',
                center: ['50%', '60%'],
                splitNumber: 8,
                axisLine: {
                    lineStyle: {
                        width: 14,
                        color: [
                            [0.3125, '#10b981'],  // 0-12.5: 绿
                            [0.425, '#3b82f6'],   // 12.5-17: 蓝
                            [0.575, '#eab308'],   // 17-23: 黄
                            [0.75, '#f97316'],     // 23-30: 橙
                            [1, '#ef4444'],        // 30-40: 红
                        ]
                    }
                },
                pointer: {
                    length: '55%', width: 4,
                    itemStyle: { color: rd.color }
                },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: {
                    distance: -20, fontSize: 9, color: '#475569',
                    formatter: v => v % 10 === 0 ? v + '%' : ''
                },
                title: { show: false },
                detail: {
                    valueAnimation: true,
                    formatter: '{value}%',
                    fontSize: 22, fontWeight: 700,
                    color: rd.color,
                    offsetCenter: [0, '10%']
                },
                data: [{ value: Math.round(v1 * 10) / 10 }]
            }]
        });
        if (typeof AC !== 'undefined') AC._charts?.add(chart);
    }

    // ── Regime 标签 + 斜率 ──
    const regimeEl = document.getElementById('aiae-hub-regime');
    if (regimeEl) {
        regimeEl.textContent = `${rd.emoji} ${rd.name} · ${regimeCn}`;
        regimeEl.style.color = rd.color;
    }
    const slopeEl = document.getElementById('aiae-hub-slope');
    if (slopeEl) {
        const arrow = slopeDir === 'up' ? '↗' : slopeDir === 'down' ? '↘' : '→';
        const sign = slope > 0 ? '+' : '';
        slopeEl.textContent = `月环比斜率: ${arrow} ${sign}${slope.toFixed(2)}`;
        slopeEl.style.color = Math.abs(slope) >= 1.5 ? '#ef4444' : '#94a3b8';
    }

    // ── 五档状态条 ──
    const strip = document.getElementById('aiae-hub-regime-strip');
    if (strip) {
        strip.innerHTML = _REGIME_DEFS.map(d => `
            <div class="aiae-hub-regime-item${d.r === regime ? ' active' : ''}" style="${d.r === regime ? 'background:rgba(255,255,255,0.04);border-color:' + d.color + '30;' : ''}">
                <div class="aiae-hub-ri-emoji">${d.emoji}</div>
                <div class="aiae-hub-ri-name" style="${d.r === regime ? 'color:' + d.color : ''}">${d.name}</div>
                <div class="aiae-hub-ri-range">${d.range}</div>
                <div class="aiae-hub-ri-pos">仓位 ${d.pos}</div>
            </div>
        `).join('');
    }

    // ── 三警示指标 ──
    const warns = document.getElementById('aiae-hub-warnings');
    if (warns) {
        const items = [
            {
                label: '🔥 融资热度', val: marginHeat.toFixed(2) + '%',
                pct: Math.min(100, (marginHeat / 5) * 100),
                danger: marginHeat >= 3.5,
                color: marginHeat >= 3.5 ? '#ef4444' : '#10b981',
                threshold: '警戒: >3.5%'
            },
            {
                label: '📐 月环比斜率', val: (slope > 0 ? '+' : '') + slope.toFixed(2),
                pct: Math.min(100, (Math.abs(slope) / 3) * 100),
                danger: Math.abs(slope) >= 1.5,
                color: Math.abs(slope) >= 1.5 ? '#ef4444' : '#10b981',
                threshold: '警戒: |±1.5|'
            },
            {
                label: '🏦 基金仓位', val: fundPos + '%',
                pct: Math.min(100, fundPos),
                danger: fundPos >= 90,
                color: fundPos >= 90 ? '#ef4444' : '#10b981',
                threshold: '警戒: >90%'
            },
        ];
        warns.innerHTML = items.map(w => `
            <div class="aiae-hub-warn-item">
                <div class="aiae-hub-warn-label">${w.label}</div>
                <div class="aiae-hub-warn-val" style="color:${w.color}">${w.val}</div>
                <div class="aiae-hub-warn-bar"><div class="aiae-hub-warn-bar-fill" style="width:${w.pct}%;background:${w.color}"></div></div>
                <div class="aiae-hub-warn-status ${w.danger ? 'danger' : 'ok'}">${w.danger ? '⚠️' : 'OK'}</div>
            </div>
        `).join('');
    }
}

async function runSimulation(scenarioId) {
    // 高亮选中卡片
    document.querySelectorAll('.scenario-card').forEach(c => c.classList.remove('active'));
    const card = document.querySelector(`.scenario-card[data-id="${scenarioId}"]`);
    if (card) card.classList.add('active');

    const resultEl = document.getElementById('sim-result');
    if (resultEl) { resultEl.classList.remove('visible'); resultEl.innerHTML = '<div class="loading-spinner">⏳ 模拟推演中...</div>'; resultEl.classList.add('visible'); }

    try {
        if (typeof AC === 'undefined' || typeof AC.secureFetch !== 'function') {
            if (resultEl) resultEl.innerHTML = '<div class="loading-spinner">🔒 安全模块未就绪，请刷新页面 (Ctrl+Shift+R)</div>';
            console.error('AC.secureFetch not available - alphacore_utils.js may not be loaded');
            return;
        }
        const resp = await AC.secureFetch(`${API_BASE}/simulate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenario: scenarioId }),
        });
        const data = await resp.json();
        if (data.status === 'success') {
            renderSimResult(data);
        } else {
            resultEl.innerHTML = `<div class="loading-spinner">❌ ${data.error || '模拟失败'}</div>`;
        }
    } catch (e) {
        if (resultEl) resultEl.innerHTML = `<div class="loading-spinner">❌ ${e.isCancelled ? '操作已取消' : '网络错误: ' + e.message}</div>`;
    }
}

function renderSimResult(data) {
    const el = document.getElementById('sim-result');
    if (!el) return;

    const b = data.before;
    const a = data.after;
    const metrics = [
        ['AIAE 档位', b.aiae_regime ?? '--', a.aiae_regime ?? '--'],
        ['ERP 估值', (b.erp_val ?? '--') + '%', (a.erp_val ?? '--') + '%'],
        ['ERP 评分', b.erp_score ?? '--', a.erp_score ?? '--'],
        ['VIX', b.vix_val ?? '--', a.vix_val ?? '--'],
        ['建议仓位', (b.suggested_position ?? '--') + '%', (a.suggested_position ?? '--') + '%'],
        ['JCS', b.jcs ?? '--', a.jcs ?? '--'],
        ['Composite', b.hub_composite ?? '--', a.hub_composite ?? '--'],
    ];

    el.innerHTML = `
        <div class="sim-compare">
            <div class="sim-col before">
                <div class="sim-col-title">📍 当前状态</div>
                ${metrics.map(m => `<div class="sim-metric"><span class="sim-metric-name">${m[0]}</span><span class="sim-metric-val">${m[1]}</span></div>`).join('')}
            </div>
            <div class="sim-arrow">→</div>
            <div class="sim-col after">
                <div class="sim-col-title">🔮 ${data.scenario.name}</div>
                ${metrics.map(m => `<div class="sim-metric"><span class="sim-metric-name">${m[0]}</span><span class="sim-metric-val">${m[2]}</span></div>`).join('')}
            </div>
        </div>
        ${data.impact && data.impact.length > 0 ? `
        <div class="sim-impact">
            <div class="sim-impact-title">📊 影响摘要</div>
            ${data.impact.map(i => `<div class="sim-impact-item">• ${i}</div>`).join('')}
        </div>` : ''}
    `;
    el.classList.add('visible');
}

// ═══════════════════════════════════════════════════
//  决策时间线 (Tab 2)
// ═══════════════════════════════════════════════════

let timelineLoaded = false;

async function loadTimeline() {
    if (timelineLoaded) return;
    try {
        const resp = await AC.secureFetch(`${API_BASE}/history?days=30`);
        const data = await resp.json();
        if (data.status === 'success' && data.data.length > 0) {
            renderTimelineChart(data.data);
            renderTimelineList(data.data);
            timelineLoaded = true;
        } else {
            document.getElementById('timeline-chart').innerHTML = '';
            document.getElementById('timeline-list').innerHTML = `
                <div class="empty-state">
                    <div class="icon">📋</div>
                    <p>暂无决策日志数据<br>系统将在每日 15:35 收盘后自动记录</p>
                    <div class="placeholder-chart">── 趋势图将在此展示 ──</div>
                </div>`;
        }
    } catch (e) {
        console.error('Timeline load error:', e);
    }
}

function renderTimelineChart(data) {
    const chartEl = document.getElementById('timeline-chart');
    if (!chartEl || typeof echarts === 'undefined') return;

    const chart = echarts.init(chartEl);
    const dates = data.map(d => d.date);
    const jcsData = data.map(d => d.jcs_score);
    const posData = data.map(d => d.suggested_position);

    // V17.0 C3: AIAE Regime 色带 (markArea)
    const _regimeColors = {
        1: 'rgba(16,185,129,0.06)',   // 极度恐慌 (绿 = 加仓机会)
        2: 'rgba(16,185,129,0.04)',   // 低配置区
        3: 'rgba(148,163,184,0.03)',  // 中性
        4: 'rgba(245,158,11,0.06)',   // 偏热
        5: 'rgba(239,68,68,0.06)',    // 极度过热
    };
    const markAreas = [];
    let prevRegime = null, areaStart = null;
    data.forEach((d, i) => {
        const r = d.aiae_regime || 3;
        if (r !== prevRegime) {
            if (prevRegime !== null && areaStart !== null) {
                markAreas.push([{ xAxis: areaStart, itemStyle: { color: _regimeColors[prevRegime] || _regimeColors[3] } }, { xAxis: dates[i - 1] }]);
            }
            areaStart = dates[i];
            prevRegime = r;
        }
    });
    // 最后一段
    if (prevRegime !== null && areaStart !== null) {
        markAreas.push([{ xAxis: areaStart, itemStyle: { color: _regimeColors[prevRegime] || _regimeColors[3] } }, { xAxis: dates[dates.length - 1] }]);
    }

    chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['JCS 置信度', '建议仓位'], textStyle: { color: '#94a3b8', fontSize: 11 }, top: 0 },
        grid: { left: 45, right: 20, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: dates, axisLabel: { color: '#64748b', fontSize: 10, rotate: 30 }, axisLine: { lineStyle: { color: 'rgba(148,163,184,0.1)' } } },
        yAxis: [
            { type: 'value', min: 0, max: 100, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } } },
            { type: 'value', min: 0, max: 100, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { show: false } },
        ],
        series: [
            {
                name: 'JCS 置信度', type: 'line', data: jcsData, yAxisIndex: 0,
                lineStyle: { color: '#a78bfa', width: 2 },
                itemStyle: { color: '#a78bfa' },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(167,139,250,0.15)' }, { offset: 1, color: 'rgba(167,139,250,0)' }] } },
                smooth: true,
                markArea: markAreas.length > 0 ? { silent: true, data: markAreas } : undefined,
            },
            {
                name: '建议仓位', type: 'line', data: posData, yAxisIndex: 1,
                lineStyle: { color: '#34d399', width: 2 },
                itemStyle: { color: '#34d399' },
                smooth: true,
            },
        ],
    });

    window.addEventListener('resize', () => chart.resize());
}

function renderTimelineList(data) {
    const el = document.getElementById('timeline-list');
    if (!el) return;

    const header = `<div class="timeline-item header">
        <span>日期</span><span style="text-align:center">AIAE</span><span style="text-align:center">ERP</span>
        <span style="text-align:center">VIX</span><span style="text-align:center">MR</span><span style="text-align:center">JCS</span>
        <span style="text-align:center">仓位</span>
    </div>`;

    const mrColors = { BULL: '#34d399', BEAR: '#f87171', CRASH: '#ef4444', RANGE: '#94a3b8' };
    const rows = data.slice().reverse().slice(0, 15).map(d => {
        const jcsClass = d.jcs_level === 'high' ? 'color:#34d399' : (d.jcs_level === 'low' ? 'color:#f87171' : 'color:#fbbf24');
        const mr = d.mr_regime || '-';
        const mrC = mrColors[mr] || '#94a3b8';
        return `<div class="timeline-item">
            <span class="timeline-date">${(d.date || '').slice(5)}</span>
            <span class="timeline-val">R${d.aiae_regime ?? '-'}</span>
            <span class="timeline-val">${d.erp_score != null ? d.erp_score.toFixed(0) : '-'}</span>
            <span class="timeline-val">${d.vix_val != null ? d.vix_val.toFixed(1) : '-'}</span>
            <span class="timeline-val" style="color:${mrC};font-weight:600;font-size:0.72rem">${mr}</span>
            <span class="timeline-val timeline-jcs" style="${jcsClass}">${d.jcs_score != null ? d.jcs_score.toFixed(1) : '-'}</span>
            <span class="timeline-val">${d.suggested_position != null ? d.suggested_position.toFixed(0) + '%' : '-'}</span>
        </div>`;
    });

    el.innerHTML = header + rows.join('');
}

// ═══════════════════════════════════════════════════
//  Phase 2: 风险关联矩阵 (Tab 3)
// ═══════════════════════════════════════════════════

let riskLoaded = false;

async function loadRiskMatrix() {
    if (riskLoaded) return;
    try {
        const [riskResp, accResp] = await Promise.all([
            AC.secureFetch(`${API_BASE}/risk-matrix`),
            AC.secureFetch(`${API_BASE}/accuracy`),
        ]);
        const riskData = await riskResp.json();
        const accData = await accResp.json();

        if (riskData.status === 'success') {
            renderOverlapMatrix(riskData);
            renderSectorConcentration(riskData.sector_concentration);
            renderTailRisk(riskData.tail_risk);
        }
        if (accData.status === 'success') renderAccuracy(accData);
        // V18.0 Phase L: 绩效分析 (独立请求, 不阻塞主流程)
        loadPerformanceAnalytics();
        riskLoaded = true;
    } catch (e) { console.error('Risk matrix load error:', e); }
}

function renderOverlapMatrix(data) {
    const el = document.getElementById('overlap-matrix');
    if (!el) return;
    const names = data.strategy_names;
    if (names.length === 0) { el.innerHTML = '<div style="text-align:center;padding:20px;color:#64748b;">暂无策略数据</div>'; return; }
    const labels = { mr: 'MR趋势', div: 'DIV红利', mom: 'MOM动量' };
    let html = '<table class="overlap-table"><tr><th></th>';
    names.forEach(n => html += `<th>${labels[n] || n}</th>`);
    html += '</tr>';
    data.overlap_matrix.forEach((row, i) => {
        html += `<tr><th>${labels[names[i]] || names[i]}</th>`;
        row.forEach((cell, ci) => {
            const j = cell.jaccard;
            const isDiag = i === ci;
            const cls = isDiag ? 'overlap-cell diagonal' : 'overlap-cell';
            const bg = isDiag ? '' : `background:rgba(${j>0.3?'239,68,68':(j>0?'245,158,11':'16,185,129')},${0.08+j*0.25})`;
            html += `<td class="${cls}" style="${bg}">${(j*100).toFixed(0)}%<br><span style="font-size:0.65rem;color:#94a3b8">${cell.shared}个</span></td>`;
        });
        html += '</tr>';
    });
    html += '</table>';
    if (data.multi_strategy_codes.length > 0) {
        html += '<div style="margin-top:12px;font-size:0.8rem;color:#e2e8f0;">🔗 多策略共有标的:</div><div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">';
        data.multi_strategy_codes.forEach(c => { html += `<span style="background:rgba(139,92,246,0.1);border:1px solid rgba(139,92,246,0.2);padding:3px 8px;border-radius:6px;font-size:0.72rem;color:#a78bfa;">${c.code} (${c.count}策略)</span>`; });
        html += '</div>';
    }
    el.innerHTML = html;
}

function renderSectorConcentration(sectors) {
    const el = document.getElementById('sector-concentration');
    if (!el) return;
    if (!sectors || sectors.length === 0) {
        el.innerHTML = '<div style="text-align:center;padding:20px;color:#64748b;">暂无板块数据</div>';
        return;
    }
    const colors = ['#a78bfa', '#34d399', '#fbbf24', '#f87171', '#38bdf8', '#fb923c', '#e879f9', '#94a3b8'];
    el.innerHTML = sectors.map((s, i) => `
        <div class="sector-bar-row">
            <span class="sector-bar-name">${s.sector}</span>
            <div class="sector-bar-bg"><div class="sector-bar-fill" style="width:${s.pct}%;background:${colors[i % colors.length]}"></div></div>
            <span class="sector-bar-pct">${s.pct}%</span>
        </div>
    `).join('');
}

function renderTailRisk(tail) {
    const el = document.getElementById('tail-risk');
    if (!el) return;
    const comps = tail.components;
    const cColors = { concentration: '#a78bfa', vix: '#fbbf24', conflict: '#f87171' };
    const cLabels = { concentration: '集中', vix: 'VIX', conflict: '矛盾' };
    const lvlColor = tail.level === 'high' ? '#f87171' : (tail.level === 'medium' ? '#fbbf24' : '#34d399');
    el.innerHTML = `
        <div class="tail-risk-wrap">
            <div class="tail-gauge-container"><canvas id="tail-gauge-canvas"></canvas>
                <div class="tail-gauge-value ${tail.level}">${tail.score.toFixed(1)}</div>
            </div>
            <div class="tail-risk-label" style="color:${lvlColor}">${tail.label}</div>
            <div class="tail-risk-bars">
                ${Object.entries(comps).map(([k, v]) => `<div class="tail-bar-row"><span class="tail-bar-name">${cLabels[k]}</span><div class="tail-bar-bg"><div class="tail-bar-fill" style="width:${v}%;background:${cColors[k]}"></div></div></div>`).join('')}
            </div>
        </div>`;
    // B1: 半圆 Gauge Canvas
    setTimeout(() => drawTailGauge(tail.score), 50);
}
function drawTailGauge(score) {
    const canvas = document.getElementById('tail-gauge-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = 240, h = 130;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    ctx.scale(dpr, dpr);
    const cx = w/2, cy = h - 10, r = 90, lw = 14;
    const pct = Math.min(score / 100, 1);
    // 背景弧
    ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0);
    ctx.strokeStyle = 'rgba(148,163,184,0.08)'; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.stroke();
    // 渐变弧 (绿→黄→红)
    const grad = ctx.createLinearGradient(cx - r, cy, cx + r, cy);
    grad.addColorStop(0, '#34d399'); grad.addColorStop(0.5, '#fbbf24'); grad.addColorStop(1, '#f87171');
    const endAngle = Math.PI + pct * Math.PI;
    let cur = 0; const dur = 700; const st = performance.now();
    function anim(now) {
        const p = Math.min((now - st) / dur, 1);
        const e = 1 - Math.pow(1-p, 3); cur = pct * e;
        ctx.clearRect(0, 0, w, h);
        ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0);
        ctx.strokeStyle = 'rgba(148,163,184,0.08)'; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.stroke();
        ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + cur * Math.PI);
        ctx.strokeStyle = grad; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.stroke();
        // 发光
        ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + cur * Math.PI);
        ctx.strokeStyle = grad; ctx.lineWidth = lw + 6; ctx.globalAlpha = 0.12; ctx.stroke(); ctx.globalAlpha = 1;
        if (p < 1) requestAnimationFrame(anim);
    }
    requestAnimationFrame(anim);
}

function renderAccuracy(data) {
    const el = document.getElementById('accuracy-panel');
    if (!el) return;
    if (!data.has_data) {
        el.innerHTML = `<div class="skeleton-grid">
            <div class="skeleton-card"><div class="skeleton-bar"></div><div class="skeleton-text"></div></div>
            <div class="skeleton-card"><div class="skeleton-bar"></div><div class="skeleton-text"></div></div>
            <div class="skeleton-card"><div class="skeleton-bar"></div><div class="skeleton-text"></div></div>
        </div>
        <div style="text-align:center;padding:12px 0 0;color:#64748b;font-size:0.78rem;">📊 系统正在积累信号准确率数据 (T+5)...</div>`;
        return;
    }
    el.innerHTML = `
        <div class="accuracy-grid">
            <div class="accuracy-metric">
                <div class="accuracy-value" style="color:${(data.accuracy_pct || 0) >= 60 ? '#34d399' : '#fbbf24'}">${data.accuracy_pct != null ? data.accuracy_pct + '%' : '--'}</div>
                <div class="accuracy-label">总体准确率 (${data.total_decisions}次)</div>
            </div>
            <div class="accuracy-metric">
                <div class="accuracy-value" style="color:#a78bfa">${data.recent_10_accuracy != null ? data.recent_10_accuracy + '%' : '--'}</div>
                <div class="accuracy-label">近10次准确率</div>
            </div>
            <div class="accuracy-metric">
                <div class="accuracy-value">${data.correct_decisions}</div>
                <div class="accuracy-label">正确决策次数</div>
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════
//  Phase 2: 复盘日历 (Tab 4)
// ═══════════════════════════════════════════════════

let calendarLoaded = false;
let calendarYear, calendarMonth;

async function loadCalendar() {
    const now = new Date();
    if (!calendarYear) { calendarYear = now.getFullYear(); calendarMonth = now.getMonth() + 1; }
    try {
        const resp = await AC.secureFetch(`${API_BASE}/calendar?year=${calendarYear}&month=${calendarMonth}`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderCalendar(data.data, calendarYear, calendarMonth);
            calendarLoaded = true;
        }
    } catch (e) { console.error('Calendar load error:', e); }
}

function changeMonth(delta) {
    calendarMonth += delta;
    if (calendarMonth > 12) { calendarMonth = 1; calendarYear++; }
    if (calendarMonth < 1) { calendarMonth = 12; calendarYear--; }
    calendarLoaded = false;
    loadCalendar();
}

function jcsToColor(score) {
    // B3: 连续色温 (0=红, 50=黄, 100=绿)
    const s = Math.max(0, Math.min(100, score));
    if (s >= 50) { const t = (s - 50) / 50; return { r: Math.round(251*(1-t)+52*t), g: Math.round(191*(1-t)+211*t), b: Math.round(36*(1-t)+153*t) }; }
    const t = s / 50; return { r: Math.round(248*(1-t)+251*t), g: Math.round(113*(1-t)+191*t), b: Math.round(113*(1-t)+36*t) };
}
function renderCalendar(data, year, month) {
    const el = document.getElementById('calendar-grid');
    const titleEl = document.getElementById('calendar-title');
    if (!el) return;
    if (titleEl) titleEl.textContent = `${year}年${month}月`;
    const dataMap = {}; data.forEach(d => { if (d.date) dataMap[d.date] = d; });
    const firstDay = new Date(year, month - 1, 1).getDay();
    const daysInMonth = new Date(year, month, 0).getDate();
    const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    let html = weekdays.map(w => `<div class="calendar-weekday">${w}</div>`).join('');
    for (let i = 0; i < firstDay; i++) html += '<div class="calendar-day empty"></div>';
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        const entry = dataMap[dateStr];
        if (entry) {
            const jcs = entry.jcs_score != null ? entry.jcs_score : 50;
            const jcsStr = jcs.toFixed(1);
            const c = jcsToColor(jcs);
            const bg = `rgba(${c.r},${c.g},${c.b},0.15)`;
            const fg = `rgb(${c.r},${c.g},${c.b})`;
            const pos = entry.suggested_position != null ? entry.suggested_position + '%' : '--';
            const correct = entry.signal_correct;
            const ci = correct === 1 ? '✅' : (correct === 0 ? '❌' : '');
            html += `<div class="calendar-day has-data" style="background:${bg};box-shadow:inset 0 0 12px rgba(${c.r},${c.g},${c.b},0.08)">
                <span class="day-num">${d}</span><span class="day-jcs" style="color:${fg}">${jcsStr}</span>
                <div class="calendar-tooltip">JCS: ${jcsStr} | R${entry.aiae_regime||'-'} | ${entry.mr_regime||'-'}<br>仓位: ${pos} | ERP: ${entry.erp_score != null ? entry.erp_score.toFixed(0) : '-'}${ci?'<br>信号: '+ci:''}</div>
            </div>`;
        } else {
            html += `<div class="calendar-day no-data"><span class="day-num" style="color:#334155">${d}</span></div>`;
        }
    }
    el.innerHTML = html;
}

// ═══════════════════════════════════════════════════
//  V18.0 M: JCS 成分拆解 (Koyfin 风格因子条)
// ═══════════════════════════════════════════════════

function renderJCSComponents(jcs) {
    const el = document.getElementById('jcs-components');
    if (!el) return;
    const items = [
        { label: '一致性', val: jcs.agreement_pct, max: 100, color: '#a78bfa', suffix: '%' },
        { label: '数据健康', val: jcs.data_health, max: 20, color: '#34d399', suffix: '/20' },
        { label: '共识加成', val: jcs.consensus_bonus, max: 20, color: '#fbbf24', suffix: '/20' },
    ];
    el.innerHTML = items.map(it => {
        const pct = Math.min(100, (it.val / it.max) * 100);
        return `<div class="jcs-comp-row">
            <span class="jcs-comp-label">${it.label}</span>
            <div class="jcs-comp-bar-bg"><div class="jcs-comp-bar-fill" style="width:${pct}%;background:${it.color}"></div></div>
            <span class="jcs-comp-val">${it.val != null ? (typeof it.val === 'number' ? it.val.toFixed(1) : it.val) : '--'}${it.suffix}</span>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════
//  V19.0: 全球市场温度仪表板
// ═══════════════════════════════════════════════════

const _globalTempCharts = {};

function renderGlobalTemperature(gt) {
    const gridEl = document.getElementById('global-temp-grid');
    const recEl = document.getElementById('global-temp-rec');
    const timeEl = document.getElementById('global-temp-time');
    if (!gridEl) return;

    // 时间戳
    if (timeEl) {
        const now = new Date();
        timeEl.textContent = now.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'}) + ' 更新';
    }

    const markets = gt.markets || [];
    if (markets.length === 0) {
        gridEl.innerHTML = '<div class="loading-spinner">暂无全球市场数据</div>';
        return;
    }

    // 渲染卡片
    gridEl.innerHTML = markets.map(m => {
        if (m.status === 'loading') {
            return `<div class="global-temp-card-loading">
                <div class="global-temp-market-name"><span class="global-temp-flag">${m.flag}</span> ${m.name}</div>
                <div class="skeleton-bar"></div>
                <div style="font-size:0.72rem;color:#475569">加载中...</div>
            </div>`;
        }
        const color = m.regime_color || '#eab308';
        const aiae = typeof m.aiae_v1 === 'number' ? m.aiae_v1.toFixed(1) : '--';
        const cap = m.cap || 55;
        return `<div class="global-temp-card" style="--regime-color:${color}">
            <div style="position:absolute;top:0;left:0;right:0;height:3px;background:${color};opacity:0.7"></div>
            <div class="global-temp-market-name">
                <span class="global-temp-flag">${m.flag}</span> ${m.name}
            </div>
            <div class="global-temp-gauge" id="gt-gauge-${m.key}"></div>
            <div class="global-temp-regime-badge" style="background:${color}15;color:${color};border:1px solid ${color}30">
                ${m.emoji} R${m.regime} · ${m.regime_cn}
            </div>
            <div class="global-temp-pos-row">
                <span class="global-temp-pos-label">仓位</span>
                <div class="global-temp-pos-bar">
                    <div class="global-temp-pos-fill" style="width:${cap}%;background:${color}"></div>
                </div>
                <span class="global-temp-pos-val">${cap}%</span>
            </div>
            <div class="global-temp-action">📋 ${m.action}</div>
        </div>`;
    }).join('');

    // 初始化 ECharts Gauge (延迟确保 DOM 已渲染)
    requestAnimationFrame(() => {
        markets.forEach(m => {
            if (m.status === 'loading') return;
            const gaugeEl = document.getElementById(`gt-gauge-${m.key}`);
            if (!gaugeEl) return;

            // 销毁旧实例
            if (_globalTempCharts[m.key]) {
                _globalTempCharts[m.key].dispose();
            }
            const chart = echarts.init(gaugeEl);
            _globalTempCharts[m.key] = chart;

            const bands = m.gauge_bands || [15, 20, 27, 34, 45];
            const maxVal = bands[4];
            const aiae = typeof m.aiae_v1 === 'number' ? m.aiae_v1 : 22;

            chart.setOption({
                series: [{
                    type: 'gauge',
                    startAngle: 200, endAngle: -20,
                    radius: '90%', center: ['50%', '65%'],
                    min: 0, max: maxVal,
                    splitNumber: 5,
                    axisLine: {
                        lineStyle: {
                            width: 12,
                            color: [
                                [bands[0]/maxVal, '#10b981'],
                                [bands[1]/maxVal, '#3b82f6'],
                                [bands[2]/maxVal, '#eab308'],
                                [bands[3]/maxVal, '#f97316'],
                                [1, '#ef4444'],
                            ]
                        }
                    },
                    pointer: {
                        icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z',
                        length: '55%', width: 6,
                        offsetCenter: [0, '-10%'],
                        itemStyle: { color: m.regime_color || '#eab308' }
                    },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: {
                        distance: 14, fontSize: 9,
                        color: '#475569',
                        formatter: v => v % Math.round(maxVal/4) === 0 ? v + '%' : ''
                    },
                    detail: {
                        valueAnimation: true,
                        fontSize: 18, fontWeight: 700,
                        color: m.regime_color || '#e2e8f0',
                        offsetCenter: [0, '30%'],
                        formatter: v => v.toFixed(1) + '%'
                    },
                    data: [{ value: aiae }]
                }]
            });
        });

        // Resize 监听
        const resizeAll = () => Object.values(_globalTempCharts).forEach(c => c && c.resize());
        window.removeEventListener('resize', resizeAll);
        window.addEventListener('resize', resizeAll);
    });

    // 全球推荐条
    if (recEl && gt.comparison) {
        const comp = gt.comparison;
        const names = {cn: 'A股', us: '美股', hk: '港股', jp: '日股'};
        let recHtml = '';
        if (comp.coldest && comp.hottest) {
            // coldest/hottest 可能是字符串 "hk" 或对象 {region, aiae_v1}
            const coldKey = typeof comp.coldest === 'string' ? comp.coldest : comp.coldest.region;
            const hotKey = typeof comp.hottest === 'string' ? comp.hottest : comp.hottest.region;
            const coldName = names[coldKey] || coldKey;
            const hotName = names[hotKey] || hotKey;
            // 从 comparison 的 xx_aiae 字段获取值
            const coldV = comp[coldKey + '_aiae'] != null ? Number(comp[coldKey + '_aiae']).toFixed(1) : '--';
            const hotV = comp[hotKey + '_aiae'] != null ? Number(comp[hotKey + '_aiae']).toFixed(1) : '--';
            recHtml = `<span class="global-temp-rec-icon">🧊</span> 当前 <b>${coldName}</b>(AIAE=${coldV}%) 配置热度最低, 超配优先; <b>${hotName}</b>(AIAE=${hotV}%) 最高, 谨慎配置`;
        } else if (comp.recommendation) {
            recHtml = `<span class="global-temp-rec-icon">💡</span> ${comp.recommendation}`;
        }
        if (recHtml) {
            recEl.innerHTML = recHtml;
            recEl.classList.add('visible');
        }
    }
}

// ═══════════════════════════════════════════════════
//  页面初始化
// ═══════════════════════════════════════════════════

async function initDecisionHub() {
    initTabs();

    try {
        fetchSwingGuard(); // Load Swing Guard
        
        const resp = await AC.secureFetch(`${API_BASE}/hub`);
        const data = await resp.json();

        if (data.status === 'success') {
            // JCS
            drawJCSRing(data.jcs.score, data.jcs.level);
            const labelEl = document.getElementById('jcs-label');
            if (labelEl) labelEl.textContent = data.jcs.label;
            // V18.0 M: JCS 成分拆解条
            renderJCSComponents(data.jcs);

            // V20.0: 事实层先渲染 (方向指示器)
            renderDirections(data.jcs.directions, data.snapshot);

            // 推导层 (矛盾检测)
            renderConflicts(data.conflicts);

            // 内联执行指令
            if (data.action_plan) renderActionPlan(data.action_plan);

            // V17.3: 警示系统
            renderAlerts(data.alerts || []);

            // V19.0: 全球市场温度仪表板
            if (data.global_temperature) renderGlobalTemperature(data.global_temperature);

            // V17.5: AIAE 宏观仓位管控
            if (data.snapshot) renderAIAEHub(data.snapshot);

            // 情景
            renderScenarioCards(data.scenarios);
        } else {
            document.getElementById('jcs-value').textContent = '--';
        }
    } catch (e) {
        console.error('Decision hub load error:', e);
        document.querySelector('.loading-spinner')?.remove();
    }
}

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
    ['perf-heatmap-chart', 'perf-drawdown-chart', 'perf-sharpe-chart'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { const inst = echarts.getInstanceByDom(el); if (inst) inst.dispose(); }
    });
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
    const chart = echarts.init(el);

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
    window.addEventListener('resize', () => chart.resize());
}

function renderPerfDrawdown(dd) {
    const el = document.getElementById('perf-drawdown-chart');
    if (!el || !dd || !dd.series || dd.series.length === 0) return;
    const chart = echarts.init(el);

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
    window.addEventListener('resize', () => chart.resize());
}

function renderPerfSharpe(sharpeData) {
    const el = document.getElementById('perf-sharpe-chart');
    if (!el || !sharpeData || sharpeData.length === 0) return;
    const chart = echarts.init(el);

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
    window.addEventListener('resize', () => chart.resize());
}

// ═══════════════════════════════════════════════════
//  Phase 2: 全球宽基波段守卫 (Swing Guard)
// ═══════════════════════════════════════════════════

async function fetchSwingGuard() {
    const grid = document.getElementById('swing-guard-grid');
    if (!grid) return;
    
    grid.innerHTML = '<div class="loading-spinner">⏳ 拉取7大ETF最新信号 (若Tushare冷启动约需5秒)...</div>';
    
    try {
        const resp = await AC.secureFetch(`${API_BASE}/swing-guard`);
        const result = await resp.json();
        
        if (result.status === 'success') {
            renderSwingGuard(result.data);
            if (result.cached) {
                console.log("Swing Guard: Using cached data");
            }
        } else {
            grid.innerHTML = `<div class="loading-spinner">❌ 无法获取波段守卫数据: ${result.error || '未知错误'}</div>`;
        }
    } catch (e) {
        grid.innerHTML = `<div class="loading-spinner">❌ 网络请求失败</div>`;
        console.error("Swing Guard fetch error: ", e);
    }
}

function renderSwingGuard(data) {
    const grid = document.getElementById('swing-guard-grid');
    if (!grid) return;
    
    if (!data || Object.keys(data).length === 0) {
        grid.innerHTML = '<div class="loading-spinner">暂无波段监测数据</div>';
        return;
    }
    
    const statusStyles = { 
        "GREEN": { card: "sg-status-green", text: "sg-text-green", bg: "sg-bg-green" }, 
        "YELLOW": { card: "sg-status-yellow", text: "sg-text-yellow", bg: "sg-bg-yellow" }, 
        "RED": { card: "sg-status-red", text: "sg-text-red", bg: "sg-bg-red" }, 
        "UNKNOWN": { card: "", text: "sg-text-neutral", bg: "sg-bg-neutral" }, 
        "ERROR": { card: "sg-status-red", text: "sg-text-red", bg: "sg-bg-red" } 
    };
    const emojis = { "GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "UNKNOWN": "⚪", "ERROR": "❌" };
    
    let html = '';
    
    // Sort logic to put RED on top
    const entries = Object.entries(data).sort((a, b) => {
        const order = {"RED":0, "YELLOW":1, "GREEN":2};
        const stA = a[1].status || "UNKNOWN";
        const stB = b[1].status || "UNKNOWN";
        return (order[stA]??3) - (order[stB]??3);
    });
    
    entries.forEach(([assetId, info]) => {
        const st = info.status || "UNKNOWN";
        const style = statusStyles[st] || statusStyles["UNKNOWN"];
        const emoji = emojis[st] || "⚪";
        
        const action = info.action || '--';
        const rawBuffer = info.buffer_pct !== undefined ? info.buffer_pct : 0;
        const bufferStr = info.buffer_pct !== undefined ? (rawBuffer * 100).toFixed(1) + '%' : '--';
        const reason = info.reason || '';
        const name = info.asset_name || assetId;
        
        // Energy Bar Logic (Max ref is 12%)
        let barWidth = Math.max(0, Math.min(100, (rawBuffer / 0.12) * 100));
        let barColor = st === 'GREEN' ? '#10b981' : (st === 'YELLOW' ? '#f59e0b' : '#ef4444');
        let flashClass = rawBuffer <= 0.005 ? 'flash' : ''; // Flash if buffer is negative or very close to 0
        if (st === 'RED') barWidth = 100; // If red, fill the bar with red flashing
        
        html += `
            <div class="sg-card ${style.card}">
                <div class="sg-header">
                    <div class="sg-title">${emoji} ${name}</div>
                    <div class="sg-badge ${style.bg}">${action}</div>
                </div>
                
                <div class="sg-data-row">
                    <span class="sg-data-label">安全垫缓冲</span>
                    <span class="sg-data-value ${rawBuffer < 0 ? 'sg-text-red' : style.text}">${bufferStr}</span>
                </div>
                
                <div class="sg-buffer-track">
                    <div class="sg-buffer-fill ${flashClass}" style="width: ${barWidth}%; background: ${barColor};"></div>
                </div>
                
                <div class="sg-footer">
                    ${reason}
                </div>
            </div>
        `;
    });
    
    grid.innerHTML = html;
}

// 启动
document.addEventListener('DOMContentLoaded', initDecisionHub);

