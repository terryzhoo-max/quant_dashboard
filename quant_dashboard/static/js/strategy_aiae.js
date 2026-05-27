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
     'fund-reminder-banner','fund-stale-badge',
     'slippage-desk', 'slip-size', 'slip-cost', 'slip-algo',
     'contagion-matrix-container', 'contagion-matrix',
     'grc-emergency-alert', 'discipline-drawer', 'drawer-trigger',
     'drawer-close', 'drawer-overlay', 'grc-read-confirm',
     'grc-sig-input', 'grc-sign-btn', 'grc-audit-trail', 'slip-size-select'
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

// ── 生产级风控抽屉交互绑定 ──
let _grcDrawerBound = false;

// 辅助渲染时间轴
function renderGRCAuditTrail() {
    const trailEl = _aiaeDOM['grc-audit-trail'];
    if (!trailEl) return;
    
    let history = [];
    try {
        history = JSON.parse(localStorage.getItem('aiae_grc_audit_history') || '[]');
    } catch(e) {
        history = [];
    }
    
    if (history.length === 0) {
        trailEl.innerHTML = `<div style="font-size: 0.65rem; color: #64748b; font-style: italic;">暂无签认记录</div>`;
        return;
    }
    
    const regimeRoman = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
    trailEl.innerHTML = history.map((record, idx) => {
        const gapVal = parseFloat(record.gap);
        const gapStr = (gapVal >= 0 ? '+' : '') + gapVal.toFixed(1) + ' pt';
        return `
            <div class="aiae-audit-node">
                <div class="aiae-audit-dot signed"></div>
                <div class="aiae-audit-info">
                    交易员 <b>${record.operator}</b> 签认 SOP 纪律<br/>
                    <span style="color:#94a3b8;">状态: AIAE ${regimeRoman[record.regime] || record.regime}级 · 实盘偏差 ${gapStr}</span>
                </div>
                <div class="aiae-audit-time">${record.timestamp}</div>
            </div>
        `;
    }).join('');
}

function bindGRCDrawer() {
    if (_grcDrawerBound) return;
    
    const trigger = _aiaeDOM['drawer-trigger'];
    const drawer = _aiaeDOM['discipline-drawer'];
    const closeBtn = _aiaeDOM['drawer-close'];
    const overlay = _aiaeDOM['drawer-overlay'];
    const checkbox = _aiaeDOM['grc-read-confirm'];
    const sigInput = _aiaeDOM['grc-sig-input'];
    const signBtn = _aiaeDOM['grc-sign-btn'];
    const scaleSelect = _aiaeDOM['slip-size-select'];

    if (trigger && drawer) {
        trigger.addEventListener('click', () => {
            drawer.classList.add('open');
            if (overlay) overlay.style.display = 'block';
            renderGRCAuditTrail();
        });
    }

    const closeDrawer = () => {
        if (drawer) drawer.classList.remove('open');
        if (overlay) overlay.style.display = 'none';
    };

    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
    if (overlay) overlay.addEventListener('click', closeDrawer);

    // 键盘 Esc 快捷键关闭抽屉
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && drawer && drawer.classList.contains('open')) {
            closeDrawer();
        }
    });

    // 记住签认勾选状态并绑定提交签名按钮
    if (checkbox && sigInput && signBtn) {
        const confirmed = localStorage.getItem('aiae_grc_confirmed') === 'true';
        checkbox.checked = confirmed;
        
        // 初始高亮检查
        const lastSignature = localStorage.getItem('aiae_grc_last_signature');
        if (confirmed && lastSignature && trigger) {
            trigger.style.background = 'rgba(16, 185, 129, 0.25)';
            trigger.textContent = `🛡️ ${lastSignature} 已签认`;
        }

        checkbox.addEventListener('change', () => {
            if (!checkbox.checked) {
                localStorage.setItem('aiae_grc_confirmed', 'false');
                if (trigger) {
                    trigger.style.background = 'rgba(16, 185, 129, 0.15)';
                    trigger.textContent = '🛡️ 风控 SOP 百科';
                }
            }
        });

        signBtn.addEventListener('click', () => {
            if (!checkbox.checked) {
                alert('请先勾选：我已阅读并理解生产级风控合规纪律');
                return;
            }
            
            const operatorName = sigInput.value.trim().toUpperCase();
            if (!operatorName) {
                sigInput.style.borderColor = '#ef4444';
                sigInput.style.boxShadow = '0 0 8px rgba(239, 68, 68, 0.3)';
                setTimeout(() => {
                    sigInput.style.borderColor = 'rgba(255,255,255,0.08)';
                    sigInput.style.boxShadow = 'none';
                }, 2000);
                return;
            }
            
            // 构造签认审计记录
            const gapVal = _aiaeData ? (_aiaeData.position.gap ?? _aiaeData.position.gap_pt ?? 0) : 0;
            const regimeVal = _aiaeData ? _aiaeData.current.regime : 3;
            
            const record = {
                operator: operatorName,
                timestamp: new Date().toLocaleString('zh-CN'),
                regime: regimeVal,
                gap: gapVal
            };
            
            let history = [];
            try {
                history = JSON.parse(localStorage.getItem('aiae_grc_audit_history') || '[]');
            } catch(e) {
                history = [];
            }
            
            history.unshift(record);
            if (history.length > 3) {
                history = history.slice(0, 3);
            }
            
            localStorage.setItem('aiae_grc_audit_history', JSON.stringify(history));
            localStorage.setItem('aiae_grc_confirmed', 'true');
            localStorage.setItem('aiae_grc_last_signature', operatorName);
            
            checkbox.checked = true;
            sigInput.value = '';
            
            if (trigger) {
                trigger.style.background = 'rgba(16, 185, 129, 0.25)';
                trigger.textContent = `🛡️ ${operatorName} 已签认`;
            }
            
            renderGRCAuditTrail();
            
            // 提示签认成功并关闭抽屉
            const originalText = signBtn.textContent;
            signBtn.textContent = '✅ 已成功签认';
            signBtn.disabled = true;
            setTimeout(() => {
                signBtn.textContent = originalText;
                signBtn.disabled = false;
                closeDrawer();
            }, 1000);
        });
    }

    // 绑定组合资产规模选择联动
    if (scaleSelect) {
        scaleSelect.addEventListener('change', () => {
            if (_aiaeData) {
                renderDeviationStats(_aiaeData);
            }
        });
    }

    _grcDrawerBound = true;
}

