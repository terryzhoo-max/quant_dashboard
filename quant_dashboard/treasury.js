// ============================================================
// treasury.js — 海外策略终端 JS 模块
// 海外ERP择时 + 利率择时V1.5 + 海外AIAE仓位管控
// ============================================================

// ── 页面基础功能: Tab切换 + 导航高亮 + 实时时钟 (Phase 2: 统一由 AlphaCore 工具库驱动) ──
(function _initTreasuryUI() {
    function setup() {
        AC.initNavigation();
        AC.startClock();
        AC.initTabSystem();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }
})();

// 🌐 海外ERP择时 V2.0 — 渲染引擎 (升级版)
// ============================================================
let _globalERPData = null;
let _usGaugeChart = null, _jpGaugeChart = null, _hkGaugeChart = null;
let _usErpChart = null, _jpErpChart = null, _hkErpChart = null;

async function loadGlobalERP() {
    const btn = document.getElementById('global-erp-refresh');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 加载中...'; }
    try {
        // P2-1: 12s超时 + 1次自动重试
        let resp;
        try {
            resp = await fetch('/api/v1/strategy/erp-global', { signal: AbortSignal.timeout(12000) });
        } catch (e1) {
            if (e1.name === 'TimeoutError' || e1.name === 'AbortError') {
                console.warn('[Global ERP] 首次请求超时, 自动重试...');
                resp = await fetch('/api/v1/strategy/erp-global', { signal: AbortSignal.timeout(15000) });
            } else { throw e1; }
        }
        const json = await resp.json();
        if (json.status === 'success') {
            _globalERPData = json;
            renderRegionPanel('us', json.us, '#3b82f6');
            renderRegionPanel('jp', json.jp, '#dc2626');
            // HK panel (use hk_hsi as primary)
            if (json.hk_hsi) {
                renderRegionPanel('hk', json.hk_hsi, '#a855f7');
            }
            renderGlobalAlerts('us', json.us);
            renderGlobalAlerts('jp', json.jp);
            if (json.hk_hsi) {
                renderGlobalAlerts('hk', json.hk_hsi);
            }
            renderGlobalComparison(json.global_comparison);
            renderGlobalEncyclopedia(json.us, json.jp, json.hk_hsi);
            if (json.us && json.us.chart) renderRegionChart('us', json.us.chart, '#3b82f6');
            if (json.jp && json.jp.chart) renderRegionChart('jp', json.jp.chart, '#dc2626');
            if (json.hk_hsi && json.hk_hsi.chart) renderRegionChart('hk', json.hk_hsi.chart, '#a855f7');
            const t = document.getElementById('global-erp-update-time');
            if (t) t.textContent = '更新: ' + new Date().toLocaleTimeString('zh-CN');
        } else {
            console.error('[Global ERP] Error:', json.message);
        }
    } catch (e) { console.error('[Global ERP] Fetch failed:', e); }
    if (btn) { btn.disabled = false; btn.innerHTML = '🔄 刷新全球数据'; }
}

// ---- 警示横幅 ----
function renderGlobalAlerts(region, data) {
    if (!data) return;
    const alerts = data.alerts || [];
    const el = document.getElementById('global-alert-' + region);
    if (!el) return;
    const danger = alerts.filter(a => a.level === 'danger' || a.level === 'opportunity');
    if (!danger.length) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    const flag = region === 'us' ? '🇺🇸' : region === 'jp' ? '🇯🇵' : '🇭🇰';
    el.innerHTML = danger.map(a => {
        const bg = a.level === 'danger' ? 'rgba(239,68,68,0.08)' : 'rgba(16,185,129,0.08)';
        const bc = a.level === 'danger' ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)';
        const pulse = a.pulse ? 'animation:pulse-glow 2s infinite;' : '';
        return '<div style="padding:7px 14px;border:1px solid '+bc+';background:'+bg+';border-radius:8px;font-size:0.72rem;color:#e2e8f0;'+pulse+'">' +
            flag + ' ' + a.icon + ' ' + a.text + '</div>';
    }).join('');
}

// ---- 信号色带 V2.0 ----
function renderSignalLevelBar(elId, currentKey) {
    const el = document.getElementById(elId);
    if (!el) return;
    const levels = [
        {k:'strong_buy',c:'#10b981',l:'SB'},{k:'buy',c:'#34d399',l:'B'},{k:'hold',c:'#3b82f6',l:'H'},
        {k:'reduce',c:'#f59e0b',l:'R'},{k:'underweight',c:'#f97316',l:'UW'},{k:'cash',c:'#ef4444',l:'C'}
    ];
    el.innerHTML = levels.map(lv => {
        const active = lv.k === currentKey;
        return '<div style="width:18px;height:10px;border-radius:3px;background:' + lv.c + (active ? '' : '22') + ';' +
            (active ? 'box-shadow:0 0 8px '+lv.c+';transform:scaleY(1.4);' : '') + '" title="'+lv.l+'"></div>';
    }).join('');
}

// ---- 仪表盘 V2.0 (放大+渐变弧线 + P1-3 dispose检查) ----
function renderMiniGauge(elId, score, color) {
    const el = document.getElementById(elId);
    if (!el) return;
    // P1-3: 复用已有实例，避免内存泄漏
    let chart = echarts.getInstanceByDom(el);
    if (!chart) chart = AC.registerChart(echarts.init(el));
    if (elId.startsWith('us')) _usGaugeChart = chart;
    else if (elId.startsWith('jp')) _jpGaugeChart = chart;
    else if (elId.startsWith('hk')) _hkGaugeChart = chart;
    chart.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
            pointer: { show: true, length: '60%', width: 4, itemStyle: { color: color } },
            axisLine: { lineStyle: { width: 12, color: [[0.25,'#ef4444'],[0.45,'#f59e0b'],[0.65,'#3b82f6'],[0.85,'#34d399'],[1,'#10b981']] } },
            axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
            detail: { show: true, offsetCenter: [0, '70%'], fontSize: 11, color: '#94a3b8',
                formatter: v => v.toFixed(0) + '分' },
            data: [{ value: score }]
        }]
    });
}

// ---- 主面板渲染 V2.0 ----
function renderRegionPanel(region, data, accentColor) {
    if (!data) return;
    const snap = data.current_snapshot || {};
    const sig = data.signal || {};
    const dims = data.dimensions || {};
    const trade = data.trade_rules || {};

    const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setC = (id, c) => { const el = document.getElementById(id); if (el) el.style.color = c; };

    // Hero ERP Card
    const erpVal = (snap.erp_value||0);
    setT(region+'-val-erp', erpVal.toFixed(2) + '%');
    setC(region+'-val-erp', erpVal >= 3 ? '#10b981' : erpVal >= 1 ? '#f59e0b' : '#ef4444');
    // Hero card border glow based on signal
    const heroCard = document.getElementById(region+'-hero-card');
    if (heroCard) {
        heroCard.style.borderColor = (sig.color||accentColor) + '44';
        heroCard.style.boxShadow = '0 0 24px ' + (sig.color||accentColor) + '15';
    }

    // Aux metrics
    setT(region+'-val-pe', (snap.pe_ttm||0).toFixed(1) + 'x');
    setT(region+'-val-yield', (snap.yield_10y||0).toFixed(2) + '%');
    setT(region+'-sub-pe', 'E/Y ' + (snap.earnings_yield||0).toFixed(1) + '%');

    if (region === 'us') {
        const vix = (dims.vix||{}).vix_info || {};
        const fed = (dims.fed_liquidity||{}).fed_info || {};
        const crd = (dims.credit_spread||{}).credit_info || {};
        setT('us-val-vix', (vix.current||0).toFixed(1));
        setC('us-val-vix', (vix.current||0)>=30?'#ef4444':(vix.current||0)>=20?'#f59e0b':'#10b981');
        setT('us-sub-vix', vix.regime==='extreme_panic'?'极端恐慌':vix.regime==='high_fear'?'高恐慌':vix.regime==='elevated_high'?'明显偏高':vix.regime==='elevated'?'偏高':vix.regime==='mild_elevated'?'略偏高':vix.regime==='normal'?'正常':vix.regime==='complacent'?'偏低':'--');
        setT('us-val-rate', (fed.current||0).toFixed(2)+'%');
        setC('us-val-rate', fed.direction==='easing'?'#10b981':'#f59e0b');
        setT('us-sub-rate', fed.direction==='easing'?'宽松':'紧缩');
        setT('us-val-credit', (crd.spread||0).toFixed(1)+'%');
        setC('us-val-credit', (crd.spread||0)<=3?'#10b981':(crd.spread||0)<=5?'#f59e0b':'#ef4444');
        setT('us-sub-credit', (crd.raw_bps||0)+'bps '+(crd.trend==='tightening'?'收窄':'走阔'));
    } else if (region === 'jp') {
        const yen = (dims.yen_trend||{}).yen_info || {};
        const vol = (dims.volatility||{}).vol_info || {};
        const rate = (dims.rate_env||{}).rate_info || {};
        setT('jp-val-yen', (yen.current||0).toFixed(1));
        setC('jp-val-yen', (yen.current||0)>155?'#ef4444':(yen.current||0)>145?'#f59e0b':'#10b981');
        setT('jp-sub-yen', yen.direction==='weakening'?'日元贬值':'日元升值');
        setT('jp-val-vol', (vol.current||0).toFixed(1)+'%');
        setC('jp-val-vol', vol.regime==='extreme_panic'?'#ef4444':vol.regime==='high'?'#f59e0b':'#10b981');
        setT('jp-sub-vol', vol.pct?(vol.pct.toFixed(0)+'%分位'):'--');
        setT('jp-val-rate', (rate.jgb_now||0).toFixed(3)+'%');
        setC('jp-val-rate', rate.jgb_direction==='rising'?'#ef4444':'#10b981');
        setT('jp-sub-rate', rate.jgb_direction==='rising'?'上行(收紧)':rate.jgb_direction==='falling'?'下行(宽松)':'稳定');
    } else if (region === 'hk') {
        // HK-specific aux metrics
        const sb = (dims.southbound||{}).sb_info || {};
        const vol = (dims.vhsi||{}).vol_info || {};
        const rspread = (dims.rate_spread||{}).spread_info || {};
        // Blended Rf
        setT('hk-val-yield', (snap.blended_rf||snap.yield_10y||0).toFixed(2)+'%');
        // Southbound
        const sbWeekly = sb.weekly||0;
        setT('hk-val-sb', (sbWeekly>=0?'+':'')+sbWeekly.toFixed(0)+'亿');
        setC('hk-val-sb', sbWeekly>0?'#10b981':'#ef4444');
        setT('hk-sub-sb', sb.direction==='inflow'?'净流入':'净流出');
        // HSI Vol
        setT('hk-val-vol', (vol.current||0).toFixed(1)+'%');
        setC('hk-val-vol', vol.regime==='extreme_panic'?'#ef4444':vol.regime==='high'?'#f59e0b':'#10b981');
        setT('hk-sub-vol', vol.pct?(vol.pct.toFixed(0)+'%分位'):'--');
        // Rate spread
        const spread = rspread.spread||0;
        setT('hk-val-spread', (spread>=0?'+':'')+spread.toFixed(1)+'%');
        setC('hk-val-spread', spread>2.5?'#ef4444':spread>1.5?'#f59e0b':'#10b981');
        setT('hk-sub-spread', rspread.trend==='widening'?'走阔↑':rspread.trend==='narrowing'?'收窄↓':'稳定');
    }

    // Signal Decision Banner V2.0
    const banner = document.getElementById(region+'-signal-banner');
    if (banner && sig.color) {
        banner.style.background = (sig.color||'#94a3b8') + '12';
        banner.style.borderColor = (sig.color||'#94a3b8') + '44';
    }
    setT(region+'-composite-score', sig.score||'--');
    setC(region+'-composite-score', sig.color||'#94a3b8');
    const sigLabel = document.getElementById(region+'-signal-label');
    if (sigLabel) {
        sigLabel.textContent = (sig.emoji||'')+' '+(sig.label||'');
        sigLabel.style.color = sig.color||'#94a3b8';
    }
    const sigPos = document.getElementById(region+'-signal-pos');
    if (sigPos) sigPos.textContent = '仓位: '+(sig.position||'--');

    // Signal level bar
    renderSignalLevelBar(region+'-signal-level-bar', sig.key||'hold');

    // Signal badge
    const badge = document.getElementById(region+'-signal-badge');
    if (badge) {
        badge.textContent = (sig.emoji||'') + ' ' + (sig.label||'');
        badge.style.background = (sig.color||'#94a3b8') + '22';
        badge.style.color = sig.color||'#94a3b8';
        badge.style.border = '1px solid '+(sig.color||'#94a3b8')+'44';
    }

    // ETF配置
    const etfEl = document.getElementById(region+'-etf-advice');
    if (etfEl && trade.etf_advice) {
        etfEl.innerHTML = trade.etf_advice.map(e =>
            '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(100,116,139,0.1);"><span>'+(e.etf?e.etf.name:'')+'</span><span style="color:#fbbf24;font-weight:600;">'+e.ratio+'</span></div>'
        ).join('');
    }

    // 止盈规则
    const tpEl = document.getElementById(region+'-take-profit');
    if (tpEl && trade.take_profit) {
        tpEl.innerHTML = trade.take_profit.map(r => {
            const triggered = r.triggered;
            const bg = triggered ? 'background:rgba(16,185,129,0.12);border-left:2px solid #10b981;padding-left:6px;border-radius:3px;' : '';
            const currentTag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.58rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:2px 0;margin-bottom:2px;'+bg+'"><span style="color:#10b981;">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+currentTag+'</div>';
        }).join('');
    }

    // 止损规则
    const slEl = document.getElementById(region+'-stop-loss');
    if (slEl && trade.stop_loss) {
        slEl.innerHTML = trade.stop_loss.map(r => {
            const triggered = r.triggered;
            const trigColor = r.color || '#f59e0b';
            const bg = triggered ? 'background:rgba('+(trigColor==='#10b981'?'16,185,129':'239,68,68')+',0.12);border-left:2px solid '+trigColor+';padding-left:6px;border-radius:3px;' : '';
            const currentTag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.58rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:2px 0;margin-bottom:2px;'+bg+'"><span style="color:'+trigColor+';">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+currentTag+'</div>';
        }).join('');
    }

    // 共振标签
    const resEl = document.getElementById('global-resonance-'+region);
    if (resEl && trade.resonance_label) {
        const flag = region==='us'?'🇺🇸':region==='jp'?'🇯🇵':'🇭🇰';
        resEl.textContent = flag + ' ' + trade.resonance_label;
    }

    // 仪表盘 V2.0 (放大)
    setTimeout(() => renderMiniGauge(region+'-gauge-chart', sig.score||0, accentColor), 50);

    // 五维评分条 V2.0 (增强版)
    const barsEl = document.getElementById(region+'-dim-bars');
    if (barsEl) {
        barsEl.innerHTML = Object.keys(dims).map(k => {
            const d = dims[k]; const s = d.score||0;
            const w = d.weight?(d.weight*100).toFixed(0)+'%':'';
            const bc = s>=70?'#10b981':s>=40?'#f59e0b':'#ef4444';
            return '<div class="erp-dim-row">' +
                '<span class="erp-dim-label">'+(d.label||k)+' <span class="erp-dim-weight">'+w+'</span></span>' +
                '<div class="erp-dim-track"><div class="erp-dim-fill" style="width:'+s+'%;background:linear-gradient(90deg,'+bc+'cc,'+bc+');"></div></div>' +
                '<span class="erp-dim-score" style="color:'+bc+';">'+s.toFixed(0)+'</span></div>';
        }).join('');
    }

    // 诊断卡片 V2.0 (2列)
    const diagEl = document.getElementById(region+'-diagnosis');
    if (diagEl && data.diagnosis) {
        const typeMap = {
            success: {bg:'rgba(16,185,129,0.06)',border:'#10b981',icon:'✅'},
            info: {bg:'rgba(59,130,246,0.06)',border:'#3b82f6',icon:'ℹ️'},
            warning: {bg:'rgba(245,158,11,0.06)',border:'#f59e0b',icon:'⚠️'},
            danger: {bg:'rgba(239,68,68,0.06)',border:'#ef4444',icon:'🔴'}
        };
        diagEl.innerHTML = data.diagnosis.map(c => {
            const st = typeMap[c.type]||typeMap.info;
            return '<div style="background:'+st.bg+';border:1px solid '+st.border+'33;border-left:3px solid '+st.border+';border-radius:8px;padding:10px 12px;">' +
                '<div style="font-size:0.68rem;font-weight:700;color:'+st.border+';margin-bottom:4px;">'+st.icon+' '+c.title+'</div>' +
                '<div style="font-size:0.6rem;color:#cbd5e1;line-height:1.5;">'+c.text+'</div></div>';
        }).join('');
    }
}

