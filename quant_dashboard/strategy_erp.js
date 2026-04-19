// ============================================================
// strategy_erp.js — A股 ERP 择时引擎前端模块
// 依赖: strategy.js (需先加载)
// ============================================================

let _erpLoaded = false;
let _erpLastFetchTime = 0;          // 上次拉取时间戳 (ms)
let _erpCountdownTimer = null;      // P1: 倒计时定时器
let _erpGaugeChart = null;
let _erpHistoryChart = null;
const ERP_COOLDOWN_MS = 5 * 60 * 1000;  // 5 分钟刷新冷却
const ERP_STALE_MS = 30 * 60 * 1000;    // C4 fix: 30 分钟数据过期阈值

// P1: 注入变化高亮 CSS
(function injectERPHighlightCSS() {
    if (document.getElementById('erp-highlight-style')) return;
    const style = document.createElement('style');
    style.id = 'erp-highlight-style';
    style.textContent = `
        @keyframes erpValueFlash {
            0% { background: rgba(245,158,11,0.35); }
            100% { background: transparent; }
        }
        .erp-value-changed {
            animation: erpValueFlash 1.2s ease-out;
            border-radius: 4px;
        }
    `;
    document.head.appendChild(style);
})();

/**
 * P1: 启动/重启倒计时显示
 */
function startERPCountdown() {
    if (_erpCountdownTimer) clearInterval(_erpCountdownTimer);
    const el = document.getElementById('erp-refresh-countdown');
    if (!el) return;
    _erpCountdownTimer = setInterval(() => {
        const elapsed = Date.now() - _erpLastFetchTime;
        const remaining = Math.max(0, ERP_COOLDOWN_MS - elapsed);
        if (remaining <= 0) {
            el.textContent = '可刷新';
            el.style.color = '#10b981';
            clearInterval(_erpCountdownTimer);
            _erpCountdownTimer = null;
        } else {
            const mins = Math.floor(remaining / 60000);
            const secs = Math.floor((remaining % 60000) / 1000);
            el.textContent = `${mins}m${secs.toString().padStart(2,'0')}s 后可刷新`;
            el.style.color = '#475569';
        }
    }, 1000);
}

/**
 * P1: 检测数值变化并添加高亮动画
 */
function highlightERPChanges(oldSnap, newSnap) {
    if (!oldSnap || !newSnap) return;
    const pairs = [
        ['erp-val-erp',    oldSnap.erp_value,    newSnap.erp_value],
        ['erp-val-pe',     oldSnap.pe_ttm,       newSnap.pe_ttm],
        ['erp-val-yield',  oldSnap.yield_10y,    newSnap.yield_10y],
    ];
    pairs.forEach(([id, oldVal, newVal]) => {
        if (oldVal != null && newVal != null && oldVal !== newVal) {
            const el = document.getElementById(id);
            if (el) {
                el.classList.remove('erp-value-changed');
                void el.offsetWidth;  // force reflow
                el.classList.add('erp-value-changed');
            }
        }
    });
}

let _erpPrevSnapshot = null;  // P1: 保存上次快照用于变化比较

/**
 * 刷新按钮入口 — 带 5 分钟冷却 + Loading 状态
 */
async function refreshERPData() {
    const btn = document.getElementById('erp-refresh-btn');
    const elapsed = Date.now() - _erpLastFetchTime;
    
    // 5 分钟冷却检查
    if (_erpLoaded && elapsed < ERP_COOLDOWN_MS) {
        const remaining = Math.ceil((ERP_COOLDOWN_MS - elapsed) / 60000);
        // 闪烁提示
        if (btn) {
            const orig = btn.innerHTML;
            btn.innerHTML = '✅ 数据仍为最新';
            btn.style.borderColor = 'rgba(16,185,129,0.4)';
            btn.style.color = '#10b981';
            setTimeout(() => {
                btn.innerHTML = orig;
                btn.style.borderColor = 'rgba(245,158,11,0.3)';
                btn.style.color = '#f59e0b';
            }, 1500);
        }
        return;
    }
    
    // 解锁 + 设置 Loading 状态
    _erpLoaded = false;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ 刷新中...';
        btn.style.opacity = '0.6';
    }
    
    try {
        await loadERPTimingData();
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔄 刷新实时数据';
            btn.style.opacity = '1';
        }
    }
}