// ── 动态合规警示渲染 ──
function renderAIAEGRCAlert(c, pd) {
    const alertEl = _aiaeDOM['grc-emergency-alert'];
    if (!alertEl) return;

    const gap = pd.gap ?? pd.gap_pt;
    const regime = c.regime;
    const ri = c.regime_info || {};

    let alertHtml = '';
    let levelClass = 'alert-level-green';

    // 场景 1：超额违规强平警告 (Regime 4/5 且实盘偏差为负或为正，只要实盘偏离严重)
    if (regime >= 4) {
        levelClass = 'alert-level-red';
        alertHtml = `🚨 <b>合规预警</b>：当前宏观定位为 <b style="color:${ri.color};">${ri.cn || '偏热'} (${regime}级)</b>。根据 GRC 一级防御铁律，<b>严禁在此状态下开新仓或追高进攻型标的！</b> 必须严格按照交易指令，每周强制降低总权益仓位上限至 ${ri.position || '25-40%'} 水平。`;
    } 
    // 场景 2：实盘仓位严重超配超过硬顶的 110%
    else if (gap !== null && gap > 8.0) {
        levelClass = 'alert-level-red';
        alertHtml = `🚨 <b>合规违规</b>：当前仓位偏离度达 <b>+${gap.toFixed(1)} pt</b>，超出合规警示硬红线 (3.0pt)！属于<b>【严重超配违规】</b>，禁止因主观执念手动覆盖信号，请立即开启执行决策桌并启动 TWAP/VWAP 算法分拆减仓。`;
    } 
    // 场景 3：大底机会建仓提示
    else if (regime <= 2 && gap !== null && gap < -8.0) {
        levelClass = 'alert-level-blue';
        alertHtml = `💡 <b>合规建仓提示</b>：当前市场处于配置性极佳的 <b style="color:${ri.color};">${ri.cn || '底部'} (${regime}级)</b>，但实盘偏离度为 <b>${gap.toFixed(1)} pt</b> (严重欠配)。依据一级防御 SOP，建议利用盘中日度回踩机会，被动买入宽基 ETF 完成补仓，禁止单日一步满仓。`;
    }
    // 场景 4：常规超配或欠配警示（橙色警告，偏差处于 3 到 8pt 之间）
    else if (gap !== null && (gap > 3.0 || gap < -3.0)) {
        levelClass = 'alert-level-orange';
        const typeStr = gap > 0 ? '超配偏离' : '欠配偏离';
        alertHtml = `⚠️ <b>合规提示</b>：当前实盘处于常规 ${typeStr} 状态，偏离度为 <b>${gap > 0 ? '+' : ''}${gap.toFixed(1)} pt</b>，超出 3.0pt 软限限制。请投资经理与交易员密切监控，仓位调整建议利用执行桌算法分摊 1.5 - 2 天完成，禁止因主观情绪一步到位。`;
    }
    // 正常状态 (Gap 处于合规区间 [-3.0, 3.0]pt)
    else {
        levelClass = 'alert-level-green';
        alertHtml = `🟢 <b>合规运行中</b>：当前实盘与宏观 AIAE 偏离度为 <b>${gap >= 0 ? '+' : ''}${gap !== null ? gap.toFixed(1) : '0.0'} pt</b>，处于合规偏差允许区间 [-3.0, +3.0]pt 内。系统风控与三层防御正常运转。`;
    }

    // 设置警示类名并显示
    alertEl.className = 'aiae-grc-alert ' + levelClass;
    alertEl.innerHTML = alertHtml;
    alertEl.style.display = 'block';
}