// ---- 规则百科 ----
function renderGlobalEncyclopedia(usData, jpData, hkData) {
    const el = document.getElementById('global-encyclopedia-body');
    if (!el) return;
    const usEnc = (usData||{}).encyclopedia || {};
    const jpEnc = (jpData||{}).encyclopedia || {};
    const hkEnc = (hkData||{}).encyclopedia || {};
    let html = '<div><h4 style="margin:0 0 8px;font-size:0.8rem;color:#60a5fa;">🇺🇸 美股五维指标</h4>';
    for (const [k,v] of Object.entries(usEnc)) {
        html += '<div style="background:rgba(59,130,246,0.04);border:1px solid rgba(59,130,246,0.15);border-radius:6px;padding:8px;margin-bottom:6px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:#60a5fa;margin-bottom:3px;">'+v.title+'</div>' +
            '<div style="font-size:0.62rem;color:#cbd5e1;line-height:1.5;">' +
            '<b style="color:#94a3b8;">是什么:</b> '+v.what+'<br>' +
            '<b style="color:#94a3b8;">为什么:</b> '+v.why+'<br>' +
            '<b style="color:#f59e0b;">⚠️ 警示:</b> <span style="color:#f59e0b;">'+v.alert+'</span>' +
            (v.history ? '<br><b style="color:#94a3b8;">📊 历史:</b> '+v.history : '') +
            '</div></div>';
    }
    html += '</div><div><h4 style="margin:0 0 8px;font-size:0.8rem;color:#f87171;">🇯🇵 日本五维指标</h4>';
    for (const [k,v] of Object.entries(jpEnc)) {
        html += '<div style="background:rgba(220,38,38,0.04);border:1px solid rgba(220,38,38,0.15);border-radius:6px;padding:8px;margin-bottom:6px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:#f87171;margin-bottom:3px;">'+v.title+'</div>' +
            '<div style="font-size:0.62rem;color:#cbd5e1;line-height:1.5;">' +
            '<b style="color:#94a3b8;">是什么:</b> '+v.what+'<br>' +
            '<b style="color:#94a3b8;">为什么:</b> '+v.why+'<br>' +
            '<b style="color:#f59e0b;">⚠️ 警示:</b> <span style="color:#f59e0b;">'+v.alert+'</span>' +
            '</div></div>';
    }
    html += '</div>';
    // HK Encyclopedia
    if (Object.keys(hkEnc).length > 0) {
        html += '<div style="grid-column:1/-1;"><h4 style="margin:0 0 8px;font-size:0.8rem;color:#c084fc;">🇭🇰 港股五维指标</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">';
        for (const [k,v] of Object.entries(hkEnc)) {
            html += '<div style="background:rgba(168,85,247,0.04);border:1px solid rgba(168,85,247,0.15);border-radius:6px;padding:8px;">' +
                '<div style="font-size:0.72rem;font-weight:600;color:#c084fc;margin-bottom:3px;">'+v.title+'</div>' +
                '<div style="font-size:0.62rem;color:#cbd5e1;line-height:1.5;">' +
                '<b style="color:#94a3b8;">是什么:</b> '+v.what+'<br>' +
                '<b style="color:#94a3b8;">为什么:</b> '+v.why+'<br>' +
                '<b style="color:#f59e0b;">⚠️ 警示:</b> <span style="color:#f59e0b;">'+v.alert+'</span>' +
                '</div></div>';
        }
        html += '</div></div>';
    }
    el.innerHTML = html;
}

