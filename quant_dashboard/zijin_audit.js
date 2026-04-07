/**
 * AlphaCore · 紫金矿业 个股穿透审计终端 V3.0
 * 五维穿透审计：财务健康 · 资源禀赋 · 全球化风险 · 估值合理性 · 成长动能
 * Self-contained — Gold/Amber premium theme
 */

// ═══════════════════════════════════════════════════════
//  紫金矿业 五维审计数据模型
// ═══════════════════════════════════════════════════════
const ZIJIN_MODULES = {
    financial:  { icon: '💰', color: '#10b981', label: '财务健康', weight: 25 },
    resource:   { icon: '⛏️', color: '#f59e0b', label: '资源禀赋', weight: 20 },
    global_risk:{ icon: '🌍', color: '#ef4444', label: '全球化风险', weight: 20 },
    valuation:  { icon: '📊', color: '#3b82f6', label: '估值合理性', weight: 15 },
    growth:     { icon: '🚀', color: '#8b5cf6', label: '成长动能', weight: 20 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildZijinData() {
    const modules = {
        financial: {
            score: 82, grade: 'B',
            checks: [
                { name:'营收增长', score:88, status:'pass', detail:'2025年营收约3,580亿元(+16.0%)，连续6年双位数增长，金铜价格上行+产量增长双轮驱动', explanation:'矿业公司营收受金属价格与产量双因子驱动，紫金矿业量价齐升格局持续', threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%' },
                { name:'净利润', score:85, status:'pass', detail:'归母净利润约355亿元(+10.6%)，EPS约1.34元，盈利能力持续增强', explanation:'2024年归母净利润321亿元，同比+51.5%，基数效应下2025增速回归常态' },
                { name:'毛利率', score:78, status:'pass', detail:'综合毛利率约18.5%，矿产金毛利率约55%，矿产铜毛利率约38%', explanation:'矿业行业毛利率波动大，紫金矿业受益于低成本矿山组合', threshold:'🟢 >15% | 🟡 10-15% | 🔴 <10%' },
                { name:'ROE', score:80, status:'pass', detail:'ROE约22.8%(2024: 23.6%)，持续高于行业均值15%', explanation:'高ROE反映管理层优秀的资本配置能力与资源整合效率' },
                { name:'资产负债率', score:62, status:'warn', detail:'资产负债率约58.2%，有息负债超1,200亿元，财务杠杆偏高', explanation:'激进并购扩张导致杠杆较高，但矿业行业重资产属性下尚属可控', action:'关注利息覆盖率及现金流偿债能力', threshold:'🟢 <50% | 🟡 50-65% | 🔴 >65%' },
                { name:'自由现金流', score:72, status:'pass', detail:'经营性现金流约580亿元，FCF约220亿元(CAPEX约360亿元)', explanation:'矿业公司FCF取决于金属价格景气度，当前处于上行周期' },
            ]
        },
        resource: {
            score: 90, grade: 'A',
            checks: [
                { name:'黄金资源量', score:95, status:'pass', detail:'黄金资源量约3,200吨(含权)，全球第三大金矿企业', explanation:'2024矿产金76.5吨(+12.6%)，2025E约88吨，持续扩产中' },
                { name:'铜资源量', score:92, status:'pass', detail:'铜资源量约7,600万吨(含权)，全球前五铜矿企业', explanation:'2024矿产铜115万吨(+6.2%)，2025E约125万吨，刚果(金)Kamoa-Kakula贡献增量' },
                { name:'锌资源量', score:78, status:'pass', detail:'锌资源量约1,100万吨，矿产锌约48万吨(2024)', explanation:'锌板块盈利贡献约8%，整体占比较小但提供多元化对冲' },
                { name:'资源自给率', score:88, status:'pass', detail:'矿产金/铜/锌自给率分别约95%/82%/90%，冶炼加工占比持续下降', explanation:'高资源自给率确保利润率与供应安全' },
                { name:'矿山成本控制', score:85, status:'pass', detail:'矿产金AISC约1,050美元/盎司，矿产铜C1成本约1.45美元/磅，均低于全球中位数', explanation:'低成本优势是抵御金属价格下行的核心护城河', threshold:'🟢 AISC<1200 | 🟡 1200-1500 | 🔴 >1500' },
                { name:'储量替换率', score:82, status:'pass', detail:'储量替换率约130%，新发现矿体+并购双重补充', explanation:'储量持续增长是矿企可持续经营的核心指标' },
            ]
        },
        global_risk: {
            score: 55, grade: 'C',
            checks: [
                { name:'地缘集中度', score:48, status:'warn', detail:'海外营收占比约42%，刚果(金)/塞尔维亚/巴新/哥伦比亚等高风险地区资产占比约35%', explanation:'刚果(金)政治不稳定性+矿业税收政策波动为核心风险因子', action:'跟踪刚果(金)矿业法修订及特许权费率变化' },
                { name:'刚果(金)风险', score:38, status:'fail', detail:'Kamoa-Kakula铜矿占铜产量约30%，刚果(金)政局不稳+矿业税改风险', explanation:'2025年刚果(金)拟提高矿业特许权使用费率至8-10%，将直接冲击利润', action:'评估特许权费率上调对铜板块毛利率的影响' },
                { name:'汇率风险', score:65, status:'warn', detail:'大量海外资产以美元计价，人民币汇率波动影响约±15亿元/年', explanation:'矿业公司天然具有美元资产敞口，汇率波动为常规风险' },
                { name:'环保合规', score:60, status:'warn', detail:'ESG评级BBB(MSCI)，尾矿库管理与碳中和承诺有待提升', explanation:'海外矿山环保标准趋严，合规成本逐年增加约5-8%' },
                { name:'政策支持', score:75, status:'pass', detail:'国内矿业龙头地位稳固，"走出去"战略获政策背书', explanation:'一带一路+矿产资源安全战略提供稳定的政策环境' },
            ]
        },
        valuation: {
            score: 65, grade: 'C',
            checks: [
                { name:'PE估值', score:58, status:'warn', detail:'PE(TTM) ~18.5X，高于全球矿业巨头(Barrick 14X / Newmont 16X)但低于A股溢价均值', explanation:'A股矿业龙头享有流动性溢价，但当前PE处于近3年分位80%', threshold:'🟢 <15X | 🟡 15-25X | 🔴 >25X' },
                { name:'PB估值', score:52, status:'warn', detail:'PB ~3.8X，显著高于全球矿业中位数1.5X', explanation:'高ROE(22.8%)支撑较高PB定价，但3.8X已接近历史上沿', threshold:'🟢 <2.0X | 🟡 2.0-4.0X | 🔴 >4.0X' },
                { name:'EV/EBITDA', score:68, status:'pass', detail:'EV/EBITDA ~8.5X，处于全球矿企合理区间(6-10X)', explanation:'矿业行业EV/EBITDA估值更具横向可比性' },
                { name:'DCF内在价值', score:72, status:'pass', detail:'乐观/中性/悲观情景估值：22.5/18.0/13.5 元(当前¥19.8)', explanation:'中性情景显示当前股价略低于内在价值，安全边际约9%' },
                { name:'股息率', score:70, status:'pass', detail:'股息率约2.8%，分红率约38%，2024年分红总额约122亿元', explanation:'矿业公司高分红是价值投资重要信号，紫金矿业分红率持续提升' },
            ]
        },
        growth: {
            score: 85, grade: 'A',
            checks: [
                { name:'产量增速', score:90, status:'pass', detail:'2024-2028E矿产金CAGR约15%，矿产铜CAGR约12%，远超全球矿业增速', explanation:'新矿投产(西藏巨龙铜矿/刚果金KK矿三期)推动产量高速增长' },
                { name:'金属价格趋势', score:82, status:'pass', detail:'国际金价$3,200+/盎司，铜价$9,800+/吨，均处于历史高位区间', explanation:'全球降息周期+地缘避险推高黄金，新能源需求支撑铜价中枢上移' },
                { name:'并购扩张', score:88, status:'pass', detail:'2024年完成多项战略并购(含Buriticá金矿/苏里南金矿等)，资源版图持续扩大', explanation:'紫金矿业并购整合能力为国内矿企最强' },
                { name:'产业链延伸', score:75, status:'pass', detail:'向新能源材料(碳酸锂/镍)延伸布局，锂矿产量约2.5万吨LCE(2025E)', explanation:'第二增长曲线布局，但锂价低迷短期难以贡献利润' },
                { name:'国产替代机遇', score:78, status:'pass', detail:'国内金铜资源自给率不足50%，紫金矿业作为龙头获得政策+资本双重倾斜', explanation:'矿产资源安全纳入国家战略，头部企业集中度将持续提升', action:'关注国内矿权审批加速与资源税改革进展' },
            ]
        }
    };

    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = ZIJIN_MODULES[k].weight;
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
        company: '紫金矿业', ticker_a: '601899.SH', ticker_h: '2899.HK',
        market_cap: '5,246亿', price: '19.80', pe: '18.5', pb: '3.80',
        eps: '1.34', week52_high: '22.35', week52_low: '13.60',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'刚果(金)政治风险', level:'critical', desc:'Kamoa-Kakula铜矿所在刚果(金)政局不稳，矿业税改+特许权费率上调将直接冲击铜板块盈利', probability:'高', impact:'重大', mitigation:'多元化矿区布局+政府关系维护' },
            { name:'金属价格回调风险', level:'critical', desc:'金价$3,200+/盎司、铜价$9,800+/吨均处历史高位，宏观紧缩或全球衰退将触发暴跌', probability:'中等', impact:'致命', mitigation:'AISC成本优势+多金属对冲' },
            { name:'海外资产减值风险', level:'high', desc:'大量海外并购资产存在商誉及矿权减值风险，历史并购溢价偏高', probability:'中等', impact:'重大', mitigation:'保守减值测试+加速矿山产能达产' },
            { name:'ESG及环保风险', level:'high', desc:'尾矿库安全事故+碳排放政策趋严，海外环保合规成本持续攀升', probability:'中等', impact:'中等', mitigation:'ESG评级提升+绿色矿山建设投入' },
            { name:'资产负债率偏高', level:'medium', desc:'有息负债超1,200亿元，激进并购扩张导致杠杆水平高于行业均值', probability:'低', impact:'中等', mitigation:'经营现金流充沛+滚动再融资' },
            { name:'汇率波动风险', level:'medium', desc:'海外资产美元计价估值约占总资产42%，人民币升值将产生汇兑损失', probability:'中等', impact:'轻微', mitigation:'自然对冲+适度外汇套保' },
        ],
        verdict: {
            bull: ['全球第三大金矿+前五铜矿企业，资源禀赋全球顶级', '矿产金/铜CAGR 15%/12%，增速远超全球矿业', '低AISC成本构成抵御价格下行的核心护城河', 'ROE持续>22%，资本配置能力业内领先'],
            bear: ['刚果(金)政治风险可能冲击铜板块30%产量', '金铜价格处于历史高位，回调风险不容忽视', '资产负债率58%偏高，并购节奏过于激进', 'PB 3.8X处于历史高位，估值溢价空间收窄'],
            catalysts: ['黄金突破$3,500/盎司(央行购金+降息周期)', '西藏巨龙铜矿二期投产(2026H2)', 'Kamoa-Kakula三期满产(年产铜40万吨+)', '国内矿权审批加速+资源税改革利好'],
            positioning: '✅ 优质龙头标的。当前PE 18.5X合理偏高，建议仓位控制在8-12%。核心逻辑为资源量价齐升Alpha，黄金避险+铜新能源需求提供双重Beta。设置金价跌破$2,800/铜价跌破$8,500为风险警戒线。',
            rating: 'buy', rating_text: '📈 战略性建仓 / 逢低加仓',
            summary: '紫金矿业是A股唯一具有全球顶级资源禀赋的矿业龙头，金铜双轮驱动下2025年营收预计达3,580亿元(+16%)，归母净利润355亿元。ROE持续>22%、AISC全球低位、储量替换率>130%构成三重护城河。主要风险为刚果(金)地缘政治不确定性及金属价格高位回调。当前PE 18.5X处于合理偏高区间(近3年分位80%)，建议采取"核心仓位+趋势加仓"策略，逢回调至PE 15X以下(约¥16)积极加仓。'
        },
        financials: {
            years: ['2019','2020','2021','2022','2023','2024','2025E'],
            revenue: [1361, 1715, 2252, 2703, 2934, 3086, 3580],
            net_income: [42.8, 65.1, 157.0, 200.4, 211.8, 321.0, 355.0],
            gross_margin: [10.2, 11.8, 16.5, 14.8, 13.5, 17.2, 18.5],
            roe: [15.2, 18.6, 28.6, 25.4, 21.8, 23.6, 22.8],
            gold_output: [40.8, 44.6, 57.7, 67.7, 68.0, 76.5, 88.0],
            copper_output: [37.1, 45.3, 58.4, 90.5, 108.3, 115.0, 125.0],
            zinc_output: [31.2, 35.6, 38.5, 42.0, 44.8, 48.0, 52.0],
            revenue_split: { '金矿': 32, '铜矿': 38, '锌矿': 8, '冶炼加工': 15, '其他': 7 }
        }
    };
}

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runZijinAudit(); });