function renderAIAEUI(data) {
    if (!data) return;
    _aiaeCacheDOM();  // 懒初始化 DOM 缓存
    try { bindGRCDrawer(); } catch(e) { console.warn('[AIAE GRC] Drawer bind error:', e); }
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

    // ── ZONE 6: Factor Decomposition + HF (async, non-blocking) ──
    try { loadAndRenderZone6(); } catch(e) { console.warn('[AIAE] zone6 skip:', e); }

    // ── ZONE 7: Health + Cross-Market + Reconciliation (async, non-blocking) ──
    try { loadAndRenderZone7(); } catch(e) { console.warn('[AIAE] zone7 skip:', e); }

    // ── GRC: 生产级风控警告动态渲染 ──
    try { renderAIAEGRCAlert(c, p); } catch(e) { console.warn('[AIAE GRC] GRC alert render error:', e); }
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
        const resp = await AC.secureFetch('/api/v1/aiae/update_fund_position', {
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

            // V3.1: 根据数据密度自适应标记大小和标签显示
            const isSparse = chart.values.length <= 12;
            const symbolSizes = chart.labels.map(l => l ? (isSparse ? 10 : 7) : (isSparse ? 10 : 3));
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
                    symbol: 'circle', symbolSize: symbolSizes,
                    lineStyle: { color: '#f59e0b', width: isSparse ? 3 : 2, shadowColor: 'rgba(245,158,11,0.3)', shadowBlur: 6 },
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
                        formatter: function(p) {
                            // V3.1: 仅在有标注的关键节点上显示标签, 避免密集数据时标签重叠
                            const idx = p.dataIndex;
                            if (chart.labels[idx]) return p.value + '%';
                            return '';
                        },
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
    const strategies = ['mr', 'div', 'mom', 'gem', 'erp', 'aiae_etf'];
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

// ═══════════════════════════════════════════════════════════════
//  ZONE 6: 因子分解 + HF 高频代理
// ═══════════════════════════════════════════════════════════════

async function loadAndRenderZone6() {
    // 并发请求 decomposition + factor_trend
    const [decompResp, trendResp] = await Promise.allSettled([
        fetch('/api/v1/aiae/decomposition', { signal: AbortSignal.timeout(8000) }).then(r => r.json()),
        fetch('/api/v1/aiae/factor_trend?days=60', { signal: AbortSignal.timeout(8000) }).then(r => r.json()),
    ]);

    const decomp = decompResp.status === 'fulfilled' ? decompResp.value : null;
    const trend = trendResp.status === 'fulfilled' ? trendResp.value : null;

    if (decomp && decomp.decomposition) {
        renderWaterfallChart(decomp.decomposition, decomp.aiae_v1);
    }
    if (decomp && decomp.hf_estimate) {
        renderHFCard(decomp.hf_estimate, decomp.aiae_v1);
    }
    if (trend && trend.status === 'success' && trend.series) {
        renderFactorTrendChart(trend);
    }
}

function renderWaterfallChart(decomp, totalV1) {
    const container = document.getElementById('aiae-waterfall-chart');
    if (!container || typeof echarts === 'undefined') return;
    try { window._aiaeWfChart = AC.disposeChart(window._aiaeWfChart); } catch(_) {}
    window._aiaeWfChart = AC.registerChart(echarts.init(container));

    const factors = ['aiae_simple', 'fund_position', 'margin_heat'];
    const labels = factors.map(f => decomp[f]?.label || f);
    labels.push('AIAE V1');

    const contribs = factors.map(f => decomp[f]?.contribution || 0);

    // Waterfall: transparent base stacks
    let cumBase = 0;
    const baseData = [];
    const contribData = [];

    for (let i = 0; i < contribs.length; i++) {
        baseData.push(cumBase);
        contribData.push(contribs[i]);
        cumBase += contribs[i];
    }
    // Total bar: from 0 to total
    baseData.push(0);
    contribData.push(totalV1 || cumBase);

    const colors = ['#f59e0b', '#eab308', '#f97316', 'rgba(255,255,255,0.9)'];

    window._aiaeWfChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(245,158,11,0.3)',
            textStyle: { color: '#e2e8f0', fontSize: 11 },
            formatter: function(params) {
                if (!params.length) return '';
                const idx = params[0].dataIndex;
                const val = contribData[idx];
                const freq = idx < factors.length ? (decomp[factors[idx]]?.frequency || '') : '';
                const weight = idx < factors.length ? (decomp[factors[idx]]?.weight * 100).toFixed(0) + '%' : '100%';
                return '<b>' + labels[idx] + '</b><br/>' +
                    '贡献: <b>' + val.toFixed(2) + '</b> pt<br/>' +
                    '权重: ' + weight + (freq ? ' · ' + freq : '');
            }
        },
        grid: { left: 50, right: 20, top: 20, bottom: 40 },
        xAxis: {
            type: 'category', data: labels,
            axisLabel: { color: '#94a3b8', fontSize: 10, interval: 0, rotate: 0 },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#64748b', fontSize: 9 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
        },
        series: [
            {
                type: 'bar', stack: 'wf', data: baseData, barWidth: '45%',
                itemStyle: { color: 'transparent' }, emphasis: { disabled: true }
            },
            {
                type: 'bar', stack: 'wf', data: contribData.map((v, i) => ({
                    value: v,
                    itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] }
                })),
                barWidth: '45%',
                label: {
                    show: true, position: 'top', color: '#cbd5e1', fontSize: 10,
                    formatter: p => p.value.toFixed(2)
                }
            }
        ]
    });
}

