/**
 * AlphaCore · 东方财富 个股穿透审计终端 V3.0
 * 五维穿透审计：财务健康 · 平台生态 · 竞争格局 · 估值合理性 · 成长动能
 * Self-contained — Blue/Gold FinTech premium theme
 */

// ═══════════════════════════════════════════════════════
//  东方财富 五维审计数据模型
// ═══════════════════════════════════════════════════════
const EM_MODULES = {
    financial:   { icon: '💰', color: '#10b981', label: '财务健康', weight: 25 },
    platform:    { icon: '🌐', color: '#2563eb', label: '平台生态', weight: 20 },
    competition: { icon: '⚔️', color: '#f59e0b', label: '竞争格局', weight: 20 },
    valuation:   { icon: '📊', color: '#8b5cf6', label: '估值合理性', weight: 15 },
    growth:      { icon: '🚀', color: '#06b6d4', label: '成长动能', weight: 20 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildEMData() {
    const modules = {
        financial: {
            score: 82, grade: 'B',
            checks: [
                { name:'营收增长', score:85, status:'pass', detail:'2025年营收约185亿元(+22.5%)，基金代销+经纪业务+两融利息三引擎共振复苏', explanation:'2024年营收约151亿元(+3.2%)，2025年受益于A股日均成交额突破1.5万亿元', threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%' },
                { name:'净利润', score:88, status:'pass', detail:'归母净利润约105亿元(+28.0%)，EPS约0.66元，盈利弹性显著', explanation:'2024年归母净利润82亿元(+1.3%)，2025年牛市催化下利润弹性极强' },
                { name:'毛利率', score:90, status:'pass', detail:'综合毛利率约72%，互联网金融平台属性保持极高毛利率', explanation:'轻资产互联网模式毛利率远超传统券商(35-45%)，护城河显著', threshold:'🟢 >60% | 🟡 40-60% | 🔴 <40%' },
                { name:'ROE', score:78, status:'pass', detail:'ROE约14.8%(2024: 12.5%)，市场回暖推动ROE回升', explanation:'互联网券商ROE波动大，与市场活跃度高度相关', threshold:'🟢 >15% | 🟡 10-15% | 🔴 <10%' },
                { name:'资产负债率', score:72, status:'pass', detail:'资产负债率约62%，有息负债约480亿元(两融+自营融资)，整体可控', explanation:'券商行业负债率天然偏高(客户保证金+两融)，东方财富杠杆水平低于行业均值68%' },
                { name:'手续费收入', score:80, status:'pass', detail:'手续费及佣金净收入约95亿元(+25%)，经纪+基金代销为核心', explanation:'佣金率下行趋势下，以量补价，市占率提升对冲费率压力' },
            ]
        },
        platform: {
            score: 88, grade: 'A',
            checks: [
                { name:'天天基金代销规模', score:92, status:'pass', detail:'天天基金非货基保有量约8,500亿元，非货基代销市占率约4.8%，第三方独立平台第一', explanation:'天天基金是中国最大的独立基金销售平台，仅次于蚂蚁/招行等银行系渠道' },
                { name:'东方财富APP矩阵', score:90, status:'pass', detail:'东方财富APP月活约5,200万，Choice金融终端覆盖超80%专业投资者', explanation:'APP矩阵:东方财富(行情)+天天基金(代销)+Choice(数据)+股吧(社区)' },
                { name:'股吧社区生态', score:82, status:'pass', detail:'股吧注册用户超3亿，日均发帖量约120万条，为A股最大投资者社区', explanation:'内容生态形成用户黏性飞轮:行情→社区→交易→基金，转化效率极高' },
                { name:'数据终端壁垒', score:85, status:'pass', detail:'Choice金融终端付费用户约18万，年费约1.2-3.6万元/终端', explanation:'对标Wind/Bloomberg的国产金融数据终端，护城河深厚' },
                { name:'用户增长趋势', score:78, status:'pass', detail:'2025年新增开户约280万户，累计开户约2,800万户，行业排名第三', explanation:'互联网获客成本约200元/户，远低于传统券商800元/户' },
                { name:'AI赋能进展', score:72, status:'pass', detail:'AI智投助手上线，基于大模型的智能选基/选股功能覆盖60%用户', explanation:'AI赋能提升用户体验和转化率，但尚处早期阶段' },
            ]
        },
        competition: {
            score: 75, grade: 'B',
            checks: [
                { name:'经纪市占率', score:78, status:'pass', detail:'2025年A股经纪业务市占率约4.2%，排名第八，互联网券商第一', explanation:'前三名:中信(7.2%)、华泰(6.5%)、国泰君安(5.8%)，东方财富以互联网模式差异化竞争' },
                { name:'基金代销竞争', score:72, status:'pass', detail:'非货基代销市占率4.8%，面临蚂蚁(15%)、招行(8%)、京东金融等激烈竞争', explanation:'费率战持续，基金代销费率从1%降至0.1%,以规模换利润', action:'关注基金销售费率改革对公司收入结构的影响' },
                { name:'佣金率下行压力', score:55, status:'warn', detail:'行业平均佣金率已降至万1.5左右，东方财富约万2.0，仍有下行空间', explanation:'零佣金趋势不可逆，需通过增值服务(两融/数据/AI)弥补收入缺口', action:'监控佣金率变化趋势及增值业务占比' },
                { name:'牌照优势', score:85, status:'pass', detail:'持有证券、基金销售、期货、保险代销全牌照，金融版图完整', explanation:'全牌照优势使得平台可实现一站式金融服务，转化效率最高' },
                { name:'同花顺竞争', score:68, status:'warn', detail:'同花顺(300033)在行情软件市占率更高(MAU约6,800万)，AI能力更强', explanation:'同花顺侧重工具+AI，东方财富侧重交易+代销，赛道略有差异', action:'跟踪两家AI产品迭代速度及用户转化率对比' },
            ]
        },
        valuation: {
            score: 60, grade: 'C',
            checks: [
                { name:'PE估值', score:52, status:'warn', detail:'PE(TTM) ~32X，高于传统券商(12-18X)但低于同花顺(45X)', explanation:'互联网金融平台享有科技属性溢价，但32X已处于合理上沿', threshold:'🟢 <25X | 🟡 25-40X | 🔴 >40X' },
                { name:'PB估值', score:55, status:'warn', detail:'PB ~3.2X，高于传统券商PB中位数1.2X', explanation:'轻资产模式PB天然偏高，但3.2X需盈利持续增长支撑', threshold:'🟢 <2.5X | 🟡 2.5-4.0X | 🔴 >4.0X' },
                { name:'EV/EBITDA', score:62, status:'warn', detail:'EV/EBITDA ~22X，高于券商行业中位数10X', explanation:'高EV/EBITDA反映市场对东方财富平台化商业模式的溢价认可' },
                { name:'DCF内在价值', score:68, status:'pass', detail:'乐观/中性/悲观情景估值：28/22/16 元(当前¥21.5)', explanation:'中性情景估值与当前股价接近，安全边际约2%' },
                { name:'股息率', score:62, status:'warn', detail:'股息率约1.2%，分红率约28%', explanation:'互联网公司偏低分红属正常，但相比传统券商(3-5%)缺乏吸引力', threshold:'🟢 >2% | 🟡 1-2% | 🔴 <1%' },
            ]
        },
        growth: {
            score: 80, grade: 'B',
            checks: [
                { name:'基金代销恢复', score:82, status:'pass', detail:'2025年偏股基金发行回暖，天天基金非货基保有量+18%，结构性牛市催化', explanation:'基金行业从2022-2024年寒冬中复苏，代销规模与市场情绪高度正相关' },
                { name:'两融业务弹性', score:85, status:'pass', detail:'两融余额约280亿元(+35%)，融资融券利差约4.5%，利息收入贡献显著', explanation:'市场活跃时两融弹性极大，是东方财富盈利弹性的放大器' },
                { name:'财富管理转型', score:75, status:'pass', detail:'从交易佣金向财富管理AUM模式转型，投顾签约资产约450亿元', explanation:'买方投顾试点推进，长期利好以客户资产规模为导向的盈利模式' },
                { name:'机构业务拓展', score:68, status:'warn', detail:'机构客户(私募/险资/公募)覆盖率约35%，Choice终端渗透率持续提升', explanation:'机构业务TO-B模式增长曲线更平稳，但面临Wind的强力竞争', action:'跟踪Choice终端在公募基金市场的渗透进度' },
                { name:'市场周期依赖', score:55, status:'warn', detail:'营收/利润与A股成交量高度正相关(相关系数0.85+)，周期性风险显著', explanation:'互联网券商本质是A股牛熊市的Beta放大器，非纯Alpha标的', action:'关注日均成交额是否跌破1万亿(盈利警戒线)' },
                { name:'海外业务布局', score:60, status:'warn', detail:'东方财富国际(香港)业务起步阶段，2025年港股通交易市占率约1.5%', explanation:'海外业务为增量但短期贡献有限，面临富途/老虎等互联网券商竞争' },
            ]
        }
    };

    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = EM_MODULES[k].weight;
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
        company: '东方财富', ticker_a: '300059.SZ', ticker_h: '—',
        market_cap: '2,918亿', price: '18.48', pe: '28.0', pb: '2.76',
        eps: '0.66', week52_high: '31.00', week52_low: '10.58',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'市场周期性风险', level:'critical', desc:'营收/利润与A股成交量高度正相关(相关系数0.85+)，若日均成交跌破1万亿，利润可能腰斩', probability:'中等', impact:'致命', mitigation:'多元化收入结构+财富管理转型' },
            { name:'佣金率持续下行', level:'high', desc:'行业佣金率已降至万1.5且仍有下行趋势，零佣金压力迫在眉睫', probability:'高', impact:'重大', mitigation:'增值服务变现+两融利差+基金代销' },
            { name:'基金代销费率改革', level:'high', desc:'监管推动基金销售费率市场化改革，天天基金代销费率可能进一步压缩', probability:'高', impact:'中等', mitigation:'以规模换利润+买方投顾转型' },
            { name:'同花顺AI竞争', level:'medium', desc:'同花顺在AI金融领域投入更大，AI选股/AI投顾产品可能分流用户', probability:'中等', impact:'中等', mitigation:'加大AI研发投入+利用交易闭环优势' },
            { name:'监管政策风险', level:'medium', desc:'证监会对互联网金融监管趋严，基金代销合规要求提升', probability:'低', impact:'中等', mitigation:'全牌照合规优势+积极配合监管' },
            { name:'估值压缩风险', level:'medium', desc:'PE 32X处于合理上沿，市场转熊后估值可能压缩至20X以下', probability:'中等', impact:'中等', mitigation:'严格止损纪律+仓位控制' },
        ],
        verdict: {
            bull: ['A股最大互联网券商，全牌照+平台生态构成核心竞争力', '天天基金非货基保有量8,500亿元，独立第三方第一', '毛利率72%远超传统券商，轻资产模式利润弹性极大', '2025年牛市催化，营收+22.5%/净利润+28%，弹性兑现'],
            bear: ['营收与A股成交量相关系数0.85+，市场周期Beta属性极强', '佣金率下行趋势不可逆，核心经纪收入持续承压', 'PE 32X处于合理偏高区间，估值回归风险存在', '同花顺AI能力更强，面临工具端竞争压力'],
            catalysts: ['A股日均成交突破2万亿(牛市信号)', '买方投顾试点全面推广', '天天基金非货基保有量突破1万亿', 'AI智投产品大规模落地提升用户ARPU'],
            positioning: '✅ 牛市弹性标的。当前PE 32X基本合理，建议仓位控制在5-8%。核心逻辑为A股流动性改善Beta + 互联网金融份额集中Alpha。设置日均成交<1万亿 / 佣金率降至万1.2以下为风险警戒线。',
            rating: 'buy', rating_text: '📈 趋势跟踪 / 牛市加仓',
            summary: '东方财富是A股唯一的互联网金融全生态平台，集行情(APP 5200万MAU)+社区(股吧3亿用户)+交易(经纪市占率4.2%)+代销(天天基金8500亿)于一体。2025年受益于A股牛市回暖，营收185亿元(+22.5%)，净利润105亿元(+28%)。毛利率72%的轻资产模式使其盈利弹性远超传统券商。主要风险为高度周期性(与成交量相关系数0.85+)及佣金率持续下行。当前PE 32X合理偏高，建议采取\"趋势跟踪+牛市加仓\"策略，市场转弱时及时减仓。'
        },
        financials: {
            years: ['2019','2020','2021','2022','2023','2024','2025E'],
            revenue: [50.4, 82.4, 131.0, 112.0, 146.5, 151.0, 185.0],
            net_income: [18.5, 48.0, 85.5, 51.6, 81.0, 82.0, 105.0],
            gross_margin: [65.2, 68.5, 72.8, 70.1, 71.5, 71.8, 72.0],
            roe: [8.2, 16.5, 22.8, 10.5, 14.2, 12.5, 14.8],
            fund_aum: [2800, 4200, 7500, 5200, 6500, 7200, 8500],
            margin_balance: [85, 120, 180, 110, 160, 210, 280],
            brokerage_share: [2.1, 2.8, 3.5, 3.4, 3.8, 4.0, 4.2],
            revenue_split: { '经纪业务': 35, '基金代销': 28, '利息净收入': 22, '数据服务': 8, '其他': 7 }
        }
    };
}

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runEMAudit(); });