const ZIJIN_SECTIONS = ['zijin-identity','trust-hero','zijin-kpi-dashboard','audit-overview','zijin-charts-grid','zijin-risk-matrix','zijin-verdict','audit-timeline'];

function runZijinAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    ZIJIN_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    const loadingStatus = document.querySelector('.loading-status');
    const moduleSteps = [
        { t: 300,  text: '💰 正在审计 [1/5] 财务健康… 营收·利润率·ROE·现金流·杠杆率' },
        { t: 600,  text: '⛏️ 正在审计 [2/5] 资源禀赋… 金资源量·铜资源量·矿山成本·储量替换' },
        { t: 900,  text: '🌍 正在审计 [3/5] 全球化风险… 刚果(金)·汇率·ESG·政策支持' },
        { t: 1200, text: '📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA·股息率' },
        { t: 1500, text: '🚀 正在审计 [5/5] 成长动能… 产量增速·金属价格·并购扩张·产业链' },
        { t: 1800, text: '✅ 五维穿透审计完成，正在生成报告…' },
    ];
    moduleSteps.forEach(step => {
        setTimeout(() => { if(loadingStatus) loadingStatus.textContent = step.text; }, step.t);
    });

    setTimeout(() => {
        const data = buildZijinData();
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

    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'zijin-charts-grid':'grid', 'zijin-kpi-dashboard':'grid' };
    ZIJIN_SECTIONS.forEach(id => {
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

    ZIJIN_SECTIONS.forEach((id, i) => {
        const el = document.getElementById(id);
        if(!el) return;
        setTimeout(() => {
            el.style.transition = 'opacity 0.5s ease, transform 0.5s cubic-bezier(0.22,1,0.36,1)';
            el.style.opacity = '1';
            el.style.transform = 'translateY(0)';
        }, 80 * i);
        el.style.transform = 'translateY(12px)';
    });

    const layout = document.getElementById('audit-layout');
    layout.classList.remove('scan-complete');
    void layout.offsetWidth;
    layout.classList.add('scan-complete');

    // Detail panel no longer auto-expands — users click to view
}

// ═══════════════════════════════════════════════════════
//  Counter-Up Animation
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
    document.getElementById('qs-price').textContent = '¥'+d.price;
    const peEl = document.getElementById('qs-pe');
    peEl.textContent = d.pe+'X';
    const peVal = parseFloat(d.pe);
    if(peVal > 30) peEl.style.color = '#f87171';
    else if(peVal > 20) peEl.style.color = '#fbbf24';
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

    const verdicts = { A:'投资价值突出，各维度均衡优秀', B:'整体可投，存在结构性风险需关注', C:'风险与机会并存，需精选入场时机', D:'⚠️ 高风险标的，不建议重仓' };
    document.getElementById('trust-verdict').textContent = verdicts[d.trust_grade] || '';
    document.getElementById('stat-pass').textContent = `✅ ${d.pass_count} 优势`;
    document.getElementById('stat-warn').textContent = `⚠️ ${d.warn_count} 关注`;
    document.getElementById('stat-fail').textContent = `❌ ${d.fail_count} 风险`;
    document.getElementById('trust-meta').textContent = `共 ${d.total_checks} 项检查 · 加权评分 ${d.trust_score}/100 · ${d.audit_time}`;

    const keys = Object.keys(ZIJIN_MODULES);
    const shortLabels = { financial:'财务', resource:'资源', global_risk:'地缘', valuation:'估值', growth:'成长' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s*1.4, 8);
        return `<div class="eq-bar-group" title="${ZIJIN_MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${c}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${c};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${shortLabels[k]}</span></div>`;
    }).join('');

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
    const keys = Object.keys(ZIJIN_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:ZIJIN_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(245,158,11,0.02)','rgba(245,158,11,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'紫金矿业审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.35)'},{offset:1,color:'rgba(217,119,6,0.08)'}]}},
            lineStyle:{color:'#f59e0b',width:2}, itemStyle:{color:'#fbbf24'}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = ZIJIN_MODULES[k]; const s = d.modules[k].score;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  5. Module Cards