function renderHFCard(hf, v1) {
    const $v1 = document.getElementById('hf-aiae-v1');
    const $hf = document.getElementById('hf-aiae-hf');
    const $delta = document.getElementById('hf-delta-val');
    const $conf = document.getElementById('hf-confidence');

    if ($v1) $v1.textContent = (v1 || 0).toFixed(2) + '%';

    const aiae_hf = hf.aiae_hf || v1 || 0;
    const delta = hf.hf_delta || 0;
    const conf = hf.confidence || 'N/A';

    if ($hf) $hf.textContent = aiae_hf.toFixed(2) + '%';
    if ($delta) {
        const sign = delta >= 0 ? '+' : '';
        $delta.textContent = sign + delta.toFixed(2) + ' pt';
        $delta.style.color = delta > 0 ? '#f97316' : (delta < 0 ? '#10b981' : '#94a3b8');
    }

    if ($conf) {
        const dots = { 'LOW': '●○○○', 'MEDIUM': '●●○○', 'HIGH': '●●●○', 'VERY_HIGH': '●●●●' };
        const confColors = { 'LOW': '#64748b', 'MEDIUM': '#eab308', 'HIGH': '#10b981', 'VERY_HIGH': '#3b82f6' };
        $conf.textContent = conf + ' ' + (dots[conf] || '○○○○');
        $conf.style.color = confColors[conf] || '#94a3b8';
    }

    // HF sub-indicator radar
    const radarEl = document.getElementById('hf-radar-chart');
    if (!radarEl || typeof echarts === 'undefined' || !hf.breakdown) return;
    try { window._hfRadar = AC.disposeChart(window._hfRadar); } catch(_) {}
    window._hfRadar = AC.registerChart(echarts.init(radarEl));

    const bd = hf.breakdown;
    // 后端键名: turnover/etf_flow/margin_delta, 值结构: {normalized, weight, contribution}
    const radarData = [
        bd.turnover?.normalized ?? bd.turnover_zscore?.normalized ?? 0,
        bd.etf_flow?.normalized ?? bd.etf_flow_rank?.normalized ?? 0,
        bd.margin_delta?.normalized ?? bd.margin_delta_5d?.normalized ?? 0
    ].map(v => Math.min(Math.max((v + 1) * 50, 0), 100)); // [-1,1] → [0,100]

    window._hfRadar.setOption({
        backgroundColor: 'transparent',
        radar: {
            indicator: [
                { name: '换手率', max: 100 },
                { name: 'ETF流', max: 100 },
                { name: '融资Δ', max: 100 }
            ],
            radius: '60%',
            nameTextStyle: { color: '#94a3b8', fontSize: 9 },
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            splitArea: { show: false }
        },
        series: [{
            type: 'radar',
            data: [{ value: radarData, areaStyle: { color: 'rgba(245,158,11,0.15)' } }],
            lineStyle: { color: '#f59e0b', width: 2 },
            itemStyle: { color: '#f59e0b' },
            symbol: 'circle', symbolSize: 5
        }]
    });
}

