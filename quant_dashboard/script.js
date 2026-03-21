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
    const valEl = document.getElementById(valId);
    
    // Update HTML layout based on the design plan
    valEl.innerHTML = `
        ${dataItem.value} 
        <span class="trend" id="${trendId}">${dataItem.trend}</span>
    `;
    
    // Dynamically set highlight color based on status (up = green, down = red, neutral = gray etc)
    const cardEl = document.getElementById(cardId);
    if (dataItem.status === 'up') {
        valEl.className = 'stat-value highlight-up';
        if (cardEl) cardEl.classList.add('active-glow');
    } else if (dataItem.status === 'down') {
        valEl.className = 'stat-value highlight-down';
        if (cardEl) cardEl.classList.remove('active-glow');
    } else {
        valEl.className = 'stat-value';
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
        updateCardUI('card-vix', 'val-vix', 'trend-vix', marketData.macro_cards.vix);
        updateCardUI('card-erp', 'val-erp', 'trend-erp', marketData.macro_cards.erp);
        updateCardUI('card-capital', 'val-capital', 'trend-capital', marketData.macro_cards.capital);
        updateCardUI('card-signal', 'val-signal', 'trend-signal', marketData.macro_cards.signal);
    }
    
    // Render Execution Lists    // 4. 更新情绪仪表盘 (Market Temperature & Advice)
    if (marketData.macro_cards.market_temp) {
        const temp = marketData.macro_cards.market_temp;
        document.getElementById('val-market-temp').innerText = `${temp.value}°`;
        document.getElementById('label-market-temp').innerText = temp.label;
        document.getElementById('val-pos-advice').innerText = temp.advice;
        
        // 简单正则提取建议比例的平均值用于进度条
        const match = temp.advice.match(/(\d+)%/);
        if (match) {
            const posVal = match[1];
            document.getElementById('bar-pos-advice').style.width = `${posVal}%`;
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
            vix: { value: 20.15, trend: "+5.2%", status: "up" },
            benchmark: { value: "多头排列", trend: "短期均线发散", status: "up" },
            capital: { value: "-124.5 亿", trend: "缩量流出", status: "down" },
            signal: { value: "右侧胜率区", trend: "动量与红利共振", status: "up" }
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