async function loadERPTimingData() {
    // C4 fix: 数据超过30分钟自动刷新，而非永久缓存
    if (_erpLoaded && (Date.now() - _erpLastFetchTime) < ERP_STALE_MS) return;
    
    // Loading 状态: 信号 Badge
    const sigLabel = document.getElementById('erp-signal-label');
    const sigEmoji = document.getElementById('erp-signal-emoji');
    if (sigLabel) { sigLabel.textContent = '刷新中...'; sigLabel.style.color = '#f59e0b'; }
    if (sigEmoji) sigEmoji.textContent = '⏳';
    
    try {
        const resp = await fetch('/api/v1/strategy/erp-timing');
        const json = await resp.json();
        if (json.status !== 'success' || !json.data) { console.error('ERP API error:', json); return; }
        const data = json.data;

        // V2.1: 降级状态检测 — 引擎返回 fallback 时显示警告
        const bar = document.getElementById('erp-identity-bar');
        if (data.status === 'fallback') {
            if (bar) {
                bar.style.borderLeftColor = '#f59e0b';
                bar.style.boxShadow = '0 0 20px rgba(245,158,11,0.3)';
            }
            const badge = document.getElementById('erp-resonance-badge');
            if (badge) {
                badge.textContent = '⚠️ 数据降级模式';
                badge.style.background = 'rgba(245,158,11,0.15)';
                badge.style.color = '#f59e0b';
            }
        }
        // P1: 变化高亮 (比较新旧快照)
        const newSnap = data.current_snapshot || {};
        highlightERPChanges(_erpPrevSnapshot, newSnap);
        _erpPrevSnapshot = { ...newSnap };
        
        renderERPSnapshot(data);
        renderERPAlerts(data.alerts || []);
        renderERPTradeHub(data.trade_rules || {});
        renderERPDimBars(data.dimensions, data.encyclopedia || {});
        renderERPGauge(data.signal, data.trade_rules);
        if (data.chart && data.chart.status === 'success') renderERPHistoryChart(data.chart, data);
        renderERPEncyclopedia(data.encyclopedia || {});
        renderERPDiagnosis(data.diagnosis || []);
        // 头部徽章
        const sig = data.signal || {};
        const tr = data.trade_rules || {};
        document.getElementById('erp-signal-emoji').textContent = sig.emoji || '?';
        const lbl = document.getElementById('erp-signal-label');
        lbl.textContent = sig.label || '--'; lbl.style.color = sig.color || '#94a3b8';
        document.getElementById('erp-signal-position').textContent = '\u5EFA\u8BAE\u4ED3\u4F4D ' + (sig.position||'--') + ' \u00B7 \u5F97\u5206 ' + (sig.score||'--');
        document.getElementById('erp-resonance-badge').textContent = tr.resonance_label || '';
        document.getElementById('erp-update-time').textContent = '\u6700\u540E\u66F4\u65B0: ' + new Date().toLocaleString('zh-CN');
        // 脉冲动画
        const alerts = data.alerts || [];
        const hasPulse = alerts.some(a => a.pulse);
        if (hasPulse) {
            const bar = document.getElementById('erp-identity-bar');
            const pulseAlert = alerts.find(a => a.pulse);
            const pulseColor = pulseAlert.level === 'danger' ? '#ef4444' : (pulseAlert.level === 'opportunity' ? '#10b981' : '#f59e0b');
            bar.style.boxShadow = '0 0 20px ' + pulseColor + '40';
            bar.style.borderLeftColor = pulseColor;
        }
        _erpLoaded = true;
        _erpLastFetchTime = Date.now();
        
        // P1: 启动倒计时
        startERPCountdown();
        
    } catch (e) {
        console.error('ERP load error:', e);
        // 错误恢复: 保持 _erpLoaded = false 允许重试
        if (sigLabel) { sigLabel.textContent = '加载失败'; sigLabel.style.color = '#ef4444'; }
        if (sigEmoji) sigEmoji.textContent = '❌';
    }
}