function renderFactorTrendChart(trend) {
    const container = document.getElementById('aiae-factor-trend-chart');
    if (!container || typeof echarts === 'undefined') return;
    try { window._ftChart = AC.disposeChart(window._ftChart); } catch(_) {}
    window._ftChart = AC.registerChart(echarts.init(container));

    const series = trend.series;
    const dates = trend.dates || [];
    const colors = { 'aiae_simple': '#f59e0b', 'fund_position': '#eab308', 'margin_heat': '#f97316' };
    const names = { 'aiae_simple': 'AIAE简', 'fund_position': '基金仓位', 'margin_heat': '融资热度' };

    // series 格式: {aiae_simple: {label: "...", values: [...]}} 或 {aiae_simple: [...]}
    const echartsData = Object.entries(series).map(([key, valOrObj]) => {
        const vals = Array.isArray(valOrObj) ? valOrObj : (valOrObj?.values || []);
        return {
            name: names[key] || (valOrObj?.label) || key,
            type: 'line', stack: 'factor', areaStyle: { opacity: 0.4 },
            data: vals, smooth: true,
            lineStyle: { width: 1.5, color: colors[key] || '#94a3b8' },
            itemStyle: { color: colors[key] || '#94a3b8' },
            symbol: 'none'
        };
    });

    window._ftChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(245,158,11,0.3)',
            textStyle: { color: '#e2e8f0', fontSize: 11 }
        },
        legend: {
            data: Object.values(names), top: 0, right: 10,
            textStyle: { color: '#94a3b8', fontSize: 10 }
        },
        grid: { left: 45, right: 15, top: 30, bottom: 30 },
        xAxis: {
            type: 'category', data: dates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 9 },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: '#64748b', fontSize: 9 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
        },
        series: echartsData
    });
}

// ═══════════════════════════════════════════════════════════════
//  ZONE 7: 实盘健康度 + 跨市场 + 对账
// ═══════════════════════════════════════════════════════════════

async function loadAndRenderZone7() {
    const [devResp, alertResp, reconResp] = await Promise.allSettled([
        fetch('/api/v1/aiae/deviation', { signal: AbortSignal.timeout(8000) }).then(r => r.json()),
        fetch('/api/v1/aiae/cross_market_alerts', { signal: AbortSignal.timeout(8000) }).then(r => r.json()),
        fetch('/api/v1/aiae/reconciliation', { signal: AbortSignal.timeout(8000) }).then(r => r.json()),
    ]);

    const dev = devResp.status === 'fulfilled' ? devResp.value : null;
    const alerts = alertResp.status === 'fulfilled' ? alertResp.value : null;
    const recon = reconResp.status === 'fulfilled' ? reconResp.value : null;

    if (dev && dev.status === 'success') {
        renderHealthGauge(dev.health_score);
        renderHealthRadar(dev.health_score);
        renderDeviationStats(dev);
        renderReductionList(dev.reduction_candidates);
    }
    if (alerts) {
        renderCrossMarketAlerts(alerts);
    }
    if (recon && recon.status === 'success') {
        renderReconSummary(recon);
    }
}

function renderHealthGauge(hs) {
    if (!hs) return;
    const container = document.getElementById('aiae-health-gauge');
    if (!container || typeof echarts === 'undefined') return;
    try { window._healthGauge = AC.disposeChart(window._healthGauge); } catch(_) {}
    window._healthGauge = AC.registerChart(echarts.init(container));

    const score = hs.score || 0;
    const gradeColors = { 'S': '#10b981', 'A': '#3b82f6', 'B': '#eab308', 'C': '#f97316', 'D': '#ef4444' };
    const color = gradeColors[hs.grade?.[0]] || '#f59e0b';

    window._healthGauge.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20,
            min: 0, max: 100,
            pointer: { length: '55%', width: 4, itemStyle: { color: color } },
            anchor: { show: true, size: 8, itemStyle: { color: '#0f172a', borderColor: color, borderWidth: 2 } },
            axisLine: {
                lineStyle: {
                    width: 12,
                    color: [[0.3, '#ef4444'], [0.5, '#f97316'], [0.7, '#eab308'], [0.85, '#3b82f6'], [1, '#10b981']]
                }
            },
            axisTick: { show: false },
            splitLine: { show: false },
            axisLabel: { show: false },
            detail: { show: false },
            data: [{ value: score }],
            animationDuration: 1200
        }]
    });

    const $grade = document.getElementById('aiae-health-grade');
    const $msg = document.getElementById('aiae-health-msg');
    if ($grade) { $grade.textContent = score + '/' + (hs.grade || '—'); $grade.style.color = color; }
    // 后端无 verdict 字段, 根据 grade 生成
    const verdictMap = { 'A': '健康', 'B+': '良好', 'B': '偏弱', 'C+': '需改善', 'C': '风险', 'D': '危险' };
    if ($msg) $msg.textContent = hs.verdict || verdictMap[hs.grade] || '';
}

