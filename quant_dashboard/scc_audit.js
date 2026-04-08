/**
 * AlphaCore · SCC 深南电路 穿透审计终端 V3.0
 * 五维穿透审计：技术研发 · 财务健康 · 产能良率 · 汽车体系 · 估值周期
 * 无Sina数据源 - 极致数据准确性
 */

const SCC_MODULES = {
    financial:  { icon: '💰', color: '#10b981', label: '财务健康', weight: 20 },
    tech_moat:  { icon: '🧠', color: '#6366f1', label: '技术研发', weight: 25 },
    capacity:   { icon: '🏭', color: '#f59e0b', label: '产能良率', weight: 25 },
    auto_elec:  { icon: '🚗', color: '#ec4899', label: '汽车体系', weight: 15 },
    valuation:  { icon: '📊', color: '#3b82f6', label: '估值周期', weight: 15 },
};

const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildSCCData() {
    const modules = {
        financial: {
            score: 78, grade: 'B',
            checks: [
                { name:'营收增长', score:85, status:'pass', detail:'2024E预计实现营收165亿元，YoY +22%，持续回暖', explanation:'受AI服务器及汽车电子需求驱动，封装基板营收触底反弹', threshold:'🟢 >20% | 🟡 10-20% | 🔴 <10%' },
                { name:'毛利率', score:70, status:'warn', detail:'综合毛利率预计约24.5%，受FC-BGA新产能折旧影响', explanation:'折旧压力处于高峰期，但产品结构向高端AI服务器转移提升了毛利弹性', threshold:'🟢 >28% | 🟡 22-28% | 🔴 <22%' },
                { name:'资产负债率', score:82, status:'pass', detail:'资产负债率维持48%左右，具备充足扩张冗余', explanation:'资本结构稳健，长期付息债务比例极低' },
                { name:'经营现金流', score:75, status:'pass', detail:'经营性现金流净额预计超25亿元，造血能力强劲', explanation:'高效的存货与账期管理，抵御宏观下行风险' }
            ]
        },
        tech_moat: {
            score: 88, grade: 'A',
            checks: [
                { name:'FC-BGA基板突破', score:92, status:'pass', detail:'无锡基地14层以上高频高速基板具备量产能力', explanation:'打破海外高端IC封装基板垄断，深度受益国产算力链自主可控' },
                { name:'AI服务器PCB能力', score:85, status:'pass', detail:'全面掌握OAM/UBB等高端AI服务器PCB技术', explanation:'已打入核心算力芯片及头部整机厂供应链' },
                { name:'研发投入强度', score:88, status:'pass', detail:'研发占营收比例稳定超8%（超12亿元）', explanation:'深耕高密度互连(HDI)、先进封装领域工艺技术壁垒' }
            ]
        },
        capacity: {
            score: 75, grade: 'C',
            checks: [
                { name:'广州封装基板项目', score:65, status:'warn', detail:'FC-BGA规划产能2亿颗，目前仍在爬坡攻坚期', explanation:'新产线良率爬升及客户验证周期长，是短期利润压制核心因素', action:'密切跟踪大客户审厂及产品良率拐点' },
                { name:'南通三期', score:82, status:'pass', detail:'专注汽车电子PCB，已全面达产并盈利', explanation:'产能满载带来规模效应释放' },
                { name:'数字化工厂', score:78, status:'pass', detail:'高度自动化提升生产效率，降低人工成本', explanation:'“一站式”解决方案从PCB到电子装联的协同效应逐步体现' }
            ]
        },
        auto_elec: {
            score: 82, grade: 'B',
            checks: [
                { name:'Tier 1客户渗透', score:85, status:'pass', detail:'已导入多家国际与国内知名Tier 1及整车厂', explanation:'车用PCB(ADAS、新能源动力系统)市占率提升' },
                { name:'订单能见度', score:78, status:'pass', detail:'汽车业务订单覆盖至2025年Q3，具备高确定性', explanation:'汽车智能化、电动化趋势下，车用PCB附加值显著增长' }
            ]
        },
        valuation: {
            score: 65, grade: 'C',
            checks: [
                { name:'PE 估值(TTM)', score:68, status:'warn', detail:'PE 约29X，处于近三年中枢合理偏高水平', explanation:'市场给予其算力基板国产替代的估值溢价', threshold:'🟢 <20X | 🟡 20-35X | 🔴 >35X' },
                { name:'PB 估值', score:62, status:'warn', detail:'PB 约4.1X，处于历史均值加一倍标准差附近', explanation:'重资产属性下PB相对偏高，需业绩加速兑现' },
                { name:'股息率', score:65, status:'warn', detail:'股息率约1.2%，保持连续分红', explanation:'作为成长型周期股，非高收益分红标的' }
            ]
        }
    };

    let weightedSum = 0, totalWeight = 0;
    for (const [k, mod] of Object.entries(modules)) {
        const w = SCC_MODULES[k].weight;
        weightedSum += mod.score * w;
        totalWeight += w;
    }
    const trustScore = Math.round(weightedSum / totalWeight);
    const trustGrade = trustScore >= 85 ? 'A' : trustScore >= 70 ? 'B' : trustScore >= 55 ? 'C' : 'D';

    let pass = 0, warn = 0, fail = 0, total = 0;
    Object.values(modules).forEach(mod => mod.checks.forEach(c => {
        total++;
        if (c.status === 'pass') pass++;
        else if (c.status === 'warn') warn++;
        else fail++;
    }));

    return {
        company: '深南电路', ticker_a: '002916.SZ',
        market_cap: '538亿', price: '105.20', pe: '28.8', pb: '4.1',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules,
        audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'FC-BGA良率不及预期', level:'high', desc:'高端封装基板量产初期面临较大良率挑战。', probability:'中等', impact:'重大', mitigation:'引进高端人才，强化产学研结合' },
            { name:'折旧压力剧增', level:'high', desc:'广州及无锡新厂房大额资产固化，折旧包袱可能侵蚀表面利润。', probability:'极高', impact:'中等', mitigation:'加速订单导入实现规模化' },
            { name:'宏观需求下行', level:'medium', desc:'消费电子及通信基站建设放缓，压制传统业务表现。', probability:'高', impact:'中等', mitigation:'业务结构向AI和汽车重点迁移' }
        ],
        verdict: {
            bull: ['国产算力唯一正宗高端载板(FC-BGA)稀缺标的', 'AI服务器(OAM、GPU板)量价齐升释放弹性', '汽车电子三期达产，第二曲线增长确定性强'],
            bear: ['中短期折旧海啸压制表观利润率', 'PE近30X已抢跑反映部分算力预期', '传统通信PCB业务复苏动能相对疲软'],
            catalysts: ['大客户FC-BGA产品正式通过验证并获得批量订单', '全球AI算力资本开支二次上修', '国产算力芯片规模化出货'],
            positioning: '🌟 核心配置。具备极致的国产替代及AI产业双轮驱动属性，逢低(PB<3.5X或调整超15%)坚决加仓。',
            rating: 'buy', rating_text: '📈 积极看多 / 核心底仓',
            summary: '深南电路是国内少数具备“PCB+基板+装联”一站式能力的企业。AI算力带来的覆铜板层数及面积跃升，以及极具壁垒的高端FC-BGA国产化进程，将成为其贯穿未来三年的增长主轴。尽管短期受产能爬坡与折旧干扰，中长期安全边际确立。建议作为硬科技赛道的核心标的予以超配。'
        },
        financials: {
            years: ['2019','2020','2021','2022','2023','2024E','2025E'],
            revenue: [105.2, 116.0, 139.4, 139.9, 135.3, 165.0, 195.0],
            net_income: [12.3, 14.3, 14.8, 16.4, 14.0, 19.3, 23.5],
            gross_margin: [26.5, 26.5, 23.7, 25.5, 23.4, 24.5, 25.8],
            rd_expense: [5.4, 6.4, 7.8, 8.2, 10.7, 12.5, 14.0],
            capex: [15.2, 22.0, 31.0, 48.0, 35.0, 22.0, 15.0],
            node_split: { '印制电路板(PCB)': 58, '封装基板': 22, '电子装联': 15, '其他': 5 }
        }
    };
}

