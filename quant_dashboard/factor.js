/**
 * AlphaCore Factor Research Terminal V5.0
 * 因子研究终端：8维因子池 · IC分布直方图 · 衰减趋势 · 雷达叠加 · Premium视觉
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

    let charts = { radar: null, ic: null, qAvg: null, qCum: null, gauge: null, histogram: null, decay: null };
    let currentFactor = 'roe';
    let factorCache = {};

    // === V5.0 因子元数据 (8因子 + 分组) ===
    const FACTORS = [
        // 基本面
        { key: 'roe', name: 'ROE', label: '净资产收益率', color: '#3b82f6', group: 'fundamental' },
        { key: 'eps', name: 'EPS', label: '每股收益', color: '#10b981', group: 'fundamental' },
        { key: 'netprofit_margin', name: '净利率', label: '销售净利率', color: '#8b5cf6', group: 'fundamental' },
        { key: 'bps', name: 'BPS', label: '每股净资产', color: '#f59e0b', group: 'fundamental' },
        { key: 'debt_to_assets', name: '负债率', label: '资产负债率', color: '#ef4444', group: 'fundamental' },
        // 技术面
        { key: 'momentum_20d', name: '动量', label: '20日价格动量', color: '#06b6d4', group: 'technical' },
        { key: 'volatility_20d', name: '波动率', label: '20日波动率', color: '#f472b6', group: 'technical' },
        { key: 'turnover_rate', name: '换手率', label: '换手率比', color: '#a78bfa', group: 'technical' },
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

    // === 因子百科 V5.0 ===
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
        },
        momentum_20d: {
            name: '20日动量',
            definition: '当前价格 ÷ 20日前价格 - 1',
            quant_meaning: '捕捉短期价格趋势，正动量 → 趋势延续假说 → 动量溢价',
            empirical: 'A股实证IC通常 0.02-0.05，在趋势市(牛市)中表现优异，震荡市中失效',
            trap: '动量反转风险: 极端高动量个股可能面临均值回归; 需结合止损使用'
        },
        volatility_20d: {
            name: '20日波动率',
            definition: '日收益率的20日滚动标准差 × √252 (年化)',
            quant_meaning: '低波动异常现象: 低波动股票长期跑赢高波动股票 (与CAPM矛盾)',
            empirical: 'A股实证IC为负 (低波动组表现好)，是稳健的防御因子',
            trap: '低波时期波动率区分力下降; 行业偏差大(银行低波 vs 科技高波)'
        },
        turnover_rate: {
            name: '换手率比',
            definition: '当日成交量 ÷ 20日均成交量',
            quant_meaning: '市场关注度/拥挤度代理，异常放量可能预示趋势变化或见顶',
            empirical: 'A股实证IC波动大，短期有效但不稳定。高换手常伴随高波动',
            trap: '新股/次新股天然高换手; 除权除息日成交量异常; 需结合价格趋势判断'
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

    // === 因子百科渲染 ===
    function renderFactorWiki(factorKey) {
        const wiki = FACTOR_WIKI[factorKey];
        if (!wiki) return;
        document.getElementById('wiki-title').textContent = `📖 ${wiki.name}`;
        document.getElementById('wiki-content').innerHTML = `
            <div class="ft-wiki-item">
                <div class="ft-wiki-item-title">📐 定义</div>
                <div class="ft-wiki-item-text">${wiki.definition}</div>
            </div>
            <div class="ft-wiki-item">
                <div class="ft-wiki-item-title">🔬 量化含义</div>
                <div class="ft-wiki-item-text">${wiki.quant_meaning}</div>
            </div>
            <div class="ft-wiki-item">
                <div class="ft-wiki-item-title">📊 A股实证</div>
                <div class="ft-wiki-item-text">${wiki.empirical}</div>
            </div>
            <div class="ft-wiki-item">
                <div class="ft-wiki-item-title">⚠️ 常见陷阱</div>
                <div class="ft-wiki-item-text warn">${wiki.trap}</div>
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

    // === V5.0 因子导航条 (带分组分隔符) ===
    function renderFactorNav() {
        let html = '';
        let lastGroup = '';
        const groupLabels = { fundamental: '基本面', technical: '技术面' };

        FACTORS.forEach(f => {
            // 新分组时插入分隔符
            if (f.group !== lastGroup && lastGroup !== '') {
                html += `<div class="ft-nav-divider"></div>`;
                html += `<div class="ft-nav-group-label">${groupLabels[f.group] || ''}</div>`;
            } else if (lastGroup === '') {
                html += `<div class="ft-nav-group-label">${groupLabels[f.group] || ''}</div>`;
            }
            lastGroup = f.group;

            const cached = factorCache[f.key];
            const grade = cached ? cached.grade : '—';
            const score = cached ? cached.alpha_score : null;
            const gradeClass = cached ? `grade-${cached.grade}` : '';

            html += `
                <div class="ft-tile ${f.key === currentFactor ? 'active' : ''}"
                     data-factor="${f.key}" style="--tile-color: ${f.color};">
                    <div class="ft-tile-header">
                        <span class="ft-tile-name">${f.name}</span>
                        <span class="ft-tile-grade ${gradeClass}">${grade}</span>
                    </div>
                    <div class="ft-tile-stats">
                        <span class="ft-tile-score" style="color: ${cached ? GRADE_COLORS[cached.grade] : '#64748b'}">
                            ${score !== null ? '★' + score : '—'}
                        </span>
                        <span>${f.label}</span>
                    </div>
                </div>
            `;
        });

        factorNav.innerHTML = html;

        document.querySelectorAll('.ft-tile').forEach(tile => {
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
        document.querySelectorAll('.ft-tile').forEach(t => {
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
            showLoading('正在计算 Alpha Score V5.0...', 35);

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

                // V5.0: 渲染数据新鲜度
                if (result.data_freshness) {
                    renderFreshness(result.data_freshness);
                }

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
        overlay.classList.add('show');
        loadingStep.textContent = step;
        loadingFill.style.width = pct + '%';
    }
    function hideLoading() {
        overlay.style.display = 'none';
        overlay.classList.remove('show');
        loadingFill.style.width = '0%';
    }

    // === V5.0: 数据新鲜度渲染 ===
    function renderFreshness(info) {
        const badge = document.getElementById('data-freshness-badge');
        const text = document.getElementById('freshness-text');
        if (!badge || !text) return;

        const daily = info.daily_latest || 'N/A';
        const isStale = info.is_stale;
        const staleDays = info.stale_days || 0;

        // 格式化日期: 20250328 → 2025-03-28
        let dateStr = daily;
        if (daily.length === 8) {
            dateStr = daily.slice(0, 4) + '-' + daily.slice(4, 6) + '-' + daily.slice(6, 8);
        }

        badge.classList.remove('fresh', 'stale');
        if (isStale) {
            badge.classList.add('stale');
            text.textContent = `⚠️ 数据过期 ${staleDays}天 · ${dateStr}`;
            badge.title = `日线最新: ${dateStr} | 财务最新: ${info.fina_latest || 'N/A'} | 下次分析时将自动同步`;
        } else {
            badge.classList.add('fresh');
            text.textContent = `数据: ${dateStr}`;
            badge.title = `日线最新: ${dateStr} | 财务最新: ${info.fina_latest || 'N/A'} | 每日15:35自动更新`;
        }
    }

    // === ECharts 初始化 ===
    function initCharts() {
        if (!charts.gauge) charts.gauge = AC.registerChart(echarts.init(document.getElementById('alpha-gauge')));
        if (!charts.radar) charts.radar = AC.registerChart(echarts.init(document.getElementById('radar-chart')));
        if (!charts.ic) charts.ic = AC.registerChart(echarts.init(document.getElementById('ic-series-chart')));
        if (!charts.qAvg) charts.qAvg = AC.registerChart(echarts.init(document.getElementById('quantile-avg-chart')));
        if (!charts.qCum) charts.qCum = AC.registerChart(echarts.init(document.getElementById('quantile-cum-chart')));
        if (!charts.histogram) charts.histogram = AC.registerChart(echarts.init(document.getElementById('ic-histogram-chart')));
        if (!charts.decay) charts.decay = AC.registerChart(echarts.init(document.getElementById('ic-decay-chart')));
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
        renderICHistogram(data);
        renderICDecay(data);

        // V5.0: 更新Alpha卡呼吸色
        const color = GRADE_COLORS[data.grade] || '#3b82f6';
        document.getElementById('alpha-score-card').style.setProperty(
            '--alpha-glow', color.replace(')', ',0.15)').replace('rgb', 'rgba')
        );
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
                startAngle: 220, endAngle: -40,
                min: 0, max: 100, radius: '90%',
                progress: {
                    show: true, width: 10, roundCap: true,
                    itemStyle: { color: color }
                },
                pointer: { show: false },
                axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(255,255,255,0.06)']] } },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: { show: false },
                title: { show: false },
                detail: {
                    fontSize: 28, fontWeight: 800, fontFamily: 'Outfit',
                    color: color, offsetCenter: [0, '10%'], formatter: '{value}'
                },
                data: [{ value: score }]
            }]
        });
    }

    // --- 指标卡 ---
    function renderMetrics(data) {
        setMetric('m-ic-mean', data.ic_mean.toFixed(4),
            Math.abs(data.ic_mean) > 0.03 ? 'mc-good' : Math.abs(data.ic_mean) > 0.01 ? 'mc-warn' : 'mc-bad');

        setMetric('m-ir', data.ic_ir.toFixed(3),
            Math.abs(data.ic_ir) > 0.3 ? 'mc-good' : Math.abs(data.ic_ir) > 0.1 ? 'mc-warn' : 'mc-bad');

        setMetric('m-win-rate', (data.ic_win_rate * 100).toFixed(1) + '%',
            data.ic_win_rate > 0.55 ? 'mc-good' : data.ic_win_rate > 0.45 ? 'mc-warn' : 'mc-bad');

        setMetric('m-mono', data.monotonicity.toFixed(2),
            data.monotonicity > 0.8 ? 'mc-good' : data.monotonicity > 0.5 ? 'mc-warn' : 'mc-bad');

        setMetric('m-stability', data.ic_stability.toFixed(2),
            (data.ic_stability > 0.7 && data.ic_stability < 1.3) ? 'mc-good' :
            (data.ic_stability > 0.5 && data.ic_stability < 1.5) ? 'mc-warn' : 'mc-bad');

        setMetric('m-ls-spread', (data.ls_spread * 10000).toFixed(1) + 'bp',
            data.ls_spread > 0.001 ? 'mc-good' : data.ls_spread >= 0 ? 'mc-warn' : 'mc-bad');

        const gradeEl = document.getElementById('m-grade');
        gradeEl.textContent = data.grade;
        gradeEl.style.color = GRADE_COLORS[data.grade] || '#94a3b8';
    }

    function setMetric(id, value, cssClass) {
        const el = document.getElementById(id);
        el.textContent = value;
        const card = el.closest('.ft-metric');
        card.classList.remove('mc-good', 'mc-warn', 'mc-bad');
        if (cssClass) card.classList.add(cssClass);
    }

    // --- 交易建议 ---
    function renderAdvice(data) {
        const adv = data.advice;
        if (!adv) return;

        const signalEl = document.getElementById('adv-signal');
        signalEl.textContent = adv.signal_label;
        signalEl.style.color = adv.signal_color;
        // V5.0: 信号脉冲
        signalEl.classList.toggle('signal-strong',
            adv.signal === 'STRONG_BUY' || adv.signal === 'AVOID');

        document.getElementById('adv-hold').textContent = adv.hold_period;
        const holdNote = document.getElementById('adv-hold-note');
        if (holdNote) holdNote.textContent = adv.hold_note || '';

        document.getElementById('adv-target-t2').textContent = '+' + parseFloat(adv.target_t2).toFixed(2) + '%';
        document.getElementById('adv-t1').textContent = 'T1 +' + parseFloat(adv.target_t1).toFixed(2) + '%';
        document.getElementById('adv-t2-badge').textContent = 'T2 +' + parseFloat(adv.target_t2).toFixed(2) + '%';
        document.getElementById('adv-t3').textContent = 'T3 +' + parseFloat(adv.target_t3).toFixed(2) + '%';
        document.getElementById('adv-stop').textContent = '-' + parseFloat(adv.stop_loss).toFixed(2) + '%';
        document.getElementById('adv-position').textContent = adv.position_pct + '%';
        document.getElementById('adv-position').style.color = adv.position_pct > 0 ? '#60a5fa' : '#f87171';
        document.getElementById('adv-confidence-val').textContent = adv.confidence + '%';
        document.getElementById('advice-confidence').textContent = `置信度: ${adv.confidence}%`;

        if (adv.reasoning) {
            document.getElementById('reasoning-text').textContent = adv.reasoning;
        }

        // Risk
        const riskMsg = document.getElementById('risk-message');
        const riskText = document.getElementById('risk-text');
        const riskIcon = document.getElementById('risk-icon');
        const risks = adv.risks || [];

        if (risks.length > 0) {
            const textParts = risks.map(r => typeof r === 'string' ? r : r.text);
            riskText.textContent = textParts.join(' | ');

            const hasHigh = risks.some(r =>
                (r.level === 'danger') ||
                (typeof r === 'string' && (r.includes('失效') || r.includes('为负'))));
            const hasWarn = risks.some(r =>
                (r.level === 'warn') ||
                (typeof r === 'string' && (r.includes('不足') || r.includes('放大'))));

            riskMsg.className = 'ft-risk-msg ' + (
                hasHigh ? 'risk-danger' : hasWarn ? 'risk-warn' : 'risk-ok'
            );
            riskIcon.textContent = hasHigh ? '🚨' : hasWarn ? '⚠️' : '✅';
        }
    }

    // --- 健康灯 ---
    function renderHealthLamps(data) {
        const container = document.getElementById('health-lamps');
        const items = data.health_status || [];
        if (!items.length) { container.innerHTML = ''; return; }
        container.innerHTML = items.map(item => `
            <div class="ft-lamp" title="${item.detail || ''}">
                <span class="ft-lamp-dot ${item.status}"></span>
                <span>${item.label}</span>
            </div>
        `).join('');
    }

    // --- 雷达图 (V5.0: 支持叠加已缓存因子) ---
    function renderRadar(data) {
        const bd = data.score_breakdown || {};
        const color = GRADE_COLORS[data.grade] || '#94a3b8';

        // 收集已缓存因子用于叠加对比
        const seriesData = [];
        const currentKey = currentFactor;

        // 当前因子 (实线 + 填充)
        seriesData.push({
            value: [
                bd.ic_strength || 0, bd.ir_stability || 0, bd.win_rate || 0,
                bd.monotonicity || 0, bd.decay_health || 0, bd.ls_profit || 0
            ],
            name: FACTORS.find(f => f.key === currentKey)?.name || currentKey,
            lineStyle: { color: color, width: 2.5 },
            itemStyle: { color: color },
            areaStyle: { color: color, opacity: 0.15 }
        });

        // 叠加其他已缓存因子 (虚线, 无填充)
        Object.keys(factorCache).forEach(key => {
            if (key === currentKey) return;
            const cached = factorCache[key];
            const cbd = cached.score_breakdown || {};
            const cColor = FACTORS.find(f => f.key === key)?.color || '#64748b';
            seriesData.push({
                value: [
                    cbd.ic_strength || 0, cbd.ir_stability || 0, cbd.win_rate || 0,
                    cbd.monotonicity || 0, cbd.decay_health || 0, cbd.ls_profit || 0
                ],
                name: FACTORS.find(f => f.key === key)?.name || key,
                lineStyle: { color: cColor, width: 1.5, type: 'dashed' },
                itemStyle: { color: cColor },
                areaStyle: null
            });
        });

        charts.radar.setOption({
            backgroundColor: 'transparent',
            legend: {
                show: seriesData.length > 1,
                data: seriesData.map(s => s.name),
                textStyle: { color: '#64748b', fontSize: 10 },
                bottom: 0
            },
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
                radius: seriesData.length > 1 ? '55%' : '65%',
                axisName: { color: '#94a3b8', fontSize: 10 },
                splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.04)'] } },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
            },
            series: [{
                type: 'radar',
                symbol: 'circle',
                symbolSize: 4,
                data: seriesData
            }]
        });
    }

    // --- IC 时间序列 ---
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
                textStyle: { color: '#64748b', fontSize: 10 },
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
                            return p.value >= 0 ? 'rgba(16,185,129,0.7)' : 'rgba(239,68,68,0.7)';
                        }
                    }
                },
                {
                    name: 'MA20', type: 'line', data: ma20,
                    smooth: true, showSymbol: false,
                    lineStyle: { color: '#f59e0b', width: 2 }, z: 10
                },
                {
                    name: '+2σ', type: 'line', data: upper2s,
                    showSymbol: false,
                    lineStyle: { color: 'rgba(239,68,68,0.3)', width: 1, type: 'dashed' }, z: 5
                },
                {
                    name: '-2σ', type: 'line', data: lower2s,
                    showSymbol: false,
                    lineStyle: { color: 'rgba(239,68,68,0.3)', width: 1, type: 'dashed' }, z: 5
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
            grid: { top: 50, bottom: 35, left: 50, right: 20 },
            xAxis: {
                type: 'category', data: qData.quantiles,
                axisLabel: { color: '#94a3b8', fontSize: 12, fontWeight: 600 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { formatter: '{value}%', color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            graphic: [{
                type: 'text', left: 'center', top: 10,
                style: {
                    text: `单调性: ${data.monotonicity.toFixed(2)}  |  Alpha: ${data.alpha_score}  |  ${data.grade}级`,
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
                    formatter: '{c}%', color: '#94a3b8', fontSize: 11, fontFamily: 'Outfit'
                }
            }]
        });
    }

    // --- 分组累计收益曲线 ---
    function renderQuantileCum(data) {
        const qData = data.quantile_rets;
        const lineColors = ['#475569', '#64748b', '#3b82f6', '#10b981', '#f59e0b'];

        const cumSeries = qData.cum_rets.series.map((s, i) => ({
            name: `Q${i + 1}`, type: 'line', smooth: true, showSymbol: false,
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
                textStyle: { color: '#64748b', fontSize: 11 }, top: 0
            },
            grid: { top: 35, bottom: 30, left: 50, right: 15 },
            xAxis: {
                type: 'category', data: qData.cum_rets.dates,
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

    // === V5.0 新增: IC 分布直方图 ===
    function renderICHistogram(data) {
        const dist = data.ic_distribution || {};
        const hist = dist.histogram || {};
        const bins = hist.bins || [];
        const counts = hist.counts || [];
        const mean = hist.mean || 0;
        const std = hist.std || 0;

        if (!bins.length) {
            charts.histogram.setOption({
                backgroundColor: 'transparent',
                graphic: [{
                    type: 'text', left: 'center', top: 'center',
                    style: { text: '暂无IC分布数据', fill: '#475569', fontSize: 13 }
                }]
            });
            return;
        }

        charts.histogram.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0', fontSize: 11 },
                formatter: p => `IC: ${p[0].name}<br/>频次: <b>${p[0].value}</b>`
            },
            grid: { top: 45, bottom: 35, left: 50, right: 20 },
            graphic: [{
                type: 'text', left: 'center', top: 8,
                style: {
                    text: `偏度: ${dist.skewness}  |  峰度: ${dist.kurtosis}  |  μ=${mean}  σ=${std}`,
                    fill: (Math.abs(dist.skewness) < 1 && dist.kurtosis < 5) ? '#34d399' : '#fbbf24',
                    fontSize: 10.5, fontWeight: 600, fontFamily: 'Outfit'
                }
            }],
            xAxis: {
                type: 'category',
                data: bins.map(b => b.toFixed(3)),
                axisLabel: { color: '#475569', fontSize: 9, rotate: 30 },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#475569', fontSize: 10 },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            series: [
                {
                    type: 'bar', data: counts.map((c, i) => ({
                        value: c,
                        itemStyle: {
                            color: bins[i] >= 0
                                ? 'rgba(16,185,129,0.6)'
                                : 'rgba(239,68,68,0.6)',
                            borderRadius: [2, 2, 0, 0]
                        }
                    })),
                    barWidth: '70%'
                },
                {
                    // 均值线
                    type: 'line',
                    markLine: {
                        silent: true,
                        symbol: 'none',
                        data: [{
                            name: 'IC均值',
                            xAxis: bins.reduce((p, b, i) =>
                                Math.abs(b - mean) < Math.abs(bins[p] - mean) ? i : p, 0),
                            lineStyle: { color: '#f59e0b', width: 2, type: 'dashed' },
                            label: {
                                formatter: `μ=${mean}`,
                                color: '#f59e0b', fontSize: 10, fontFamily: 'Outfit'
                            }
                        }]
                    },
                    data: []
                }
            ]
        });
    }

    // === V5.0 新增: IC 衰减趋势图 ===
    function renderICDecay(data) {
        const rolling = data.ic_rolling || {};
        const dates = rolling.dates || [];
        const rollingMean = rolling.rolling_mean || [];
        const rollingWR = rolling.rolling_win_rate || [];

        if (!dates.length) {
            charts.decay.setOption({
                backgroundColor: 'transparent',
                graphic: [{
                    type: 'text', left: 'center', top: 'center',
                    style: { text: '暂无衰减趋势数据', fill: '#475569', fontSize: 13 }
                }]
            });
            return;
        }

        charts.decay.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0', fontSize: 11 }
            },
            legend: {
                data: ['滚动IC均值', '滚动胜率'],
                textStyle: { color: '#64748b', fontSize: 10 },
                top: 0, right: 10
            },
            grid: { top: 35, bottom: 30, left: 50, right: 50 },
            xAxis: {
                type: 'category', data: dates,
                axisLabel: { color: '#475569', fontSize: 9, interval: Math.floor(dates.length / 6) },
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
            },
            yAxis: [
                {
                    type: 'value', name: 'IC',
                    axisLabel: { color: '#475569', fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
                    nameTextStyle: { color: '#64748b', fontSize: 10 }
                },
                {
                    type: 'value', name: '胜率',
                    min: 0, max: 1,
                    axisLabel: { formatter: v => (v * 100).toFixed(0) + '%', color: '#475569', fontSize: 10 },
                    splitLine: { show: false },
                    nameTextStyle: { color: '#64748b', fontSize: 10 }
                }
            ],
            series: [
                {
                    name: '滚动IC均值', type: 'line', smooth: true, showSymbol: false,
                    data: rollingMean,
                    lineStyle: { color: '#3b82f6', width: 2 },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(59,130,246,0.15)' },
                            { offset: 1, color: 'transparent' }
                        ])
                    },
                    yAxisIndex: 0
                },
                {
                    name: '滚动胜率', type: 'line', smooth: true, showSymbol: false,
                    data: rollingWR,
                    lineStyle: { color: '#f59e0b', width: 2, type: 'dashed' },
                    yAxisIndex: 1
                },
                {
                    // 50% 参考线
                    type: 'line', yAxisIndex: 1,
                    markLine: {
                        silent: true, symbol: 'none',
                        data: [{
                            yAxis: 0.5,
                            lineStyle: { color: 'rgba(239,68,68,0.3)', width: 1, type: 'dotted' },
                            label: { formatter: '50%', color: '#ef4444', fontSize: 9, position: 'end' }
                        }]
                    },
                    data: []
                }
            ]
        });
    }

    // resize 由 AC (alphacore_utils.js) 统一管理

    // === 启动 ===
    init();
});