// ---- 三地对比 V2.0 (含皇冠动画) ----
function renderGlobalComparison(gc) {
    if (!gc) return;
    const setT = (id,v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
    const setCS = (id,c) => { const el=document.getElementById(id); if(el) el.style.color=c; };
    const scores = {};
    ['cn','us','jp','hk'].forEach(r => {
        const d = gc[r]||{};
        scores[r] = d.score||0;
        setT('global-'+r+'-erp', (d.erp||0).toFixed(2)+'%');
        setT('global-'+r+'-score', '得分: '+(d.score||0).toFixed(0));
        const sigEl = document.getElementById('global-'+r+'-signal');
        if (sigEl) { sigEl.textContent = (d.emoji||'')+' '+(d.label||'--'); sigEl.style.color = d.color||'#94a3b8'; }

        // 决策矩阵表格
        setT('gm-'+r+'-pe', (d.pe||0).toFixed(1)+'x');
        setT('gm-'+r+'-yield', (d.yield||0).toFixed(2)+'%');
        const erpCell = document.getElementById('gm-'+r+'-erp');
        if (erpCell) { erpCell.textContent = (d.erp||0).toFixed(2)+'%'; erpCell.style.color = (d.erp||0)>=3?'#10b981':(d.erp||0)>=1?'#f59e0b':'#ef4444'; }
        const scoreCell = document.getElementById('gm-'+r+'-score');
        if (scoreCell) { scoreCell.textContent = (d.score||0).toFixed(0); scoreCell.style.color = d.color||'#94a3b8'; }
        const sigCell = document.getElementById('gm-'+r+'-signal');
        if (sigCell) { sigCell.textContent = (d.emoji||'')+' '+(d.label||'--'); sigCell.style.color = d.color||'#94a3b8'; }
    });

    // V2.0: 皇冠动画 — 最高分卡片获得皇冠
    const maxScore = Math.max(scores.cn||0, scores.us||0, scores.jp||0, scores.hk||0);
    ['cn','us','jp','hk'].forEach(r => {
        const card = document.getElementById('global-'+r+'-card');
        const crown = document.getElementById('global-'+r+'-crown');
        const d = gc[r]||{};
        if (card) {
            if (scores[r] === maxScore && maxScore > 0) {
                card.classList.add('winner');
                card.style.borderColor = (d.color||'#fbbf24') + '88';
                card.style.boxShadow = '0 0 24px '+(d.color||'#fbbf24')+'25';
                if (crown) { crown.style.display = 'block'; crown.innerHTML = '<span class="erp-crown">👑</span>'; }
            } else {
                card.classList.remove('winner');
                card.style.boxShadow = 'none';
                if (crown) crown.style.display = 'none';
            }
        }
    });

    const advEl = document.getElementById('global-advice');
    if (advEl && gc.advice) advEl.textContent = '🌍 ' + gc.advice;

    // 配置比例条
    const allocBar = document.getElementById('global-allocation-bar');
    const allocText = document.getElementById('global-allocation-text');
    if (allocBar && gc.allocation) {
        const alloc = gc.allocation;
        const colors = {cn:'#ef4444', us:'#3b82f6', jp:'#dc2626', hk:'#a855f7'};
        const flags = {cn:'🇨🇳', us:'🇺🇸', jp:'🇯🇵', hk:'🇭🇰'};
        allocBar.innerHTML = ['cn','us','jp','hk'].map(r => {
            const pct = alloc[r] || 0;
            return '<div style="width:'+pct+'%;background:linear-gradient(135deg,'+colors[r]+','+colors[r]+'bb);display:flex;align-items:center;justify-content:center;font-size:0.72rem;color:white;font-weight:700;transition:width 0.6s;">'+flags[r]+' '+pct+'%</div>';
        }).join('');
    }
    if (allocText && gc.allocation_text) {
        allocText.textContent = gc.allocation_text;
    }
}

// ---- ERP走势图 V2.0 (含买卖区间阴影) ----
function renderRegionChart(region, chart, color) {
    if (!chart || chart.status !== 'success') return;
    const el = document.getElementById(region+'-erp-chart');
    if (!el) return;
    const instance = AC.registerChart(echarts.init(el));
    if (region === 'us') _usErpChart = instance;
    else if (region === 'jp') _jpErpChart = instance;
    else if (region === 'hk') _hkErpChart = instance;
    const stats = chart.stats || {};
    instance.setOption({
        backgroundColor: 'transparent',
        grid: { top: 30, right: 12, bottom: 30, left: 40 },
        tooltip: { trigger:'axis', backgroundColor:'rgba(15,23,42,0.95)', borderColor:color+'44',
            textStyle:{color:'#e2e8f0',fontSize:11},
            formatter: p => { if (!p.length) return ''; let s='<b>'+p[0].axisValue+'</b><br/>'; p.forEach(i=>s+='<span style="color:'+i.color+'">●</span> '+i.seriesName+': <b>'+i.value+'%</b><br/>'); return s; }
        },
        xAxis: { type:'category', data:chart.dates, axisLabel:{color:'#64748b',fontSize:9,formatter:v=>v.substring(2,7)}, axisLine:{lineStyle:{color:'#334155'}} },
        yAxis: { type:'value', axisLabel:{color:'#64748b',fontSize:10,formatter:'{value}%'}, splitLine:{lineStyle:{color:'#1e293b'}} },
        series: [
            { name:'ERP', type:'line', data:chart.erp, smooth:true,
              lineStyle:{color:color,width:2.5},
              areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:color+'44'},{offset:1,color:color+'05'}]}},
              itemStyle:{color:color}, symbol:'none' },
            { name:'超配线', type:'line', data:chart.dates.map(()=>stats.overweight_line),
              lineStyle:{color:'#10b981',type:'dashed',width:1}, symbol:'none', itemStyle:{color:'#10b981'} },
            { name:'低配线', type:'line', data:chart.dates.map(()=>stats.underweight_line),
              lineStyle:{color:'#ef4444',type:'dashed',width:1}, symbol:'none', itemStyle:{color:'#ef4444'} },
        ]
    });
}

// Tab切换钩子

(function() {
    document.querySelectorAll('.st-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            if (this.dataset.report === 'st-aiae-global' && !_globalAIAEData) {
                setTimeout(loadGlobalAIAE, 100);
            }
            if (this.dataset.report === 'st-erp-global' && !_globalERPData) {
                setTimeout(loadGlobalERP, 100);
            }
            if (this.dataset.report === 'st-rates-strategy' && !_ratesData) {
                setTimeout(loadRatesStrategy, 100);
            }
        });
    });
})();

// 🏦 利率择时引擎 V1.5 — JS渲染
// ═══════════════════════════════════════════════
let _ratesData = null;
let _ratesGaugeChart = null;
let _ratesMainChart = null;

async function loadRatesStrategy() {
    const btn = document.getElementById('rates-refresh-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 加载中...'; }
    try {
        // P2-1: 12s超时 + 1次自动重试
        let resp;
        try {
            resp = await fetch('/api/v1/strategy/rates', { signal: AbortSignal.timeout(12000) });
        } catch (e1) {
            if (e1.name === 'TimeoutError' || e1.name === 'AbortError') {
                console.warn('[Rates] 首次请求超时, 自动重试...');
                resp = await fetch('/api/v1/strategy/rates', { signal: AbortSignal.timeout(15000) });
            } else { throw e1; }
        }
        const json = await resp.json();
        if (json.status === 'success' && json.data) {
            _ratesData = json.data;
            renderRatesPanel(json.data);
            const t = document.getElementById('rates-update-time');
            if (t) t.textContent = '更新: ' + new Date().toLocaleTimeString('zh-CN');
        } else {
            console.error('[Rates] Error:', json.message || json);
            _ratesShowError(json.message || '数据返回异常');
        }
    } catch (e) {
        console.error('[Rates] Fetch failed:', e);
        _ratesShowError(e.message || '网络连接失败');
    }
    if (btn) { btn.disabled = false; btn.innerHTML = '🔄 刷新利率数据'; }
}

function _ratesShowError(msg) {
    const zone = document.getElementById('rates-decision-zone');
    if (zone) {
        zone.style.display = 'block';
        zone.innerHTML = '<div style="text-align:center;padding:24px;color:#ef4444;font-size:0.82rem;">' +
            '❌ 利率数据加载失败: ' + msg +
            '<br><span style="font-size:0.65rem;color:#64748b;margin-top:6px;display:inline-block;">请检查 FRED API 连接或稍后重试</span></div>';
    }
}

function renderRatesPanel(data) {
    if (!data) return;
    const snap = data.current_snapshot || {};
    const dims = data.dimensions || {};
    const signal = data.signal || {};
    const trade = data.trade_rules || {};
    const trSig = trade.signal || signal;

    const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setC = (id, c) => { const el = document.getElementById(id); if (el) el.style.color = c; };

    const rcn = snap.regime_cn || {};

    // === Regime Badge (Hero) ===
    const regBadge = document.getElementById('rates-regime-badge');
    if (regBadge && data.buy_sell_zones) {
        const bsz = data.buy_sell_zones;
        regBadge.textContent = bsz.regime_label || '';
        regBadge.style.background = (bsz.conclusion_color||'#94a3b8') + '22';
        regBadge.style.color = bsz.conclusion_color||'#94a3b8';
        regBadge.style.border = '1px solid '+(bsz.conclusion_color||'#94a3b8')+'44';
    }

    // === ZONE 1: 快照卡片 (中文Regime + alert hint) ===
    setT('rates-val-10y', (snap.yield_10y||0).toFixed(2) + '%');
    setC('rates-val-10y', (snap.yield_10y||0)>=4.5?'#10b981':(snap.yield_10y||0)>=3.5?'#f59e0b':'#ef4444');
    const ylInfo = (dims.yield_level||{}).yield_info || {};
    setT('rates-sub-10y', (rcn.yield_level||'--') + ' | 分位'+(ylInfo.pct||0).toFixed(0)+'%');

    setT('rates-val-2y', (snap.yield_2y||0).toFixed(2) + '%');
    setC('rates-val-2y', '#e2e8f0');
    setT('rates-sub-2y', '短端 | Fed映射');

    const spreadBps = snap.spread_bps || 0;
    setT('rates-val-spread', (spreadBps >= 0 ? '+' : '') + spreadBps.toFixed(0) + 'bps');
    setC('rates-val-spread', spreadBps < 0 ? '#ef4444' : spreadBps < 50 ? '#f59e0b' : '#10b981');
    setT('rates-sub-spread', (rcn.curve||'--') + (spreadBps < 0 ? ' ⚠️' : ''));

    setT('rates-val-real', (snap.real_yield||0).toFixed(2) + '%');
    setC('rates-val-real', (snap.real_yield||0)>=2?'#10b981':(snap.real_yield||0)>=1?'#f59e0b':'#ef4444');
    setT('rates-sub-real', (rcn.real_yield||'--'));

    const momInfo = (dims.yield_momentum||{}).momentum_info || {};
    const chg3m = momInfo.chg_3m_bps || 0;
    setT('rates-val-momentum', (chg3m >= 0 ? '+' : '') + chg3m.toFixed(0) + 'bps');
    setC('rates-val-momentum', chg3m < -30 ? '#10b981' : chg3m > 30 ? '#ef4444' : '#f59e0b');
    setT('rates-sub-momentum', (rcn.momentum||'--') + (chg3m < 0 ? ' 📉' : ' 📈'));

    setT('rates-val-bei', (snap.breakeven||0).toFixed(2) + '%');
    setC('rates-val-bei', (snap.breakeven||0) > 2.5 ? '#ef4444' : '#e2e8f0');
    setT('rates-sub-bei', '通胀预期');

    // Alert hints
    const hints = data.alert_hints || {};
    setT('rates-hint-10y', hints.yield_10y || '');
    setT('rates-hint-2y', hints.yield_2y || '');
    setT('rates-hint-spread', hints.spread || '');
    setT('rates-hint-real', hints.real_yield || '');
    setT('rates-hint-momentum', hints.momentum || '');
    setT('rates-hint-bei', hints.bei || '');

    // === ZONE 2: 信号badge ===
    const badge = document.getElementById('rates-signal-badge');
    if (badge) {
        badge.textContent = (trSig.emoji||'') + ' ' + (trSig.label||'');
        badge.style.background = (trSig.color||'#94a3b8') + '22';
        badge.style.color = trSig.color||'#94a3b8';
        badge.style.border = '1px solid '+(trSig.color||'#94a3b8')+'44';
    }

    // ETF
    const etfEl = document.getElementById('rates-etf-advice');
    if (etfEl && trade.etf_advice) {
        etfEl.innerHTML = trade.etf_advice.map(e =>
            '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(100,116,139,0.1);"><span>'+(e.etf?e.etf.name:'')+'</span><span style="color:#fbbf24;font-weight:600;">'+e.ratio+'</span></div>'
        ).join('');
    }

    // 止盈 (动态高亮)
    const tpEl = document.getElementById('rates-take-profit');
    if (tpEl && trade.take_profit) {
        tpEl.innerHTML = trade.take_profit.map(r => {
            const triggered = r.triggered;
            const bg = triggered ? 'background:rgba(16,185,129,0.12);border-left:2px solid #10b981;padding-left:6px;border-radius:3px;' : '';
            const tag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.6rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:3px 0;margin-bottom:3px;'+bg+'"><span style="color:#10b981;">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+tag+'</div>';
        }).join('');
    }

    // 止损 (动态高亮)
    const slEl = document.getElementById('rates-stop-loss');
    if (slEl && trade.stop_loss) {
        slEl.innerHTML = trade.stop_loss.map(r => {
            const triggered = r.triggered;
            const trigColor = r.color || '#f59e0b';
            const bg = triggered ? 'background:rgba('+(trigColor==='#10b981'?'16,185,129':'239,68,68')+',0.12);border-left:2px solid '+trigColor+';padding-left:6px;border-radius:3px;' : '';
            const tag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.6rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:3px 0;margin-bottom:3px;'+bg+'"><span style="color:'+trigColor+';">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+tag+'</div>';
        }).join('');
    }

    // === 综合得分 + 信号标签 ===
    setT('rates-composite-score', trSig.score || '--');
    setC('rates-composite-score', trSig.color || '#94a3b8');
    const sigLabel = document.getElementById('rates-signal-label');
    if (sigLabel) {
        sigLabel.textContent = (trSig.emoji||'')+' '+(trSig.label||'')+' ('+(trSig.position||'')+')';
        sigLabel.style.color = trSig.color||'#94a3b8';
    }

    // 仪表盘
    setTimeout(() => renderRatesGauge(trSig.score||0), 50);

    // 五维评分条 (新增desc行)
    const barsEl = document.getElementById('rates-dim-bars');
    if (barsEl) {
        barsEl.innerHTML = Object.keys(dims).map(k => {
            const d = dims[k]; const s = d.score||0;
            const w = d.weight?(d.weight*100).toFixed(0)+'%':'';
            const bc = s>=70?'#10b981':s>=40?'#f59e0b':'#ef4444';
            const desc = d.desc ? '<div style="font-size:0.48rem;color:#64748b;margin-top:1px;line-height:1.2;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'+d.desc+'</div>' : '';
            return '<div style="margin-bottom:5px;">' +
                '<div style="display:flex;align-items:center;gap:5px;">' +
                '<span style="font-size:0.6rem;color:#94a3b8;width:62px;text-align:right;flex-shrink:0;">'+d.label+'<span style="color:#475569;font-size:0.5rem;"> '+w+'</span></span>' +
                '<div style="flex:1;height:5px;background:rgba(30,41,59,0.8);border-radius:3px;overflow:hidden;">' +
                '<div style="width:'+s+'%;height:100%;background:'+bc+';border-radius:3px;transition:width 0.6s;"></div></div>' +
                '<span style="font-size:0.6rem;color:'+bc+';width:24px;text-align:right;">'+s.toFixed(0)+'</span></div>'+desc+'</div>';
        }).join('');
    }

    // === ZONE 4: 配置比例条 ===
    const allocBar = document.getElementById('rates-allocation-bar');
    if (allocBar && trSig.stock_pct !== undefined) {
        const items = [
            {label:'📈 股票', pct:trSig.stock_pct, color:'#f59e0b'},
            {label:'🏦 债券', pct:trSig.bond_pct, color:'#c084fc'},
            {label:'🥇 黄金', pct:trSig.gold_pct, color:'#fbbf24'},
        ];
        allocBar.innerHTML = items.map(i =>
            '<div style="width:'+i.pct+'%;background:'+i.color+';display:flex;align-items:center;justify-content:center;font-size:0.72rem;color:white;font-weight:600;transition:width 0.5s;">'+i.label+' '+i.pct+'%</div>'
        ).join('');
        setT('rates-alloc-stock', '📈 股票 '+trSig.stock_pct+'%');
        setT('rates-alloc-bond', '🏦 债券 '+trSig.bond_pct+'%');
        setT('rates-alloc-gold', '🥇 黄金 '+trSig.gold_pct+'%');
        setT('rates-alloc-duration', '久期: '+trSig.duration);
    }

    // === 决策汇总区 ===
    if (data.buy_sell_zones) renderRatesDecisionZone(data.buy_sell_zones);

    // === 图表操作信号条 (V3.1) ===
    if (data.buy_sell_zones) renderRatesChartActionBar(data.buy_sell_zones, signal, data.alerts || []);

    // === 警示 ===
    renderRatesAlerts(data.alerts || []);

    // === 诊断 ===
    renderRatesDiagnosis(data.diagnosis || []);

    // === Tooltips ===
    if (data.card_tooltips) setupRatesTooltips(data.card_tooltips);

    // === 走势图 ===
    if (data.chart) renderRatesChart(data.chart);
}

