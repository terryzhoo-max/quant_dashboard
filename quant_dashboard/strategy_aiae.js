// ============================================================
// strategy_aiae.js — A股 AIAE 宏观仓位管控前端模块
// 依赖: strategy.js (需先加载)
// ============================================================

//  AIAE 宏观仓位管控模块 V2.0
//  琥珀金色系 · ECharts仪表盘 · 五档markArea色带 · 脉冲信号卡片
// ====================================================================

let _aiaeData = null;
let _aiaeLoading = false;

// DOM 缓存 — 避免每次 render 执行 ~30 次 getElementById
const _aiaeDOM = {};
function _aiaeCacheDOM() {
    if (_aiaeDOM._ready) return;
    ['hero-value','hero-regime','hero-position','hero-erp',
     'gauge-container','gauge-label','gauge-regime','slope-indicator',
     'data-simple','data-margin','data-fund','data-fund-date',
     'history-chart','hist-current','signal-cards',
     'matrix-table','matrix-verdict','cross-validation',
     'action-buy-list','action-hold-list','action-sell-list',
     'warn-margin','warn-slope','warn-fund',
     'warn-margin-val','warn-slope-val','warn-fund-val',
     'warn-margin-bar','warn-slope-bar','warn-fund-bar',
     'warning-panel','history-summary','regime-cards',
     'alloc-cards','load-status','load-btn','refresh-btn',
     'fund-reminder-banner','fund-stale-badge'
    ].forEach(k => {
        _aiaeDOM[k] = document.getElementById('aiae-' + k);
    });
    _aiaeDOM._ready = true;
}


