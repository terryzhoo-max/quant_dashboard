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
        renderERPGauge(data.signal, data.trade_rules, data.position_layer);
        if (data.chart && data.chart.status === 'success') renderERPHistoryChart(data.chart, data);
        renderERPEncyclopedia(data.encyclopedia || {});
        renderERPDiagnosis(data.diagnosis || []);
        // V3.4: 仓位管理层
        if (data.position_layer) renderERPPositionLayer(data.position_layer);
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
    // V3.0: 阈值从后端读取, 消除硬编码
    const thresh = data.erp_thresholds || { bullish: 5.0, bearish: 3.5 };
    // ERP
    const erpEl = document.getElementById('erp-val-erp');
    erpEl.textContent = (snap.erp_value || '--') + '%';
    erpEl.style.color = snap.erp_value >= thresh.bullish ? '#10b981' : (snap.erp_value >= thresh.bearish ? '#f59e0b' : '#ef4444');
    document.getElementById('erp-sub-erp').textContent = '\u8FD14\u5E74 ' + (snap.erp_percentile || '--') + '% \u5206\u4F4D';
    const trendErp = document.getElementById('erp-trend-erp');
    if (snap.erp_value >= thresh.bullish) { trendErp.textContent = '\u2191'; trendErp.style.color = '#10b981'; }
    else if (snap.erp_value < thresh.bearish) { trendErp.textContent = '\u2193'; trendErp.style.color = '#ef4444'; }
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
    let html = order.map(key => {
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

    // V3.3: O7 ERP动量 + O12 市场势能修正器 (正负标签, 非进度条)
    const modifiers = ['erp_momentum', 'market_trend', 'momentum_confirm'];
    const modIcons = { erp_momentum: '\u26A1', market_trend: '\uD83C\uDF0A', momentum_confirm: '\uD83C\uDFAF' };
    const modItems = modifiers.map(key => {
        const d = dims[key];
        if (!d) return '';
        const val = d.score || 0;
        const color = val > 0 ? '#10b981' : (val < 0 ? '#ef4444' : '#64748b');
        const sign = val > 0 ? '+' : '';
        return '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:' + color + '10;border-radius:6px;border:1px solid ' + color + '25;">' +
            '<span style="font-size:0.72rem;color:#cbd5e1;">' + (modIcons[key]||'') + ' ' + (d.label||key) + '</span>' +
            '<span style="font-size:0.78rem;font-weight:700;color:' + color + ';">' + sign + val + '\u5206</span></div>';
    }).filter(Boolean);

    if (modItems.length) {
        html += '<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(100,116,139,0.2);">' +
            '<div style="font-size:0.65rem;color:#64748b;margin-bottom:5px;">\u4FEE\u6B63\u5668</div>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">' + modItems.join('') + '</div>';
        // 修正器描述 (折叠显示)
        const descItems = modifiers.map(key => {
            const d = dims[key];
            return d && d.desc ? '<div style="font-size:0.6rem;color:#94a3b8;">' + (modIcons[key]||'') + ' ' + d.desc + '</div>' : '';
        }).filter(Boolean);
        if (descItems.length) {
            html += '<div style="margin-top:4px;">' + descItems.join('') + '</div>';
        }
        html += '</div>';
    }

    container.innerHTML = html;
}

function renderERPGauge(signal, trade, posLayer) {
    const dom = document.getElementById('erp-gauge-chart');
    if (!dom) return;
    _erpGaugeChart = AC.disposeChart(_erpGaugeChart);
    _erpGaugeChart = AC.registerChart(echarts.init(dom));
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
    // V3.4: 统一仓位建议 — 优先使用 position_layer 精确仓位
    const matrix = document.getElementById('erp-signal-matrix');
    if (matrix && trade) {
        const pl = (posLayer && posLayer.status === 'success') ? posLayer.position : null;
        let posText, posColor;
        if (pl) {
            const pct = pl.suggested_position_pct;
            posColor = pct >= 60 ? '#10b981' : (pct <= 40 ? '#ef4444' : '#f59e0b');
            posText = pct + '%';
            // 显示 O16/O17 修正标签
            const mods = [];
            if (pl.o16_cap) mods.push('O16 ' + pl.o16_cap);
            if (pl.o17_boost) mods.push('O17 +10pp');
            if (mods.length) posText += ' <span style="font-size:0.6rem;color:#94a3b8;">(' + mods.join(' · ') + ')</span>';
        } else {
            posText = signal.position || '--';
            posColor = color;
        }
        matrix.innerHTML = (trade.resonance_label || '') + ' | \u4ED3\u4F4D\u5EFA\u8BAE: <span style="color:' + posColor + ';font-weight:700;">' + posText + '</span>';
    }
}

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

function _renderERPChartPIT(chart, signalData) {
    const dom = document.getElementById('erp-history-chart');
    _erpHistoryChart = AC.disposeChart(_erpHistoryChart);
    _erpHistoryChart = AC.registerChart(echarts.init(dom));
    const stats = chart.stats || {}, pit = chart.pit || {}, b = chart.bands;
    const dates = chart.dates || [], erp = chart.erp || [];
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);
    const diff = (hi, lo) => hi.map((v, i) => (v == null || lo[i] == null) ? null : +(v - lo[i]).toFixed(2));
    const yrs = pit.window_years || 4;

    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) titleEl.textContent = ' ERP 估值走势 (近' + (stats.date_range_years || '?') + '年) · 近' + yrs + '年滚动分位五档 ';

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

    _erpHistoryChart.setOption({
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
        '样本内时间占比: 危险 ' + (share.danger ?? '--') + '% · 低配 ' + (share.under ?? '--') + '% · 强买 ' + (share.strong ?? '--') +
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
        card('估值区间', z.label, z.color, ['近' + pit.window_years + '年 P' + (pct != null ? Math.round(pct) : '--'), sigText].filter(Boolean).join('<br>'), 1.8),
        card('当前 ERP', (stats.current != null ? stats.current : '--') + '%', z.color),
        card('距危险线', buf == null ? '--' : ((buf >= 0 ? '+' : '') + buf + 'pp'), bufColor,
             '危险线 ' + (pit.danger_line ?? '--') + '%' + (pit.floor_binding ? ' (绝对下限)' : '')),
        card('距低配线', bufU == null ? '--' : ((bufU >= 0 ? '+' : '') + bufU + 'pp'), bufU != null && bufU < 0 ? '#fb923c' : '#94a3b8',
             '低配线 ' + (pit.underweight_line ?? '--') + '%'),
        card('危险区时间占比', ((pit.zone_share_pct || {}).danger ?? '--') + '%', '#ef4444',
             (pit.danger_episodes || []).length + ' 段'),
    ].join('');
}

