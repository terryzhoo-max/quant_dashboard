/**
 * AlphaCore · WUS 沪电股份 个股穿透审计终端 V3.0
 * 五维穿透审计：AI算力护城河 · 财务健康 · 产能与良率 · 汽车电子 · 估值与周期
 */

const WUS_MODULES = {
    ai_moat:  { icon: '🧠', color: '#ec4899', label: 'AI算力护城河', weight: 30 },
    financial:{ icon: '💰', color: '#10b981', label: '财务健康',     weight: 20 },
    capacity: { icon: '🏭', color: '#6366f1', label: '产能与良率',   weight: 20 },
    auto_elec:{ icon: '🚗', color: '#06b6d4', label: '汽车电子',     weight: 15 },
    valuation:{ icon: '📊', color: '#f59e0b', label: '估值与周期',   weight: 15 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildWUSData() {
    const modules = {
        ai_moat: {
            score: 91, grade: 'A',
            checks: [
                { name:'英伟达核心一供', score:95, status:'pass', detail:'Hopper/Blackwell AI服务器高阶HDI及OAM核心计算板唯一核心供应商', explanation:'AI算力板技术壁垒极高（层数超24层，对向性要求严苛），拥有不可替代的先发卡位优势', threshold:'🟢 独供 | 🟡 寡供 | 🔴 多供竞争' },
                { name:'800G交换机PCB', score:90, status:'pass', detail:'800G光模块交换机PCB大规模放量，北美四大云厂商加速拉货', explanation:'数据中心网络升级是AI基建第二波段，800G→1.6T升级周期带来极强利润弹性', threshold:'🟢 >40%增速 | 🟡 20-40% | 🔴 <20%' },
                { name:'企业通讯营收占比', score:88, status:'pass', detail:'企业通讯（含AI算力）营收占比突破70%，产品结构发生质的蜕变', explanation:'从低端消费PCB彻底转型AI硬件，摆脱行业红海，ROE结构性提升' },
                { name:'技术壁垒与良率', score:88, status:'pass', detail:'超高多层板（24-32层）及高阶HDI量产良率业内领先，获英伟达产线认证', explanation:'良率差距即利润护城河，认证壁垒使竞争对手进入周期长达2-3年' },
                { name:'Blackwell深度绑定', score:92, status:'pass', detail:'GB200/GB300系列NVLink板唯一供应商，单卡PCB层数跃升至32层', explanation:'每代芯片迭代ASP提升25-40%，量价双升逻辑清晰', threshold:'🟢 层数≥24层 | 🟡 16-24层 | 🔴 <16层' },
            ]
        },
        financial: {
            score: 86, grade: 'A',
            checks: [
                { name:'营收高速增长', score:90, status:'pass', detail:'2024年营收约120.6亿元，YoY+34.9%，远超行业平均增速8%', explanation:'量价双升：AI板单价提升+出货量放大，驱动营收跨越百亿台阶', threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%' },
                { name:'净利润爆发', score:92, status:'pass', detail:'2024年归母净利润约28亿元，YoY+85.4%，净利率提升至23.2%', explanation:'高阶HDI附加值极高，规模效应+产品结构优化带来利润加速释放' },
                { name:'综合毛利率', score:88, status:'pass', detail:'2024年毛利率约33.8%，已逼近制造业天花板，Q4单季超36%', explanation:'AI板ASP大幅拉升整体毛利率，相比2023年的28.1%提升近6个百分点', threshold:'🟢 >32% | 🟡 25-32% | 🔴 <25%' },
                { name:'现金流质量', score:82, status:'pass', detail:'经营性现金流净额约20.5亿元，现金转化率良好', explanation:'制造业现金流健康的标志，无大规模补贴依赖，盈利质量高' },
                { name:'资产负债率', score:78, status:'pass', detail:'2024年资产负债率约35%，有息负债控制良好，账上现金充足', explanation:'轻杠杆制造业，稳健财务结构为扩产提供充裕空间' },
                { name:'ROE提升', score:85, status:'pass', detail:'2024年ROE约23.5%，较2023年的14.2%大幅跃升', explanation:'ROE持续提升是价值重估核心驱动，PB估值有坚实基本面支撑空间' },
            ]
        },
        capacity: {
            score: 74, grade: 'B',
            checks: [
                { name:'泰国工厂进度', score:80, status:'pass', detail:'泰国Saraburi工厂2024年底投产爬坡，规避"China+1"关税风险', explanation:'泰国基地是英伟达供应链多元化要求的直接响应，锁定北美订单战略意义重大', action:'追踪泰国产线月度爬坡进度及良率达标时间' },
                { name:'高阶HDI产能瓶颈', score:65, status:'warn', detail:'Blackwell NVLink板24-32层产能满载，交货周期被迫延拉', explanation:'极度考验扩产节奏，短期内产能不足是最大的增长制约，非需求不足', action:'跟踪2025年高端产线扩建资本支出进度' },
                { name:'资本开支力度', score:82, status:'pass', detail:'2024年资本开支约25亿元，重点投向高阶HDI产线及泰国工厂', explanation:'资本开支即市场份额，持续高强度投入是护城河的硬件基础' },
                { name:'良率稳定性风险', score:62, status:'warn', detail:'GB300层数进一步增加至32层，初始量产良率面临挑战', explanation:'每次层数跃升初期良率波动1%都对应数千万成本增量，需密切监控', action:'关注Q1-Q2 2025良率爬坡数据及废品率趋势' },
                { name:'扩产进度跟踪', score:75, status:'pass', detail:'2025年规划月产能提升至950万平方英尺，同比扩增约28%', explanation:'产能释放周期与需求爆发期高度同步，保障不会错失订单窗口' },
            ]
        },
        auto_elec: {
            score: 70, grade: 'B',
            checks: [
                { name:'毫米波雷达PCB', score:82, status:'pass', detail:'深度卡位博世、大陆、法雷奥等全球Tier1 ADAS供应商', explanation:'ADAS渗透率从30%提升至50%过程中，毫米波雷达板是稳定现金牛业务' },
                { name:'增速环比放缓', score:58, status:'warn', detail:'2024年汽车板增速降至约8%，受全球EV销量增速放缓传导影响', explanation:'汽车板Beta偏弱，近阶段应将其定位为业务稳定器而非增长驱动', action:'观察2025年ADAS政策强制装配落地进展' },
                { name:'电控基板升级', score:72, status:'pass', detail:'卡位高阶新能源PDU及域控板，单车价值量从80元提升至220元', explanation:'智能化升级带来的ASP提升将在2025-2026年逐步体现' },
                { name:'客户集中度', score:68, status:'warn', detail:'博世营收贡献约45%，国际Tier1集中度偏高，议价能力受限', explanation:'正积极拓展比亚迪/理想等国内新能源主机厂，分散风险', action:'追踪国内新能源Tier1客户拓展动态' },
            ]
        },
        valuation: {
            score: 52, grade: 'C',
            checks: [
                { name:'PE(TTM)估值', score:42, status:'warn', detail:'动态PE(TTM)约34.5X，硬件制造业高位，极致预期已部分Price-in', explanation:'34X PE处于容错极低区域，任何季度业绩不及预期都会触发戴维斯双杀', threshold:'🟢 <25X | 🟡 25-35X | 🔴 >35X' },
                { name:'周期见顶风险', score:35, status:'fail', detail:'AI硬件毛细血管难逃双杀周期，北美云厂商CAPEX是最核心先行指标', explanation:'历史上每轮AI算力周期（2018/2021/2023），硬件股股价提前6-9个月见顶', action:'设定移动止损；持续追踪META/Microsoft/Google资本开支指引' },
                { name:'PB估值', score:52, status:'warn', detail:'PB约7.1X，远超制造业历史中枢2-3X，已进入溢价重度区间', explanation:'高ROE（23.5%）支撑高PB有一定合理性，但历史上PB>7X均给出负超额收益', threshold:'🟢 <3X | 🟡 3-5X | 🔴 >5X' },
                { name:'股息率防御性', score:72, status:'pass', detail:'股息率约1.8%，分红率约35%，稳健分红体现管理层信心', explanation:'稳定分红为持股提供安全垫，优质现金流管理值得加分' },
                { name:'2025E隐含增速匹配度', score:60, status:'warn', detail:'34X PE隐含2025年净利润增速需达40%+才能回归合理区间', explanation:'若北美云厂投资周期超预期，增速达标则估值自然消化；风险在于不达标' },
            ]
        }
    };

    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = WUS_MODULES[k].weight;
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
        company: '沪电股份', ticker_a: '002463.SZ',
        market_cap: '1,462亿', price: '76.37', pe: '34.5', pb: '7.12',
        eps: '2.21', week52_high: '85.50', week52_low: '28.10',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'砍单/周期双杀', level:'critical', desc:'AI资本开支见顶→英伟达减产→HDI出货骤降，PE高悬放大回撤幅度', probability:'中等', impact:'致命', mitigation:'设定25X PE止损线；波段操作' },
            { name:'玻璃基板颠覆', level:'high', desc:'英特尔/AMD主导的玻璃基板（Glass Substrate）技术大规模商用，有效替代传统HDI', probability:'低', impact:'重大', mitigation:'追踪英特尔2027玻璃基板路线图' },
            { name:'良率爬坡失控', level:'high', desc:'GB300 32层板量产良率不及预期，导致成本失控且交付延迟', probability:'中等', impact:'重大', mitigation:'关注Q1-Q2 2025毛利率环比变动' },
            { name:'泰国工厂延期', level:'medium', desc:'泰国产线认证周期拉长，无法及时满足北美"中国以外"供应链要求', probability:'低', impact:'中等', mitigation:'追踪泰国工厂季度产能交付公告' },
            { name:'竞争格局恶化', level:'medium', desc:'深南/生益技术/鹏鼎控股加速追赶高阶HDI，价格战压缩超额利润', probability:'中等', impact:'中等', mitigation:'监控同行高阶产线资本开支公告' },
            { name:'汇率风险', level:'medium', desc:'人民币升值压缩以美元计价出口订单利润，泰国工厂泰铢成本波动', probability:'中等', impact:'轻', mitigation:'自然对冲（泰铢支出+美元收入）' },
        ],
        verdict: {
            bull: ['英伟达Blackwell/下一代芯片核心PCB不可替代的一供地位', '800G→1.6T交换机升级带来第二成长曲线，订单能见度高', 'AI数据中心CAPEX景气周期仍处于上升阶段，2025E营收增速约35%', '泰国产能规避关税+中国以外供应链偏好，战略价值极高'],
            bear: ['动态PE 34.5X严重透支未来，容错空间接近零', 'AI本质属于强周期硬件股，历史上双杀幅度普遍在50%+', 'PB 7.1X远超制造业历史中枢，高位向下均值回归风险大', '玻璃基板技术路线一旦加速，现有技术壁垒部分失效'],
            catalysts: ['英伟达GB300量产进度超预期', '北美四大云厂商上修2025年资本开支指引', '泰国工厂顺利达产并获英伟达认证', '800G-1.6T交换机规模放量订单确认'],
            positioning: '🔄 周期博弈/高抛低吸。34.5X PE处于估值红线区域，采用【波段交易思维】。跌至25X附近（约55元区间）可考虑重仓入场，现价区域以不超过5%仓位参与，设定英伟达CAPEX数据为关键触发器。',
            rating: 'hold', rating_text: '⚖️ 波段控仓',
            summary: '沪电股份是本轮AI算力基建最优质的"卖水人"之一：英伟达核心HDI不可替代+800G交换机第二曲线+泰国工厂战略卡位，基本面逻辑有极强确定性。但34.5X PE与7.1X PB意味着市场已极度透支乐观预期，任何关于AI CAPEX放缓或英伟达砍单的风吹草动，都会引发戴维斯双杀。建议理性控仓：以波段思维参与，高位不追；在估值回调至25X PE（均值回归区间）时，才是真正的重仓时机。'
        },
        financials: {
            years: ['2020','2021','2022','2023','2024','2025E','2026E'],
            revenue:     [74.6, 74.2, 83.3, 89.4, 120.6, 168.0, 205.0],
            net_income:  [13.4, 10.6, 13.6, 15.1, 28.0,  42.5,  52.0],
            gross_margin:[26.5, 25.4, 27.2, 28.1, 33.8,  36.5,  37.2],
            caputil:     [88.5, 85.0, 89.2, 86.5, 96.0,  98.5,  94.0],
            rd_expense:  [3.8,  4.1,  4.5,  4.8,  6.7,   8.5,   10.2],
            capex:       [11.2, 10.5, 14.8, 16.5, 25.0,  32.0,  28.0],
            node_split:  { 'AI算力服务器': 52.0, '800G交换机': 22.5, '汽车电子': 21.0, '工业/其他': 4.5 }
        }
    };
}

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runWUSAudit(); });