function renderRatesGauge(score) {
    const el = document.getElementById('rates-gauge-chart');
    if (!el) return;
    _ratesGaugeChart = AC.disposeChart(_ratesGaugeChart);
    _ratesGaugeChart = AC.registerChart(echarts.init(el));
    _ratesGaugeChart.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
            pointer: { show: true, length: '55%', width: 3, itemStyle: { color: '#c084fc' } },
            axisLine: { lineStyle: { width: 8, color: [[0.2,'#ef4444'],[0.35,'#f97316'],[0.5,'#f59e0b'],[0.65,'#94a3b8'],[0.8,'#3b82f6'],[1,'#10b981']] } },
            axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
            detail: { show: false }, data: [{ value: score }]
        }]
    });
}

// V3.0→V3.1: KPI 卡片 6项 — 补充 Z-Score + 当前区间 + 倒挂占比
function renderRatesChartKPIs(stats) {
    const container = document.getElementById('rates-chart-kpis');
    if (!container || !stats) return;
    const dev = stats.current_vs_mean || 0;
    const devColor = dev > 0 ? '#10b981' : (dev < -0.5 ? '#ef4444' : '#f59e0b');
    const devSign = dev > 0 ? '+' : '';
    const pct = stats.current_pct || 0;
    const zStd = stats.std ? ((stats.current - stats.mean) / stats.std).toFixed(1) : '--';
    const zColor = Math.abs(parseFloat(zStd)) >= 1.5 ? '#ef4444' : (Math.abs(parseFloat(zStd)) >= 0.8 ? '#f59e0b' : '#94a3b8');
    const invPct = stats.inversion_pct || 0;

    container.innerHTML = [
        { label: '当前 10Y', value: (stats.current || '--') + '%', color: stats.current >= 4.5 ? '#10b981' : (stats.current >= 3.5 ? '#f59e0b' : '#ef4444') },
        { label: '均值偏离', value: devSign + dev + '%', color: devColor },
        { label: '5年分位', value: pct + '%', color: pct >= 75 ? '#10b981' : (pct <= 25 ? '#ef4444' : '#94a3b8') },
        { label: 'Z-Score', value: zStd + 'σ', color: zColor },
        { label: '当前区间', value: stats.current_zone_label || '--', color: stats.current_zone_color || '#94a3b8' },
        { label: '倒挂占比', value: invPct + '%', color: invPct > 30 ? '#ef4444' : (invPct > 10 ? '#f59e0b' : '#10b981') },
    ].map(k => `<div style="flex:1;background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 12px;text-align:center;min-width:0;">
        <div style="font-size:0.6rem;color:#64748b;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${k.label}</div>
        <div style="font-size:1rem;font-weight:800;color:${k.color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${k.value}</div>
    </div>`).join('');
}

// V3.0: 逐点区间判定 — 对标 getZoneLabel
function getYieldZoneLabel(v, zt) {
    if (!zt) return '—';
    if (v >= zt.high_zone) return '🟢 超配债券区';
    if (v >= zt.high_tilt) return '🔵 标配偏债区';
    if (v <= zt.low_zone)  return '🔴 全股票区';
    if (v <= zt.low_tilt)  return '🟠 标配偏股区';
    return '⚪ 中性均衡区';
}

function renderRatesChart(chart) {
    if (!chart || chart.status !== 'success') return;
    const el = document.getElementById('rates-chart');
    if (!el) return;
    _ratesMainChart = AC.disposeChart(_ratesMainChart);
    _ratesMainChart = AC.registerChart(echarts.init(el));
    const lines = chart.lines || {};
    const markAreas = chart.mark_areas || [];
    const pctStats = chart.percentile_stats || {};
    const stats = chart.stats || {};
    const zt = stats.zone_thresholds || {};

    // V3.1: 动态标题 (fallback: 从 dates.length 计算年限)
    const titleEl = document.getElementById('rates-chart-title');
    if (titleEl) {
        const yrs = stats.date_range_years || (chart.dates ? (chart.dates.length / 252).toFixed(1) : '?');
        titleEl.textContent = '\u{1F4CA} US 10Y Treasury \u8D70\u52BF (\u8FD1' + yrs + '\u5E74) \u00B7 \u56DB\u6863\u533A\u95F4\u53EF\u89C6\u5316';
    }

    // V3.0: KPI 卡片
    renderRatesChartKPIs(stats);

    // V3.0: markArea 四档色带
    const echartsMarkAreaData = markAreas.map(area => [
        { yAxis: area.y_from, name: area.label,
          itemStyle: { color: area.color } },
        { yAxis: area.y_to }
    ]);

    // V3.0: markPoint — 当前值 Pin + 极值
    const markPointData = [];
    const lastDate = chart.dates[chart.dates.length - 1];
    if (stats.current != null) {
        markPointData.push({
            coord: [lastDate, stats.current],
            name: '\u5F53\u524D', symbol: 'pin', symbolSize: 44,
            itemStyle: { color: stats.current_zone_color || '#c084fc' },
            label: { formatter: stats.current + '%', color: '#fff', fontSize: 10, fontWeight: 700 }
        });
    }
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

    // 主10Y曲线 + markArea色带 + markLine + markPoint
    const series = [
        { name:'10Y Yield', type:'line', data:chart.yields_10y, smooth:false,
          lineStyle:{color:'#c084fc',width:2.5, shadowColor:'rgba(192,132,252,0.2)', shadowBlur:4},
          areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#c084fc22'},{offset:1,color:'#c084fc02'}]}},
          itemStyle:{color:'#c084fc'}, symbol:'none', yAxisIndex:0, z:10,
          markArea: {
              silent: true,
              label: { show: true, position: 'insideRight', fontSize: 8, color: '#64748b', distance: 4 },
              data: echartsMarkAreaData
          },
          markLine: {
              silent: true, symbol: 'none',
              lineStyle: { type: 'dashed', width: 1 },
              data: [
                  { yAxis: lines.high_zone, name: '\u8D85\u914D ' + (lines.high_zone||'') + '%',
                    lineStyle: {color:'#10b98166'}, label:{color:'#10b981',fontSize:9,position:'insideEndTop'} },
                  { yAxis: lines.high_tilt, name: '\u504F\u503A ' + (lines.high_tilt||'') + '%',
                    lineStyle: {color:'#3b82f640',type:'dotted'}, label:{color:'#3b82f6',fontSize:9,position:'insideEndTop'} },
                  { yAxis: lines.neutral, name: 'P50=' + (lines.neutral||'') + '%',
                    lineStyle: {color:'#64748b'}, label:{color:'#94a3b8',fontSize:9} },
                  { yAxis: lines.low_tilt, name: '\u504F\u80A1 ' + (lines.low_tilt||'') + '%',
                    lineStyle: {color:'#f9731640',type:'dotted'}, label:{color:'#f97316',fontSize:9,position:'insideEndTop'} },
                  { yAxis: lines.low_zone, name: '\u5168\u80A1\u7968 ' + (lines.low_zone||'') + '%',
                    lineStyle: {color:'#ef444466'}, label:{color:'#ef4444',fontSize:9,position:'insideEndTop'} },
              ]
          },
          markPoint: {
              data: markPointData,
              animation: true, animationDuration: 600
          }
        },
    ];

    // 利差曲线 (第二Y轴) — V3.0: 倒挂红色增强
    if (chart.spreads) {
        series.push({
            name:'10Y-2Y\u5229\u5DEE', type:'bar', data:chart.spreads,
            itemStyle:{ color: function(p) { return p.data < 0 ? '#ef444499' : '#10b98155'; } },
            barWidth: '60%', yAxisIndex:1
        });
    }

    const yAxes = [
        { type:'value', name:'Yield(%)', position:'left',
          axisLabel:{color:'#64748b',fontSize:9,formatter:'{value}%'},
          splitLine:{lineStyle:{color:'rgba(100,116,139,0.08)'}},
          nameTextStyle:{color:'#64748b',fontSize:9} }
    ];
    if (chart.spreads) {
        yAxes.push({ type:'value', name:'Spread(%)', position:'right',
            axisLabel:{color:'#64748b',fontSize:9,formatter:'{value}%'},
            splitLine:{show:false}, nameTextStyle:{color:'#64748b',fontSize:9} });
    }

    _ratesMainChart.setOption({
        backgroundColor: 'transparent',
        animation: true,
        animationDuration: 1000,
        grid: { top: 40, right: chart.spreads ? 70 : 50, bottom: 55, left: 50 },
        legend: { top: 0, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:14, itemHeight:8,
                  data: ['10Y Yield', '10Y-2Y\u5229\u5DEE'] },
        toolbox: {
            right: 20, top: 0,
            feature: {
                saveAsImage: { title: '\u4FDD\u5B58', pixelRatio: 2, backgroundColor: '#0f172a' },
                restore: { title: '\u91CD\u7F6E' }
            },
            iconStyle: { borderColor: '#64748b' }
        },
        dataZoom: [
            { type: 'inside', start: 75, end: 100 },
            { type: 'slider', height: 16, bottom: 4, borderColor: 'rgba(255,255,255,0.06)',
              fillerColor: 'rgba(192,132,252,0.12)', handleStyle: { color: '#c084fc', borderColor: '#c084fc' },
              textStyle: { color: '#64748b', fontSize: 9 },
              dataBackground: { lineStyle: { color: '#334155' }, areaStyle: { color: 'rgba(192,132,252,0.05)' } }
            }
        ],
        tooltip: { trigger:'axis', backgroundColor:'rgba(15,23,42,0.95)', borderColor:'#334155',
            textStyle:{color:'#e2e8f0',fontSize:11},
            formatter: function(p) {
                if (!p.length) return '';
                let s='<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">'+p[0].axisValue+'</div>';
                p.forEach(i => {
                    if (i.value != null) {
                        s += '<div>'+i.marker+' '+i.seriesName+': <b>'+i.value+'%</b></div>';
                    }
                });
                // V3.0: 逐点区间判定 (而非固定快照)
                const yieldParam = p.find(x => x.seriesName === '10Y Yield');
                if (yieldParam && yieldParam.value != null) {
                    s += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;">'+getYieldZoneLabel(yieldParam.value, zt)+'</div>';
                }
                return s;
            }
        },
        xAxis: { type:'category', data:chart.dates, boundaryGap:false,
            axisLabel:{color:'#64748b',fontSize:10,formatter:function(v){return v.substring(0,7);}},
            axisLine:{lineStyle:{color:'#334155'}} },
        yAxis: yAxes,
        series: series,
    });
}

