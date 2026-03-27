/**
 * AlphaCore Portfolio Manager V1.0
 */

document.addEventListener('DOMContentLoaded', function() {
    const tradeModal = document.getElementById('trade-modal');
    const openTradeBtn = document.getElementById('open-trade-btn');
    const closeTradeBtn = document.getElementById('close-modal');
    const buyBtn = document.getElementById('buy-btn');
    const sellBtn = document.getElementById('sell-btn');

    let charts = { sector: null, mctr: null };

    function initCharts() {
        if (!charts.sector) charts.sector = echarts.init(document.getElementById('sector-pie-chart'));
        if (!charts.mctr) charts.mctr = echarts.init(document.getElementById('mctr-chart'));
    }

    async function loadPortfolio() {
        try {
            const res = await fetch('/api/v1/portfolio/valuation');
            const result = await res.json();
            if (result.status === 'success') {
                updateUI(result.data);
                loadRisk();
            }
        } catch (err) { console.error(err); }
    }

    async function loadRisk() {
        try {
            const res = await fetch('/api/v1/portfolio/risk');
            const result = await res.json();
            if (result.status === 'success' && result.data.status !== 'empty') {
                renderRiskCharts(result.data);
            }
        } catch (err) { console.error(err); }
    }

    function updateUI(data) {
        document.getElementById('port-cash').textContent = "￥" + data.cash.toLocaleString();
        document.getElementById('port-mv').textContent = "￥" + data.market_value.toLocaleString();
        document.getElementById('nav-val').textContent = "总资产: ￥" + data.total_asset.toLocaleString();

        const body = document.getElementById('positions-body');
        body.innerHTML = '';
        
        data.positions.forEach(pos => {
            const row = document.createElement('tr');
            const pnlClass = pos.pnl >= 0 ? 'status-up' : 'status-down';
            row.innerHTML = `
                <td>${pos.ts_code}</td>
                <td>${pos.name}</td>
                <td>${pos.amount}</td>
                <td>${pos.cost}</td>
                <td>${pos.price}</td>
                <td>${pos.market_value.toLocaleString()}</td>
                <td class="${pnlClass}">${pos.pnl_pct}%</td>
                <td>
                    <button class="btn btn-outline" style="padding: 2px 8px; font-size: 0.7rem;" onclick="quickTrade('${pos.ts_code}', '${pos.name}')">交易</button>
                </td>
            `;
            body.appendChild(row);
        });
    }

    function renderRiskCharts(risk) {
        initCharts();

        // MCTR Chart
        const mctrOption = {
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis' },
            xAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
            yAxis: { type: 'category', data: risk.details.map(d => d.name), axisLabel: { color: '#f8fafc' } },
            series: [{
                name: 'Risk Contribution (%)',
                type: 'bar',
                data: risk.details.map(d => d.risk_contribution),
                itemStyle: { color: '#ef4444' }
            }]
        };
        charts.mctr.setOption(mctrOption);

        // Sector Pie (Dummy grouping for now - since engine doesn't return industry yet)
        const pieOption = {
            backgroundColor: 'transparent',
            tooltip: { trigger: 'item' },
            series: [{
                type: 'pie',
                radius: ['40%', '70%'],
                data: risk.details.map(d => ({ name: d.name, value: d.weight })),
                label: { color: '#94a3b8' }
            }]
        };
        charts.sector.setOption(pieOption);
        
        document.getElementById('port-vol').textContent = (risk.portfolio_vol * 100).toFixed(2) + "%";
    }

    async function doTrade(action) {
        const payload = {
            ts_code: document.getElementById('trade-code').value,
            name: document.getElementById('trade-name').value,
            amount: parseInt(document.getElementById('trade-amount').value),
            price: parseFloat(document.getElementById('trade-price').value),
            action: action
        };

        const res = await fetch('/api/v1/portfolio/trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await res.json();
        if (result.status === 'success') {
            alert(result.message);
            tradeModal.style.display = 'none';
            loadPortfolio();
        } else {
            alert("交易失败: " + result.message);
        }
    }

    window.quickTrade = (code, name) => {
        document.getElementById('trade-code').value = code;
        document.getElementById('trade-name').value = name;
        tradeModal.style.display = 'flex';
    };

    openTradeBtn.onclick = () => tradeModal.style.display = 'flex';
    closeTradeBtn.onclick = () => tradeModal.style.display = 'none';
    buyBtn.onclick = () => doTrade('buy');
    sellBtn.onclick = () => doTrade('sell');

    loadPortfolio();
});
