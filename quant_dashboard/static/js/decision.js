/**
 * AlphaCore V16.0 · 决策中枢 JS
 * ================================
 * - JCS 环形仪表盘 (Canvas)
 * - 矛盾矩阵渲染
 * - 情景模拟器交互
 * - 决策时间线图 (ECharts)
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
        panel.innerHTML = `<div class="no-conflict-badge"><span class="pulse-dot"></span> 所有引擎信号对齐，无矛盾</div>
        <div class="pair-list">
            <div class="pair-item"><span class="pair-check">✓</span><span class="pair-engines">AIAE ↔ ERP</span> 方向一致</div>
            <div class="pair-item"><span class="pair-check">✓</span><span class="pair-engines">VIX ↔ MR</span> 方向一致</div>
            <div class="pair-item"><span class="pair-check">✓</span><span class="pair-engines">ERP ↔ VIX</span> 方向一致</div>
            <div class="pair-item"><span class="pair-check">✓</span><span class="pair-engines">AIAE ↔ MR</span> 方向一致</div>
        </div>`;
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

function renderDirections(directions) {
    const grid = document.getElementById('direction-grid');
    if (!grid) return;

    const labels = { aiae: 'AIAE', erp: 'ERP', vix: 'VIX', mr: 'MR' };
    const arrows = { '1': '▲', '-1': '▼', '0': '━' };
    const cls = { '1': 'up', '-1': 'down', '0': 'neutral' };

    grid.innerHTML = Object.entries(directions).map(([key, dir]) => `
        <div class="direction-item">
            <div class="direction-label">${labels[key] || key}</div>
            <div class="direction-arrow ${cls[String(dir)] || 'neutral'}">${arrows[String(dir)] || '●'}</div>
        </div>
    `).join('');
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

async function runSimulation(scenarioId) {
    // 高亮选中卡片
    document.querySelectorAll('.scenario-card').forEach(c => c.classList.remove('active'));
    const card = document.querySelector(`.scenario-card[data-id="${scenarioId}"]`);
    if (card) card.classList.add('active');

    const resultEl = document.getElementById('sim-result');
    if (resultEl) { resultEl.classList.remove('visible'); resultEl.innerHTML = '<div class="loading-spinner">⏳ 模拟推演中...</div>'; resultEl.classList.add('visible'); }

    try {
        const resp = await fetch(`${API_BASE}/simulate`, {
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
        if (resultEl) resultEl.innerHTML = `<div class="loading-spinner">❌ 网络错误: ${e.message}</div>`;
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
        const resp = await fetch(`${API_BASE}/history?days=30`);
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
        <span style="text-align:center">VIX</span><span style="text-align:center">JCS</span>
        <span style="text-align:center">仓位</span><span style="text-align:center">矛盾</span>
    </div>`;

    const rows = data.slice().reverse().slice(0, 15).map(d => {
        const jcsClass = d.jcs_level === 'high' ? 'color:#34d399' : (d.jcs_level === 'low' ? 'color:#f87171' : 'color:#fbbf24');
        return `<div class="timeline-item">
            <span class="timeline-date">${(d.date || '').slice(5)}</span>
            <span class="timeline-val">R${d.aiae_regime ?? '-'}</span>
            <span class="timeline-val">${d.erp_score != null ? d.erp_score.toFixed(0) : '-'}</span>
            <span class="timeline-val">${d.vix_val != null ? d.vix_val.toFixed(1) : '-'}</span>
            <span class="timeline-val timeline-jcs" style="${jcsClass}">${d.jcs_score != null ? d.jcs_score.toFixed(1) : '-'}</span>
            <span class="timeline-val">${d.suggested_position != null ? d.suggested_position.toFixed(0) + '%' : '-'}</span>
            <span class="timeline-val">${d.conflict_count || 0}</span>
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
            fetch(`${API_BASE}/risk-matrix`),
            fetch(`${API_BASE}/accuracy`),
        ]);
        const riskData = await riskResp.json();
        const accData = await accResp.json();

        if (riskData.status === 'success') {
            renderOverlapMatrix(riskData);
            renderSectorConcentration(riskData.sector_concentration);
            renderTailRisk(riskData.tail_risk);
        }
        if (accData.status === 'success') renderAccuracy(accData);
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
        const resp = await fetch(`${API_BASE}/calendar?year=${calendarYear}&month=${calendarMonth}`);
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
                <div class="calendar-tooltip">JCS: ${jcsStr} | 仓位: ${pos}<br>AIAE: R${entry.aiae_regime||'-'} | 矛盾: ${entry.conflict_count||0}${ci?'<br>信号: '+ci:''}</div>
            </div>`;
        } else {
            html += `<div class="calendar-day no-data"><span class="day-num" style="color:#334155">${d}</span></div>`;
        }
    }
    el.innerHTML = html;
}

// ═══════════════════════════════════════════════════
//  页面初始化
// ═══════════════════════════════════════════════════

async function initDecisionHub() {
    initTabs();

    try {
        const resp = await fetch(`${API_BASE}/hub`);
        const data = await resp.json();

        if (data.status === 'success') {
            // JCS
            drawJCSRing(data.jcs.score, data.jcs.level);
            const labelEl = document.getElementById('jcs-label');
            if (labelEl) labelEl.textContent = data.jcs.label;

            // 矛盾
            renderConflicts(data.conflicts);

            // 方向
            renderDirections(data.jcs.directions);

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

// 启动
document.addEventListener('DOMContentLoaded', initDecisionHub);
