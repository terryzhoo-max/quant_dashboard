// 全局图表实例，方便后续更新
let trendChartInstance = null;
let radarChartInstance = null;

// 后端 API 地址
const API_URL = 'http://127.0.0.1:8000/api/v1/dashboard-data';

// 格式化函数
const formatTrend = (change, isInverse = false) => {
    // 对于某些指标（如资金流入），下跌可能判定为 down。对于 VIX，上涨代表恐慌。
    const sign = change > 0 ? '+' : '';
    const arrow = change > 0 ? '▲' : '▼';
    return `${arrow} ${sign}${change}%`;
};

const updateCardUI = (cardId, valId, trendId, dataItem) => {
    const valEl = document.getElementById(valId);
    const trendEl = document.getElementById(trendId);
    
    // 更新数值和趋势
    valEl.innerHTML = `${dataItem.value} <span class="trend" id="${trendId}">${formatTrend(dataItem.change)}</span>`;
    
    // 动态调整高亮颜色
    if (dataItem.status === 'up') {
        valEl.className = 'stat-value highlight-up';
    } else {
        valEl.className = 'stat-value highlight-down';
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
    // 1. 更新顶部卡片数值
    updateCardUI('card-vix', 'val-vix', 'trend-vix', marketData.vix);
    updateCardUI('card-capital', 'val-capital', 'trend-capital', marketData.capitalFlow);
    updateCardUI('card-dividend', 'val-dividend', 'trend-dividend', marketData.dividendYield);
    
    // 2. 更新折线图
    if (trendChartInstance) {
        trendChartInstance.data.labels = marketData.trendChart.labels;
        trendChartInstance.data.datasets[0].data = marketData.trendChart.aiInfrastructure;
        trendChartInstance.data.datasets[1].data = marketData.trendChart.traditional;
        trendChartInstance.update('active');
    }

    // 3. 更新雷达图
    if (radarChartInstance) {
        radarChartInstance.data.labels = marketData.radarChart.labels;
        radarChartInstance.data.datasets[0].data = marketData.radarChart.alphaModel;
        radarChartInstance.data.datasets[1].data = marketData.radarChart.betaModel;
        radarChartInstance.update();
    }
}

function showFallbackData() {
    const fallbackData = {
        vix: { value: 20.15, change: 5.2, status: "up" },
        capitalFlow: { value: -124.5, change: -1.5, status: "down" },
        dividendYield: { value: 4.2, change: 0.3, status: "up" },
        trendChart: {
            labels: ['2023Q4', '2024Q2', '2024Q4', '2025Q2', '2025Q4', '2026Q2(E)'],
            aiInfrastructure: [10, 25, 40, 60, 75, 95], 
            traditional: [45, 40, 32, 28, 20, 15]
        },
        radarChart: {
            labels: ['盈利动量', '资产质量', '估值倍数(倒数)', '成长性', '交易拥挤度(倒数)', '宏观贝塔'],
            alphaModel: [92, 85, 68, 95, 45, 88],
            betaModel: [60, 85, 45, 35, 80, 55]
        }
    };
    updateDashboard(fallbackData);
}

// 首次渲染图表的基础底座
function renderCharts() {
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    
    // ================= Trend Chart =================
    const trendCtx = document.getElementById('trendChart').getContext('2d');
    const gradientAI = trendCtx.createLinearGradient(0, 0, 0, 350);
    gradientAI.addColorStop(0, 'rgba(59, 130, 246, 0.45)');
    gradientAI.addColorStop(1, 'rgba(59, 130, 246, 0.02)');

    trendChartInstance = new Chart(trendCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'AI算力基础设施核心动能',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: gradientAI,
                borderWidth: 3,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#07090e',
                pointBorderColor: '#3b82f6',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6
            },
            {
                label: '传统系统集成利润中枢',
                data: [],
                borderColor: '#ef4444',
                borderWidth: 2,
                borderDash: [5, 5],
                tension: 0.4,
                pointRadius: 0,
                pointHoverRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', align: 'end', labels: { boxWidth: 12, usePointStyle: true, padding: 20 } },
                tooltip: { backgroundColor: 'rgba(13, 16, 23, 0.95)', titleColor: '#fff', bodyColor: '#e2e8f0', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, padding: 12, boxPadding: 6, usePointStyle: true }
            },
            scales: {
                y: { grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false }, border: { display: false } },
                x: { grid: { display: false }, border: { display: false } }
            }
        }
    });

    // ================= Radar Chart =================
    const radarCtx = document.getElementById('radarChart').getContext('2d');
    radarChartInstance = new Chart(radarCtx, {
        type: 'radar',
        data: {
            labels: [],
            datasets: [{
                label: '全市场标兵模型',
                data: [],
                backgroundColor: 'rgba(139, 92, 246, 0.25)',
                borderColor: '#8b5cf6',
                pointBackgroundColor: '#8b5cf6',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#8b5cf6',
                borderWidth: 2,
            }, {
                label: '大盘防御基准',
                data: [],
                backgroundColor: 'rgba(16, 185, 129, 0.15)',
                borderColor: '#10b981',
                pointBackgroundColor: '#10b981',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#10b981',
                borderWidth: 2,
                borderDash: [5, 5]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    angleLines: { color: 'rgba(255,255,255,0.06)' },
                    grid: { color: 'rgba(255,255,255,0.06)' },
                    pointLabels: { color: '#cbd5e1', font: { size: 11, family: "'Inter', sans-serif" } },
                    ticks: { display: false, max: 100, min: 0 }
                }
            },
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, usePointStyle: true, padding: 20 } },
                tooltip: { backgroundColor: 'rgba(13, 16, 23, 0.95)', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, padding: 10 }
            }
        }
    });
}

// Init when DOM loaded
document.addEventListener('DOMContentLoaded', () => {
    // 渲染图表空骨架
    renderCharts();
    
    // 发起网络数据请求
    fetchQuantData();

    // 绑定刷新按钮事件
    const refreshBtn = document.getElementById('refresh-btn');
    if(refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            const originalText = refreshBtn.innerText;
            refreshBtn.innerText = '拉取中...';
            // 添加旋转体动画逻辑也可以放这
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
            // 只对 # 链接阻止默认行为，真实页面链接允许跳转
            if (!href || href === '#') {
                e.preventDefault();
            }
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });
});
