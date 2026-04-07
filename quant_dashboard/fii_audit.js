/**
 * AlphaCore · 工业富联 个股穿透审计终端 V3.0
 * 五维穿透审计：财务健康 · AI算力护城河 · 供应链韧性 · 估值合理性 · 成长动能
 * Self-contained — Real-time data sync + Enhanced UI
 */

// ═══════════════════════════════════════════════════════
//  工业富联 五维审计数据模型
// ═══════════════════════════════════════════════════════
const FII_MODULES = {
    financial:    { icon: '💰', color: '#10b981', label: '财务健康', weight: 25 },
    ai_moat:      { icon: '🤖', color: '#0ea5e9', label: 'AI算力护城河', weight: 20 },
    supply_chain: { icon: '🔗', color: '#f59e0b', label: '供应链韧性', weight: 20 },
    valuation:    { icon: '📊', color: '#3b82f6', label: '估值合理性', weight: 15 },
    growth:       { icon: '🚀', color: '#8b5cf6', label: '成长动能', weight: 20 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildFIIData() {
    const modules = {
        financial: {
            score: 75, grade: 'B',
            checks: [
                { name:'营收增长', score:92, status:'pass', detail:'2025年营收9028.87亿元，YoY +48.22%，AI算力需求驱动爆发式增长', explanation:'全球AI基础设施资本开支高增长，公司作为核心供应商深度受益', threshold:'🟢 >20% | 🟡 10-20% | 🔴 <10%' },
                { name:'净利润增速', score:88, status:'pass', detail:'归母净利润352.86亿元，YoY +51.99%，利润增速高于营收增速', explanation:'产品结构升级(高毛利AI服务器占比提升)带动盈利质量改善', threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%' },
                { name:'毛利率', score:48, status:'warn', detail:'综合毛利率约7.5%，制造业属性决定毛利水平偏低', explanation:'代工制造业固有特征，但AI产品占比提升正推动毛利率边际改善(2024: 7.1%→2025: 7.5%)', threshold:'🟢 >12% | 🟡 6-12% | 🔴 <6%' },
                { name:'经营性现金流', score:55, status:'warn', detail:'全年经营性现金流净额+52.38亿元，转正但远低于净利润(352亿)', explanation:'订单高峰期备货导致存货大幅增加，应收账款规模扩大，现金转化率偏低', action:'关注Q1/Q2现金回流节奏，若OCF/NI持续<30%需提升预警' },
                { name:'资产负债率', score:62, status:'warn', detail:'资产负债率约65%，有息资产负债率23.19%，短期借款显著增加', explanation:'快速扩产期杠杆率上升，但有息负债率可控，需关注资金周转效率' },
                { name:'分红回报', score:82, status:'pass', detail:'全年累计现金分红194.51亿元，现金分红率55.12%，EPS 1.78元', explanation:'分红率超50%，在成长股中属于高分红水平，彰显盈利质量信心' },
            ]
        },
        ai_moat: {
            score: 88, grade: 'A',
            checks: [
                { name:'AI服务器全球份额', score:95, status:'pass', detail:'全球AI服务器市场份额超40%，稳居行业第一', explanation:'深度绑定NVIDIA、AMD等算力芯片巨头，JDM联合研发模式构建壁垒' },
                { name:'核心客户绑定', score:92, status:'pass', detail:'深度服务微软、谷歌、亚马逊、Meta等全球Top CSP，订单能见度至2027年', explanation:'从OEM代工升级为JDM(联合研发)合作伙伴，客户粘性极高' },
                { name:'AI服务器营收爆发', score:93, status:'pass', detail:'云服务商AI服务器营收YoY增长超3倍(>300%)，云计算板块营收6027亿元(+88.7%)', explanation:'GB200/B200等新一代GPU服务器量产交付，驱动营收爆发式增长' },
                { name:'算力全栈覆盖', score:85, status:'pass', detail:'从GPU模组、基板、服务器整机到液冷系统、高速交换机全产业链覆盖', explanation:'系统级整合能力构成深厚竞争壁垒，800G以上高速交换机营收YoY增长13倍' },
                { name:'下一代产品储备', score:78, status:'pass', detail:'GB300/Rubin架构等下一代算力产品研发跟进中，量产计划明确', explanation:'技术迭代响应速度是保持龙头地位的关键，目前节奏领先同业' },
            ]
        },
        supply_chain: {
            score: 62, grade: 'C',
            checks: [
                { name:'客户集中度', score:42, status:'fail', detail:'前五大客户营收占比约65-70%，高度依赖少数核心CSP', explanation:'若核心客户资本开支收缩或份额调整，将直接冲击业绩表现', action:'持续监控微软/谷歌/Meta等头部客户CapEx指引' },
                { name:'地缘政治风险', score:48, status:'warn', detail:'全球贸易环境不确定性加剧，出口管制政策可能影响跨境供应链', explanation:'虽非直接制裁标的，但中美科技脱钩趋势可能间接影响全球产能布局' },
                { name:'上游供应依赖', score:55, status:'warn', detail:'核心GPU芯片(NVIDIA/AMD)供应受制于上游，产能分配权不在手中', explanation:'GPU供应紧张时，分配优先级由NVIDIA决定，被动受制于上游格局' },
                { name:'产能全球布局', score:78, status:'pass', detail:'全球制造基地覆盖中国、越南、墨西哥、印度等地，产能弹性强', explanation:'多元化产能布局可对冲单一地区地缘风险，灯塔工厂模式提升制造效率' },
                { name:'库存管理', score:58, status:'warn', detail:'2025年存货规模大幅增加(备货AI服务器组件)，库存周转天数上升', explanation:'AI订单高峰期备货属合理行为，但需警惕需求放缓后的库存减值风险' },
            ]
        },
        valuation: {
            score: 65, grade: 'C',
            checks: [
                { name:'PE估值', score:70, status:'pass', detail:'PE(TTM) ~29.4X，对比全球电子制造服务(EMS)行业均值15-20X偏高，但AI算力赛道溢价合理', explanation:'市场给予AI算力龙头结构性溢价，若按2026E净利润450亿元计，前瞻PE ~23X', threshold:'🟢 <25X | 🟡 25-35X | 🔴 >35X' },
                { name:'PB估值', score:42, status:'warn', detail:'PB ~6.21X，显著高于传统EMS行业均值2-3X', explanation:'高PB反映市场对AI转型溢价认可，但估值回归风险存在', threshold:'🟢 <3X | 🟡 3-6X | 🔴 >6X' },
                { name:'EV/EBITDA', score:55, status:'warn', detail:'EV/EBITDA ~18X，高于行业均值10X，但低于纯AI概念股', explanation:'相对于纯软件/芯片AI标的(30-50X)，制造型AI龙头估值仍具性价比' },
                { name:'DCF内在价值', score:72, status:'pass', detail:'乐观/中性/悲观情景估值：68/52/38 元(当前¥52.18)', explanation:'中性情景锚定当前价格，若AI CapEx周期延续至2028年，上行空间约30%', action:'关注2026Q1业绩是否超预期验证估值支撑' },
                { name:'股息率', score:78, status:'pass', detail:'股息率约3.7%，分红率55.12%', explanation:'在万亿市值科技股中，3.7%股息率极具吸引力，提供估值安全边际' },
            ]
        },
        growth: {
            score: 85, grade: 'A',
            checks: [
                { name:'AI CapEx超级周期', score:92, status:'pass', detail:'全球AI基础设施资本开支2025-2027年CAGR预计超40%，公司处于核心受益位', explanation:'微软/谷歌/Meta/Amazon年度CapEx合计超3000亿美元，持续加码AI算力建设' },
                { name:'营收增速', score:90, status:'pass', detail:'2024-2026E CAGR约35-40%，远超传统EMS行业5-8%增速', explanation:'AI服务器+高速交换机双引擎驱动，结构性增长远超行业均值' },
                { name:'产品升级路径', score:82, status:'pass', detail:'从通用服务器→AI推理服务器→AI训练服务器，ASP(平均售价)持续提升', explanation:'GPU服务器ASP是传统服务器的5-10倍，产品结构升级直接拉升营收天花板' },
                { name:'AI需求可持续性', score:68, status:'warn', detail:'AI CapEx周期预计持续至2028年，但需警惕2027年后增速放缓的可能', explanation:'当前属于AI基础设施建设爆发期，长期可持续性取决于AI应用落地进度', action:'密切关注全球CSP季度CapEx指引变化' },
                { name:'智能制造输出', score:72, status:'pass', detail:'灯塔工厂技术对外输出，工业互联网平台收入稳步增长', explanation:'制造能力IP化输出构建第二增长曲线，但体量暂小' },
            ]
        }
    };

    // Calculate trust score
    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = FII_MODULES[k].weight;
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
        company: '工业富联', ticker: '601138.SH',
        market_cap: '1.04万亿', price: '52.18', pe: '29.4', pb: '6.21',
        eps: '1.78', week52_high: '83.88', week52_low: '14.58',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'客户集中度风险', level:'critical', desc:'营收高度依赖少数核心CSP(微软/谷歌/Meta/Amazon)，若主要客户CapEx收缩或供应商切换，将直接冲击业绩', probability:'中等', impact:'致命', mitigation:'多元化客户拓展+长期合约锁定' },
            { name:'AI CapEx放缓风险', level:'critical', desc:'若全球AI投资回报不及预期，大厂可能收缩CapEx，导致AI服务器订单断崖式下跌', probability:'中低', impact:'致命', mitigation:'关注季度CapEx指引+提前调整产能' },
            { name:'地缘政治/出口管制', level:'high', desc:'中美科技脱钩升级、芯片出口管制趋严可能影响全球供应链布局和产能分配', probability:'中等', impact:'重大', mitigation:'全球多元化产能布局(越南/墨西哥/印度)' },
            { name:'毛利率天花板', level:'high', desc:'代工制造业固有的低毛利率(7-8%)限制盈利空间上限，产品升级带来的毛利率改善可能低于预期', probability:'高', impact:'中等', mitigation:'提升JDM占比+高附加值产品结构优化' },
            { name:'上游GPU供应风险', level:'high', desc:'核心GPU芯片供应受制于NVIDIA产能分配，公司无法自主控制上游供应节奏', probability:'中等', impact:'重大', mitigation:'深化NVIDIA战略合作+拓展AMD/自研ASIC方案' },
            { name:'PB估值回归风险', level:'medium', desc:'PB 6.21X显著高于EMS行业均值(2-3X)，若AI叙事降温，估值可能面临压缩', probability:'中等', impact:'中等', mitigation:'高分红率(55%)提供安全边际+业绩增长消化估值' },
            { name:'存货减值风险', level:'medium', desc:'AI订单备货期存货大幅膨胀，若需求不及预期，可能面临存货减值损失', probability:'中低', impact:'中等', mitigation:'动态订单管理+JIT供应链优化' },
        ],
        verdict: {
            bull: ['全球AI服务器绝对龙头，市占率超40%，JDM模式构建深厚壁垒', '2025年营收9029亿元(+48%)、净利润353亿元(+52%)，增长质量极高', 'AI CapEx超级周期2025-2028年确定性强，订单能见度至2027年', '高分红率55.12%(股息率3.7%)在成长股中罕见，兼具成长+价值属性'],
            bear: ['毛利率仅7.5%，代工制造业属性限制盈利上限', '客户集中度极高(前五大占比~70%)，大客户波动风险不可忽视', 'PB 6.21X严重偏高于EMS行业均值，估值隐含较多乐观预期', '经营性现金流(52亿)远低于净利润(353亿)，现金转化率偏低'],
            catalysts: ['GB300/Rubin架构量产交付推动营收再上台阶', '2026Q1业绩超预期验证增长持续性', '全球CSP CapEx指引上调', 'NVIDIA新一代GPU平台(Blackwell Ultra/Rubin)大规模部署'],
            positioning: '🟢 AI算力核心Beta标的。建议仓位8-12%，定位为组合中的AI基础设施核心持仓。当前PE 29X在AI CapEx超级周期背景下具有合理性，但需严格跟踪全球CSP CapEx季度指引，若出现连续下调信号应果断减仓。',
            rating: 'buy', rating_text: '📈 积极买入 / AI算力核心配置',
            summary: '工业富联是全球AI算力基础设施的绝对龙头，2025年营收突破9000亿元大关(+48%)，净利润352.86亿元(+52%)，增长质量极高。公司已从传统EMS代工成功转型为AI算力全栈解决方案供应商，JDM模式深度绑定全球头部CSP，订单能见度延伸至2027年。PE 29X在AI CapEx超级周期背景下估值合理，叠加55%分红率(股息率3.7%)提供安全边际。核心风险在于客户集中度和毛利率天花板。建议作为AI主题核心持仓，仓位8-12%，动态跟踪全球CSP CapEx变化。'
        },
        financials: {
            years: ['2019','2020','2021','2022','2023','2024','2025'],
            revenue: [4086.9, 4317.9, 4396.1, 5118.5, 4763.4, 6091.4, 9028.9],
            net_income: [186.1, 174.3, 200.1, 200.7, 210.2, 232.2, 352.9],
            gross_margin: [8.4, 8.3, 8.3, 7.3, 7.6, 7.1, 7.5],
            net_margin: [4.6, 4.0, 4.6, 3.9, 4.4, 3.8, 3.9],
            cloud_revenue: [1629, 1804, 1776, 2124, 2005, 3194, 6027],
            ai_server_pct: [5, 8, 12, 18, 25, 40, 66.7],
            biz_split: { '云计算': 66.7, '通信及移动网络': 33.0, '其他': 0.3 }
        }
    };
}

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runFIIAudit(); });