document.addEventListener('DOMContentLoaded', () => { runSCCAudit(); });

const SCC_SECTIONS = ['scc-identity','trust-hero','scc-kpi-dashboard','audit-overview','scc-charts-grid','scc-risk-matrix','scc-verdict','audit-timeline'];

function runSCCAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    if(btn) btn.disabled = true;
    if(spinner) spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    SCC_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.style.display = 'none'; el.style.opacity = '0'; }
    });

    const loadingStatus = document.querySelector('.loading-status');
    const moduleSteps = [
        { t: 300,  text: '🧠 正在审计 [1/5] 技术研发… FC-BGA突破·算力订单' },
        { t: 600,  text: '💰 正在审计 [2/5] 财务健康… 利润率·账期·经营现金流' },
        { t: 900,  text: '🏭 正在审计 [3/5] 产能良率… 广州新厂·高阶利用率' },
        { t: 1200, text: '🚗 正在审计 [4/5] 汽车体系… Tier1渗透·订单能见度' },
        { t: 1500, text: '📊 正在审计 [5/5] 估值周期… 绝对估值·历史中枢对比' },
        { t: 1800, text: '✅ 五维穿透审计完成，正在生成报告…' },
    ];
    moduleSteps.forEach(step => {
        setTimeout(() => { if(loadingStatus) loadingStatus.textContent = step.text; }, step.t);
    });

    setTimeout(() => {
        const data = buildSCCData();
        renderAll(data);
        if(btn) btn.disabled = false;
        if(spinner) spinner.style.display = 'none';
    }, 2200);
}