function renderERPSnapshot(data) {
    const snap = data.current_snapshot || {};
    const dims = data.dimensions || {};
    const m1 = dims.m1_trend?.m1_info || {};
    const vol = dims.volatility?.vol_info || {};
    const credit = dims.credit?.credit_info || {};
    // ERP
    const erpEl = document.getElementById('erp-val-erp');
    erpEl.textContent = (snap.erp_value || '--') + '%';
    erpEl.style.color = snap.erp_value >= 5 ? '#10b981' : (snap.erp_value >= 3.5 ? '#f59e0b' : '#ef4444');
    document.getElementById('erp-sub-erp').textContent = '\u8FD14\u5E74 ' + (snap.erp_percentile || '--') + '% \u5206\u4F4D';
    const trendErp = document.getElementById('erp-trend-erp');
    if (snap.erp_value >= 5) { trendErp.textContent = '\u2191'; trendErp.style.color = '#10b981'; }
    else if (snap.erp_value < 3.5) { trendErp.textContent = '\u2193'; trendErp.style.color = '#ef4444'; }
    else { trendErp.textContent = '\u2192'; trendErp.style.color = '#f59e0b'; }
    // PE
    document.getElementById('erp-val-pe').textContent = (snap.pe_ttm || '--') + 'x';
    document.getElementById('erp-sub-pe').textContent = '\u76C8\u5229\u6536\u76CA\u7387 ' + (snap.earnings_yield || '--') + '%';
    // 10Y
    document.getElementById('erp-val-yield').textContent = (snap.yield_10y || '--') + '%';
    // M1
    const m1El = document.getElementById('erp-val-m1');
    m1El.textContent = (m1.current ?? '--') + '%';
    m1El.style.color = m1.current > 0 ? '#10b981' : '#ef4444';
    // M1 fix: show data month to detect stale M1
    const m1Month = m1.data_month ? m1.data_month.replace(/^(\d{4})(\d{2})$/, '$1-$2') : '';
    document.getElementById('erp-sub-m1').textContent = 'M2: ' + (m1.m2_yoy ?? '--') + '%' + (m1Month ? ' \u00b7 \u622a\u81f3' + m1Month : '');
    const trendM1 = document.getElementById('erp-trend-m1');
    if (m1.direction === 'rising') { trendM1.textContent = '\u2191'; trendM1.style.color = '#10b981'; }
    else { trendM1.textContent = '\u2193'; trendM1.style.color = '#ef4444'; }
    // Vol
    const volEl = document.getElementById('erp-val-vol');
    volEl.textContent = (vol.current ?? '--');
    volEl.style.color = vol.regime === 'calm' ? '#10b981' : (vol.regime === 'extreme_panic' ? '#ef4444' : '#94a3b8');
    document.getElementById('erp-sub-vol').textContent = (vol.pct ?? '--') + '% \u5206\u4F4D | ' + ({calm:'\u5E73\u9759',normal:'\u6B63\u5E38',high:'\u504F\u9AD8',extreme_panic:'\u6050\u614C'}[vol.regime]||'--');
    // Credit
    const creditEl = document.getElementById('erp-val-credit');
    const scissor = m1.scissor ?? credit.scissor ?? '--';
    creditEl.textContent = (typeof scissor === 'number' ? (scissor >= 0 ? '+' : '') + scissor.toFixed(1) : scissor) + '%';
    creditEl.style.color = scissor >= -2 ? '#10b981' : '#f59e0b';
    document.getElementById('erp-sub-credit').textContent = scissor >= 0 ? '\u8D44\u91D1\u6D3B\u5316' : '\u8D44\u91D1\u6C89\u6DC0';
}

function renderERPAlerts(alerts) {
    const banner = document.getElementById('erp-alert-banner');
    if (!alerts.length || (alerts.length === 1 && alerts[0].level === 'normal')) { banner.style.display = 'none'; return; }
    const colorMap = { danger: '#ef4444', warning: '#f59e0b', opportunity: '#10b981', normal: '#64748b' };
    banner.style.display = 'flex';
    banner.style.cssText += 'display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;';
    banner.innerHTML = alerts.filter(a => a.level !== 'normal').map(a => {
        const c = colorMap[a.level] || '#64748b';
        const pulse = a.pulse ? 'animation:erpPulse 2s infinite;' : '';
        return '<div style="font-size:0.7rem;padding:4px 10px;border-radius:6px;background:' + c + '15;border:1px solid ' + c + '40;color:' + c + ';' + pulse + '">' + a.icon + ' ' + a.text + '</div>';
    }).join('');
    // 注入脉冲动画CSS
    if (!document.getElementById('erp-pulse-style')) {
        const style = document.createElement('style');
        style.id = 'erp-pulse-style';
        style.textContent = '@keyframes erpPulse{0%,100%{opacity:1;box-shadow:0 0 8px rgba(245,158,11,0.3)}50%{opacity:0.7;box-shadow:0 0 16px rgba(245,158,11,0.6)}}';
        document.head.appendChild(style);
    }
}