// V3.1: 图表区操作信号条 — 紧凑版买卖/警示提醒 (用户不用滚回顶部)
function renderRatesChartActionBar(bsz, signal, alerts) {
    const el = document.getElementById('rates-chart-action-bar');
    if (!el || !bsz) return;

    // 提取已满足的条件 (最多显示2条)
    const metBonds = (bsz.bond_buy || []).filter(c => c.met).slice(0, 2);
    const metStocks = (bsz.stock_buy || []).filter(c => c.met).slice(0, 2);
    const metDefense = (bsz.defense || []).filter(c => c.met).slice(0, 2);

    // 条件简写渲染
    const renderMet = (items, color) => items.map(c =>
        `<span style="font-size:0.58rem;color:${color};background:${color}11;padding:1px 5px;border-radius:3px;border:1px solid ${color}22;">✅ ${c.cond} <span style="color:#fbbf24;font-weight:600;">${c.val}</span></span>`
    ).join(' ');

    // 警示信号 (仅触发的)
    const alertHtml = alerts.length > 0
        ? alerts.slice(0, 2).map(a => {
            const c = a.level === 'danger' ? '#ef4444' : a.level === 'opportunity' ? '#10b981' : '#f59e0b';
            return `<span style="font-size:0.58rem;color:${c};background:${c}11;padding:1px 5px;border-radius:3px;border:1px solid ${c}22;">${a.icon} ${a.text.substring(0, 30)}${a.text.length > 30 ? '...' : ''}</span>`;
        }).join(' ')
        : '';

    // 结论 badge
    const cc = bsz.conclusion_color || '#94a3b8';
    const conclusionBadge = `<span style="font-size:0.62rem;font-weight:700;color:${cc};background:${cc}15;padding:2px 10px;border-radius:12px;border:1px solid ${cc}33;white-space:nowrap;">${(signal.emoji||'')} ${signal.label||''} · ${signal.score||'--'} · ${signal.position||''}</span>`;

    el.innerHTML = `<div style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:rgba(15,23,42,0.5);border:1px solid rgba(100,116,139,0.12);border-radius:8px;flex-wrap:wrap;">
        <span style="font-size:0.65rem;color:#c084fc;font-weight:600;flex-shrink:0;">⚡ 信号</span>
        ${bsz.bond_met > 0 ? `<span style="font-size:0.6rem;color:#10b981;flex-shrink:0;">🟢 债${bsz.bond_met}/${bsz.bond_buy.length}</span>` : ''}
        ${renderMet(metBonds, '#10b981')}
        ${bsz.stock_met > 0 ? `<span style="font-size:0.6rem;color:#f97316;flex-shrink:0;">🟠 股${bsz.stock_met}/${bsz.stock_buy.length}</span>` : ''}
        ${renderMet(metStocks, '#f97316')}
        ${bsz.defense_met > 0 ? `<span style="font-size:0.6rem;color:#ef4444;flex-shrink:0;">🔴 防${bsz.defense_met}/${bsz.defense.length}</span>` : ''}
        ${renderMet(metDefense, '#ef4444')}
        ${alertHtml ? `<span style="font-size:0.5rem;color:#475569;">│</span> ${alertHtml}` : ''}
        <span style="flex:1;"></span>
        ${conclusionBadge}
    </div>`;
}

function renderRatesAlerts(alerts) {
    const el = document.getElementById('rates-alerts');
    if (!el) return;
    if (!alerts.length) { el.style.display = 'none'; return; }
    el.style.display = 'flex';
    el.innerHTML = alerts.map(a => {
        const bg = a.level==='danger'?'rgba(239,68,68,0.08)':a.level==='opportunity'?'rgba(16,185,129,0.08)':'rgba(245,158,11,0.08)';
        const bc = a.level==='danger'?'rgba(239,68,68,0.3)':a.level==='opportunity'?'rgba(16,185,129,0.3)':'rgba(245,158,11,0.3)';
        const pulse = a.pulse ? 'animation:pulse 2s infinite;' : '';
        return '<div style="padding:6px 14px;border:1px solid '+bc+';background:'+bg+';border-radius:6px;font-size:0.72rem;color:#e2e8f0;'+pulse+'">🏦 '+a.icon+' '+a.text+'</div>';
    }).join('');
}

function renderRatesDiagnosis(diagnosis) {
    const diagEl = document.getElementById('rates-diagnosis');
    if (!diagEl || !diagnosis.length) return;
    const typeMap = {
        success: {bg:'rgba(16,185,129,0.06)',border:'#10b981',icon:'✅'},
        info: {bg:'rgba(59,130,246,0.06)',border:'#3b82f6',icon:'ℹ️'},
        warning: {bg:'rgba(245,158,11,0.06)',border:'#f59e0b',icon:'⚠️'},
        danger: {bg:'rgba(239,68,68,0.06)',border:'#ef4444',icon:'🔴'}
    };
    diagEl.innerHTML = diagnosis.map(c => {
        const st = typeMap[c.type]||typeMap.info;
        return '<div style="background:'+st.bg+';border:1px solid '+st.border+'33;border-left:2px solid '+st.border+';border-radius:6px;padding:7px 9px;">' +
            '<div style="font-size:0.65rem;font-weight:600;color:'+st.border+';margin-bottom:2px;">'+st.icon+' '+c.title+'</div>' +
            '<div style="font-size:0.58rem;color:#cbd5e1;line-height:1.4;">'+c.text+'</div></div>';
    }).join('');
}

function renderRatesEncyclopedia(enc) {
    // V1.5: 百科已改为tooltip模式，此函数保留但不渲染
}

// === V2.0: 买卖决策汇总区 (含迷你分位条 + 分位数上下文) ===
function renderRatesDecisionZone(bsz) {
    const el = document.getElementById('rates-decision-zone');
    if (!el || !bsz) return;
    el.style.display = 'block';

    const pct = bsz.percentile_stats || {};

    const miniPctBar = (item) => {
        if (!item.pct && item.pct !== 0) return '';
        const p = Math.max(0, Math.min(100, item.pct));
        const barColor = p >= 75 ? '#10b981' : p >= 25 ? '#f59e0b' : '#ef4444';
        return '<div style="width:48px;height:4px;background:rgba(30,41,59,0.8);border-radius:2px;overflow:hidden;flex-shrink:0;" title="5Y分位:'+p.toFixed(0)+'%">' +
            '<div style="width:'+p+'%;height:100%;background:'+barColor+';border-radius:2px;transition:width 0.6s;"></div></div>' +
            '<span style="font-size:0.5rem;color:#64748b;flex-shrink:0;">P'+p.toFixed(0)+'</span>';
    };

    const renderConds = (items, color) => items.map(c => {
        const icon = c.met ? '<span style="color:#10b981;">✅</span>' : '<span style="color:#475569;">❌</span>';
        const valStyle = c.met ? 'color:#fbbf24;font-weight:600;' : 'color:#64748b;';
        return '<div style="display:flex;align-items:center;gap:5px;padding:3px 0;">' +
            icon + '<span style="color:#cbd5e1;font-size:0.66rem;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + c.cond + '</span>' +
            miniPctBar(c) +
            '<span style="'+valStyle+'font-size:0.63rem;flex-shrink:0;">' + c.val + '</span>' +
            '<span style="font-size:0.52rem;color:#64748b;flex-shrink:0;">' + c.why + '</span></div>';
    }).join('');

    const pctFooter = pct.current_zone_label
        ? '<div style="margin-top:10px;padding:8px 12px;background:rgba(192,132,252,0.04);border:1px solid rgba(192,132,252,0.12);border-radius:6px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">' +
          '<span style="font-size:0.62rem;color:#c084fc;font-weight:600;">📐 5Y分位数</span>' +
          '<span style="font-size:0.58rem;color:#64748b;">P25='+pct.p25+'%</span>' +
          '<span style="font-size:0.58rem;color:#64748b;">P50='+pct.p50+'%</span>' +
          '<span style="font-size:0.58rem;color:#64748b;">P75='+pct.p75+'%</span>' +
          '<span style="font-size:0.58rem;color:#64748b;">σ='+pct.std+'</span>' +
          '<span style="font-size:0.62rem;color:'+(pct.current_zone_color||'#94a3b8')+';font-weight:600;margin-left:auto;">当前: '+(pct.current||'--')+'% · '+pct.current_zone_label+' (P'+(pct.current_pct||50).toFixed(0)+')</span>' +
          '</div>'
        : '';

    el.innerHTML = 
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
        '<span style="font-size:0.82rem;font-weight:700;color:#c084fc;">📊 买卖决策汇总</span>' +
        '<div style="padding:4px 14px;border-radius:20px;font-size:0.72rem;font-weight:700;background:'+(bsz.conclusion_color||'#94a3b8')+'22;color:'+(bsz.conclusion_color||'#94a3b8')+';border:1px solid '+(bsz.conclusion_color||'#94a3b8')+'44;">'+bsz.conclusion+'</div></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">' +
        // 债券买入区
        '<div style="background:rgba(16,185,129,0.04);border:1px solid rgba(16,185,129,0.15);border-radius:8px;padding:10px;">' +
        '<div style="font-size:0.7rem;font-weight:600;color:#10b981;margin-bottom:6px;">🟢 债券买入区 <span style="font-size:0.6rem;color:#64748b;">'+bsz.bond_met+'/'+bsz.bond_buy.length+'</span></div>' +
        renderConds(bsz.bond_buy, '#10b981') + '</div>' +
        // 股票买入区
        '<div style="background:rgba(249,115,22,0.04);border:1px solid rgba(249,115,22,0.15);border-radius:8px;padding:10px;">' +
        '<div style="font-size:0.7rem;font-weight:600;color:#f97316;margin-bottom:6px;">🟠 股票超配区 <span style="font-size:0.6rem;color:#64748b;">'+bsz.stock_met+'/'+bsz.stock_buy.length+'</span></div>' +
        renderConds(bsz.stock_buy, '#f97316') + '</div>' +
        // 避险区
        '<div style="background:rgba(239,68,68,0.04);border:1px solid rgba(239,68,68,0.15);border-radius:8px;padding:10px;">' +
        '<div style="font-size:0.7rem;font-weight:600;color:#ef4444;margin-bottom:6px;">🔴 避险防御区 <span style="font-size:0.6rem;color:#64748b;">'+bsz.defense_met+'/'+bsz.defense.length+'</span></div>' +
        renderConds(bsz.defense, '#ef4444') + '</div>' +
        '</div>' +
        pctFooter;
}

