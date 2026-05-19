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

function showFallbackData() {
    const fallbackData = {
        macro_cards: {
            vix: { 
                value: 20.15, trend: "+5.2%", status: "up", 
                regime: "🟡 正常震荡", class: "vix-status-norm",
                desc: "市场常态，结构性调仓", percentile: 15.2
            },
            tomorrow_plan: {
                primary_regime: {
                    tier: 3, emoji: "🟡", cn: "中性均衡",
                    aiae_v1: 22.3, cap: 65, cap_range: "50-65%",
                    action: "均衡持有", action_detail: "有纪律地持有，到了就卖",
                },
                validators: {
                    erp: { value: 5.22, label: "偏低估", erp_tier: "bull", confirms: true },
                    vix: { value: 20.15, label: "🟡 正常震荡", risk_override: false, multiplier: 1.0 },
                },
                regime_matrix: [
                    { tier: 1, emoji: "🟢", cn: "极度恐慌", range: "<12%", cap_range: "90-95%", action: "满配进攻 · 越跌越买", vix_cross: "VIX>30时分批介入", active: false },
                    { tier: 2, emoji: "🔵", cn: "低配置区", range: "12-16%", cap_range: "70-85%", action: "标准建仓 · 不因波动减仓", vix_cross: "VIX<20加速建仓", active: false },
                    { tier: 3, emoji: "🟡", cn: "中性均衡", range: "16-24%", cap_range: "50-65%", action: "均衡持有 · 到了就卖", vix_cross: "VIX>30启动减仓", active: true },
                    { tier: 4, emoji: "🟠", cn: "偏热区域", range: "24-32%", cap_range: "25-40%", action: "系统减仓 · 每周减5%", vix_cross: "VIX<15警惕拥挤", active: false },
                    { tier: 5, emoji: "🔴", cn: "极度过热", range: ">32%", cap_range: "0-15%", action: "清仓防守 · 3天内完成", vix_cross: "任何VIX都清仓", active: false },
                ],
                directives: [
                    { priority: "primary", icon: "🎯", text: "AIAE 🟡 中性均衡 Cap65% → 均衡持有", color: "#eab308" },
                    { priority: "confirm", icon: "✅", text: "ERP 5.22% 偏低估 → 验证主轴方向", color: "#10b981" },
                    { priority: "risk", icon: "🛡️", text: "VIX 20.15 正常 → 风控不触发", color: "#94a3b8" },
                ],
                scenarios: [
                    { condition: "AIAE上行至Ⅳ级", action: "启动系统减仓至40%以下", type: "aiae_upgrade" },
                    { condition: "VIX突破30+", action: "风控降级Cap×0.75 + 增配红利", type: "vix_alert" },
                    { condition: "ERP跌破3%", action: "估值吸引力下降·降低进攻权重", type: "erp_shift" },
                ],
                risk_panel: {
                    margin_heat: { value: 2.1, threshold: 3.5, status: "safe" },
                    slope: { value: 0.3, threshold: 1.5, status: "safe", direction: "rising" },
                    fund_position: { value: 82.0, threshold: 90, status: "safe" },
                    overall_risk: "low",
                },
                framework: ["🎯 AIAE 🟡 中性均衡 Cap65% → 均衡持有", "✅ ERP 5.22% 偏低估 → 验证主轴方向", "🛡️ VIX 20.15 正常 → 风控不触发"],
                current_tactics: { regime: "🟡 Ⅲ级 中性均衡" },
            },
            capital_a: { value: "A: 151.4 亿", trend: "外资稳步买入", status: "up", z_score: 0.85, raw_5d: 151.4, resonance: "双多共振", resonance_status: "bull", z_composite: 1.65 },
            capital_h: { value: "H: 20.5 亿", trend: "南向博弈均衡", status: "neutral", z_score: 0.32, raw_5d: 20.5 },
            signal: {
                strategies: [
                    { key: "mr",   icon: "📐", name: "均值回归", signal: "2买/3卖",  metric: "偏离8只",   direction: "mixed" },
                    { key: "mom",  icon: "🚀", name: "动量轮动", signal: "AI领涨",   metric: "动量5.2%",  direction: "up" },
                    { key: "div",  icon: "🛡️", name: "红利防线", signal: "5/8趋势",  metric: "买入2只",   direction: "up" },
                    { key: "erp",  icon: "🌐", name: "ERP择时",  signal: "极度低估",  metric: "3.50%",    direction: "up" },
                    { key: "aiae", icon: "🌡️", name: "AIAE管控", signal: "中性均衡",  metric: "Cap65%",   direction: "neutral" },
                ],
                consensus: "3/5 看多",
                consensus_label: "偏多共振",
                status: "up",
                value: "MR 2买/3卖 · ERP 极度低估",
                trend: "DT 5/8趋 · AIAE 中性均衡 · MOM AI领涨"
            },
            erp: { value: "5.2%", trend: "估值中性", status: "neutral", desc: "偏低估 · 4Y分位10.8%", erp_pct: 10.8, signal_label: "标配持有" },
            regime_banner: { regime: "🟠 震荡偏多", temp: 52.3, advice: "🟡 中性均衡 (Cap 65%)", vix: 20.15, vix_label: "🟡 正常震荡", z_capital: 0.8, aiae_regime: 3, aiae_regime_cn: "中性均衡", aiae_cap: 65, aiae_v1: 22.3 },
            aiae_thermometer: { aiae_v1: 22.3, regime: 3, regime_cn: "中性均衡", regime_emoji: "🟡", regime_color: "#eab308", regime_name: "Regime III", cap: 65, slope: 0.3, slope_direction: "rising", margin_heat: 2.1, fund_position: 82.5, aiae_simple: 19.8, erp_value: 3.5, status: "fallback" },
            market_temp: {
                value: 52.3, label: "温暖 | 极度低估", advice: "🟡 中性均衡 (Cap 65%)",
                regime_name: "平衡模式", mindset: "⚖️ 仓位中型，等待分歧",
                market_vix_multiplier: 1.0, erp_z: 1.8, z_capital: 0.8,
                hub_confidence: 72,
                hub_composite: 62.5,
                hub_factors: {
                    aiae_regime:  { score: 55, weight: 0.40, label: "中性均衡" },
                    erp_value:    { score: 85, weight: 0.25, label: "极度低估" },
                    vix_fear:     { score: 78, weight: 0.15, label: "恐慌低位" },
                    capital_flow: { score: 63, weight: 0.10, label: "资金中性" },
                    macro_temp:   { score: 48, weight: 0.10, label: "宏观中性" },
                    aiae_temp:    { score: 55, weight: 0.15, label: "中性均衡" }
                },
                regime_weights: { div: 0.30, mr: 0.24, mom: 0.18, erp: 0.11, aiae_etf: 0.18 },
                strategy_positions: { div_pos: 18.5, mr_pos: 14.5, mom_pos: 11.0, erp_pos: 6.6, aiae_pos: 11.0, total: 61.6 },
                strategy_filters: { div: "正常", mr: "正常", mom: "正常" }
            }
        },
        sector_heatmap: [
            { name: "医药生物", change:  1.60, trend_5d:  0.8, rps: 91 },
            { name: "银行/金融", change: -0.99, trend_5d:  0.3, rps: 100 },
            { name: "酒/自选消费", change: -1.00, trend_5d:  0.2, rps: 75 },
            { name: "上证180/主板", change: -0.87, trend_5d: -0.6, rps: 58 },
            { name: "有色金属", change: -1.00, trend_5d: -1.8, rps: 25 },
            { name: "证券/非银", change: -0.88, trend_5d: -2.0, rps: 41 },
            { name: "计算机/AI", change: -0.44, trend_5d: -2.3, rps: 33 },
            { name: "中证传媒", change: -1.15, trend_5d: -2.9, rps: 50 },
            { name: "军工龙头", change: -1.17, trend_5d: -3.0, rps: 16 },
            { name: "半导体/芯片", change: -0.26, trend_5d: -3.6, rps: 8 },
            { name: "创业板/成长", change: -0.73, trend_5d: -3.8, rps: 83 },
            { name: "新能源车", change: -2.07, trend_5d: -5.7, rps: 66 }
        ],
        execution_lists: {
            buy_zone: [
                { name: "某AI行业龙头", code: "60XXXX.SH", pe: 15.2, score: 82.5, badge: "核心资产", badgeClass: "buy" },
                { name: "车规半导体标的", code: "00XXXX.SZ", pe: 22.1, score: 71.4, badge: "性价比较高", badgeClass: "buy" }
            ],
            danger_zone: [
                { name: "业绩衰退标的", code: "30XXXX.SZ", pe: 120.5, score: 18.2, badge: "严重泡沫", badgeClass: "sell" },
                { name: "高杠杆爆雷风险", code: "60XXXX.SH", metric: "彻底破位", score: 12.5, badge: "财务预警", badgeClass: "sell" }
            ]
        },
        strategy_status: {
            mr: { status_text: "发现极值猎物", status_class: "active", metric1: "54只", metric2: "全仓 80%" },
            mom: { status_text: "动能衰竭", status_class: "warning", metric1: "红利低波", metric2: "拥挤度 92%" },
            div: { status_text: "稳定防御", status_class: "dormant", metric1: "4.82%", metric2: "62%" },
            erp: { status_text: "ERP 极度低估", status_class: "active", metric1: "ERP 3.5%", metric2: "Z: +1.8" },
            aiae: { status_text: "🟡 中性均衡", status_class: "dormant", metric1: "AIAE 22.3%", metric2: "Cap 65%" }
        }
    };
    updateDashboard(fallbackData);
}