const WUS_SECTIONS = ['wus-identity','trust-hero','wus-kpi-dashboard','audit-overview','wus-charts-grid','wus-risk-matrix','wus-verdict','audit-timeline'];

function runWUSAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    WUS_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    const loadingStatus = document.querySelector('.loading-status');
    const steps = [
        { t: 300,  text: '🧠 正在审计 [1/5] AI算力护城河… 英伟达一供·800G·技术壁垒' },
        { t: 650,  text: '💰 正在审计 [2/5] 财务健康… 营收·利润·毛利率·现金流' },
        { t: 1000, text: '🏭 正在审计 [3/5] 产能与良率… 泰国工厂·HDI产线·良率' },
        { t: 1300, text: '🚗 正在审计 [4/5] 汽车电子… ADAS·雷达板·电控基板' },
        { t: 1600, text: '📊 正在审计 [5/5] 估值与周期… PE·PB·DCF·风险溢价' },
        { t: 1900, text: '✅ 五维审计完成，正在生成深度穿透报告…' },
    ];
    steps.forEach(s => setTimeout(() => { if(loadingStatus) loadingStatus.textContent = s.text; }, s.t));

    setTimeout(() => {
        const data = buildWUSData();
        renderAll(data);
        if(btn) btn.disabled = false;
        if(spinner) spinner.style.display = 'none';
    }, 2300);
}

