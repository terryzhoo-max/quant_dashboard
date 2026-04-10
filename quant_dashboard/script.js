// 移除过期 Chart.js 实例
// 后端 API 地址
const API_URL = '/api/v1/dashboard-data';

// 格式化函数
const formatTrend = (change, isInverse = false) => {
    // 对于某些指标（如资金流入），下跌可能判定为 down。对于 VIX，上涨代表恐慌。
    const sign = change > 0 ? '+' : '';
    const arrow = change > 0 ? '▲' : '▼';
    return `${arrow} ${sign}${change}%`;
};

const updateCardUI = (cardId, valId, trendId, dataItem) => {
    if (!dataItem) return;
    
    const valEl = document.getElementById(valId);
    if (!valEl) {
        console.warn(`[UI] Element not found: ${valId}`);
        return;
    }
    
    // Update HTML layout based on the design plan
    valEl.innerHTML = `
        ${dataItem.value} 
        <span class="trend" id="${trendId}">${dataItem.trend}</span>
    `;
    
    // Dynamically set highlight color based on status (up = green, down = red, neutral = gray etc)
    const cardEl = cardId ? document.getElementById(cardId) : null;
    if (dataItem.status === 'up') {
        valEl.className = 'stat-value highlight-up';
        if (cardEl) cardEl.classList.add('active-glow');
    } else if (dataItem.status === 'down') {
        valEl.className = 'stat-value highlight-down';
        if (cardEl) cardEl.classList.remove('active-glow');
    } else {
        valEl.className = 'stat-value highlight-neutral';
        if (cardEl) cardEl.classList.remove('active-glow');
    }
};

// 核心拉取数据的逻辑
async function fetchQuantData() {
    try {
        const response = await fetch(API_URL);
        if (!response.ok) {
            throw new Error(`HTTP 异常: ${response.status}`);
        }
        const result = await response.json();
        
        if (result.status === 'success') {
            updateDashboard(result.data);
            
            // 更新最后拉取时间
            const date = new Date(result.timestamp);
            document.getElementById('system-time').innerText = 
                `${date.toLocaleDateString()} ${date.toLocaleTimeString()} · 已连接 AlphaCore API · 数据实时同步中`;
        } else {
            console.error("后端返回错误:", result.message);
            document.getElementById('system-time').innerText = `API 错误: ${result.message}`;
        }
    } catch (error) {
        console.warn("未能连接到本地 FastAPI 后端，展示模拟本地挂载数据...", error);
        document.getElementById('system-time').innerText = "提示：未检测到后端服务运行，当前展示本地缓存推演数据。请按指引启动 main.py";
        // 如果后端没开，使用备用数据平滑过渡
        showFallbackData();
    }
}