// V4.0: 估值区间工具 — 区间判定 / 区间历史段落 / σ 口径
const _ERP_ZONE_COLORS = { strong: '#10b981', over: '#34d399', neutral: '#f59e0b', under: '#fb923c', danger: '#ef4444' };

function _erpZoneOf(v, s) {
    if (v == null) return null;
    if (v >= s.strong_buy_line) return { key: 'strong', label: '🟢 强买区', color: _ERP_ZONE_COLORS.strong };
    if (v >= s.overweight_line) return { key: 'over', label: '🔵 超配区', color: _ERP_ZONE_COLORS.over };
    if (v >= s.underweight_line) return { key: 'neutral', label: '⚪ 中性区', color: _ERP_ZONE_COLORS.neutral };
    if (v >= s.danger_line) return { key: 'under', label: '🟠 低配区', color: _ERP_ZONE_COLORS.under };
    return { key: 'danger', label: '🔴 危险区', color: _ERP_ZONE_COLORS.danger };
}

// 线相对均值的 σ 倍数 (如 6.04 → "μ+1σ")
function _erpSigmaTag(line, s) {
    if (line == null || !s.std) return '';
    const k = Math.round(((line - s.mean) / s.std) * 2) / 2;
    if (k === 0) return 'μ';
    return 'μ' + (k > 0 ? '+' : '−') + Math.abs(k) + 'σ';
}

