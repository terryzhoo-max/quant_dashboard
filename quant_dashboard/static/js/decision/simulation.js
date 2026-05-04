/**
 * AlphaCore V21.2 · 模拟推演 + 时间线模块
 * ========================================
 * - 情景模拟 (runSimulation / renderSimResult)
 * - 决策时间线 (loadTimeline / renderTimelineChart / renderTimelineList)
 * - 重叠矩阵 / 行业集中度 / 尾部风险 / 回测精度
 *
 * 依赖: _getChart, _fmt, API_BASE (from _infra.js)
 */
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

    const chart = _getChart('timeline-chart');
    if (!chart) return;
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

    // V20.0: resize 由全局 _chartInstances handler 统一管理
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
            <span class="timeline-val">${_fmt(d.erp_score, 0, '-')}</span>
            <span class="timeline-val">${_fmt(d.vix_val, 1, '-')}</span>
            <span class="timeline-val" style="color:${mrC};font-weight:600;font-size:0.72rem">${mr}</span>
            <span class="timeline-val timeline-jcs" style="${jcsClass}">${_fmt(d.jcs_score, 1, '-')}</span>
            <span class="timeline-val">${d.suggested_position != null ? _fmt(d.suggested_position, 0) + '%' : '-'}</span>
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
        // V20.0: 复用缓存层, 消灭与 loadRiskGuardrail 的重复请求
        const [riskData, accResp] = await Promise.all([
            _fetchRiskMatrix(),
            AC.secureFetch(`${API_BASE}/accuracy`),
        ]);
        const accData = await accResp.json();

        if (riskData.status === 'success') {
            renderOverlapMatrix(riskData);
            renderSectorConcentration(riskData.sector_concentration, riskData.hhi, riskData.total_signals, riskData.data_source);
            renderTailRisk(riskData.tail_risk);
        }
        if (accData.status === 'success') renderAccuracy(accData);
        // V18.0 Phase L: 绩效分析 (独立请求, 不阻塞主流程)
        loadPerformanceAnalytics();
        // V21.1: 持仓相关性 + MCTR (独立请求, 不阻塞)
        loadCorrelationMatrix();
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

function renderSectorConcentration(sectors, hhi, totalSignals, dataSource) {
    const el = document.getElementById('sector-concentration');
    if (!el) return;
    if (!sectors || sectors.length === 0) {
        el.innerHTML = '<div style="text-align:center;padding:20px;color:#64748b;">暂无板块数据</div>';
        return;
    }
    const SECTOR_LIMIT = 40; // config.py sector_limit
    const colors = ['#a78bfa', '#34d399', '#fbbf24', '#38bdf8', '#fb923c', '#e879f9', '#94a3b8', '#6ee7b7'];
    const hhiLevel = (hhi || 0) > 2500 ? 'danger' : ((hhi || 0) > 1500 ? 'warn' : 'ok');
    const hhiLabel = hhiLevel === 'danger' ? '⚠️ 高集中' : (hhiLevel === 'warn' ? '🟡 中等' : '🟢 分散');
    const isPortfolio = dataSource === 'portfolio';
    const srcIcon = isPortfolio ? '🟢' : '🟡';
    const srcLabel = isPortfolio ? '实际持仓 (市值加权)' : '策略信号 (等权)';
    const countLabel = isPortfolio ? '持仓' : '信号';

    el.innerHTML = `
        <div class="sc-summary">
            <span class="sc-badge ${isPortfolio ? 'sc-badge-ok' : 'sc-badge-warn'}">${srcIcon} ${srcLabel}</span>
            <span class="sc-badge sc-badge-${hhiLevel}">HHI: ${hhi || '--'} ${hhiLabel}</span>
            <span class="sc-badge sc-badge-count">${totalSignals || '--'} ${countLabel}</span>
            <span class="sc-badge sc-badge-limit">红线: ${SECTOR_LIMIT}%</span>
        </div>
        ${sectors.map((s, i) => {
            const over = s.pct > SECTOR_LIMIT;
            const barColor = over ? '#f87171' : colors[i % colors.length];
            // 持仓模式: 来源已在顶部标明, 不重复; 信号模式: 显示策略来源
            const srcHtml = (!isPortfolio && s.sources) ? s.sources.map(src => `<span class="sc-src-pill">${src}</span>`).join('') : '';
            return `<div class="sector-bar-row ${over ? 'sc-over' : ''}">
                <span class="sector-bar-name">${s.sector}</span>
                <div class="sector-bar-bg">
                    <div class="sector-bar-fill" style="width:${s.pct}%;background:${barColor}"></div>
                    <div class="sc-redline" style="left:${SECTOR_LIMIT}%"></div>
                </div>
                <span class="sector-bar-pct ${over ? 'sc-pct-over' : ''}">${s.pct}%${over ? ' ⚠️' : ''}</span>
            </div>${srcHtml ? `<div class="sc-src-row">${srcHtml}</div>` : ''}`;
        }).join('')}`;
}

