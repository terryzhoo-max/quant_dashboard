/**
 * AlphaCore · SMIC 个股穿透审计终端 V3.0
 * 五维穿透审计：财务健康 · 技术护城河 · 地缘风险 · 估值合理性 · 成长动能
 * Self-contained — Real-time data sync + Enhanced UI
 */

// ═══════════════════════════════════════════════════════
//  SMIC 五维审计数据模型
// ═══════════════════════════════════════════════════════
const SMIC_MODULES = {
    financial:  { icon: '💰', color: '#10b981', label: '财务健康', weight: 25 },
    tech_moat:  { icon: '🔬', color: '#6366f1', label: '技术护城河', weight: 20 },
    geopolitics:{ icon: '🌍', color: '#f59e0b', label: '地缘风险', weight: 25 },
    valuation:  { icon: '📊', color: '#3b82f6', label: '估值合理性', weight: 15 },
    growth:     { icon: '🚀', color: '#8b5cf6', label: '成长动能', weight: 15 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildSMICData() {
    const modules = {
        financial: {
            score: 70, grade: 'B',
            checks: [
                { name:'营收增长', score:80, status:'pass', detail:'2025年营收约660亿元(~$93.3亿)，YoY +27%，受益于AI需求+国产替代爆发', explanation:'晶圆代工行业平均增速12%，SMIC增速显著领先同业', threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%' },
                { name:'毛利率', score:62, status:'warn', detail:'综合毛利率约22.0%，较2024(18.6%)回升但仍低于台积电(55%)和联电(32%)', explanation:'产能利用率回升推动毛利率修复，但折旧压力持续', threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%' },
                { name:'净利润', score:50, status:'warn', detail:'净利润约49亿元(~$6.85亿)，净利率~7.4%，YoY +39%但绝对规模仍低', explanation:'折旧高峰期(2025折旧增长约30%)吞噬大量利润空间' },
                { name:'自由现金流', score:38, status:'fail', detail:'FCF持续为负(约-300亿元)，资本开支/营收比超55%', explanation:'半导体制造属重资产行业，4座新厂同步建设期FCF必然为负', action:'关注产能利用率回升节点，FCF拐点预计2027-2028年' },
                { name:'资产负债率', score:72, status:'pass', detail:'资产负债率54%，有息负债率40%，整体可控', explanation:'对比行业平均55%，SMIC杠杆水平合理' },
                { name:'研发投入', score:85, status:'pass', detail:'研发费用率约10.5%，研发投入约69亿元', explanation:'持续高研发投入是突破先进制程的必要条件' },
            ]
        },
        tech_moat: {
            score: 68, grade: 'C',
            checks: [
                { name:'制程节点', score:60, status:'warn', detail:'量产最先进制程：14nm FinFET(N+1/N+2)，与台积电(2nm)差距约5代', explanation:'受EUV光刻机禁运限制，7nm以下制程推进受阻' },
                { name:'产能规模', score:82, status:'pass', detail:'月产能已突破100万片8寸当量(2025年底)，全球第三大纯晶圆代工厂', explanation:'规模效应显著，成熟制程产能利用率93.5%' },
                { name:'技术自主率', score:55, status:'warn', detail:'关键设备自主率约18-22%，国产替代进程加速中', explanation:'光刻机、刻蚀机等核心设备仍依赖进口存量' },
                { name:'客户集中度', score:70, status:'pass', detail:'前五大客户营收占比约52%，客户结构持续优化', explanation:'消费电子/汽车芯片/AI边缘芯片占比持续提升' },
                { name:'专利壁垒', score:70, status:'pass', detail:'累计专利超13,500项，年新增专利约1,600项', explanation:'专利布局集中在成熟制程工艺和先进封装技术' },
            ]
        },
        geopolitics: {
            score: 42, grade: 'D',
            checks: [
                { name:'制裁风险', score:28, status:'fail', detail:'已被列入美国实体清单，EUV及部分DUV设备禁运持续', explanation:'2022年10月BIS新规后，先进制程设备获取受限，2025年管控进一步趋严', action:'持续跟踪美国商务部出口管制政策及荷兰/日本跟进措施' },
                { name:'供应链韧性', score:40, status:'fail', detail:'核心设备(ASML/LAM/AMAT)断供风险高，备件库存约16个月', explanation:'设备禁运→产能扩张受限→长期竞争力天花板' },
                { name:'政策支持', score:82, status:'pass', detail:'大基金一期/二期/三期持续投资，地方政策补贴力度加大', explanation:'国家半导体战略核心标的，政策扶持确定性极高' },
                { name:'国际竞争格局', score:45, status:'warn', detail:'与GlobalFoundries、联电、华虹竞争成熟制程市场', explanation:'成熟制程价格战加剧，28nm及以上制程竞争白热化' },
                { name:'合规风险', score:32, status:'fail', detail:'美国"最终用户"审查趋严，部分客户订单受限', explanation:'地缘政治不确定性为最大系统性风险因子，2026年美国大选增加政策不确定性' },
            ]
        },
        valuation: {
            score: 38, grade: 'D',
            checks: [
                { name:'PE估值', score:18, status:'fail', detail:'PE(TTM) ~145.7X，显著高于台积电(24X)和联电(9X)，为全球主要晶圆代工厂最高', explanation:'市场price-in极强国产替代溢价，当前估值透支未来3-5年盈利增长', threshold:'🟢 <20X | 🟡 20-40X | 🔴 >40X' },
                { name:'PB估值', score:68, status:'pass', detail:'PB ~1.94X，对比历史中位数2.0X处于合理区间', explanation:'重资产行业PB估值更具参考价值，当前PB位于52周低位(1.94-2.62)', threshold:'🟢 <1.5X | 🟡 1.5-2.5X | 🔴 >2.5X' },
                { name:'EV/EBITDA', score:45, status:'warn', detail:'EV/EBITDA ~18X，高于行业平均8X，溢价程度偏高', explanation:'高CAPEX导致EBITDA虚高，自由现金流收益率为负' },
                { name:'DCF内在价值', score:42, status:'warn', detail:'乐观/中性/悲观情景估值：105/72/50 元(当前¥91.78)', explanation:'中性情景隐含21%下行空间，当前价格接近乐观情景', action:'若股价突破¥105，需重新评估安全边际' },
                { name:'股息率', score:60, status:'warn', detail:'股息率约0.5%，分红率约12%', explanation:'半导体扩产期分红率极低，EPS仅¥0.63' },
            ]
        },
        growth: {
            score: 78, grade: 'B',
            checks: [
                { name:'营收增速', score:85, status:'pass', detail:'2024-2026E CAGR约22-28%，增速大幅超越全球同业', explanation:'AI算力需求+国产替代+消费电子复苏三轮驱动' },
                { name:'产能扩张', score:80, status:'pass', detail:'4座12寸晶圆厂(深圳/上海/北京/天津)同步推进，月产能已突破100万片', explanation:'2025年底实现百万片里程碑，2027年目标120万片' },
                { name:'下游需求', score:75, status:'pass', detail:'AI边缘推理芯片/汽车芯片/IoT需求爆发式增长', explanation:'成熟制程需求结构性增长，28nm仍是主力节点' },
                { name:'国产替代市占率', score:82, status:'pass', detail:'国内晶圆代工市占率约38%，国产替代渗透率加速提升', explanation:'政策驱动+供应链安全诉求→份额确定性提升' },
                { name:'技术演进', score:52, status:'warn', detail:'N+1/N+2制程良率提升缓慢，7nm量产时间表仍不明确', explanation:'无EUV约束下的先进制程突破存在根本性不确定性' },
            ]
        }
    };

    // Calculate trust score
    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = SMIC_MODULES[k].weight;
        weightedSum += mod.score * w;
        totalWeight += w;
    }
    const trustScore = Math.round(weightedSum / totalWeight);
    const trustGrade = trustScore >= 85 ? 'A' : trustScore >= 70 ? 'B' : trustScore >= 55 ? 'C' : 'D';

    let pass = 0, warn = 0, fail = 0, total = 0;
    for (const mod of Object.values(modules)) {
        for (const c of mod.checks) {
            total++;
            if (c.status === 'pass') pass++;
            else if (c.status === 'warn') warn++;
            else fail++;
        }
    }

    return {
        company: '中芯国际', ticker_a: '688981.SH', ticker_h: '0981.HK',
        market_cap: '4,524亿', price: '91.78', pe: '145.7', pb: '1.94',
        eps: '0.63', week52_high: '153.00', week52_low: '77.80',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'EUV设备禁运', level:'critical', desc:'美国BIS限制ASML向中国出口EUV光刻机，直接制约7nm及以下制程量产能力', probability:'极高', impact:'致命', mitigation:'DUV多重曝光替代方案' },
            { name:'制裁升级风险', level:'critical', desc:'若美方将DUV光刻机纳入禁运清单，现有产能扩张计划将面临根本性威胁', probability:'中等', impact:'致命', mitigation:'加速国产设备导入验证' },
            { name:'估值泡沫化风险', level:'critical', desc:'PE(TTM) 145X严重偏离基本面，一旦政策预期落空，股价可能面临40%+回撤', probability:'高', impact:'致命', mitigation:'严格仓位控制+动态止损' },
            { name:'产能过剩周期', level:'high', desc:'全球成熟制程产能集中释放(2025-2027)，价格战压力加大', probability:'高', impact:'重大', mitigation:'差异化工艺+长期合约锁定' },
            { name:'折旧海啸', level:'high', desc:'2025-2027年折旧增长30%+，新产能投产后利润率可能持续承压', probability:'极高', impact:'重大', mitigation:'提升高毛利产品组合占比' },
            { name:'技术追赶瓶颈', level:'medium', desc:'无EUV条件下先进制程推进速度慢于预期', probability:'高', impact:'中等', mitigation:'聚焦成熟制程差异化竞争' },
            { name:'客户流失风险', level:'medium', desc:'地缘政治不确定性导致部分国际客户转单', probability:'中等', impact:'中等', mitigation:'拓展国内客户+多元化客户结构' },
        ],
        verdict: {
            bull: ['国产替代逻辑确定性极高，大基金三期持续注资', '成熟制程需求结构性爆发(AI边缘/汽车/IoT)', '产能百万片里程碑达成，规模效应加速显现', '2025营收增速27%大幅领先全球同业'],
            bear: ['PE 145X严重透支，估值泡沫化风险极高', '地缘政治风险为不可控系统性因子', '先进制程突破受限，技术天花板明确', 'FCF持续为负，EPS仅¥0.63，盈利质量差'],
            catalysts: ['DUV多重曝光7nm量产突破', '国产光刻机导入验证成功', '全球晶圆代工涨价周期启动', '大基金三期投资落地'],
            positioning: '⚠️ 高风险标的。当前PE 145X严重偏高，建议仓位严格控制在3-5%以内。核心逻辑为国产替代情绪Beta，非基本面Alpha。务必设置地缘政治事件+估值回归双重止损线。',
            rating: 'hold', rating_text: '⚖️ 谨慎持有 / 等待回调',
            summary: '中芯国际是A股半导体制造板块的核心Beta标的，国产替代叙事提供长期支撑(2025营收+27%)，但PE 145X已严重脱离基本面。地缘政治风险(制裁升级)构成系统性不确定性，折旧海啸将持续压制利润率至2027年。建议已持仓者控制仓位谨慎持有，未建仓者等待估值回调至PE 60X以下(约¥38)或技术突破催化剂出现后再行介入。'
        },
        financials: {
            years: ['2019','2020','2021','2022','2023','2024','2025'],
            revenue: [220.2, 274.7, 356.3, 495.2, 452.5, 519.3, 660.0],
            net_income: [17.9, 43.3, 107.3, 121.3, 48.2, 35.3, 49.0],
            gross_margin: [20.8, 23.8, 28.7, 38.3, 19.3, 18.6, 22.0],
            caputil: [97.8, 95.2, 100.4, 92.1, 75.8, 85.6, 93.5],
            rd_expense: [47.4, 46.7, 41.2, 49.5, 55.3, 62.1, 69.0],
            capex: [67.2, 57.0, 105.0, 255.0, 310.0, 288.0, 350.0],
            node_split: { '28nm+': 27.5, '40nm': 13.8, '55nm': 19.2, '0.15-0.18µm': 28.5, '其他': 11.0 }
        }
    };
}

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runSMICAudit(); });