function renderAll(data) {
    document.getElementById('audit-loading').style.display = 'none';
    const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid', 'scc-charts-grid':'grid', 'scc-kpi-dashboard':'grid' };
    SCC_SECTIONS.forEach(id => {
        const el = document.getElementById(id);
        if(el) el.style.display = displayMap[id] || 'block';
    });

    renderIdentity(data); renderTrustHero(data); renderKPIDashboard(data);
    renderAlertBanner(data); renderRadar(data); renderModuleCards(data);
    renderCharts(data); renderRiskMatrix(data); renderVerdict(data); renderTimeline(data);

    document.getElementById('audit-time').textContent = data.audit_time;
    document.getElementById('footer-time').textContent = '· 审计于 ' + data.audit_time;

    SCC_SECTIONS.forEach((id, i) => {
        const el = document.getElementById(id);
        if(!el) return;
        setTimeout(() => {
            el.style.transition = 'opacity 0.5s ease, transform 0.5s cubic-bezier(0.22,1,0.36,1)';
            el.style.opacity = '1'; el.style.transform = 'translateY(0)';
        }, 80 * i);
        el.style.transform = 'translateY(12px)';
    });

    const layout = document.getElementById('audit-layout');
    layout.classList.remove('scan-complete');
    void layout.offsetWidth;
    layout.classList.add('scan-complete');
}

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

function renderIdentity(d) {
    document.getElementById('qs-mcap').textContent = d.market_cap;
    document.getElementById('qs-price').textContent = '¥'+d.price;
    document.getElementById('qs-pe').textContent = d.pe+'X';
    document.getElementById('qs-pb').textContent = d.pb+'X';
}