// === V1.5: 卡片Tooltip ===
let _ratesActiveTooltips = null;
function setupRatesTooltips(tips) {
    _ratesActiveTooltips = tips;
    const popup = document.getElementById('rates-tooltip-popup');
    if (!popup) return;
    document.querySelectorAll('.rates-card-tip').forEach(card => {
        card.addEventListener('mouseenter', function(e) {
            const key = this.dataset.tipKey;
            const tip = _ratesActiveTooltips[key];
            if (!tip) return;
            document.getElementById('rates-tip-title').textContent = tip.title || '';
            document.getElementById('rates-tip-desc').textContent = tip.desc || '';
            document.getElementById('rates-tip-logic').textContent = '📐 ' + (tip.logic || '');
            document.getElementById('rates-tip-alert').textContent = tip.alert || '';
            document.getElementById('rates-tip-history').textContent = tip.history ? '📊 ' + tip.history : '';
            const rect = this.getBoundingClientRect();
            popup.style.left = Math.min(rect.left + window.scrollX, window.innerWidth - 300) + 'px';
            popup.style.top = (rect.bottom + window.scrollY + 8) + 'px';
            popup.style.display = 'block';
        });
        card.addEventListener('mouseleave', function() {
            popup.style.display = 'none';
        });
    });
}

// [V3.1] 重复的 renderRatesChart 已删除 (使用 L3432 的V3.0版本)


// Phase 2: resize 已由 alphacore_utils.js 注册中心统一处理


// ====================================================================
//  海外 AIAE 宏观仓位管控模块 V1.1
//  US(蓝) + JP(红) 双面板 | 五档竖卡 | 警示指标 | 三地对比 | 合并操作区
// ====================================================================

let _globalAIAEData = null;
let _globalAIAELoading = false;

async function loadGlobalAIAE(forceRefresh = false) {
    if (_globalAIAELoading) return;
    if (_globalAIAEData && !forceRefresh) {
        renderGlobalAIAE(_globalAIAEData);
        return;
    }

    _globalAIAELoading = true;
    const btn = document.getElementById('gaiae-refresh-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 加载中...'; }

    try {
        const endpoint = forceRefresh ? '/api/v1/aiae_global/refresh' : '/api/v1/aiae_global/report';
        // P2-1: 12s超时 + 1次自动重试
        let resp;
        try {
            resp = await fetch(endpoint, { signal: AbortSignal.timeout(12000) });
        } catch (e1) {
            if (e1.name === 'TimeoutError' || e1.name === 'AbortError') {
                console.warn('[GlobalAIAE] 首次请求超时, 自动重试...');
                resp = await fetch(endpoint, { signal: AbortSignal.timeout(15000) });
            } else { throw e1; }
        }
        const json = await resp.json();
        if (json.status === 'success') {
            _globalAIAEData = json;
            renderGlobalAIAE(json);
            const t = document.getElementById('gaiae-update-time');
            if (t) t.textContent = new Date().toLocaleTimeString('zh-CN');
        } else {
            console.error('[GlobalAIAE] Error:', json.message);
        }
    } catch (e) {
        console.error('[GlobalAIAE] Fetch failed:', e);
    }
    if (btn) { btn.disabled = false; btn.innerHTML = '🔄 刷新'; }
    _globalAIAELoading = false;
}

function renderGlobalAIAE(json) {
    const us = json.us || {};
    const jp = json.jp || {};
    const hk = json.hk || {};
    const gc = json.global_comparison || {};

    // -- Region panels --
    renderGAIAERegionPanel('us', us, '#3b82f6');
    renderGAIAERegionPanel('jp', jp, '#dc2626');
    renderGAIAERegionPanel('hk', hk, '#a855f7');

    // Hero values
    const usV1 = (us.current||{}).aiae_v1 || 0;
    const jpV1 = (jp.current||{}).aiae_v1 || 0;
    const hkV1 = (hk.current||{}).aiae_v1 || 0;
    const usRI = (us.current||{}).regime_info || {};
    const jpRI = (jp.current||{}).regime_info || {};
    const hkRI = (hk.current||{}).regime_info || {};

    const $usV = document.getElementById('gaiae-us-value');
    const $jpV = document.getElementById('gaiae-jp-value');
    const $hkV = document.getElementById('gaiae-hk-value');
    const $usR = document.getElementById('gaiae-us-regime');
    const $jpR = document.getElementById('gaiae-jp-regime');
    const $hkR = document.getElementById('gaiae-hk-regime');
    if ($usV) $usV.textContent = usV1.toFixed(1) + '%';
    if ($jpV) $jpV.textContent = jpV1.toFixed(1) + '%';
    if ($hkV) $hkV.textContent = hkV1.toFixed(1) + '%';
    if ($usR) { $usR.textContent = (usRI.emoji||'') + ' ' + (usRI.cn||'--'); $usR.style.color = usRI.color||'#94a3b8'; }
    if ($jpR) { $jpR.textContent = (jpRI.emoji||'') + ' ' + (jpRI.cn||'--'); $jpR.style.color = jpRI.color||'#94a3b8'; }
    if ($hkR) { $hkR.textContent = (hkRI.emoji||'') + ' ' + (hkRI.cn||'--'); $hkR.style.color = hkRI.color||'#94a3b8'; }

    // Coldest market hero card
    const regionMap = { cn: '🇨🇳 A股', us: '🇺🇸 美股', jp: '🇯🇵 日股', hk: '🇭🇰 港股' };
    const $cold = document.getElementById('gaiae-coldest');
    const $coldL = document.getElementById('gaiae-coldest-label');
    const $coldCard = document.getElementById('gaiae-coldest-card');
    if ($cold) $cold.textContent = regionMap[gc.coldest] || '--';
    if ($coldL) $coldL.textContent = '超配优先 · 远离过热';
    if ($coldCard) $coldCard.classList.add('coldest-glow');

    // Matrices
    renderGAIAEMatrix('us', us);
    renderGAIAEMatrix('jp', jp);
    renderGAIAEMatrix('hk', hk);

    // 4-way comparison
    renderGAIAE3Way(gc);

    // Warning indicators
    renderGAIAEWarnings('us', us);
    renderGAIAEWarnings('jp', jp);
    renderGAIAEWarnings('hk', hk);

    // Consolidated actions
    renderGAIAEActionZone((us.current||{}).regime || 3, (jp.current||{}).regime || 3, (hk.current||{}).regime || 3);

    // Charts
    try { renderGAIAEHistoryChart(us.chart, jp.chart, hk.chart); } catch(e) { console.warn('[GAIAE] chart skip:', e); }
}

function renderGAIAERegionPanel(region, data, color) {
    if (!data || !data.current) return;
    const c = data.current;
    const ri = c.regime_info || {};

    // Gauge
    const max = region === 'us' ? 50 : (region === 'jp' ? 40 : 45);
    const bands = region === 'us'
        ? [[0.30,'#10b981'],[0.40,'#3b82f6'],[0.54,'#eab308'],[0.68,'#f97316'],[1,'#ef4444']]
        : region === 'jp'
        ? [[0.25,'#10b981'],[0.35,'#3b82f6'],[0.50,'#eab308'],[0.70,'#f97316'],[1,'#ef4444']]
        : [[0.18,'#10b981'],[0.31,'#3b82f6'],[0.49,'#eab308'],[0.67,'#f97316'],[1,'#ef4444']];

    try {
        const el = document.getElementById('gaiae-' + region + '-gauge');
        if (el && typeof echarts !== 'undefined') {
            const key = '_gaiae' + region.charAt(0).toUpperCase() + region.slice(1) + 'Gauge';
            if (window[key]) AC.disposeChart(window[key]);
            window[key] = AC.registerChart(echarts.init(el));
            window[key].setOption({
                series: [{
                    type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: max,
                    pointer: { show: true, length: '55%', width: 4, itemStyle: { color: ri.color || color, shadowColor: (ri.color||color), shadowBlur: 6 }, icon: 'triangle' },
                    anchor: { show: true, size: 8, itemStyle: { color: '#0f172a', borderColor: ri.color||color, borderWidth: 2 } },
                    axisLine: { lineStyle: { width: 12, color: bands } },
                    axisTick: { length: 6, distance: -12, lineStyle: { color: 'auto', width: 1 } },
                    splitLine: { length: 10, distance: -12, lineStyle: { color: 'auto', width: 1.5 } },
                    splitNumber: 5,
                    axisLabel: { distance: -28, color: '#64748b', fontSize: 8 },
                    detail: { show: false },
                    data: [{ value: Math.min(Math.max(c.aiae_v1, 0), max) }],
                    animationDuration: 1200
                }]
            });
        }
    } catch(e) { console.warn('[GAIAE] gauge error:', e); }

    // Gauge labels
    const $gv = document.getElementById('gaiae-' + region + '-gauge-val');
    const $gr = document.getElementById('gaiae-' + region + '-gauge-regime');
    if ($gv) $gv.textContent = c.aiae_v1.toFixed(1) + '%';
    if ($gr) { $gr.textContent = (ri.emoji||'') + ' ' + (ri.cn||'--') + ' · 建议仓位 ' + (data.position||{}).matrix_position + '%'; $gr.style.color = ri.color||'#94a3b8'; }

    // ⑤ Regime cards highlight
    const cardsEl = document.getElementById('gaiae-' + region + '-regime-cards');
    if (cardsEl) {
        cardsEl.querySelectorAll('.gaiae-rc').forEach(card => {
            card.classList.toggle('active', parseInt(card.dataset.regime) === c.regime);
        });
    }

    // Factor cards
    const $core = document.getElementById('gaiae-' + region + '-core');
    if ($core) $core.textContent = (c.aiae_core||0).toFixed(1) + '%';

    if (region === 'us') {
        const $margin = document.getElementById('gaiae-us-margin');
        const $aaii = document.getElementById('gaiae-us-aaii');
        if ($margin) $margin.textContent = (c.margin_heat||0).toFixed(2) + '%';
        if ($aaii) {
            const spread = (c.aaii_sentiment||{}).spread || 0;
            $aaii.textContent = (spread > 0 ? '+' : '') + spread.toFixed(0) + '%';
            $aaii.style.color = spread > 15 ? '#ef4444' : spread < -10 ? '#10b981' : '#e2e8f0';
        }
    } else if (region === 'jp') {
        const $margin = document.getElementById('gaiae-jp-margin');
        const $foreign = document.getElementById('gaiae-jp-foreign');
        if ($margin) $margin.textContent = (c.margin_heat||0).toFixed(2) + '%';
        if ($foreign) {
            const net = (c.foreign_flow||{}).net_buy_billion_jpy || 0;
            $foreign.textContent = (net > 0 ? '+' : '') + (net/100).toFixed(0) + '億円';
            $foreign.style.color = net > 2000 ? '#3b82f6' : net < -2000 ? '#ef4444' : '#e2e8f0';
        }
    } else if (region === 'hk') {
        const $sb = document.getElementById('gaiae-hk-southbound');
        const $ah = document.getElementById('gaiae-hk-ahpremium');
        if ($sb) {
            const sbHeat = c.southbound_heat || 0;
            // sbHeat from engine is already a percentage (e.g. 1.12 = 1.12%)
            $sb.textContent = sbHeat.toFixed(2) + '%';
            $sb.style.color = sbHeat > 1.5 ? '#ef4444' : sbHeat < 0.5 ? '#10b981' : '#e2e8f0';
        }
        if ($ah) {
            const ahVal = typeof c.ah_premium === 'object'
                ? (c.ah_premium.index_value || 135)
                : (typeof c.ah_premium === 'number' ? c.ah_premium : 135);
            $ah.textContent = ahVal.toFixed(0);
            $ah.style.color = ahVal > 145 ? '#10b981' : ahVal < 115 ? '#ef4444' : '#e2e8f0';
        }
    }

    // Signals
    const sigEl = document.getElementById('gaiae-' + region + '-signals');
    if (sigEl && data.signals) {
        sigEl.innerHTML = data.signals.map(s => {
            return '<div class="gaiae-signal-item" style="border-color:' + (s.color||'#f59e0b') + '"><span>' + s.text + '</span></div>';
        }).join('');
    }
}