async function loadAIAEReport(forceRefresh = false) {
    if (_aiaeLoading) return;
    if (_aiaeData && !forceRefresh) {
        renderAIAEUI(_aiaeData);
        return;
    }

    _aiaeLoading = true;
    const statusEl = document.getElementById('aiae-load-status');
    const loadBtn = document.getElementById('aiae-load-btn');
    const refreshBtn = document.getElementById('aiae-refresh-btn');
    if (statusEl) statusEl.textContent = '⏳ 正在连接 Tushare 数据源...';
    if (loadBtn) { loadBtn.disabled = true; loadBtn.innerHTML = '⏳ 加载中...'; }
    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const endpoint = forceRefresh ? '/api/v1/aiae/refresh' : '/api/v1/aiae/report';
        const resp = await fetch(endpoint, { signal: AbortSignal.timeout(20000) });
        const json = await resp.json();

        if (json.status === 'success' && json.data) {
            _aiaeData = json.data;
            try {
                renderAIAEUI(_aiaeData);
            } catch(renderErr) {
                console.warn('[AIAE] Partial render error (non-blocking):', renderErr);
            }
            if (statusEl) {
                const st = _aiaeData.status === 'fallback' ? '⚠️ 降级数据' : '✅ 实时数据';
                statusEl.textContent = st + ' · ' + new Date().toLocaleTimeString();
            }
            if (loadBtn) loadBtn.innerHTML = '✅ 数据已加载';
            setTimeout(() => { if (loadBtn) loadBtn.innerHTML = '⚡ 加载实时数据'; }, 2000);
        } else {
            if (statusEl) statusEl.textContent = `❌ ${json.message || '加载失败'}`;
            if (loadBtn) loadBtn.innerHTML = '❌ 重试';
            setTimeout(() => { if (loadBtn) loadBtn.innerHTML = '⚡ 加载实时数据'; }, 3000);
        }
    } catch (e) {
        console.error('[AIAE] Load error:', e);
        if (statusEl) statusEl.textContent = `❌ 网络异常: ${e.message}`;
        if (loadBtn) loadBtn.innerHTML = '❌ 重试';
        setTimeout(() => { if (loadBtn) loadBtn.innerHTML = '⚡ 加载实时数据'; }, 3000);
    } finally {
        _aiaeLoading = false;
        if (loadBtn) loadBtn.disabled = false;
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

function renderAIAEUI(data) {
    if (!data) return;
    _aiaeCacheDOM();  // 懒初始化 DOM 缓存
    const c = data.current;
    const p = data.position;
    const cv = data.cross_validation;
    const ri = c.regime_info;

    // ── Hero Stats (使用 DOM 缓存) ──
    const $v = _aiaeDOM['hero-value'];
    const $r = _aiaeDOM['hero-regime'];
    const $p = _aiaeDOM['hero-position'];
    const $e = _aiaeDOM['hero-erp'];
    if ($v) $v.textContent = c.aiae_v1 + '%';
    if ($r) { $r.textContent = `${ri.emoji} ${ri.cn}`; $r.style.color = ri.color; }
    if ($p) $p.textContent = p.matrix_position + '%';
    if ($e) { $e.textContent = cv.verdict; $e.style.color = cv.color; }

    // ── ZONE 1: ECharts Gauge ──
    try { renderAIAEGauge(c.aiae_v1, c.regime, ri); } catch(e) { console.warn('[AIAE] gauge skip:', e); }
    const $gl = _aiaeDOM['gauge-label'];
    const $gr = _aiaeDOM['gauge-regime'];
    const $sl = _aiaeDOM['slope-indicator'];
    if ($gl) $gl.textContent = c.aiae_v1;
    if ($gr) { $gr.textContent = `${ri.emoji} ${ri.name}`; $gr.style.color = ri.color; }
    if ($sl) {
        const slope = c.slope;
        const arrow = slope.direction === 'rising' ? '↗' : (slope.direction === 'falling' ? '↘' : '→');
        $sl.textContent = `月环比斜率: ${arrow} ${slope.slope > 0 ? '+' : ''}${slope.slope}`;
        $sl.style.color = slope.direction === 'rising' ? '#f97316' : (slope.direction === 'falling' ? '#10b981' : '#94a3b8');
    }

    // ── Regime cards highlight ──
    document.querySelectorAll('.aiae-regime-card').forEach(card => {
        const r = parseInt(card.dataset.regime);
        card.classList.toggle('active', r === c.regime);
    });

    // ── Data source cards (DOM 缓存) ──
    const $ds = _aiaeDOM['data-simple'];
    const $dm = _aiaeDOM['data-margin'];
    const $df = _aiaeDOM['data-fund'];
    if ($ds) $ds.textContent = c.aiae_simple + '%';
    if ($dm) $dm.textContent = c.margin_heat + '%';
    if ($df) $df.textContent = c.fund_position + '%';

    // ── ZONE 2: Matrix highlight ──
    renderAIAEMatrix(p, cv);

    // ── Allocations ──
    renderAIAEAllocs(p.allocations, p.matrix_position);

    // ── Cross validation (M1: 动态罗马数字映射, 修复硬编码 Ⅳ bug) ──
    const $cv = _aiaeDOM['cross-validation'];
    if ($cv) {
        const _romanMap = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
        const _romanLabel = _romanMap[c.regime] || 'Ⅲ';
        $cv.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;">
                <span class="aiae-cross-stars">${cv.confidence_stars}</span>
                <span class="aiae-cross-verdict" style="color:${cv.color};">${cv.verdict}</span>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px;line-height:1.6;">
                AIAE ${_romanLabel}${c.regime}级 × ERP ${p.erp_value}% (${cv.erp_level}) · 置信度 ${cv.confidence}/5
            </div>
        `;
    }

    // ── ZONE 3: History chart ──
    try { if (data.chart) renderAIAEHistoryChart(data.chart, c.aiae_v1); } catch(e) { console.warn('[AIAE] chart skip:', e); }

    // ── History summary current value (DOM 缓存) ──
    const $hc = _aiaeDOM['hist-current'];
    if ($hc) $hc.textContent = c.aiae_v1 + '%';

    // ── ZONE 4: Signals ──
    renderAIAESignals(data.signals);

    // ── Warning Indicators ──
    try { renderAIAEWarnings(c); } catch(e) { console.warn('[AIAE] warnings skip:', e); }

    // ── V2.1: Fund Position Quarterly Reminder ──
    try { renderAIAEFundReminder(data.stale_data_warnings || []); } catch(e) { console.warn('[AIAE] fund reminder skip:', e); }

    // ── Action Dashboard ──
    try { renderAIAEActionDashboard(c.regime, ri, p.matrix_position); } catch(e) { console.warn('[AIAE] action skip:', e); }
}

// ── Warning Indicators V2.1 (DOM 缓存) ──
function renderAIAEWarnings(c) {
    // Margin heat
    const mVal = c.margin_heat || 0;
    const $mV = _aiaeDOM['warn-margin-val'];
    const $mB = _aiaeDOM['warn-margin-bar'];
    const $mC = _aiaeDOM['warn-margin'];
    if ($mV) { $mV.textContent = mVal + '%'; $mV.style.color = mVal > 3.5 ? '#ef4444' : mVal > 2.5 ? '#f59e0b' : '#10b981'; }
    if ($mB) { $mB.style.width = Math.min(mVal / 5 * 100, 100) + '%'; $mB.style.background = mVal > 3.5 ? '#ef4444' : mVal > 2.5 ? '#f59e0b' : '#10b981'; }
    if ($mC) { $mC.className = 'aiae-warning-card ' + (mVal > 3.5 ? 'warn-danger' : mVal > 2.5 ? 'warn-caution' : 'warn-ok'); }

    // Slope
    const sVal = c.slope?.slope || 0;
    const absSlope = Math.abs(sVal);
    const $sV = _aiaeDOM['warn-slope-val'];
    const $sB = _aiaeDOM['warn-slope-bar'];
    const $sC = _aiaeDOM['warn-slope'];
    if ($sV) { $sV.textContent = (sVal > 0 ? '+' : '') + sVal; $sV.style.color = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981'; }
    if ($sB) { $sB.style.width = Math.min(absSlope / 3 * 100, 100) + '%'; $sB.style.background = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981'; }
    if ($sC) { $sC.className = 'aiae-warning-card ' + (absSlope > 1.5 ? 'warn-danger' : absSlope > 0.8 ? 'warn-caution' : 'warn-ok'); }

    // Fund position + 过期告警
    const fVal = c.fund_position || 0;
    const fDate = c.fund_position_date || '';
    const $fV = _aiaeDOM['warn-fund-val'];
    const $fB = _aiaeDOM['warn-fund-bar'];
    const $fC = _aiaeDOM['warn-fund'];
    if ($fV) { $fV.textContent = fVal + '%'; $fV.style.color = fVal > 90 ? '#ef4444' : fVal > 85 ? '#f59e0b' : '#10b981'; }
    if ($fB) { $fB.style.width = Math.min(fVal / 100 * 100, 100) + '%'; $fB.style.background = fVal > 90 ? '#ef4444' : fVal > 85 ? '#f59e0b' : '#10b981'; }
    if ($fC) { $fC.className = 'aiae-warning-card ' + (fVal > 90 ? 'warn-danger' : fVal > 85 ? 'warn-caution' : 'warn-ok'); }

    // C1: 基金仓位过期告警 (>90天显示橙色⚠️)
    if (fDate) {
        const daysStaleFund = Math.floor((Date.now() - new Date(fDate).getTime()) / 86400000);
        const $fStale = _aiaeDOM['fund-stale-badge'];
        if ($fStale) {
            if (daysStaleFund > 90) {
                $fStale.style.display = 'inline-flex';
                $fStale.textContent = `⚠️ 数据滞后 ${daysStaleFund} 天`;
                $fStale.style.color = daysStaleFund > 150 ? '#ef4444' : '#f59e0b';
            } else {
                $fStale.style.display = 'none';
            }
        }
        // 也在数据源卡片上追加日期信息
        const $dfLabel = _aiaeDOM['data-fund-date'];
        if ($dfLabel) {
            $dfLabel.textContent = fDate;
            $dfLabel.style.color = daysStaleFund > 90 ? '#f59e0b' : '#64748b';
        }
    }
}

// ── V2.1: Fund Position Quarterly Reminder ──
function renderAIAEFundReminder(staleWarnings) {
    const banner = document.getElementById('aiae-fund-reminder-banner');
    if (!banner) return;

    // 查找基金仓位相关告警
    const fundWarning = staleWarnings.find(w => w.type === 'fund_update_due' || w.type === 'fund_position_stale');
    if (!fundWarning) {
        banner.style.display = 'none';
        return;
    }

    banner.style.display = 'block';

    // 设置标签
    const labelEl = document.getElementById('aiae-fund-reminder-label');
    if (labelEl) {
        const severity = fundWarning.severity === 'critical' ? '🔴 紧急' : '🟡 提醒';
        labelEl.textContent = severity + (fundWarning.expected_label ? ' · ' + fundWarning.expected_label : '');
    }

    // 设置消息
    const msgEl = document.getElementById('aiae-fund-reminder-message');
    if (msgEl) {
        const days = fundWarning.days_stale || 0;
        msgEl.innerHTML = fundWarning.message + 
            '<br><span style="color:#64748b;">当前值: ' + (fundWarning.current_value||'--') + '% · 截至 ' + (fundWarning.current_date||'--') + 
            ' · 滞后 <b style="color:#f59e0b;">' + days + '</b> 天 · 占 AIAE_V1 权重 30%</span>';
    }

    // 如果是 critical 级别，加脉冲动画
    if (fundWarning.severity === 'critical') {
        banner.style.animation = 'pulse 2s infinite';
        banner.style.borderColor = 'rgba(239,68,68,0.4)';
    } else {
        banner.style.animation = 'none';
        banner.style.borderColor = 'rgba(245,158,11,0.3)';
    }
}

// ── V2.1: Fund Position Update Submit ──
async function submitFundPositionUpdate() {
    const valueEl = document.getElementById('aiae-fund-input-value');
    const dateEl = document.getElementById('aiae-fund-input-date');
    const resultEl = document.getElementById('aiae-fund-update-result');
    const submitBtn = document.getElementById('aiae-fund-submit-btn');

    if (!valueEl || !dateEl) return;
    const value = parseFloat(valueEl.value);
    const date = dateEl.value;

    if (isNaN(value) || value < 50 || value > 100) {
        if (resultEl) { resultEl.textContent = '❌ 仓位值须在 50-100% 之间'; resultEl.style.color = '#ef4444'; }
        return;
    }

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = '⏳ 提交中...'; }
    if (resultEl) { resultEl.textContent = '⏳ 正在更新...'; resultEl.style.color = '#f59e0b'; }

    try {
        const resp = await fetch('/api/v1/aiae/update_fund_position', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: value, date: date })
        });
        const json = await resp.json();

        if (json.status === 'success') {
            if (resultEl) { resultEl.innerHTML = '✅ 更新成功! ' + json.message + ' <span style="color:#64748b;">· 3秒后自动刷新数据...</span>'; resultEl.style.color = '#10b981'; }
            // 隐藏提醒 banner
            const banner = document.getElementById('aiae-fund-reminder-banner');
            if (banner) banner.style.display = 'none';
            // 3秒后自动刷新报告
            setTimeout(() => {
                document.getElementById('aiae-fund-update-panel').style.display = 'none';
                loadAIAEReport(true);  // 强制刷新
            }, 3000);
        } else {
            if (resultEl) { resultEl.textContent = '❌ ' + (json.message || '更新失败'); resultEl.style.color = '#ef4444'; }
        }
    } catch(e) {
        console.error('[AIAE Fund Update] Error:', e);
        if (resultEl) { resultEl.textContent = '❌ 网络异常: ' + e.message; resultEl.style.color = '#ef4444'; }
    } finally {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '✅ 提交更新'; }
    }
}

// ── Action Dashboard V2.1 (dynamic per regime) ──
function renderAIAEActionDashboard(regime, ri, matrixPos) {
    const actionData = {
        1: {
            buy: ['<b style="color:#10b981">AIAE<12% 满仓进攻模式</b>','分3批建仓，越跌越买','优先宽基ETF: 300/50/500/创业板','红利ETF同步配置底仓'],
            hold: ['每批完成后等待3-5天观察','不追高，只在下跌日建仓','总仓位控制在90-95%内'],
            sell: ['此档位禁止任何卖出操作','除非触发组合级-25%强制止损','耐心持有，等待市场修复']
        },
        2: {
            buy: ['<b style="color:#3b82f6">AIAE 12-16% 标准建仓区</b>','按节奏建仓，总目标仓位70-85%','宽基+红利均衡配置','ERP>4%时加大买入力度'],
            hold: ['已建仓位坚定持有','不因短期波动减仓','定期检查子策略配额是否到位'],
            sell: ['此档位不主动卖出','仅止损触发时被动减仓','子策略止损线: MR-8% DIV-5% MOM-7%']
        },
        3: {
            buy: ['<b style="color:#eab308">Ⅲ级不主动加仓</b>','仅在子策略出现强烈买入信号时小幅加仓','新增仓位限制在总仓5%以内'],
            hold: ['维持均衡仓位50-65%','有纪律持有，到目标价就卖','以宽基+红利为主，减少进攻型标的'],
            sell: ['到达止盈目标的标的及时卖出','密切监控AIAE是否向24%靠近','若接近24%开始做减仓准备']
        },
        4: {
            buy: ['<b style="color:#f97316">Ⅳ级禁止新开仓</b>','不追涨任何进攻型标的','仅保留现有红利型标的'],
            hold: ['总仓位压缩至25-40%','红利ETF可继续持有','进攻型标的逐步清退'],
            sell: ['<b style="color:#ef4444">每周减5%总仓位</b>','优先清退高波动标的','3-4周完成减仓至目标水位']
        },
        5: {
            buy: ['<b style="color:#ef4444">Ⅴ级·绝对禁止任何买入</b>','历史级泡沫信号','任何新仓位=与市场对赌'],
            hold: ['仅保留0-15%极低仓位','仅限红利防御型ETF','现金为王'],
            sell: ['<b style="color:#ef4444">3天内完成清仓</b>','无例外，不抄底','强制执行，无论盈亏']
        }
    };

    const d = actionData[regime] || actionData[3];
    const $buy = document.getElementById('aiae-action-buy-list');
    const $hold = document.getElementById('aiae-action-hold-list');
    const $sell = document.getElementById('aiae-action-sell-list');

    if ($buy) $buy.innerHTML = d.buy.map(t => `<li>${t}</li>`).join('');
    if ($hold) $hold.innerHTML = d.hold.map(t => `<li>${t}</li>`).join('');
    if ($sell) $sell.innerHTML = d.sell.map(t => `<li>${t}</li>`).join('');

    // Highlight active zone
    const cards = document.querySelectorAll('.aiae-action-card');
    cards.forEach(c => {
        c.style.opacity = '0.6';
        c.style.transform = '';
    });
    const activeMap = { 1: 0, 2: 0, 3: 1, 4: 2, 5: 2 };
    const activeIdx = activeMap[regime] ?? 1;
    if (cards[activeIdx]) {
        cards[activeIdx].style.opacity = '1';
        cards[activeIdx].style.transform = 'scale(1.03)';
    }
}

// ── ECharts Gauge V2.0 ──
function renderAIAEGauge(value, regime, ri) {
    const container = document.getElementById('aiae-gauge-container');
    if (!container || typeof echarts === 'undefined') return;
    try { window._aiaeGaugeChart = AC.disposeChart(window._aiaeGaugeChart); } catch(_) {}
    window._aiaeGaugeChart = AC.registerChart(echarts.init(container));

    const v = Math.min(Math.max(value, 0), 50);

    window._aiaeGaugeChart.setOption({
        series: [{
            type: 'gauge',
            startAngle: 200,
            endAngle: -20,
            min: 0,
            max: 50,
            pointer: {
                show: true,
                length: '58%',
                width: 4,
                itemStyle: { color: ri.color, shadowColor: ri.color, shadowBlur: 8 },
                icon: 'triangle'
            },
            anchor: {
                show: true,
                size: 10,
                itemStyle: { color: '#0f172a', borderColor: ri.color, borderWidth: 3 }
            },
            axisLine: {
                lineStyle: {
                    width: 14,
                    color: [
                        [0.25, '#10b981'],   // Ⅰ: 0-12.5
                        [0.34, '#3b82f6'],   // Ⅱ: 12.5-17
                        [0.46, '#eab308'],   // Ⅲ: 17-23
                        [0.60, '#f97316'],   // Ⅳ: 23-30
                        [1, '#ef4444']       // Ⅴ: 30-50
                    ]
                }
            },
            axisTick: {
                length: 8,
                distance: -14,
                lineStyle: { color: 'auto', width: 1.5 }
            },
            splitLine: {
                length: 14,
                distance: -14,
                lineStyle: { color: 'auto', width: 2 }
            },
            splitNumber: 5,
            axisLabel: {
                distance: -36,
                color: '#64748b',
                fontSize: 9,
                formatter: function(val) {
                    var map = {0: '0', 10: '10', 13: 'Ⅰ', 17: 'Ⅱ', 20: '20', 23: 'Ⅲ', 30: 'Ⅳ', 40: '40', 50: '50'};
                    return map[val] || '';
                }
            },
            detail: { show: false },
            data: [{ value: v }],
            animationDuration: 1200,
            animationEasingUpdate: 'cubicOut'
        }]
    });
}

// ── History Chart V2.0 (五档 markArea 色带) ──
function renderAIAEHistoryChart(chart, currentValue) {
    const container = document.getElementById('aiae-history-chart');
    if (!container || typeof echarts === 'undefined') return;
    try {
        try { if (window._aiaeHistChart) AC.disposeChart(window._aiaeHistChart); } catch(_) {}
        window._aiaeHistChart = AC.registerChart(echarts.init(container));

        // 五档区间色带
        const markAreaData = [
            [{ yAxis: 0, itemStyle: { color: 'rgba(16,185,129,0.06)' } }, { yAxis: 12.5 }],   // Ⅰ
            [{ yAxis: 12.5, itemStyle: { color: 'rgba(59,130,246,0.05)' } }, { yAxis: 17 }],   // Ⅱ
            [{ yAxis: 17, itemStyle: { color: 'rgba(234,179,8,0.05)' } }, { yAxis: 23 }],    // Ⅲ
            [{ yAxis: 23, itemStyle: { color: 'rgba(249,115,22,0.06)' } }, { yAxis: 30 }],   // Ⅳ
            [{ yAxis: 30, itemStyle: { color: 'rgba(239,68,68,0.06)' } }, { yAxis: 50 }],    // Ⅴ
        ];

        // 分界参考线
        const markLines = [12.5, 17, 23, 30].map(val => ({
            yAxis: val,
            lineStyle: { color: val <= 17 ? '#3b82f644' : (val <= 23 ? '#eab30844' : '#ef444444'), type: 'dashed', width: 1 },
            label: {
                formatter: val === 12.5 ? 'Ⅰ|Ⅱ' : (val === 17 ? 'Ⅱ|Ⅲ' : (val === 23 ? 'Ⅲ|Ⅳ' : 'Ⅳ|Ⅴ')),
                position: 'end', color: '#64748b', fontSize: 9
            }
        }));

        window._aiaeHistChart.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(245,158,11,0.3)',
                textStyle: { color: '#e2e8f0', fontSize: 11 },
                formatter: function(params) {
                    if (!params.length) return '';
                    const p = params[0];
                    const idx = chart.dates.indexOf(p.axisValue);
                    const label = idx >= 0 && chart.labels[idx] ? chart.labels[idx] : '';
                    // Determine tier
                    const val = p.value;
                    let tierLabel = '';
                    if (val < 12.5) tierLabel = '<span style="color:#10b981">Ⅰ级 极度恐慌</span>';
                    else if (val < 17) tierLabel = '<span style="color:#3b82f6">Ⅱ级 低配置区</span>';
                    else if (val < 23) tierLabel = '<span style="color:#eab308">Ⅲ级 中性均衡</span>';
                    else if (val < 30) tierLabel = '<span style="color:#f97316">Ⅳ级 偏热区域</span>';
                    else tierLabel = '<span style="color:#ef4444">Ⅴ级 极度过热</span>';

                    return '<b>' + p.axisValue + '</b><br/>' +
                        '<span style="color:#f59e0b">●</span> AIAE: <b>' + p.value + '%</b><br/>' +
                        tierLabel +
                        (label ? '<br/><span style="color:#94a3b8">' + label + '</span>' : '');
                }
            },
            grid: { left: 55, right: 30, top: 32, bottom: 32 },
            xAxis: {
                type: 'category', data: chart.dates, boundaryGap: false,
                axisLabel: { color: '#64748b', fontSize: 9, formatter: function(v) { return v.substring(0, 7); } },
                axisLine: { lineStyle: { color: '#334155' } }
            },
            yAxis: {
                type: 'value', min: 0, max: 50,
                axisLabel: { color: '#64748b', fontSize: 9, formatter: function(v) { return v + '%'; } },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            series: [{
                type: 'line', data: chart.values, smooth: true,
                symbol: 'circle', symbolSize: 10,
                lineStyle: { color: '#f59e0b', width: 3, shadowColor: 'rgba(245,158,11,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#f59e0b', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(245,158,11,0.25)' },
                            { offset: 1, color: 'rgba(245,158,11,0)' }
                        ]
                    }
                },
                label: {
                    show: true, fontSize: 8, color: '#f59e0b',
                    formatter: function(p) { return p.value + '%'; },
                    position: 'top'
                },
                markArea: { silent: true, data: markAreaData },
                markLine: { silent: true, symbol: 'none', data: markLines }
            }]
        });
    } catch(err) {
        console.warn('[AIAE] History chart error:', err);
    }
}


function renderAIAEMatrix(pos, cv) {
    const table = document.getElementById('aiae-matrix-table');
    if (!table) return;

    // Heatmap color function: 高仓位=绿, 低仓位=红
    function posColor(v) {
        if (v >= 80) return 'rgba(16,185,129,0.2)';
        if (v >= 60) return 'rgba(52,211,153,0.12)';
        if (v >= 40) return 'rgba(234,179,8,0.1)';
        if (v >= 20) return 'rgba(249,115,22,0.12)';
        return 'rgba(239,68,68,0.15)';
    }

    // 清除旧高亮 + 添加热力图
    const posValues = [[95,85,65,40,15],[90,80,60,35,10],[85,70,50,25,5],[75,55,35,15,0]];
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach((row, ri) => {
        const cells = row.querySelectorAll('td');
        cells.forEach((td, ci) => {
            td.classList.remove('aiae-matrix-active');
            if (ci > 0 && posValues[ri]) { // skip row label
                td.style.background = posColor(posValues[ri][ci-1]);
            }
        });
    });

    // 确定当前交叉位置并高亮
    const erpMap = { 'erp_gt6': 0, 'erp_4_6': 1, 'erp_2_4': 2, 'erp_lt2': 3 };
    const rowIdx = erpMap[pos.erp_level] ?? 2;
    const colIdx = Math.min(pos.regime - 1, 4);
    if (rows[rowIdx]) {
        const cells = rows[rowIdx].querySelectorAll('td');
        if (cells[colIdx + 1]) cells[colIdx + 1].classList.add('aiae-matrix-active');
    }

    const regimeNames = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
    const $verdict = document.getElementById('aiae-matrix-verdict');
    if ($verdict) {
        $verdict.innerHTML = '当前: <b style="color:#f59e0b">' + regimeNames[pos.regime] + '级</b>' +
            ' × <b style="color:#60a5fa">ERP ' + pos.erp_value + '%</b>' +
            ' → 建议总仓位 <b style="color:#10b981;font-size:1.1rem;">' + pos.matrix_position + '%</b>';
    }
}

function renderAIAEAllocs(allocs, totalPos) {
    if (!allocs) return;
    // M2: 新增 aiae_etf 第5策略配额 (金色主题)
    const strategies = ['mr', 'div', 'mom', 'erp', 'aiae_etf'];
    strategies.forEach(key => {
        const a = allocs[key];
        if (!a) {
            // aiae_etf 可能不在后端 allocations 中, 用 JOINT_WEIGHTS 补算
            if (key === 'aiae_etf') {
                const etfPct = 100 - Object.values(allocs).reduce((s, v) => s + (v.pct || 0), 0);
                const etfPos = Math.round(totalPos * Math.max(etfPct, 0) / 100 * 10) / 10;
                const $pct = document.getElementById('aiae-alloc-aiae_etf-pct');
                const $pos = document.getElementById('aiae-alloc-aiae_etf-pos');
                const $bar = document.getElementById('aiae-alloc-aiae_etf-bar');
                if ($pct) $pct.textContent = Math.max(etfPct, 0) + '%';
                if ($pos) $pos.textContent = etfPos + '% 仓位';
                if ($bar) $bar.style.width = Math.min(Math.max(etfPct, 0), 100) + '%';
            }
            return;
        }
        const $pct = document.getElementById(`aiae-alloc-${key}-pct`);
        const $pos = document.getElementById(`aiae-alloc-${key}-pos`);
        const $bar = document.getElementById(`aiae-alloc-${key}-bar`);
        if ($pct) $pct.textContent = a.pct + '%';
        if ($pos) $pos.textContent = a.position + '% 仓位';
        if ($bar) $bar.style.width = Math.min(a.pct, 100) + '%';
    });
}

function renderAIAESignals(signals) {
    const container = document.getElementById('aiae-signal-cards');
    if (!container || !signals || !signals.length) return;

    function hexToRgba(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r},${g},${b},${alpha})`;
    }

    container.innerHTML = signals.map((s, i) => {
        const c = s.color || '#f59e0b';
        const isMain = s.type === 'main' || i === 0;
        const icon = s.type === 'main' ? '🌡️' : (s.type === 'slope' ? '📐' : (s.type === 'margin' ? '💳' : '📡'));
        const mainClass = isMain ? ' aiae-signal-main' : '';
        const time = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
        return `<div class="aiae-signal-card${mainClass}" style="--signal-color:${c};">
            <div class="aiae-signal-icon">${icon}</div>
            <div>
                <div class="aiae-signal-text" style="color:${c}">${s.text}</div>
                <span class="aiae-signal-time">${time}</span>
            </div>
        </div>`;
    }).join('');
}

// 页面首次加载时，如果AIAE是默认active tab则自动加载
document.addEventListener('DOMContentLoaded', function() {
    const aiaeTab = document.querySelector('.st-tab[data-report="st-aiae-position"]');
    if (aiaeTab && aiaeTab.classList.contains('active')) {
        setTimeout(() => loadAIAEReport(), 500);
    }
});

// Phase 2: resize 已由 alphacore_utils.js 注册中心统一处理