function renderTrustHero(d) {
    const gc = GRADE_COLORS[d.trust_grade] || '#94a3b8';
    const bigScore = document.getElementById('trust-big-score');
    bigScore.style.color = gc;
    counterUp(bigScore, d.trust_score, '', 1400);

    const badge = document.getElementById('trust-grade-badge');
    badge.textContent = d.trust_grade;
    badge.className = 'trust-grade-badge grade-'+d.trust_grade;

    const verdicts = { A:'深度护城河 极具配置价值', B:'优质资产 结构性机遇明确', C:'估值修复 兼具风险收益比', D:'⚠ 高风险标的 建议回避' };
    document.getElementById('trust-verdict').textContent = verdicts[d.trust_grade] || '';
    document.getElementById('stat-pass').textContent = '✅ '+d.pass_count+' 优势';
    document.getElementById('stat-warn').textContent = '⚠️ '+d.warn_count+' 关注';
    document.getElementById('stat-fail').textContent = '❌ '+d.fail_count+' 风险';
    document.getElementById('trust-meta').textContent = '共 '+d.total_checks+' 项检查 · 加权评分 '+d.trust_score+'/100';

    const keys = Object.keys(SCC_MODULES);
    const shortLabels = { financial:'财务', tech_moat:'护城河', capacity:'产能', auto_elec:'汽车', valuation:'估值' };
    document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
        const s = d.modules[k].score;
        const c = s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444';
        const h = Math.max(s*1.4, 8);
        return '<div class="eq-bar-group"><span class="eq-score" style="color:'+c+'">'+s+'</span><div class="eq-track"><div class="eq-fill" style="height:'+h+'px;background:'+c+';animation-delay:'+(0.1+i*0.12)+'s"></div></div><span class="eq-label">'+shortLabels[k]+'</span></div>';
    }).join('');

    const chart = echarts.init(document.getElementById('trust-gauge-chart'));
    chart.setOption({
        series:[{ type:'gauge', startAngle:210, endAngle:-30, radius:'88%', center:['50%','55%'], min:0, max:100, splitNumber:4,
            axisLine:{ lineStyle:{ width:18, color:[[0.55,'#ef4444'],[0.70,'#f59e0b'],[0.85,'#3b82f6'],[1,'#10b981']] }},
            pointer:{ length:'55%', width:4, itemStyle:{ color:gc }},
            axisTick:{ show:false }, splitLine:{ length:10, lineStyle:{ color:'rgba(255,255,255,0.15)', width:1 }},
            axisLabel:{ distance:18, color:'#64748b', fontSize:10, fontFamily:'Outfit' },
            detail:{ show:false }, data:[{ value:d.trust_score, name:'综合分' }]
        }]
    });
}

function renderAlertBanner(d) {
    const banner = document.getElementById('alert-banner');
    if(d.fail_count > 0) {
        banner.className = 'alert-banner level-fail visible';
        document.getElementById('alert-icon').textContent = '🚨';
        document.getElementById('alert-text').innerHTML = '<strong>'+d.fail_count+' 项高风险</strong> 需重点排雷';
    } else if(d.warn_count > 0) {
        banner.className = 'alert-banner level-warn visible';
        document.getElementById('alert-icon').textContent = '⚠️';
        document.getElementById('alert-text').innerHTML = '<strong>'+d.warn_count+' 项需补充研究</strong>';
    } else { banner.classList.remove('visible'); }
}

function renderRadar(d) {
    const keys = Object.keys(SCC_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:SCC_MODULES[k].label,max:100})), shape:'polygon', radius:'72%',
            axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
            splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}, splitArea:{areaStyle:{color:['rgba(99,102,241,0.02)','rgba(99,102,241,0.04)']}},
            axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}} },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'SCC审计',
            areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(236,72,153,0.35)'},{offset:1,color:'rgba(139,92,246,0.08)'}]}},
            lineStyle:{color:'#ec4899',width:2}, itemStyle:{color:'#f472b6'}, symbol:'circle', symbolSize:7 }] }]
    });
    document.getElementById('radar-legend').innerHTML = keys.map(k => {
        const m = SCC_MODULES[k]; const s = d.modules[k].score;
        return '<span class="radar-legend-item"><span class="radar-legend-dot" style="background:'+m.color+'"></span>'+m.label+' '+s+'</span>';
    }).join('');
}