function renderHealthRadar(hs) {
    if (!hs || !hs.breakdown) return;
    const container = document.getElementById('aiae-health-radar');
    if (!container || typeof echarts === 'undefined') return;
    try { window._healthRadar = AC.disposeChart(window._healthRadar); } catch(_) {}
    window._healthRadar = AC.registerChart(echarts.init(container));

    const bd = hs.breakdown;
    const dims = ['position', 'etf_coverage', 'concentration', 'allocation', 'stop_loss', 'freshness'];
    const labels = ['仓位', 'ETF覆盖', '集中度', '配额', '止损', '新鲜度'];
    // breakdown 返回扁平格式 {position: 70} 而非 {position: {score: 70}}
    const values = dims.map(d => {
        const v = bd[d];
        return (typeof v === 'number') ? v : (v?.score ?? 50);
    });

    window._healthRadar.setOption({
        backgroundColor: 'transparent',
        radar: {
            indicator: labels.map(l => ({ name: l, max: 100 })),
            radius: '65%',
            nameTextStyle: { color: '#94a3b8', fontSize: 9 },
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            splitArea: { show: false }
        },
        series: [{
            type: 'radar',
            data: [{ 
                value: values, 
                areaStyle: { 
                    color: new echarts.graphic.RadialGradient(0.5, 0.5, 0.8, [
                        { offset: 0, color: 'rgba(245, 158, 11, 0.05)' },
                        { offset: 1, color: 'rgba(245, 158, 11, 0.22)' }
                    ])
                } 
            }],
            lineStyle: { 
                color: '#f59e0b', 
                width: 2.5,
                shadowColor: 'rgba(245, 158, 11, 0.4)',
                shadowBlur: 10
            },
            itemStyle: { color: '#f59e0b' },
            symbol: 'circle', symbolSize: 5
        }]
    });
}

function renderDeviationStats(dev) {
    const pd = dev.position_deviation;
    const conc = dev.concentration;
    const etf = dev.etf_coverage;

    const $gap = document.getElementById('dev-gap');
    const $etf = document.getElementById('dev-etf');
    const $max = document.getElementById('dev-max');
    const $conc = document.getElementById('dev-conc');

    if ($gap && pd) {
        const gap = pd.gap ?? pd.gap_pt;
        if (gap !== null && gap !== undefined) {
            const absGap = Math.abs(gap);
            let badgeClass = 'compliant';
            let badgeText = 'Compliant';
            if (absGap > 8.0) {
                badgeClass = 'hard-breach';
                badgeText = 'Hard Breach';
            } else if (absGap > 3.0) {
                badgeClass = 'soft-warning';
                badgeText = 'Soft Limit';
            }
            $gap.innerHTML = `${gap.toFixed(1)} pt <span class="aiae-compliance-badge ${badgeClass}">${badgeText}</span>`;
        } else {
            $gap.textContent = '—';
        }
    }
    if ($etf && etf) $etf.textContent = etf.held_count + '/' + etf.total_count + ' (' + etf.coverage_pct + '%)';
    if ($max && conc) {
        if (conc.max_name) {
            $max.textContent = conc.max_name + ' ' + (conc.max_pct || 0).toFixed(1) + '%';
        } else if (conc.positions && conc.positions.length) {
            const top = conc.positions[0];
            $max.textContent = top.name + ' ' + top.pct.toFixed(1) + '%';
        }
    }
    if ($conc && conc) {
        $conc.textContent = conc.verdict;
        $conc.style.color = conc.verdict === '红线违规' ? '#ef4444' : (conc.alert_count > 0 ? '#f97316' : '#10b981');
    }

    // 🔬 交互式调仓执行建议与滑点估计 (ADV Desk)
    const $desk = _aiaeDOM['slippage-desk'];
    const $sSize = _aiaeDOM['slip-size'];
    const $sCost = _aiaeDOM['slip-cost'];
    const $sAlgo = _aiaeDOM['slip-algo'];
    const $sizeSelect = _aiaeDOM['slip-size-select'];

    if ($desk && pd) {
        const gap = pd.gap ?? pd.gap_pt;
        if (gap !== null && gap !== undefined && Math.abs(gap) > 0.05) {
            $desk.style.display = 'block';
            
            // 获取交互选择的总资产规模 (若无，fallback 到 5000 万)
            const portfolioSize = $sizeSelect ? parseFloat($sizeSelect.value) : 50000000;
            const tradeSize = (portfolioSize * Math.abs(gap) / 100);
            
            // 经典的非线性滑点预估公式：基于绝对交易额相比于日均基准流量（设 ADV 盘中单批承载力为 250 万人民币）
            // 经验模型: 1.5bps 固差 + 0.8 * (tradeSize / 2,500,000)^0.6 冲击系数
            const estSlippageBps = 1.5 + 0.8 * Math.pow(tradeSize / 2500000, 0.6);
            
            // 交互式执行建议算法选择联动
            let algo = '主动盘中限价单 (Limit Order)';
            if (tradeSize > 20000000) {
                algo = '大额调仓：建议 VWAP 算法，分 2 天分批执行';
            } else if (tradeSize > 5000000) {
                algo = '建议 TWAP 算法，分 1 天内执行';
            } else if (Math.abs(gap) > 8.0) {
                algo = '建议 VWAP 算法，分 2 天分批执行';
            } else if (Math.abs(gap) > 4.0) {
                algo = '建议 TWAP 算法，分 1 天内执行';
            } else if (Math.abs(gap) > 1.5) {
                algo = '盘中主动分拆下单 (约 2-4 小时)';
            }
            
            if ($sSize) $sSize.textContent = (tradeSize / 10000).toFixed(1) + ' 万 RMB';
            if ($sCost) $sCost.textContent = `~${estSlippageBps.toFixed(1)} bps (${(tradeSize * estSlippageBps / 10000).toFixed(0)} 元)`;
            if ($sAlgo) {
                $sAlgo.textContent = algo;
                $sAlgo.style.color = tradeSize > 20000000 || Math.abs(gap) > 8.0 ? '#ef4444' : (tradeSize > 5000000 || Math.abs(gap) > 4.0 ? '#f97316' : '#60a5fa');
            }
        } else {
            $desk.style.display = 'none';
        }
    } else if ($desk) {
        $desk.style.display = 'none';
    }
}

