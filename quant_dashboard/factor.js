/**
 * AlphaCore Factor Research Terminal V4.0
 * 因子研究终端：科学评分 + 三档止盈 + 因子百科 + 健康监控 + 推理链
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

    let charts = { radar: null, ic: null, qAvg: null, qCum: null, gauge: null };
    let currentFactor = 'roe';
    let factorCache = {};

    // === 因子元数据 ===
    const FACTORS = [
        { key: 'roe', name: 'ROE', label: '净资产收益率', color: '#3b82f6' },
        { key: 'eps', name: 'EPS', label: '每股收益', color: '#10b981' },
        { key: 'netprofit_margin', name: '净利率', label: '销售净利率', color: '#8b5cf6' },
        { key: 'bps', name: 'BPS', label: '每股净资产', color: '#f59e0b' },
        { key: 'debt_to_assets', name: '负债率', label: '资产负债率', color: '#ef4444' },
    ];

    // === 评级配色 ===
    const GRADE_COLORS = {
        S: '#10b981', A: '#34d399', B: '#60a5fa',
        C: '#fbbf24', D: '#f97316', F: '#f87171'
    };
    const GRADE_LABELS = {
        S: '顶级因子', A: '优质因子', B: '可用因子',
        C: '边缘因子', D: '噪音因子', F: '无效因子'
    };

    // === 因子百科 (V4.0 新增) ===
    const FACTOR_WIKI = {
        roe: {
            name: 'ROE (净资产收益率)',
            definition: '净利润 ÷ 平均股东权益 × 100%',
            quant_meaning: '衡量公司用股东资金创造利润的效率，高ROE → 盈利能力强 → 理论上应获得超额收益',
            empirical: 'A股实证IC均值通常 0.01-0.03 (偏弱)，但多空价差常为正，长期有微弱Alpha',
            trap: '高杠杆也会放大ROE，需结合负债率交叉验证; 周期性行业ROE波动大'
        },
        eps: {
            name: 'EPS (每股收益)',
            definition: '净利润 ÷ 总股本',
            quant_meaning: '标准化的盈利指标，可跨公司比较。高EPS → 强现金流 → 市场偏好',
            empirical: 'A股实证IC通常 0.02-0.04，在消费/科技板块表现较好',
            trap: '一次性收益(如资产出售)会扭曲EPS; 不同行业EPS区间差异极大'
        },
        netprofit_margin: {
            name: '销售净利率',
            definition: '净利润 ÷ 营业收入 × 100%',
            quant_meaning: '衡量销售转化为利润的效率，高净利率 → 护城河深 → 抗风险能力强',
            empirical: 'A股实证IC通常 0.01-0.03，在高毛利行业(医药/软件)区分度更高',
            trap: '不同行业净利率天然差异大(银行2-3% vs 软件30%+)，建议行业内比较'
        },
        bps: {
            name: 'BPS (每股净资产)',
            definition: '(总资产 - 总负债) ÷ 总股本',
            quant_meaning: '价值因子的基石，低PB(=Price/BPS)→ 被低估 → 均值回归收益',
            empirical: 'A股实证BPS本身IC较弱，但PB(市净率)是最经典的价值因子之一',
            trap: 'BPS不反映无形资产价值(品牌/专利); 轻资产公司BPS低但可能很赚钱'
        },
        debt_to_assets: {
            name: '资产负债率',
            definition: '总负债 ÷ 总资产 × 100%',
            quant_meaning: '风险因子，高负债率 → 财务风险大 → 理论上低负债应获正超额收益(质量溢价)',
            empirical: 'A股实证IC通常为负(低负债组表现好)，需反转因子方向使用',
            trap: '金融行业天然高杠杆(85%+)，需剔除或行业中性化处理'
        }
    };

    // === 初始化 ===
    function init() {
        renderFactorNav();
        renderFactorWiki(currentFactor);
        initDrawer();
        initReasoningToggle();
        runBtn.addEventListener('click', () => runAnalysis(currentFactor));
        drawerRunBtn.addEventListener('click', () => {
            closeDrawer();
            currentFactor = document.getElementById('factor-select').value;
            highlightNav(currentFactor);
            runAnalysis(currentFactor);
        });
        runAnalysis('roe');
    }

    // === 因子百科渲染 (V4.0) ===
    function renderFactorWiki(factorKey) {
        const wiki = FACTOR_WIKI[factorKey];
        if (!wiki) return;
        document.getElementById('wiki-title').textContent = `📖 ${wiki.name}`;
        document.getElementById('wiki-content').innerHTML = `
            <div class="wiki-item">
                <div class="wiki-item-title">📐 定义</div>
                <div class="wiki-item-text">${wiki.definition}</div>
            </div>
            <div class="wiki-item">
                <div class="wiki-item-title">🔬 量化含义</div>
                <div class="wiki-item-text">${wiki.quant_meaning}</div>
            </div>
            <div class="wiki-item">
                <div class="wiki-item-title">📊 A股实证</div>
                <div class="wiki-item-text">${wiki.empirical}</div>
            </div>
            <div class="wiki-item">
                <div class="wiki-item-title">⚠️ 常见陷阱</div>
                <div class="wiki-item-text wiki-warn">${wiki.trap}</div>
            </div>
        `;
    }

    // 百科折叠
    document.getElementById('wiki-toggle-btn').addEventListener('click', () => {
        document.getElementById('wiki-card').classList.toggle('open');
    });

    // === 推理链折叠 ===
    function initReasoningToggle() {
        const toggle = document.getElementById('reasoning-toggle');
        const strip = document.getElementById('reasoning-strip');
        toggle.addEventListener('click', () => {
            strip.classList.toggle('open');
            toggle.classList.toggle('open');
        });
    }

    // === 因子导航条 ===
    function renderFactorNav() {
        factorNav.innerHTML = FACTORS.map(f => {
            const cached = factorCache[f.key];
            const grade = cached ? cached.grade : '—';
            const score = cached ? cached.alpha_score : null;
            const gradeClass = cached ? `grade-${cached.grade}` : '';
            return `
                <div class="factor-tile ${f.key === currentFactor ? 'active' : ''}"
                     data-factor="${f.key}" style="--tile-color: ${f.color};">
                    <div class="ft-header">
                        <span class="ft-name">${f.name}</span>
                        <span class="ft-grade ${gradeClass}">${grade}</span>
                    </div>
                    <div class="ft-stats">
                        <span class="ft-score" style="color: ${cached ? GRADE_COLORS[cached.grade] : '#64748b'}">
                            ${score !== null ? '★' + score : '—'}
                        </span>
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
                renderFactorWiki(key);
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
            showLoading('正在计算 Alpha Score V4.0...', 35);

            const response = await fetch('/api/v1/factor-analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();

            if (result.status === 'success') {
                showLoading('正在渲染终端矩阵...', 75);
                factorCache[factorKey] = result.data;
                renderFactorNav();
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
        if (!charts.gauge) charts.gauge = echarts.init(document.getElementById('alpha-gauge'));
        if (!charts.radar) charts.radar = echarts.init(document.getElementById('radar-chart'));
        if (!charts.ic) charts.ic = echarts.init(document.getElementById('ic-series-chart'));
        if (!charts.qAvg) charts.qAvg = echarts.init(document.getElementById('quantile-avg-chart'));
        if (!charts.qCum) charts.qCum = echarts.init(document.getElementById('quantile-cum-chart'));
    }

    // === 渲染结果 ===
    function renderResults(data) {
        renderAlphaGauge(data);
        renderMetrics(data);
        renderAdvice(data);
        renderHealthLamps(data);
        renderRadar(data);
        renderICChart(data);
        renderQuantileAvg(data);
        renderQuantileCum(data);
    }

    // --- Alpha Score 环形仪表 ---
    function renderAlphaGauge(data) {
        const score = data.alpha_score;
        const grade = data.grade;
        const color = GRADE_COLORS[grade] || '#94a3b8';

        const gradeEl = document.getElementById('asc-grade');
        gradeEl.textContent = `${grade} 级 · ${GRADE_LABELS[grade]}`;
        gradeEl.style.color = color;

        charts.gauge.setOption({
            backgroundColor: 'transparent',
            series: [{
                type: 'gauge',
                startAngle: 220,
                endAngle: -40,
                min: 0,
                max: 100,
                radius: '90%',
                progress: {
                    show: true,
                    width: 10,
                    roundCap: true,
                    itemStyle: { color: color }
                },
                pointer: { show: false },
                axisLine: {
                    lineStyle: { width: 10, color: [[1, 'rgba(255,255,255,0.06)']] }
                },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: { show: false },
                title: { show: false },
                detail: {
                    fontSize: 28,
                    fontWeight: 800,
                    fontFamily: 'Outfit',
                    color: color,
                    offsetCenter: [0, '10%'],
                    formatter: '{value}'
                },
                data: [{ value: score }]
            }]
        });
    }

    // --- 指标卡 V4.0 (带阈值条) ---
    function renderMetrics(data) {
        setMetric('m-ic-mean', data.ic_mean.toFixed(4),
            Math.abs(data.ic_mean) > 0.03 ? 'mc-good' : Math.abs(data.ic_mean) > 0.01 ? 'mc-warn' : 'mc-bad',
            'bar-ic', Math.min(100, Math.abs(data.ic_mean) / 0.05 * 100));

        setMetric('m-ir', data.ic_ir.toFixed(3),
            Math.abs(data.ic_ir) > 0.3 ? 'mc-good' : Math.abs(data.ic_ir) > 0.1 ? 'mc-warn' : 'mc-bad',
            'bar-ir', Math.min(100, Math.abs(data.ic_ir) / 0.5 * 100));

        setMetric('m-win-rate', (data.ic_win_rate * 100).toFixed(1) + '%',
            data.ic_win_rate > 0.55 ? 'mc-good' : data.ic_win_rate > 0.45 ? 'mc-warn' : 'mc-bad',
            'bar-win', Math.min(100, Math.max(0, (data.ic_win_rate - 0.4) / 0.3 * 100)));

        setMetric('m-mono', data.monotonicity.toFixed(2),
            data.monotonicity > 0.8 ? 'mc-good' : data.monotonicity > 0.5 ? 'mc-warn' : 'mc-bad',
            'bar-mono', data.monotonicity * 100);

        setMetric('m-stability', data.ic_stability.toFixed(2),
            (data.ic_stability > 0.7 && data.ic_stability < 1.3) ? 'mc-good' :
            (data.ic_stability > 0.5 && data.ic_stability < 1.5) ? 'mc-warn' : 'mc-bad',
            'bar-stab', Math.max(0, (1 - Math.abs(data.ic_stability - 1)) * 100));

        setMetric('m-ls-spread', (data.ls_spread * 10000).toFixed(1) + 'bp',
            data.ls_spread > 0.001 ? 'mc-good' : data.ls_spread >= 0 ? 'mc-warn' : 'mc-bad',
            'bar-ls', Math.min(100, Math.max(0, data.ls_spread / 0.005 * 100)));

        // 评级
        const gradeEl = document.getElementById('m-grade');
        gradeEl.textContent = data.grade;
        gradeEl.style.color = GRADE_COLORS[data.grade] || '#94a3b8';
    }

    function setMetric(id, value, cssClass, barId, barPct) {
        const el = document.getElementById(id);
        el.textContent = value;
        const card = el.closest('.metric-card');
        card.classList.remove('mc-good', 'mc-warn', 'mc-bad');
        if (cssClass) card.classList.add(cssClass);
        // 阈值条
        if (barId) {
            const bar = document.getElementById(barId);
            if (bar) {
                bar.style.width = Math.max(3, Math.min(100, barPct)) + '%';
            }
        }
    }

    // --- 交易建议卡 V4.0 ---
    function renderAdvice(data) {
        const adv = data.advice;
        if (!adv) return;

        // 信号
        const signalEl = document.getElementById('adv-signal');
        signalEl.textContent = adv.signal_label;
        signalEl.style.color = adv.signal_color;

        // 持有期 + 注释
        document.getElementById('adv-hold').textContent = adv.hold_period;
        const holdNote = document.getElementById('adv-hold-note');
        if (holdNote) holdNote.textContent = adv.hold_note || '';

        // 三档止盈 V4.0
        document.getElementById('adv-target-t2').textContent = '+' + parseFloat(adv.target_t2).toFixed(2) + '%';
        document.getElementById('adv-t1').textContent = 'T1 +' + parseFloat(adv.target_t1).toFixed(2) + '%';
        document.getElementById('adv-t2-badge').textContent = 'T2 +' + parseFloat(adv.target_t2).toFixed(2) + '%';
        document.getElementById('adv-t3').textContent = 'T3 +' + parseFloat(adv.target_t3).toFixed(2) + '%';

        // 止损
        document.getElementById('adv-stop').textContent = '-' + parseFloat(adv.stop_loss).toFixed(2) + '%';

        // 仓位
        document.getElementById('adv-position').textContent = adv.position_pct + '%';
        document.getElementById('adv-position').style.color = adv.position_pct > 0 ? '#60a5fa' : '#f87171';

        // 置信度
        document.getElementById('adv-confidence-val').textContent = adv.confidence + '%';
        document.getElementById('advice-confidence').textContent = `置信度: ${adv.confidence}%`;

        // 推理链 V4.0
        const reasoningText = document.getElementById('reasoning-text');
        if (adv.reasoning) {
            reasoningText.textContent = adv.reasoning;
        }

        // 风险提示
        const riskMsg = document.getElementById('risk-message');
        const riskText = document.getElementById('risk-text');
        const riskIcon = document.getElementById('risk-icon');
        const risks = adv.risks || [];

        if (risks.length > 0) {
            // V4.0: risks 是对象数组 {level, text}
            const textParts = risks.map(r => typeof r === 'string' ? r : r.text);
            riskText.textContent = textParts.join(' | ');

            const hasHighRisk = risks.some(r =>
                (r.level === 'danger') ||
                (typeof r === 'string' && (r.includes('失效') || r.includes('为负') || r.includes('不建议'))));
            const hasWarn = risks.some(r =>
                (r.level === 'warn') ||
                (typeof r === 'string' && (r.includes('不足') || r.includes('放大') || r.includes('低于'))));

            riskMsg.className = 'risk-message ' + (
                hasHighRisk ? 'risk-danger' :
                hasWarn ? 'risk-warn' : 'risk-ok'
            );
            riskIcon.textContent = hasHighRisk ? '🚨' : hasWarn ? '⚠️' : '✅';
        }
    }

    // --- 健康监控灯 V4.0 ---
    function renderHealthLamps(data) {
        const container = document.getElementById('health-lamps');
        const items = data.health_status || [];
        if (items.length === 0) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = items.map(item => `
            <div class="health-lamp" title="${item.detail || ''}">
                <span class="lamp-dot ${item.status}"></span>
                <span>${item.label}</span>
            </div>
        `).join('');
    }

    // --- 因子质量雷达图 ---
    function renderRadar(data) {
        const bd = data.score_breakdown || {};
        const color = GRADE_COLORS[data.grade] || '#94a3b8';

        charts.radar.setOption({
            backgroundColor: 'transparent',
            radar: {
                indicator: [
                    { name: 'IC强度', max: 100 },
                    { name: 'IR稳定', max: 100 },
                    { name: '胜率', max: 100 },
                    { name: '单调性', max: 100 },
                    { name: '时效性', max: 100 },
                    { name: '盈利力', max: 100 }
                ],
                shape: 'polygon',
                radius: '65%',
                axisName: { color: '#94a3b8', fontSize: 10 },
                splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.04)'] } },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
            },
            series: [{
                type: 'radar',
                symbol: 'circle',
                symbolSize: 5,
                data: [{
                    value: [
                        bd.ic_strength || 0, bd.ir_stability || 0, bd.win_rate || 0,
                        bd.monotonicity || 0, bd.decay_health || 0, bd.ls_profit || 0
                    ],
                    name: '因子画像',
                    lineStyle: { color: color, width: 2 },
                    itemStyle: { color: color },
                    areaStyle: { color: color, opacity: 0.15 }
                }]
            }]
        });
    }

    // --- IC 时间序列 (V4.0: 含 ±2σ 波动带) ---
    function renderICChart(data) {
        const dates = data.ic_series.dates;
        const values = data.ic_series.values;
        const icStd = data.ic_std || 0;
        const icMean = data.ic_mean || 0;

        const ma20 = values.map((_, i) => {
            if (i < 19) return null;
            const slice = values.slice(i - 19, i + 1);
            return slice.reduce((a, b) => a + b, 0) / 20;
        });

        // ±2σ 波动带 V4.0
        const upper2s = values.map(() => icMean + 2 * icStd);
        const lower2s = values.map(() => icMean - 2 * icStd);

        charts.ic.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0', fontSize: 12 }
            },
            legend: {
                data: ['Rank IC', 'MA20', '+2σ', '-2σ'],
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
                },
                {
                    name: '+2σ', type: 'line', data: upper2s,
                    showSymbol: false,
                    lineStyle: { color: 'rgba(239,68,68,0.3)', width: 1, type: 'dashed' },
                    z: 5
                },
                {
                    name: '-2σ', type: 'line', data: lower2s,
                    showSymbol: false,
                    lineStyle: { color: 'rgba(239,68,68,0.3)', width: 1, type: 'dashed' },
                    z: 5
                }
            ]
        });
    }

    // --- 分组收益柱状图 ---
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
                    text: `单调性: ${data.monotonicity.toFixed(2)}  |  Alpha Score: ${data.alpha_score}  |  ${data.grade}级`,
                    fill: data.monotonicity > 0.8 ? '#34d399' : data.monotonicity > 0.5 ? '#fbbf24' : '#f87171',
                    fontSize: 11, fontWeight: 700, fontFamily: 'Outfit'
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