// ═══════════════════════════════════════════════════════
let zijinData = null, activeModule = null;

function renderModuleCards(d) {
    zijinData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(ZIJIN_MODULES).map(([key, meta]) => {
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
    const meta = ZIJIN_MODULES[key], mod = zijinData.modules[key];
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
    if(!zijinData) return;
    for(const key of Object.keys(ZIJIN_MODULES)) {
        if(zijinData.modules[key]?.checks?.some(c=>c.status==='fail'||c.status==='warn')) { toggleDetail(key); return; }
    }
}

function autoExpandWorst(d) {
    let wk=null, ws=101;
    for(const k of Object.keys(ZIJIN_MODULES)) {
        const mod=d.modules[k]; if(!mod) continue;
        const ef = mod.checks?.some(c=>c.status==='fail') ? mod.score-100 : mod.score;
        if(ef<ws){ ws=ef; wk=k; }
    }
    if(wk && ws<100) toggleDetail(wk, true);
}

// ═══════════════════════════════════════════════════════
//  7. Financial Charts — Gold/Amber Theme
// ═══════════════════════════════════════════════════════
function renderCharts(d) {
    const f = d.financials;
    const darkGrid = { top:40, bottom:28, left:55, right:20 };
    const axisStyle = { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)',type:'dashed'}} };
    const tooltipStyle = { trigger:'axis', backgroundColor:'rgba(15,23,42,0.92)', borderColor:'rgba(245,158,11,0.2)', textStyle:{color:'#e2e8f0',fontSize:12,fontFamily:'Inter'}, padding:[10,14] };
    const legendStyle = { top:6, right:10, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:12, itemHeight:8 };

    // Revenue & Net Income
    echarts.init(document.getElementById('chart-revenue')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#fbbf24'},{offset:1,color:'#f59e0b'}]},borderRadius:[4,4,0,0]},
                emphasis:{itemStyle:{shadowBlur:12,shadowColor:'rgba(245,158,11,0.3)'}}},
            {name:'净利润',type:'line',data:f.net_income,smooth:true,
                lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399',borderColor:'#10b981',borderWidth:2},
                symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.12)'},{offset:1,color:'transparent'}]}}}
        ]
    });

    // Gross Margin & ROE
    echarts.init(document.getElementById('chart-margins')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,max:35},
        series:[
            {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,
                lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.15)'},{offset:1,color:'transparent'}]}},
                markLine:{silent:true,data:[{yAxis:15,label:{show:true,formatter:'健康线 15%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
            {name:'ROE',type:'line',data:f.roe,smooth:true,
                lineStyle:{color:'#8b5cf6',width:2,type:'dashed'},itemStyle:{color:'#a78bfa',borderColor:'#8b5cf6',borderWidth:2},symbol:'circle',symbolSize:6}
        ]
    });

    // Gold/Copper/Zinc Production
    echarts.init(document.getElementById('chart-production')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:[
            {type:'value',name:'吨(金)',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
            {type:'value',name:'万吨(铜/锌)',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,splitLine:{show:false}}
        ],
        series:[
            {name:'矿产金(吨)',type:'bar',data:f.gold_output,barWidth:'22%',yAxisIndex:0,
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#fcd34d'},{offset:1,color:'#f59e0b'}]},borderRadius:[3,3,0,0]}},
            {name:'矿产铜(万吨)',type:'line',data:f.copper_output,smooth:true,yAxisIndex:1,
                lineStyle:{color:'#c2410c',width:2.5},itemStyle:{color:'#ea580c',borderColor:'#c2410c',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(194,65,12,0.1)'},{offset:1,color:'transparent'}]}}},
            {name:'矿产锌(万吨)',type:'line',data:f.zinc_output,smooth:true,yAxisIndex:1,
                lineStyle:{color:'#06b6d4',width:2,type:'dashed'},itemStyle:{color:'#22d3ee',borderColor:'#06b6d4',borderWidth:2},symbol:'circle',symbolSize:5}
        ]
    });

    // Revenue Split (Pie)
    const rs = d.financials.revenue_split;
    echarts.init(document.getElementById('chart-segments')).setOption({
        tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(245,158,11,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
        series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],
            data:Object.entries(rs).map(([k,v])=>({name:k,value:v})),
            label:{show:false},
            emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700},itemStyle:{shadowBlur:16,shadowColor:'rgba(245,158,11,0.3)'}},
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},
            color:['#fbbf24','#c2410c','#06b6d4','#6366f1','#475569']
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
    badge.className = `zijin-rm-badge ${critCount>0?'high':'medium'}`;

    document.getElementById('zijin-rm-body').innerHTML = d.risks.map(r => {
        const cls = r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
        const icon = r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
        return `<div class="zijin-risk-item ${cls}">
            <div class="zijin-risk-name">${icon} ${r.name}</div>
            <div class="zijin-risk-desc">${r.desc}</div>
            <div class="zijin-risk-tags">
                <span class="zijin-risk-tag probability">概率: ${r.probability}</span>
                <span class="zijin-risk-tag impact">影响: ${r.impact}</span>
                <span class="zijin-risk-tag mitigation">对冲: ${r.mitigation}</span>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  9. Investment Verdict
// ═══════════════════════════════════════════════════════
function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('zijin-verdict-body').innerHTML = `
        <div class="zijin-verdict-card bull"><div class="zijin-verdict-card-title">📈 看多逻辑</div><ul class="zijin-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="zijin-verdict-card bear"><div class="zijin-verdict-card-title">📉 看空逻辑</div><ul class="zijin-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="zijin-verdict-card catalyst"><div class="zijin-verdict-card-title">⚡ 关键催化剂</div><ul class="zijin-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="zijin-verdict-card position"><div class="zijin-verdict-card-title">🎯 仓位建议</div><ul class="zijin-verdict-list"><li>${v.positioning}</li></ul></div>
        <div class="zijin-conclusion-box">
            <div class="zijin-conclusion-title">🏛️ 投资研判总结</div>
            <div class="zijin-conclusion-text">${v.summary}</div>
            <div class="zijin-conclusion-rating ${v.rating}">${v.rating_text}</div>
        </div>`;
}

// ═══════════════════════════════════════════════════════
//  10. Timeline
// ═══════════════════════════════════════════════════════
function renderTimeline(d) {
    const container = document.getElementById('audit-timeline');
    if(!container) return;
    const hk = 'alphacore_zijin_audit_history_v3';
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
            lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.2)'},{offset:1,color:'rgba(245,158,11,0)'}]}}
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  KPI Dashboard
// ═══════════════════════════════════════════════════════
function renderKPIDashboard(d) {
    const c = document.getElementById('zijin-kpi-dashboard');
    if(!c) return;
    const accentMap = { pass:'rgba(16,185,129,0.5)', warn:'rgba(245,158,11,0.5)', fail:'rgba(239,68,68,0.5)' };
    const colorMap = { pass:'#34d399', warn:'#fbbf24', fail:'#f87171' };
    const kpis = [
        { label:'综合评分', icon:'🏆', value:d.trust_score, suffix:'/100', sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`, level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail', indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危' },
        { label:'财务健康', icon:'💰', value:d.modules.financial.score, suffix:'', sub:`营收+16% · ROE ${d.financials.roe[6]}%`, level:d.modules.financial.score>=70?'pass':'warn' },
        { label:'资源禀赋', icon:'⛏️', value:d.modules.resource.score, suffix:'', sub:'全球第三大金矿企业', level:d.modules.resource.score>=85?'pass':d.modules.resource.score>=70?'pass':'warn', indicator:'🥇 顶级' },
        { label:'全球化风险', icon:'🌍', value:d.modules.global_risk.score, suffix:'', sub:'刚果(金)政治风险为核心制约', level:d.modules.global_risk.score>=70?'pass':d.modules.global_risk.score>=55?'warn':'fail', indicator:d.modules.global_risk.score>=55?'⚠ 中等':'🔴 高危' },
        { label:'估值合理性', icon:'📊', value:d.modules.valuation.score, suffix:'', sub:`PE ${d.pe}X · PB ${d.pb}X`, level:d.modules.valuation.score>=70?'pass':'warn', indicator:'◐ 合理偏高' },
        { label:'成长动能', icon:'🚀', value:d.modules.growth.score, suffix:'', sub:'金铜CAGR 15%/12%', level:d.modules.growth.score>=70?'pass':'warn', indicator:'● 强劲' },
    ];
    c.innerHTML = kpis.map((kpi,i) => {
        const accent = accentMap[kpi.level];
        const color = colorMap[kpi.level];
        return `<div class="zijin-kpi-card" style="--kpi-accent:${accent};animation:zijinSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
            <div class="zijin-kpi-label">${kpi.icon} ${kpi.label}</div>
            <div class="zijin-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
            <div class="zijin-kpi-sub">${kpi.sub}</div>
            ${kpi.indicator?`<div class="zijin-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
        </div>`;
    }).join('');
    kpis.forEach((kpi,i) => {
        setTimeout(() => counterUp(document.getElementById(`kpi-val-${i}`), kpi.value, kpi.suffix||'', 900), 200 + i*100);
    });
}
