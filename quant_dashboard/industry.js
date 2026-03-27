document.addEventListener('DOMContentLoaded', function() {
    const navContainer = document.getElementById('sector-nav-container');
    const datePicker = document.getElementById('data-date-picker');
    const syncBtn = document.getElementById('sync-btn');
    const overlay = document.getElementById('loading-overlay');
    
    let charts = { rps: null, value: null, risk: null, rsLine: null, rotation: null };
    let currentCode = null; // Will be set to #1 ranked sector

    let SECTORS = [
        { code: "512760.SH", name: "半导体/芯片" },
        { code: "512720.SH", name: "计算机/AI" },
        { code: "515030.SH", name: "新能源车" },
        { code: "512010.SH", name: "医药生物" },
        { code: "512690.SH", name: "酒/自选消费" },
        { code: "512880.SH", name: "证券/非银" },
        { code: "512800.SH", name: "银行/金融" },
        { code: "512660.SH", name: "军工龙头" },
        { code: "512100.SH", name: "中证传媒" },
        { code: "512400.SH", name: "有色金属" },
        { code: "510180.SH", name: "上证180/主板" },
        { code: "159915.SZ", name: "创业板/成长" }
    ];

    async function initPage() {
        datePicker.value = new Date().toISOString().split('T')[0];
        initCharts();
        
        // Step 1: Fetch rotation matrix first to get ranking data
        await loadRotationMatrix(); 
        
        // Step 2: Render details for the now-selected top sector
        if (currentCode) {
            loadIndustryDetail(currentCode);
        }
    }

    function renderSectorNav(rankData = []) {
        // Sort SECTORS based on rankData (trend_5d)
        if (rankData.length > 0) {
            const rankMap = {};
            rankData.forEach(item => rankMap[item.ts_code] = item.trend_5d);
            
            SECTORS.sort((a, b) => {
                const valA = rankMap[a.code] || -999;
                const valB = rankMap[b.code] || -999;
                return valB - valA; // Descending
            });
            
            if (!currentCode) currentCode = SECTORS[0].code;
        }

        navContainer.innerHTML = SECTORS.map((s, idx) => {
            const trend = rankData.find(r => (r.ts_code === s.code || r.code === s.code))?.trend_5d || 0;
            const color = trend > 0 ? '#f87171' : (trend < 0 ? '#34d399' : '#94a3b8');
            return `
                <div class="sector-tile ${s.code === currentCode ? 'active' : ''}" data-code="${s.code}">
                    <div style="position:absolute; top:5px; left:8px; font-size:0.6rem; opacity:0.4; font-weight:800;">#${idx+1}</div>
                    <span class="tile-name">${s.name}</span>
                    <span class="tile-code" style="color:${color}; opacity:1; font-weight:700;">${trend > 0 ? '+' : ''}${trend.toFixed(1)}%</span>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.sector-tile').forEach(tile => {
            tile.addEventListener('click', () => {
                const code = tile.getAttribute('data-code');
                if (code === currentCode) return;
                
                document.querySelectorAll('.sector-tile').forEach(t => t.classList.remove('active'));
                tile.classList.add('active');
                currentCode = code;
                loadIndustryDetail(code);
            });
        });
    }

    function initCharts() {
        charts.rps = echarts.init(document.getElementById('gauge-rps'));
        charts.value = echarts.init(document.getElementById('gauge-value'));
        charts.risk = echarts.init(document.getElementById('gauge-risk'));
        charts.rsLine = echarts.init(document.getElementById('rs-line-chart'));
        charts.rotation = echarts.init(document.getElementById('rotation-line-chart'));
    }

    function getGaugeOption(name, value, color, unit = '') {
        return {
            series: [{
                type: 'gauge',
                startAngle: 180, endAngle: 0,
                radius: '95%',
                center: ['50%', '75%'],
                progress: { show: true, width: 10, itemStyle: { color: color, shadowBlur: 10, shadowColor: color } },
                axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(255,255,255,0.05)']] } },
                axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false },
                pointer: { show: false },
                detail: {
                    valueAnimation: true,
                    offsetCenter: [0, -15],
                    fontSize: 28,
                    fontWeight: '800',
                    color: '#fff',
                    fontFamily: 'Outfit',
                    formatter: `{value}${unit}`
                },
                data: [{ value: value }]
            }]
        };
    }

    async function loadIndustryDetail(code) {
        try {
            const res = await fetch(`/api/v1/industry-detail?code=${code}`);
            const result = await res.json();
            if (result.status === 'success') {
                const data = result.data;
                const m = data.metrics;

                // Update Gauges with enhanced visuals
                charts.rps.setOption(getGaugeOption('RPS', m.rps, m.rps > 80 ? '#3b82f6' : '#94a3b8'));
                charts.value.setOption(getGaugeOption('Value', m.pe_percentile, m.pe_percentile > 70 ? '#ef4444' : (m.pe_percentile < 30 ? '#10b981' : '#f59e0b'), '%'));
                charts.risk.setOption(getGaugeOption('Risk', m.crowding, m.crowding > 1.5 ? '#ef4444' : '#6366f1', 'x'));

                // Descriptions & Pulse Values
                const valFlow = document.getElementById('val-flow');
                valFlow.textContent = m.hsgt_flow;
                valFlow.classList.add('pulse-value');

                document.getElementById('desc-rps').innerHTML = `<span class="stat-desc" style="color:${m.rps > 80 ? '#3b82f6' : '#94a3b8'}">${m.rps > 80 ? "🔥 强势领涨" : "🛡️ 震荡蓄势"}</span>`;
                document.getElementById('desc-value').innerHTML = `<span class="stat-desc" style="color:${m.pe_percentile < 30 ? '#10b981' : (m.pe_percentile > 70 ? '#ef4444' : '#f59e0b')}">${m.pe_percentile < 30 ? "💎 极度低估" : (m.pe_percentile > 70 ? "⚠️ 估值偏高" : "⚖️ 合理区间")}</span>`;
                document.getElementById('desc-risk').innerHTML = `<span class="stat-desc" style="color:${m.crowding > 1.5 ? '#ef4444' : '#6366f1'}">${m.crowding > 1.5 ? "🚫 极其拥挤" : "✅ 筹码健康"}</span>`;

                // RS Line Chart
                charts.rsLine.setOption({
                    tooltip: { trigger: 'axis', backgroundColor: 'rgba(10, 10, 10, 0.8)', borderColor: 'rgba(255,255,255,0.1)', textStyle: { color: '#fff' } },
                    grid: { top: 40, bottom: 40, left: 50, right: 30 },
                    xAxis: { type: 'category', data: data.chart_data.dates.map(d => d.substring(4)), axisLabel: { color: '#64748b' } },
                    yAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
                    legend: { data: ['中枢价格', '相对强度(RS)'], textStyle: { color: '#94a3b8' }, right: 10, icon: 'circle' },
                    series: [
                        { name: '中枢价格', type: 'line', data: data.chart_data.prices, itemStyle: { color: '#3b82f6' }, smooth: true, showSymbol: false, areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [{offset:0, color:'rgba(59,130,246,0.2)'},{offset:1, color:'transparent'}]) } },
                        { name: '相对强度(RS)', type: 'line', data: data.chart_data.relative_strength, itemStyle: { color: '#10b981' }, smooth: true, showSymbol: false }
                    ]
                });

                // Constituents
                const list = document.getElementById('list-constituents');
                list.innerHTML = m.constituents.map(c => `
                    <li>
                        <span>${c.name}</span>
                        <span>权重 ${c.weight}</span>
                    </li>
                `).join('');

            }
        } catch (err) { console.error(err); }
    }

    async function loadRotationMatrix() {
        try {
            const res = await fetch('/api/v1/industry-tracking');
            const result = await res.json();
            if (result.status === 'success') {
                const heatmap = result.data.sector_heatmap;
                
                // DATA-DRIVEN SORTING: Pass data to navigator renderer
                renderSectorNav(heatmap);

                charts.rotation.setOption({
                    tooltip: { trigger: 'axis' },
                    grid: { top: 40, bottom: 60, left: 50, right: 30 },
                    xAxis: { type: 'category', data: heatmap.map(s => s.name), axisLabel: { color: '#64748b', rotate: 30 } },
                    yAxis: { type: 'value', axisLabel: { color: '#64748b', formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
                    series: [{
                        type: 'bar', data: heatmap.map(s => s.trend_5d),
                        itemStyle: { 
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset:0, color:'#3b82f6'},{offset:1, color:'#10b981'}]),
                            borderRadius: [4, 4, 0, 0] 
                        }
                    }]
                });
            }
        } catch (err) { console.error(err); }
    }

    async function syncData() {
        if (!confirm("确定要同步全量产业情报吗？\n将触发 12 个核心 ETF 近 60 日行情、估值及资金流数据的深度抓取，约需 10-20 秒。")) return;

        overlay.style.display = 'flex';
        const loadingText = overlay.querySelector('p');
        loadingText.textContent = "AlphaCore 正在通过 Tushare/HSGT 接口同步增量数据...";

        try {
            const res = await fetch('/api/v1/sync/industry', { method: 'POST' });
            const result = await res.json();
            
            if (result.status === 'success') {
                alert("同步成功！最新数据已就绪。");
                await loadRotationMatrix(); // Re-sort first
                loadIndustryDetail(currentCode);
            } else {
                alert("同步完成，请刷新查看最新状态。");
                loadIndustryDetail(currentCode);
            }
        } catch (err) {
            console.error("同步异常", err);
            loadIndustryDetail(currentCode);
        } finally {
            overlay.style.display = 'none';
        }
    }

    syncBtn.addEventListener('click', syncData);

    initPage();
    window.addEventListener('resize', () => Object.values(charts).forEach(c => c && c.resize()));
});
