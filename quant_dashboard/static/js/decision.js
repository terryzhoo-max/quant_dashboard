/**
 * AlphaCore V21.2 · 决策中枢 JS (主入口)
 * ========================================
 * 模块化架构 V1.0:
 *   decision/_infra.js          — 共享基础设施 (API_BASE, _getChart, _fmt)
 *   decision/hub_core.js        — JCS 环 + 矛盾矩阵 + AIAE 仓位管控
 *   decision/simulation.js      — 情景模拟 + 决策时间线 + 回测
 *   decision/global_analytics.js — 全球温度 + 日历 + 阈值速查
 *   decision/perf_matrix.js     — 绩效分析 + 多基准对比
 *   decision/swing_guard.js     — 波段守卫
 *   decision/risk_alerts.js     — 风险面板 + 预警 + 日报
 *   decision.js                 — 初始化调度 (本文件, 最后加载)
 *
 * 加载顺序: echarts → alphacore_utils → _infra → 6 模块 → 本文件
 */

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

            // V24.0: Tab 切换后瞬间回顶 (不用 smooth，Tab 切换应零延迟)
            window.scrollTo(0, 0);

            // 切到对应 tab 时懒加载数据
            if (tab.dataset.tab === 'tab-timeline') loadTimeline();
            if (tab.dataset.tab === 'tab-risk') loadRiskMatrix();
            if (tab.dataset.tab === 'tab-calendar') loadCalendar();
        });
    });
}

// ═══════════════════════════════════════════════════
//  V19.3: 异步加载超时降级
// ═══════════════════════════════════════════════════

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
//  V24.0: 可折叠面板通用切换 + LazyInit
// ═══════════════════════════════════════════════════

let _cachedGlobalTemp = null;   // 全球温度 LazyInit 缓存
let _globalTempRendered = false; // Gauge 是否已渲染

function toggleDHPanel(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    const isCollapsed = panel.classList.contains('collapsed');
    panel.classList.toggle('collapsed');

    // LazyInit: 全球温度面板展开时初始化 ECharts Gauge
    if (panelId === 'global-temp-panel' && isCollapsed && _cachedGlobalTemp && !_globalTempRendered) {
        requestAnimationFrame(() => {
            renderGlobalTemperature(_cachedGlobalTemp);
            _globalTempRendered = true;
        });
    }
}

// ═══════════════════════════════════════════════════
//  V24.0: 全球温度摘要行 (折叠态显示)
// ═══════════════════════════════════════════════════

function _updateGlobalTempSummary(gt) {
    const el = document.getElementById('global-temp-summary');
    if (!el || !gt || !gt.markets) return;
    const names = {cn: 'A股', us: '美股', hk: '港股', jp: '日股'};
    const parts = gt.markets
        .filter(m => m.status !== 'loading')
        .slice(0, 4)
        .map(m => `${names[m.key] || m.name} R${m.regime}${m.regime_cn || ''}`);
    el.textContent = parts.join(' · ') || '加载中...';
}

// ═══════════════════════════════════════════════════
//  V24.0: 风控护栏进度条渲染
// ═══════════════════════════════════════════════════

function _updateGuardrailBars(data) {
    const tail = data.tail_risk || {};
    const comps = tail.components || {};
    const codes = data.multi_strategy_codes || [];

    const bars = [
        { id: 'rg-bar-conc', val: comps.concentration || 0, max: 100 },
        { id: 'rg-bar-aiae', val: comps.aiae || 0, max: 100 },
        { id: 'rg-bar-vix',  val: comps.vix || 0, max: 100 },
        { id: 'rg-bar-overlap', val: codes.length, max: 12 },
    ];

    bars.forEach(b => {
        const el = document.getElementById(b.id);
        if (!el) return;
        const pct = Math.min(100, (b.val / b.max) * 100);
        const color = b.val >= 50 ? '#ef4444' : (b.val >= 30 ? '#f97316' : '#10b981');
        el.style.width = pct + '%';
        el.style.background = color;
    });
    // 重叠度使用不同阈值
    const overlapBar = document.getElementById('rg-bar-overlap');
    if (overlapBar) {
        const v = codes.length;
        const color = v >= 8 ? '#ef4444' : (v >= 4 ? '#f97316' : '#10b981');
        overlapBar.style.background = color;
    }
}

// ═══════════════════════════════════════════════════
//  页面初始化 (主调度器)
// ═══════════════════════════════════════════════════