function renderERPTradeHub(trade) {
    // 信号等级条
    const levelBar = document.getElementById('erp-signal-level-bar');
    const levels = ['cash','underweight','reduce','hold','buy','strong_buy'];
    const levelLabels = ['\u6E05\u4ED3','\u4F4E\u914D','\u51CF\u4ED3','\u6807\u914D','\u4E70\u5165','\u5F3A\u4E70'];
    const levelColors = ['#ef4444','#f97316','#f59e0b','#3b82f6','#34d399','#10b981'];
    if (levelBar) {
        levelBar.innerHTML = levels.map((l, i) => {
            const active = l === trade.signal_key;
            return '<div style="width:' + (active ? '40' : '20') + 'px;height:8px;border-radius:4px;background:' + (active ? levelColors[i] : 'rgba(100,116,139,0.2)') + ';transition:all 0.5s;" title="' + levelLabels[i] + '"></div>';
        }).join('');
    }
    // ETF
    const etfC = document.getElementById('erp-etf-advice');
    if (etfC && trade.etf_advice) {
        etfC.innerHTML = trade.etf_advice.map(e => {
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(100,116,139,0.1);border-radius:4px;">' +
                '<div><span style="font-size:0.75rem;color:#e2e8f0;">' + e.etf.name + '</span><span style="font-size:0.6rem;color:#64748b;margin-left:6px;">' + e.etf.code + '</span></div>' +
                '<div style="text-align:right;"><span style="font-size:0.8rem;font-weight:700;color:#f59e0b;">' + e.ratio + '</span><div style="font-size:0.55rem;color:#64748b;">' + e.reason + '</div></div></div>';
        }).join('');
    }
    // 止盈 — V2.1: 动态触发标注 (与海外版对齐)
    const tpC = document.getElementById('erp-take-profit');
    if (tpC && trade.take_profit) {
        tpC.innerHTML = trade.take_profit.map(r => {
            const triggered = r.triggered;
            const bg = triggered
                ? 'background:rgba(16,185,129,0.18);border-left:3px solid #10b981;box-shadow:0 0 8px rgba(16,185,129,0.15);'
                : 'background:rgba(16,185,129,0.06);border-left:2px solid rgba(16,185,129,0.3);';
            const currentTag = r.current
                ? ' <span style="color:#64748b;font-size:0.58rem;margin-left:4px;">[' + r.current + ']</span>'
                : '';
            const statusIcon = triggered ? '✅ ' : '';
            return '<div style="font-size:0.65rem;padding:5px 8px;border-radius:5px;' + bg + 'transition:all 0.3s;">' +
                '<div style="color:' + (triggered ? '#10b981' : '#6ee7b7') + ';font-weight:' + (triggered ? '700' : '400') + ';">' + statusIcon + r.trigger + currentTag + '</div>' +
                '<div style="color:#94a3b8;margin-top:2px;font-size:0.6rem;">\u2192 ' + r.action + '</div></div>';
        }).join('');
    }
    // 止损 — V2.1: 动态触发标注
    const slC = document.getElementById('erp-stop-loss');
    if (slC && trade.stop_loss) {
        slC.innerHTML = trade.stop_loss.map(r => {
            const c = r.color || '#f59e0b';
            const triggered = r.triggered;
            const bg = triggered
                ? 'background:' + c + '20;border-left:3px solid ' + c + ';box-shadow:0 0 8px ' + c + '25;'
                : 'background:' + c + '08;border-left:2px solid ' + c + '40;';
            const currentTag = r.current
                ? ' <span style="color:#64748b;font-size:0.58rem;margin-left:4px;">[' + r.current + ']</span>'
                : '';
            const statusIcon = triggered ? '✅ ' : '';
            return '<div style="font-size:0.65rem;padding:5px 8px;border-radius:5px;' + bg + 'transition:all 0.3s;">' +
                '<div style="color:' + c + ';font-weight:' + (triggered ? '700' : '400') + ';">' + statusIcon + r.trigger + currentTag + '</div>' +
                '<div style="color:#94a3b8;margin-top:2px;font-size:0.6rem;">\u2192 ' + r.action + '</div></div>';
        }).join('');
    }
}