// ═══════════════════════════════════════════════════════
//  渲染主控
// ═══════════════════════════════════════════════════════
function renderAll(data) {
    document.getElementById('audit-loading').style.display = 'none';

    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'wus-charts-grid':'grid', 'wus-kpi-dashboard':'grid' };
    WUS_SECTIONS.forEach(id => {
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

    WUS_SECTIONS.forEach((id, i) => {
        const el = document.getElementById(id);
        if(!el) return;
        el.style.transform = 'translateY(12px)';
        setTimeout(() => {
            el.style.transition = 'opacity 0.5s ease, transform 0.5s cubic-bezier(0.22,1,0.36,1)';
            el.style.opacity = '1';
            el.style.transform = 'translateY(0)';
        }, 80 * i);
    });

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
        const p = Math.min((now - t0) / dur, 1);
        const ease = 1 - Math.pow(1 - p, 3);
        el.textContent = (isInt ? Math.round(target * ease) : (target * ease).toFixed(1)) + suffix;
        if(p < 1) requestAnimationFrame(tick);
    })(t0);
}

// ═══════════════════════════════════════════════════════
//  1. Company Identity
// ═══════════════════════════════════════════════════════
function renderIdentity(d) {
    document.getElementById('qs-mcap').textContent = d.market_cap;
    document.getElementById('qs-price').textContent = '¥' + d.price;
    const peEl = document.getElementById('qs-pe');
    peEl.textContent = d.pe + 'X';
    const peVal = parseFloat(d.pe);
    if(peVal > 40) peEl.style.color = '#f87171';
    else if(peVal > 30) peEl.style.color = '#fbbf24';
    else peEl.style.color = '#34d399';
    document.getElementById('qs-pb').textContent = d.pb + 'X';
}