// 动态将数据注入到图表和 DOM
function updateDashboard(marketData) {
    if (marketData.macro_cards) {
        // 1. 更新顶部卡片数值
        if (marketData.macro_cards.vix) {
            updateCardUI('card-vix', 'val-vix', 'trend-vix', marketData.macro_cards.vix);
            // V4.2 新增: VIX 风格描述与分位条
            const vix = marketData.macro_cards.vix;
            const vixRegimeEl = document.getElementById('val-vix-regime');
            if (vixRegimeEl && vix.regime) {
                vixRegimeEl.innerText = vix.regime;
                vixRegimeEl.className = `vix-regime-box ${vix.class}`;
            }
            if (document.getElementById('desc-vix')) document.getElementById('desc-vix').innerText = vix.desc || "接入实时全球避险情绪水温";
            if (document.getElementById('val-vix-percentile')) document.getElementById('val-vix-percentile').innerText = `Range: ${vix.percentile}%`;
            const vixBar = document.getElementById('bar-vix-range');
            if (vixBar) vixBar.style.width = `${vix.percentile}%`;
        }
        updateCardUI('card-erp', 'val-erp', 'trend-erp', marketData.macro_cards.erp);
        
        // A+H 跨境流量独立渲染
        if (marketData.macro_cards.capital_a) {
            updateCardUI(null, 'val-capital-a', 'trend-capital-a', marketData.macro_cards.capital_a);
        }
        if (marketData.macro_cards.capital_h) {
            updateCardUI(null, 'val-capital-h', 'trend-capital-h', marketData.macro_cards.capital_h);
        }
        
        // 如果 A+H 有一侧正在强力流入，点亮整个卡片背景
        const cardCapital = document.getElementById('card-capital');
        if (cardCapital) {
            const isUp = (marketData.macro_cards.capital_a && marketData.macro_cards.capital_a.status === 'up') ||
                         (marketData.macro_cards.capital_h && marketData.macro_cards.capital_h.status === 'up');
            if (isUp) cardCapital.classList.add('active-glow');
            else cardCapital.classList.remove('active-glow');
        }

        updateCardUI('card-signal', 'val-signal', 'trend-signal', marketData.macro_cards.signal);

        // V5.0: 全局 Regime 状态横幅
        if (marketData.macro_cards.regime_banner) {
            const rb = marketData.macro_cards.regime_banner;
            const banner = document.getElementById('regime-banner');
            const dot = document.getElementById('rb-dot');
            const regimeEl = document.getElementById('rb-regime');
            const tempEl = document.getElementById('rb-temp');
            const adviceEl = document.getElementById('rb-advice');
            const vixEl = document.getElementById('rb-vix');
            const capEl = document.getElementById('rb-capital');
            
            if (regimeEl) regimeEl.innerText = rb.regime || '—';
            if (tempEl) tempEl.innerText = `${rb.temp}°`;
            if (adviceEl) adviceEl.innerText = rb.advice || '—';
            if (vixEl) vixEl.innerText = `VIX ${rb.vix} ${rb.vix_label || ''}`;
            if (capEl) capEl.innerText = `资金 Z:${rb.z_capital > 0 ? '+' : ''}${rb.z_capital}`;
            
            // 状态颜色
            if (banner && dot) {
                let colorClass = 'rb-neutral';
                if (rb.temp > 65) colorClass = 'rb-bull';
                else if (rb.temp < 35) colorClass = 'rb-bear';
                banner.className = `regime-banner glass-panel ${colorClass}`;
                dot.className = `rb-dot ${colorClass}`;
            }
            
            // V7.0: AIAE 状态标签
            const aiaeEl = document.getElementById('rb-aiae');
            if (aiaeEl && rb.aiae_regime_cn) {
                aiaeEl.innerText = `🌡️ AIAE ${rb.aiae_regime_cn} Cap${rb.aiae_cap}%`;
                const ar = rb.aiae_regime || 3;
                aiaeEl.style.borderColor = ar <= 2 ? 'rgba(16,185,129,0.5)' : ar >= 4 ? 'rgba(239,68,68,0.5)' : 'rgba(245,158,11,0.5)';
            }
        }
    }
    
    // 3.5 AIAE 温度计渲染
    if (marketData.macro_cards && marketData.macro_cards.aiae_thermometer) {
        renderAIAEThermometer(marketData.macro_cards.aiae_thermometer);
    }

    // 4. V6.0 情绪与持仓枢纽渲染 (Sentiment & Position Hub)
    if (marketData.macro_cards && marketData.macro_cards.market_temp) {
        renderPositionHub(marketData.macro_cards.market_temp);
    }

    // 4.5 更新明日实战决策矩阵 (V4.4)
    if (marketData.macro_cards && marketData.macro_cards.tomorrow_plan) {
        const plan = marketData.macro_cards.tomorrow_plan;
        
        // 更新视角切换：Regime Badge
        const badgeEl = document.getElementById('tag-current-regime');
        if (badgeEl && plan.current_tactics) {
            badgeEl.innerText = `实时状态: ${plan.current_tactics.regime}`;
        }

        // 渲染 4 阶战术矩阵
        const matrixEl = document.getElementById('matrix-content');
        if (matrixEl && plan.regime_matrix) {
            matrixEl.innerHTML = plan.regime_matrix.map(m => `
                <div class="matrix-row ${m.active ? 'active' : ''}">
                    <div class="col-regime">${m.regime}</div>
                    <div class="col-tactics">${m.tactics}</div>
                    <div class="col-pos">${m.pos}</div>
                </div>
            `).join('');
        }
        
        // 渲染核心建议 (标记 Priority)
        const frameworkEl = document.getElementById('list-plan-framework');
        if (frameworkEl && plan.framework) {
            frameworkEl.innerHTML = plan.framework.map(f => {
                const isHighlight = f.includes('优先') || f.includes('核心');
                const style = isHighlight ? 'color: #f59e0b; font-weight: 600' : '';
                return `<li style="${style}">${f}</li>`;
            }).join('');
        }

        // 渲染情景模拟标签
        const scenarioEl = document.getElementById('list-plan-scenarios');
        if (scenarioEl && plan.scenarios) {
            scenarioEl.innerHTML = plan.scenarios.map(s => 
                `<div class="scenario-tag">${s.case}: ${s.action}</div>`
            ).join('');
        }
    }


    // 5. 更新行业热力图 (Sector Heatmap)
    if (marketData.sector_heatmap) {
        renderHeatmap('heatmap-grid', marketData.sector_heatmap);
    }
    
    // 6. 更新个股列表
    if (marketData.execution_lists) {
        renderExecutionLists(document.getElementById('list-buy-zone'), marketData.execution_lists.buy_zone);
        renderExecutionLists(document.getElementById('list-danger-zone'), marketData.execution_lists.danger_zone);
    }
    
    // 2. 更新策略监控卡片 (5策略)
    if (marketData.strategy_status) {
        updateStrategyCard('mr', marketData.strategy_status.mr);
        updateStrategyCard('mom', marketData.strategy_status.mom);
        updateStrategyCard('div', marketData.strategy_status.div);
        updateStrategyCard('erp', marketData.strategy_status.erp);
        updateStrategyCard('aiae', marketData.strategy_status.aiae);
    }
}