function renderERPDimBars(dims, encyclopedia) {
    const container = document.getElementById('erp-dim-bars');
    if (!container || !dims) return;
    const order = ['erp_abs', 'erp_pct', 'm1_trend', 'volatility', 'credit'];
    const icons = { erp_abs: '\uD83D\uDCCA', erp_pct: '\uD83D\uDCD0', m1_trend: '\uD83D\uDCA7', volatility: '\uD83C\uDF0A', credit: '\uD83D\uDD17' };
    const encKeys = { erp_abs: 'erp_abs', erp_pct: 'erp_pct', m1_trend: 'm1_trend', volatility: 'volatility', credit: 'credit' };
    container.innerHTML = order.map(key => {
        const d = dims[key];
        if (!d) return '';
        const barColor = d.score >= 70 ? '#10b981' : (d.score >= 40 ? '#f59e0b' : '#ef4444');
        const weightPct = Math.round(d.weight * 100);
        const enc = encyclopedia[encKeys[key]];
        const encHtml = enc ? '<div id="erp-enc-' + key + '" style="display:none;margin-top:6px;padding:8px;background:rgba(59,130,246,0.08);border-radius:6px;border:1px solid rgba(59,130,246,0.2);font-size:0.63rem;color:#cbd5e1;line-height:1.6;">' +
            '<div style="color:#60a5fa;font-weight:600;margin-bottom:3px;">' + enc.title + '</div>' +
            '<div>\uD83D\uDCD6 ' + enc.what + '</div>' +
            '<div>\u2753 ' + enc.why + '</div>' +
            '<div style="color:#f59e0b;">\u26A0\uFE0F ' + enc.alert + '</div>' +
            '<div style="color:#64748b;">\uD83D\uDCDC ' + enc.history + '</div></div>' : '';
        return '<div>' +
            '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;">' +
            '<span style="font-size:0.78rem;color:#e2e8f0;">' + (icons[key]||'') + ' ' + d.label + ' <span style="color:#64748b;font-size:0.65rem;">(' + weightPct + '%)</span>' +
            (enc ? ' <span style="cursor:pointer;font-size:0.65rem;" onclick="var e=document.getElementById(\'erp-enc-' + key + '\');e.style.display=e.style.display===\'none\'?\'block\':\'none\';">\u2139\uFE0F</span>' : '') +
            '</span>' +
            '<span style="font-size:0.82rem;font-weight:700;color:' + barColor + ';">' + d.score + '</span></div>' +
            '<div style="height:8px;background:rgba(100,116,139,0.2);border-radius:4px;overflow:hidden;position:relative;">' +
            '<div style="height:100%;width:' + d.score + '%;background:linear-gradient(90deg,' + barColor + '80,' + barColor + ');border-radius:4px;transition:width 0.8s ease;"></div>' +
            '<div style="position:absolute;top:0;left:35%;width:1px;height:100%;background:rgba(255,255,255,0.15);"></div>' +
            '<div style="position:absolute;top:0;left:70%;width:1px;height:100%;background:rgba(255,255,255,0.15);"></div></div>' +
            '<div style="font-size:0.63rem;color:#94a3b8;margin-top:3px;">' + (d.desc || '') + '</div>' +
            encHtml + '</div>';
    }).join('');
}

function renderERPGauge(signal, trade) {
    const dom = document.getElementById('erp-gauge-chart');
    if (!dom) return;
    if (_erpGaugeChart) _erpGaugeChart.dispose();
    _erpGaugeChart = echarts.init(dom);
    const score = signal.score || 50;
    const color = signal.color || '#64748b';
    _erpGaugeChart.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
            center: ['50%', '60%'], radius: '88%',
            itemStyle: { color: color },
            progress: { show: true, width: 16, roundCap: true },
            pointer: { show: false },
            axisLine: { lineStyle: { width: 16, color: [[0.25, '#ef4444'], [0.40, '#f59e0b'], [0.55, '#3b82f6'], [0.70, '#34d399'], [1, '#10b981']] } },
            axisTick: { show: false }, splitLine: { show: false },
            axisLabel: {
                distance: 22, fontSize: 9, color: '#64748b',
                formatter: function(v) { if(v===0) return '\u6E05\u4ED3'; if(v===25) return '\u4F4E\u914D'; if(v===40) return '\u51CF\u4ED3'; if(v===55) return '\u6807\u914D'; if(v===70) return '\u4E70\u5165'; if(v===100) return ''; return ''; }
            },
            detail: {
                valueAnimation: true, fontSize: 26, fontWeight: 'bold', color: color,
                offsetCenter: [0, '10%'],
                formatter: function(v) { return v + '\n' + (signal.label || ''); }
            },
            data: [{ value: score }]
        }]
    });
    // 信号矩阵
    const matrix = document.getElementById('erp-signal-matrix');
    if (matrix && trade) {
        matrix.innerHTML = (trade.resonance_label || '') + ' | \u4ED3\u4F4D\u5EFA\u8BAE: <span style="color:' + color + ';font-weight:700;">' + (signal.position || '--') + '</span>';
    }
}

