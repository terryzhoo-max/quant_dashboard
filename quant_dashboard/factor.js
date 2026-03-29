/**
 * AlphaCore Factor Research Terminal V2.0
 * 因子研究终端：快选导航 + 质量评级 + 多维可视化
 */
document.addEventListener('DOMContentLoaded', function () {
    // === DOM ===
    const runBtn = document.getElementById('run-btn');
    const drawerRunBtn = document.getElementById('drawer-run-btn');
    const configBtn = document.getElementById('config-btn');
    const configClose = document.getElementById('config-close');
    const configDrawer = document.getElementById('config-drawer');
    const configOverlay = document.getElementById('config-overlay');
    const overlay = document.getElementById('loading-overlay');
    const loadingStep = document.getElementById('loading-step');
    const loadingFill = document.getElementById('loading-fill');
    const factorNav = document.getElementById('factor-nav');

    let charts = { radar: null, ic: null, qAvg: null, qCum: null };
    let currentFactor = 'roe';
    let factorCache = {};  // 缓存已计算因子的结果

    // === 因子元数据 ===
    const FACTORS = [
        { key: 'roe', name: 'ROE', label: '净资产收益率', color: '#3b82f6' },
        { key: 'eps', name: 'EPS', label: '每股收益', color: '#10b981' },
        { key: 'netprofit_margin', name: '净利率', label: '销售净利率', color: '#8b5cf6' },
        { key: 'bps', name: 'BPS', label: '每股净资产', color: '#f59e0b' },
        { key: 'debt_to_assets', name: '负债率', label: '资产负债率', color: '#ef4444' },
    ];

    // === 初始化 ===
    function init() {
        renderFactorNav();
        initDrawer();
        runBtn.addEventListener('click', () => runAnalysis(currentFactor));
        drawerRunBtn.addEventListener('click', () => {
            closeDrawer();
            currentFactor = document.getElementById('factor-select').value;
            highlightNav(currentFactor);
            runAnalysis(currentFactor);
        });
        // 自动运行默认因子
        runAnalysis('roe');
    }

    // === 因子导航条 ===
    function renderFactorNav() {
        factorNav.innerHTML = FACTORS.map(f => {
            const cached = factorCache[f.key];
            const grade = cached ? cached.grade : '—';
            const ic = cached ? cached.ic_mean.toFixed(3) : '—';
            const gradeClass = cached ? `grade-${cached.grade}` : '';
            return `
                <div class="factor-tile ${f.key === currentFactor ? 'active' : ''}"
                     data-factor="${f.key}" style="--tile-color: ${f.color};">
                    <div class="ft-header">
                        <span class="ft-name">${f.name}</span>
                        <span class="ft-grade ${gradeClass}">${grade}</span>
                    </div>
                    <div class="ft-stats">
                        <span>IC: <span class="ft-ic">${ic}</span></span>
                        <span>${f.label}</span>
                    </div>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.factor-tile').forEach(tile => {
            tile.addEventListener('click', () => {
                const key = tile.dataset.factor;
                if (key === currentFactor && factorCache[key]) return;
                currentFactor = key;
                document.getElementById('factor-select').value = key;
                highlightNav(key);
                runAnalysis(key);
            });
        });
    }

    function highlightNav(key) {
        document.querySelectorAll('.factor-tile').forEach(t => {
            t.classList.toggle('active', t.dataset.factor === key);
        });
    }

    // === 配置抽屉 ===
    function initDrawer() {
        configBtn.addEventListener('click', openDrawer);
        configClose.addEventListener('click', closeDrawer);
        configOverlay.addEventListener('click', closeDrawer);
        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
    }
    function openDrawer() {
        configDrawer.classList.add('open');
        configOverlay.classList.add('open');
    }
    function closeDrawer() {
        configDrawer.classList.remove('open');
        configOverlay.classList.remove('open');
    }

    // === 运行分析 ===
    async function runAnalysis(factorKey) {
        const payload = {
            factor_name: factorKey,
            stock_pool: document.getElementById('pool-select').value,
            start_date: document.getElementById('start-date').value,
            end_date: document.getElementById('end-date').value
        };

        showLoading('正在加载横截面数据...', 10);
        initCharts();

        try {
            showLoading('正在计算 Rank-IC 分布...', 35);

            const response = await fetch('/api/v1/factor-analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();

            if (result.status === 'success') {
                showLoading('正在渲染图表矩阵...', 75);
                factorCache[factorKey] = result.data;
                renderFactorNav(); // 更新导航条缓存数据
                highlightNav(factorKey);

                await new Promise(r => setTimeout(r, 200));
                showLoading('完成!', 100);
                renderResults(result.data);
            } else {
                alert('分析失败: ' + result.message);
            }
        } catch (err) {
            alert('请求异常: ' + err.message);
        } finally {
            setTimeout(() => hideLoading(), 400);
        }
    }

    // === 加载进度 ===
    function showLoading(step, pct) {
        overlay.style.display = 'flex';
        loadingStep.textContent = step;
        loadingFill.style.width = pct + '%';
    }
    function hideLoading() {
        overlay.style.display = 'none';
        loadingFill.style.width = '0%';
    }

    // === ECharts 初始化 ===
    function initCharts() {
        if (!charts.radar) charts.radar = echarts.init(document.getElementById('radar-chart'));
        if (!charts.ic) charts.ic = echarts.init(document.getElementById('ic-series-chart'));
        if (!charts.qAvg) charts.qAvg = echarts.init(document.getElementById('quantile-avg-chart'));
        if (!charts.qCum) charts.qCum = echarts.init(document.getElementById('quantile-cum-chart'));
    }

    // === 渲染结果 ===
    function renderResults(data) {
        renderMetrics(data);
        renderRadar(data);
        renderICChart(data);
        renderQuantileAvg(data);
        renderQuantileCum(data);
    }

    // --- 指标卡 ---
    function renderMetrics(data) {
        const gradeColors = {
            A: '#34d399', B: '#60a5fa', C: '#94a3b8', D: '#fbbf24', F: '#f87171'
        };
        const gradeLabels = {
            A: '精英因子', B: '可用因子', C: '边缘因子', D: '噪音因子', F: '无效因子'
        };

        // 评级
        const gradeEl = document.getElementById('m-grade');
        gradeEl.textContent = data.grade;
        gradeEl.style.color = gradeColors[data.grade] || '#94a3b8';
        document.getElementById('m-grade-label').textContent = gradeLabels[data.grade] || '—';

        // IC均值
        setMetric('m-ic-mean', data.ic_mean.toFixed(4),
            Math.abs(data.ic_mean) > 0.03 ? 'mc-good' : Math.abs(data.ic_mean) > 0.01 ? 'mc-warn' : 'mc-bad');

        // IR
        setMetric('m-ir', data.ic_ir.toFixed(3),
            Math.abs(data.ic_ir) > 0.5 ? 'mc-good' : Math.abs(data.ic_ir) > 0.2 ? 'mc-warn' : 'mc-bad');

        // IC胜率
        setMetric('m-win-rate', (data.ic_win_rate * 100).toFixed(1) + '%',
            data.ic_win_rate > 0.55 ? 'mc-good' : data.ic_win_rate > 0.45 ? 'mc-warn' : 'mc-bad');

        // 单调性
        setMetric('m-mono', data.monotonicity.toFixed(2),
            data.monotonicity > 0.8 ? 'mc-good' : data.monotonicity > 0.5 ? 'mc-warn' : 'mc-bad');

        // IC稳定性
        setMetric('m-stability', data.ic_stability.toFixed(2),
            (data.ic_stability > 0.7 && data.ic_stability < 1.3) ? 'mc-good' : 'mc-warn');

        // 多空价差
        setMetric('m-ls-spread', (data.ls_spread * 10000).toFixed(1) + 'bp',
            data.ls_spread > 0 ? 'mc-good' : 'mc-bad');

        // 样本量
        document.getElementById('m-samples').textContent = data.ic_series.dates.length;
    }

    function setMetric(id, value, cssClass) {
        const el = document.getElementById(id);
        el.textContent = value;
        const card = el.closest('.metric-card');
        card.classList.remove('mc-good', 'mc-warn', 'mc-bad');
        if (cssClass) card.classList.add(cssClass);
    }

    // --- 因子质量雷达图 ---
    function renderRadar(data) {
        const ic_score = Math.min(100, Math.abs(data.ic_mean) / 0.06 * 100);
        const ir_score = Math.min(100, Math.abs(data.ic_ir) / 0.8 * 100);
        const win_score = Math.min(100, data.ic_win_rate / 0.75 * 100);
        const mono_score = data.monotonicity * 100;
        const stab_score = Math.min(100, Math.max(0, (1 - Math.abs(data.ic_stability - 1)) * 100));

        const gradeColors = {
            A: '#34d399', B: '#60a5fa', C: '#94a3b8', D: '#fbbf24', F: '#f87171'
        };
        const color = gradeColors[data.grade] || '#94a3b8';

        charts.radar.setOption({
            backgroundColor: 'transparent',
            radar: {
                indicator: [
                    { name: 'IC强度', max: 100 },
                    { name: 'IR稳定', max: 100 },
                    { name: '胜率', max: 100 },
                    { name: '单调性', max: 100 },
                    { name: '时效性', max: 100 }
                ],
                shape: 'polygon',
                radius: '68%',
                axisName: { color: '#94a3b8', fontSize: 11 },
                splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.04)'] } },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
            },
            series: [{
                type: 'radar',
                symbol: 'circle',
                symbolSize: 5,
                data: [{
                    value: [ic_score, ir_score, win_score, mono_score, stab_score],
                    name: '因子画像',
                    lineStyle: { color: color, width: 2 },
                    itemStyle: { color: color },
                    areaStyle: { color: color, opacity: 0.15 }
                }]
            }]
        });
    }

    // --- IC 时间序列 (面积图) ---
    function renderICChart(data) {
        const dates = data.ic_series.dates;
        const values = data.ic_series.values;

        // 计算 MA20
        const ma20 = values.map((_, i) => {
            if (i < 19) return null;
            const slice = values.slice(i - 19, i + 1);
            return slice.reduce((a, b) => a + b, 0) / 20;
        });

        charts.ic.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0', fontSize: 12 }
            },
            legend: {
                data: ['Rank IC', 'MA20'],
                textStyle: { color: '#64748b', fontSize: 11 },
                top: 0, right: 10
            },
            grid: { top: 30, bottom: 30, left: 45, right: 15 },
            xAxis: {
                type: 'category', data: dates,
                axisLabel: { color: '#475569', fontSize: 10, interval: Math.floor(dates.length / 6) },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            series: [
                {
                    name: 'Rank IC', type: 'bar', data: values, barMaxWidth: 3,
                    itemStyle: {
                        color: function (p) {
                            return p.value >= 0
                                ? 'rgba(16,185,129,0.7)'
                                : 'rgba(239,68,68,0.7)';
                        }
                    }
                },
                {
                    name: 'MA20', type: 'line', data: ma20,
                    smooth: true, showSymbol: false,
                    lineStyle: { color: '#f59e0b', width: 2 },
                    z: 10
                }
            ]
        });
    }

    // --- 分组收益柱状图 (渐变色) ---
    function renderQuantileAvg(data) {
        const qData = data.quantile_rets;
        const gradientColors = ['#475569', '#64748b', '#3b82f6', '#10b981', '#f59e0b'];

        charts.qAvg.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0' },
                formatter: p => `${p[0].name}<br/>平均5日收益: <b>${p[0].value}%</b>`
            },
            grid: { top: 50, bottom: 40, left: 50, right: 20 },
            xAxis: {
                type: 'category',
                data: qData.quantiles,
                axisLabel: { color: '#94a3b8', fontSize: 12, fontWeight: 600 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { formatter: '{value}%', color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            graphic: [{
                type: 'text',
                left: 'center', top: 10,
                style: {
                    text: `单调性: ${data.monotonicity.toFixed(2)}`,
                    fill: data.monotonicity > 0.8 ? '#34d399' : data.monotonicity > 0.5 ? '#fbbf24' : '#f87171',
                    fontSize: 12, fontWeight: 700, fontFamily: 'Outfit'
                }
            }],
            series: [{
                name: '平均收益', type: 'bar',
                data: qData.avg_rets.map((v, i) => ({
                    value: (v * 100).toFixed(3),
                    itemStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: gradientColors[i] || '#3b82f6' },
                            { offset: 1, color: 'rgba(15,23,42,0.8)' }
                        ]),
                        borderRadius: [4, 4, 0, 0]
                    }
                })),
                barWidth: '50%',
                label: {
                    show: true, position: 'top',
                    formatter: '{c}%', color: '#94a3b8', fontSize: 11,
                    fontFamily: 'Outfit'
                }
            }]
        });
    }

    // --- 分组累计收益曲线 ---
    function renderQuantileCum(data) {
        const qData = data.quantile_rets;
        const lineColors = ['#475569', '#64748b', '#3b82f6', '#10b981', '#f59e0b'];

        const cumSeries = qData.cum_rets.series.map((s, i) => ({
            name: `Q${i + 1}`,
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: s.map(v => (v * 100).toFixed(2)),
            lineStyle: { width: i === 0 || i === qData.cum_rets.series.length - 1 ? 2.5 : 1.5, color: lineColors[i] },
            itemStyle: { color: lineColors[i] },
            areaStyle: i === qData.cum_rets.series.length - 1
                ? { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(245,158,11,0.12)' }, { offset: 1, color: 'transparent' }]) }
                : null,
            z: i === 0 || i === qData.cum_rets.series.length - 1 ? 10 : 5
        }));

        charts.qCum.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0', fontSize: 11 }
            },
            legend: {
                data: qData.cum_rets.series.map((_, i) => `Q${i + 1}`),
                textStyle: { color: '#64748b', fontSize: 11 },
                top: 0
            },
            grid: { top: 35, bottom: 30, left: 50, right: 15 },
            xAxis: {
                type: 'category',
                data: qData.cum_rets.dates,
                axisLabel: { color: '#475569', fontSize: 10, interval: Math.floor(qData.cum_rets.dates.length / 6) },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { formatter: '{value}%', color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            series: cumSeries
        });
    }

    // === resize ===
    window.addEventListener('resize', () => {
        Object.values(charts).forEach(c => c && c.resize());
    });

    // === 启动 ===
    init();
});
