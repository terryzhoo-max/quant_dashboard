// ══════════════════════════════════════════
// AlphaCore · UI Utilities (O3 模块化拆分)
// 通用 DOM 工具、动画、Toast、策略卡片更新
// ══════════════════════════════════════════

// 移除过期 Chart.js 实例
// 后端 API 地址
const API_URL = '/api/v1/dashboard-data';

// 全局 DOM 查询工具 (消除各渲染函数重复声明)
const el = (id) => document.getElementById(id);

// 格式化函数
const formatTrend = (change, isInverse = false) => {
    // 对于某些指标（如资金流入），下跌可能判定为 down。对于 VIX，上涨代表恐慌。
    const sign = change > 0 ? '+' : '';
    const arrow = change > 0 ? '▲' : '▼';
    return `${arrow} ${sign}${change}%`;
};

// ====== UI/UX 平滑动画库 ======
function animateValueWithHTML(elementId, targetValueStr, trendHtml, duration = 800) {
    const obj = document.getElementById(elementId);
    if (!obj) return;
    
    const targetNum = parseFloat(targetValueStr);
    if (isNaN(targetNum)) {
        obj.innerHTML = `${targetValueStr} ${trendHtml}`;
        return;
    }
    
    const currentText = obj.childNodes[0] ? obj.childNodes[0].textContent.trim() : "0";
    const startNum = parseFloat(currentText) || 0;
    
    if (startNum === targetNum) {
        obj.innerHTML = `${targetValueStr} ${trendHtml}`;
        return;
    }
    
    let startTimestamp = null;
    const isInt = String(targetValueStr).indexOf('.') === -1;
    const decimals = isInt ? 0 : String(targetValueStr).split('.')[1].length;
    
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 4); // easeOutQuart
        const current = startNum + (targetNum - startNum) * ease;
        
        obj.innerHTML = `${current.toFixed(decimals)} ${trendHtml}`;
        if (progress < 1) {
            window.requestAnimationFrame(step);
        } else {
            obj.innerHTML = `${targetValueStr} ${trendHtml}`;
        }
    };
    window.requestAnimationFrame(step);
}

const updateCardUI = (cardId, valId, trendId, dataItem) => {
    if (!dataItem) return;
    
    const valEl = document.getElementById(valId);
    if (!valEl) {
        console.warn(`[UI] Element not found: ${valId}`);
        return;
    }
    
    const trendHtml = `<span class="trend" id="${trendId}">${dataItem.trend}</span>`;
    animateValueWithHTML(valId, dataItem.value, trendHtml);
    
    // Dynamically set highlight color based on status (up = green, down = red, neutral = gray etc)
    const cardEl = cardId ? document.getElementById(cardId) : null;
    if (dataItem.status === 'up') {
        valEl.classList.remove('highlight-down', 'highlight-neutral');
        valEl.classList.add('stat-value', 'highlight-up');
        if (cardEl) cardEl.classList.add('active-glow');
    } else if (dataItem.status === 'down') {
        valEl.classList.remove('highlight-up', 'highlight-neutral');
        valEl.classList.add('stat-value', 'highlight-down');
        if (cardEl) cardEl.classList.remove('active-glow');
    } else {
        valEl.classList.remove('highlight-up', 'highlight-down');
        valEl.classList.add('stat-value', 'highlight-neutral');
        if (cardEl) cardEl.classList.remove('active-glow');
    }
};

let _pollingTimer = null;
let _isWarmingUp = false;

/** V14.0 UI/UX: 现代 Toast 通知系统 (替换过时的 _showBanner) */
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = message;
    
    container.appendChild(toast);
    
    // 强制重绘以触发动画
    toast.offsetHeight;
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400); // 等待 CSS 过渡结束
    }, 4000);
}

// 废弃的横幅函数作为空壳保留，防止其他旧代码报错
function _showBanner() {}
function _removeBanner() {}
function _removeOfflineBanner() {}

function updateStrategyCard(prefix, data) {
    if (!data) return;
    
    // V5.0: 状态行（状态指示灯 + 状态文本）
    const statusRow = document.getElementById(`strat-status-row-${prefix}`);
    const statusText = document.getElementById(`strat-status-${prefix}`);
    if (statusText) statusText.innerText = data.status_text;
    if (statusRow) {
        const dotEl = statusRow.querySelector('.strat-dot');
        if (dotEl) dotEl.className = `strat-dot ${data.status_class}`;
        statusRow.className = `strat-status-row ${data.status_class}`;
    }
    
    const metric1El = document.getElementById(`strat-metric1-${prefix}`);
    if (metric1El) metric1El.innerText = data.metric1;
    
    const metric2El = document.getElementById(`strat-metric2-${prefix}`);
    if (metric2El) metric2El.innerText = data.metric2;
}

function showFallbackData(reason = "DASHBOARD_DATA_UNAVAILABLE") {
    const lockedMessage = reason === "DASHBOARD_WARMING_UP"
        ? "后台引擎预热中，停止生成交易指令"
        : "无法验证后端数据，停止生成交易指令";
    const unavailableCard = {
        available: false,
        value: "--",
        trend: "不可用",
        status: "unavailable",
    };
    const unavailableStrategy = {
        status_text: "数据不可用",
        status_class: "dormant",
        metric1: "--",
        metric2: "--",
    };
    const unavailableData = {
        _meta_unavailable: true,
        _meta_is_fallback: true,
        _meta_is_stale: true,
        unavailable_reason: reason,
        decision_locked: true,
        timestamp: new Date().toISOString(),
        degraded_modules: ["dashboard"],
        macro_cards: {
            vix: { ...unavailableCard, regime: "🔒 数据不可用", class: "vix-status-alert", desc: "未取得可验证的 VIX 数据", percentile: null },
            erp: { ...unavailableCard, desc: "数据不可用", erp_pct: null, signal_label: "决策锁定" },
            capital_a: { ...unavailableCard, resonance: "数据不可用", resonance_status: "neutral" },
            capital_h: { ...unavailableCard },
            signal: { available: false, strategies: [], consensus: "--", consensus_label: "决策锁定", status: "unavailable", trend: lockedMessage },
            regime_banner: {
                available: false,
                regime: "🔒 数据不可用",
                temp: "--",
                advice: "执行仓位 0% · 禁止形成交易决策",
                vix: "--",
                vix_label: "",
                z_capital: "--",
                aiae_regime: 0,
                aiae_regime_cn: "不可用",
                aiae_cap: "--",
            },
            aiae_thermometer: { available: false, decision_locked: true, status: "unavailable" },
            market_temp: { available: false, decision_locked: true, unavailable_reason: reason },
            tomorrow_plan: { mode: "locked", decision_locked: true, lock_reason: "unverifiable", lock_message: lockedMessage },
        },
        sector_heatmap: [],
        execution_lists: { buy_zone: [], danger_zone: [] },
        strategy_status: {
            mr: { ...unavailableStrategy },
            mom: { ...unavailableStrategy },
            div: { ...unavailableStrategy },
            erp: { ...unavailableStrategy },
            aiae: { ...unavailableStrategy },
        },
    };
    updateDashboard(unavailableData);
}

