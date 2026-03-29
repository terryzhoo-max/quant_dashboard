document.addEventListener('DOMContentLoaded', function() {
    const navContainer = document.getElementById('sector-nav-container');
    const datePicker = document.getElementById('data-date-picker');
    const syncBtn = document.getElementById('sync-btn');
    const overlay = document.getElementById('loading-overlay');

    let charts = { rps: null, value: null, risk: null, rsLine: null, radar: null };
    let currentCode = null;
    let allSectorData = [];

    const SECTORS = [
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

    // === 指标百科数据 ===
    const GLOSSARY = [
        { name: "Alpha Score (综合评分)", desc: "四因子加权的综合投资评分。热度30% + 动量25% + 估值安全25% + 趋势强度20%。分数越高越值得配置。", range: "60-80 优质", warn: "< 35 需回避" },
        { name: "RPS (相对强度排名)", desc: "该行业ETF价格在全市场ETF中的相对强度排名位置。反映板块在同类中的涨幅表现。", range: "> 80 优秀", warn: "< 30 极弱，谨慎追入" },
        { name: "PE 分位 (估值百分位)", desc: "当前市盈率在过去5年中的百分位。低分位=便宜=安全边际高，高分位=昂贵=回撤风险大。", range: "20-60 合理", warn: "> 80 极贵，< 15 极便宜" },
        { name: "成交拥挤度", desc: "当日成交额与20日平均成交额的比值。衡量场内资金的拥挤程度，过高表示追涨情绪浓厚。", range: "0.8-1.5x 健康", warn: "> 2.0x 极度拥挤，追高危险" },
        { name: "热度分 (Heat Score)", desc: "资金关注度综合评分。成交放量比40% + 5日动量35% + 拥挤度修正25%。反映市场资金对该行业的关注热情。", range: "45-70 活跃", warn: "> 85 过热，可能见顶" },
        { name: "放量比 (Vol Ratio)", desc: "当日成交金额与20日均量的比值，>1表示放量。配合价格方向判断：放量上涨=强势，放量下跌=出货。", range: "0.8-1.5x", warn: "> 2.5x 可能见顶放量" },
        { name: "MA20 / MA60", desc: "20日/60日均线。站上MA20=短期趋势向好，站上MA60=中期趋势健康。MA20斜率向上=趋势加速。", range: "站上MA20+MA60 最佳", warn: "跌破MA60 → 中线止损" },
        { name: "5D / 20D 动量", desc: "近5日/20日的累计涨跌幅。正值=上涨趋势，负值=下跌趋势。20D动量更稳定，适合判断中期方向。", range: "5D +1~5% 健康", warn: "5D > +8% 短期过热" }
    ];

    // === 颜色工具 ===
    function gradeColor(grade) {
        return { A: '#10b981', B: '#3b82f6', C: '#64748b', D: '#f59e0b', F: '#ef4444' }[grade] || '#64748b';
    }
    function trendColor(v) { return v > 0 ? '#f87171' : (v < 0 ? '#34d399' : '#94a3b8'); }

    // === 初始化 ===
    async function initPage() {
        datePicker.value = new Date().toISOString().split('T')[0];
        initCharts();
        renderGlossary();
        initGlossaryToggle();
        await loadRotationMatrix();
        if (currentCode) loadIndustryDetail(currentCode);
    }

    function initCharts() {
        charts.rps = echarts.init(document.getElementById('gauge-rps'));
        charts.value = echarts.init(document.getElementById('gauge-value'));
        charts.risk = echarts.init(document.getElementById('gauge-risk'));
        charts.rsLine = echarts.init(document.getElementById('rs-line-chart'));
        charts.radar = echarts.init(document.getElementById('radar-chart'));
    }

    // === V3.0 指标百科 ===
    function renderGlossary() {
        const grid = document.getElementById('glossary-grid');
        grid.innerHTML = GLOSSARY.map(g => `
            <div class="glossary-item">
                <div class="glossary-item-header">
                    <span class="glossary-item-name">${g.name}</span>
                    <span class="glossary-item-range">${g.range}</span>
                </div>
                <div class="glossary-item-desc">${g.desc}</div>
                <div class="glossary-item-warn">⚠️ 警示: ${g.warn}</div>
            </div>
        `).join('');
    }

    function initGlossaryToggle() {
        const toggle = document.getElementById('glossary-toggle');
        const drawer = document.getElementById('glossary-drawer');
        const drawerOverlay = document.getElementById('glossary-overlay');
        const closeBtn = document.getElementById('glossary-close');

        // 首次访问闪烁提示
        if (!localStorage.getItem('alphacore_glossary_seen')) {
            toggle.classList.add('pulse-hint');
            setTimeout(() => {
                toggle.classList.remove('pulse-hint');
                localStorage.setItem('alphacore_glossary_seen', '1');
            }, 6000);
        }

        function openDrawer() { drawer.classList.add('open'); drawerOverlay.classList.add('open'); }
        function closeDrawer() { drawer.classList.remove('open'); drawerOverlay.classList.remove('open'); }

        toggle.addEventListener('click', openDrawer);
        closeBtn.addEventListener('click', closeDrawer);
        drawerOverlay.addEventListener('click', closeDrawer);
        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
    }

    // === V3.2 导航条渲染 (Alpha分数 + 排名奖牌) ===
    function renderSectorNav(rankData = []) {
        if (rankData.length > 0) {
            rankData.sort((a, b) => (b.alpha_score || 0) - (a.alpha_score || 0));
            if (!currentCode) currentCode = rankData[0]?.ts_code || rankData[0]?.code || SECTORS[0].code;
        }

        const orderedSectors = rankData.length > 0
            ? rankData.map(d => ({ code: d.ts_code || d.code, name: d.name }))
            : SECTORS;

        const rankMedals = ['🥇', '🥈', '🥉'];

        navContainer.innerHTML = orderedSectors.map((s, idx) => {
            const d = rankData.find(r => (r.ts_code === s.code || r.code === s.code)) || {};
            const trend = d.trend_5d || 0;
            const alpha = d.alpha_score || 0;
            const grade = d.alpha_grade || 'C';
            const heat = d.heat_score || 0;
            const gc = gradeColor(grade);
            const tc = trendColor(trend);
            const rankClass = idx < 3 ? `rank-top rank-${idx+1}` : '';
            const rankLabel = idx < 3 ? `${rankMedals[idx]}` : `#${idx+1}`;

            return `
                <div class="sector-tile ${s.code === currentCode ? 'active' : ''}" data-code="${s.code}" style="--tile-heat-color: ${gc};">
                    <span class="tile-rank ${rankClass}">${rankLabel}</span>
                    <div class="tile-alpha">
                        <span class="tile-alpha-score">${alpha.toFixed(0)}</span>
                        <span class="tile-grade grade-${grade}">${grade}</span>
                    </div>
                    <span class="tile-name">${s.name}</span>
                    <div class="tile-bottom">
                        <span class="tile-trend" style="color:${tc};">${trend > 0 ? '+' : ''}${trend.toFixed(1)}%</span>
                        <span class="tile-heat-label"><span class="tile-heat-dot"></span>${heat.toFixed(0)}</span>
                    </div>
                    <div class="tile-heat-bar"><div class="tile-heat-fill" style="width:${alpha}%; background:${gc};"></div></div>
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
                updateActiveCard();
                renderStrategyCard(code);
                loadIndustryDetail(code);
            });
        });
    }

    // === V3.0 Alpha Score 排行榜 ===
    function renderAlphaRanking(data) {
        const container = document.getElementById('alpha-ranking-list');
        const strongCount = data.filter(d => d.alpha_grade === 'A' || d.alpha_grade === 'B').length;
        document.getElementById('alpha-a-count').textContent = `${strongCount} 个强力`;

        container.innerHTML = data.map((d, idx) => {
            const gc = gradeColor(d.alpha_grade || 'C');
            const tc5 = trendColor(d.trend_5d);
            const tc20 = trendColor(d.ret_20d || 0);
            const code = d.ts_code || d.code;
            const circumference = 2 * Math.PI * 20;
            const offset = circumference - (circumference * (d.alpha_score || 0) / 100);
            const isActive = code === currentCode;

            // 风险警示标签
            const alertsHtml = (d.risk_alerts || []).map(a =>
                `<span class="risk-tag ${a.level}">${a.icon} ${a.text}</span>`
            ).join('');

            return `
                <div class="alpha-card grade-${d.alpha_grade || 'C'} ${isActive ? 'active-card' : ''}" data-code="${code}">
                    <div class="alpha-card-top">
                        <div class="alpha-card-info">
                            <span class="alpha-card-rank">#${idx+1}</span>
                            <span class="alpha-card-name">${d.name}</span>
                            <div class="alpha-card-trends">
                                <span style="color:${tc5};">${d.trend_5d > 0 ? '+' : ''}${d.trend_5d.toFixed(1)}%<small style="opacity:0.5">5D</small></span>
                                <span style="color:${tc20};">${(d.ret_20d||0) > 0 ? '+' : ''}${(d.ret_20d||0).toFixed(1)}%<small style="opacity:0.5">20D</small></span>
                            </div>
                        </div>
                        <div class="alpha-ring-wrap">
                            <svg viewBox="0 0 48 48">
                                <circle class="alpha-ring-bg" cx="24" cy="24" r="20" />
                                <circle class="alpha-ring-fill" cx="24" cy="24" r="20"
                                    stroke="${gc}"
                                    stroke-dasharray="${circumference}"
                                    stroke-dashoffset="${offset}" />
                            </svg>
                            <span class="alpha-ring-text">${(d.alpha_score||0).toFixed(0)}</span>
                            <span class="alpha-ring-grade" style="background:${gc};">${d.alpha_grade||'C'}</span>
                        </div>
                    </div>

                    <div class="alpha-factors">
                        <span class="alpha-factor-tag">🔥 热度 ${(d.heat_score||0).toFixed(0)}</span>
                        <span class="alpha-factor-tag">📊 放量 ${(d.vol_ratio||1).toFixed(1)}x</span>
                        <span class="alpha-factor-tag">📈 动量 ${(d.f_momentum||0).toFixed(0)}</span>
                        <span class="alpha-factor-tag">💰 PE ${(d.pe_percentile||50).toFixed(0)}%</span>
                        <span class="alpha-factor-tag">${d.trend_strength?.above_ma20 ? '✅' : '❌'} MA20</span>
                    </div>

                    <div class="alpha-strategy">
                        <div class="alpha-strat-row">
                            <span class="alpha-strat-icon">💡</span>
                            <span class="alpha-strat-text"><b>买入:</b> ${d.buy_strategy || '—'}</span>
                        </div>
                        <div class="alpha-strat-row">
                            <span class="alpha-strat-icon">🎯</span>
                            <span class="alpha-strat-text"><b>止盈:</b> ${d.take_profit || '—'}</span>
                        </div>
                    </div>

                    ${alertsHtml ? `<div class="risk-tags">${alertsHtml}</div>` : ''}

                    <div class="alpha-advice-row" style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:0.75rem; color:#94a3b8; font-style:italic;">${d.advice || ''}</span>
                        <span class="alpha-advice-label ${d.advice_action || 'neutral'}">${d.advice_label || ''}</span>
                    </div>
                </div>
            `;
        }).join('');

        // 卡片点击事件
        document.querySelectorAll('.alpha-card').forEach(card => {
            card.addEventListener('click', () => {
                const code = card.getAttribute('data-code');
                if (code === currentCode) return;
                currentCode = code;
                // 同步导航条
                document.querySelectorAll('.sector-tile').forEach(t => {
                    t.classList.toggle('active', t.getAttribute('data-code') === code);
                });
                updateActiveCard();
                renderStrategyCard(code);
                loadIndustryDetail(code);
            });
        });
    }

    function updateActiveCard() {
        document.querySelectorAll('.alpha-card').forEach(c => {
            c.classList.toggle('active-card', c.getAttribute('data-code') === currentCode);
        });
    }

    // === V3.1 因子进度条可视化 ===
    function renderFactorBars(d) {
        const factors = [
            { label: '热度', value: d.f_heat || 0, color: '#f87171', weight: '30%' },
            { label: '动量', value: d.f_momentum || 0, color: '#3b82f6', weight: '25%' },
            { label: '估值安全', value: d.f_valuation || 0, color: '#10b981', weight: '25%' },
            { label: '趋势', value: d.f_trend || 0, color: '#a78bfa', weight: '20%' }
        ];
        return factors.map(f => {
            const v = Math.min(100, Math.max(0, f.value));
            const opacity = v >= 60 ? 1 : 0.5;
            return `<div class="factor-bar-wrap">
                <span class="factor-bar-label">${f.label} <small style="opacity:0.5">${f.weight}</small></span>
                <div class="factor-bar-track">
                    <div class="factor-bar-fill" style="width:${v}%; background:${f.color}; opacity:${opacity};"></div>
                </div>
                <span class="factor-bar-value" style="color:${v>=60?f.color:'#64748b'}">${v.toFixed(0)}</span>
            </div>`;
        }).join('');
    }

    // === V3.1 策略操作卡 ===
    function renderStrategyCard(code) {
        const d = allSectorData.find(s => (s.ts_code === code || s.code === code));
        if (!d) return;

        const gc = gradeColor(d.alpha_grade || 'C');
        const badge = document.getElementById('soc-grade-badge');
        badge.textContent = `${d.alpha_grade || 'C'} · ${(d.alpha_score||0).toFixed(0)}分`;
        badge.className = `soc-grade-badge grade-${d.alpha_grade || 'C'}`;
        document.getElementById('soc-sector-name').textContent = `📋 ${d.name} · 投资策略`;
        document.getElementById('strategy-ops-card').style.setProperty('--grade-color', gc);

        const alerts = (d.risk_alerts || []).map(a =>
            `<li style="color:${a.level==='danger'?'#f87171':(a.level==='positive'?'#34d399':'#fbbf24')}">${a.icon} ${a.text}</li>`
        ).join('') || '<li style="color:#34d399">✅ 暂无风险警示</li>';

        document.getElementById('soc-body').innerHTML = `
            <div class="soc-fade-in">
            <div class="soc-section">
                <div class="soc-section-title buy">✅ 买入策略</div>
                <ul class="soc-content">
                    <li><b>触发条件:</b> Alpha评级达到B级(65分)以上 + 站上MA20</li>
                    <li><b>建仓方法:</b> ${d.buy_strategy || '—'}</li>
                    <li><b>仓位上限:</b> ${d.position_cap || '—'}</li>
                </ul>
            </div>
            <div class="soc-divider"></div>
            <div class="soc-section">
                <div class="soc-section-title profit">🎯 止盈策略</div>
                <ul class="soc-content">
                    <li>${d.take_profit || '—'}</li>
                </ul>
            </div>
            <div class="soc-divider"></div>
            <div class="soc-section">
                <div class="soc-section-title profit" style="color:#f59e0b;">🛑 止损策略</div>
                <ul class="soc-content">
                    <li>${d.stop_loss || '—'}</li>
                </ul>
            </div>
            <div class="soc-divider"></div>
            <div class="soc-section">
                <div class="soc-section-title risk">⚠️ 风险警示</div>
                <ul class="soc-content">${alerts}</ul>
            </div>
            <div style="margin-top:12px; padding:14px; border-radius:10px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04);">
                <div style="font-size:0.72rem; color:#64748b; margin-bottom:10px;">Alpha Score 因子拆解</div>
                ${renderFactorBars(d)}
            </div>
            </div>
        `;
    }

    // === V3.0 行业雷达图 (新增Alpha维度) ===
    function renderRadarChart(data) {
        if (!data || data.length === 0) return;
        const names = data.map(d => d.name);
        const alphaScores = data.map(d => d.alpha_score || 0);
        const heatScores = data.map(d => d.heat_score || 0);
        const momScores = data.map(d => d.f_momentum || 50);
        const peScores = data.map(d => 100 - (d.pe_percentile || 50));

        charts.radar.setOption({
            tooltip: {
                trigger: 'item',
                backgroundColor: 'rgba(10, 10, 10, 0.92)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#fff', fontSize: 12 }
            },
            legend: {
                data: ['Alpha综合', '资金热度', '价格动量', '估值安全'],
                textStyle: { color: '#94a3b8', fontSize: 11 },
                bottom: 10, icon: 'circle'
            },
            radar: {
                indicator: names.map(n => ({ name: n, max: 100 })),
                center: ['50%', '48%'],
                radius: '62%',
                shape: 'polygon',
                splitNumber: 4,
                axisName: { color: '#cbd5e1', fontSize: 11, fontWeight: 500 },
                nameGap: 10,
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                splitArea: { show: true, areaStyle: { color: ['rgba(59,130,246,0.02)', 'rgba(59,130,246,0.04)', 'rgba(59,130,246,0.06)', 'rgba(59,130,246,0.08)'] } },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
            },
            series: [{
                type: 'radar',
                data: [
                    {
                        value: alphaScores, name: 'Alpha综合',
                        lineStyle: { color: '#a78bfa', width: 2.5 },
                        areaStyle: { color: 'rgba(167, 139, 250, 0.15)' },
                        itemStyle: { color: '#a78bfa' }, symbol: 'circle', symbolSize: 5
                    },
                    {
                        value: heatScores, name: '资金热度',
                        lineStyle: { color: '#ef4444', width: 1.5 },
                        areaStyle: { color: 'rgba(239, 68, 68, 0.08)' },
                        itemStyle: { color: '#ef4444' }, symbol: 'circle', symbolSize: 4
                    },
                    {
                        value: momScores, name: '价格动量',
                        lineStyle: { color: '#3b82f6', width: 1.5 },
                        areaStyle: { color: 'rgba(59, 130, 246, 0.08)' },
                        itemStyle: { color: '#3b82f6' }, symbol: 'circle', symbolSize: 4
                    },
                    {
                        value: peScores, name: '估值安全',
                        lineStyle: { color: '#10b981', width: 1.5, type: 'dashed' },
                        areaStyle: { color: 'rgba(16, 185, 129, 0.06)' },
                        itemStyle: { color: '#10b981' }, symbol: 'diamond', symbolSize: 5
                    }
                ]
            }]
        });
    }

    // === ECharts 仪表盘配置 ===
    function getGaugeOption(name, value, color, unit = '') {
        return {
            series: [{
                type: 'gauge',
                startAngle: 180, endAngle: 0,
                radius: '95%',
                center: ['50%', '80%'],
                progress: { show: true, width: 10, itemStyle: { color: color, shadowBlur: 10, shadowColor: color } },
                axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(255,255,255,0.05)']] } },
                axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false },
                pointer: { show: false },
                detail: {
                    valueAnimation: true,
                    offsetCenter: [0, -10],
                    fontSize: 22,
                    fontWeight: '800',
                    color: '#fff',
                    fontFamily: 'Outfit',
                    formatter: `{value}${unit}`
                },
                data: [{ value: value }]
            }]
        };
    }

    // === 加载行业详情 ===
    async function loadIndustryDetail(code) {
        try {
            const res = await fetch(`/api/v1/industry-detail?code=${code}`);
            const result = await res.json();
            if (result.status === 'success') {
                const data = result.data;
                const m = data.metrics;

                charts.rps.setOption(getGaugeOption('RPS', m.rps, m.rps > 80 ? '#3b82f6' : '#94a3b8'));
                charts.value.setOption(getGaugeOption('Value', m.pe_percentile, m.pe_percentile > 70 ? '#ef4444' : (m.pe_percentile < 30 ? '#10b981' : '#f59e0b'), '%'));
                charts.risk.setOption(getGaugeOption('Risk', m.crowding, m.crowding > 1.5 ? '#ef4444' : '#6366f1', 'x'));

                const valFlow = document.getElementById('val-flow');
                valFlow.textContent = m.hsgt_flow;

                document.getElementById('desc-rps').innerHTML = `<span style="color:${m.rps > 80 ? '#3b82f6' : '#94a3b8'}">${m.rps > 80 ? "🔥 强势领涨" : "🛡️ 震荡蓄势"}</span>`;
                document.getElementById('desc-value').innerHTML = `<span style="color:${m.pe_percentile < 30 ? '#10b981' : (m.pe_percentile > 70 ? '#ef4444' : '#f59e0b')}">${m.pe_percentile < 30 ? "💎 极度低估" : (m.pe_percentile > 70 ? "⚠️ 估值偏高" : "⚖️ 合理区间")}</span>`;
                document.getElementById('desc-risk').innerHTML = `<span style="color:${m.crowding > 1.5 ? '#ef4444' : '#6366f1'}">${m.crowding > 1.5 ? "🚫 极其拥挤" : "✅ 筹码健康"}</span>`;

                // V3.1: 仪表盘动态风险边框
                const metricCards = document.querySelectorAll('.metric-row .metric-card');
                if (metricCards[0]) {
                    metricCards[0].classList.remove('metric-danger','metric-safe','metric-warn');
                    if (m.rps > 80) metricCards[0].classList.add('metric-safe');
                    else if (m.rps < 30) metricCards[0].classList.add('metric-danger');
                }
                if (metricCards[1]) {
                    metricCards[1].classList.remove('metric-danger','metric-safe','metric-warn');
                    if (m.pe_percentile > 70) metricCards[1].classList.add('metric-danger');
                    else if (m.pe_percentile < 30) metricCards[1].classList.add('metric-safe');
                    else metricCards[1].classList.add('metric-warn');
                }
                if (metricCards[2]) {
                    metricCards[2].classList.remove('metric-danger','metric-safe','metric-warn');
                    if (m.crowding > 1.5) metricCards[2].classList.add('metric-danger');
                    else if (m.crowding > 1.2) metricCards[2].classList.add('metric-warn');
                    else metricCards[2].classList.add('metric-safe');
                }

                // RS Line Chart
                charts.rsLine.setOption({
                    tooltip: { trigger: 'axis', backgroundColor: 'rgba(10,10,10,0.85)', borderColor: 'rgba(255,255,255,0.1)', textStyle: { color: '#fff' } },
                    grid: { top: 30, bottom: 30, left: 45, right: 20 },
                    xAxis: { type: 'category', data: data.chart_data.dates.map(d => d.substring(4)), axisLabel: { color: '#64748b', fontSize: 10 } },
                    yAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
                    legend: { data: ['中枢价格', '相对强度(RS)'], textStyle: { color: '#94a3b8', fontSize: 10 }, right: 0, icon: 'circle' },
                    series: [
                        { name: '中枢价格', type: 'line', data: data.chart_data.prices, itemStyle: { color: '#3b82f6' }, smooth: true, showSymbol: false, areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [{offset:0, color:'rgba(59,130,246,0.15)'},{offset:1, color:'transparent'}]) } },
                        { name: '相对强度(RS)', type: 'line', data: data.chart_data.relative_strength, itemStyle: { color: '#10b981' }, smooth: true, showSymbol: false }
                    ]
                });

                // 成分股列表
                const listEl = document.getElementById('list-constituents');
                listEl.innerHTML = m.constituents.map(c => `
                    <div class="constituent-item">
                        <span class="constituent-name">● ${c.name}</span>
                        <span class="constituent-weight">权重 ${c.weight}</span>
                    </div>
                `).join('');
            }
        } catch (err) { console.error('Detail load error:', err); }
    }

    // === 加载轮动矩阵 + Alpha 排行 ===
    async function loadRotationMatrix() {
        try {
            const res = await fetch('/api/v1/industry-tracking');
            const result = await res.json();
            if (result.status === 'success') {
                allSectorData = result.data.sector_heatmap;

                // V3.0: 渲染四大组件
                renderSectorNav(allSectorData);
                renderAlphaRanking(allSectorData);
                renderRadarChart(allSectorData);

                // 自动选中排名第一并渲染策略卡
                if (allSectorData.length > 0 && currentCode) {
                    renderStrategyCard(currentCode);
                }
            }
        } catch (err) { console.error('Rotation load error:', err); }
    }

    // === 同步数据 ===
    async function syncData() {
        if (!confirm("确定要同步全量产业情报？\n将触发 12 个核心 ETF 数据深度抓取，约需 10-20 秒。")) return;
        overlay.style.display = 'flex';
        try {
            const res = await fetch('/api/v1/sync/industry', { method: 'POST' });
            const result = await res.json();
            if (result.status === 'success') {
                alert("同步成功！最新数据已就绪。");
            } else {
                alert("同步完成，请刷新查看。");
            }
            await loadRotationMatrix();
            loadIndustryDetail(currentCode);
        } catch (err) {
            console.error("同步异常", err);
        } finally {
            overlay.style.display = 'none';
        }
    }

    syncBtn.addEventListener('click', syncData);
    initPage();
    window.addEventListener('resize', () => Object.values(charts).forEach(c => c && c.resize()));
});
