/**
 * AlphaCore V21.2 · 全球分析 + 日历模块
 * ======================================
 * - JCS 日历 (renderCalendar / changeMonth)
 * - JCS 成分拆解 (renderJCSComponents)
 * - 全球市场温度仪表板 (renderGlobalTemperature)
 * - 尾部风险简报 (renderTailRiskBrief)
 * - SOP 折叠 (initSOPToggle)
 * - 阈值速查表高亮 (highlightThresholdTable)
 *
 * 依赖: _getChart, _fmt, API_BASE (from _infra.js)
 */
function changeMonth(delta) {
    calendarMonth += delta;
    if (calendarMonth > 12) { calendarMonth = 1; calendarYear++; }
    if (calendarMonth < 1) { calendarMonth = 12; calendarYear--; }
    // V20.0: key-based guard 自动检测月份变化, 无需手动重置
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
            const jcsStr = _fmt(jcs, 1, '50.0');
            const c = jcsToColor(jcs);
            const varColor = `${c.r}, ${c.g}, ${c.b}`;
            const fg = `rgb(${varColor})`;
            const pos = entry.suggested_position != null ? entry.suggested_position + '%' : '--';
            const correct = entry.signal_correct;
            const ci = correct === 1 ? '✅' : (correct === 0 ? '❌' : '');
            html += `<div class="calendar-day has-data" style="--jcs-color: ${varColor};">
                <span class="day-num">${d}</span><span class="day-jcs" style="color:${fg}">${jcsStr}</span>
                <div class="calendar-tooltip">
                    <div style="font-weight:700; margin-bottom:4px; color:${fg}">JCS: ${jcsStr}</div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:2px"><span>Regime:</span> <span>R${entry.aiae_regime||'-'} | ${entry.mr_regime||'-'}</span></div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:2px"><span>仓位:</span> <span>${pos}</span></div>
                    <div style="display:flex; justify-content:space-between;"><span>ERP:</span> <span>${entry.erp_score != null ? entry.erp_score.toFixed(0) : '-'}</span></div>
                    ${ci ? `<div style="margin-top:4px; border-top:1px dashed rgba(255,255,255,0.1); padding-top:4px;">信号: ${ci}</div>` : ''}
                </div>
            </div>`;
        } else {
            html += `<div class="calendar-day no-data"><span class="day-num">${d}</span></div>`;
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
            <div class="jcs-comp-bar-bg"><div class="jcs-comp-bar-fill" style="width:${pct}%;background:${it.color};color:${it.color}"></div></div>
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

        // V19.3: 具名全局引用避免 resize 监听器累积
        if (window._acGlobalTempResize) window.removeEventListener('resize', window._acGlobalTempResize);
        window._acGlobalTempResize = () => Object.values(_globalTempCharts).forEach(c => c && c.resize());
        window.addEventListener('resize', window._acGlobalTempResize);
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
//  V24.0: 预交易合规检查引擎 (Pre-Trade Compliance Engine)
// ═══════════════════════════════════════════════════

async function loadRiskGuardrail() {
    try {
        const resp = await AC.secureFetch(`${API_BASE}/compliance-check`);
        const data = await resp.json();
        if (data.status) {
            renderComplianceEngine(data);
        }
    } catch (e) {
        console.warn('Compliance engine load error:', e);
        const listEl = document.getElementById('ce-rule-list');
        if (listEl) listEl.innerHTML = `<div class="loading-spinner">❌ 合规检查引擎异常: ${e.message}</div>`;
    }
}

/** V20.0: risk-matrix 缓存层 — 保留供其他模块使用 */
async function _fetchRiskMatrix() {
    if (window._riskMatrixCache) return window._riskMatrixCache;
    const resp = await AC.secureFetch(`${API_BASE}/risk-matrix`);
    window._riskMatrixCache = await resp.json();
    return window._riskMatrixCache;
}

function renderComplianceEngine(data) {
    const statusEl = document.getElementById('ce-overall-status');
    const listEl = document.getElementById('ce-rule-list');
    if (!statusEl || !listEl) return;

    // 1. 总体状态更新
    statusEl.textContent = data.summary || '状态未知';
    statusEl.className = 'ce-status ' + (data.status || 'warning');

    // 2. 规则列表渲染
    const checks = data.checks || [];
    if (checks.length === 0) {
        listEl.innerHTML = '<div class="loading-spinner">⚠️ 未获取到合规规则</div>';
        return;
    }

    const rowStatus = (c) => {
        if (!c.passed && c.severity === 'hard_block') return 'block';
        if (!c.passed && c.severity === 'soft_warn') return 'warn';
        return 'pass';
    };

    listEl.innerHTML = checks.map(c => {
        const status = rowStatus(c);
        const icon = status === 'block' ? '🛑' : (status === 'warn' ? '⚠️' : '🟢');
        
        return `<div class="ce-rule-row ${status}">
            <div class="ce-rule-indicator"></div>
            <div class="ce-rule-name-col">
                <span class="ce-rule-name">${c.rule_name}</span>
                <span class="ce-rule-badge ce-badge-${c.severity}">${c.severity.replace('_', ' ')}</span>
            </div>
            <div class="ce-rule-detail">${c.detail}</div>
            <div class="ce-rule-icon">${icon}</div>
        </div>`;
    }).join('');
}
// V19.3: SOP 折叠事件委托 (替代 inline onclick)
function initSOPToggle() {
    document.querySelectorAll('.sop-toggle').forEach(el => {
        el.addEventListener('click', () => el.parentElement.classList.toggle('open'));
    });
}

// V19.3: 异步加载超时降级 (8s 后显示失败 + 重试按钮)
function _fetchWithDegradation(containerId, fetchFn, label) {
    const timer = setTimeout(() => {
        const el = document.getElementById(containerId);
        if (!el) return;
        const spinner = el.querySelector('.loading-spinner');
        if (spinner) {
            spinner.innerHTML = `⚠️ ${label}数据暂不可用 <button class="sg-refresh-btn" style="margin-left:8px;font-size:0.72rem;" onclick="this.parentElement.innerHTML='⏳ 重新加载...';${fetchFn.name}()">↻ 重试</button>`;
        }
    }, 8000);
    fetchFn().finally(() => clearTimeout(timer));
}

// ═══════════════════════════════════════════════════
//  V19.2: 信号阈值速查表 — 实时高亮当前信号
// ═══════════════════════════════════════════════════
function highlightThresholdTable(snap) {
    const table = document.querySelector('.threshold-table tbody');
    if (!table) return;
    const rows = table.querySelectorAll('tr');
    // 判定每个引擎当前落在哪列: 1=看多, 2=中性, 3=看空
    const aiae = snap.aiae_v1 ?? 22;
    const erp = snap.erp_score ?? 45;
    const vix = snap.vix_val ?? 20;
    const mr = (snap.mr_regime || 'RANGE').toUpperCase();

    const zones = [
        aiae < 17 ? 1 : (aiae <= 23 ? 2 : 3),                    // AIAE
        erp > 55 ? 1 : (erp >= 35 ? 2 : 3),                       // ERP
        vix < 16 ? 1 : (vix <= 25 ? 2 : 3),                       // VIX
        mr === 'BULL' ? 1 : (['BEAR','CRASH'].includes(mr) ? 3 : 2) // MR
    ];

    rows.forEach((row, i) => {
        if (i >= zones.length) return;
        const cells = row.querySelectorAll('td');
        if (cells.length < 4) return;
        const activeCol = zones[i]; // 1=看多(col1), 2=中性(col2), 3=看空(col3)
        cells.forEach((td, j) => td.classList.remove('tt-active', 'tt-active-bull', 'tt-active-neutral', 'tt-active-bear'));
        const target = cells[activeCol];
        if (target) {
            target.classList.add('tt-active');
            target.classList.add(activeCol === 1 ? 'tt-active-bull' : (activeCol === 2 ? 'tt-active-neutral' : 'tt-active-bear'));
        }
    });
}

// ═══════════════════════════════════════════════════
//  V22.0: 跨市场风险传染热度图
// ═══════════════════════════════════════════════════

async function fetchContagionMatrix() {
    const card = document.getElementById('contagion-card');
    const grid = document.getElementById('contagion-grid');
    if (!card || !grid) return;

    card.classList.remove('initially-hidden');
    grid.innerHTML = '<div class="loading-spinner">⏳ 分析跨市场相关性...</div>';

    try {
        const resp = await fetch(`${API_BASE}/contagion-matrix`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderContagionMatrix(data);
        } else {
            grid.innerHTML = `<div class="contagion-empty">⚠️ ${data.message || '数据不足'}</div>`;
        }
    } catch (e) {
        grid.innerHTML = '<div class="contagion-empty">⚠️ 网络异常</div>';
    }
}

function renderContagionMatrix(data) {
    const grid = document.getElementById('contagion-grid');
    const badge = document.getElementById('contagion-risk-badge');
    const note = document.getElementById('contagion-note');
    if (!grid) return;

    const markets = data.markets || [];
    const matrix = data.correlation_matrix || [];
    const n = markets.length;

    if (n < 2) {
        grid.innerHTML = `<div class="contagion-empty">📊 ${data.contagion_note || '数据不足'}</div>`;
        if (note) note.innerHTML = '';
        return;
    }

    // Risk badge
    if (badge) {
        const icons = { high: '🔴', medium: '🟡', low: '🟢', unknown: '⚪' };
        const labels = { high: '高传染', medium: '中等联动', low: '低传染', unknown: '--' };
        badge.textContent = `${icons[data.contagion_risk] || ''} ${labels[data.contagion_risk] || data.contagion_risk}`;
        badge.className = `contagion-risk-badge ${data.contagion_risk}`;
    }

    // Color mapping: -1=blue, 0=white/grey, 1=red
    const corrToColor = (v) => {
        if (v > 0.8) return '#ef4444';
        if (v > 0.6) return '#f97316';
        if (v > 0.3) return '#fbbf24';
        if (v > -0.3) return '#475569';
        if (v > -0.6) return '#60a5fa';
        return '#3b82f6';
    };
    const corrToBg = (v) => {
        const absV = Math.abs(v);
        const alpha = 0.06 + absV * 0.25;
        if (v > 0) return `rgba(239,68,68,${alpha})`;
        if (v < 0) return `rgba(59,130,246,${alpha})`;
        return 'rgba(148,163,184,0.04)';
    };

    // Build grid
    let html = '<div class="contagion-axes"><div class="contagion-corner"></div>';
    markets.forEach(m => {
        html += `<div class="contagion-col-label">${m.flag} ${m.label}</div>`;
    });
    html += '</div>';

    for (let i = 0; i < n; i++) {
        html += '<div class="contagion-row">';
        html += `<div class="contagion-row-label">${markets[i].flag} ${markets[i].label}</div>`;
        for (let j = 0; j < n; j++) {
            const v = matrix[i] ? (matrix[i][j] != null ? matrix[i][j] : 0) : 0;
            const isDiag = i === j;
            const color = corrToColor(v);
            const bg = isDiag ? 'rgba(148,163,184,0.03)' : corrToBg(v);
            const label = isDiag ? '1.00' : (v > 0 ? '+' : '') + v.toFixed(2);
            const cls = isDiag ? 'contagion-cell diag' : 'contagion-cell';
            html += `<div class="${cls}" style="background:${bg};color:${isDiag ? '#64748b' : color};font-weight:${isDiag ? '400' : '600'};">
                ${label}
            </div>`;
        }
        html += '</div>';
    }
    grid.innerHTML = html;

    // High pairs
    if (note && data.high_pairs && data.high_pairs.length > 0) {
        note.innerHTML = `<span class="contagion-high-pairs">
            🔗 高联对: ${data.high_pairs.map(p =>
                `<span class="contagion-pair-tag ${p.level}">${p.a}↔${p.b} ρ=${p.corr > 0 ? '+' : ''}${p.corr.toFixed(2)} ${p.direction}</span>`
            ).join(' ')}
        </span><br>${data.contagion_note || ''}`;
    } else if (note) {
        note.innerHTML = data.contagion_note || '';
    }
}