function renderExecutionLists(listContainer, listData) {
    if (!listContainer || !listData) return;
    
    listContainer.innerHTML = ''; // Clear processing text
    
    if (listData.length === 0) {
        listContainer.innerHTML = `<li><div style="color: #64748b; padding: 10px;">当前无符合条件标的</div></li>`;
        return;
    }
    
    listData.forEach(item => {
        const li = document.createElement('li');
        // 根据评分和买卖逻辑确定分数颜色
        let scoreClass = '';
        if (item.badgeClass === 'buy') {
            if (item.score >= 75) scoreClass = 'score-high';
            else if (item.score >= 60) scoreClass = 'score-mid';
            else scoreClass = 'score-low';
        } else { // danger_zone or sell
            if (item.score <= 30) scoreClass = 'score-danger';
            else scoreClass = 'score-low';
        }
            
        li.innerHTML = `
            <div class="stock-info">
                <span class="stock-name">${item.name}</span>
                <span class="stock-code">${item.code}</span>
            </div>
            <div class="stock-metrics">
                <div class="score-pill ${scoreClass}">评分: ${item.score || '--'}</div>
                <div class="metric-row">
                    <span class="metric">${item.metric || 'PE: ' + item.pe + 'x'}</span>
                    <span class="badge ${item.badgeClass}">${item.badge}</span>
                </div>
            </div>
        `;
        listContainer.appendChild(li);
    });
}

/**
 * V6.0 情绪与持仓枢纽渲染引擎
 */