function renderReductionList(rc) {
    const panel = document.getElementById('aiae-reduction-panel');
    const list = document.getElementById('aiae-reduction-list');
    if (!panel || !list || !rc) return;

    if (!rc.count || rc.count === 0) { panel.style.display = 'none'; return; }
    panel.style.display = 'block';

    // 后端字段: candidates (非 items), pct (非 position_pct), ts_code (非 code)
    const items = rc.candidates || rc.items || [];
    if (!items.length) { panel.style.display = 'none'; return; }
    list.innerHTML = items.map(item =>
        `<div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.04);">
            <span><b style="color:#f87171">${item.name}</b> (${item.ts_code || item.code || ''})</span>
            <span>占比 <b>${(item.pct ?? item.position_pct ?? 0).toFixed(1)}%</b> · 浮盈 <b style="color:${item.pnl_pct > 0 ? '#10b981' : '#ef4444'}">${item.pnl_pct > 0 ? '+' : ''}${item.pnl_pct.toFixed(1)}%</b> · 优先级 ${item.priority.toFixed(2)}</span>
        </div>`
    ).join('');
}

function renderCrossMarketAlerts(data) {
    const regimeBar = document.getElementById('aiae-cross-regime-bar');
    const alertsEl = document.getElementById('aiae-cross-alerts');
    const emptyEl = document.getElementById('aiae-cross-empty');

    // Regime bar
    if (regimeBar && data.regimes) {
        const regimeColors = { 1: '#10b981', 2: '#3b82f6', 3: '#eab308', 4: '#f97316', 5: '#ef4444' };
        const marketNames = { 'CN': 'A股', 'US': '美股', 'HK': '港股', 'JP': '日股' };
        regimeBar.innerHTML = Object.entries(data.regimes).map(([mkt, r]) => {
            const c = regimeColors[r] || '#94a3b8';
            return `<div style="flex:1; text-align:center; padding:8px; background:rgba(255,255,255,0.03); border-radius:8px; border:1px solid ${c}33;">
                <div style="font-size:0.65rem; color:#64748b;">${marketNames[mkt] || mkt}</div>
                <div style="font-size:1.1rem; font-weight:800; color:${c}; font-family:'Outfit',sans-serif;">R${r}</div>
            </div>`;
        }).join('');
    }

    // Alerts
    const alerts = data.alerts || [];
    if (alertsEl) {
        if (alerts.length === 0) {
            alertsEl.innerHTML = '';
            if (emptyEl) emptyEl.style.display = 'block';
        } else {
            if (emptyEl) emptyEl.style.display = 'none';
            const sevColors = { 'critical': '#ef4444', 'warning': '#f97316', 'opportunity': '#10b981', 'info': '#3b82f6' };
            const sevIcons = { 'critical': '🔴', 'warning': '⚠️', 'opportunity': '🟢', 'info': 'ℹ️' };
            alertsEl.innerHTML = alerts.map(a => {
                const c = sevColors[a.severity] || '#94a3b8';
                return `<div style="padding:12px 16px; background:${c}08; border:1px solid ${c}33; border-radius:10px; border-left:3px solid ${c};">
                    <div style="font-size:0.8rem; font-weight:700; color:${c};">${sevIcons[a.severity] || ''} ${a.title}</div>
                    <div style="font-size:0.7rem; color:#94a3b8; margin-top:4px; line-height:1.5;">${a.action || ''}</div>
                    ${a.contagion_coef ? '<div style="font-size:0.65rem; color:#64748b; margin-top:2px;">传导系数: ' + a.contagion_coef + '</div>' : ''}
                </div>`;
            }).join('');
        }
    }

    // 🌐 跨市场风险传染系数矩阵 (Contagion Correlation Matrix)
    const mContainer = _aiaeDOM['contagion-matrix-container'];
    const mTableContainer = _aiaeDOM['contagion-matrix'];
    if (mContainer && mTableContainer && data.contagion_matrix && data.contagion_matrix.matrix) {
        mContainer.style.display = 'block';
        const matrix = data.contagion_matrix.matrix;
        const markets = ['CN', 'US', 'HK', 'JP'];
        const mNames = { 'CN': 'A股', 'US': '美股', 'HK': '港股', 'JP': '日股' };
        
        let html = '<table class="aiae-contagion-table">';
        html += '<thead><tr><th>源 ➔ 宿</th>' + markets.map(m => `<th>${mNames[m]}</th>`).join('') + '</tr></thead>';
        html += '<tbody>';
        
        markets.forEach(src => {
            html += `<tr><td>${mNames[src]}</td>`;
            markets.forEach(dest => {
                const key = `${src}➔${dest}`;
                const keyAlt = `${src}→${dest}`;
                const val = matrix[key] ?? matrix[keyAlt] ?? (src === dest ? 1.0 : 0.0);
                
                // 根据传染系数分配热力背景色 (红、橙、蓝)
                let bgColor = 'rgba(255,255,255,0.01)';
                let textColor = '#cbd5e1';
                if (src !== dest) {
                    if (val >= 0.7) {
                        bgColor = `rgba(239, 68, 68, ${val * 0.28})`; // 强传染: 红色
                        textColor = '#f87171';
                    } else if (val >= 0.4) {
                        bgColor = `rgba(249, 115, 22, ${val * 0.22})`;  // 中传染: 橙色
                        textColor = '#fbd58d';
                    } else if (val >= 0.2) {
                        bgColor = `rgba(59, 130, 246, ${val * 0.18})`; // 弱传染: 蓝色
                        textColor = '#93c5fd';
                    }
                } else {
                    bgColor = 'rgba(255, 255, 255, 0.04)';
                    textColor = '#94a3b8';
                }
                
                html += `<td style="background: ${bgColor}; color: ${textColor}">${val.toFixed(2)}</td>`;
            });
            html += '</tr>';
        });
        
        html += '</tbody></table>';
        mTableContainer.innerHTML = html;
    } else if (mContainer) {
        mContainer.style.display = 'none';
    }
}