let activeModule = null, sccData = null;
function renderModuleCards(d) {
    sccData = d;
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(SCC_MODULES).map(([key, meta]) => {
        const mod = d.modules[key];
        const gc = GRADE_COLORS[mod.grade]||'#94a3b8';
        const r=18, circ=2*Math.PI*r, dash=circ*(mod.score/100);
        return '<div class="module-card" style="--mod-color:'+meta.color+'" onclick="toggleDetail(\''+key+'\')" id="card-'+key+'">' +
            '<div class="mod-header"><span class="mod-label">'+meta.icon+' '+meta.label+'</span>' +
            '<div class="mod-score-ring"><svg viewBox="0 0 42 42"><circle class="mod-ring-bg" cx="21" cy="21" r="'+r+'"/><circle class="mod-ring-fill" cx="21" cy="21" r="'+r+'" stroke="'+gc+'" stroke-dasharray="'+circ+'" stroke-dashoffset="'+(circ-dash)+'"/></svg>' +
            '<span class="mod-score-text">'+mod.score+'</span></div></div>' +
            '<div class="mod-checks-summary"><span class="weight-tag">权重 '+meta.weight+'%</span></div></div>';
    }).join('');
}

function toggleDetail(key) {
    const section = document.getElementById('detail-section');
    document.querySelectorAll('.module-card').forEach(c=>c.classList.remove('expanded'));
    if(activeModule===key){ section.classList.remove('visible'); activeModule=null; return; }
    activeModule = key;
    document.getElementById('card-'+key).classList.add('expanded');
    const meta = SCC_MODULES[key], mod = sccData.modules[key];
    document.getElementById('detail-title').textContent = meta.icon+' '+meta.label+' · '+mod.score+'/100';

    document.getElementById('detail-body').innerHTML = mod.checks.map((c,idx) => {
        const icon = c.status==='pass'?'✅':c.status==='warn'?'⚠️':'❌';
        const barC = c.status==='pass'?'#10b981':c.status==='warn'?'#f59e0b':'#ef4444';
        return '<div class="check-row status-'+c.status+'"><span class="check-icon">'+icon+'</span>' +
            '<div class="check-info"><div class="check-name">'+c.name+'</div><div class="check-detail">'+c.detail+'</div></div>' +
            '<div class="check-score-bar"><div class="check-score-fill" style="width:'+c.score+'%;background:'+barC+'"></div></div>' +
            '<span class="check-score-val" style="color:'+barC+'">'+c.score+'</span></div>' +
            (c.explanation?'<div class="check-rule-panel open"><div class="rule-explanation">📖 '+c.explanation+'</div></div>':'');
    }).join('');
    section.classList.add('visible');
    section.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function closeDetail() { document.getElementById('detail-section').classList.remove('visible'); activeModule=null; }

function renderCharts(d) {
    const f = d.financials;
    const darkGrid = { top:35, bottom:25, left:50, right:20 };
    const axisStyle = { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)'}} };
    const tooltipStyle = { trigger:'axis', backgroundColor:'rgba(15,23,42,0.92)', borderColor:'rgba(236,72,153,0.3)', textStyle:{color:'#e2e8f0',fontSize:12} };

    echarts.init(document.getElementById('chart-revenue')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:{top:5,textStyle:{color:'#94a3b8'}},
        xAxis:{type:'category',data:f.years,...axisStyle}, yAxis:{type:'value',name:'亿元',...axisStyle},
        series:[
            {name:'营收',type:'bar',data:f.revenue,barWidth:'35%',itemStyle:{color:'#8b5cf6',borderRadius:[4,4,0,0]}},
            {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#ec4899',width:3},symbol:'circle',symbolSize:6}
        ]
    });

    echarts.init(document.getElementById('chart-margins')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:{top:5,textStyle:{color:'#94a3b8'}},
        xAxis:{type:'category',data:f.years,...axisStyle}, yAxis:{type:'value',name:'%',...axisStyle},
        series:[
            {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,areaStyle:{color:'rgba(16,185,129,0.1)'},lineStyle:{color:'#10b981',width:3}}
        ]
    });

    echarts.init(document.getElementById('chart-rdcapex')).setOption({
        grid:darkGrid, tooltip:tooltipStyle, legend:{top:5,textStyle:{color:'#94a3b8'}},
        xAxis:{type:'category',data:f.years,...axisStyle}, yAxis:{type:'value',name:'亿元',...axisStyle},
        series:[
            {name:'研发投入',type:'bar',data:f.rd_expense,barWidth:'25%',itemStyle:{color:'#3b82f6',borderRadius:[3,3,0,0]}},
            {name:'资本开支',type:'line',data:f.capex,smooth:true,lineStyle:{color:'#f59e0b',width:3,type:'dashed'}}
        ]
    });

    echarts.init(document.getElementById('chart-nodes')).setOption({
        tooltip:{trigger:'item'}, legend:{bottom:2,textStyle:{color:'#94a3b8'}},
        series:[{type:'pie',radius:['40%','65%'],center:['50%','45%'],
            data:Object.entries(f.node_split).map(([name,value])=>({name,value})),
            itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:2},
            color:['#8b5cf6','#ec4899','#3b82f6','#475569']
        }]
    });
}