async function initDecisionHub() {
    _riskMatrixCache = null;  // V20.0: 刷新时清除缓存
    window._riskMatrixCacheTs = 0; // V25.1: 对齐 TTL 缓存时间戳
    if (typeof resetRiskTabGuards === 'function') resetRiskTabGuards(); // V25.1: 重置 Risk Tab guards

    // P4: 版本号自动同步 (fire-and-forget, 不阻塞主流程)
    fetch('/version').then(r => r.json()).then(v => {
        const short = 'V' + v.version;
        document.querySelectorAll('#ac-ver-nav, #ac-ver-header').forEach(el => { if (el) el.textContent = short; });
    }).catch(() => {});

    initTabs();
    initSOPToggle();  // V19.3: SOP 折叠事件委托

    try {
        // V19.3: 异步独立请求 + 超时降级
        _fetchWithDegradation('swing-guard-grid', fetchSwingGuard, '波段守卫');
        _fetchWithDegradation('compliance-engine-panel', loadRiskGuardrail, '合规引擎');

        // V20.0: Hub 主 API 超时保护 (15s)
        const _hubCtrl = new AbortController();
        const _hubTimeout = setTimeout(() => _hubCtrl.abort(), 15000);
        const resp = await AC.secureFetch(`${API_BASE}/hub`, { signal: _hubCtrl.signal });
        clearTimeout(_hubTimeout);
        const data = await resp.json();

        if (data.status === 'success') {
            // ① 警示系统 (最高优先级，顶部)
            renderAlerts(data.alerts || []);

            // V21.2: 数据新鲜度状态栏
            if (data.data_freshness) renderFreshnessBar(data.data_freshness, data.timestamp, data.data_date, data.date_consistent);

            // V20.0: 冷启动透明度
            if (data.snapshot?._data_quality?.is_cold_start) {
                const acEl = document.getElementById('alert-container');
                if (acEl) acEl.innerHTML = `<div class="alert-card alert-caution">
                    <div class="alert-header"><span class="alert-icon">⚡</span><span class="alert-title">数据预热中</span></div>
                    <div class="alert-detail">缓存尚未完成预热，当前 JCS 基于默认值计算。请等待 1-2 分钟后刷新。</div>
                    <span class="alert-rule">规则: 冷启动期间不依据 JCS 执行任何操作</span>
                </div>` + acEl.innerHTML;
            }

            // ② AIAE 宏观仓位管控
            if (data.snapshot) renderAIAEHub(data.snapshot);

            // ③ JCS 环形图 + 成分拆解
            drawJCSRing(data.jcs.score, data.jcs.level);
            const labelEl = document.getElementById('jcs-label');
            if (labelEl) labelEl.textContent = data.jcs.label;
            renderJCSComponents(data.jcs);
            // V22.0: 信号时效衰减指示器
            if (data.signal_decay) renderSignalDecay(data.signal_decay);

            // ④ 方向指示器
            renderDirections(data.jcs.directions, data.snapshot);

            // ⑤ 矛盾检测
            renderConflicts(data.conflicts);

            // ⑥ 执行指令
            if (data.action_plan) renderActionPlan(data.action_plan);

            // V22.0: 合规检查徽章
            if (data.compliance) renderComplianceBadge(data.compliance);

            // V22.0: 仓位调整路径 (独立异步, 不阻塞主流程)
            fetchPositionPath();

            // ⑦ 信号阈值速查表
            if (data.snapshot) highlightThresholdTable(data.snapshot);

            // V22.0: 动态市场事件
            if (data.market_events && data.market_events.length > 0) renderMarketEvents(data.market_events);

            // ⑧ 全球市场温度 — 缓存数据 + 摘要行 (LazyInit: 折叠态不渲染 Gauge)
            if (data.global_temperature) {
                _cachedGlobalTemp = data.global_temperature;
                _globalTempRendered = false;
                _updateGlobalTempSummary(data.global_temperature);
                // 如果面板已展开则立即渲染
                const gtPanel = document.getElementById('global-temp-panel');
                if (gtPanel && !gtPanel.classList.contains('collapsed')) {
                    renderGlobalTemperature(data.global_temperature);
                    _globalTempRendered = true;
                }
            }

            // V22.0: 跨市场风险传染热度图 (独立异步, 不阻塞主流程)
            fetchContagionMatrix();

            // ⑨ 情景模拟器
            renderScenarioCards(data.scenarios);

            // ⑪ P2-C: NLP 情报中心 (独立异步)
            loadIntelligence();

            // ⑫ P4: AI 叙事分析 (独立异步)
            loadNarrative();

            // V25.2: ⑩ 信号准确率 (独立异步, 不阻塞主流程)
            AC.secureFetch(`${API_BASE}/accuracy`).then(r => r.json()).then(acc => {
                if (acc.status === 'success') renderAccuracy(acc);
            }).catch(e => console.warn('Accuracy load:', e));
        } else {
            document.getElementById('jcs-value').textContent = '--';
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            console.warn('Decision hub request timed out (15s)');
            const jcsEl = document.getElementById('jcs-value');
            if (jcsEl) jcsEl.textContent = '--';
            const csEl = document.getElementById('conflict-summary');
            if (csEl) { csEl.className = 'conflict-summary warn'; csEl.textContent = '⚠️ 数据加载超时，请点击顶部「刷新决策数据」重试'; }
        } else {
            console.error('Decision hub load error:', e);
        }
        document.querySelector('.loading-spinner')?.remove();
    }
}

