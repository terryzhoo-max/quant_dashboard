/**
 * AlphaCore V21.2 · Hub 核心渲染模块
 * ====================================
 * - JCS 环形仪表盘 (Canvas)
 * - 矛盾矩阵渲染
 * - 方向指示器
 * - 情景模拟器卡片
 * - 执行建议卡片
 * - 警示卡片
 * - AIAE 宏观仓位管控仪表
 *
 * 依赖: _getChart, _fmt (from _infra.js)
 */
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
    ctx.setTransform(1, 0, 0, 1, 0, 0);  // V19.3: 防止多次调用 scale 叠加
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
        panel.innerHTML = `<div class="no-conflict-badge"><span class="pulse-dot"></span> 零矛盾信号，各引擎间无方向冲突</div>`;
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
        vix:  { label: 'VIX', weight: 20, unit: '',
            val: snapshot ? snapshot.vix_val : null,
            fmt: v => v != null ? v.toFixed(1) : '--' },
        mr:   { label: 'MR', weight: 20, unit: '',
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

    // 置信度色温弥散光 (CSS 变量驱动底光 + 顶线)
    const confColorMap = {
        high: 'rgba(16, 185, 129, 0.7)',
        medium: 'rgba(245, 158, 11, 0.6)',
        low: 'rgba(239, 68, 68, 0.7)'
    };
    el.style.setProperty('--conf-color', confColorMap[plan.confidence] || confColorMap.medium);
    el.classList.remove('initially-hidden');
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
    { r: 2, emoji: '🔵', name: 'Ⅱ级', cn: '低配置区', range: '12.5-17%', pos: '70-85%', color: '#3b82f6' },
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

    panel.classList.remove('initially-hidden');

    // ── ECharts 半环仪表 ──
    const chartEl = document.getElementById('aiae-hub-gauge-chart');
    if (chartEl && typeof echarts !== 'undefined') {
        // V19.3: 销毁旧实例防止内存泄漏 (刷新按钮可能重复调用)
        const oldChart = echarts.getInstanceByDom(chartEl);
        if (oldChart) oldChart.dispose();
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
                    formatter: v => v % 5 === 0 ? v + '%' : ''  // V19.3: 5% 精度刻度
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

    // ── 五档状态条 (注入 CSS 变量驱动发光色) ──
    const strip = document.getElementById('aiae-hub-regime-strip');
    if (strip) {
        strip.innerHTML = _REGIME_DEFS.map(d => {
            const isActive = d.r === regime;
            const activeStyle = isActive
                ? `--regime-color:${d.color}40;--regime-rgb:${_hexToRgb(d.color)};background:rgba(255,255,255,0.04);border-color:${d.color}30;`
                : '';
            return `
            <div class="aiae-hub-regime-item${isActive ? ' active' : ''}" style="${activeStyle}">
                <div class="aiae-hub-ri-emoji">${d.emoji}</div>
                <div class="aiae-hub-ri-name" style="${isActive ? 'color:' + d.color : ''}">${d.name}</div>
                <div class="aiae-hub-ri-range">${d.range}</div>
                <div class="aiae-hub-ri-pos">仓位 ${d.pos}</div>
            </div>
        `;
        }).join('');
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

// ═══════════════════════════════════════════════════
//  V22.0: 信号时效衰减指示器
//  放射性衰变模型: reliability = 0.5^(age / half_life)
// ═══════════════════════════════════════════════════

function renderSignalDecay(decay) {
    const bars = document.getElementById('signal-decay-bars');
    const panel = document.getElementById('signal-decay');
    if (!bars || !decay) return;
    if (panel) panel.style.display = 'block';

    const engines = ['aiae', 'erp', 'vix', 'mr'];
    const getColor = (rel) => {
        if (rel >= 0.85) return '#34d399';
        if (rel >= 0.60) return '#a78bfa';
        if (rel >= 0.30) return '#fbbf24';
        return '#f87171';
    };
    const getLabel = (rel) => {
        if (rel >= 0.85) return '鲜';
        if (rel >= 0.60) return '可';
        if (rel >= 0.30) return '衰';
        return '旧';
    };

    bars.innerHTML = engines.map(key => {
        const d = decay[key];
        if (!d) return '';
        const rel = d.reliability;
        const pct = Math.max(2, Math.round(rel * 100));
        const color = getColor(rel);
        const label = getLabel(rel);
        const ageStr = d.age_min >= 0
            ? (d.age_min < 60 ? d.age_min + 'm' : (d.age_min / 60).toFixed(0) + 'h')
            : '—';
        return `
        <div class="sd-bar-row">
            <span class="sd-bar-engine">${d.label}</span>
            <div class="sd-bar-track">
                <div class="sd-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <span class="sd-bar-age" title="数据年龄">${ageStr}</span>
            <span class="sd-bar-badge" style="color:${color};border-color:${color}40">${label}</span>
        </div>`;
    }).join('');

    // 更新脚注
    const overallRel = Math.min(...engines.map(k => (decay[k] || {}).reliability || 0));
    let noteEl = document.getElementById('signal-decay-note');
    if (!noteEl) {
        noteEl = document.createElement('div');
        noteEl.id = 'signal-decay-note';
        noteEl.className = 'sd-footnote';
        bars.parentElement.appendChild(noteEl);
    }
    noteEl.textContent = overallRel < 0.6
        ? '⚠️ 部分引擎数据老化，JCS 可能偏离当前市场'
        : '可靠性 = 0.5^(年龄/半衰期) · 指数衰减模型';
}

// ═══════════════════════════════════════════════════
//  V22.0: 仓位调整路径渲染
// ═══════════════════════════════════════════════════

async function fetchPositionPath() {
    const card = document.getElementById('position-path-card');
    const body = document.getElementById('pp-body');
    if (!card || !body) return;

    card.classList.remove('initially-hidden');
    body.innerHTML = '<div class="loading-spinner">⏳ 生成执行路径...</div>';

    try {
        const resp = await fetch(`${API_BASE}/position-path`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderPositionPath(data);
        } else {
            body.innerHTML = `<div class="pp-empty">⚠️ ${data.error || '路径生成失败'}</div>`;
        }
    } catch (e) {
        body.innerHTML = '<div class="pp-empty">⚠️ 网络异常，请点击「刷新决策数据」重试</div>';
    }
}

function renderPositionPath(data) {
    const body = document.getElementById('pp-body');
    const badge = document.getElementById('pp-gap-badge');
    const footer = document.getElementById('pp-footer');
    if (!body) return;

    // Gap badge
    if (badge) {
        const dirIcon = data.direction === 'increase' ? '▲' : (data.direction === 'decrease' ? '▼' : '━');
        const dirColor = data.direction === 'increase' ? '#34d399' : (data.direction === 'decrease' ? '#f87171' : '#94a3b8');
        const gapSign = data.gap > 0 ? '+' : '';
        badge.innerHTML = `${dirIcon} <span style="color:${dirColor}">${gapSign}${data.gap}%</span>`;
        badge.title = `当前 ${data.current_cap}% → 目标 ${data.target_cap}%`;
    }

    // Warnings
    let warnHtml = '';
    if (data.warnings && data.warnings.length > 0) {
        warnHtml = `<div class="pp-warnings">${data.warnings.map(w => `<div class="pp-warn-item">${w}</div>`).join('')}</div>`;
    }

    // Data source indicator
    const srcLabel = data.data_source === 'portfolio' ? '🟢 基于实际持仓' : '🟡 基于策略信号';

    // Steps
    const stepColors = ['#a78bfa', '#3b82f6', '#34d399'];
    const stepIcons = ['🚀', '⚙️', '🎯'];
    const stepsHtml = data.steps.map((step, i) => {
        const hasActions = step.actions && step.actions.length > 0;
        const actionRows = hasActions ? step.actions.map(a => {
            const dirIcon = a.action === 'reduce' ? '🔻' : (a.action === 'increase' ? '🔺' : '━');
            const dirCls = a.action === 'reduce' ? 'pp-action-reduce' : (a.action === 'increase' ? 'pp-action-increase' : '');
            const deltaSign = a.delta > 0 ? '+' : '';
            const deltaColor = a.delta > 0 ? '#34d399' : '#f87171';
            return `
            <div class="pp-action-row ${dirCls}">
                <span class="pp-action-icon">${dirIcon}</span>
                <span class="pp-action-name">${a.name}<span class="pp-action-code">${a.code}</span></span>
                <span class="pp-action-weights">${a.current_weight}% → ${a.target_weight}%</span>
                <span class="pp-action-delta" style="color:${deltaColor}">${deltaSign}${a.delta}%</span>
                <span class="pp-action-reason">${a.reason}</span>
                ${a.execution_cost ? `
                <span class="pp-action-cost" title="冲击成本: ${a.execution_cost.impact_cost_pct}% · ${a.execution_cost.liquidity_grade}">
                    ~${a.execution_cost.impact_cost_value.toFixed(0)}元
                </span>` : ''}
            </div>`;
        }).join('') : '<div class="pp-action-row pp-no-action">━ 此步骤无需操作</div>';

        return `
        <div class="pp-step" style="border-left: 3px solid ${stepColors[i]}">
            <div class="pp-step-header">
                <span class="pp-step-icon">${stepIcons[i]}</span>
                <span class="pp-step-day">${step.day}</span>
                <span class="pp-step-note">${step.note}</span>
                <span class="pp-step-cap" style="color:${stepColors[i]}">→ ${step.step_cap}%</span>
            </div>
            <div class="pp-step-actions">${actionRows}</div>
        </div>`;
    }).join('');

    body.innerHTML = `${warnHtml}<div class="pp-steps">${stepsHtml}</div>`;

    if (footer) {
        footer.innerHTML = `<span class="pp-src">${srcLabel}</span><span class="pp-disclaimer">以上为系统生成建议，不构成投资指令</span>`;
    }
}