// ② Warning indicators rendering
function renderGAIAEWarnings(region, data) {
    if (!data || !data.current) return;
    const c = data.current;
    const slope = (data.position||{}).slope || 0;

    if (region === 'us') {
        _setWarnIndicator('gaiae-us-warn-margin', 'gaiae-us-warn-margin-val', 'gaiae-us-warn-margin-bar',
            c.margin_heat || 0, '%', 1.5, 1.0);
        _setWarnIndicator('gaiae-us-warn-slope', 'gaiae-us-warn-slope-val', 'gaiae-us-warn-slope-bar',
            Math.abs(slope), '', 3.0, 1.5, slope);
        const spread = (c.aaii_sentiment||{}).spread || 0;
        _setWarnIndicator('gaiae-us-warn-aaii', 'gaiae-us-warn-aaii-val', 'gaiae-us-warn-aaii-bar',
            spread, '%', 20, 10);
    } else if (region === 'jp') {
        _setWarnIndicator('gaiae-jp-warn-margin', 'gaiae-jp-warn-margin-val', 'gaiae-jp-warn-margin-bar',
            c.margin_heat || 0, '%', 0.6, 0.4);
        _setWarnIndicator('gaiae-jp-warn-slope', 'gaiae-jp-warn-slope-val', 'gaiae-jp-warn-slope-bar',
            Math.abs(slope), '', 2.0, 1.0, slope);
        const foreign = (c.foreign_flow||{}).net_buy_billion_jpy || 0;
        _setWarnIndicator('gaiae-jp-warn-foreign', 'gaiae-jp-warn-foreign-val', 'gaiae-jp-warn-foreign-bar',
            foreign / 100, '億', 30, 15);
    } else if (region === 'hk') {
        // sbHeat is already a percentage from engine (e.g. 1.12 = 1.12%)
        const sbHeat = c.southbound_heat || 0;
        _setWarnIndicator('gaiae-hk-warn-sb', 'gaiae-hk-warn-sb-val', 'gaiae-hk-warn-sb-bar',
            sbHeat, '%', 2.0, 1.0);
        _setWarnIndicator('gaiae-hk-warn-slope', 'gaiae-hk-warn-slope-val', 'gaiae-hk-warn-slope-bar',
            Math.abs(slope), '', 2.5, 1.5, slope);
        const ahPremium = typeof c.ah_premium === 'object'
            ? (c.ah_premium.index_value || 135)
            : (typeof c.ah_premium === 'number' ? c.ah_premium : 135);
        _setWarnIndicator('gaiae-hk-warn-ah', 'gaiae-hk-warn-ah-val', 'gaiae-hk-warn-ah-bar',
            ahPremium, '', 145, 130);
    }
}

function _setWarnIndicator(cardId, valId, barId, value, unit, dangerThreshold, cautionThreshold, displayVal) {
    const card = document.getElementById(cardId);
    const $val = document.getElementById(valId);
    const $bar = document.getElementById(barId);
    if (!card) return;

    const dv = displayVal !== undefined ? displayVal : value;
    const absVal = Math.abs(value);
    const isDanger = absVal >= dangerThreshold;
    const isCaution = absVal >= cautionThreshold && !isDanger;

    card.className = 'gaiae-warn-card ' + (isDanger ? 'warn-danger' : isCaution ? 'warn-caution' : 'warn-ok');
    if ($val) {
        $val.textContent = (typeof dv === 'number' ? (dv > 0 ? '+' : '') + dv.toFixed(2) : dv) + unit;
        $val.style.color = isDanger ? '#ef4444' : isCaution ? '#f59e0b' : '#10b981';
    }
    if ($bar) {
        const pct = Math.min((absVal / dangerThreshold) * 100, 100);
        $bar.style.width = pct + '%';
        $bar.style.background = isDanger ? '#ef4444' : isCaution ? '#f59e0b' : '#10b981';
    }
}

function renderGAIAEMatrix(region, data) {
    if (!data || !data.position) return;
    const pos = data.position;
    const cv = data.cross_validation || {};

    // Cross-validation verdict
    const $cv = document.getElementById('gaiae-' + region + '-cv-verdict');
    if ($cv) {
        const regimeRN = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
        $cv.innerHTML = '当前: <b style="color:#f59e0b">' + (regimeRN[pos.regime]||pos.regime) + '级</b>' +
            ' × <b style="color:#60a5fa">ERP ' + (pos.erp_value||0).toFixed(1) + '%</b>' +
            ' → 建议仓位 <b style="color:' + (cv.color||'#10b981') + ';font-size:0.85rem">' + pos.matrix_position + '%</b>' +
            ' · <span style="color:' + (cv.color||'#94a3b8') + '">' + (cv.confidence_stars||'') + ' ' + (cv.verdict||'') + '</span>';
    }

    // Highlight active cell
    const table = document.getElementById('gaiae-' + region + '-matrix');
    if (!table) return;

    const erpMap_us = { 'erp_gt5': 0, 'erp_3_5': 1, 'erp_1_3': 2, 'erp_lt1': 3 };
    const erpMap_jp = { 'erp_gt4': 0, 'erp_2_4': 1, 'erp_0_2': 2, 'erp_lt0': 3 };
    const erpMap_hk = { 'erp_gt5': 0, 'erp_3_5': 1, 'erp_1_3': 2, 'erp_lt1': 3 };
    const erpMap = region === 'us' ? erpMap_us : (region === 'jp' ? erpMap_jp : erpMap_hk);
    const rowIdx = erpMap[pos.erp_level] ?? 2;
    const colIdx = Math.min((pos.regime||3) - 1, 4);

    // Color all cells
    const posValues = [[95,85,70,45,20],[90,80,65,40,15],[85,70,55,30,10],[75,60,40,20,5]];
    function posColor(v) {
        if (v >= 80) return 'rgba(16,185,129,0.15)';
        if (v >= 60) return 'rgba(52,211,153,0.08)';
        if (v >= 40) return 'rgba(234,179,8,0.08)';
        if (v >= 20) return 'rgba(249,115,22,0.08)';
        return 'rgba(239,68,68,0.1)';
    }
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach((row, ri) => {
        const cells = row.querySelectorAll('td');
        cells.forEach((td, ci) => {
            td.classList.remove('gaiae-cell-active');
            if (ci > 0 && posValues[ri]) { td.style.background = posColor(posValues[ri][ci-1]); }
        });
    });
    if (rows[rowIdx]) {
        const cells = rows[rowIdx].querySelectorAll('td');
        if (cells[colIdx + 1]) cells[colIdx + 1].classList.add('gaiae-cell-active');
    }
}

function renderGAIAE3Way(gc) {
    if (!gc) return;
    const regimeNames = {1: 'Ⅰ极度恐慌', 2: 'Ⅱ低配置区', 3: 'Ⅲ中性均衡', 4: 'Ⅳ偏热区域', 5: 'Ⅴ极度过热'};
    const regimeColors = {1: '#10b981', 2: '#3b82f6', 3: '#eab308', 4: '#f97316', 5: '#ef4444'};

    const $cn = document.getElementById('gaiae-3way-cn');
    const $us = document.getElementById('gaiae-3way-us');
    const $jp = document.getElementById('gaiae-3way-jp');
    const $hk = document.getElementById('gaiae-3way-hk');
    const $cnR = document.getElementById('gaiae-3way-cn-regime');
    const $usR = document.getElementById('gaiae-3way-us-regime');
    const $jpR = document.getElementById('gaiae-3way-jp-regime');
    const $hkR = document.getElementById('gaiae-3way-hk-regime');

    if ($cn) $cn.textContent = (gc.cn_aiae||0).toFixed(1) + '%';
    if ($us) $us.textContent = (gc.us_aiae||0).toFixed(1) + '%';
    if ($jp) $jp.textContent = (gc.jp_aiae||0).toFixed(1) + '%';
    if ($hk) $hk.textContent = (gc.hk_aiae||0).toFixed(1) + '%';
    if ($cnR) { $cnR.textContent = 'A股 ' + (regimeNames[gc.cn_regime]||'Ⅲ中性'); $cnR.style.color = regimeColors[gc.cn_regime]||'#94a3b8'; }
    if ($usR) { $usR.textContent = '美股 ' + (regimeNames[gc.us_regime]||'Ⅲ中性'); $usR.style.color = regimeColors[gc.us_regime]||'#94a3b8'; }
    if ($jpR) { $jpR.textContent = '日股 ' + (regimeNames[gc.jp_regime]||'Ⅲ中性'); $jpR.style.color = regimeColors[gc.jp_regime]||'#94a3b8'; }
    if ($hkR) { $hkR.textContent = '港股 ' + (regimeNames[gc.hk_regime]||'Ⅲ中性'); $hkR.style.color = regimeColors[gc.hk_regime]||'#94a3b8'; }

    // Crown animation on coldest market
    const coldest = gc.coldest || '';
    ['cn','us','jp','hk'].forEach(r => {
        const card = document.getElementById('gaiae-3way-card-' + r);
        if (card) {
            card.classList.toggle('is-coldest', r === coldest);
            // Add crown to flag
            const flagEl = card.querySelector('.gaiae-3way-flag');
            if (flagEl && r === coldest && !flagEl.querySelector('.gaiae-3way-crown')) {
                flagEl.innerHTML += ' <span class="gaiae-3way-crown">👑</span>';
            }
        }
    });

    const $rec = document.getElementById('gaiae-recommendation');
    if ($rec) $rec.textContent = '🌍 ' + (gc.recommendation || '加载中...');
}