function renderERPHistoryChart(chart, signalData) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom) return;
    if (_erpHistoryChart) _erpHistoryChart.dispose();
    _erpHistoryChart = echarts.init(dom);
    const stats = chart.stats || {};
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);

    // V3.0: 动态标题
    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) {
        const yrs = stats.date_range_years || '?';
        titleEl.textContent = '\u{1F4C8} ERP \u5386\u53F2\u8D70\u52BF (\u8FD1' + yrs + '\u5E74) \u00B7 \u56DB\u6863\u533A\u95F4\u53EF\u89C6\u5316';
    }

    // V3.0: KPI 卡片
    renderERPChartKPIs(stats, signalData);

    // V3.0: markArea 四档色带 (对标 AIAE History Chart 模式)
    const markAreaData = [
        [{ yAxis: stats.strong_buy_line, itemStyle: { color: 'rgba(16,185,129,0.08)' } }, { yAxis: (stats.max || 8) + 0.5 }],
        [{ yAxis: stats.overweight_line, itemStyle: { color: 'rgba(16,185,129,0.03)' } }, { yAxis: stats.strong_buy_line }],
        [{ yAxis: stats.underweight_line, itemStyle: { color: 'transparent' } }, { yAxis: stats.overweight_line }],
        [{ yAxis: stats.danger_line, itemStyle: { color: 'rgba(239,68,68,0.04)' } }, { yAxis: stats.underweight_line }],
        [{ yAxis: (stats.min || 2) - 0.5, itemStyle: { color: 'rgba(239,68,68,0.08)' } }, { yAxis: stats.danger_line }],
    ];

    // V3.0: markPoint — 当前值 + 历史极值
    const markPointData = [];
    const lastDate = chart.dates[chart.dates.length - 1];
    if (stats.current != null) {
        markPointData.push({
            coord: [lastDate, stats.current],
            name: '\u5F53\u524D', symbol: 'pin', symbolSize: 44,
            itemStyle: { color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
            label: { formatter: '{@[1]}%', color: '#fff', fontSize: 10, fontWeight: 700 }
        });
    }
    // 极值标注
    const extremes = stats.extremes || [];
    extremes.forEach(e => {
        markPointData.push({
            coord: [e.date, e.value],
            name: e.type === 'max' ? '\u5386\u53F2\u6700\u9AD8' : '\u5386\u53F2\u6700\u4F4E',
            symbol: e.type === 'max' ? 'triangle' : 'arrow',
            symbolSize: 12, symbolRotate: e.type === 'min' ? 180 : 0,
            itemStyle: { color: e.type === 'max' ? '#10b981' : '#ef4444' },
            label: { show: true, formatter: e.value + '%', fontSize: 9, color: e.type === 'max' ? '#10b981' : '#ef4444', position: e.type === 'max' ? 'top' : 'bottom' }
        });
    });

    // 区间判定函数
    function getZoneLabel(v) {
        if (v >= (stats.strong_buy_line || 99)) return '\uD83D\uDFE2 \u5F3A\u4E70\u533A';
        if (v >= (stats.overweight_line || 99)) return '\uD83D\uDD35 \u8D85\u914D\u533A';
        if (v >= (stats.underweight_line || -99)) return '\u26AA \u4E2D\u6027\u533A';
        if (v >= (stats.danger_line || -99)) return '\uD83D\uDFE0 \u4F4E\u914D\u533A';
        return '\uD83D\uDD34 \u5371\u9669\u533A';
    }

    const legendData = ['ERP', 'PE-TTM', '10Y\u56FD\u503A'];
    if (hasM1) legendData.push('M1\u540C\u6BD4');

    _erpHistoryChart.setOption({
        tooltip: {
            trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155',
            textStyle: { fontSize: 11, color: '#e2e8f0' },
            formatter: function(params) {
                let r = '<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">' + params[0].axisValue + '</div>';
                params.forEach(p => {
                    if (p.value != null) {
                        const unit = p.seriesName === 'PE-TTM' ? 'x' : '%';
                        r += '<div>' + p.marker + ' ' + p.seriesName + ': <b>' + p.value + unit + '</b></div>';
                    }
                });
                // 找到 ERP 值并标注区间
                const erpParam = params.find(p => p.seriesName === 'ERP');
                if (erpParam && erpParam.value != null) {
                    r += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;">' + getZoneLabel(erpParam.value) + '</div>';
                }
                return r;
            }
        },
        legend: {
            data: legendData, top: 0,
            textStyle: { color: '#94a3b8', fontSize: 10 },
            selected: { '10Y\u56FD\u503A': false }
        },
        toolbox: {
            right: 20, top: 0,
            feature: {
                saveAsImage: { title: '\u4FDD\u5B58', pixelRatio: 2, backgroundColor: '#0f172a' },
                restore: { title: '\u91CD\u7F6E' }
            },
            iconStyle: { borderColor: '#64748b' }
        },
        grid: { top: 40, bottom: 55, left: 50, right: hasM1 ? 90 : 50 },
        dataZoom: [
            { type: 'inside', start: 65, end: 100 },
            { type: 'slider', height: 16, bottom: 4, borderColor: 'rgba(255,255,255,0.06)',
              fillerColor: 'rgba(245,158,11,0.12)', handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
              textStyle: { color: '#64748b', fontSize: 9 },
              dataBackground: { lineStyle: { color: '#334155' }, areaStyle: { color: 'rgba(245,158,11,0.05)' } }
            }
        ],
        xAxis: {
            type: 'category', data: chart.dates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 10, formatter: function(v) { return v.substring(0, 7); } },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: [
            { type: 'value', name: 'ERP %', nameTextStyle: { color: '#64748b', fontSize: 10 },
              axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
              splitLine: { lineStyle: { color: 'rgba(100,116,139,0.08)' } }
            },
            { type: 'value', name: 'PE-TTM', position: 'right',
              nameTextStyle: { color: '#3b82f6', fontSize: 10 },
              axisLabel: { color: '#3b82f680', fontSize: 9 },
              splitLine: { show: false }
            },
            hasM1 ? {
                type: 'value', name: 'M1%', nameTextStyle: { color: '#a78bfa', fontSize: 10 },
                position: 'right', offset: 40,
                axisLabel: { color: '#a78bfa', fontSize: 9, formatter: '{value}%' },
                splitLine: { show: false }
            } : null
        ].filter(Boolean),
        series: [
            {
                name: 'ERP', type: 'line', data: chart.erp, yAxisIndex: 0,
                lineStyle: { color: '#f59e0b', width: 2.5, shadowColor: 'rgba(245,158,11,0.2)', shadowBlur: 4 },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none', z: 10,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(245,158,11,0.12)' },
                            { offset: 1, color: 'rgba(245,158,11,0)' }
                        ]
                    }
                },
                markLine: {
                    silent: true, symbol: 'none', lineStyle: { type: 'dashed', width: 1 },
                    data: [
                        { yAxis: stats.mean, label: { formatter: '\u5747\u503C ' + stats.mean + '%', color: '#94a3b8', fontSize: 9 }, lineStyle: { color: '#64748b' } },
                        { yAxis: stats.overweight_line, label: { formatter: '\u8D85\u914D ' + stats.overweight_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98166' } },
                        { yAxis: stats.underweight_line, label: { formatter: '\u4F4E\u914D ' + stats.underweight_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444466' } },
                        { yAxis: stats.strong_buy_line, label: { formatter: '\u5F3A\u4E70 ' + stats.strong_buy_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98140', type: 'dotted' } },
                        { yAxis: stats.danger_line, label: { formatter: '\u5371\u9669 ' + stats.danger_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444440', type: 'dotted' } }
                    ]
                },
                markArea: { silent: true, data: markAreaData },
                markPoint: {
                    data: markPointData,
                    animation: true, animationDuration: 600
                }
            },
            {
                name: 'PE-TTM', type: 'line', data: chart.pe_ttm, yAxisIndex: 1,
                lineStyle: { color: '#3b82f6', width: 1.5, type: 'dashed' },
                itemStyle: { color: '#3b82f6' }, symbol: 'none'
            },
            {
                name: '10Y\u56FD\u503A', type: 'line', data: chart.yield_10y, yAxisIndex: 0,
                lineStyle: { color: '#ef4444', width: 1, type: 'dotted' },
                itemStyle: { color: '#ef4444' }, symbol: 'none'
            },
            hasM1 ? {
                name: 'M1\u540C\u6BD4', type: 'line', data: chart.m1_yoy, yAxisIndex: 2,
                lineStyle: { color: '#a78bfa', width: 2, type: 'solid' },
                itemStyle: { color: '#a78bfa' },
                symbol: 'none', smooth: true,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [{offset:0,color:'rgba(167,139,250,0.10)'},{offset:1,color:'rgba(167,139,250,0)'}]
                    }
                }
            } : null
        ].filter(Boolean)
    });
    // V3.0: resize 已由全局 handler (L2735) 统一处理，M4 fix: 移除重复注册
}

// V3.0: ERP 图表 KPI 统计卡片
function renderERPChartKPIs(stats, signalData) {
    const container = document.getElementById('erp-chart-kpis');
    if (!container) return;
    const sig = signalData || {};
    const snap = sig.current_snapshot || {};
    const pct = snap.erp_percentile || '--';
    const deviation = stats.current_vs_mean;
    const devColor = deviation > 0 ? '#10b981' : (deviation < -5 ? '#ef4444' : '#f59e0b');
    const devSign = deviation > 0 ? '+' : '';

    container.innerHTML = [
        { label: '\u5F53\u524D ERP', value: (stats.current || '--') + '%', color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
        { label: '\u5747\u503C\u504F\u79BB', value: devSign + deviation + '%', color: devColor },
        { label: '\u8FD14\u5E74\u5206\u4F4D', value: pct + '%', color: pct >= 70 ? '#10b981' : (pct <= 30 ? '#ef4444' : '#94a3b8') },
        { label: '\u8D85\u914D\u533A\u5360\u6BD4', value: (stats.buy_zone_pct || '--') + '%', color: '#10b981' },
    ].map(k => `<div style="flex:1;background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 12px;text-align:center;">
        <div style="font-size:0.65rem;color:#64748b;margin-bottom:3px;">${k.label}</div>
        <div style="font-size:1.1rem;font-weight:800;color:${k.color};">${k.value}</div>
    </div>`).join('');
}

function renderERPEncyclopedia(enc) {
    const body = document.getElementById('erp-encyclopedia-body');
    if (!body || !enc) return;
    const order = ['erp_abs', 'erp_pct', 'm1_trend', 'volatility', 'credit'];
    const colors = ['#f59e0b', '#8b5cf6', '#3b82f6', '#ec4899', '#06b6d4'];
    body.innerHTML = order.map((key, i) => {
        const e = enc[key];
        if (!e) return '';
        const c = colors[i];
        return '<div style="background:rgba(15,23,42,0.6);border:1px solid ' + c + '30;border-radius:8px;padding:12px;">' +
            '<div style="font-size:0.8rem;font-weight:600;color:' + c + ';margin-bottom:6px;">' + e.title + '</div>' +
            '<div style="font-size:0.65rem;color:#cbd5e1;line-height:1.7;">' +
            '<div style="margin-bottom:4px;">\uD83D\uDCD6 <b>\u662F\u4EC0\u4E48:</b> ' + e.what + '</div>' +
            '<div style="margin-bottom:4px;">\u2753 <b>\u4E3A\u4EC0\u4E48\u91CD\u8981:</b> ' + e.why + '</div>' +
            '<div style="margin-bottom:4px;color:#f59e0b;">\u26A0\uFE0F <b>\u8B66\u793A:</b> ' + e.alert + '</div>' +
            '<div style="color:#64748b;">\uD83D\uDCDC <b>\u5386\u53F2:</b> ' + e.history + '</div></div></div>';
    }).join('');
}

function renderERPDiagnosis(cards) {
    const container = document.getElementById('erp-diagnosis-cards');
    if (!container) return;
    const typeMap = {
        success: { bg: 'rgba(16,185,129,0.08)', border: '#10b981', icon: '\u2705' },
        info:    { bg: 'rgba(59,130,246,0.08)', border: '#3b82f6', icon: '\u2139\uFE0F' },
        warning: { bg: 'rgba(245,158,11,0.08)', border: '#f59e0b', icon: '\u26A0\uFE0F' },
        danger:  { bg: 'rgba(239,68,68,0.08)',  border: '#ef4444', icon: '\uD83D\uDEA8' }
    };
    container.innerHTML = cards.map(c => {
        const style = typeMap[c.type] || typeMap.info;
        return '<div style="background:' + style.bg + ';border:1px solid ' + style.border + '33;border-left:3px solid ' + style.border + ';border-radius:8px;padding:10px 12px;">' +
            '<div style="font-size:0.75rem;font-weight:600;color:' + style.border + ';margin-bottom:3px;">' + style.icon + ' ' + c.title + '</div>' +
            '<div style="font-size:0.65rem;color:#cbd5e1;line-height:1.5;">' + c.text + '</div></div>';
    }).join('');
}

// 窗口resize
let _usErpChart = null, _jpErpChart = null, _hkErpChart = null;
window.addEventListener('resize', () => {
    if (_erpGaugeChart) _erpGaugeChart.resize();
    if (_erpHistoryChart) _erpHistoryChart.resize();
    if (_usErpChart) _usErpChart.resize();
    if (_jpErpChart) _jpErpChart.resize();
    if (_hkErpChart) _hkErpChart.resize();
    if (_usGaugeChart) _usGaugeChart.resize();
    if (_jpGaugeChart) _jpGaugeChart.resize();
    if (_hkGaugeChart) _hkGaugeChart.resize();
});

// ============================================================
