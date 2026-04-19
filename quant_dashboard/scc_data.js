/**
 * AlphaCore · 深南电路(SCC) 审计数据文件 (Phase 3A)
 */
AuditCore.init({
    companyName: '深南电路',
    themeColor: '#ec4899',
    themeColorRgba: 'rgba(236,72,153,',
    localStorageKey: 'alphacore_scc_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        financial:  { icon:'💰', color:'#10b981', label:'财务健康', weight:20 },
        tech_moat:  { icon:'🧠', color:'#6366f1', label:'技术研发', weight:25 },
        capacity:   { icon:'🏭', color:'#f59e0b', label:'产能良率', weight:25 },
        auto_elec:  { icon:'🚗', color:'#ec4899', label:'汽车体系', weight:15 },
        valuation:  { icon:'📊', color:'#3b82f6', label:'估值周期', weight:15 },
    },
    shortLabels: { financial:'财务', tech_moat:'护城河', capacity:'产能', auto_elec:'汽车', valuation:'估值' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'🧠 正在审计 [1/5] 技术研发… FC-BGA突破·算力订单' },
        { t:600, text:'💰 正在审计 [2/5] 财务健康… 利润率·账期·经营现金流' },
        { t:900, text:'🏭 正在审计 [3/5] 产能良率… 广州新厂·高阶利用率' },
        { t:1200, text:'🚗 正在审计 [4/5] 汽车体系… Tier1渗透·订单能见度' },
        { t:1500, text:'📊 正在审计 [5/5] 估值周期… 绝对估值·历史中枢对比' },
        { t:1800, text:'✅ 五维穿透审计完成，正在生成报告…' },
    ],

    buildData() {
        const modules = {
            financial: { score:78, grade:'B', checks:[
                {name:'营收增长',score:85,status:'pass',detail:'2024E营收165亿元，YoY +22%',explanation:'AI服务器及汽车电子需求驱动',threshold:'🟢 >20% | 🟡 10-20% | 🔴 <10%'},
                {name:'毛利率',score:70,status:'warn',detail:'综合毛利率约24.5%，受FC-BGA折旧影响',explanation:'折旧压力高峰期，但产品结构向高端转移',threshold:'🟢 >28% | 🟡 22-28% | 🔴 <22%'},
                {name:'资产负债率',score:82,status:'pass',detail:'资产负债率约48%，扩张冗余充足',explanation:'资本结构稳健'},
                {name:'经营现金流',score:75,status:'pass',detail:'经营性现金流净额超25亿元',explanation:'高效存货与账期管理'},
            ]},
            tech_moat: { score:88, grade:'A', checks:[
                {name:'FC-BGA基板突破',score:92,status:'pass',detail:'无锡基地14层以上高频高速基板量产',explanation:'打破海外高端IC封装基板垄断'},
                {name:'AI服务器PCB能力',score:85,status:'pass',detail:'全面掌握OAM/UBB等高端AI服务器PCB技术',explanation:'已打入核心算力芯片供应链'},
                {name:'研发投入强度',score:88,status:'pass',detail:'研发占营收比超8%（超12亿元）',explanation:'深耕HDI、先进封装领域'},
            ]},
            capacity: { score:75, grade:'C', checks:[
                {name:'广州封装基板项目',score:65,status:'warn',detail:'FC-BGA规划产能2亿颗，仍在爬坡期',explanation:'新产线良率爬升周期长',action:'密切跟踪大客户审厂及良率拐点'},
                {name:'南通三期',score:82,status:'pass',detail:'专注汽车电子PCB，已全面达产',explanation:'产能满载带来规模效应'},
                {name:'数字化工厂',score:78,status:'pass',detail:'高度自动化提升生产效率',explanation:'一站式解决方案协同效应逐步体现'},
            ]},
            auto_elec: { score:82, grade:'B', checks:[
                {name:'Tier 1客户渗透',score:85,status:'pass',detail:'已导入多家国际与国内知名Tier 1及整车厂',explanation:'车用PCB市占率提升'},
                {name:'订单能见度',score:78,status:'pass',detail:'汽车业务订单覆盖至2025年Q3',explanation:'汽车智能化/电动化趋势下附加值增长'},
            ]},
            valuation: { score:65, grade:'C', checks:[
                {name:'PE 估值(TTM)',score:68,status:'warn',detail:'PE 约29X，近三年中枢合理偏高',explanation:'市场给予算力基板国产替代溢价',threshold:'🟢 <20X | 🟡 20-35X | 🔴 >35X'},
                {name:'PB 估值',score:62,status:'warn',detail:'PB 约4.1X，历史均值+1σ附近',explanation:'重资产属性下PB偏高'},
                {name:'股息率',score:65,status:'warn',detail:'股息率约1.2%，保持连续分红',explanation:'成长型周期股非高收益分红标的'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'深南电路',ticker:'002916.SZ',
            market_cap:'538亿',price:'105.20',pe:'28.8',pb:'4.1',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules,audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'FC-BGA良率不及预期',level:'high',desc:'高端封装基板量产初期面临较大良率挑战',probability:'中等',impact:'重大',mitigation:'引进高端人才，强化产学研结合'},
                {name:'折旧压力剧增',level:'high',desc:'广州及无锡新厂房大额资产固化',probability:'极高',impact:'中等',mitigation:'加速订单导入实现规模化'},
                {name:'宏观需求下行',level:'medium',desc:'消费电子及通信基站建设放缓',probability:'高',impact:'中等',mitigation:'业务结构向AI和汽车迁移'},
            ],
            verdict:{
                bull:['国产算力唯一正宗高端载板(FC-BGA)稀缺标的','AI服务器(OAM、GPU板)量价齐升','汽车电子三期达产，第二曲线确定性强'],
                bear:['中短期折旧海啸压制利润率','PE近30X已抢跑反映部分算力预期','传统通信PCB复苏动能疲软'],
                catalysts:['大客户FC-BGA产品正式通过验证','全球AI算力CAPEX二次上修','国产算力芯片规模化出货'],
                positioning:'🌟 核心配置。逢低(PB<3.5X或调整超15%)坚决加仓。',
                rating:'buy',rating_text:'📈 积极看多 / 核心底仓',
                summary:'深南电路是国内少数具备"PCB+基板+装联"一站式能力的企业。AI算力及FC-BGA国产化进程将成为未来三年增长主轴。尽管短期受产能爬坡与折旧干扰，中长期安全边际确立。建议作为硬科技赛道核心标的超配。'
            },
            financials:{
                years:['2019','2020','2021','2022','2023','2024E','2025E'],
                revenue:[105.2,116.0,139.4,139.9,135.3,165.0,195.0],
                net_income:[12.3,14.3,14.8,16.4,14.0,19.3,23.5],
                gross_margin:[26.5,26.5,23.7,25.5,23.4,24.5,25.8],
                rd_expense:[5.4,6.4,7.8,8.2,10.7,12.5,14.0],
                capex:[15.2,22.0,31.0,48.0,35.0,22.0,15.0],
                biz_split:{'印制电路板(PCB)':58,'封装基板':22,'电子装联':15,'其他':5}
            }
        };
    },

    buildKPIs(d) {
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':'warn',indicator:d.trust_score>=70?'● 可投':'◐ 谨慎'},
            {label:'技术护城河',icon:'🧠',value:d.modules.tech_moat.score,suffix:'',sub:'FC-BGA破局·AI PCB',level:'pass',indicator:'🔮 核心优势'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:'营收+22% · 强劲造血',level:'pass'},
            {label:'产能良率',icon:'🏭',value:d.modules.capacity.score,suffix:'',sub:'广州爬坡·南通达产',level:d.modules.capacity.score>=70?'pass':'warn'},
            {label:'估值周期',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:'warn',indicator:'◐ 合理偏高'},
            {label:'汽车体系',icon:'🚗',value:d.modules.auto_elec.score,suffix:'',sub:'Tier1渗透·订单确定',level:'pass'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(236,72,153,0.3)');
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'35%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#a78bfa'},{offset:1,color:'#8b5cf6'}]},borderRadius:[4,4,0,0]}},
                {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#ec4899',width:2.5},itemStyle:{color:'#f472b6'},symbol:'circle',symbolSize:6,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(236,72,153,0.1)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        core.initChart('chart-margins')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.1)'},{offset:1,color:'transparent'}]}},
                    markLine:{silent:true,data:[{yAxis:28,label:{show:true,formatter:'健康线 28%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}}
            ]
        });
        core.initChart('chart-rdcapex')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'研发投入',type:'bar',data:f.rd_expense,barWidth:'25%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#60a5fa'},{offset:1,color:'#3b82f6'}]},borderRadius:[3,3,0,0]}},
                {name:'资本开支',type:'line',data:f.capex,smooth:true,lineStyle:{color:'#f59e0b',width:2.5,type:'dashed'},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:6}
            ]
        });
        const ns=f.biz_split;
        core.initChart('chart-nodes')?.setOption({
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(236,72,153,0.3)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(ns).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#8b5cf6','#ec4899','#3b82f6','#475569']}]
        });
    }
});