// ═══════════════════════════════════════════════════
//  V20.0: 全局生命周期管理
// ═══════════════════════════════════════════════════

// 统一 resize handler
window.addEventListener('resize', () => {
    Object.values(_chartInstances).forEach(c => c && !c.isDisposed() && c.resize());
    if (typeof _globalTempCharts !== 'undefined') {
        Object.values(_globalTempCharts).forEach(c => c && !c.isDisposed() && c.resize());
    }
});

// 页面卸载时统一销毁所有 ECharts 实例
window.addEventListener('beforeunload', () => {
    Object.values(_chartInstances).forEach(c => c && c.dispose());
    if (typeof _globalTempCharts !== 'undefined') {
        Object.values(_globalTempCharts).forEach(c => c && c.dispose());
    }
});

// ═══════════════════════════════════════════════════
//  启动
// ═══════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initDecisionHub();
    startAlertPolling();
});

// ═══════════════════════════════════════════════════
//  V22.0: 策略参数版本对比器
// ═══════════════════════════════════════════════════

let _paramVersions = [];

async function openParamCompare() {
    const overlay = document.getElementById('param-compare-overlay');
    if (!overlay) return;

    // 加载版本列表
    try {
        const resp = await fetch(`${API_BASE}/param-versions`);
        const data = await resp.json();
        if (data.status === 'success') {
            _paramVersions = data.versions || [];
            _populateVersionSelects();
        }
    } catch (e) {
        console.warn('Param versions load error:', e);
    }

    overlay.classList.add('active');
    document.addEventListener('keydown', _pcEscHandler);
}

function closeParamCompare(e) {
    if (e && e.target && !e.target.classList.contains('report-overlay')) return;
    const overlay = document.getElementById('param-compare-overlay');
    if (overlay) overlay.classList.remove('active');
    document.removeEventListener('keydown', _pcEscHandler);
}

function _pcEscHandler(e) {
    if (e.key === 'Escape') closeParamCompare();
}

function _populateVersionSelects() {
    const selA = document.getElementById('pc-version-a');
    const selB = document.getElementById('pc-version-b');
    const btn = document.getElementById('btn-compare-run');
    const result = document.getElementById('pc-result');
    if (!selA || !selB) return;

    // P5: 优先显示描述 + AIAE版本标记
    const options = _paramVersions.map(v => {
        const label = v.description || v.version_id;
        const ts = v.timestamp ? v.timestamp.split('T')[0] : '';
        return `<option value="${v.version_id}">${label}${ts ? ' (' + ts + ')' : ''}</option>`;
    }).join('');

    selA.innerHTML = '<option value="">-- 选择版本 --</option>' + options;
    selB.innerHTML = '<option value="">-- 选择版本 --</option>' + options;

    // P6: 空版本引导态
    if (_paramVersions.length === 0 && result) {
        result.innerHTML = '<div style="text-align:center;padding:24px;color:#64748b;font-size:0.78rem;">📸 尚无参数快照。点击「保存快照」记录当前参数配置，<br>即可开始版本对比与敏感度分析。</div>';
    }

    // Auto-enable compare button when both selected
    const checkReady = () => {
        if (btn) btn.disabled = !(selA.value && selB.value);
    };
    selA.addEventListener('change', checkReady);
    selB.addEventListener('change', checkReady);
}

async function saveParamSnapshot() {
    const btn = document.querySelector('#param-compare-overlay .btn-sm');
    if (!btn) return;
    const origText = btn.textContent;
    btn.textContent = '⏳ 保存中...';
    btn.disabled = true;

    try {
        const headers = {};
        const apiKey = localStorage.getItem('alphacore_api_key');
        if (apiKey) headers['X-API-Key'] = apiKey;
        const resp = await fetch(`${API_BASE}/param-snapshot`, { method: 'POST', headers });
        const data = await resp.json();
        if (data.status === 'success') {
            btn.textContent = '✅ 已保存 ' + data.version_id;
            // 刷新列表
            const listResp = await fetch(`${API_BASE}/param-versions`);
            const listData = await listResp.json();
            if (listData.status === 'success') {
                _paramVersions = listData.versions || [];
                _populateVersionSelects();
            }
        } else {
            btn.textContent = '❌ 保存失败';
        }
    } catch (e) {
        btn.textContent = '❌ 网络错误';
    } finally {
        setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
        }, 2000);
    }
}