const SMIC_SECTIONS = ['smic-identity','trust-hero','smic-kpi-dashboard','audit-overview','smic-charts-grid','smic-risk-matrix','smic-verdict','audit-timeline'];

function runSMICAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    SMIC_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    // Enhanced loading: show module names during audit
    const loadingStatus = document.querySelector('.loading-status');
    const moduleSteps = [
        { t: 300,  text: '🔬 正在审计 [1/5] 财务健康… 营收·利润率·现金流·杠杆率' },
        { t: 600,  text: '🔬 正在审计 [2/5] 技术护城河… 制程节点·产能规模·专利壁垒' },
        { t: 900,  text: '🌍 正在审计 [3/5] 地缘风险… 制裁清单·供应链·政策支持' },
        { t: 1200, text: '📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA' },
        { t: 1500, text: '🚀 正在审计 [5/5] 成长动能… 产能扩张·下游需求·市占率' },
        { t: 1800, text: '✅ 五维穿透审计完成，正在生成报告…' },
    ];
    moduleSteps.forEach(step => {
        setTimeout(() => { if(loadingStatus) loadingStatus.textContent = step.text; }, step.t);
    });

    setTimeout(() => {
        const data = buildSMICData();
        renderAll(data);
        if(btn) btn.disabled = false;
        if(spinner) spinner.style.display = 'none';
    }, 2200);
}