// ③ Consolidated action zone rendering
function renderGAIAEActionZone(usRegime, jpRegime, hkRegime) {
    // Determine which zone is active
    // Buy: regime 1-2, Hold: regime 3, Sell: regime 4-5
    // Use the "hotter" regime to be conservative
    const maxRegime = Math.max(usRegime, jpRegime, hkRegime || 3);

    const $buy = document.getElementById('gaiae-az-buy');
    const $hold = document.getElementById('gaiae-az-hold');
    const $sell = document.getElementById('gaiae-az-sell');

    if ($buy) {
        $buy.classList.toggle('az-active', maxRegime <= 2);
        $buy.classList.toggle('az-dimmed', maxRegime > 2);
    }
    if ($hold) {
        $hold.classList.toggle('az-active', maxRegime === 3);
        $hold.classList.toggle('az-dimmed', maxRegime !== 3);
    }
    if ($sell) {
        $sell.classList.toggle('az-active', maxRegime >= 4);
        $sell.classList.toggle('az-dimmed', maxRegime < 4);
    }

    // Update action content based on actual regimes
    const _rn = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
    const usLabel = '🇺🇸 美股 (' + (_rn[usRegime]||usRegime) + '级)';
    const jpLabel = '🇯🇵 日股 (' + (_rn[jpRegime]||jpRegime) + '级)';
    const hkLabel = '🇭🇰 港股 (' + (_rn[hkRegime]||hkRegime) + '级)';
    const buyData = {
        1: { us: ['<b>极低 → 满配进攻</b>', '分3批建仓 SPY/QQQ', '总仓位冲至90-95%'], jp: ['<b>極度悲観 → 全力買い</b>', '3批建仓 1306/1321', '総ポジション90-95%'], hk: ['<b>极度恐慌 → 满配</b>', '分3批建仓 159920/513130', '仓位冲至90-95%'] },
        2: { us: ['<b>标准建仓区</b>', '目标仓位70-85%', 'ERP为正时加大买入'], jp: ['<b>標準建倉区</b>', '目標70-85%', '積極的にETF配分'], hk: ['<b>标准建仓区</b>', '目标70-85%', '南向资金流入验证'] },
        3: { us: ['Ⅲ级不主动加仓', '新增限制5%以内', '等待回调机会'], jp: ['Ⅲ級 加倉なし', '新規5%以内', '押し目待ち'], hk: ['Ⅲ级不加仓', '新增限制5%以内', '等待南向/AH信号'] },
        4: { us: ['<b>Ⅳ级禁止新开仓</b>', '不追涨进攻型标的', '仅保留红利型'], jp: ['<b>Ⅳ級 新規禁止</b>', '攻撃型銘柄撤退', '高配当のみ保有'], hk: ['<b>Ⅳ级禁止新开</b>', '科技ETF逐步撤退', '仅保留红利低波'] },
        5: { us: ['<b>Ⅴ级 绝对禁止买入</b>', '历史级泡沫信号', '任何新仓=与市场对赌'], jp: ['<b>Ⅴ級 絶対禁止</b>', 'バブル警報発令', '新規ポジション厳禁'], hk: ['<b>Ⅴ级 绝对禁止</b>', '2018年1月级泡沫', '任何新仓=接盘'] }
    };
    const holdData = {
        1: { us: ['每批完成后等3-5天', '只在下跌日建仓', '90-95%上限'], jp: ['各批3-5日間隔', '下落日のみ建倉', '90-95%上限'], hk: ['每批等3-5天', '只在下跌日建', '90-95%上限'] },
        2: { us: ['已建仓位坚定持有', '不因短期波动减仓', '观察AIAE方向'], jp: ['既存ポジション堅持', '短期変動で減らさない', 'AIAE方向を観察'], hk: ['仓位坚定持有', '不因波动减仓', '观察南向方向'] },
        3: { us: ['维持50-65%均衡仓位', '到目标价就卖', '宽基+红利为主'], jp: ['50-65%バランス維持', '目標価で売却', 'ETF+高配当中心'], hk: ['维持50-65%均衡', '恒生ETF+红利低波', '关注AH溢价'] },
        4: { us: ['总仓位压缩至25-40%', '进攻型逐步清退', '红利ETF可继续'], jp: ['25-40%へ圧縮', '攻撃型段階的撤退', '高配当ETF継続可'], hk: ['压缩至25-40%', '科技ETF逐步清退', '红利低波可继续'] },
        5: { us: ['仅保留0-15%极低仓', '仅限红利防御型', '现金为王'], jp: ['0-15%極低ポジション', '防御型ETFのみ', 'キャッシュ・イズ・キング'], hk: ['仅保留0-15%', '仅限恒生红利低波', '现金/债券为王'] }
    };
    const sellData = {
        1: { us: ['此档位禁止卖出', '除非触发组合-25%止损', '耐心持有'], jp: ['売却禁止', '組合-25%止損のみ', '忍耐保有'], hk: ['禁止卖出', '除非止损-25%', '耐心持有'] },
        2: { us: ['不主动卖出', '仅止损触发时被动减', '子策略止损: -8%'], jp: ['自発的売却なし', '止損のみ反応', '個別止損: -7%'], hk: ['不主动卖出', '仅止损时被动减', '个股止损: -8%'] },
        3: { us: ['到达止盈目标及时卖', '监控AIAE走向', '接近上档做准备'], jp: ['利確目標で売却', 'AIAE動向監視', '上昇接近で準備'], hk: ['止盈目标及时卖', '监控南向+AIAE', '接近Ⅳ做准备'] },
        4: { us: ['<b>每周减5%总仓位</b>', '优先清退高波动', '3-4周完成减仓'], jp: ['<b>毎週5%ずつ減倉</b>', '高ボラ銘柄から撤退', '3-4週間で完了'], hk: ['<b>每周减5%仓位</b>', '优先清退科技ETF', '3-4周完成'] },
        5: { us: ['<b>3天内完成清仓</b>', '无例外，不抄底', '强制执行，无论盈亏'], jp: ['<b>3日以内に完全撤退</b>', '例外なし・底打ち買い禁止', '損益問わず強制執行'], hk: ['<b>3天内完成清仓</b>', '无例外，不抄底', '强制执行'] }
    };

    const $buyList = document.getElementById('gaiae-az-buy-list');
    const $holdList = document.getElementById('gaiae-az-hold-list');
    const $sellList = document.getElementById('gaiae-az-sell-list');

    function makeList(data, usR, jpR, hkR) {
        const ud = data[usR] || data[3];
        const jd = data[jpR] || data[3];
        const hd = data[hkR] || data[3];
        return '<li class="az-region-label" style="color:#3b82f6">' + usLabel + '</li>' +
            ud.us.map(t => '<li>' + t + '</li>').join('') +
            '<li class="az-region-label" style="color:#dc2626">' + jpLabel + '</li>' +
            jd.jp.map(t => '<li>' + t + '</li>').join('') +
            '<li class="az-region-label" style="color:#a855f7">' + hkLabel + '</li>' +
            hd.hk.map(t => '<li>' + t + '</li>').join('');
    }

    if ($buyList) $buyList.innerHTML = makeList(buyData, usRegime, jpRegime, hkRegime);
    if ($holdList) $holdList.innerHTML = makeList(holdData, usRegime, jpRegime, hkRegime);
    if ($sellList) $sellList.innerHTML = makeList(sellData, usRegime, jpRegime, hkRegime);
}

function renderGAIAEHistoryChart(usChart, jpChart, hkChart) {
    const el = document.getElementById('gaiae-history-chart');
    if (!el || typeof echarts === 'undefined') return;
    if (window._gaiaeHistChart) AC.disposeChart(window._gaiaeHistChart);
    window._gaiaeHistChart = AC.registerChart(echarts.init(el));

    // Use US chart dates as x-axis (it has more data points typically)
    const usDates = usChart ? usChart.dates : [];
    const usValues = usChart ? usChart.values : [];
    const jpDates = jpChart ? jpChart.dates : [];
    const jpValues = jpChart ? jpChart.values : [];
    const hkDates = hkChart ? hkChart.dates : [];
    const hkValues = hkChart ? hkChart.values : [];

    // Merge dates
    const allDates = [...new Set([...usDates, ...jpDates, ...hkDates])].sort();
    const usMap = {}; usDates.forEach((d, i) => usMap[d] = usValues[i]);
    const jpMap = {}; jpDates.forEach((d, i) => jpMap[d] = jpValues[i]);
    const hkMap = {}; hkDates.forEach((d, i) => hkMap[d] = hkValues[i]);

    const usData = allDates.map(d => usMap[d] ?? null);
    const jpData = allDates.map(d => jpMap[d] ?? null);
    const hkData = allDates.map(d => hkMap[d] ?? null);

    // US five-tier mark areas
    const markAreaData = [
        [{ yAxis: 0, itemStyle: { color: 'rgba(16,185,129,0.05)' } }, { yAxis: 15 }],
        [{ yAxis: 15, itemStyle: { color: 'rgba(59,130,246,0.04)' } }, { yAxis: 20 }],
        [{ yAxis: 20, itemStyle: { color: 'rgba(234,179,8,0.04)' } }, { yAxis: 27 }],
        [{ yAxis: 27, itemStyle: { color: 'rgba(249,115,22,0.05)' } }, { yAxis: 34 }],
        [{ yAxis: 34, itemStyle: { color: 'rgba(239,68,68,0.05)' } }, { yAxis: 50 }],
    ];

    window._gaiaeHistChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(245,158,11,0.3)',
            textStyle: { color: '#e2e8f0', fontSize: 11 },
        },
        legend: { top: 0, textStyle: { color: '#94a3b8', fontSize: 10 } },
        grid: { left: 50, right: 20, top: 30, bottom: 30 },
        xAxis: {
            type: 'category', data: allDates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 8, formatter: function(v) { return v.substring(0, 7); } },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: {
            type: 'value', min: 0, max: 50,
            axisLabel: { color: '#64748b', fontSize: 8, formatter: function(v) { return v + '%'; } },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
        },
        series: [
            {
                name: '🇺🇸 US AIAE', type: 'line', data: usData, smooth: true, connectNulls: true,
                symbol: 'circle', symbolSize: 8,
                lineStyle: { color: '#3b82f6', width: 2.5, shadowColor: 'rgba(59,130,246,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#3b82f6', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(59,130,246,0.15)' }, { offset: 1, color: 'rgba(59,130,246,0)' }]
                }},
                label: { show: true, fontSize: 7, color: '#3b82f6', formatter: function(p) { return p.value !== null ? p.value + '%' : ''; }, position: 'top' },
                markArea: { silent: true, data: markAreaData },
            },
            {
                name: '🇯🇵 JP AIAE', type: 'line', data: jpData, smooth: true, connectNulls: true,
                symbol: 'diamond', symbolSize: 8,
                lineStyle: { color: '#dc2626', width: 2.5, shadowColor: 'rgba(220,38,38,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#dc2626', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(220,38,38,0.12)' }, { offset: 1, color: 'rgba(220,38,38,0)' }]
                }},
                label: { show: true, fontSize: 7, color: '#dc2626', formatter: function(p) { return p.value !== null ? p.value + '%' : ''; }, position: 'bottom' },
            },
            {
                name: '🇭🇰 HK AIAE', type: 'line', data: hkData, smooth: true, connectNulls: true,
                symbol: 'rect', symbolSize: 7,
                lineStyle: { color: '#a855f7', width: 2.5, shadowColor: 'rgba(168,85,247,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#a855f7', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(168,85,247,0.12)' }, { offset: 1, color: 'rgba(168,85,247,0)' }]
                }},
                label: { show: true, fontSize: 7, color: '#a855f7', formatter: function(p) { return p.value !== null ? p.value + '%' : ''; }, position: 'insideTopRight' },
            }
        ]
    });
}

// Phase 2: resize 已由 alphacore_utils.js 注册中心统一处理