async function runParamCompare() {
    const selA = document.getElementById('pc-version-a');
    const selB = document.getElementById('pc-version-b');
    const result = document.getElementById('pc-result');
    if (!selA || !selB || !result) return;

    const v1 = selA.value;
    const v2 = selB.value;
    if (!v1 || !v2) return;

    result.innerHTML = '<div style="text-align:center;padding:20px;color:#94a3b8;">⏳ 对比中...</div>';

    try {
        const resp = await fetch(`${API_BASE}/param-compare?v1=${encodeURIComponent(v1)}&v2=${encodeURIComponent(v2)}`);
        const data = await resp.json();

        if (data.status === 'success') {
            const jcsDiff = data.result_b.jcs_score - data.result_a.jcs_score;
            const diffSign = jcsDiff > 0 ? '+' : '';
            const diffColor = jcsDiff > 0 ? '#34d399' : (jcsDiff < 0 ? '#f87171' : '#94a3b8');

            const levelMap = { high: '🟢 高', medium: '🟡 中', low: '🔴 低' };

            result.innerHTML = `
            <div class="pc-compare-grid">
                <div class="pc-compare-col pc-col-a">
                    <div class="pc-col-header">版本 A: ${v1}</div>
                    <div class="pc-metric"><span>JCS</span><span class="pc-val">${data.result_a.jcs_score}</span></div>
                    <div class="pc-metric"><span>置信度</span><span>${levelMap[data.result_a.jcs_level] || data.result_a.jcs_level}</span></div>
                    <div class="pc-params-preview">${_renderParamPreview(data.version_a)}</div>
                </div>
                <div class="pc-compare-col pc-col-b">
                    <div class="pc-col-header">版本 B: ${v2}</div>
                    <div class="pc-metric"><span>JCS</span><span class="pc-val">${data.result_b.jcs_score}</span></div>
                    <div class="pc-metric"><span>置信度</span><span>${levelMap[data.result_b.jcs_level] || data.result_b.jcs_level}</span></div>
                    <div class="pc-params-preview">${_renderParamPreview(data.version_b)}</div>
                </div>
            </div>
            <div class="pc-diff-bar">
                <span>JCS 差异: </span>
                <span style="font-weight:700;color:${diffColor};font-size:1.1rem;">${diffSign}${jcsDiff.toFixed(1)}</span>
                ${data.diffs && data.diffs.length > 0 ? data.diffs.map(d => `<span class="pc-diff-item"> · ${d}</span>`).join('') : ''}
            </div>
            ${_renderMatrixDiffs(data.matrix_diffs)}
            <div class="pc-recommendation">💡 ${data.recommendation || ''}</div>
            <div class="pc-snapshot-note">📊 基于当前市场环境快照: AIAE R${data.current_snapshot?.aiae_regime || '?'} · ERP ${data.current_snapshot?.erp_score || '?'} · VIX ${data.current_snapshot?.vix_val || '?'}</div>
            `;
        } else {
            result.innerHTML = `<div style="text-align:center;padding:20px;color:#f87171;">⚠️ ${data.error || '对比失败'}</div>`;
        }
    } catch (e) {
        result.innerHTML = '<div style="text-align:center;padding:20px;color:#f87171;">⚠️ 网络异常</div>';
    }
}

function _renderParamPreview(ver) {
    if (!ver) return '';
    const chips = [];
    // JCS 权重
    const jw = ver.jcs_weights;
    if (jw) {
        Object.entries(jw).forEach(([k, v]) =>
            chips.push(`<span class="pc-param-chip">JCS/${k}: ${typeof v === 'number' ? (v * 100).toFixed(0) + '%' : v}</span>`));
    }
    // AIAE 权重
    const aw = ver.aiae_weights;
    if (aw) {
        Object.entries(aw).forEach(([k, v]) =>
            chips.push(`<span class="pc-param-chip">AIAE/${k}: ${typeof v === 'number' ? v.toFixed(2) : v}</span>`));
    }
    // 分界线
    const rt = ver.regime_thresholds;
    if (rt && Array.isArray(rt)) {
        chips.push(`<span class="pc-param-chip">分界: [${rt.join(', ')}]</span>`);
    }
    return chips.join('');
}