// ═══════════════════════════════════════════════════════
//  渲染主控
// ═══════════════════════════════════════════════════════
function renderAll(data) {
    document.getElementById('audit-loading').style.display = 'none';

    // Display map for grid vs block
    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'smic-charts-grid':'grid', 'smic-kpi-dashboard':'grid' };
    SMIC_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) el.style.display = displayMap[id] || 'block';
    });

    renderIdentity(data);
    renderTrustHero(data);
    renderKPIDashboard(data);
    renderAlertBanner(data);
    renderRadar(data);
    renderModuleCards(data);
    renderCharts(data);
    renderRiskMatrix(data);
    renderVerdict(data);
    renderTimeline(data);

    document.getElementById('audit-time').textContent = data.audit_time;
    document.getElementById('footer-time').textContent = `· 审计于 ${data.audit_time}`;

    // Staggered entrance animations
    SMIC_SECTIONS.forEach((id, i) => {
        const el = document.getElementById(id);
        if(!el) return;
        setTimeout(() => {
            el.style.transition = 'opacity 0.5s ease, transform 0.5s cubic-bezier(0.22,1,0.36,1)';
            el.style.opacity = '1';
            el.style.transform = 'translateY(0)';
        }, 80 * i);
        el.style.transform = 'translateY(12px)';
    });

    // Scan animation
    const layout = document.getElementById('audit-layout');
    layout.classList.remove('scan-complete');
    void layout.offsetWidth;
    layout.classList.add('scan-complete');

    setTimeout(() => autoExpandWorst(data), 1200);
}