function renderPositionHub(temp) {
    const vixMult = temp.market_vix_multiplier || 1.0;
    const hubEl = document.getElementById('card-sentiment-hub');
    
    // === 左栏: 宏观温度计 ===
    const el = (id) => document.getElementById(id);
    
    // 温度大字
    if (el('val-market-temp')) el('val-market-temp').innerText = `${temp.value}°`;
    
    // Regime 标签
    if (el('val-regime-name')) el('val-regime-name').innerText = temp.regime_name || "模式识别中";
    
    // 风险标签 (VIX 修正显示)
    const riskLabel = el('label-market-temp');
    if (riskLabel) {
        const isVixHedged = vixMult < 0.9;
        riskLabel.innerText = isVixHedged ? `${temp.label} (VIX 避险修正)` : temp.label;
        riskLabel.style.color = isVixHedged ? "#ef4444" : (temp.value > 65 ? "#ef4444" : (temp.value < 35 ? "#06b6d4" : "#f59e0b"));
    }
    
    // 心态指引
    if (el('val-mindset')) el('val-mindset').innerText = temp.mindset || "侦测中...";
    
    // 温度颜色区域 (CSS data attribute 切换)
    if (hubEl) {
        let zone = 'warm';
        if (temp.value < 35) zone = 'cold';
        else if (temp.value > 65) zone = 'hot';
        hubEl.setAttribute('data-temp-zone', zone);
    }
    
    // 温度环形仪表角度 (0-100 → 0-360deg)
    const gaugeRing = el('gauge-ring');
    if (gaugeRing) {
        const deg = Math.round((temp.value / 100) * 360);
        gaugeRing.style.setProperty('--temp-deg', deg);
    }
    
    // 宏观微标签: 资金Z + ERP
    if (el('val-capital-z') && temp.z_capital !== undefined) {
        const zVal = temp.z_capital;
        el('val-capital-z').innerText = `${zVal > 0 ? '+' : ''}${zVal.toFixed(2)}`;
        el('val-capital-z').style.color = zVal > 0.5 ? '#10b981' : (zVal < -0.5 ? '#ef4444' : '#f59e0b');
    }
    if (el('val-erp-tag') && temp.hub_factors && temp.hub_factors.erp_value) {
        el('val-erp-tag').innerText = temp.hub_factors.erp_value.label;
        const erpScore = temp.hub_factors.erp_value.score;
        el('val-erp-tag').style.color = erpScore >= 70 ? '#10b981' : (erpScore >= 40 ? '#f59e0b' : '#ef4444');
    }
    
    // === 中栏: 仓位决策面板 ===
    if (el('val-pos-advice')) el('val-pos-advice').innerText = temp.advice;
    
    // 仓位进度条
    const posMatch = temp.advice.match(/(\d+)%/);
    if (posMatch && el('bar-pos-advice')) {
        el('bar-pos-advice').style.width = `${posMatch[1]}%`;
    }
    
    // 置信度
    if (temp.hub_confidence !== undefined) {
        const conf = temp.hub_confidence;
        if (el('val-confidence')) el('val-confidence').innerText = conf;
        if (el('conf-fill')) el('conf-fill').style.width = `${conf}%`;
    }
    
    // 五因子条形图
    if (temp.hub_factors) {
        const factorMap = {
            'vix':     { barId: 'fbar-vix',     scoreId: 'fscore-vix',     data: temp.hub_factors.vix_fear },
            'capital': { barId: 'fbar-capital',  scoreId: 'fscore-capital', data: temp.hub_factors.capital_flow },
            'temp':    { barId: 'fbar-temp',     scoreId: 'fscore-temp',    data: temp.hub_factors.macro_temp },
            'erp':     { barId: 'fbar-erp',      scoreId: 'fscore-erp',     data: temp.hub_factors.erp_value },
            'signal':  { barId: 'fbar-signal',   scoreId: 'fscore-signal',  data: temp.hub_factors.signal_sync },
            'aiae':    { barId: 'fbar-aiae',     scoreId: 'fscore-aiae',    data: temp.hub_factors.aiae_temp }
        };
        
        for (const [key, cfg] of Object.entries(factorMap)) {
            if (!cfg.data) continue;
            const barEl = el(cfg.barId);
            const scoreEl = el(cfg.scoreId);
            
            if (barEl) {
                barEl.style.width = `${cfg.data.score}%`;
                // 颜色分级
                barEl.className = 'factor-bar';
                if (cfg.data.score >= 65) barEl.classList.add('score-high');
                else if (cfg.data.score >= 35) barEl.classList.add('score-mid');
                else barEl.classList.add('score-low');
            }
            if (scoreEl) {
                scoreEl.innerText = Math.round(cfg.data.score);
            }
        }
    }
    
    // === 右栏: 策略配仓 (合并自原配仓总览) ===
    // 策略权重条
    if (temp.regime_weights) {
        const rw = temp.regime_weights;
        // 策略卡片权重 pill 更新 (5策略)
        if (el('weight-mr'))  el('weight-mr').innerText  = `${(rw.mr * 100).toFixed(0)}%权重`;
        if (el('weight-mom')) el('weight-mom').innerText = `${(rw.mom * 100).toFixed(0)}%权重`;
        if (el('weight-div')) el('weight-div').innerText = `${(rw.div * 100).toFixed(0)}%权重`;
        if (el('weight-erp')) el('weight-erp').innerText = `${((rw.erp || 0) * 100).toFixed(0)}%权重`;
        if (el('weight-aiae')) el('weight-aiae').innerText = `${((rw.aiae_etf || 0) * 100).toFixed(0)}%权重`;
        
        // 堆叠条 (5策略)
        const updateBar = (id, key, label) => {
            const b = el(id);
            if (b) {
                b.style.width = `${((rw[key] || 0) * 100).toFixed(0)}%`;
                const span = b.querySelector('span');
                if (span) span.innerText = `${label} ${((rw[key] || 0) * 100).toFixed(0)}%`;
            }
        };
        updateBar('bar-div', 'div', '红利');
        updateBar('bar-mr',  'mr',  '均值');
        updateBar('bar-mom', 'mom', '动量');
        updateBar('bar-erp', 'erp', 'ERP');
        updateBar('bar-aiae', 'aiae_etf', 'AIAE');
    }
    
    // 各策略名义仓位
    if (temp.strategy_positions) {
        const sp = temp.strategy_positions;
        if (el('val-alloc-total')) el('val-alloc-total').innerText = `总仓位: ${sp.total}%`;
        const setPos = (id, val) => { const e = el(id); if (e) e.innerText = `${val}%`; };
        setPos('val-pos-div', sp.div_pos);
        setPos('val-pos-mr',  sp.mr_pos);
        setPos('val-pos-mom', sp.mom_pos);
        setPos('val-pos-erp', sp.erp_pos || 0);
        setPos('val-pos-aiae', sp.aiae_pos || 0);
    }
    
    // 策略过滤器状态
    if (temp.strategy_filters) {
        const sf = temp.strategy_filters;
        const setFilter = (id, val) => { const e = el(id); if (e) e.innerText = val === '正常' ? '' : val; };
        setFilter('filter-div', sf.div);
        setFilter('filter-mr',  sf.mr);
        setFilter('filter-mom', sf.mom);
    }
}

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
                pos_control: "60-80%",
                tech_logic: "🚀 均线多头持有",
                framework: ["🔥 优先：适度加仓硬科技龙头", "💎 持有算力/AI核心资产", "🛡️ 红利ETF底仓不动"],
                scenarios: [
                    {case: "VIX回落至22-24", action: "适度加仓"},
                    {case: "VIX突破30+", action: "强制止损"}
                ],
                current_tactics: { regime: "🟡 Ⅱ级 正常震荡" },
                regime_matrix: [
                    { regime: "Ⅰ 恐慌 (VIX>30)", tactics: "停止买入·核心仓锁仓·对冲", pos: "≤25%", active: false },
                    { regime: "Ⅱ 正常 (20-30)",   tactics: "结构性调仓·均值回归优先", pos: "50-70%", active: true },
                    { regime: "Ⅲ 低波 (15-20)",   tactics: "趋势跟踪·动量轮动为主", pos: "70-85%", active: false },
                    { regime: "Ⅳ 极静 (<15)",     tactics: "满仓进攻·关注拥挤度风险", pos: "85-95%", active: false }
                ]
            },
            capital_a: { value: "A: 151.4 亿", trend: "外资稳步买入", status: "up" },
            capital_h: { value: "H: 20.5 亿", trend: "南向博弈均衡", status: "neutral" },
            signal: { value: "MR 2买/3卖 · ERP 极度低估", trend: "DT 5/8趋 · AIAE 中性均衡 · MOM AI领涨", status: "up" },
            erp: { value: "3.5%", trend: "极度低估", status: "up" },
            regime_banner: { regime: "🟠 震荡偏多", temp: 52.3, advice: "50-65% (中性偏多)", vix: 20.15, vix_label: "🟡 正常震荡", z_capital: 0.8, aiae_regime: 3, aiae_regime_cn: "中性均衡", aiae_cap: 65, aiae_v1: 22.3 },
            aiae_thermometer: { aiae_v1: 22.3, regime: 3, regime_cn: "中性均衡", regime_emoji: "🟡", regime_color: "#eab308", regime_name: "Regime III", cap: 65, slope: 0.3, slope_direction: "rising", margin_heat: 2.1, fund_position: 82.5, aiae_simple: 19.8, erp_value: 3.5, status: "fallback" },
            market_temp: {
                value: 52.3, label: "温暖 | 极度低估", advice: "55% (趋势共振)",
                regime_name: "平衡模式", mindset: "⚖️ 仓位中型，等待分歧",
                market_vix_multiplier: 1.0, erp_z: 1.8, z_capital: 0.8,
                hub_confidence: 72,
                hub_composite: 62.5,
                hub_factors: {
                    vix_fear:     { score: 78, weight: 0.30, label: "恐慌低位" },
                    capital_flow: { score: 63, weight: 0.20, label: "资金中性" },
                    macro_temp:   { score: 48, weight: 0.20, label: "宏观中性" },
                    erp_value:    { score: 85, weight: 0.15, label: "极度低估" },
                    signal_sync:  { score: 55, weight: 0.15, label: "策略分歧" },
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

/**
 * 渲染行业热力图
 */
function renderHeatmap(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    container.innerHTML = data.map(sector => {
        let intensityClass = '';
        const chg = sector.change;
        const trend5d = sector.trend_5d || 0;
        const rps = sector.rps || 0;
        
        if (chg >= 1.5) intensityClass = 'up-high';
        else if (chg >= 0.5) intensityClass = 'up-mid';
        else if (chg > 0) intensityClass = 'up-low';
        else if (chg <= -1.5) intensityClass = 'down-high';
        else if (chg <= -0.5) intensityClass = 'down-mid';
        else if (chg < 0) intensityClass = 'down-low';
        
        const sign = chg > 0 ? '+' : '';
        const trendSign = trend5d > 0 ? '+' : '';
        
        // 提示信息
        const tooltip = `5日累计: ${trendSign}${trend5d}% | RPS: ${rps} | MR: ${sector.mr_signal || '-'} | MOM: ${sector.mom_signal || '-'}`;
        
        // V5.0 信号角标
        let badges = '';
        if (sector.mr_signal === 'BUY' || sector.mr_signal === '买入') badges += '<span class="hm-badge hm-buy">📐</span>';
        else if (sector.mr_signal === 'SELL' || sector.mr_signal === '卖出') badges += '<span class="hm-badge hm-sell">📐</span>';
        if (sector.mom_signal === 'BUY' || sector.mom_signal === '买入') badges += '<span class="hm-badge hm-buy">🚀</span>';
        
        return `
            <div class="heatmap-cell ${intensityClass}" title="${tooltip}">
                ${badges ? `<div class="hm-badges">${badges}</div>` : ''}
                <span class="sector-name">${sector.name}</span>
                <span class="sector-change">${sign}${chg.toFixed(2)}%</span>
                <span class="sector-rps">5D:${trendSign}${trend5d.toFixed(1)}% · R:${rps}</span>
            </div>
        `;
    }).join('');
}

// Init when DOM loaded
document.addEventListener('DOMContentLoaded', () => {
    
    // 发起网络数据请求
    fetchQuantData();

    // 绑定刷新按钮事件
    const refreshBtn = document.getElementById('refresh-btn');
    if(refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            const originalText = refreshBtn.innerText;
            refreshBtn.innerText = '拉取中...';
            fetchQuantData().then(() => {
                setTimeout(() => refreshBtn.innerText = originalText, 500);
            });
        });
    }

    // 导航交互动效
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const href = item.getAttribute('href');
            if (!href || href === '#') {
                e.preventDefault();
            }
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });

    // ERP 历史走势图异步加载
    fetchAndRenderERPChart();
});