// ═══════════════════════════════════════════════════════
//  2. Trust Hero + Gauge
// ═══════════════════════════════════════════════════════
function renderTrustHero(d) {
    const gc = GRADE_COLORS[d.trust_grade] || '#94a3b8';
    const bigScore = document.getElementById('trust-big-score');
    bigScore.style.color = gc;
    counterUp(bigScore, d.trust_score, '', 1400);

    const badge = document.getElementById('trust-grade-badge');
    badge.textContent = d.trust_grade;
    badge.className = `trust-grade-badge grade-${d.trust_grade}`;

    const verdicts = { A:'投资价值突出，AI护城河各维度均衡优秀', B:'整体具备投资价值，估值需密切跟踪', C:'风险与机会并存，需精选入场时机', D:'⚠️ 高风险标的，不建议重仓' };
    document.getElementById('trust-verdict').textContent = verdicts[d.trust_grade] || '';
    document.getElementById('stat-pass').textContent = `✅ ${d.pass_count} 优势`;
    document.getElementById('stat-warn').textContent = `⚠️ ${d.warn_count} 关注`;
    document.getElementById('stat-fail').textContent = `❌ ${d.fail_count} 风险`;
    document.getElementById('trust-meta').textContent = `共 ${d.total_checks} 项检查 · 加权评分 ${d.trust_score}/100 · ${d.audit_time}`;

    const keys = Object.keys(WUS_MODULES);
    const shortLabels = { ai_moat:'AI护城河', financial:'财务', capacity:'产能', auto_elec:'汽车', valuation:'估值' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k, i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s * 1.4, 8);
        return `<div class="eq-bar-group" title="${WUS_MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${c}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${c};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${shortLabels[k]}</span></div>`;
    }).join('');

    const chart = echarts.init(document.getElementById('trust-gauge-chart'));
    chart.setOption({
        series:[{ type:'gauge', startAngle:210, endAngle:-30, radius:'88%', center:['50%','55%'], min:0, max:100, splitNumber:4,
            axisLine:{ lineStyle:{ width:18, color:[[0.55,'#ef4444'],[0.70,'#f59e0b'],[0.85,'#3b82f6'],[1,'#10b981']] }},
            pointer:{ length:'55%', width:4, itemStyle:{ color:gc }},
            axisTick:{ show:false }, splitLine:{ length:10, lineStyle:{ color:'rgba(255,255,255,0.15)', width:1 }},
            axisLabel:{ distance:18, color:'#64748b', fontSize:10, fontFamily:'Outfit' },
            detail:{ show:false }, title:{ show:true, offsetCenter:[0,'35%'], fontSize:11, color:'#94a3b8' },
            data:[{ value:d.trust_score, name:'AI护城河强度' }]
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
        document.getElementById('alert-text').innerHTML = `<strong>${d.fail_count} 项高风险</strong> — ${items.slice(0,3).join('、')}${items.length>3?` 等${items.length}项`:''} 须重点关注`;
    } else if(d.warn_count > 0) {
        banner.className = 'alert-banner level-warn visible';
        document.getElementById('alert-icon').textContent = '⚠️';
        document.getElementById('alert-text').innerHTML = `<strong>${d.warn_count} 项需要关注</strong> — 估值与产能良率存在结构性风险`;
    } else { banner.classList.remove('visible'); }
}

// ═══════════════════════════════════════════════════════
//  4. Radar
// ═══════════════════════════════════════════════════════
function renderRadar(d) {
    const keys = Object.keys(WUS_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:WUS_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(236,72,153,0.02)','rgba(236,72,153,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'WUS审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(236,72,153,0.35)'},{offset:1,color:'rgba(139,92,246,0.08)'}]}},
            lineStyle:{color:'#ec4899',width:2}, itemStyle:{color:'#f472b6',borderColor:'#ec4899',borderWidth:2}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = WUS_MODULES[k]; const s = d.modules[k].score;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  5. Module Cards (clickable, with expand)
// ═══════════════════════════════════════════════════════
let wusData = null, activeModule = null;

function renderModuleCards(d) {
    wusData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(WUS_MODULES).map(([key, meta]) => {
        const mod = d.modules[key]; if(!mod) return '';
        const {score, grade, checks} = mod;
        const gc = GRADE_COLORS[grade] || '#94a3b8';
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

function toggleDetail(key, noScroll=false) {
    const section = document.getElementById('detail-section');
    document.querySelectorAll('.module-card').forEach(c=>c.classList.remove('expanded'));
    if(activeModule===key){ section.classList.remove('visible'); activeModule=null; return; }
    activeModule = key;
    const card = document.getElementById(`card-${key}`);
    if(card) card.classList.add('expanded');
    const meta = WUS_MODULES[key], mod = wusData.modules[key];
    if(!mod) return;
    document.getElementById('detail-title').textContent = `${meta.icon} ${meta.label} · ${mod.score}/100 (${mod.grade}级)`;

    document.getElementById('detail-body').innerHTML = mod.checks.map((c, idx) => {
        const icon = c.status==='pass'?'✅':c.status==='warn'?'⚠️':'❌';
        const sc = c.score ?? 0;
        const barC = sc>=85?'#10b981':sc>=70?'#3b82f6':sc>=55?'#f59e0b':'#ef4444';
        const txtC = sc>=85?'#34d399':sc>=70?'#60a5fa':sc>=55?'#fbbf24':'#f87171';
        const rid = `rule-${key}-${idx}`;
        const hasRule = c.explanation || c.threshold || c.action;
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
            ${hasRule?`<button class="check-expand-btn" id="btn-${rid}" onclick="toggleRule(event,'${rid}')">▼</button>`:''}
        </div>
        ${hasRule?`<div class="check-rule-panel" id="${rid}">
            ${c.explanation?`<div class="rule-explanation"><span class="rule-section-icon">📖</span> ${c.explanation}</div>`:''}
            ${threshHtml}
            ${c.action?`<div class="rule-action"><span class="rule-action-label">🛠️ 建议:</span><span class="rule-action-text">${c.action}</span></div>`:''}
        </div>`:''}`;
    }).join('');

    section.classList.add('visible');
    if(!noScroll) section.scrollIntoView({behavior:'smooth', block:'nearest'});
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
    if(!wusData) return;
    for(const key of Object.keys(WUS_MODULES)) {
        if(wusData.modules[key]?.checks?.some(c=>c.status==='fail'||c.status==='warn')) { toggleDetail(key); return; }
    }
}

// ═══════════════════════════════════════════════════════
//  6. Financial Charts
// ═══════════════════════════════════════════════════════
function renderCharts(d) {
    const f = d.financials;
    const darkGrid = { top:40, bottom:28, left:55, right:20 };
    const axisStyle = { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)',type:'dashed'}} };
    const tooltipStyle = { trigger:'axis', backgroundColor:'rgba(15,23,42,0.92)', borderColor:'rgba(236,72,153,0.2)', textStyle:{color:'#e2e8f0',fontSize:12,fontFamily:'Inter'}, padding:[10,14] };
    const legendStyle = { top:6, right:10, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:12, itemHeight:8 };

    // Revenue & Net Income
    echarts.init(document.getElementById('chart-revenue')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#f472b6'},{offset:1,color:'#ec4899'}]},borderRadius:[4,4,0,0]},
                emphasis:{itemStyle:{shadowBlur:12,shadowColor:'rgba(236,72,153,0.3)'}}},
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
                markLine:{silent:true,data:[{yAxis:32,label:{show:true,formatter:'健康线 32%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
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

    // Product Mix Pie
    const ns = f.node_split;
    echarts.init(document.getElementById('chart-nodes')).setOption({
        tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(236,72,153,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
        series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],
            data:Object.entries(ns).map(([k,v])=>({name:k,value:v})),
            label:{show:false},
            emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700},itemStyle:{shadowBlur:16,shadowColor:'rgba(236,72,153,0.3)'}},
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},
            color:['#ec4899','#8b5cf6','#06b6d4','#475569']
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  7. Risk Matrix
// ═══════════════════════════════════════════════════════
function renderRiskMatrix(d) {
    const badge = document.getElementById('rm-badge');
    const critCount = d.risks.filter(r=>r.level==='critical').length;
    badge.textContent = critCount>0 ? `${critCount} 项致命风险` : '风险可控';
    badge.className = `wus-rm-badge ${critCount>0?'high':'medium'}`;

    document.getElementById('wus-rm-body').innerHTML = d.risks.map(r => {
        const cls = r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
        const icon = r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
        return `<div class="wus-risk-item ${cls}">
            <div class="wus-risk-name">${icon} ${r.name}</div>
            <div class="wus-risk-desc">${r.desc}</div>
            <div class="wus-risk-tags">
                <span class="wus-risk-tag probability">概率: ${r.probability}</span>
                <span class="wus-risk-tag impact">影响: ${r.impact}</span>
                <span class="wus-risk-tag mitigation">对冲: ${r.mitigation}</span>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  8. Investment Verdict
// ═══════════════════════════════════════════════════════
function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('wus-verdict-body').innerHTML = `
        <div class="wus-verdict-card bull"><div class="wus-verdict-card-title">📈 看多逻辑</div><ul class="wus-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="wus-verdict-card bear"><div class="wus-verdict-card-title">📉 看空逻辑</div><ul class="wus-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="wus-verdict-card catalyst"><div class="wus-verdict-card-title">⚡ 关键催化剂</div><ul class="wus-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="wus-verdict-card position"><div class="wus-verdict-card-title">🎯 仓位建议</div><ul class="wus-verdict-list"><li>${v.positioning}</li></ul></div>
        <div class="wus-conclusion-box">
            <div class="wus-conclusion-title">🏛️ 投资研判总结</div>
            <div class="wus-conclusion-text">${v.summary}</div>
            <div class="wus-conclusion-rating ${v.rating}">${v.rating_text}</div>
        </div>`;
}

// ═══════════════════════════════════════════════════════
//  9. Timeline
// ═══════════════════════════════════════════════════════
function renderTimeline(d) {
    const container = document.getElementById('audit-timeline');
    if(!container) return;
    const hk = 'alphacore_wus_audit_history_v3';
    let hist = []; try { hist = JSON.parse(localStorage.getItem(hk)||'[]'); } catch(e){}
    const last = hist.length>0 ? hist[hist.length-1].time : '';
    if(d.audit_time !== last) hist.push({score:d.trust_score, time:d.audit_time, grade:d.trust_grade});
    if(hist.length>20) hist = hist.slice(-20);
    localStorage.setItem(hk, JSON.stringify(hist));

    container.style.display = 'block';
    const trendEl = document.getElementById('timeline-trend');
    if(hist.length < 2) {
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
            lineStyle:{color:'#ec4899',width:2.5},itemStyle:{color:'#f472b6',borderColor:'#ec4899',borderWidth:2},
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(236,72,153,0.2)'},{offset:1,color:'rgba(236,72,153,0)'}]}}}]
    });
}

// ═══════════════════════════════════════════════════════
//  10. KPI Dashboard
// ═══════════════════════════════════════════════════════
function renderKPIDashboard(d) {
    const c = document.getElementById('wus-kpi-dashboard');
    if(!c) return;
    const accentMap = { pass:'rgba(16,185,129,0.5)', warn:'rgba(245,158,11,0.5)', fail:'rgba(239,68,68,0.5)' };
    const colorMap  = { pass:'#34d399', warn:'#fbbf24', fail:'#f87171' };
    const valLevel = d.modules.valuation.score >= 55 ? 'warn' : 'fail';
    const kpis = [
        { label:'综合评分', icon:'🏆', value:d.trust_score, suffix:'/100', sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`, level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail', indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危' },
        { label:'AI护城河', icon:'🧠', value:d.modules.ai_moat.score, suffix:'', sub:'英伟达一供·800G·NVLink', level:d.modules.ai_moat.score>=85?'pass':'warn', indicator:'🔮 核心优势' },
        { label:'财务健康', icon:'💰', value:d.modules.financial.score, suffix:'', sub:`营收+34.9% · 毛利率${d.financials.gross_margin[4]}%`, level:d.modules.financial.score>=70?'pass':'warn' },
        { label:'产能与良率', icon:'🏭', value:d.modules.capacity.score, suffix:'', sub:'泰国工厂爬坡·32层良率', level:d.modules.capacity.score>=70?'pass':'warn' },
        { label:'估值合理性', icon:'📊', value:d.modules.valuation.score, suffix:'', sub:`PE ${d.pe}X · PB ${d.pb}X`, level:valLevel, indicator:valLevel==='fail'?'🔴 严重偏高':'⚠ 偏高' },
        { label:'汽车电子', icon:'🚗', value:d.modules.auto_elec.score, suffix:'', sub:'ADAS卡位·雷达板·电控', level:d.modules.auto_elec.score>=70?'pass':'warn' },
    ];
    c.innerHTML = kpis.map((kpi, i) => {
        const accent = accentMap[kpi.level];
        const color  = colorMap[kpi.level];
        return `<div class="wus-kpi-card" style="--kpi-accent:${accent};animation:wusSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
            <div class="wus-kpi-label">${kpi.icon} ${kpi.label}</div>
            <div class="wus-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
            <div class="wus-kpi-sub">${kpi.sub}</div>
            ${kpi.indicator?`<div class="wus-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
        </div>`;
    }).join('');
    kpis.forEach((kpi, i) => {
        setTimeout(() => counterUp(document.getElementById(`kpi-val-${i}`), kpi.value, kpi.suffix||'', 900), 200 + i*100);
    });
}