function renderReconSummary(recon) {
    const pos = recon.position_reconciliation;
    const trades = recon.trade_analysis;

    if (pos && pos.summary) {
        const $gap = document.getElementById('recon-gap');
        const $comp = document.getElementById('recon-compliance');
        const $score = document.getElementById('recon-score');
        // avg_gap_pt 可能为 null, 兼容 avg_gap
        const gapVal = pos.summary.avg_gap_pt ?? pos.summary.avg_gap ?? 0;
        if ($gap) $gap.textContent = (typeof gapVal === 'number' ? gapVal.toFixed(1) : gapVal) + 'pt';
        if ($comp) $comp.textContent = pos.summary.compliance_rate_pct?.toFixed(1) + '%';
        if ($score) $score.textContent = pos.summary.score + '/100';
    }
    if (trades && trades.status === 'success') {
        const $bsr = document.getElementById('recon-bsr');
        if ($bsr) $bsr.textContent = (trades.buy_sell_ratio || 0).toFixed(2);
    }
}

// 页面首次加载时，如果AIAE是默认active tab则自动加载
document.addEventListener('DOMContentLoaded', function() {
    const aiaeTab = document.querySelector('.st-tab[data-report="st-aiae-position"]');
    if (aiaeTab && aiaeTab.classList.contains('active')) {
        setTimeout(() => loadAIAEReport(), 500);
    }
});

// Phase 2: resize 已由 alphacore_utils.js 注册中心统一处理