// P4: 仓位矩阵差异渲染
function _renderMatrixDiffs(diffs) {
    if (!diffs || diffs.length === 0) return '';
    const rows = diffs.map(d => {
        const color = d.delta < 0 ? '#f87171' : '#34d399';
        const sign = d.delta > 0 ? '+' : '';
        return `<tr style="font-size:0.62rem;color:#cbd5e1;">
            <td style="padding:3px 6px;">${d.erp}</td>
            <td style="padding:3px 6px;text-align:center;">${d.regime}</td>
            <td style="padding:3px 6px;text-align:right;">${d.before}%</td>
            <td style="padding:3px 6px;text-align:center;">→</td>
            <td style="padding:3px 6px;text-align:right;">${d.after}%</td>
            <td style="padding:3px 6px;text-align:right;font-weight:700;color:${color};">${sign}${d.delta}%</td>
        </tr>`;
    }).join('');
    return `
    <div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:rgba(15,23,42,0.5);border:1px solid rgba(255,255,255,0.05);">
        <div style="font-size:0.6rem;color:#64748b;margin-bottom:4px;font-weight:600;">📋 仓位矩阵变更明细</div>
        <table style="width:100%;border-collapse:collapse;">
            <thead><tr style="font-size:0.55rem;color:#475569;">
                <th style="text-align:left;padding:2px 6px;">ERP</th>
                <th style="text-align:center;padding:2px 6px;">档位</th>
                <th style="text-align:right;padding:2px 6px;">旧值</th>
                <th></th>
                <th style="text-align:right;padding:2px 6px;">新值</th>
                <th style="text-align:right;padding:2px 6px;">变化</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>
    </div>`;
}

// ═══════════════════════════════════════════════════
//  V22.0: 有向冲击传播模拟器
// ═══════════════════════════════════════════════════

let _shockSources = {};
let _shockNodes = {};

// 加载冲击源列表 (页面初始化时调用)
async function loadShockSources() {
    try {
        const resp = await fetch(`${API_BASE}/shock-sources`);
        const data = await resp.json();
        if (data.status === 'success') {
            _shockSources = data.sources || {};
            _shockNodes = data.nodes || {};
            _populateShockSelect();
        }
    } catch (e) { console.warn('Shock sources load:', e); }
}

function _populateShockSelect() {
    const sel = document.getElementById('shock-source-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 选择冲击源 --</option>' +
        Object.entries(_shockSources).map(([id, s]) =>
            `<option value="${id}">${s.icon} ${s.name}</option>`
        ).join('');
}

function switchSimMode(mode) {
    document.querySelectorAll('.sim-mode-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.sim-mode-tab[data-mode="${mode}"]`)?.classList.add('active');

    const grid = document.getElementById('scenario-grid');
    const panel = document.getElementById('shock-panel');
    const result = document.getElementById('sim-result');

    // V23.0: 切换时清除两侧残影
    if (result) { result.classList.remove('visible'); result.innerHTML = ''; }

    if (mode === 'shock') {
        if (grid) grid.style.display = 'none';
        if (panel) panel.classList.remove('initially-hidden');
        // 清除预设卡片选中态
        document.querySelectorAll('.scenario-card.active').forEach(c => c.classList.remove('active'));
        // 清除冲击面板旧结果
        const prop = document.getElementById('shock-propagation');
        if (prop) prop.innerHTML = '';
        if (Object.keys(_shockSources).length === 0) loadShockSources();
    } else {
        if (grid) grid.style.display = '';
        if (panel) panel.classList.add('initially-hidden');
    }
}

function onShockSourceChange() {
    const sel = document.getElementById('shock-source-select');
    const btn = document.getElementById('btn-shock-run');
    const src = _shockSources[sel?.value];
    if (btn) btn.disabled = !sel?.value;
    if (src) {
        const mag = document.getElementById('shock-magnitude');
        const val = document.getElementById('shock-mag-val');
        if (mag && val) {
            mag.value = src.default_magnitude;
            val.textContent = src.default_magnitude.toFixed(1) + 'σ';
        }
    }
}

function onShockMagChange() {
    const mag = document.getElementById('shock-magnitude');
    const val = document.getElementById('shock-mag-val');
    if (mag && val) val.textContent = parseFloat(mag.value).toFixed(1) + 'σ';
}

async function runShockPropagation() {
    const sel = document.getElementById('shock-source-select');
    const mag = document.getElementById('shock-magnitude');
    const panel = document.getElementById('shock-propagation');
    if (!sel?.value || !panel) return;

    panel.innerHTML = '<div class="loading-spinner">⏳ 冲击传播中...</div>';

    try {
        // V23.0: 统一认证 (POST 需要 API Key)
        const headers = { 'Content-Type': 'application/json' };
        const apiKey = localStorage.getItem('alphacore_api_key');
        if (apiKey) headers['X-API-Key'] = apiKey;

        const resp = await fetch(`${API_BASE}/shock-propagate`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                source: sel.value,
                magnitude: parseFloat(mag?.value || 1.0),
                steps: 3,
            }),
        });

        if (resp.status === 401 || resp.status === 403) {
            panel.innerHTML = '<div class="shock-error">🔒 需要 API Key 认证，请先在「预设情景」中触发一次模拟以输入 Key</div>';
            return;
        }

        const data = await resp.json();

        if (data.status === 'success') {
            renderShockResult(data);
        } else {
            panel.innerHTML = `<div class="shock-error">⚠️ ${data.error || '模拟失败'}</div>`;
        }
    } catch (e) {
        panel.innerHTML = '<div class="shock-error">⚠️ 网络异常</div>';
    }
}