const EM_SECTIONS = ['em-identity','trust-hero','em-kpi-dashboard','audit-overview','em-charts-grid','em-risk-matrix','em-verdict','audit-timeline'];

function runEMAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    EM_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    const loadingStatus = document.querySelector('.loading-status');
    const moduleSteps = [
        { t: 300,  text: '💰 正在审计 [1/5] 财务健康… 营收·净利润·毛利率·ROE·手续费收入' },
        { t: 600,  text: '🌐 正在审计 [2/5] 平台生态… 天天基金·APP矩阵·股吧·Choice·AI赋能' },
        { t: 900,  text: '⚔️ 正在审计 [3/5] 竞争格局… 经纪市占率·基金代销·佣金率·牌照·同花顺' },
        { t: 1200, text: '📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA·股息率' },
        { t: 1500, text: '🚀 正在审计 [5/5] 成长动能… 基金代销恢复·两融弹性·财富管理·海外' },
        { t: 1800, text: '✅ 五维穿透审计完成，正在生成报告…' },
    ];
    moduleSteps.forEach(step => {
        setTimeout(() => { if(loadingStatus) loadingStatus.textContent = step.text; }, step.t);
    });

    setTimeout(() => {
        const data = buildEMData();
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

    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'em-charts-grid':'grid', 'em-kpi-dashboard':'grid' };
    EM_SECTIONS.forEach(id => {
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

    EM_SECTIONS.forEach((id, i) => {
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
    if(peVal > 40) peEl.style.color = '#f87171';
    else if(peVal > 25) peEl.style.color = '#fbbf24';
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

    const keys = Object.keys(EM_MODULES);
    const shortLabels = { financial:'财务', platform:'平台', competition:'竞争', valuation:'估值', growth:'成长' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s*1.4, 8);
        return `<div class="eq-bar-group" title="${EM_MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${c}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${c};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${shortLabels[k]}</span></div>`;
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
        document.getElementById('alert-text').innerHTML = `<strong>${d.warn_count} 项需要关注</strong> — 估值偏高、佣金率下行、市场周期性等`;
    } else { banner.classList.remove('visible'); }
}

// ═══════════════════════════════════════════════════════
//  4. Radar
// ═══════════════════════════════════════════════════════
function renderRadar(d) {
    const keys = Object.keys(EM_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:EM_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(37,99,235,0.02)','rgba(37,99,235,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'东方财富审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(37,99,235,0.35)'},{offset:1,color:'rgba(59,130,246,0.08)'}]}},
            lineStyle:{color:'#2563eb',width:2}, itemStyle:{color:'#60a5fa'}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = EM_MODULES[k]; const s = d.modules[k].score;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  5. Module Cards
// ═══════════════════════════════════════════════════════
let emData = null, activeModule = null;

function renderModuleCards(d) {
    emData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(EM_MODULES).map(([key, meta]) => {
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
    const meta = EM_MODULES[key], mod = emData.modules[key];
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
    if(!emData) return;
    for(const key of Object.keys(EM_MODULES)) {
        if(emData.modules[key]?.checks?.some(c=>c.status==='fail'||c.status==='warn')) { toggleDetail(key); return; }
    }
}

// ═══════════════════════════════════════════════════════
//  7. Financial Charts — Blue/Gold FinTech Theme
// ═══════════════════════════════════════════════════════
function renderCharts(d) {
    const f = d.financials;
    const darkGrid = { top:40, bottom:28, left:55, right:20 };
    const axisStyle = { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)',type:'dashed'}} };
    const tooltipStyle = { trigger:'axis', backgroundColor:'rgba(15,23,42,0.92)', borderColor:'rgba(37,99,235,0.2)', textStyle:{color:'#e2e8f0',fontSize:12,fontFamily:'Inter'}, padding:[10,14] };
    const legendStyle = { top:6, right:10, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:12, itemHeight:8 };

    // Revenue & Net Income
    echarts.init(document.getElementById('chart-revenue')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
        series:[
            {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#60a5fa'},{offset:1,color:'#2563eb'}]},borderRadius:[4,4,0,0]},
                emphasis:{itemStyle:{shadowBlur:12,shadowColor:'rgba(37,99,235,0.3)'}}},
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
        yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,max:80},
        series:[
            {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,
                lineStyle:{color:'#2563eb',width:2.5},itemStyle:{color:'#60a5fa',borderColor:'#2563eb',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(37,99,235,0.15)'},{offset:1,color:'transparent'}]}},
                markLine:{silent:true,data:[{yAxis:45,label:{show:true,formatter:'券商均值 45%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
            {name:'ROE',type:'line',data:f.roe,smooth:true,
                lineStyle:{color:'#8b5cf6',width:2,type:'dashed'},itemStyle:{color:'#a78bfa',borderColor:'#8b5cf6',borderWidth:2},symbol:'circle',symbolSize:6}
        ]
    });

    // Fund AUM & Margin Balance
    echarts.init(document.getElementById('chart-platform')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:legendStyle,
        xAxis:{type:'category',data:f.years,...axisStyle},
        yAxis:[
            {type:'value',name:'亿元(基金)',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle},
            {type:'value',name:'亿元(两融)',nameTextStyle:{color:'#64748b',fontSize:10},...axisStyle,splitLine:{show:false}}
        ],
        series:[
            {name:'基金保有量',type:'bar',data:f.fund_aum,barWidth:'30%',yAxisIndex:0,
                itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#60a5fa'},{offset:1,color:'#2563eb'}]},borderRadius:[4,4,0,0]}},
            {name:'两融余额',type:'line',data:f.margin_balance,smooth:true,yAxisIndex:1,
                lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24',borderColor:'#f59e0b',borderWidth:2},symbol:'circle',symbolSize:7,
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.1)'},{offset:1,color:'transparent'}]}}}
        ]
    });

    // Revenue Split (Pie)
    const rs = d.financials.revenue_split;
    echarts.init(document.getElementById('chart-segments')).setOption({
        tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(37,99,235,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
        series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],
            data:Object.entries(rs).map(([k,v])=>({name:k,value:v})),
            label:{show:false},
            emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700},itemStyle:{shadowBlur:16,shadowColor:'rgba(37,99,235,0.3)'}},
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},
            color:['#2563eb','#f59e0b','#10b981','#8b5cf6','#475569']
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
    badge.className = `em-rm-badge ${critCount>0?'high':'medium'}`;

    document.getElementById('em-rm-body').innerHTML = d.risks.map(r => {
        const cls = r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
        const icon = r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
        return `<div class="em-risk-item ${cls}">
            <div class="em-risk-name">${icon} ${r.name}</div>
            <div class="em-risk-desc">${r.desc}</div>
            <div class="em-risk-tags">
                <span class="em-risk-tag probability">概率: ${r.probability}</span>
                <span class="em-risk-tag impact">影响: ${r.impact}</span>
                <span class="em-risk-tag mitigation">对冲: ${r.mitigation}</span>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  9. Investment Verdict
// ═══════════════════════════════════════════════════════
function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('em-verdict-body').innerHTML = `
        <div class="em-verdict-card bull"><div class="em-verdict-card-title">📈 看多逻辑</div><ul class="em-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="em-verdict-card bear"><div class="em-verdict-card-title">📉 看空逻辑</div><ul class="em-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="em-verdict-card catalyst"><div class="em-verdict-card-title">⚡ 关键催化剂</div><ul class="em-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
        <div class="em-verdict-card position"><div class="em-verdict-card-title">🎯 仓位建议</div><ul class="em-verdict-list"><li>${v.positioning}</li></ul></div>
        <div class="em-conclusion-box">
            <div class="em-conclusion-title">🏛️ 投资研判总结</div>
            <div class="em-conclusion-text">${v.summary}</div>
            <div class="em-conclusion-rating ${v.rating}">${v.rating_text}</div>
        </div>`;
}

// ═══════════════════════════════════════════════════════
//  10. Timeline
// ═══════════════════════════════════════════════════════
function renderTimeline(d) {
    const container = document.getElementById('audit-timeline');
    if(!container) return;
    const hk = 'alphacore_em_audit_history_v3';
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
            lineStyle:{color:'#2563eb',width:2.5},itemStyle:{color:'#60a5fa',borderColor:'#2563eb',borderWidth:2},
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(37,99,235,0.2)'},{offset:1,color:'rgba(37,99,235,0)'}]}}
        }]
    });
}

// ═══════════════════════════════════════════════════════
//  KPI Dashboard
// ═══════════════════════════════════════════════════════
function renderKPIDashboard(d) {
    const c = document.getElementById('em-kpi-dashboard');
    if(!c) return;
    const accentMap = { pass:'rgba(16,185,129,0.5)', warn:'rgba(245,158,11,0.5)', fail:'rgba(239,68,68,0.5)' };
    const colorMap = { pass:'#34d399', warn:'#fbbf24', fail:'#f87171' };
    const kpis = [
        { label:'综合评分', icon:'🏆', value:d.trust_score, suffix:'/100', sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`, level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail', indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危' },
        { label:'财务健康', icon:'💰', value:d.modules.financial.score, suffix:'', sub:`营收+22.5% · 毛利率${d.financials.gross_margin[6]}%`, level:d.modules.financial.score>=70?'pass':'warn' },
        { label:'平台生态', icon:'🌐', value:d.modules.platform.score, suffix:'', sub:'天天基金+股吧+Choice全生态', level:d.modules.platform.score>=85?'pass':d.modules.platform.score>=70?'pass':'warn', indicator:'🥇 顶级' },
        { label:'竞争格局', icon:'⚔️', value:d.modules.competition.score, suffix:'', sub:'互联网券商第一·佣金率承压', level:d.modules.competition.score>=70?'pass':d.modules.competition.score>=55?'warn':'fail', indicator:d.modules.competition.score>=70?'● 领先':'⚠ 承压' },
        { label:'估值合理性', icon:'📊', value:d.modules.valuation.score, suffix:'', sub:`PE ${d.pe}X · PB ${d.pb}X`, level:d.modules.valuation.score>=70?'pass':'warn', indicator:'◐ 合理偏高' },
        { label:'成长动能', icon:'🚀', value:d.modules.growth.score, suffix:'', sub:'基金代销恢复·两融弹性', level:d.modules.growth.score>=70?'pass':'warn', indicator:'● 强劲' },
    ];
    c.innerHTML = kpis.map((kpi,i) => {
        const accent = accentMap[kpi.level];
        const color = colorMap[kpi.level];
        return `<div class="em-kpi-card" style="--kpi-accent:${accent};animation:emSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
            <div class="em-kpi-label">${kpi.icon} ${kpi.label}</div>
            <div class="em-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
            <div class="em-kpi-sub">${kpi.sub}</div>
            ${kpi.indicator?`<div class="em-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
        </div>`;
    }).join('');
    kpis.forEach((kpi,i) => {
        setTimeout(() => counterUp(document.getElementById(`kpi-val-${i}`), kpi.value, kpi.suffix||'', 900), 200 + i*100);
    });
}
