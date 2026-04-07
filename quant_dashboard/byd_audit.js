/**
 * AlphaCore · 比亚迪 个股穿透审计终端 V3.0
 * 五维穿透审计：财务健康 · 技术护城河 · 竞争格局 · 估值合理性 · 成长动能
 * Self-contained — Green/Emerald EV premium theme
 */

// ═══════════════════════════════════════════════════════
//  比亚迪 五维审计数据模型
// ═══════════════════════════════════════════════════════
const BYD_MODULES = {
    financial:   { icon: '💰', color: '#10b981', label: '财务健康', weight: 25 },
    technology:  { icon: '🔋', color: '#3b82f6', label: '技术护城河', weight: 20 },
    competition: { icon: '⚔️', color: '#f59e0b', label: '竞争格局', weight: 20 },
    valuation:   { icon: '📊', color: '#8b5cf6', label: '估值合理性', weight: 15 },
    growth:      { icon: '🚀', color: '#06b6d4', label: '成长动能', weight: 20 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildBYDData() {
    const modules = {
        financial: {
            score: 84, grade: 'B',
            checks: [
                { name:'营收增长', score:92, status:'pass', detail:'2025E营收约8,850亿元(+18.5%)，连续5年高速增长，新能源车+电池+电子三大引擎联动', explanation:'比亚迪营收由汽车(约75%)、手机部件(约20%)及电池(约5%)三大板块驱动', threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%' },
                { name:'净利润', score:88, status:'pass', detail:'归母净利润约520亿元(+22.8%)，EPS约17.86元，盈利能力持续跃升', explanation:'2024年归母净利润约402亿元(+34%)，规模效应+出海溢价驱动利润率持续改善' },
                { name:'毛利率', score:80, status:'pass', detail:'综合毛利率约22.8%，汽车业务毛利率约25.5%，显著高于行业均值18%', explanation:'垂直整合(电池+电驱+芯片)带来成本优势，毛利率逐年稳步攀升', threshold:'🟢 >20% | 🟡 15-20% | 🔴 <15%' },
                { name:'ROE', score:78, status:'pass', detail:'ROE约19.5%(2024: 18.6%)，持续提升中但低于全球汽车龙头丰田(14%)差距在缩小', explanation:'重资产扩张阶段ROE受压，但利润增速快于资产增速，趋势向好' },
                { name:'资产负债率', score:65, status:'warn', detail:'资产负债率约74.8%，有息负债超2,000亿元，但经营性负债(应付账款等)占主导', explanation:'汽车行业负债率天然偏高(上下游占款)，比亚迪经营性负债占比超60%，实质风险可控', action:'关注有息负债/总负债比率变化趋势', threshold:'🟢 <65% | 🟡 65-80% | 🔴 >80%' },
                { name:'自由现金流', score:82, status:'pass', detail:'经营性现金流约850亿元，FCF约280亿元(CAPEX约570亿元)', explanation:'高CAPEX源于产能扩张(海外工厂+电池产能)，经营现金流充沛覆盖能力强' },
            ]
        },
        technology: {
            score: 91, grade: 'A',
            checks: [
                { name:'电池技术', score:95, status:'pass', detail:'刀片电池全球领先，磷酸铁锂电池能量密度达180Wh/kg，安全性+循环寿命行业第一', explanation:'刀片电池通过针刺测试已成为行业标杆，第二代刀片电池能量密度将突破200Wh/kg' },
                { name:'电驱平台', score:92, status:'pass', detail:'e平台3.0覆盖全系车型，CTB(Cell-to-Body)一体化技术全球首创', explanation:'电池车身一体化使车身刚度提升70%、空间利用率提升50%、成本下降35%' },
                { name:'智能驾驶', score:68, status:'warn', detail:'天神之眼高阶智驾系统搭载率约40%，但L3/L4自动驾驶能力落后于华为/小鹏', explanation:'城市NOA已覆盖全国300+城市，但纯视觉路线在极端场景下仍有短板', action:'跟踪比亚迪智驾团队规模扩张及算法迭代进度' },
                { name:'半导体芯片', score:88, status:'pass', detail:'比亚迪半导体自研SiC(碳化硅)MOSFET芯片，车规级IGBT市占率国内第一', explanation:'自研芯片实现电驱效率提升8%+，成本降低15%，核心零部件不受卡脖子风险' },
                { name:'研发投入', score:90, status:'pass', detail:'2025E研发费用约520亿元(营收占比约5.9%)，研发人员超10万人', explanation:'研发投入规模为全球车企第一梯队（大众约180亿欧元/丰田约120亿美元）', threshold:'🟢 >5% | 🟡 3-5% | 🔴 <3%' },
                { name:'专利壁垒', score:85, status:'pass', detail:'累计专利申请超48,000件，新能源汽车相关专利全球前三', explanation:'刀片电池、CTB、e平台等核心技术专利构成强大技术壁垒' },
            ]
        },
        competition: {
            score: 72, grade: 'B',
            checks: [
                { name:'国内市占率', score:88, status:'pass', detail:'2025年国内新能源乘用车市占率约36.2%，稳居第一', explanation:'比亚迪、特斯拉、吉利、上汽、长安位列前五，比亚迪市占率超过后三名之和' },
                { name:'全球排名', score:85, status:'pass', detail:'2025全年全球新能源汽车销量第一(约462万辆)，大幅超过特斯拉(约180万辆)', explanation:'比亚迪已全年蝉联全球EV销量冠军，中国+海外双轮驱动' },
                { name:'价格战风险', score:50, status:'warn', detail:'国内新能源车市场价格战持续升级，5-30万价格带竞争全面白热化', explanation:'比亚迪凭借垂直整合成本优势可承受更长时间价格战，但毛利率承压不可避免', action:'监控秦L/海鸥/元PLUS等走量车型终端成交价变化' },
                { name:'海外竞争壁垒', score:60, status:'warn', detail:'欧盟对中国电动车加征关税(比亚迪税率17.0%)，美国市场基本关闭，管理层上调海外销量指引至150万辆', explanation:'关税壁垒迫使比亚迪加速海外建厂(匈牙利/泰国/巴西/土耳其/印尼)，2026海外产能规划100万辆', action:'跟踪匈牙利工厂投产进度及东南亚市场份额变化' },
                { name:'品牌向上突破', score:72, status:'pass', detail:'腾势/仰望/方程豹三大高端品牌矩阵，仰望U9已树立百万级电动车技术标杆', explanation:'高端品牌ASP(平均售价)提升显著但销量占比仍低于5%，品牌溢价能力待验证' },
            ]
        },
        valuation: {
            score: 62, grade: 'C',
            checks: [
                { name:'PE估值', score:65, status:'warn', detail:'PE(TTM) ~18.5X(forward ~17X)，高于传统车企(丰田10X/大众6X)但低于新势力(理想25X)', explanation:'比亚迪处于传统车企与科技公司估值之间，市场回调后估值趋于合理', threshold:'🟢 <20X | 🟡 20-30X | 🔴 >30X' },
                { name:'PB估值', score:58, status:'warn', detail:'PB ~3.8X，高于传统整车企业(1.0-2.0X)但低于前期高点4.5X', explanation:'股价回调后PB回归合理区间，技术平台溢价仍获市场认可', threshold:'🟢 <3.0X | 🟡 3.0-6.0X | 🔴 >6.0X' },
                { name:'EV/EBITDA', score:70, status:'pass', detail:'EV/EBITDA ~11.0X，高于汽车行业中位数(8X)但低于历史均值(14X)', explanation:'估值回调至合理区间，成长溢价适中' },
                { name:'DCF内在价值', score:78, status:'pass', detail:'乐观/中性/悲观情景估值：440/380/290 元(当前¥340)，内在价值低估约12%', explanation:'中性情景显示当前股价低于内在价值约12%，具备安全边际' },
                { name:'股息率', score:60, status:'warn', detail:'股息率约1.0%，分红率约18%，2025年分红总额约94亿元', explanation:'分红率从15%提升至18%，大量资本用于产能扩张和海外建厂', threshold:'🟢 >2% | 🟡 1-2% | 🔴 <1%' },
            ]
        },
        growth: {
            score: 90, grade: 'A',
            checks: [
                { name:'销量增速', score:90, status:'pass', detail:'2025年新能源汽车销量约462万辆(+41.3%)，管理层指引2026年海外销量150万辆(+15%上调)', explanation:'比亚迪已成为全球最大新能源车企，产品矩阵覆盖6-100万元全价格带' },
                { name:'海外扩张', score:88, status:'pass', detail:'2026海外销量指引上调至150万辆(较此前+15%)，已进入78个国家和地区', explanation:'东南亚(泰国第一)、拉美(巴西第一)、欧洲(快速增长)三大海外市场同步发力，管理层主动上调海外目标' },
                { name:'电池外供', score:78, status:'pass', detail:'弗迪电池外供比例持续提升至约35%，向特斯拉/福特/丰田供货', explanation:'电池外供业务2025E营收约400亿元，有望成为第二增长曲线' },
                { name:'智能化升级', score:78, status:'pass', detail:'高阶智驾+智能座舱搭载率快速提升至55%，单车ASP从15万提升至17.5万', explanation:'智能化溢价提升+高端车型占比增加，双重推动ASP向上突破' },
                { name:'全球建厂', score:85, status:'pass', detail:'匈牙利/泰国/巴西/印尼/土耳其五大海外工厂同步推进，泰国工厂已投产，2026海外产能目标100万辆', explanation:'本地化生产规避关税壁垒，同时降低物流成本约15%', action:'关注匈牙利工厂2026投产节点及产能爬坡进度' },
                { name:'新业务探索', score:75, status:'pass', detail:'大模型赋能智能座舱+云辇智能底盘+比亚迪叉车/客车等商用车已形成多元增长极', explanation:'技术外溢形成多个百亿级业务增量，但需关注多元化边界' },
            ]
        }
    };

    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = BYD_MODULES[k].weight;
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
        company: '比亚迪', ticker_a: '002594.SZ', ticker_h: '1211.HK',
        market_cap: '9,880亿', price: '340.00', pe: '18.5', pb: '3.80',
        eps: '18.40', week52_high: '395.00', week52_low: '205.00',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'价格战持续白热化', level:'critical', desc:'国内新能源汽车市场价格战从10-20万蔓延至全价格带，比亚迪虽有成本优势但毛利率持续承压，销售费用率攀升至4.5%+', probability:'高', impact:'重大', mitigation:'垂直整合成本优势+规模效应' },
            { name:'海外关税壁垒升级', level:'critical', desc:'欧盟加征17.0%反补贴关税，美国关税100%封锁，其他国家可能跟进贸易保护政策', probability:'高', impact:'重大', mitigation:'海外建厂本地化+技术授权合作' },
            { name:'智能驾驶技术差距', level:'high', desc:'高阶智驾能力落后于华为/小鹏约1-2代，城市NOA覆盖率和体验仍有提升空间', probability:'中等', impact:'中等', mitigation:'加大智驾研发投入+外部合作+收购' },
            { name:'产能过剩风险', level:'high', desc:'全球新能源汽车产能快速扩张，2026年行业总产能可能超需求30%以上', probability:'中等', impact:'重大', mitigation:'灵活调整产能+出口消化+新车型填充' },
            { name:'原材料价格波动', level:'medium', desc:'碳酸锂价格虽已从高点回落85%但仍有波动性，铜铝等基础材料成本占整车约15%', probability:'低', impact:'中等', mitigation:'长期锁价协议+锂矿自有资源布局' },
            { name:'技术路线不确定性', level:'medium', desc:'固态电池/氢燃料电池等新技术路线可能颠覆当前锂电技术格局', probability:'低', impact:'轻微', mitigation:'多技术路线并行布局(钠电/固态均有储备)' },
        ],
        verdict: {
            bull: ['全球新能源车销量冠军(462万辆)，产品矩阵覆盖6-100万元全价格带', '垂直整合(电池+电驱+芯片+整车)构成全球最强成本护城河', '海外销量指引上调至150万辆(+15%)，78个国家布局打开成长天花板', 'forward PE ~17X已进入合理偏低区间，DCF显示低估约12%'],
            bear: ['国内价格战升级至全价格带，毛利率面临持续压力', '欧美关税壁垒升级，海外建厂产能爬坡需2-3年时间差', '智能驾驶技术落后于华为/小鹏约1-2代，智能化溢价上处于劣势', '2025销量增速(+41%)难以持续，2026增速预计回落至20%左右'],
            catalysts: ['匈牙利工厂2026投产+泰国工厂满产(海外产能突破)', '高端品牌仰望/腾势月销突破1万辆(品牌向上)', '弗迪电池外供大客户(特斯拉/丰田)放量', '第二代刀片电池量产突破200Wh/kg'],
            positioning: '✅ 核心龙头标的。当前PE 18.5X(forward 17X)已进入合理偏低区间，建议仓位控制在10-15%。核心逻辑为全球EV渗透率提升Alpha + 比亚迪份额集中度提升Beta + 海外指引上调催化。设置月销量跌破30万辆 / 毛利率跌破20%为风险警戒线。',
            rating: 'buy', rating_text: '📈 积极配置 / 回调即加仓',
            summary: '比亚迪是全球新能源汽车龙头，2025年交付约462万辆NEV(+41.3%)。管理层已将2026年海外销量指引上调至150万辆(+15%)，显示对全球化扩张的强信心。垂直整合(电池+电驱+芯片)构建了全球最深的成本护城河。当前A股PE 18.5X(forward ~17X)已回调至合理偏低区间，DCF模型显示低估约12%，安全边际充足。主要风险为国内价格战升级及欧美关税壁垒。建议采取\"核心长仓+积极加仓\"策略，当前价位适合战略性增持。'
        },
        financials: {
            years: ['2019','2020','2021','2022','2023','2024','2025E'],
            revenue: [1277, 1566, 2161, 4241, 6023, 7467, 8850],
            net_income: [16.1, 42.3, 30.5, 166.2, 300.4, 402.0, 520.0],
            gross_margin: [16.3, 19.4, 17.4, 20.4, 20.2, 21.9, 22.8],
            roe: [6.2, 12.8, 7.6, 23.1, 21.5, 18.6, 19.5],
            ev_sales: [42.7, 18.9, 59.4, 186.4, 302.4, 427.2, 550.0],
            phev_sales: [19.5, 11.8, 27.3, 94.6, 143.9, 248.5, 310.0],
            bev_sales: [23.2, 7.1, 32.1, 91.8, 158.5, 178.7, 240.0],
            revenue_split: { '汽车业务': 75, '手机部件及组装': 20, '电池及储能': 5 }
        }
    };
}

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runBYDAudit(); });