function renderShockResult(data) {
    const panel = document.getElementById('shock-propagation');
    if (!panel) return;

    const prop = data.propagation;
    const nodeLabels = _shockNodes;

    // ── 传播路径卡片 ──
    const pathByStep = {};
    (prop.propagation_path || []).forEach(p => {
        pathByStep[p.step] = pathByStep[p.step] || [];
        pathByStep[p.step].push(p);
    });

    let pathHtml = '';
    Object.entries(pathByStep).forEach(([step, items]) => {
        const stepNum = parseInt(step);
        const stepLabel = stepNum === 0 ? '🎯 冲击源' : `↳ 第 ${stepNum} 跳`;
        const itemsHtml = items.map(p => {
            const nd = nodeLabels[p.node] || {};
            const dirIcon = p.shock_value > 0 ? '↑' : (p.shock_value < 0 ? '↓' : '→');
            const dirColor = p.shock_value > 0 ? '#f87171' : (p.shock_value < 0 ? '#60a5fa' : '#64748b');
            return `
            <div class="shock-node-card">
                <span class="shock-node-icon">${nd.icon || '●'}</span>
                <span class="shock-node-label">${nd.label || p.node}</span>
                <span class="shock-node-from">← ${p.incoming_from}</span>
                <span class="shock-node-val" style="color:${dirColor}">${dirIcon} ${Math.abs(p.shock_value).toFixed(2)}σ</span>
                <span class="shock-node-net">净: ${p.net_impact.toFixed(2)}σ</span>
            </div>`;
        }).join('');
        pathHtml += `<div class="shock-step-group">
            <div class="shock-step-label">${stepLabel}</div>
            <div class="shock-step-nodes">${itemsHtml}</div>
        </div>`;
    });

    // ── 影响对比 ──
    const b = data.before;
    const a = data.after;
    const jcsDiff = data.jcs_after.score - data.jcs_before.score;
    const mrMap = { BULL: '🟢', BEAR: '🔴', CRASH: '🛑', RANGE: '🟡' };

    panel.innerHTML = `
    <div class="shock-result-grid">
        <div class="shock-path-col">
            <div class="shock-path-title">🦠 传播路径</div>
            ${pathHtml}
            <div class="shock-summary">📊 ${prop.summary || ''}</div>
        </div>
        <div class="shock-compare-col">
            <div class="shock-path-title">📊 状态对比</div>
            <table class="shock-compare-table">
                <tr><th></th><th>冲击前</th><th>冲击后</th><th>Δ</th></tr>
                <tr><td>AIAE</td><td>R${b.aiae_regime} ${(b.aiae_v1||0).toFixed(1)}%</td><td>R${a.aiae_regime} ${(a.aiae_v1||0).toFixed(1)}%</td><td class="shock-delta">${(a.aiae_v1 - b.aiae_v1).toFixed(1)}%</td></tr>
                <tr><td>ERP</td><td>${(b.erp_val||0).toFixed(2)}% · ${b.erp_score}分</td><td>${(a.erp_val||0).toFixed(2)}% · ${a.erp_score}分</td><td class="shock-delta">${((a.erp_val||0) - (b.erp_val||0)).toFixed(2)}%</td></tr>
                <tr><td>VIX</td><td>${(b.vix_val||0).toFixed(1)}</td><td>${(a.vix_val||0).toFixed(1)}</td><td class="shock-delta">${((a.vix_val||0) - (b.vix_val||0)).toFixed(1)}</td></tr>
                <tr><td>MR</td><td>${mrMap[b.mr_regime]||''} ${b.mr_regime}</td><td>${mrMap[a.mr_regime]||''} ${a.mr_regime}</td><td class="shock-delta">${b.mr_regime !== a.mr_regime ? '⚠️ 切换' : '━'}</td></tr>
                <tr><td>仓位</td><td>${b.suggested_position}%</td><td>${a.suggested_position}%</td><td class="shock-delta" style="color:${a.suggested_position > b.suggested_position ? '#34d399' : '#f87171'}">${a.suggested_position > b.suggested_position ? '+' : ''}${a.suggested_position - b.suggested_position}%</td></tr>
                <tr class="shock-jcs-row"><td>JCS</td><td>${data.jcs_before.score} · ${data.jcs_before.level}</td><td>${data.jcs_after.score} · ${data.jcs_after.level}</td><td class="shock-delta" style="color:${jcsDiff > 0 ? '#34d399' : '#f87171'}">${jcsDiff > 0 ? '+' : ''}${jcsDiff.toFixed(0)}</td></tr>
            </table>
            ${data.impact_summary && data.impact_summary.length > 0 ? `
            <div class="shock-impact-list">
                ${data.impact_summary.map(i => `<div class="shock-impact-item">• ${i}</div>`).join('')}
            </div>` : ''}
        </div>
    </div>`;
}