// ====== ERP 历史走势图 (近5年) · 买卖区间可视化 ======

let _erpDashboardChart = null;

/**
 * 从后端拉取 ERP 择时引擎数据并渲染图表
 * 降级策略: 后端未启动时显示友好提示
 */
async function fetchAndRenderERPChart() {
    const loadingEl = document.getElementById('erp-chart-loading');
    const chartEl = document.getElementById('erp-history-chart');
    
    if (!chartEl) return;
    
    // ECharts 库检测
    if (typeof echarts === 'undefined') {
        if (loadingEl) loadingEl.innerHTML = '⚠️ ECharts 可视化库未加载，图表不可用';
        return;
    }
    
    try {
        const resp = await fetch('/api/v1/strategy/erp-timing');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        
        if (json.status === 'success' && json.data && json.data.chart && json.data.chart.status === 'success') {
            // 隐藏 loading，显示图表
            if (loadingEl) loadingEl.style.display = 'none';
            chartEl.style.display = 'block';
            renderERPDashboardChart(json.data.chart);
        } else {
            if (loadingEl) loadingEl.innerHTML = '⚠️ ERP 数据暂不可用 (' + (json.message || '格式异常') + ')';
        }
    } catch (err) {
        console.warn('[ERP Chart] 拉取失败，降级处理:', err);
        if (loadingEl) {
            loadingEl.innerHTML = '📡 请启动 <code style="background:rgba(96,165,250,0.15);padding:2px 6px;border-radius:4px;color:#60a5fa;">python main.py</code> 以获取 ERP 历史数据';
        }
    }
}

