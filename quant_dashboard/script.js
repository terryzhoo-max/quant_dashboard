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
    }
    
    // 4. 更新情绪与持仓枢纽 (V4.6 Sentiment & Position Hub)
    if (marketData.macro_cards && marketData.macro_cards.market_temp) {
        const temp = marketData.macro_cards.market_temp;
        const vixMult = temp.market_vix_multiplier || 1.0;
        
        // --- 左侧：宏观分析 (Macro Status) ---
        if (document.getElementById('val-market-temp')) {
            document.getElementById('val-market-temp').innerText = `${temp.value}°`;
        }
        
        // VIX 避险修正标签显示与颜色逻辑
        const riskLabel = document.getElementById('label-market-temp');
        if (riskLabel) {
            const isVixHedged = vixMult < 0.9;
            riskLabel.innerText = isVixHedged ? `${temp.label} (VIX 避险修正)` : temp.label;
            riskLabel.style.color = isVixHedged ? "#ef4444" : "#10b981";
        }

        if (document.getElementById('val-temp-a')) {
            document.getElementById('val-temp-a').innerText = `${temp.value}`;
        }
        if (document.getElementById('val-regime-name')) {
            document.getElementById('val-regime-name').innerText = temp.regime_name || "模式识别中";
        }
        if (document.getElementById('val-mindset')) {
            document.getElementById('val-mindset').innerText = temp.mindset || "侦测中...";
        }

        // --- 右侧：战术仓位与演进 (Tactical Status) ---
        if (document.getElementById('val-pos-advice')) {
            document.getElementById('val-pos-advice').innerText = temp.advice;
        }
        if (document.getElementById('bar-pos-advice')) {
            const posMatch = temp.advice.match(/(\d+)%/);
            if (posMatch) document.getElementById('bar-pos-advice').style.width = `${posMatch[1]}%`;
        }

        
        // V3.6 新增: 子策略权重更新
        if (temp.regime_weights) {
            if (document.getElementById('weight-mr')) document.getElementById('weight-mr').innerText = `${(temp.regime_weights.mr * 100).toFixed(0)}%权重`;
            if (document.getElementById('weight-mom')) document.getElementById('weight-mom').innerText = `${(temp.regime_weights.mom * 100).toFixed(0)}%权重`;
            if (document.getElementById('weight-div')) document.getElementById('weight-div').innerText = `${(temp.regime_weights.div * 100).toFixed(0)}%权重`;
            
            // V3.9 策略配仓总览: 比例条
            const barDiv = document.getElementById('bar-div');
            const barMr  = document.getElementById('bar-mr');
            const barMom = document.getElementById('bar-mom');
            if (barDiv) { barDiv.style.width = `${(temp.regime_weights.div * 100).toFixed(0)}%`; barDiv.querySelector('span').innerText = `红利 ${(temp.regime_weights.div * 100).toFixed(0)}%`; }
            if (barMr)  { barMr.style.width  = `${(temp.regime_weights.mr  * 100).toFixed(0)}%`; barMr.querySelector('span').innerText  = `均值 ${(temp.regime_weights.mr  * 100).toFixed(0)}%`; }
            if (barMom) { barMom.style.width = `${(temp.regime_weights.mom * 100).toFixed(0)}%`; barMom.querySelector('span').innerText = `动量 ${(temp.regime_weights.mom * 100).toFixed(0)}%`; }
        }
        
        // V3.9 各策略名义仓位
        if (temp.strategy_positions) {
            const sp = temp.strategy_positions;
            const totalEl = document.getElementById('val-alloc-total');
            if (totalEl) totalEl.innerText = `总仓位: ${sp.total}%`;
            const setPosVal = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = `${val}%`; };
            setPosVal('val-pos-div', sp.div_pos);
            setPosVal('val-pos-mr',  sp.mr_pos);
            setPosVal('val-pos-mom', sp.mom_pos);
        }
        
        // V3.9 策略过滤器状态
        if (temp.strategy_filters) {
            const sf = temp.strategy_filters;
            const setFilter = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val === '正常' ? '' : val; };
            setFilter('filter-div', sf.div);
            setFilter('filter-mr',  sf.mr);
            setFilter('filter-mom', sf.mom);
        }

        // DMSO 分指数更新
        if (temp.score_a !== undefined && document.getElementById('val-temp-a')) {
            document.getElementById('val-temp-a').innerText = temp.score_a;
        }
        if (temp.score_hk !== undefined && document.getElementById('val-temp-hk')) {
            document.getElementById('val-temp-hk').innerText = temp.score_hk;
        }
        
        // 建议比例进度条
        const match = temp.advice.match(/(\d+)%/);
        if (match) {
            document.getElementById('bar-pos-advice').style.width = `${match[1]}%`;
        }
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
    
    // 2. 更新策略监控卡片 (Option C)
    if (marketData.strategy_status) {
        updateStrategyCard('mr', marketData.strategy_status.mr);
        updateStrategyCard('mom', marketData.strategy_status.mom);
        updateStrategyCard('div', marketData.strategy_status.div);
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

function updateStrategyCard(prefix, data) {
    if (!data) return;
    
    const statusEl = document.getElementById(`strat-status-${prefix}`);
    if (statusEl) {
        statusEl.innerText = data.status_text;
        statusEl.className = `strat-status ${data.status_class}`; // active, warning, dormant
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
                framework: ["适度加仓硬科技龙头", "持有国产算力/AI核心资产"],
                scenarios: [
                    {case: "VIX回落至22-24", action: "适度加仓"},
                    {case: "VIX突破30+", action: "强制止损"}
                ]
            },
            capital_a: { value: "A: 151.4 亿", trend: "外资稳步买入", status: "up" },
            capital_h: { value: "H: 20.5 亿", trend: "南向博弈均衡", status: "neutral" },
            signal: { value: "右侧胜率区", trend: "动量与红利共振", status: "up" },
            erp: { value: "3.5%", trend: "极度低估", status: "up" }
        },
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
            div: { status_text: "稳定防御", status_class: "dormant", metric1: "4.82%", metric2: "62%" }
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
        
        // 提示信息包含 5D 趋势和 RPS (相对强弱)
        const tooltip = `5日累计: ${trendSign}${trend5d}% | 相对强弱(RPS): ${rps > 0 ? '+' : ''}${rps}`;
        
        return `
            <div class="heatmap-cell ${intensityClass}" title="${tooltip}">
                <span class="sector-name">${sector.name}</span>
                <span class="sector-change">${sign}${chg.toFixed(2)}%</span>
                <span class="sector-trend" style="font-size: 0.75rem; opacity: 0.7;">5D: ${trendSign}${trend5d.toFixed(1)}%</span>
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
});
