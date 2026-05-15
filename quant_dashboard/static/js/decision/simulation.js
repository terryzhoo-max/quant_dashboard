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
        if (!window.AC_READY || typeof AC.secureFetch !== 'function') {
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

    // V23.0: 统一 JCS 取值 (shock_bridge 模式 vs delta 模式)
    const jcsBefore = data.jcs_before ? data.jcs_before.score : (b.jcs ?? '--');
    const jcsAfter = data.jcs_after ? data.jcs_after.score : (a.jcs ?? '--');
    const jcsDelta = (typeof jcsBefore === 'number' && typeof jcsAfter === 'number') ? jcsAfter - jcsBefore : null;

    const _delta = (bv, av, suffix = '') => {
        if (bv == null || av == null || bv === '--' || av === '--') return '';
        const d = typeof av === 'number' ? (av - bv) : 0;
        if (d === 0) return '';
        const sign = d > 0 ? '+' : '';
        const color = d > 0 ? '#34d399' : '#f87171';
        return `<span style="font-size:0.7rem;color:${color};margin-left:4px;">${sign}${typeof d === 'number' ? d.toFixed(1) : d}${suffix}</span>`;
    };

    const metrics = [
        ['AIAE 档位', b.aiae_regime ?? '--', a.aiae_regime ?? '--'],
        ['ERP 估值', (b.erp_val ?? '--') + '%', (a.erp_val ?? '--') + '%'],
        ['ERP 评分', b.erp_score ?? '--', a.erp_score ?? '--'],
        ['VIX', b.vix_val ?? '--', a.vix_val ?? '--'],
        ['建议仓位', (b.suggested_position ?? '--') + '%', (a.suggested_position ?? '--') + '%'],
    ];

    // 仓位 delta 色温
    const posDelta = (a.suggested_position ?? 0) - (b.suggested_position ?? 0);
    const posDeltaColor = posDelta > 0 ? '#34d399' : (posDelta < 0 ? '#f87171' : '#94a3b8');
    const posDeltaText = posDelta !== 0 ? `${posDelta > 0 ? '↑' : '↓'}${Math.abs(posDelta)}%` : '━';

    // V23.0: 传播路径 (shock_bridge 模式)
    const prop = data.propagation;
    let propHtml = '';
    if (prop && prop.propagation_path && prop.propagation_path.length > 1) {
        const topNodes = prop.propagation_path
            .filter(p => p.step > 0)
            .sort((a, b) => Math.abs(b.shock_value) - Math.abs(a.shock_value))
            .slice(0, 5);
        propHtml = `
        <div class="sim-propagation">
            <div class="sim-propagation-title">🔗 因果传播链</div>
            <div class="sim-propagation-flow">
                <span class="sim-prop-node sim-prop-source">🎯 ${prop.source_label || prop.source}</span>
                ${topNodes.map(p => {
                    const dir = p.shock_value > 0 ? '↑' : '↓';
                    const color = p.shock_value > 0 ? '#f87171' : '#60a5fa';
                    return `<span class="sim-prop-arrow">→</span>
                    <span class="sim-prop-node">
                        <span class="sim-prop-name">${p.node}</span>
                        <span class="sim-prop-val" style="color:${color}">${dir}${Math.abs(p.shock_value).toFixed(1)}σ</span>
                    </span>`;
                }).join('')}
            </div>
            <div class="sim-propagation-summary">${prop.summary || ''}</div>
        </div>`;
    }

    el.innerHTML = `
        <div class="sim-compare">
            <div class="sim-col before">
                <div class="sim-col-title">📍 当前状态</div>
                ${metrics.map(m => `<div class="sim-metric"><span class="sim-metric-name">${m[0]}</span><span class="sim-metric-val">${m[1]}</span></div>`).join('')}
                <div class="sim-metric sim-metric-jcs"><span class="sim-metric-name">JCS</span><span class="sim-metric-val">${jcsBefore}</span></div>
            </div>
            <div class="sim-arrow-col">
                <div class="sim-arrow">→</div>
                <div class="sim-pos-delta" style="color:${posDeltaColor};font-size:1.2rem;font-weight:800;">${posDeltaText}</div>
                ${jcsDelta !== null ? `<div class="sim-jcs-delta" style="color:${jcsDelta > 0 ? '#34d399' : (jcsDelta < 0 ? '#f87171' : '#94a3b8')};font-size:0.82rem;font-weight:600;">JCS ${jcsDelta > 0 ? '+' : ''}${jcsDelta.toFixed(0)}</div>` : ''}
            </div>
            <div class="sim-col after">
                <div class="sim-col-title">🔮 ${data.scenario.name}</div>
                ${metrics.map((m, i) => {
                    const bv = [b.aiae_regime, b.erp_val, b.erp_score, b.vix_val, b.suggested_position][i];
                    const av = [a.aiae_regime, a.erp_val, a.erp_score, a.vix_val, a.suggested_position][i];
                    const dHtml = _delta(bv, av, i === 1 || i === 4 ? '%' : '');
                    return `<div class="sim-metric"><span class="sim-metric-name">${m[0]}</span><span class="sim-metric-val">${m[2]}${dHtml}</span></div>`;
                }).join('')}
                <div class="sim-metric sim-metric-jcs"><span class="sim-metric-name">JCS</span><span class="sim-metric-val">${jcsAfter}${_delta(jcsBefore, jcsAfter)}</span></div>
            </div>
        </div>
        ${propHtml}
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

/** V25.1: 时间戳 guard (5分钟内不重复加载, 超时后允许刷新) */
let _riskLoadedAt = 0;
const _RISK_GUARD_TTL = 300000; // 5 min

async function loadRiskMatrix() {
    // P3-C: 准确率仪表板独立于 riskMatrix guard, 始终尝试加载
    loadAccuracyDashboard();
    if (_riskLoadedAt && (Date.now() - _riskLoadedAt) < _RISK_GUARD_TTL) return;
    try {
        // V25.1: 强制清除前端缓存以获取最新 SWR 数据
        window._riskMatrixCache = null;
        window._riskMatrixCacheTs = 0;
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
        loadPerformanceAnalytics();
        loadCorrelationMatrix();
        loadDriftStatus();
        _riskLoadedAt = Date.now();
    } catch (e) {
        console.error('Risk matrix load error:', e);
    }
}

/** V25.1: 供刷新按钮调用 — 重置所有 Risk Tab guard */
function resetRiskTabGuards() {
    _riskLoadedAt = 0;
    _corrLoadedAt = 0;
    perfLoaded = false;
}

async function loadDriftStatus() {
    const card = document.getElementById('drift-card');
    const grid = document.getElementById('drift-grid');
    if (!card || !grid) return;

    card.classList.remove('initially-hidden');
    try {
        const resp = await fetch(`${API_BASE}/drift-status`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderDriftStatus(data);
        } else {
            grid.innerHTML = '<div style="text-align:center;padding:12px;color:#64748b;">漂移数据不可用</div>';
        }
    } catch (e) {
        grid.innerHTML = '<div style="text-align:center;padding:12px;color:#64748b;">加载异常</div>';
    }
}

function renderDriftStatus(data) {
    const badge = document.getElementById('drift-status-badge');
    const grid = document.getElementById('drift-grid');
    if (!grid) return;

    // V25.2: drift_level 是漂移状态 (ok/warning/critical), status 是 API 状态
    const level = data.drift_level || 'ok';
    if (badge) {
        const statusIcons = { ok: '🟢', warning: '🟡', critical: '🔴' };
        badge.textContent = (statusIcons[level] || '') + ' ' + (data.summary || '检测中');
        badge.className = 'drift-status-badge ' + level;
    }

    const checks = data.checks || {};
    const checkOrder = ['accuracy', 'regime_shift', 'jcs_trend', 'conflict_trend'];
    const checkLabels = { accuracy: '准确率漂移', regime_shift: '环境偏移', jcs_trend: 'JCS 趋势', conflict_trend: '矛盾趋势' };
    const statusColors = { ok: '#34d399', warning: '#fbbf24', critical: '#f87171', insufficient_data: '#64748b', info: '#60a5fa' };

    grid.innerHTML = checkOrder.map(key => {
        const c = checks[key];
        if (!c) return '';
        const color = statusColors[c.status] || '#64748b';
        return `
        <div class="drift-item">
            <div class="drift-item-header">
                <span class="drift-item-dot" style="background:${color}"></span>
                <span class="drift-item-name">${checkLabels[key]}</span>
                <span class="drift-item-label" style="color:${color}">${c.label || '--'}</span>
            </div>
            <div class="drift-item-detail">${c.detail || ''}</div>
        </div>`;
    }).join('');
}

function renderOverlapMatrix(data) {
    const el = document.getElementById('overlap-matrix');
    if (!el) return;
    const names = data.strategy_names;
    // V25.1: 空态引导 UI
    if (names.length === 0) {
        el.innerHTML = `<div style="text-align:center;padding:32px 20px;">
            <div style="font-size:2rem;margin-bottom:8px;">📭</div>
            <div style="color:#94a3b8;font-size:0.82rem;margin-bottom:6px;">暂无策略信号数据</div>
            <div style="color:#64748b;font-size:0.7rem;line-height:1.6;">策略引擎尚未生成买入信号。<br>请前往「策略中心」运行至少一个策略后刷新。</div>
        </div>`;
        return;
    }
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
    const SECTOR_LIMIT = 40;
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
        <div class="sc-dual-view">
            <div id="sc-pie-chart" style="width:180px;height:180px;flex-shrink:0;"></div>
            <div class="sc-bars-col">
                ${sectors.map((s, i) => {
                    const over = s.pct > SECTOR_LIMIT;
                    const barColor = over ? '#f87171' : colors[i % colors.length];
                    const srcHtml = (!isPortfolio && s.sources) ? s.sources.map(src => `<span class="sc-src-pill">${src}</span>`).join('') : '';
                    return `<div class="sector-bar-row ${over ? 'sc-over' : ''}">
                        <span class="sector-bar-name">${s.sector}</span>
                        <div class="sector-bar-bg">
                            <div class="sector-bar-fill" style="width:${s.pct}%;background:${barColor}"></div>
                            <div class="sc-redline" style="left:${SECTOR_LIMIT}%"></div>
                        </div>
                        <span class="sector-bar-pct ${over ? 'sc-pct-over' : ''}">${s.pct}%${over ? ' ⚠️' : ''}</span>
                    </div>${srcHtml ? `<div class="sc-src-row">${srcHtml}</div>` : ''}`;
                }).join('')}
            </div>
        </div>`;
    // V25.1: ECharts 环形饼图
    setTimeout(() => {
        const chart = _getChart('sc-pie-chart');
        if (!chart) return;
        chart.setOption({
            tooltip: { formatter: p => `${p.name}<br/><b>${p.value}%</b>` },
            series: [{
                type: 'pie', radius: ['45%', '72%'], center: ['50%', '50%'],
                data: sectors.map((s, i) => ({ name: s.sector, value: s.pct, itemStyle: { color: s.pct > SECTOR_LIMIT ? '#f87171' : colors[i % colors.length] } })),
                label: { show: false },
                emphasis: { label: { show: true, fontSize: 11, color: '#e2e8f0' }, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
                itemStyle: { borderColor: '#1e2235', borderWidth: 2, borderRadius: 4 },
            }]
        });
    }, 60);
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
            <div id="tail-gauge-chart" style="width:100%;height:180px;"></div>
            <div class="tail-risk-label" style="color:${lvlColor}">${tail.label}</div>
            <div class="tail-risk-bars">
                ${Object.entries(comps).map(([k, v]) => `<div class="tail-bar-row"><span class="tail-bar-name">${cLabels[k]}<span class="tail-bar-weight">${cWeights[k]}</span></span><div class="tail-bar-bg"><div class="tail-bar-fill" style="width:${v}%;background:${cColors[k]}"></div></div><span class="tail-bar-val">${v.toFixed(0)}</span></div>`).join('')}
            </div>
        </div>`;
    // V25.1: ECharts Gauge 替换 Canvas (自动 resize + tooltip)
    setTimeout(() => _drawTailGaugeECharts(tail.score, tail.level), 60);
}

function _drawTailGaugeECharts(score, level) {
    const chart = _getChart('tail-gauge-chart');
    if (!chart) return;
    const gaugeColor = score >= 70 ? '#f87171' : (score >= 40 ? '#fbbf24' : '#34d399');
    chart.setOption({
        series: [{
            type: 'gauge', startAngle: 180, endAngle: 0,
            min: 0, max: 100, splitNumber: 5,
            radius: '95%', center: ['50%', '80%'],
            axisLine: {
                lineStyle: {
                    width: 16, color: [
                        [0.3, '#34d399'], [0.6, '#fbbf24'], [1, '#f87171']
                    ]
                }
            },
            axisTick: { length: 4, lineStyle: { color: 'rgba(148,163,184,0.2)', width: 1 } },
            splitLine: { length: 10, lineStyle: { color: 'rgba(148,163,184,0.15)', width: 1 } },
            axisLabel: { distance: 18, color: '#64748b', fontSize: 10 },
            pointer: {
                length: '65%', width: 5, offsetCenter: [0, 0],
                itemStyle: { color: gaugeColor, shadowColor: gaugeColor, shadowBlur: 8 }
            },
            anchor: { show: true, size: 10, itemStyle: { color: gaugeColor, borderWidth: 2, borderColor: '#1e2235' } },
            detail: {
                valueAnimation: true, fontSize: 28, fontWeight: 700,
                color: gaugeColor, offsetCenter: [0, '-15%'],
                formatter: v => v.toFixed(1)
            },
            title: { show: false },
            data: [{ value: score }],
            animationDuration: 800, animationEasingUpdate: 'cubicOut',
        }]
    });
}

function renderAccuracy(data) {
    const el = document.getElementById('accuracy-panel');
    if (!el) return;
    if (!data.has_data) {
        el.innerHTML = `<div class="acc-empty-state">
            <div class="acc-empty-icon">📊</div>
            <div class="acc-empty-title">信号准确率追踪 · 冷启动中</div>
            <div class="acc-empty-desc">
                系统尚无可评估的决策记录。<br>
                JCS 信号将在 T+5 日后自动回填市场收益率并计算准确率。
            </div>
        </div>`;
        return;
    }
    // V25.2: 连胜/连败 badge
    const streakIcon = data.streak_type === 'win' ? '🔥' : (data.streak_type === 'lose' ? '❄️' : '');
    const streakClass = data.streak_type === 'win' ? 'acc-streak-win' : 'acc-streak-lose';
    const streakText = data.current_streak > 0
        ? `${streakIcon} ${data.streak_type === 'win' ? '连胜' : '连败'} ${data.current_streak}`
        : '';
    // V25.2: maturity badge
    const matLabel = data.maturity === 'mature' ? '📈 成熟期'
        : (data.maturity === 'growing' ? '🌱 成长期' : '🧪 初始期');
    const matClass = `acc-mat-${data.maturity || 'initial'}`;
    // 准确率颜色
    const accPct = data.accuracy_pct || 0;
    const accColor = accPct >= 65 ? '#34d399' : (accPct >= 50 ? '#a78bfa' : '#fbbf24');
    el.innerHTML = `
        <div class="acc-header-bar">
            <span class="acc-badge ${matClass}">${matLabel} · ${data.total_decisions} 次评估</span>
            ${streakText ? `<span class="acc-badge ${streakClass}">${streakText}</span>` : ''}
        </div>
        <div class="accuracy-grid">
            <div class="accuracy-metric">
                <div class="accuracy-value" style="color:${accColor}">${data.accuracy_pct != null ? data.accuracy_pct + '%' : '--'}</div>
                <div class="accuracy-label">总体准确率</div>
            </div>
            <div class="accuracy-metric">
                <div class="accuracy-value" style="color:#a78bfa">${data.recent_10_accuracy != null ? data.recent_10_accuracy + '%' : '--'}</div>
                <div class="accuracy-label">近10次准确率</div>
            </div>
            <div class="accuracy-metric">
                <div class="accuracy-value" style="color:#38bdf8">${data.correct_decisions}<span style="font-size:0.9rem;color:#64748b">/${data.total_decisions}</span></div>
                <div class="accuracy-label">正确/总计</div>
            </div>
        </div>
        ${(data.history && data.history.length >= 3) ? '<div id="acc-trend-chart" style="width:100%;height:160px;margin-top:12px;"></div>' : ''}
        <div class="acc-history-dots">${_renderAccDots(data.history)}</div>
    `;
    // V25.2: ECharts 趋势图
    if (data.history && data.history.length >= 3) {
        setTimeout(() => _drawAccTrendChart(data.history), 80);
    }
}

function _renderAccDots(history) {
    if (!history || history.length === 0) return '';
    return '<div class="acc-dots-row">' + history.map(h => {
        const icon = h.correct === 1 ? '✅' : '❌';
        const ret = h.ret5d != null ? (h.ret5d * 100).toFixed(2) + '%' : '--';
        return `<span class="acc-dot ${h.correct === 1 ? 'acc-dot-ok' : 'acc-dot-fail'}"
                      title="${h.date} | JCS:${h.jcs || '--'} | Ret5d:${ret} | ${h.correct === 1 ? '正确' : '错误'}">${icon}</span>`;
    }).join('') + '</div>';
}

function _drawAccTrendChart(history) {
    const chart = _getChart('acc-trend-chart');
    if (!chart) return;
    const dates = history.map(h => h.date ? h.date.slice(5) : '');
    // 滚动准确率 (累积)
    let cumCorrect = 0;
    const rollingAcc = history.map((h, i) => {
        cumCorrect += (h.correct === 1 ? 1 : 0);
        return Math.round(cumCorrect / (i + 1) * 100);
    });
    // T+5 收益率
    const returns = history.map(h => h.ret5d != null ? +(h.ret5d * 100).toFixed(2) : null);
    chart.setOption({
        grid: { top: 30, right: 50, bottom: 24, left: 45 },
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.9)',
            borderColor: 'rgba(255,255,255,0.08)',
            textStyle: { color: '#e2e8f0', fontSize: 12 },
            formatter: params => {
                let s = `<b>${params[0].axisValue}</b><br/>`;
                params.forEach(p => {
                    s += `${p.marker} ${p.seriesName}: <b>${p.value != null ? p.value + (p.seriesIndex === 0 ? '%' : '%') : '--'}</b><br/>`;
                });
                return s;
            }
        },
        legend: {
            data: ['累积准确率', 'T+5收益'],
            textStyle: { color: '#94a3b8', fontSize: 10 },
            top: 0, right: 0
        },
        xAxis: {
            type: 'category', data: dates, boundaryGap: false,
            axisLine: { lineStyle: { color: 'rgba(148,163,184,0.1)' } },
            axisLabel: { color: '#64748b', fontSize: 9 }
        },
        yAxis: [
            {
                type: 'value', name: '准确率%', position: 'left',
                splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } },
                axisLabel: { color: '#64748b', fontSize: 9 },
                nameTextStyle: { color: '#64748b', fontSize: 9 }
            },
            {
                type: 'value', name: '收益%', position: 'right',
                splitLine: { show: false },
                axisLabel: { color: '#64748b', fontSize: 9 },
                nameTextStyle: { color: '#64748b', fontSize: 9 }
            }
        ],
        series: [
            {
                name: '累积准确率', type: 'line', data: rollingAcc, yAxisIndex: 0,
                smooth: true, symbol: 'circle', symbolSize: 4,
                lineStyle: { width: 2, color: '#34d399' },
                itemStyle: { color: '#34d399' },
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(52,211,153,0.25)' },
                            { offset: 1, color: 'rgba(52,211,153,0.02)' }
                        ]
                    }
                },
                markLine: {
                    silent: true, symbol: 'none',
                    data: [{ yAxis: 50, lineStyle: { color: '#fbbf24', type: 'dashed', width: 1 } }],
                    label: { show: true, formatter: '50%', color: '#fbbf24', fontSize: 9 }
                }
            },
            {
                name: 'T+5收益', type: 'bar', data: returns, yAxisIndex: 1,
                barWidth: 6, barGap: '-100%',
                itemStyle: {
                    color: (params) => (params.value || 0) >= 0 ? 'rgba(52,211,153,0.5)' : 'rgba(248,113,113,0.5)',
                    borderRadius: [2, 2, 0, 0]
                }
            }
        ],
        animationDuration: 600
    });
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

// ═══════════════════════════════════════════════════
//  P3-C: 准确率分析仪表板
// ═══════════════════════════════════════════════════

let _accDashData = null;
let _accDashLoaded = false;

async function loadAccuracyDashboard() {
    if (_accDashLoaded) return;
    const el = document.getElementById('acc-dash-content');
    try {
        const resp = await fetch(`${API_BASE}/accuracy-dashboard?window=60`);
        _accDashData = await resp.json();
        if (_accDashData.status === 'success') {
            renderAccDashJCS(_accDashData.by_jcs_level);
            _accDashLoaded = true;
        } else {
            if (el) el.innerHTML = '<div style="text-align:center;padding:16px;color:#64748b">暂无数据</div>';
        }
    } catch (e) {
        console.error('Accuracy dashboard load error:', e);
        if (el) el.innerHTML = `<div style="text-align:center;padding:16px;color:#f87171">加载异常: ${e.message}</div>`;
    }
}

function switchAccTab(tab, btnEl) {
    document.querySelectorAll('.acc-tab').forEach(t => t.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    if (!_accDashData) { loadAccuracyDashboard(); return; }
    if (tab === 'jcs') renderAccDashJCS(_accDashData.by_jcs_level);
    else if (tab === 'regime') renderAccDashRegime(_accDashData.by_regime);
    else if (tab === 'shadow') renderAccDashShadow(_accDashData.shadow);
}

function renderAccDashJCS(data) {
    const el = document.getElementById('acc-dash-content');
    if (!el || !data) return;
    const levels = [
        { key: 'high', label: '🟢 高置信', color: '#34d399' },
        { key: 'medium', label: '🟡 中置信', color: '#fbbf24' },
        { key: 'low', label: '🔴 低置信', color: '#f87171' },
    ];
    el.innerHTML = `<div class="acc-dash-grid">${levels.map(l => {
        const d = data[l.key] || { total: 0, correct: 0, accuracy: null };
        const pct = d.accuracy != null ? d.accuracy : 0;
        return `<div class="acc-dash-row">
            <div class="acc-dash-label">${l.label}</div>
            <div class="acc-dash-bar-bg"><div class="acc-dash-bar" style="width:${Math.max(pct, 2)}%;background:${l.color}"></div><span class="acc-dash-bar-pct">${d.accuracy != null ? d.accuracy + '%' : '--'}</span></div>
            <div class="acc-dash-count">${d.correct}/${d.total}</div>
        </div>`;
    }).join('')}</div><div class="acc-dash-insight">${_getJCSInsight(data)}</div>`;
}

function _getJCSInsight(data) {
    const h = data.high || {}, m = data.medium || {}, l = data.low || {};
    if (!h.total && !m.total && !l.total) return '<span style="color:#64748b">暂无足够数据生成分析</span>';
    const best = [
        { key: '高置信', acc: h.accuracy, total: h.total },
        { key: '中置信', acc: m.accuracy, total: m.total },
        { key: '低置信', acc: l.accuracy, total: l.total },
    ].filter(x => x.total >= 3).sort((a, b) => (b.acc || 0) - (a.acc || 0));
    if (best.length === 0) return '<span style="color:#64748b">各级别样本不足，继续积累数据</span>';
    return `💡 <strong>${best[0].key}</strong>信号准确率最高 (${best[0].acc}%), 建议在此级别下增加执行力度`;
}

function renderAccDashRegime(data) {
    const el = document.getElementById('acc-dash-content');
    if (!el || !data) return;
    const regimes = ['1', '2', '3', '4', '5'];
    const colors = { '1': '#34d399', '2': '#6ee7b7', '3': '#94a3b8', '4': '#fbbf24', '5': '#f87171' };
    el.innerHTML = `<div class="acc-dash-grid">${regimes.map(r => {
        const d = data[r] || { label: 'R' + r, total: 0, accuracy: null, correct: 0 };
        const pct = d.accuracy != null ? d.accuracy : 0;
        return `<div class="acc-dash-row">
            <div class="acc-dash-label">${d.label}</div>
            <div class="acc-dash-bar-bg"><div class="acc-dash-bar" style="width:${Math.max(pct, 2)}%;background:${colors[r]}"></div><span class="acc-dash-bar-pct">${d.accuracy != null ? d.accuracy + '%' : '--'}</span></div>
            <div class="acc-dash-count">${d.correct}/${d.total}</div>
        </div>`;
    }).join('')}</div><div class="acc-dash-insight">💡 不同市场 Regime 下信号准确率差异揭示系统的适应性边界</div>`;
}

function renderAccDashShadow(data) {
    const el = document.getElementById('acc-dash-content');
    if (!el) return;
    if (!data || !data.has_data) {
        el.innerHTML = `<div class="acc-dash-empty"><div style="font-size:2rem;margin-bottom:8px">🔬</div><div style="color:#94a3b8">影子模式数据积累中</div><div style="color:#64748b;font-size:0.78rem;margin-top:4px">V4/V6 对比需要至少 5 个交易日的影子数据。<br>系统已启动并行计算, 数据将自动积累。</div></div>`;
        return;
    }
    const betterIcon = data.v6_better ? '✅' : '⏳';
    el.innerHTML = `
        <div class="shadow-compare">
            <div class="shadow-metric"><div class="shadow-value" style="color:#a78bfa">${data.v4_accuracy != null ? data.v4_accuracy + '%' : '--'}</div><div class="shadow-label">V4 (4维) 准确率</div></div>
            <div class="shadow-vs">VS</div>
            <div class="shadow-metric"><div class="shadow-value" style="color:#38bdf8">${data.v6_accuracy != null ? data.v6_accuracy + '%' : '--'}</div><div class="shadow-label">V6 (6维) 准确率</div></div>
        </div>
        <div class="shadow-details">
            <div class="shadow-detail-row"><span>样本量</span><span>${data.total} 天</span></div>
            <div class="shadow-detail-row"><span>平均 Delta</span><span style="color:${data.avg_delta > 0 ? '#34d399' : '#f87171'}">${data.avg_delta > 0 ? '+' : ''}${data.avg_delta}</span></div>
            <div class="shadow-detail-row"><span>结论</span><span>${betterIcon} ${data.recommendation}</span></div>
        </div>`;
}
