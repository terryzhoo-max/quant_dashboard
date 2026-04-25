/**
 * AlphaCore · 沪电股份(WUS) 审计数据文件 (Phase 3A)
 */
AuditCore.init({
    companyName: '沪电股份',
    themeColor: '#ec4899',
    themeColorRgba: 'rgba(236,72,153,',
    localStorageKey: 'alphacore_wus_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        ai_moat:  { icon:'🧠', color:'#ec4899', label:'AI算力护城河', weight:30 },
        financial:{ icon:'💰', color:'#10b981', label:'财务健康', weight:20 },
        capacity: { icon:'🏭', color:'#6366f1', label:'产能与良率', weight:20 },
        auto_elec:{ icon:'🚗', color:'#06b6d4', label:'汽车电子', weight:15 },
        valuation:{ icon:'📊', color:'#f59e0b', label:'估值与周期', weight:15 },
    },
    shortLabels: { ai_moat:'AI护城河', financial:'财务', capacity:'产能', auto_elec:'汽车', valuation:'估值' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'🧠 正在审计 [1/5] AI算力护城河… 英伟达一供·800G·技术壁垒' },
        { t:650, text:'💰 正在审计 [2/5] 财务健康… 营收·利润·毛利率·现金流' },
        { t:1000, text:'🏭 正在审计 [3/5] 产能与良率… 泰国工厂·HDI产线·良率' },
        { t:1300, text:'🚗 正在审计 [4/5] 汽车电子… ADAS·雷达板·电控基板' },
        { t:1600, text:'📊 正在审计 [5/5] 估值与周期… PE·PB·DCF·风险溢价' },
        { t:1900, text:'✅ 五维审计完成，正在生成深度穿透报告…' },
    ],

    buildData() {
        const modules = {
            ai_moat: { score:91, grade:'A', checks:[
                {name:'英伟达核心一供',score:95,status:'pass',detail:'Hopper/Blackwell AI服务器高阶HDI唯一核心供应商',explanation:'AI算力板技术壁垒极高，不可替代的先发卡位优势',threshold:'🟢 独供 | 🟡 寡供 | 🔴 多供竞争'},
                {name:'800G交换机PCB',score:90,status:'pass',detail:'800G光模块交换机PCB大规模放量',explanation:'数据中心网络升级是AI基建第二波段',threshold:'🟢 >40%增速 | 🟡 20-40% | 🔴 <20%'},
                {name:'企业通讯营收占比',score:88,status:'pass',detail:'企业通讯（含AI算力）营收占比突破70%',explanation:'从低端消费PCB彻底转型AI硬件'},
                {name:'技术壁垒与良率',score:88,status:'pass',detail:'超高多层板（24-32层）量产良率业内领先',explanation:'良率差距即利润护城河'},
                {name:'Blackwell深度绑定',score:92,status:'pass',detail:'GB200/GB300系列NVLink板唯一供应商',explanation:'每代芯片迭代ASP提升25-40%',threshold:'🟢 层数≥24层 | 🟡 16-24层 | 🔴 <16层'},
            ]},
            financial: { score:86, grade:'A', checks:[
                {name:'营收高速增长',score:90,status:'pass',detail:'2024年营收约120.6亿元，YoY+34.9%',explanation:'AI板单价提升+出货量放大',threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%'},
                {name:'净利润爆发',score:92,status:'pass',detail:'2024年归母净利润约28亿元，YoY+85.4%',explanation:'高阶HDI附加值极高'},
                {name:'综合毛利率',score:88,status:'pass',detail:'2024年毛利率约33.8%，Q4单季超36%',explanation:'AI板ASP大幅拉升整体毛利率',threshold:'🟢 >32% | 🟡 25-32% | 🔴 <25%'},
                {name:'现金流质量',score:82,status:'pass',detail:'经营性现金流净额约20.5亿元',explanation:'无大规模补贴依赖，盈利质量高'},
                {name:'资产负债率',score:78,status:'pass',detail:'2024年资产负债率约35%',explanation:'轻杠杆制造业'},
                {name:'ROE提升',score:85,status:'pass',detail:'2024年ROE约23.5%，较2023年14.2%大幅跃升',explanation:'ROE持续提升是价值重估核心驱动'},
            ]},
            capacity: { score:74, grade:'B', checks:[
                {name:'泰国工厂进度',score:80,status:'pass',detail:'泰国Saraburi工厂2024年底投产爬坡',explanation:'锁定北美订单战略意义重大',action:'追踪泰国产线爬坡进度'},
                {name:'高阶HDI产能瓶颈',score:65,status:'warn',detail:'Blackwell NVLink板24-32层产能满载',explanation:'短期内产能不足是最大增长制约',action:'跟踪高端产线扩建资本支出'},
                {name:'资本开支力度',score:82,status:'pass',detail:'2024年资本开支约25亿元',explanation:'资本开支即市场份额'},
                {name:'良率稳定性风险',score:62,status:'warn',detail:'GB300层数增至32层，良率面临挑战',explanation:'每次层数跃升初期良率波动1%对应数千万成本增量',action:'关注Q1-Q2 2025良率爬坡数据'},
                {name:'扩产进度跟踪',score:75,status:'pass',detail:'2025年规划月产能提升约28%',explanation:'产能释放周期与需求爆发期同步'},
            ]},
            auto_elec: { score:70, grade:'B', checks:[
                {name:'毫米波雷达PCB',score:82,status:'pass',detail:'深度卡位博世、大陆、法雷奥',explanation:'ADAS渗透率提升中的稳定现金牛业务'},
                {name:'增速环比放缓',score:58,status:'warn',detail:'2024年汽车板增速降至约8%',explanation:'近阶段定位为业务稳定器',action:'观察2025年ADAS政策进展'},
                {name:'电控基板升级',score:72,status:'pass',detail:'高阶新能源PDU及域控板，单车价值量从80元提升至220元',explanation:'智能化升级带来ASP提升'},
                {name:'客户集中度',score:68,status:'warn',detail:'博世营收贡献约45%，议价能力受限',explanation:'正拓展比亚迪/理想等国内新能源主机厂',action:'追踪国内Tier1客户拓展'},
            ]},
            valuation: { score:52, grade:'C', checks:[
                {name:'PE(TTM)估值',score:42,status:'warn',detail:'动态PE约34.5X，硬件制造业高位',explanation:'34X PE容错极低区域',threshold:'🟢 <25X | 🟡 25-35X | 🔴 >35X'},
                {name:'周期见顶风险',score:35,status:'fail',detail:'AI硬件难逃双杀周期',explanation:'历史上硬件股股价提前6-9个月见顶',action:'设定移动止损；追踪云厂商CAPEX指引'},
                {name:'PB估值',score:52,status:'warn',detail:'PB约7.1X，远超制造业历史中枢2-3X',explanation:'高ROE支撑有一定合理性',threshold:'🟢 <3X | 🟡 3-5X | 🔴 >5X'},
                {name:'股息率防御性',score:72,status:'pass',detail:'股息率约1.8%，分红率约35%',explanation:'稳定分红提供安全垫'},
                {name:'2025E隐含增速匹配度',score:60,status:'warn',detail:'34X PE隐含净利润增速需达40%+',explanation:'风险在于增速不达标'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'沪电股份',ticker:'002463.SZ',
            market_cap:'1,462亿',price:'76.37',pe:'34.5',pb:'7.12',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules,audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'砍单/周期双杀',level:'critical',desc:'AI资本开支见顶→英伟达减产→HDI出货骤降',probability:'中等',impact:'致命',mitigation:'设定25X PE止损线'},
                {name:'玻璃基板颠覆',level:'high',desc:'英特尔/AMD主导的玻璃基板技术大规模商用',probability:'低',impact:'重大',mitigation:'追踪英特尔2027路线图'},
                {name:'良率爬坡失控',level:'high',desc:'GB300 32层板量产良率不及预期',probability:'中等',impact:'重大',mitigation:'关注Q1-Q2毛利率环比'},
                {name:'泰国工厂延期',level:'medium',desc:'泰国产线认证周期拉长',probability:'低',impact:'中等',mitigation:'追踪泰国工厂季度产能公告'},
                {name:'竞争格局恶化',level:'medium',desc:'深南/生益/鹏鼎加速追赶高阶HDI',probability:'中等',impact:'中等',mitigation:'监控同行资本开支'},
                {name:'汇率风险',level:'medium',desc:'人民币升值压缩出口利润',probability:'中等',impact:'轻',mitigation:'自然对冲'},
            ],
            verdict:{
                bull:['英伟达Blackwell核心PCB不可替代','800G→1.6T升级带来第二成长曲线','AI CAPEX景气周期上升阶段','泰国产能规避关税+供应链偏好'],
                bear:['PE 34.5X严重透支，容错接近零','AI本质属于强周期硬件股','PB 7.1X远超制造业历史中枢','玻璃基板技术路线风险'],
                catalysts:['英伟达GB300量产超预期','北美云厂商上修CAPEX指引','泰国工厂顺利达产','800G-1.6T规模放量'],
                positioning:'🔄 周期博弈/高抛低吸。建议仓位不超过5%。',
                rating:'hold',rating_text:'⚖️ 波段控仓',
                summary:'沪电股份是AI算力基建最优质的"卖水人"之一，基本面逻辑确定性极强。但34.5X PE与7.1X PB意味着极度透支乐观预期，建议以波段思维参与，等待估值回调至25X PE时重仓介入。'
            },
            financials:{
                years:['2020','2021','2022','2023','2024','2025E','2026E'],
                revenue:[74.6,74.2,83.3,89.4,120.6,168.0,205.0],
                net_income:[13.4,10.6,13.6,15.1,28.0,42.5,52.0],
                gross_margin:[26.5,25.4,27.2,28.1,33.8,36.5,37.2],
                caputil:[88.5,85.0,89.2,86.5,96.0,98.5,94.0],
                rd_expense:[3.8,4.1,4.5,4.8,6.7,8.5,10.2],
                capex:[11.2,10.5,14.8,16.5,25.0,32.0,28.0],
                biz_split:{'AI算力服务器':52.0,'800G交换机':22.5,'汽车电子':21.0,'工业/其他':4.5}
            }
        };
    },

    buildKPIs(d) {
        const valLevel = d.modules.valuation.score>=55?'warn':'fail';
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':'warn',indicator:d.trust_score>=70?'● 可投':'◐ 谨慎'},
            {label:'AI护城河',icon:'🧠',value:d.modules.ai_moat.score,suffix:'',sub:'英伟达一供·800G·NVLink',level:'pass',indicator:'🔮 核心优势'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:`营收+34.9% · 毛利率${d.financials.gross_margin[4]}%`,level:'pass'},
            {label:'产能与良率',icon:'🏭',value:d.modules.capacity.score,suffix:'',sub:'泰国工厂爬坡·32层良率',level:d.modules.capacity.score>=70?'pass':'warn'},
            {label:'估值合理性',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:valLevel,indicator:valLevel==='fail'?'🔴 严重偏高':'⚠ 偏高'},
            {label:'汽车电子',icon:'🚗',value:d.modules.auto_elec.score,suffix:'',sub:'ADAS卡位·雷达板·电控',level:d.modules.auto_elec.score>=70?'pass':'warn'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(236,72,153,0.2)');
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#f472b6'},{offset:1,color:'#ec4899'}]},borderRadius:[4,4,0,0]}},
                {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.12)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        core.initChart('chart-margins')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,max:110},
            series:[
                {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.15)'},{offset:1,color:'transparent'}]}},
                    markLine:{silent:true,data:[{yAxis:32,label:{show:true,formatter:'健康线 32%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
                {name:'产能利用率',type:'line',data:f.caputil,smooth:true,lineStyle:{color:'#06b6d4',width:2,type:'dashed'},itemStyle:{color:'#22d3ee'},symbol:'circle',symbolSize:6}
            ]
        });
        core.initChart('chart-rdcapex')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'研发投入',type:'bar',data:f.rd_expense,barWidth:'28%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#a78bfa'},{offset:1,color:'#8b5cf6'}]},borderRadius:[3,3,0,0]}},
                {name:'资本开支',type:'bar',data:f.capex,barWidth:'28%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#fb7185'},{offset:1,color:'#ef4444'}]},borderRadius:[3,3,0,0]}}
            ]
        });
        const ns=f.biz_split;
        core.initChart('chart-nodes')?.setOption({
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(236,72,153,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(ns).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#ec4899','#8b5cf6','#06b6d4','#475569']}]
        });
    }
});
