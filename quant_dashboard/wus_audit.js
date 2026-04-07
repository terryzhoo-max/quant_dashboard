/**
 * AlphaCore · WUS 个股穿透审计终端 V3.0
 */
const WUS_MODULES = {
    ai_moat: { icon: '🧠', color: '#ec4899', label: 'AI算力护城河', weight: 30 },
    financial: { icon: '💰', color: '#10b981', label: '财务健康', weight: 20 },
    capacity: { icon: '🏭', color: '#6366f1', label: '产能与良率', weight: 20 },
    auto_elec: { icon: '🚗', color: '#06b6d4', label: '汽车电子', weight: 15 },
    valuation: { icon: '📊', color: '#f59e0b', label: '估值与周期', weight: 15 },
};
const GRADE_COLORS = { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' };

function buildWUSData() {
    const modules = {
        ai_moat: {
            score: 92, grade: 'A',
            checks: [
                { name:'英伟达核心供应商', score:95, status:'pass', detail:'作为 Nvidia AI Server (Hopper/Blackwell) 高阶 HDI 及 OAM 核心计算板一供', explanation:'AI算力板技术壁垒极高(层数超24层，对向性要求严苛)，拥有先发优势' },
                { name:'800G 交换机 PCB', score:90, status:'pass', detail:'800G 光模块交换机 PCB 放量，北美云大厂加速拉货', explanation:'数据中心网络升级是 AI 基建第二波段，拥有极强的爆发性', threshold:'🟢 >40%增速 | 🟡 20-40% | 🔴 <20%' },
                { name:'AI在手订单', score:92, status:'pass', detail:'企业通讯市场板营收占比突破 70%', explanation:'营收结构发生质的蜕变，摆脱低端红海' },
                { name:'技术壁垒与良率', score:88, status:'pass', detail:'超高多层板及高阶 HDI 量产良率业内领先', explanation:'良率差距即利润护城河' }
            ]
        },
        financial: {
            score: 85, grade: 'A',
            checks: [
                { name:'营收增长', score:88, status:'pass', detail:'营收突破百亿级别，同比增速超 40%', explanation:'量价齐升', threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%' },
                { name:'综合毛利率', score:90, status:'pass', detail:'约36%，制造业天花板', explanation:'AI板占比飙升带来产品结构优化', threshold:'🟢 >32% | 🟡 25-32% | 🔴 <25%' },
                { name:'净利润', score:85, status:'pass', detail:'增速远超营收增速', explanation:'高阶HDI附加值极高，规模效应显现' },
                { name:'资产负债率', score:78, status:'pass', detail:'维持在 35% 左右的级别', explanation:'健康水平，现金流充沛' }
            ]
        },
        capacity: {
            score: 75, grade: 'B',
            checks: [
                { name:'泰国工厂进度', score:80, status:'pass', detail:'泰国新产能投产爬坡', explanation:'规避地缘关税风险，满足"China+1"' },
                { name:'高端产能扩充', score:70, status:'warn', detail:'高阶 HDI 及 OAM 产能满载，瓶颈显现', explanation:'极度考验扩产节奏', action:'跟踪高端月度爬坡数据' },
                { name:'研发资本开支', score:82, status:'pass', detail:'保持高资本用于钻孔机及高阶产线', explanation:'资本开支即市场份额' },
                { name:'良率稳定性', score:68, status:'warn', detail:'Blackwell 层数进一步增加，挑战良率', explanation:'良率波动1%都会造成大量成本浪费' }
            ]
        },
        auto_elec: {
            score: 72, grade: 'B',
            checks: [
                { name:'毫米波雷达板', score:80, status:'pass', detail:'卡位博世、大陆等 Tier1', explanation:'ADAS 渗透率提升带来稳健现金牛' },
                { name:'板块增速放缓', score:65, status:'warn', detail:'受全球电车增速放缓影响，汽车板增速降至个位数', explanation:'Beta 偏弱', action:'将其视为防御压舱石' },
                { name:'电控基板', score:70, status:'pass', detail:'卡位高阶新能源 PDU', explanation:'单车价值量逐渐提升' }
            ]
        },
        valuation: {
            score: 55, grade: 'C',
            checks: [
                { name:'PE估值', score:45, status:'warn', detail:'动态 PE(TTM) 约 34X，处于高位', explanation:'极致预期已被 Price-in，容错极低', threshold:'🟢 <25X | 🟡 25-35X | 🔴 >35X' },
                { name:'周期见顶风险', score:38, status:'fail', detail:'存在资本开支增速放缓隐忧', explanation:'硬件股逃不开双杀周期', action:'追踪北美云厂商大写 CAPEX' },
                { name:'PB估值', score:55, status:'warn', detail:'PB 约 7.1X，远超制造业历史中枢', explanation:'高ROE支撑，但对成长性极度苛刻' },
                { name:'股息率', score:78, status:'pass', detail:'维持合理比例分红', explanation:'优秀现金流管理' }
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
        company: '沪电股份', ticker_a: '002463.SZ', ticker_h: '—',
        market_cap: '1,462亿', price: '76.32', pe: '34.5', pb: '7.12',
        eps: '2.21', week52_high: '85.50', week52_low: '28.10',
        trust_score: trustScore, trust_grade: trustGrade,
        pass_count: pass, warn_count: warn, fail_count: fail, total_checks: total,
        modules, audit_time: new Date().toLocaleString('zh-CN', { hour12: false }),
        risks: [
            { name:'砍单风险', level:'critical', desc:'AI结构性放缓导致大幅度缩减订单', probability:'中等', impact:'致命', mitigation:'波段操作策略+高位兑现' },
            { name:'技术路线迭代', level:'high', desc:'玻璃基板的大规模商用重塑格局', probability:'低', impact:'重大', mitigation:'追踪路线图' },
            { name:'宏观周期反噬', level:'high', desc:'PE高悬可能触发双杀', probability:'高', impact:'重大', mitigation:'设定移动均线止损' }
        ],
        verdict: {
            bull: ['英伟达算力核心硬件无可争议的一供', '800G 光通信交换机大升级带来极强利润弹性', '单卡 PCB 层数再度跃升提高ASP'],
            bear: ['动态 PE 34.5X 严重透支未来', 'AI 本质属于强周期硬件', '历史来看高 PB 极易均值回归'],
            catalysts: ['Blackwell 芯片量产进度超预期', '北美四大云厂商上修明年资本开支目标'],
            positioning: '🔄 周期博弈/高抛低吸。34X PE处于估值红线区域，采用【波段交易思维】，跌至 25X 附近再行重仓入场。',
            rating: 'hold', rating_text: '⚖️ 波段控仓',
            summary: '沪电股份本轮 AI 最强卖水人。高PE估值意味着任何关于资本开支放缓的风吹草动都会引发戴维斯双杀。主张理性控仓。'
        },
        financials: {
            years: ['2020','2021','2022','2023','2024E','2025E','2026E'],
            revenue: [74.6, 74.2, 83.3, 89.4, 125.0, 168.5, 205.0],
            net_income: [13.4, 10.6, 13.6, 15.1, 28.5, 42.0, 50.8],
            gross_margin: [26.5, 25.4, 27.2, 28.1, 33.5, 36.2, 36.8],
            caputil: [88.5, 85.0, 89.2, 86.5, 95.8, 98.5, 94.0],
            rd_expense: [3.8, 4.1, 4.5, 4.8, 6.7, 8.5, 10.2],
            capex: [11.2, 10.5, 14.8, 16.5, 25.0, 32.0, 28.0],
            node_split: { '企业通讯(含AI)': 74.5, '汽车电子': 21.0, '工业控制': 3.0, '消费通讯': 1.5 }
        }
    };
}

document.addEventListener('DOMContentLoaded', () => { runWUSAudit(); });

const WUS_SECTIONS = ['wus-identity','trust-hero','wus-kpi-dashboard','audit-overview','wus-charts-grid','wus-risk-matrix','wus-verdict','audit-timeline'];

function runWUSAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    if(btn) btn.disabled = true;
    document.getElementById('audit-loading').style.display = 'block';
    WUS_SECTIONS.forEach(id => { const el = document.getElementById(id); if(el) { el.style.display = 'none'; el.style.opacity = '0'; } });
    
    setTimeout(() => {
        const data = buildWUSData();
        renderAll(data);
        if(btn) btn.disabled = false;
    }, 1800);
}

function renderAll(data) {
    document.getElementById('audit-loading').style.display = 'none';
    WUS_SECTIONS.forEach(id => { const el = document.getElementById(id); if(el) el.style.display = 'grid'; });

    renderIdentity(data); renderTrustHero(data); renderKPIDashboard(data);
    renderAlertBanner(data); renderRadar(data); renderModuleCards(data);
    renderCharts(data); renderRiskMatrix(data); renderVerdict(data); renderTimeline(data);

    document.getElementById('audit-time').textContent = data.audit_time;
    document.getElementById('footer-time').textContent = `· 审计于 ${data.audit_time}`;

    WUS_SECTIONS.forEach((id, i) => {
        const el = document.getElementById(id);
        if(!el) return;
        setTimeout(() => { el.style.opacity = '1'; el.style.transform = 'translateY(0)'; }, 80 * i);
    });
    document.getElementById('audit-layout').classList.add('scan-complete');
}
function counterUp(el, t, s='') { el.textContent = t + s; }

function renderIdentity(d) {
    document.getElementById('qs-mcap').textContent = d.market_cap;
    document.getElementById('qs-price').textContent = '¥'+d.price;
    document.getElementById('qs-pe').textContent = d.pe+'X';
    document.getElementById('qs-pb').textContent = d.pb+'X';
}

function renderTrustHero(d) {
    document.getElementById('trust-big-score').textContent = d.trust_score;
    document.getElementById('trust-grade-badge').textContent = d.trust_grade;
    document.getElementById('stat-pass').textContent = `✅ ${d.pass_count}`;
    document.getElementById('stat-warn').textContent = `⚠️ ${d.warn_count}`;
    document.getElementById('stat-fail').textContent = `❌ ${d.fail_count}`;
    const gc = GRADE_COLORS[d.trust_grade] || '#94a3b8';
    
    const chart = echarts.init(document.getElementById('trust-gauge-chart'));
    chart.setOption({ series:[{ type:'gauge', data:[{ value:d.trust_score, name:'护城河强度' }] }] });
}

function renderAlertBanner(d) {
    const banner = document.getElementById('alert-banner');
    if(d.fail_count > 0) {
        banner.className = 'alert-banner level-fail visible';
        document.getElementById('alert-icon').textContent = '🚨';
        document.getElementById('alert-text').textContent = '发生致命戴维斯双杀监控';
    } else { banner.classList.remove('visible'); }
}

function renderRadar(d) {
    const keys = Object.keys(WUS_MODULES);
    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar:{ indicator:keys.map(k=>({name:WUS_MODULES[k].label,max:100})) },
        series:[{ type:'radar', data:[{ value:keys.map(k=>d.modules[k].score), name:'WUS审计' }] }]
    });
}

function renderModuleCards(d) {
    const container = document.getElementById('module-cards');
    container.innerHTML = Object.entries(WUS_MODULES).map(([key, meta]) => {
        const mod = d.modules[key];
        return `<div class="module-card" style="--mod-color:${meta.color}" id="card-${key}"><div class="mod-header">${meta.label} - ${mod.score}</div></div>`;
    }).join('');
}

function renderCharts(d) {
    const f = d.financials;
    echarts.init(document.getElementById('chart-revenue')).setOption({ xAxis:{data:f.years}, series:[{name:'营收规模',type:'bar',data:f.revenue}, {name:'净利润',type:'line',data:f.net_income}] });
    echarts.init(document.getElementById('chart-margins')).setOption({ xAxis:{data:f.years}, series:[{type:'line',data:f.gross_margin}, {type:'line',data:f.caputil}] });
}

function renderRiskMatrix(d) {
    document.getElementById('wus-rm-body').innerHTML = d.risks.map(r => `<div style="margin-bottom:10px">${r.name}: ${r.desc}</div>`).join('');
}

function renderVerdict(d) {
    document.getElementById('wus-verdict-body').innerHTML = `
        <div class="wus-verdict-card bull">看多: ${d.verdict.bull[0]}</div>
        <div class="wus-verdict-card position">策略: ${d.verdict.positioning}</div>
    `;
}

function renderTimeline(d) {
    // simplified
}

function renderKPIDashboard(d) {
    document.getElementById('wus-kpi-dashboard').innerHTML = '<div style="color:#f472b6;font-size:1.5rem">数据正在生成中</div>';
}