/**
 * 渲染 ERP 五年走势 ECharts 图表
 * 移植自 strategy.js renderERPHistoryChart() — 已验证稳定
 */
function renderERPDashboardChart(chart) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom || typeof echarts === 'undefined') return;
    
    if (_erpDashboardChart) _erpDashboardChart.dispose();
    _erpDashboardChart = echarts.init(dom);
    
    const stats = chart.stats || {};
    
    // 买卖区间着色数据
    const buyZone = chart.erp.map(v => v >= (stats.overweight_line || 99) ? v : null);
    const sellZone = chart.erp.map(v => v <= (stats.underweight_line || -99) ? v : null);
    
    _erpDashboardChart.setOption({
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: '#334155',
            textStyle: { fontSize: 11, color: '#e2e8f0' },
            formatter: function(params) {
                let r = '<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">' + params[0].axisValue + '</div>';
                params.forEach(p => {
                    if (p.value != null) {
                        r += '<div>' + p.marker + ' ' + p.seriesName + ': <b>' + p.value + (p.seriesIndex <= 2 ? '%' : '') + '</b></div>';
                    }
                });
                return r;
            }
        },
        legend: {
            data: ['ERP', '买入区', '卖出区', 'PE-TTM', '10Y国债'],
            top: 0,
            textStyle: { color: '#94a3b8', fontSize: 10 }
        },
        grid: { top: 40, bottom: 30, left: 50, right: 50 },
        xAxis: {
            type: 'category',
            data: chart.dates,
            axisLabel: { color: '#64748b', fontSize: 10, interval: Math.floor(chart.dates.length / 6) }
        },
        yAxis: [
            {
                type: 'value', name: 'ERP %',
                nameTextStyle: { color: '#64748b', fontSize: 10 },
                axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
                splitLine: { lineStyle: { color: 'rgba(100,116,139,0.1)' } }
            },
            {
                type: 'value', name: 'PE-TTM',
                nameTextStyle: { color: '#64748b', fontSize: 10 },
                axisLabel: { color: '#64748b', fontSize: 10 },
                splitLine: { show: false }
            }
        ],
        series: [
            {
                name: 'ERP', type: 'line', data: chart.erp, yAxisIndex: 0,
                lineStyle: { color: '#f59e0b', width: 2 },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none', z: 10,
                markLine: {
                    silent: true, symbol: 'none',
                    lineStyle: { type: 'dashed', width: 1 },
                    data: [
                        { yAxis: stats.mean, label: { formatter: '均值 ' + stats.mean + '%', color: '#94a3b8', fontSize: 9 }, lineStyle: { color: '#64748b' } },
                        { yAxis: stats.overweight_line, label: { formatter: '超配线 ' + stats.overweight_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b981' } },
                        { yAxis: stats.underweight_line, label: { formatter: '低配线 ' + stats.underweight_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef4444' } },
                        { yAxis: stats.strong_buy_line, label: { formatter: '强买线 ' + stats.strong_buy_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98180', type: 'dotted' } }
                    ]
                }
            },
            {
                name: '买入区', type: 'line', data: buyZone, yAxisIndex: 0,
                lineStyle: { width: 0 }, itemStyle: { color: '#10b981' }, symbol: 'none',
                areaStyle: { color: 'rgba(16,185,129,0.15)' }
            },
            {
                name: '卖出区', type: 'line', data: sellZone, yAxisIndex: 0,
                lineStyle: { width: 0 }, itemStyle: { color: '#ef4444' }, symbol: 'none',
                areaStyle: { color: 'rgba(239,68,68,0.15)' }
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
            }
        ]
    });
}

// ERP 图表响应式 resize
let _aiaeThermGauge = null;
window.addEventListener('resize', () => {
    if (_erpDashboardChart) _erpDashboardChart.resize();
    if (_aiaeThermGauge) try { _aiaeThermGauge.resize(); } catch(e) {}
});

// ====================================================================
//  AIAE 温度计 · 量化总览精简渲染引擎
// ====================================================================

function renderAIAEThermometer(d) {
    if (!d) return;
    const el = (id) => document.getElementById(id);

    // ── 仪表盘大字 ──
    const v1 = d.aiae_v1 || 0;
    if (el('aiae-thermo-val')) el('aiae-thermo-val').textContent = v1.toFixed(1);

    // ── ECharts 小仪表盘 ──
    try {
        const gaugeEl = el('aiae-thermo-gauge');
        if (gaugeEl && typeof echarts !== 'undefined') {
            if (_aiaeThermGauge) _aiaeThermGauge.dispose();
            _aiaeThermGauge = echarts.init(gaugeEl);
            const rc = d.regime_color || '#eab308';
            _aiaeThermGauge.setOption({
                series: [{
                    type: 'gauge',
                    startAngle: 200,
                    endAngle: -20,
                    min: 0,
                    max: 50,
                    pointer: {
                        show: true, length: '55%', width: 3.5,
                        itemStyle: { color: rc, shadowColor: rc, shadowBlur: 6 },
                        icon: 'triangle'
                    },
                    anchor: {
                        show: true, size: 8,
                        itemStyle: { color: '#0f172a', borderColor: rc, borderWidth: 2 }
                    },
                    axisLine: {
                        lineStyle: {
                            width: 12,
                            color: [
                                [0.24, '#10b981'], [0.32, '#3b82f6'],
                                [0.48, '#eab308'], [0.64, '#f97316'], [1, '#ef4444']
                            ]
                        }
                    },
                    axisTick: { length: 6, distance: -12, lineStyle: { color: 'auto', width: 1 } },
                    splitLine: { length: 10, distance: -12, lineStyle: { color: 'auto', width: 1.5 } },
                    splitNumber: 5,
                    axisLabel: {
                        distance: -30, color: '#64748b', fontSize: 8,
                        formatter: function(val) {
                            var m = {0:'0',10:'10',20:'20',30:'30',40:'40',50:'50'};
                            return m[val] || '';
                        }
                    },
                    detail: { show: false },
                    data: [{ value: Math.min(Math.max(v1, 0), 50) }],
                    animationDuration: 1000,
                    animationEasingUpdate: 'cubicOut'
                }]
            });
        }
    } catch(e) { console.warn('[AIAE Thermo] gauge skip:', e); }

    // ── 档位徽章 ──
    const regimeEl = el('aiae-thermo-regime');
    if (regimeEl) {
        regimeEl.textContent = (d.regime_emoji || '🟡') + ' ' + (d.regime_cn || '中性均衡');
        regimeEl.style.color = d.regime_color || '#eab308';
        regimeEl.style.borderColor = (d.regime_color || '#eab308') + '66';
        regimeEl.style.background = (d.regime_color || '#eab308') + '18';
    }

    // ── 月环比斜率 ──
    const slopeEl = el('aiae-thermo-slope');
    if (slopeEl) {
        const slope = d.slope || 0;
        const dir = d.slope_direction || 'flat';
        const arrow = dir === 'rising' ? '↗' : (dir === 'falling' ? '↘' : '→');
        slopeEl.textContent = '月环比: ' + arrow + ' ' + (slope > 0 ? '+' : '') + slope;
        slopeEl.style.color = dir === 'rising' ? '#f97316' : (dir === 'falling' ? '#10b981' : '#94a3b8');
    }

    // ── 五档高亮 ──
    const tiers = document.querySelectorAll('#aiae-thermo-tiers .at-tier');
    tiers.forEach(t => {
        const tier = parseInt(t.dataset.tier);
        t.classList.toggle('active', tier === d.regime);
    });

    // ── Cap 仓位 ──
    const cap = d.cap || 0;
    if (el('aiae-thermo-cap')) el('aiae-thermo-cap').textContent = cap + '%';
    if (el('aiae-thermo-cap-bar')) el('aiae-thermo-cap-bar').style.width = cap + '%';

    // ── 三大预警 ──
    // 融资热度
    const mh = d.margin_heat || 0;
    if (el('at-warn-margin')) {
        el('at-warn-margin').textContent = mh + '%';
        el('at-warn-margin').style.color = mh > 3.5 ? '#ef4444' : mh > 2.5 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-margin-bar')) {
        el('at-warn-margin-bar').style.width = Math.min(mh / 5 * 100, 100) + '%';
        el('at-warn-margin-bar').style.background = mh > 3.5 ? '#ef4444' : mh > 2.5 ? '#f59e0b' : '#10b981';
    }
    // 月斜率
    const absSlope = Math.abs(d.slope || 0);
    if (el('at-warn-slope')) {
        el('at-warn-slope').textContent = (d.slope > 0 ? '+' : '') + (d.slope || 0);
        el('at-warn-slope').style.color = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-slope-bar')) {
        el('at-warn-slope-bar').style.width = Math.min(absSlope / 3 * 100, 100) + '%';
        el('at-warn-slope-bar').style.background = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981';
    }
    // 基金仓位
    const fp = d.fund_position || 0;
    if (el('at-warn-fund')) {
        el('at-warn-fund').textContent = fp + '%';
        el('at-warn-fund').style.color = fp > 90 ? '#ef4444' : fp > 85 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-fund-bar')) {
        el('at-warn-fund-bar').style.width = Math.min(fp / 100 * 100, 100) + '%';
        el('at-warn-fund-bar').style.background = fp > 90 ? '#ef4444' : fp > 85 ? '#f59e0b' : '#10b981';
    }

    // ── 数据来源 ──
    if (el('at-src-simple')) el('at-src-simple').textContent = 'AIAE_简: ' + (d.aiae_simple || 0) + '%';
    if (el('at-src-erp')) el('at-src-erp').textContent = 'ERP: ' + (d.erp_value || 0) + '%';

    // ── 操作指引 (按档位) ──
    const actionMap = {
        1: '🟢 Ⅰ级恐慌 · 分3批满仓进攻，越跌越买。优先宽基ETF (300/50/500)',
        2: '🔵 Ⅱ级低配 · 标准建仓区，按节奏买入。不因波动减仓，坚定持有',
        3: '🟡 Ⅲ级中性 · 维持均衡仓位，有纪律持有。到目标价就卖，不贪婪',
        4: '🟠 Ⅳ级偏热 · 禁止新开仓。每周减5%总仓位，优先清退高波动标的',
        5: '🔴 Ⅴ级过热 · 绝对禁止买入！3天内完成清仓，无例外执行'
    };
    if (el('aiae-thermo-action-text')) {
        el('aiae-thermo-action-text').textContent = actionMap[d.regime] || actionMap[3];
    }
}
