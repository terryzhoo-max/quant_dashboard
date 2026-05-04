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
//  页面初始化 (主调度器)
// ═══════════════════════════════════════════════════

async function initDecisionHub() {
    _riskMatrixCache = null;  // V20.0: 刷新时清除缓存
    initTabs();
    initSOPToggle();  // V19.3: SOP 折叠事件委托

    try {
        // V19.3: 异步独立请求 + 超时降级
        _fetchWithDegradation('swing-guard-grid', fetchSwingGuard, '波段守卫');
        _fetchWithDegradation('risk-guardrail', loadRiskGuardrail, '风控护栏');

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

            // ④ 方向指示器
            renderDirections(data.jcs.directions, data.snapshot);

            // ⑤ 矛盾检测
            renderConflicts(data.conflicts);

            // ⑥ 执行指令
            if (data.action_plan) renderActionPlan(data.action_plan);

            // ⑦ 信号阈值速查表
            if (data.snapshot) highlightThresholdTable(data.snapshot);

            // ⑧ 全球市场温度仪表板
            if (data.global_temperature) renderGlobalTemperature(data.global_temperature);

            // ⑨ 情景模拟器
            renderScenarioCards(data.scenarios);
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