function renderTailRisk(tail) {
    const el = document.getElementById('tail-risk');
    if (!el) return;
    const comps = tail.components;
    const cColors = { concentration: '#a78bfa', vix: '#fbbf24', aiae: '#f97316', conflict: '#f87171' };
    const cLabels = { concentration: '集中', vix: 'VIX', aiae: 'AIAE', conflict: '矛盾' };
    const cWeights = { concentration: '30%', vix: '20%', aiae: '35%', conflict: '15%' };
    const lvlColor = tail.level === 'high' ? '#f87171' : (tail.level === 'medium' ? '#fbbf24' : '#34d399');
    el.innerHTML = `
        <div class="tail-risk-wrap">
            <div class="tail-gauge-container"><canvas id="tail-gauge-canvas"></canvas>
                <div class="tail-gauge-value ${tail.level}">${tail.score.toFixed(1)}</div>
            </div>
            <div class="tail-risk-label" style="color:${lvlColor}">${tail.label}</div>
            <div class="tail-risk-bars">
                ${Object.entries(comps).map(([k, v]) => `<div class="tail-bar-row"><span class="tail-bar-name">${cLabels[k]}<span class="tail-bar-weight">${cWeights[k]}</span></span><div class="tail-bar-bg"><div class="tail-bar-fill" style="width:${v}%;background:${cColors[k]}"></div></div><span class="tail-bar-val">${v.toFixed(0)}</span></div>`).join('')}
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
    ctx.setTransform(1, 0, 0, 1, 0, 0);  // V19.3: DPR 重置
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
        <div style="text-align:center;padding:12px 0 0;color:#64748b;font-size:0.78rem;">📊 系统正在积累信号准确率数据 (T+5)...</div>
        <div style="text-align:center;padding:6px 0 0;color:#475569;font-size:0.68rem;line-height:1.6;">
            准确率 = T+5日沦深300收益率方向 vs JCS信号方向<br>
            · JCS ≥ 50 + 市场上涨 → ✅ 正确 &nbsp;· JCS < 50 + 市场下跌 → ✅ 正确<br>
            · 反向则记为 ❌。连续跑分 15 日后开始显示数据。
        </div>`;
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

// V20.0: key-based guard 替代 boolean, 修复切换月份后回到 Tab4 不加载的 bug
let _calendarLoadedKey = '';
let calendarYear, calendarMonth;

async function loadCalendar() {
    const now = new Date();
    if (!calendarYear) { calendarYear = now.getFullYear(); calendarMonth = now.getMonth() + 1; }
    const key = `${calendarYear}-${calendarMonth}`;
    if (key === _calendarLoadedKey) return;
    try {
        const resp = await AC.secureFetch(`${API_BASE}/calendar?year=${calendarYear}&month=${calendarMonth}`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderCalendar(data.data, calendarYear, calendarMonth);
            _calendarLoadedKey = key;
        }
    } catch (e) { console.error('Calendar load error:', e); }
}