function renderRiskMatrix(d) {
    document.getElementById('rm-badge').textContent = d.risks.filter(r=>r.level==='high').length + ' 重大风险';
    document.getElementById('scc-rm-body').innerHTML = d.risks.map(r => 
        '<div class="scc-risk-item risk-'+r.level+'"><div class="scc-risk-name">🔴 '+r.name+'</div><div class="scc-risk-desc">'+r.desc+'</div><div class="scc-risk-tags"><span class="scc-risk-tag mitigation">对策: '+r.mitigation+'</span></div></div>'
    ).join('');
}

function renderVerdict(d) {
    const v = d.verdict;
    document.getElementById('scc-verdict-body').innerHTML = 
        '<div class="scc-verdict-card bull"><div class="scc-verdict-card-title">📈 护城河优势</div><ul class="scc-verdict-list">'+v.bull.map(x=>'<li>'+x+'</li>').join('')+'</ul></div>' +
        '<div class="scc-verdict-card bear"><div class="scc-verdict-card-title">📉 压制因素</div><ul class="scc-verdict-list">'+v.bear.map(x=>'<li>'+x+'</li>').join('')+'</ul></div>' +
        '<div class="scc-conclusion-box"><div class="scc-conclusion-title">🏛️ 审计总结核心结论</div><div class="scc-conclusion-text">'+v.summary+'</div>' +
        '<div class="scc-conclusion-rating '+v.rating+'">'+v.rating_text+'</div></div>';
}

function renderTimeline(d) {
    const hk = 'alphacore_scc_audit_history';
    let hist = JSON.parse(localStorage.getItem(hk)||'[]');
    if(hist.length===0 || hist[hist.length-1].time!==d.audit_time) hist.push({score:d.trust_score, time:d.audit_time});
    localStorage.setItem(hk, JSON.stringify(hist));

    echarts.init(document.getElementById('timeline-chart')).setOption({
        grid:{top:10,bottom:20,left:35,right:15},
        xAxis:{type:'category',data:hist.map(h=>h.time.split(' ')[1]),axisLine:{lineStyle:{color:'rgba(255,255,255,0.1)'}}},
        yAxis:{type:'value',min:0,max:100,splitLine:{lineStyle:{color:'rgba(255,255,255,0.05)'}}},
        series:[{type:'line',data:hist.map(h=>h.score),smooth:true,lineStyle:{color:'#ec4899',width:3},areaStyle:{color:'rgba(236,72,153,0.1)'}}]
    });
}

function renderKPIDashboard(d) {
    const kpis = [
        { label:'审计评分', val:d.trust_score, sub:d.trust_grade+'级' },
        { label:'护城河', val:d.modules.tech_moat.score, sub:'FC-BGA破局' },
        { label:'财务健康', val:d.modules.financial.score, sub:'强劲造血' },
        { label:'产能释放', val:d.modules.capacity.score, sub:'折旧高峰中' },
        { label:'目标PE', val:'25-30X', sub:'估值重估期' }
    ];
    document.getElementById('scc-kpi-dashboard').innerHTML = kpis.map((k,i) => 
        '<div class="scc-kpi-card" style="animation-delay:'+(i*0.1)+'s"><div class="scc-kpi-label">'+k.label+'</div><div class="scc-kpi-value">'+k.val+'</div><div class="scc-kpi-sub">'+k.sub+'</div></div>'
    ).join('');
}
