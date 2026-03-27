/**
 * AlphaCore Factor Analysis Terminal V1.0
 */

document.addEventListener('DOMContentLoaded', function() {
    const runBtn = document.getElementById('run-analysis-btn');
    const overlay = document.getElementById('loading-overlay');
    
    let charts = { ic: null, qAvg: null, qCum: null };

    function initCharts() {
        if (!charts.ic) charts.ic = echarts.init(document.getElementById('ic-series-chart'));
        if (!charts.qAvg) charts.qAvg = echarts.init(document.getElementById('quantile-avg-chart'));
        if (!charts.qCum) charts.qCum = echarts.init(document.getElementById('quantile-cum-chart'));
    }

    runBtn.addEventListener('click', async () => {
        const payload = {
            factor_name: document.getElementById('factor-select').value,
            stock_pool: document.getElementById('pool-select').value,
            start_date: document.getElementById('start-date').value,
            end_date: document.getElementById('end-date').value
        };

        overlay.style.display = 'flex';
        initCharts();

        try {
            const response = await fetch('/api/v1/factor-analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            
            if (result.status === 'success') {
                renderResults(result.data);
            } else {
                alert("分析失败: " + result.message);
            }
        } catch (err) {
            alert("请求异常: " + err.message);
        } finally {
            overlay.style.display = 'none';
        }
    });

    function renderResults(data) {
        // Stats
        document.getElementById('res-ic-mean').textContent = data.ic_mean.toFixed(4);
        document.getElementById('res-ic-ir').textContent = data.ic_ir.toFixed(4);
        document.getElementById('res-sample-count').textContent = data.ic_series.dates.length;

        // IC Series Chart
        charts.ic.setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis' },
            grid: { top: 20, bottom: 40, left: 50, right: 20 },
            xAxis: { type: 'category', data: data.ic_series.dates, axisLabel: { color: '#64748b', fontSize: 10 } },
            yAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
            series: [{
                name: 'Rank IC', type: 'bar', data: data.ic_series.values,
                itemStyle: { color: function(p) { return p.value >= 0 ? '#10b981' : '#ef4444' } }
            }]
        });

        // Quantile Avg Chart
        charts.qAvg.setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis' },
            grid: { top: 40, bottom: 40, left: 50, right: 20 },
            xAxis: { type: 'category', data: data.quantile_rets.quantiles, axisLabel: { color: '#64748b' } },
            yAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
            series: [{
                name: 'Avg Return', type: 'bar', data: data.quantile_rets.avg_rets.map(v => (v * 100).toFixed(2)),
                itemStyle: { color: '#3b82f6' },
                label: { show: true, position: 'top', formatter: '{c}%', color: '#fff' }
            }]
        });

        // Quantile Cum Chart
        const colors = ['#64748b', '#94a3b8', '#3b82f6', '#10b981', '#f59e0b'];
        const cumSeries = data.quantile_rets.cum_rets.series.map((s, i) => ({
            name: `Q${i+1}`, type: 'line', smooth: true, showSymbol: false,
            data: s.map(v => (v * 100).toFixed(2)),
            lineStyle: { width: 2, color: colors[i] }
        }));

        charts.qCum.setOption({
            backgroundColor: 'transparent',
            tooltip: { trigger: 'axis' },
            legend: { data: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], textStyle: { color: '#94a3b8' }, top: 0 },
            grid: { top: 40, bottom: 40, left: 50, right: 20 },
            xAxis: { type: 'category', data: data.quantile_rets.cum_rets.dates, axisLabel: { color: '#64748b', fontSize: 10 } },
            yAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
            series: cumSeries
        });
    }

    // Auto-resize
    window.addEventListener('resize', () => {
        Object.values(charts).forEach(c => c && c.resize());
    });
});