// 连续处于强买区的段落 (间隔 ≤ mergeGap 个数据点的短暂跌出视为同一段, 避免色带碎片化)
function _erpStrongBuyEpisodes(dates, erp, line, mergeGap) {
    const eps = [];
    let cur = null, gap = 0;
    for (let i = 0; i < erp.length; i++) {
        const v = erp[i];
        const inZone = v != null && v >= line;
        if (inZone) {
            if (!cur) cur = { s: i, e: i, n: 0, peak: v, peakIdx: i };
            cur.e = i; cur.n += 1; gap = 0;
            if (v > cur.peak) { cur.peak = v; cur.peakIdx = i; }
        } else if (cur) {
            gap += 1;
            if (gap > mergeGap) { eps.push(cur); cur = null; gap = 0; }
        }
    }
    if (cur) eps.push(cur);
    const last = erp.length - 1;
    eps.forEach(ep => { ep.ongoing = ep.e === last; ep.start = dates[ep.s]; ep.end = dates[ep.e]; ep.peakDate = dates[ep.peakIdx]; });
    return eps;
}

function renderERPHistoryChart(chart, signalData) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom) return;
    // V4.1: 后端提供时点一致的滚动分位区间时使用 PIT 渲染; 旧后端回退到全样本 μ±σ 静态区间
    if (chart.bands && chart.pit && Array.isArray(chart.bands.zone)) return _renderERPChartPIT(chart, signalData);
    _erpHistoryChart = AC.disposeChart(_erpHistoryChart);
    _erpHistoryChart = AC.registerChart(echarts.init(dom));
    const stats = chart.stats || {};
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);
    const dates = chart.dates || [];
    const erp = chart.erp || [];
    const sb = stats.strong_buy_line;
    const episodes = (sb != null) ? _erpStrongBuyEpisodes(dates, erp, sb, 3) : [];

    // 动态标题 (保留 section-icon 和 subtitle-pill 结构)
    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) {
        const yrs = stats.date_range_years || '?';
        const textNodes = Array.from(titleEl.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
        if (textNodes.length > 0) {
            textNodes.forEach(n => n.textContent = '');
            textNodes[0].textContent = ' ERP 估值走势 (近' + yrs + '年) ';
        } else {
            titleEl.textContent = '\u{1F4C8} ERP 估值走势 (近' + yrs + '年) · 五档估值区间';
        }
    }

    renderERPChartKPIs(stats, signalData, episodes);
    _renderERPChartNote(dom, stats, episodes);

    // 横向估值色带: 强买区显著加强, 其余区间保持低噪
    const markAreaData = [
        [{ yAxis: sb, name: '强买区 ≥' + sb + '%',
           itemStyle: { color: 'rgba(16,185,129,0.13)' },
           label: { show: true, position: 'insideTopLeft', color: '#10b981', fontSize: 10, fontWeight: 700 } },
         { yAxis: 'max' }],
        [{ yAxis: stats.overweight_line, itemStyle: { color: 'rgba(16,185,129,0.04)' } }, { yAxis: sb }],
        [{ yAxis: stats.underweight_line, itemStyle: { color: 'transparent' } }, { yAxis: stats.overweight_line }],
        [{ yAxis: stats.danger_line, itemStyle: { color: 'rgba(239,68,68,0.04)' } }, { yAxis: stats.underweight_line }],
        [{ yAxis: stats.danger_line, itemStyle: { color: 'rgba(239,68,68,0.07)' } }, { yAxis: 'min' }],
    ];

    // 纵向色带: 历史上每一段进入强买区的时间窗口
    const episodeAreas = episodes.map(ep => [
        { xAxis: ep.start, itemStyle: { color: ep.ongoing ? 'rgba(16,185,129,0.22)' : 'rgba(16,185,129,0.10)' },
          label: { show: ep.n >= 10 || ep.ongoing, position: 'insideTop', color: '#10b981', fontSize: 9,
                   formatter: ep.ongoing ? '当前' : (ep.start.substring(0, 7)) } },
        { xAxis: ep.end }
    ]);

    // 当前值 + 历史极值
    const markPointData = [];
    const lastDate = dates[dates.length - 1];
    const curZone = _erpZoneOf(stats.current, stats);
    if (stats.current != null) {
        markPointData.push({
            coord: [lastDate, stats.current], name: '当前', symbol: 'pin', symbolSize: 46,
            itemStyle: { color: curZone ? curZone.color : '#f59e0b', borderColor: '#0f172a', borderWidth: 1 },
            label: { formatter: stats.current + '%', color: '#fff', fontSize: 10, fontWeight: 700 }
        });
    }
    (stats.extremes || []).forEach(e => {
        markPointData.push({
            coord: [e.date, e.value],
            name: e.type === 'max' ? '历史最高' : '历史最低',
            symbol: e.type === 'max' ? 'triangle' : 'arrow',
            symbolSize: 12, symbolRotate: e.type === 'min' ? 180 : 0,
            itemStyle: { color: e.type === 'max' ? '#10b981' : '#ef4444' },
            label: { show: true, formatter: e.value + '%', fontSize: 9, color: e.type === 'max' ? '#10b981' : '#ef4444', position: e.type === 'max' ? 'top' : 'bottom' }
        });
    });

    const legendData = ['ERP', '强买区间', 'PE-TTM', '10Y国债'];
    if (hasM1) legendData.push('M1同比');
    const tag = line => _erpSigmaTag(line, stats);

    _erpHistoryChart.setOption({
        tooltip: {
            trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155',
            textStyle: { fontSize: 11, color: '#e2e8f0' },
            formatter: function(params) {
                let r = '<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">' + params[0].axisValue + '</div>';
                params.forEach(p => {
                    if (p.value != null && p.seriesName !== '强买区间') {
                        const unit = p.seriesName === 'PE-TTM' ? 'x' : '%';
                        r += '<div>' + p.marker + ' ' + p.seriesName + ': <b>' + p.value + unit + '</b></div>';
                    }
                });
                const erpParam = params.find(p => p.seriesName === 'ERP');
                if (erpParam && erpParam.value != null) {
                    const z = _erpZoneOf(erpParam.value, stats);
                    const gap = (erpParam.value - sb);
                    r += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;">' +
                         '<span style="color:' + z.color + ';font-weight:700;">' + z.label + '</span>' +
                         ' <span style="color:#64748b;">· 距强买线 ' + (gap >= 0 ? '+' : '') + gap.toFixed(2) + 'pp</span></div>';
                }
                return r;
            }
        },
        legend: {
            data: legendData, top: 0,
            textStyle: { color: '#94a3b8', fontSize: 10 },
            selected: { '10Y国债': false }
        },
        toolbox: {
            right: 20, top: 0,
            feature: {
                saveAsImage: { title: '保存', pixelRatio: 2, backgroundColor: '#0f172a' },
                restore: { title: '重置' }
            },
            iconStyle: { borderColor: '#64748b' }
        },
        // ERP 线按区间着色: 强买区绿色 / 危险区红色 / 其余琥珀色
        visualMap: {
            show: false, seriesIndex: 0, dimension: 1,
            pieces: [
                { gte: sb, color: _ERP_ZONE_COLORS.strong },
                { lt: stats.danger_line, color: _ERP_ZONE_COLORS.danger },
                { gte: stats.danger_line, lt: sb, color: _ERP_ZONE_COLORS.neutral }
            ]
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
            type: 'category', data: dates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 10, formatter: function(v) { return v.substring(0, 7); } },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: [
            { type: 'value', name: 'ERP %', nameTextStyle: { color: '#64748b', fontSize: 10 },
              // 纵轴贴合可见数据, 避免被色带拉到 0% 而压缩强买区
              min: v => Math.max(0, Math.floor(v.min - 0.5)),
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
                name: 'ERP', type: 'line', data: erp, yAxisIndex: 0,
                lineStyle: { width: 2.5, shadowColor: 'rgba(245,158,11,0.2)', shadowBlur: 4 },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none', z: 10,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(245,158,11,0.10)' },
                            { offset: 1, color: 'rgba(245,158,11,0)' }
                        ]
                    }
                },
                markLine: {
                    silent: true, symbol: 'none', lineStyle: { type: 'dashed', width: 1 },
                    data: [
                        { yAxis: stats.mean, label: { formatter: '均值μ ' + stats.mean + '%', color: '#94a3b8', fontSize: 9 }, lineStyle: { color: '#64748b' } },
                        { yAxis: sb, label: { formatter: '强买线 ' + sb + '% (' + tag(sb) + ')', color: '#10b981', fontSize: 10, fontWeight: 700, position: 'insideEndTop' }, lineStyle: { color: '#10b981', type: 'solid', width: 1.4 } },
                        { yAxis: stats.overweight_line, label: { formatter: '超配 ' + stats.overweight_line + '% (' + tag(stats.overweight_line) + ')', color: '#34d399', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#34d39966' } },
                        { yAxis: stats.underweight_line, label: { formatter: '低配 ' + stats.underweight_line + '% (' + tag(stats.underweight_line) + ')', color: '#fb923c', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#fb923c66' } },
                        { yAxis: stats.danger_line, label: { formatter: '危险线 ' + stats.danger_line + '% (' + tag(stats.danger_line) + ')', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef4444aa', type: 'solid', width: 1 } }
                    ]
                },
                markArea: { silent: true, data: markAreaData },
                markPoint: { data: markPointData, animation: true, animationDuration: 600 }
            },
            {
                // 仅承载纵向强买区间色带, 可通过图例开关
                name: '强买区间', type: 'line', data: [], yAxisIndex: 0,
                itemStyle: { color: '#10b981' }, lineStyle: { opacity: 0 }, symbol: 'none',
                markArea: { silent: true, data: episodeAreas }
            },
            {
                name: 'PE-TTM', type: 'line', data: chart.pe_ttm, yAxisIndex: 1,
                lineStyle: { color: '#3b82f6', width: 1.5, type: 'dashed' },
                itemStyle: { color: '#3b82f6' }, symbol: 'none'
            },
            {
                name: '10Y国债', type: 'line', data: chart.yield_10y, yAxisIndex: 0,
                lineStyle: { color: '#ef4444', width: 1, type: 'dotted' },
                itemStyle: { color: '#ef4444' }, symbol: 'none'
            },
            hasM1 ? {
                name: 'M1同比', type: 'line', data: chart.m1_yoy, yAxisIndex: 2,
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
}

// 口径说明: 区间来自全样本 μ/σ (含后视信息); 估值区间 ≠ 交易信号
function _renderERPChartNote(dom, stats, episodes) {
    let note = document.getElementById('erp-chart-note');
    if (!note) {
        note = document.createElement('div');
        note.id = 'erp-chart-note';
        note.style.cssText = 'margin-top:6px;font-size:0.65rem;line-height:1.5;color:#64748b;';
        dom.parentNode.insertBefore(note, dom.nextSibling);
    }
    const n = episodes.length;
    note.textContent = '区间口径: 全样本 μ=' + stats.mean + '%, σ=' + stats.std +
        '%，强买线=μ+1σ。历史区间使用了其后的数据 (含后视)，仅用于估值定位。' +
        '样本内共 ' + n + ' 段强买区间 (绿色纵带)。估值区间≠交易信号，仓位以上方综合信号为准。';
}

// ERP 图表 KPI 卡片: 新增"估值区间"状态卡, 并并列展示综合信号, 防止把估值区间误读为买入信号
function renderERPChartKPIs(stats, signalData, episodes) {
    const container = document.getElementById('erp-chart-kpis');
    if (!container) return;
    const sig = signalData || {};
    const snap = sig.current_snapshot || {};
    const signal = sig.signal || {};
    const pct = snap.erp_percentile || '--';
    const deviation = stats.current_vs_mean;
    const devColor = deviation > 0 ? '#10b981' : (deviation < -5 ? '#ef4444' : '#f59e0b');
    const devSign = deviation > 0 ? '+' : '';
    const zone = _erpZoneOf(stats.current, stats) || { label: '--', color: '#94a3b8', key: '' };
    const sb = stats.strong_buy_line;
    const gap = (stats.current != null && sb != null) ? (stats.current - sb) : null;
    const curEp = (episodes || []).find(ep => ep.ongoing);
    let zoneSub = '';
    if (zone.key === 'strong' && curEp) {
        zoneSub = '已持续 ' + curEp.n + ' 个数据点 · 高出强买线 ' + gap.toFixed(2) + 'pp';
    } else if (gap != null) {
        zoneSub = '距强买线 ' + (gap >= 0 ? '+' : '') + gap.toFixed(2) + 'pp';
    }
    const sigText = signal.label ? ('综合信号: ' + (signal.emoji || '') + signal.label +
        (signal.score != null ? ' ' + signal.score : '') + (signal.position ? ' · ' + signal.position : '')) : '';

    const card = (label, value, color, sub, flex) => `<div style="flex:${flex || 1};min-width:0;background:rgba(15,23,42,0.6);border:1px solid ${flex ? color + '55' : 'rgba(255,255,255,0.06)'};border-radius:8px;padding:8px 12px;text-align:center;">
        <div style="font-size:0.65rem;color:#64748b;margin-bottom:3px;">${label}</div>
        <div style="font-size:1.1rem;font-weight:800;color:${color};">${value}</div>
        ${sub ? `<div style="font-size:0.6rem;color:#94a3b8;margin-top:2px;">${sub}</div>` : ''}
    </div>`;

    container.innerHTML = [
        card('估值区间', zone.label, zone.color, [zoneSub, sigText].filter(Boolean).join('<br>'), 1.8),
        card('当前 ERP', (stats.current != null ? stats.current : '--') + '%', zone.color),
        card('均值偏离', devSign + deviation + '%', devColor),
        card('近4年分位', pct + '%', pct >= 70 ? '#10b981' : (pct <= 30 ? '#ef4444' : '#94a3b8')),
        card('历史超配区占比', (stats.buy_zone_pct || '--') + '%', '#34d399', '≥' + _erpSigmaTag(stats.overweight_line, stats)),
    ].join('');
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

// V3.4: 仓位管理层渲染 (O16 趋势 + O17 换手率 + 仓位建议)
function renderERPPositionLayer(pl) {
    if (!pl || pl.status !== 'success') return;
    const trend = pl.trend || {};
    const vol = pl.volume || {};
    const pos = pl.position || {};

    // O16 趋势
    const trendColors = { bullish: '#10b981', neutral: '#94a3b8', weak: '#f59e0b', bearish: '#ef4444' };
    const trendColor = trendColors[trend.status] || '#94a3b8';
    const trendCard = document.getElementById('erp-pl-trend');
    if (trendCard) trendCard.style.borderColor = trendColor + '40';
    const te = document.getElementById('erp-pl-trend-emoji');
    if (te) te.textContent = trend.emoji || '⚪';
    const tl = document.getElementById('erp-pl-trend-label');
    if (tl) { tl.textContent = trend.label || '--'; tl.style.color = trendColor; }
    const td = document.getElementById('erp-pl-trend-detail');
    if (td) td.textContent = 'PE ' + (trend.pe_current || '--') + ' · MA60 ' + (trend.pe_ma60 || '--') + ' · MA120 ' + (trend.pe_ma120 || '--');

    // O17 换手率
    const zs = vol.zscore != null ? vol.zscore : '--';
    const volColor = vol.signal === 'high_conviction' ? '#10b981' : (vol.signal === 'low_activity' ? '#ef4444' : '#94a3b8');
    const volLabels = { high_conviction: '🔥 放量确认', low_activity: '💤 缩量冷淡', neutral: '📊 正常水平' };
    const zsEl = document.getElementById('erp-pl-vol-zscore');
    if (zsEl) { zsEl.textContent = typeof zs === 'number' ? (zs >= 0 ? '+' : '') + zs.toFixed(2) : zs; zsEl.style.color = volColor; }
    const vsEl = document.getElementById('erp-pl-vol-signal');
    if (vsEl) { vsEl.textContent = volLabels[vol.signal] || 'z-score'; vsEl.style.color = volColor; }
    const vdEl = document.getElementById('erp-pl-vol-detail');
    if (vdEl) vdEl.textContent = '换手率 ' + (vol.turnover_rate || '--') + '%';
    const volCard = document.getElementById('erp-pl-volume');
    if (volCard) volCard.style.borderColor = volColor + '40';

    // 仓位建议
    const posVal = document.getElementById('erp-pl-pos-value');
    if (posVal) {
        posVal.textContent = (pos.suggested_position_pct || '--') + '%';
        const pc = pos.suggested_position_pct || 50;
        posVal.style.color = pc >= 60 ? '#10b981' : (pc <= 40 ? '#ef4444' : '#f59e0b');
    }
    const posBase = document.getElementById('erp-pl-pos-base');
    if (posBase) posBase.textContent = '基础 ' + (pos.base_position_pct || '--') + '% (Score=' + (pos.score || '--') + ')';
    const posMods = document.getElementById('erp-pl-pos-mods');
    if (posMods) {
        const parts = [];
        if (pos.o16_cap) parts.push('O16: ' + pos.o16_cap);
        if (pos.o17_boost) parts.push('O17: +10pp 放量加码');
        if (!parts.length) parts.push('无修正');
        posMods.textContent = parts.join(' · ');
    }
    const posCard = document.getElementById('erp-pl-position');
    if (posCard) posCard.style.borderColor = 'rgba(245,158,11,0.3)';
}

// Phase 2: resize 已由 alphacore_utils.js 注册中心统一处理

// ============================================================