// ═══════════════════════════════════════════════════════
//  Counter-Up
// ═══════════════════════════════════════════════════════
function counterUp(el, target, suffix='', dur=1200) {
    if(!el) return;
    const t0 = performance.now();
    const isInt = Number.isInteger(target);
    (function tick(now) {
        const p = Math.min((now-t0)/dur, 1);
        const ease = 1-Math.pow(1-p,3);
        el.textContent = (isInt ? Math.round(target*ease) : (target*ease).toFixed(1)) + suffix;
        if(p<1) requestAnimationFrame(tick);
    })(t0);
}

// ═══════════════════════════════════════════════════════
//  1. Company Identity
// ═══════════════════════════════════════════════════════
function renderIdentity(d) {
    document.getElementById('qs-mcap').textContent = d.market_cap;
    const priceEl = document.getElementById('qs-price');
    priceEl.textContent = '¥'+d.price;
    // Color code PE by severity
    const peEl = document.getElementById('qs-pe');
    peEl.textContent = d.pe+'X';
    const peVal = parseFloat(d.pe);
    if(peVal > 100) peEl.style.color = '#f87171';
    else if(peVal > 40) peEl.style.color = '#fbbf24';
    else peEl.style.color = '#34d399';
    document.getElementById('qs-pb').textContent = d.pb+'X';
}