// ═══════════════════════════════════════════════════
//  V22.0: 动态市场事件卡片
// ═══════════════════════════════════════════════════

function renderMarketEvents(events) {
    const strip = document.getElementById('events-strip');
    const cards = document.getElementById('events-cards');
    if (!strip || !cards || !events.length) return;

    strip.classList.remove('initially-hidden');

    const sevColors = { extreme: '#ef4444', high: '#f97316', medium: '#fbbf24', low: '#64748b' };
    const sevLabels = { extreme: '极端', high: '高影响', medium: '中等', low: '信息' };

    cards.innerHTML = events.slice(0, 6).map(e => {
        const color = sevColors[e.severity] || '#64748b';
        const shockInfo = e.shock_result
            ? `<div class="event-shock">
                JCS ${e.shock_result.jcs_before.toFixed(0)} → ${e.shock_result.jcs_after.toFixed(0)}
                ${(e.shock_result.impact || []).slice(0, 2).map(i => `<span class="event-impact-chip">${i}</span>`).join('')}
               </div>`
            : '';
        return `
        <div class="event-card" style="border-left: 2px solid ${color}">
            <div class="event-card-header">
                <span class="event-icon">${e.icon}</span>
                <span class="event-title">${e.title}</span>
                <span class="event-severity" style="color:${color};border-color:${color}30">${sevLabels[e.severity] || e.severity}</span>
                <span class="event-time">${(e.detected_at || '').replace('T', ' ').slice(0, 16)}</span>
            </div>
            <div class="event-detail">${e.detail}</div>
            ${shockInfo}
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════
//  V22.0: 合规检查徽章
// ═══════════════════════════════════════════════════

function renderComplianceBadge(compliance) {
    const badge = document.getElementById('compliance-badge');
    if (!badge || !compliance) return;

    badge.style.display = '';
    const status = compliance.status;
    if (status === 'passed') {
        badge.className = 'compliance-badge passed';
        badge.textContent = '🟢 合规';
        badge.title = compliance.summary || '全部规则通过';
    } else if (status === 'blocked') {
        badge.className = 'compliance-badge blocked';
        badge.textContent = '🛑 阻断';
        badge.title = (compliance.blocks || []).map(b => b.rule_name).join('; ');
    } else if (status === 'warning') {
        badge.className = 'compliance-badge warning';
        badge.textContent = '⚠️ 警告';
        badge.title = compliance.summary || '';
    } else {
        badge.textContent = '--';
    }

    // 如果有阻断, 添加视觉阻断标记 (保持可读性)
    const actionEl = document.getElementById('action-inline');
    if (actionEl) {
        if (status === 'blocked') {
            actionEl.classList.add('compliance-blocked');
        } else {
            actionEl.classList.remove('compliance-blocked');
            actionEl.style.opacity = '';  // 清除旧版遗留
        }
    }
}

// ═══════════════════════════════════════════════════
//  V22.0: 参数敏感度分析 (CI/CD 质量门)
// ═══════════════════════════════════════════════════

async function runSensitivityAnalysis() {
    const result = document.getElementById('pc-result');
    if (!result) return;

    result.innerHTML = '<div style="text-align:center;padding:20px;color:#94a3b8;">⏳ 敏感度分析中 (±5% 扰动)...</div>';

    try {
        const resp = await fetch(`${API_BASE}/param-sensitivity`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderSensitivity(data);
        } else {
            result.innerHTML = `<div style="text-align:center;padding:20px;color:#f87171;">⚠️ ${data.error || '分析失败'}</div>`;
        }
    } catch (e) {
        result.innerHTML = '<div style="text-align:center;padding:20px;color:#f87171;">⚠️ 网络异常</div>';
    }
}

function renderSensitivity(data) {
    const result = document.getElementById('pc-result');
    if (!result) return;

    const overallColors = { robust: '#34d399', sensitive: '#fbbf24', fragile: '#f87171' };
    const overallIcons = { robust: '🟢', sensitive: '🟡', fragile: '🔴' };
    const sensColors = { high: '#f87171', medium: '#fbbf24', low: '#34d399' };
    const sensLabels = { high: '高', medium: '中', low: '低' };

    const maxDelta = Math.max(...data.results.map(r => r.max_jcs_delta), 1);

    result.innerHTML = `
    <div class="ps-overall" style="color:${overallColors[data.overall] || '#64748b'}">
        ${overallIcons[data.overall] || ''} ${data.overall_label}
        <span class="ps-baseline">基线 JCS: ${data.baseline_jcs} · 仓位: ${data.baseline_position}%</span>
    </div>
    <div class="ps-bars">
        ${data.results.slice(0, 8).map(r => {
            const barPct = Math.min(100, (r.max_jcs_delta / maxDelta) * 100);
            const color = sensColors[r.sensitivity] || '#64748b';
            return `
            <div class="ps-bar-row">
                <span class="ps-bar-label">${r.param_label}</span>
                <div class="ps-bar-track">
                    <div class="ps-bar-fill" style="width:${barPct}%;background:${color}"></div>
                </div>
                <span class="ps-bar-delta" style="color:${color}">±${r.max_jcs_delta}</span>
                <span class="ps-bar-sens" style="color:${color}">${sensLabels[r.sensitivity]}</span>
            </div>`;
        }).join('')}
    </div>
    <div class="ps-footnote">🔬 ±${data.perturbation_pct}% 参数扰动下 JCS 变动幅度 · 敏感度越高 → 策略越脆弱</div>`;
}

// ═══════════════════════════════════════════════════
//  P2-C: NLP 情报中心
// ═══════════════════════════════════════════════════

async function loadIntelligence() {
    try {
        const resp = await fetch(`${API_BASE.replace('/decision', '/intelligence')}/latest`);
        const data = await resp.json();
        if (data.status === 'success' && data.data) {
            renderIntelEvents(data.data);
        }
    } catch (e) {
        console.warn('Intelligence load:', e);
    }
}

async function triggerIntelScan() {
    const btn = document.getElementById('btn-intel-scan');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '⏳ 扫描中...';

    try {
        const headers = { 'Content-Type': 'application/json' };
        const apiKey = localStorage.getItem('alphacore_api_key');
        if (apiKey) headers['X-API-Key'] = apiKey;

        const resp = await fetch(`${API_BASE.replace('/decision', '/intelligence')}/scan`, {
            method: 'POST', headers
        });
        const data = await resp.json();

        if (data.status === 'success' && data.data) {
            renderIntelEvents(data.data);
            btn.textContent = `✅ ${data.data.events_count || 0} 条事件`;
        } else {
            btn.textContent = '⚠️ ' + (data.message || '扫描失败');
        }
    } catch (e) {
        btn.textContent = '❌ 网络异常';
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = '🔍 手动扫描';
        }, 3000);
    }
}

function renderIntelEvents(intel) {
    const list = document.getElementById('intel-events-list');
    const timeEl = document.getElementById('intel-scan-time');
    const summary = document.getElementById('intel-summary');
    if (!list) return;

    if (timeEl && intel.scan_time) {
        const t = intel.scan_time.replace('T', ' ').slice(0, 16);
        timeEl.textContent = `最近扫描: ${t}`;
    }

    const events = intel.events || [];
    if (events.length === 0) {
        list.innerHTML = '<div class="intel-empty">暂无情报 · 等待定时扫描或点击手动扫描</div>';
        return;
    }

    // 更新折叠态摘要
    if (summary) {
        summary.textContent = `${events.length} 条情报 · 最高影响 ${Math.max(...events.map(e => e.impact_score || 0)).toFixed(0)}/10`;
    }

    const catIcons = { macro: '🌐', industry: '🏭', stock: '📈', risk: '🚨' };
    const catLabels = { macro: '宏观', industry: '行业', stock: '个股', risk: '风险' };

    list.innerHTML = events.slice(0, 8).map(e => {
        const impact = e.impact_score || 0;
        const impactColor = impact >= 7 ? '#ef4444' : (impact >= 4 ? '#f97316' : '#64748b');
        const scenarioTag = e.scenario_id
            ? `<span class="intel-scenario-tag">🔮 ${e.scenario_id}</span>`
            : '';
        const assets = Array.isArray(e.affected_assets) && e.affected_assets.length
            ? `<span class="intel-assets">${e.affected_assets.slice(0, 3).join(' · ')}</span>`
            : '';

        return `
        <div class="intel-event-card">
            <div class="intel-event-header">
                <span class="intel-cat-icon">${catIcons[e.category] || '📋'}</span>
                <span class="intel-event-title">${e.title}</span>
                <span class="intel-cat-badge">${catLabels[e.category] || e.category}</span>
                <span class="intel-impact-badge" style="color:${impactColor};border-color:${impactColor}40">${impact.toFixed(0)}/10</span>
            </div>
            <div class="intel-event-body">
                <span class="intel-summary-text">${e.summary || ''}</span>
                ${scenarioTag}${assets}
            </div>
        </div>`;
    }).join('');
}