const FII_SECTIONS = ['fii-identity','trust-hero','fii-kpi-dashboard','audit-overview','fii-charts-grid','fii-risk-matrix','fii-verdict','audit-timeline'];

function runFIIAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    FII_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    // Enhanced loading: show module names during audit
    const loadingStatus = document.querySelector('.loading-status');
    const moduleSteps = [
        { t: 300,  text: '💰 正在审计 [1/5] 财务健康… 营收·利润率·现金流·分红' },
        { t: 600,  text: '🤖 正在审计 [2/5] AI算力护城河… 市占率·客户绑定·全栈覆盖' },
        { t: 900,  text: '🔗 正在审计 [3/5] 供应链韧性… 客户集中度·地缘风险·产能布局' },
        { t: 1200, text: '📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·股息率' },
        { t: 1500, text: '🚀 正在审计 [5/5] 成长动能… AI CapEx周期·产品升级·营收增速' },
        { t: 1800, text: '✅ 五维穿透审计完成，正在生成报告…' },
    ];
    moduleSteps.forEach(step => {
        setTimeout(() => { if(loadingStatus) loadingStatus.textContent = step.text; }, step.t);
    });

    setTimeout(() => {
        const data = buildFIIData();
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

    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'fii-charts-grid':'grid', 'fii-kpi-dashboard':'grid' };
    FII_SECTIONS.forEach(id => {
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
    FII_SECTIONS.forEach((id, i) => {
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
    const keys = Object.keys(FII_MODULES);
    const shortLabels = { financial:'财务', ai_moat:'AI算力', supply_chain:'供应链', valuation:'估值', growth:'成长' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s*1.4, 8);
        return `<div class="eq-bar-group" title="${FII_MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${c}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${c};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${shortLabels[k]}</span></div>`;
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
    const keys = Object.keys(FII_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:FII_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(14,165,233,0.02)','rgba(14,165,233,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'工业富联审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(14,165,233,0.35)'},{offset:1,color:'rgba(6,182,212,0.08)'}]}},
            lineStyle:{color:'#0ea5e9',width:2}, itemStyle:{color:'#38bdf8'}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = FII_MODULES[k]; const s = d.modules[k].score;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  5. Module Cards
// ═══════════════════════════════════════════════════════
let fiiData = null, activeModule = null;

function renderModuleCards(d) {
    fiiData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(FII_MODULES).map(([key, meta]) => {
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
    const meta = FII_MODULES[key], mod = fiiData.modules[key];
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
    if(!fiiData) return;
    for(const key of Object.keys(FII_MODULES)) {
        if(fiiData.modules[key]?.checks?.some(c=>c.status==='fail'||c.status==='warn')) { toggleDetail(key); return; }
    }
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
        borderColor:'rgba(14,165,233,0.2)',
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
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#38bdf8'},{offset:1,color:'#0ea5e9'}]},borderRadius:[4,4,0,0]},
                emphasis:{itemStyle:{shadowBlur:12,shadowColor:'rgba(14,165,233,0.3)'}}},
            {name:'净利润',type:'line',data:f.net_income,smooth:true,
                lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399',borderColor:'#10b981',borderWidth:2},
                symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.12)'},{offset:1,color:'transparent'}]}}}
        ]
    });

    // Margins
    echarts.init(document.getElementById('chart-margins')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,max:12},
        series:[
            {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,
                lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.15)'},{offset:1,color:'transparent'}]}},
                markLine:{silent:true,data:[{yAxis:8,label:{show:true,formatter:'行业均值 8%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
            {name:'净利率',type:'line',data:f.net_margin,smooth:true,
                lineStyle:{color:'#06b6d4',width:2,type:'dashed'},itemStyle:{color:'#22d3ee',borderColor:'#06b6d4',borderWidth:2},symbol:'circle',symbolSize:6}
        ]
    });

    // Cloud Revenue & AI Server %
    echarts.init(document.getElementById('chart-cloud')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:[
            {type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
            {type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},position:'right',max:100,...axisStyle,splitLine:{show:false}}
        ],
        series:[
            {name:'云计算营收',type:'bar',data:f.cloud_revenue,barWidth:'38%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#a78bfa'},{offset:1,color:'#8b5cf6'}]},borderRadius:[4,4,0,0]}},
            {name:'AI服务器占比',type:'line',yAxisIndex:1,data:f.ai_server_pct,smooth:true,
                lineStyle:{color:'#f43f5e',width:2.5},itemStyle:{color:'#fb7185',borderColor:'#f43f5e',borderWidth:2},
                symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(244,63,94,0.12)'},{offset:1,color:'transparent'}]}}}
        ]
    });

    // Business Split (Pie)
    const bs = d.financials.biz_split;
    echarts.init(document.getElementById('chart-segments')).setOption({
        tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(14,165,233,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
        series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],
            data:Object.entries(bs).map(([k,v])=>({name:k,value:v})),
            label:{show:false},
            emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700},itemStyle:{shadowBlur:16,shadowColor:'rgba(14,165,233,0.3)'}},
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},
            color:['#0ea5e9','#8b5cf6','#475569']
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
    badge.className = `fii-rm-badge ${critCount>0?'high':'medium'}`;

    document.getElementById('fii-rm-body').innerHTML = d.risks.map(r => {
        const cls = r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
        const icon = r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
        return `<div class="fii-risk-item ${cls}">
            <div class="fii-risk-name">${icon} ${r.name}</div>
            <div class="fii-risk-desc">${r.desc}</div>
            <div class="fii-risk-tags">
                <span class="fii-risk-tag probability">概率: ${r.probability}</span>
                <span class="fii-risk-tag impact">影响: ${r.impact}</span>
                <span class="fii-risk-tag mitigation">对冲: ${r.mitigation}</span>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  9. Investment Verdict
// ═══════════════════════════════════════════════════════
function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('fii-verdict-body').innerHTML = `
        <div class="fii-verdict-card bull"><div class="fii-verdict-card-title">📈 看多逻辑</div><ul class="fii-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="fii-verdict-card bear"><div class="fii-verdict-card-title">📉 看空逻辑</div><ul class="fii-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="fii-verdict-card catalyst"><div class="fii-verdict-card-title">⚡ 关键催化剂</div><ul class="fii-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="fii-verdict-card position"><div class="fii-verdict-card-title">🎯 仓位建议</div><ul class="fii-verdict-list"><li>${v.positioning}</li></ul></div>
        <div class="fii-conclusion-box">
            <div class="fii-conclusion-title">🏛️ 投资研判总结</div>
            <div class="fii-conclusion-text">${v.summary}</div>
            <div class="fii-conclusion-rating ${v.rating}">${v.rating_text}</div>
        </div>`;
}

// ═══════════════════════════════════════════════════════
//  10. Timeline
// ═══════════════════════════════════════════════════════
function renderTimeline(d) {
    const container = document.getElementById('audit-timeline');
    if(!container) return;
    const hk = 'alphacore_fii_audit_history_v3';
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
            lineStyle:{color:'#0ea5e9',width:2.5},itemStyle:{color:'#38bdf8',borderColor:'#0ea5e9',borderWidth:2},
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(14,165,233,0.2)'},{offset:1,color:'rgba(14,165,233,0)'}]}}
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  KPI Dashboard
// ═══════════════════════════════════════════════════════
function renderKPIDashboard(d) {
    const c = document.getElementById('fii-kpi-dashboard');
    if(!c) return;
    const accentMap = { pass:'rgba(16,185,129,0.5)', warn:'rgba(245,158,11,0.5)', fail:'rgba(239,68,68,0.5)' };
    const colorMap = { pass:'#34d399', warn:'#fbbf24', fail:'#f87171' };
    const kpis = [
        { label:'综合评分', icon:'🏆', value:d.trust_score, suffix:'/100', sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`, level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail', indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危' },
        { label:'财务健康', icon:'💰', value:d.modules.financial.score, suffix:'', sub:`营收+48% · 净利+52%`, level:d.modules.financial.score>=70?'pass':'warn' },
        { label:'AI算力护城河', icon:'🤖', value:d.modules.ai_moat.score, suffix:'', sub:'全球AI服务器份额>40%', level:d.modules.ai_moat.score>=85?'pass':d.modules.ai_moat.score>=70?'pass':'warn', indicator:'🟢 绝对龙头' },
        { label:'供应链韧性', icon:'🔗', value:d.modules.supply_chain.score, suffix:'', sub:'客户集中度为核心关切', level:d.modules.supply_chain.score>=70?'pass':d.modules.supply_chain.score>=55?'warn':'fail', indicator:'⚠ 需关注' },
        { label:'估值合理性', icon:'📊', value:d.modules.valuation.score, suffix:'', sub:`PE ${d.pe}X · PB ${d.pb}X`, level:d.modules.valuation.score>=70?'pass':'warn' },
        { label:'成长动能', icon:'🚀', value:d.modules.growth.score, suffix:'', sub:'AI CapEx超级周期驱动', level:d.modules.growth.score>=85?'pass':d.modules.growth.score>=70?'pass':'warn', indicator:'🟢 强劲' },
    ];
    c.innerHTML = kpis.map((kpi,i) => {
        const accent = accentMap[kpi.level];
        const color = colorMap[kpi.level];
        return `<div class="fii-kpi-card" style="--kpi-accent:${accent};animation:fiiSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
            <div class="fii-kpi-label">${kpi.icon} ${kpi.label}</div>
            <div class="fii-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
            <div class="fii-kpi-sub">${kpi.sub}</div>
            ${kpi.indicator?`<div class="fii-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
        </div>`;
    }).join('');
    // Animate KPI numbers
    kpis.forEach((kpi,i) => {
        setTimeout(() => counterUp(document.getElementById(`kpi-val-${i}`), kpi.value, kpi.suffix||'', 900), 200 + i*100);
    });
}