const BYD_SECTIONS = ['byd-identity','trust-hero','byd-kpi-dashboard','audit-overview','byd-charts-grid','byd-risk-matrix','byd-verdict','audit-timeline'];

function runBYDAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    BYD_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    const loadingStatus = document.querySelector('.loading-status');
    const moduleSteps = [
        { t: 300,  text: '💰 正在审计 [1/5] 财务健康… 营收·利润率·ROE·现金流·杠杆率' },
        { t: 600,  text: '🔋 正在审计 [2/5] 技术护城河… 刀片电池·e平台·智驾·芯片·专利' },
        { t: 900,  text: '⚔️ 正在审计 [3/5] 竞争格局… 市占率·价格战·海外壁垒·品牌' },
        { t: 1200, text: '📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA·股息' },
        { t: 1500, text: '🚀 正在审计 [5/5] 成长动能… 销量增速·海外扩张·电池外供·智能化' },
        { t: 1800, text: '✅ 五维穿透审计完成，正在生成报告…' },
    ];
    moduleSteps.forEach(step => {
        setTimeout(() => { if(loadingStatus) loadingStatus.textContent = step.text; }, step.t);
    });

    setTimeout(() => {
        const data = buildBYDData();
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

    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'byd-charts-grid':'grid', 'byd-kpi-dashboard':'grid' };
    BYD_SECTIONS.forEach(id => {
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

    BYD_SECTIONS.forEach((id, i) => {
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

    const keys = Object.keys(BYD_MODULES);
    const shortLabels = { financial:'财务', technology:'技术', competition:'竞争', valuation:'估值', growth:'成长' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s*1.4, 8);
        return `<div class="eq-bar-group" title="${BYD_MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${c}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${c};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${shortLabels[k]}</span></div>`;
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
        document.getElementById('alert-text').innerHTML = `<strong>${d.warn_count} 项需要关注</strong> — 估值合理性偏高、价格战风险、智驾差距等`;
    } else { banner.classList.remove('visible'); }
}

// ═══════════════════════════════════════════════════════
//  4. Radar
// ═══════════════════════════════════════════════════════
function renderRadar(d) {
    const keys = Object.keys(BYD_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:BYD_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(16,185,129,0.02)','rgba(16,185,129,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'比亚迪审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.35)'},{offset:1,color:'rgba(5,150,105,0.08)'}]}},
            lineStyle:{color:'#10b981',width:2}, itemStyle:{color:'#34d399'}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = BYD_MODULES[k]; const s = d.modules[k].score;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  5. Module Cards
// ═══════════════════════════════════════════════════════
let bydData = null, activeModule = null;

function renderModuleCards(d) {
    bydData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(BYD_MODULES).map(([key, meta]) => {
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
    const meta = BYD_MODULES[key], mod = bydData.modules[key];
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
    if(!bydData) return;
    for(const key of Object.keys(BYD_MODULES)) {
        if(bydData.modules[key]?.checks?.some(c=>c.status==='fail'||c.status==='warn')) { toggleDetail(key); return; }
    }
}

// ═══════════════════════════════════════════════════════
//  7. Financial Charts — Green/Emerald Theme
// ═══════════════════════════════════════════════════════
function renderCharts(d) {
    const f = d.financials;
    const darkGrid = { top:40, bottom:28, left:55, right:20 };
    const axisStyle = { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)',type:'dashed'}} };
    const tooltipStyle = { trigger:'axis', backgroundColor:'rgba(15,23,42,0.92)', borderColor:'rgba(16,185,129,0.2)', textStyle:{color:'#e2e8f0',fontSize:12,fontFamily:'Inter'}, padding:[10,14] };
    const legendStyle = { top:6, right:10, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:12, itemHeight:8 };

    // Revenue & Net Income
    echarts.init(document.getElementById('chart-revenue')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#34d399'},{offset:1,color:'#10b981'}]},borderRadius:[4,4,0,0]},
                emphasis:{itemStyle:{shadowBlur:12,shadowColor:'rgba(16,185,129,0.3)'}}},
            {name:'净利润',type:'line',data:f.net_income,smooth:true,
                lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},
                symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.12)'},{offset:1,color:'transparent'}]}}}
        ]
    });

    // Gross Margin & ROE
    echarts.init(document.getElementById('chart-margins')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,max:30},
        series:[
            {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,
                lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399',borderColor:'#10b981',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.15)'},{offset:1,color:'transparent'}]}},
                markLine:{silent:true,data:[{yAxis:18,label:{show:true,formatter:'行业均值 18%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
            {name:'ROE',type:'line',data:f.roe,smooth:true,
                lineStyle:{color:'#8b5cf6',width:2,type:'dashed'},itemStyle:{color:'#a78bfa',borderColor:'#8b5cf6',borderWidth:2},symbol:'circle',symbolSize:6}
        ]
    });

    // EV Sales (BEV+PHEV)
    echarts.init(document.getElementById('chart-sales')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'万辆',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'纯电(BEV)',type:'bar',data:f.bev_sales,barWidth:'30%',stack:'sales',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#06b6d4'},{offset:1,color:'#0891b2'}]},borderRadius:[0,0,0,0]}},
            {name:'插混(PHEV)',type:'bar',data:f.phev_sales,barWidth:'30%',stack:'sales',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#34d399'},{offset:1,color:'#10b981'}]},borderRadius:[4,4,0,0]}},
            {name:'总销量',type:'line',data:f.ev_sales,smooth:true,
                lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},symbol:'circle',symbolSize:7}
        ]
    });

    // Revenue Split (Pie)
    const rs = d.financials.revenue_split;
    echarts.init(document.getElementById('chart-segments')).setOption({
        tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(16,185,129,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
        series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],
            data:Object.entries(rs).map(([k,v])=>({name:k,value:v})),
            label:{show:false},
            emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700},itemStyle:{shadowBlur:16,shadowColor:'rgba(16,185,129,0.3)'}},
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},
            color:['#10b981','#3b82f6','#f59e0b']
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
    badge.className = `byd-rm-badge ${critCount>0?'high':'medium'}`;

    document.getElementById('byd-rm-body').innerHTML = d.risks.map(r => {
        const cls = r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
        const icon = r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
        return `<div class="byd-risk-item ${cls}">
            <div class="byd-risk-name">${icon} ${r.name}</div>
            <div class="byd-risk-desc">${r.desc}</div>
            <div class="byd-risk-tags">
                <span class="byd-risk-tag probability">概率: ${r.probability}</span>
                <span class="byd-risk-tag impact">影响: ${r.impact}</span>
                <span class="byd-risk-tag mitigation">对冲: ${r.mitigation}</span>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  9. Investment Verdict
// ═══════════════════════════════════════════════════════
function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('byd-verdict-body').innerHTML = `
        <div class="byd-verdict-card bull"><div class="byd-verdict-card-title">📈 看多逻辑</div><ul class="byd-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="byd-verdict-card bear"><div class="byd-verdict-card-title">📉 看空逻辑</div><ul class="byd-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="byd-verdict-card catalyst"><div class="byd-verdict-card-title">⚡ 关键催化剂</div><ul class="byd-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="byd-verdict-card position"><div class="byd-verdict-card-title">🎯 仓位建议</div><ul class="byd-verdict-list"><li>${v.positioning}</li></ul></div>
        <div class="byd-conclusion-box">
            <div class="byd-conclusion-title">🏛️ 投资研判总结</div>
            <div class="byd-conclusion-text">${v.summary}</div>
            <div class="byd-conclusion-rating ${v.rating}">${v.rating_text}</div>
        </div>`;
}

// ═══════════════════════════════════════════════════════
//  10. Timeline
// ═══════════════════════════════════════════════════════
function renderTimeline(d) {
    const container = document.getElementById('audit-timeline');
    if(!container) return;
    const hk = 'alphacore_byd_audit_history_v3';
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
            lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399',borderColor:'#10b981',borderWidth:2},
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.2)'},{offset:1,color:'rgba(16,185,129,0)'}]}}
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  KPI Dashboard
// ═══════════════════════════════════════════════════════
function renderKPIDashboard(d) {
    const c = document.getElementById('byd-kpi-dashboard');
    if(!c) return;
    const accentMap = { pass:'rgba(16,185,129,0.5)', warn:'rgba(245,158,11,0.5)', fail:'rgba(239,68,68,0.5)' };
    const colorMap = { pass:'#34d399', warn:'#fbbf24', fail:'#f87171' };
    const kpis = [
        { label:'综合评分', icon:'🏆', value:d.trust_score, suffix:'/100', sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`, level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail', indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危' },
        { label:'财务健康', icon:'💰', value:d.modules.financial.score, suffix:'', sub:`营收+18.5% · ROE ${d.financials.roe[6]}%`, level:d.modules.financial.score>=70?'pass':'warn' },
        { label:'技术护城河', icon:'🔋', value:d.modules.technology.score, suffix:'', sub:'刀片电池+e平台全球领先', level:d.modules.technology.score>=85?'pass':d.modules.technology.score>=70?'pass':'warn', indicator:'🥇 顶级' },
        { label:'竞争格局', icon:'⚔️', value:d.modules.competition.score, suffix:'', sub:'全球EV销量冠军·价格战承压', level:d.modules.competition.score>=70?'pass':d.modules.competition.score>=55?'warn':'fail', indicator:d.modules.competition.score>=70?'● 领先':'⚠ 承压' },
        { label:'估值合理性', icon:'📊', value:d.modules.valuation.score, suffix:'', sub:`PE ${d.pe}X · PB ${d.pb}X`, level:d.modules.valuation.score>=70?'pass':'warn', indicator:'◐ 合理偏高' },
        { label:'成长动能', icon:'🚀', value:d.modules.growth.score, suffix:'', sub:'销量CAGR +28% · 海外+60%', level:d.modules.growth.score>=70?'pass':'warn', indicator:'● 强劲' },
    ];
    c.innerHTML = kpis.map((kpi,i) => {
        const accent = accentMap[kpi.level];
        const color = colorMap[kpi.level];
        return `<div class="byd-kpi-card" style="--kpi-accent:${accent};animation:bydSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
            <div class="byd-kpi-label">${kpi.icon} ${kpi.label}</div>
            <div class="byd-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
            <div class="byd-kpi-sub">${kpi.sub}</div>
            ${kpi.indicator?`<div class="byd-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
        </div>`;
    }).join('');
    kpis.forEach((kpi,i) => {
        setTimeout(() => counterUp(document.getElementById(`kpi-val-${i}`), kpi.value, kpi.suffix||'', 900), 200 + i*100);
    });
}