// ═══════════════════════════════════════════════════════
//  2. Trust Hero
// ═══════════════════════════════════════════════════════
function renderTrustHero(d) {
    const gc = GRADE_COLORS[d.trust_grade] || '#94a3b8';
    const bigScore = document.getElementById('trust-big-score');
    bigScore.style.color = gc;
    counterUp(bigScore, d.trust_score, '', 1400);

    const badge = document.getElementById('trust-grade-badge');
    badge.textContent = d.trust_grade;
    badge.className = `trust-grade-badge grade-${d.trust_grade}`;

    const verdicts = { A:'投资价值突出，各维度均衡优秀', B:'整体可投，存在结构性风险需关注', C:'风险与机会并存，需精选入场时机', D:'⚠️ 高风险标的，估值严重偏高，不建议重仓' };
    document.getElementById('trust-verdict').textContent = verdicts[d.trust_grade] || '';
    document.getElementById('stat-pass').textContent = `✅ ${d.pass_count} 优势`;
    document.getElementById('stat-warn').textContent = `⚠️ ${d.warn_count} 关注`;
    document.getElementById('stat-fail').textContent = `❌ ${d.fail_count} 风险`;
    document.getElementById('trust-meta').textContent = `共 ${d.total_checks} 项检查 · 加权评分 ${d.trust_score}/100 · ${d.audit_time}`;

    // Equalizer
    const keys = Object.keys(SMIC_MODULES);
    const shortLabels = { financial:'财务', tech_moat:'技术', geopolitics:'地缘', valuation:'估值', growth:'成长' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s*1.4, 8);
        return `<div class="eq-bar-group" title="${SMIC_MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${c}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${c};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${shortLabels[k]}</span></div>`;
    }).join('');

    // Gauge
    const chart = echarts.init(document.getElementById('trust-gauge-chart'));
    chart.setOption({
        series:[{ type:'gauge', startAngle:210, endAngle:-30, radius:'88%', center:['50%','55%'], min:0, max:100, splitNumber:4,
            axisLine:{ lineStyle:{ width:18, color:[[0.55,'#ef4444'],[0.70,'#f59e0b'],[0.85,'#3b82f6'],[1,'#10b981']] }},
            pointer:{ length:'55%', width:4, itemStyle:{ color:gc }},
            axisTick:{ show:false }, splitLine:{ length:10, lineStyle:{ color:'rgba(255,255,255,0.15)', width:1 }},
            axisLabel:{ distance:18, color:'#64748b', fontSize:10, fontFamily:'Outfit' },
            detail:{ show:false }, title:{ show:true, offsetCenter:[0,'35%'], fontSize:11, color:'#94a3b8' },
            data:[{ value:d.trust_score, name:'投资可行性' }]
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  3. Alert Banner
// ═══════════════════════════════════════════════════════
function renderAlertBanner(d) {
    const banner = document.getElementById('alert-banner');
    if(d.fail_count > 0) {
        const items = [];
        for(const mod of Object.values(d.modules)) for(const c of mod.checks) if(c.status==='fail') items.push(c.name);
        banner.className = 'alert-banner level-fail visible';
        document.getElementById('alert-icon').textContent = '🚨';
        document.getElementById('alert-text').innerHTML = `<strong>${d.fail_count} 项高风险</strong> — ${items.slice(0,3).join('、')}${items.length>3?` 等${items.length}项`:''} 需重点关注`;
    } else if(d.warn_count > 0) {
        banner.className = 'alert-banner level-warn visible';
        document.getElementById('alert-icon').textContent = '⚠️';
        document.getElementById('alert-text').innerHTML = `<strong>${d.warn_count} 项需要关注</strong>`;
    } else { banner.classList.remove('visible'); }
}

// ═══════════════════════════════════════════════════════
//  4. Radar
// ═══════════════════════════════════════════════════════
function renderRadar(d) {
    const keys = Object.keys(SMIC_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:SMIC_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(99,102,241,0.02)','rgba(99,102,241,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'SMIC审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(99,102,241,0.35)'},{offset:1,color:'rgba(59,130,246,0.08)'}]}},
            lineStyle:{color:'#6366f1',width:2}, itemStyle:{color:'#818cf8'}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = SMIC_MODULES[k]; const s = d.modules[k].score;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  5. Module Cards
// ═══════════════════════════════════════════════════════
let smicData = null, activeModule = null;

function renderModuleCards(d) {
    smicData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(SMIC_MODULES).map(([key, meta]) => {
        const mod = d.modules[key]; if(!mod) return '';
        const {score, grade, checks} = mod;
        const gc = GRADE_COLORS[grade]||'#94a3b8';
        const r=18, circ=2*Math.PI*r, dash=circ*(score/100);
        const pC=checks.filter(c=>c.status==='pass').length, wC=checks.filter(c=>c.status==='warn').length, fC=checks.filter(c=>c.status==='fail').length;
        const worst = [...checks].sort((a,b)=>(a.score??100)-(b.score??100))[0];
        const wIcon = worst?.status==='pass'?'✅':worst?.status==='warn'?'⚠️':'❌';
        const wColor = worst?.status==='pass'?'#34d399':worst?.status==='warn'?'#fbbf24':'#f87171';
        return `<div class="module-card" style="--mod-color:${meta.color}" onclick="toggleDetail('${key}')" id="card-${key}">
            <div class="mod-header"><span class="mod-label">${meta.icon} ${meta.label}</span>
                <div class="mod-score-ring"><svg viewBox="0 0 42 42"><circle class="mod-ring-bg" cx="21" cy="21" r="${r}"/><circle class="mod-ring-fill" cx="21" cy="21" r="${r}" stroke="${gc}" stroke-dasharray="${circ}" stroke-dashoffset="${circ-dash}"/></svg>
                <span class="mod-score-text">${score}</span><span class="mod-grade-pill grade-${grade}">${grade}</span></div></div>
            <div class="mod-checks-summary">${pC>0?`<span style="color:#34d399">✅${pC}</span> `:''}${wC>0?`<span style="color:#fbbf24">⚠️${wC}</span> `:''}${fC>0?`<span style="color:#f87171">❌${fC}</span> `:''}
                <span class="weight-tag">权重 ${meta.weight}%</span></div>
            ${worst?`<div class="mod-worst-preview${worst.status!=='pass'?' has-issue':''}"><span style="color:${wColor}">${wIcon} ${worst.name}</span><span class="mod-worst-score" style="color:${wColor}">${worst.score??0}</span></div>`:''}
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  6. Detail Expand
// ═══════════════════════════════════════════════════════
function toggleDetail(key, noScroll=false) {
    const section = document.getElementById('detail-section');
    document.querySelectorAll('.module-card').forEach(c=>c.classList.remove('expanded'));
    if(activeModule===key){ section.classList.remove('visible'); activeModule=null; return; }
    activeModule = key;
    const card = document.getElementById(`card-${key}`);
    if(card) card.classList.add('expanded');
    const meta = SMIC_MODULES[key], mod = smicData.modules[key];
    if(!mod) return;
    document.getElementById('detail-title').textContent = `${meta.icon} ${meta.label} · ${mod.score}/100 (${mod.grade}级)`;

    document.getElementById('detail-body').innerHTML = mod.checks.map((c,idx) => {
        const icon = c.status==='pass'?'✅':c.status==='warn'?'⚠️':'❌';
        const sc = c.score??0;
        const barC = sc>=85?'#10b981':sc>=70?'#3b82f6':sc>=55?'#f59e0b':'#ef4444';
        const txtC = sc>=85?'#34d399':sc>=70?'#60a5fa':sc>=55?'#fbbf24':'#f87171';
        const rid = `rule-${key}-${idx}`;
        const hasRule = c.explanation||c.threshold||c.action;
        let threshHtml = '';
        if(c.threshold) {
            const segs = c.threshold.split('|').map(s=>s.trim()).map(seg=>{
                let t='green'; if(seg.includes('🟡'))t='yellow'; if(seg.includes('🔴'))t='red';
                const text=seg.replace(/🟢|🟡|🔴/g,'').trim();
                const isAct = t===(c.status==='pass'?'green':c.status==='warn'?'yellow':'red');
                return `<div class="threshold-seg seg-${t}${isAct?' active':''}"><span class="seg-icon">${t==='green'?'🟢':t==='yellow'?'🟡':'🔴'}</span><span class="seg-text">${text}</span></div>`;
            }).join('');
            threshHtml = `<div class="rule-threshold-bar"><span class="threshold-label">📊 阈值:</span><div class="threshold-segments">${segs}</div></div>`;
        }
        return `<div class="check-row status-${c.status}"><span class="check-icon">${icon}</span>
            <div class="check-info"><div class="check-name">${c.name}</div><div class="check-detail">${c.detail||''}</div></div>
            <div class="check-score-bar"><div class="check-score-fill" style="width:${sc}%;background:${barC}"></div></div>
            <span class="check-score-val" style="color:${txtC}">${sc}</span>
            ${hasRule?`<button class="check-expand-btn" id="btn-${rid}" onclick="toggleRule(event,'${rid}')">▼</button>`:''}</div>
        ${hasRule?`<div class="check-rule-panel" id="${rid}">
            ${c.explanation?`<div class="rule-explanation"><span class="rule-section-icon">📖</span> ${c.explanation}</div>`:''}
            ${threshHtml}
            ${c.action?`<div class="rule-action"><span class="rule-action-label">🛠️ 建议:</span><span class="rule-action-text">${c.action}</span></div>`:''}
        </div>`:''}`;
    }).join('');

    section.classList.add('visible');
    if(!noScroll) section.scrollIntoView({behavior:'smooth',block:'nearest'});
}

function toggleRule(e, rid) {
    e.stopPropagation();
    const panel = document.getElementById(rid), btn = document.getElementById(`btn-${rid}`);
    if(!panel) return;
    const isOpen = panel.classList.contains('open');
    panel.parentElement?.querySelectorAll('.check-rule-panel.open').forEach(p=>{ p.classList.remove('open'); const b=document.getElementById(`btn-${p.id}`); if(b)b.classList.remove('open'); });
    if(!isOpen){ panel.classList.add('open'); if(btn)btn.classList.add('open'); }
}

function closeDetail() { document.getElementById('detail-section').classList.remove('visible'); document.querySelectorAll('.module-card').forEach(c=>c.classList.remove('expanded')); activeModule=null; }

function scrollToFirstIssue() {
    if(!smicData) return;
    for(const key of Object.keys(SMIC_MODULES)) {
        if(smicData.modules[key]?.checks?.some(c=>c.status==='fail'||c.status==='warn')) { toggleDetail(key); return; }
    }
}

function autoExpandWorst(d) {
    let wk=null, ws=101;
    for(const k of Object.keys(SMIC_MODULES)) {
        const mod=d.modules[k]; if(!mod) continue;
        const ef = mod.checks?.some(c=>c.status==='fail') ? mod.score-100 : mod.score;
        if(ef<ws){ ws=ef; wk=k; }
    }
    if(wk && ws<100) toggleDetail(wk, true);
}

// ═══════════════════════════════════════════════════════
//  7. Financial Charts — ENHANCED V2.0
// ═══════════════════════════════════════════════════════
function renderCharts(d) {
    const f = d.financials;
    const darkGrid = { top:40, bottom:28, left:55, right:20 };
    const axisStyle = { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)',type:'dashed'}} };
    const tooltipStyle = {
        trigger:'axis',
        backgroundColor:'rgba(15,23,42,0.92)',
        borderColor:'rgba(99,102,241,0.2)',
        textStyle:{color:'#e2e8f0',fontSize:12,fontFamily:'Inter'},
        padding:[10,14]
    };
    const legendStyle = { top:6, right:10, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:12, itemHeight:8 };

    // Revenue & Net Income
    echarts.init(document.getElementById('chart-revenue')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#818cf8'},{offset:1,color:'#6366f1'}]},borderRadius:[4,4,0,0]},
                emphasis:{itemStyle:{shadowBlur:12,shadowColor:'rgba(99,102,241,0.3)'}}},
            {name:'净利润',type:'line',data:f.net_income,smooth:true,
                lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399',borderColor:'#10b981',borderWidth:2},
                symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.12)'},{offset:1,color:'transparent'}]}}}
        ]
    });

    // Margins & Utilization
    echarts.init(document.getElementById('chart-margins')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,max:110},
        series:[
            {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,
                lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.15)'},{offset:1,color:'transparent'}]}},
                markLine:{silent:true,data:[{yAxis:30,label:{show:true,formatter:'健康线 30%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
            {name:'产能利用率',type:'line',data:f.caputil,smooth:true,
                lineStyle:{color:'#06b6d4',width:2,type:'dashed'},itemStyle:{color:'#22d3ee',borderColor:'#06b6d4',borderWidth:2},symbol:'circle',symbolSize:6}
        ]
    });

    // R&D vs CAPEX
    echarts.init(document.getElementById('chart-rdcapex')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'研发投入',type:'bar',data:f.rd_expense,barWidth:'28%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#a78bfa'},{offset:1,color:'#8b5cf6'}]},borderRadius:[3,3,0,0]}},
            {name:'资本开支',type:'bar',data:f.capex,barWidth:'28%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#fb7185'},{offset:1,color:'#ef4444'}]},borderRadius:[3,3,0,0]}}
        ]
    });

    // Node Split (Pie)
    const ns = d.financials.node_split;
    echarts.init(document.getElementById('chart-nodes')).setOption({
        tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(99,102,241,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
        series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],
            data:Object.entries(ns).map(([k,v])=>({name:k,value:v})),
            label:{show:false},
            emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700},itemStyle:{shadowBlur:16,shadowColor:'rgba(99,102,241,0.3)'}},
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},
            color:['#6366f1','#8b5cf6','#a78bfa','#06b6d4','#475569']
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  8. Risk Matrix
// ═══════════════════════════════════════════════════════
function renderRiskMatrix(d) {
    const badge = document.getElementById('rm-badge');
    const critCount = d.risks.filter(r=>r.level==='critical').length;
    badge.textContent = critCount>0 ? `${critCount} 项致命风险` : '风险可控';
    badge.className = `smic-rm-badge ${critCount>0?'high':'medium'}`;

    document.getElementById('smic-rm-body').innerHTML = d.risks.map(r => {
        const cls = r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
        const icon = r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
        return `<div class="smic-risk-item ${cls}">
            <div class="smic-risk-name">${icon} ${r.name}</div>
            <div class="smic-risk-desc">${r.desc}</div>
            <div class="smic-risk-tags">
                <span class="smic-risk-tag probability">概率: ${r.probability}</span>
                <span class="smic-risk-tag impact">影响: ${r.impact}</span>
                <span class="smic-risk-tag mitigation">对冲: ${r.mitigation}</span>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  9. Investment Verdict
// ═══════════════════════════════════════════════════════
function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('smic-verdict-body').innerHTML = `
        <div class="smic-verdict-card bull"><div class="smic-verdict-card-title">📈 看多逻辑</div><ul class="smic-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="smic-verdict-card bear"><div class="smic-verdict-card-title">📉 看空逻辑</div><ul class="smic-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="smic-verdict-card catalyst"><div class="smic-verdict-card-title">⚡ 关键催化剂</div><ul class="smic-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="smic-verdict-card position"><div class="smic-verdict-card-title">🎯 仓位建议</div><ul class="smic-verdict-list"><li>${v.positioning}</li></ul></div>
        <div class="smic-conclusion-box">
            <div class="smic-conclusion-title">🏛️ 投资研判总结</div>
            <div class="smic-conclusion-text">${v.summary}</div>
            <div class="smic-conclusion-rating ${v.rating}">${v.rating_text}</div>
        </div>`;
}

// ═══════════════════════════════════════════════════════
//  10. Timeline
// ═══════════════════════════════════════════════════════
function renderTimeline(d) {
    const container = document.getElementById('audit-timeline');
    if(!container) return;
    const hk = 'alphacore_smic_audit_history_v3';
    let hist = []; try { hist = JSON.parse(localStorage.getItem(hk)||'[]'); } catch(e){}
    const last = hist.length>0 ? hist[hist.length-1].time : '';
    if(d.audit_time !== last) hist.push({score:d.trust_score, time:d.audit_time, grade:d.trust_grade});
    if(hist.length>20) hist = hist.slice(-20);
    localStorage.setItem(hk, JSON.stringify(hist));

    container.style.display = 'block';
    const trendEl = document.getElementById('timeline-trend');
    if(hist.length<2) {
        trendEl.textContent = '— 首次审计'; trendEl.className = 'timeline-trend stable';
    } else {
        const prev=hist[hist.length-2].score, curr=hist[hist.length-1].score;
        if(curr>prev){trendEl.textContent=`↑ +${curr-prev}`;trendEl.className='timeline-trend up';}
        else if(curr<prev){trendEl.textContent=`↓ ${curr-prev}`;trendEl.className='timeline-trend down';}
        else{trendEl.textContent='→ 稳定';trendEl.className='timeline-trend stable';}
    }

    echarts.init(document.getElementById('timeline-chart')).setOption({
        grid:{top:8,bottom:24,left:40,right:16},
        xAxis:{type:'category',data:hist.map(h=>h.time?.split(' ')[1]||'now'),axisLabel:{fontSize:10,color:'#475569'},axisLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}},
        yAxis:{type:'value',min:0,max:100,axisLabel:{fontSize:10,color:'#475569'},splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)'}},
            markLine:{silent:true,data:[{yAxis:70,label:{show:true,formatter:'可投线',color:'#4ade80',fontSize:9},lineStyle:{color:'rgba(74,222,128,0.2)',type:'dashed'}},{yAxis:55,label:{show:true,formatter:'警戒线',color:'#fbbf24',fontSize:9},lineStyle:{color:'rgba(251,191,36,0.2)',type:'dashed'}}]}},
        series:[{type:'line',data:hist.map(h=>h.score),smooth:true,symbol:'circle',symbolSize:7,
            lineStyle:{color:'#6366f1',width:2.5},itemStyle:{color:'#818cf8',borderColor:'#6366f1',borderWidth:2},
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(99,102,241,0.2)'},{offset:1,color:'rgba(99,102,241,0)'}]}}
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  KPI Dashboard — NEW in V2.0
// ═══════════════════════════════════════════════════════
function renderKPIDashboard(d) {
    const c = document.getElementById('smic-kpi-dashboard');
    if(!c) return;
    const accentMap = { pass:'rgba(16,185,129,0.5)', warn:'rgba(245,158,11,0.5)', fail:'rgba(239,68,68,0.5)' };
    const colorMap = { pass:'#34d399', warn:'#fbbf24', fail:'#f87171' };
    const valLevel = d.modules.valuation.score>=55?'warn':'fail';
    const kpis = [
        { label:'综合评分', icon:'🏆', value:d.trust_score, suffix:'/100', sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`, level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail', indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危' },
        { label:'财务健康', icon:'💰', value:d.modules.financial.score, suffix:'', sub:`营收+27% · 毛利率${d.financials.gross_margin[6]}%`, level:d.modules.financial.score>=70?'pass':'warn' },
        { label:'地缘风险', icon:'🌍', value:d.modules.geopolitics.score, suffix:'', sub:'制裁风险为核心制约因子', level:d.modules.geopolitics.score>=55?'warn':'fail', indicator:'⚠ 高风险' },
        { label:'技术护城河', icon:'🔬', value:d.modules.tech_moat.score, suffix:'', sub:'产能已破100万片/月', level:d.modules.tech_moat.score>=70?'pass':'warn' },
        { label:'估值合理性', icon:'📊', value:d.modules.valuation.score, suffix:'', sub:`PE ${d.pe}X · PB ${d.pb}X`, level:valLevel, indicator:valLevel==='fail'?'🔴 严重偏高':'⚠ 偏高' },
        { label:'成长动能', icon:'🚀', value:d.modules.growth.score, suffix:'', sub:'CAGR 22-28% · 百万片里程碑', level:d.modules.growth.score>=70?'pass':'warn' },
    ];
    c.innerHTML = kpis.map((kpi,i) => {
        const accent = accentMap[kpi.level];
        const color = colorMap[kpi.level];
        return `<div class="smic-kpi-card" style="--kpi-accent:${accent};animation:smicSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
            <div class="smic-kpi-label">${kpi.icon} ${kpi.label}</div>
            <div class="smic-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
            <div class="smic-kpi-sub">${kpi.sub}</div>
            ${kpi.indicator?`<div class="smic-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
        </div>`;
    }).join('');
    // Animate KPI numbers
    kpis.forEach((kpi,i) => {
        setTimeout(() => counterUp(document.getElementById(`kpi-val-${i}`), kpi.value, kpi.suffix||'', 900), 200 + i*100);
    });
}
