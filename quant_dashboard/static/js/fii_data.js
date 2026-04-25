/**
 * AlphaCore · 工业富联 审计数据文件 (Phase 3A)
 */
AuditCore.init({
    companyName: '工业富联',
    themeColor: '#0ea5e9',
    themeColorRgba: 'rgba(14,165,233,',
    localStorageKey: 'alphacore_fii_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        financial:    { icon:'💰', color:'#10b981', label:'财务健康', weight:25 },
        ai_moat:      { icon:'🤖', color:'#0ea5e9', label:'AI算力护城河', weight:20 },
        supply_chain: { icon:'🔗', color:'#f59e0b', label:'供应链韧性', weight:20 },
        valuation:    { icon:'📊', color:'#3b82f6', label:'估值合理性', weight:15 },
        growth:       { icon:'🚀', color:'#8b5cf6', label:'成长动能', weight:20 },
    },
    shortLabels: { financial:'财务', ai_moat:'AI算力', supply_chain:'供应链', valuation:'估值', growth:'成长' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'💰 正在审计 [1/5] 财务健康… 营收·利润率·现金流·分红' },
        { t:600, text:'🤖 正在审计 [2/5] AI算力护城河… 市占率·客户绑定·全栈覆盖' },
        { t:900, text:'🔗 正在审计 [3/5] 供应链韧性… 客户集中度·地缘风险·产能布局' },
        { t:1200, text:'📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·股息率' },
        { t:1500, text:'🚀 正在审计 [5/5] 成长动能… AI CapEx周期·产品升级·营收增速' },
        { t:1800, text:'✅ 五维穿透审计完成，正在生成报告…' },
    ],

    buildData() {
        const modules = {
            financial: { score:75, grade:'B', checks:[
                {name:'营收增长',score:92,status:'pass',detail:'2025年营收9028.87亿元，YoY +48.22%，AI算力需求驱动爆发式增长',explanation:'全球AI基础设施资本开支高增长，公司作为核心供应商深度受益',threshold:'🟢 >20% | 🟡 10-20% | 🔴 <10%'},
                {name:'净利润增速',score:88,status:'pass',detail:'归母净利润352.86亿元，YoY +51.99%，利润增速高于营收增速',explanation:'产品结构升级(高毛利AI服务器占比提升)带动盈利质量改善',threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%'},
                {name:'毛利率',score:48,status:'warn',detail:'综合毛利率约7.5%，制造业属性决定毛利水平偏低',explanation:'代工制造业固有特征，但AI产品占比提升正推动毛利率边际改善(2024: 7.1%→2025: 7.5%)',threshold:'🟢 >12% | 🟡 6-12% | 🔴 <6%'},
                {name:'经营性现金流',score:55,status:'warn',detail:'全年经营性现金流净额+52.38亿元，转正但远低于净利润(352亿)',explanation:'订单高峰期备货导致存货大幅增加，应收账款规模扩大，现金转化率偏低',action:'关注Q1/Q2现金回流节奏，若OCF/NI持续<30%需提升预警'},
                {name:'资产负债率',score:62,status:'warn',detail:'资产负债率约65%，有息资产负债率23.19%，短期借款显著增加',explanation:'快速扩产期杠杆率上升，但有息负债率可控，需关注资金周转效率'},
                {name:'分红回报',score:82,status:'pass',detail:'全年累计现金分红194.51亿元，现金分红率55.12%，EPS 1.78元',explanation:'分红率超50%，在成长股中属于高分红水平，彰显盈利质量信心'},
            ]},
            ai_moat: { score:88, grade:'A', checks:[
                {name:'AI服务器全球份额',score:95,status:'pass',detail:'全球AI服务器市场份额超40%，稳居行业第一',explanation:'深度绑定NVIDIA、AMD等算力芯片巨头，JDM联合研发模式构建壁垒'},
                {name:'核心客户绑定',score:92,status:'pass',detail:'深度服务微软、谷歌、亚马逊、Meta等全球Top CSP，订单能见度至2027年',explanation:'从OEM代工升级为JDM(联合研发)合作伙伴，客户粘性极高'},
                {name:'AI服务器营收爆发',score:93,status:'pass',detail:'云服务商AI服务器营收YoY增长超3倍(>300%)，云计算板块营收6027亿元(+88.7%)',explanation:'GB200/B200等新一代GPU服务器量产交付，驱动营收爆发式增长'},
                {name:'算力全栈覆盖',score:85,status:'pass',detail:'从GPU模组、基板、服务器整机到液冷系统、高速交换机全产业链覆盖',explanation:'系统级整合能力构成深厚竞争壁垒，800G以上高速交换机营收YoY增长13倍'},
                {name:'下一代产品储备',score:78,status:'pass',detail:'GB300/Rubin架构等下一代算力产品研发跟进中，量产计划明确',explanation:'技术迭代响应速度是保持龙头地位的关键，目前节奏领先同业'},
            ]},
            supply_chain: { score:62, grade:'C', checks:[
                {name:'客户集中度',score:42,status:'fail',detail:'前五大客户营收占比约65-70%，高度依赖少数核心CSP',explanation:'若核心客户资本开支收缩或份额调整，将直接冲击业绩表现',action:'持续监控微软/谷歌/Meta等头部客户CapEx指引'},
                {name:'地缘政治风险',score:48,status:'warn',detail:'全球贸易环境不确定性加剧，出口管制政策可能影响跨境供应链',explanation:'虽非直接制裁标的，但中美科技脱钩趋势可能间接影响全球产能布局'},
                {name:'上游供应依赖',score:55,status:'warn',detail:'核心GPU芯片(NVIDIA/AMD)供应受制于上游，产能分配权不在手中',explanation:'GPU供应紧张时，分配优先级由NVIDIA决定，被动受制于上游格局'},
                {name:'产能全球布局',score:78,status:'pass',detail:'全球制造基地覆盖中国、越南、墨西哥、印度等地，产能弹性强',explanation:'多元化产能布局可对冲单一地区地缘风险，灯塔工厂模式提升制造效率'},
                {name:'库存管理',score:58,status:'warn',detail:'2025年存货规模大幅增加(备货AI服务器组件)，库存周转天数上升',explanation:'AI订单高峰期备货属合理行为，但需警惕需求放缓后的库存减值风险'},
            ]},
            valuation: { score:65, grade:'C', checks:[
                {name:'PE估值',score:70,status:'pass',detail:'PE(TTM) ~29.4X，对比全球EMS行业均值15-20X偏高，但AI算力赛道溢价合理',explanation:'市场给予AI算力龙头结构性溢价，若按2026E净利润450亿元计，前瞻PE ~23X',threshold:'🟢 <25X | 🟡 25-35X | 🔴 >35X'},
                {name:'PB估值',score:42,status:'warn',detail:'PB ~6.21X，显著高于传统EMS行业均值2-3X',explanation:'高PB反映市场对AI转型溢价认可，但估值回归风险存在',threshold:'🟢 <3X | 🟡 3-6X | 🔴 >6X'},
                {name:'EV/EBITDA',score:55,status:'warn',detail:'EV/EBITDA ~18X，高于行业均值10X，但低于纯AI概念股',explanation:'相对于纯软件/芯片AI标的(30-50X)，制造型AI龙头估值仍具性价比'},
                {name:'DCF内在价值',score:72,status:'pass',detail:'乐观/中性/悲观情景估值：68/52/38 元(当前¥52.18)',explanation:'中性情景锚定当前价格，若AI CapEx周期延续至2028年，上行空间约30%',action:'关注2026Q1业绩是否超预期验证估值支撑'},
                {name:'股息率',score:78,status:'pass',detail:'股息率约3.7%，分红率55.12%',explanation:'在万亿市值科技股中，3.7%股息率极具吸引力，提供估值安全边际'},
            ]},
            growth: { score:85, grade:'A', checks:[
                {name:'AI CapEx超级周期',score:92,status:'pass',detail:'全球AI基础设施资本开支2025-2027年CAGR预计超40%，公司处于核心受益位',explanation:'微软/谷歌/Meta/Amazon年度CapEx合计超3000亿美元，持续加码AI算力建设'},
                {name:'营收增速',score:90,status:'pass',detail:'2024-2026E CAGR约35-40%，远超传统EMS行业5-8%增速',explanation:'AI服务器+高速交换机双引擎驱动，结构性增长远超行业均值'},
                {name:'产品升级路径',score:82,status:'pass',detail:'从通用服务器→AI推理服务器→AI训练服务器，ASP(平均售价)持续提升',explanation:'GPU服务器ASP是传统服务器的5-10倍，产品结构升级直接拉升营收天花板'},
                {name:'AI需求可持续性',score:68,status:'warn',detail:'AI CapEx周期预计持续至2028年，但需警惕2027年后增速放缓的可能',explanation:'当前属于AI基础设施建设爆发期，长期可持续性取决于AI应用落地进度',action:'密切关注全球CSP季度CapEx指引变化'},
                {name:'智能制造输出',score:72,status:'pass',detail:'灯塔工厂技术对外输出，工业互联网平台收入稳步增长',explanation:'制造能力IP化输出构建第二增长曲线，但体量暂小'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'工业富联',ticker:'601138.SH',
            market_cap:'1.04万亿',price:'52.18',pe:'29.4',pb:'6.21',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules,audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'客户集中度风险',level:'critical',desc:'营收高度依赖少数核心CSP(微软/谷歌/Meta/Amazon)',probability:'中等',impact:'致命',mitigation:'多元化客户拓展+长期合约锁定'},
                {name:'AI CapEx放缓风险',level:'critical',desc:'若全球AI投资回报不及预期，大厂可能收缩CapEx',probability:'中低',impact:'致命',mitigation:'关注季度CapEx指引+提前调整产能'},
                {name:'地缘政治/出口管制',level:'high',desc:'中美科技脱钩升级、芯片出口管制趋严',probability:'中等',impact:'重大',mitigation:'全球多元化产能布局(越南/墨西哥/印度)'},
                {name:'毛利率天花板',level:'high',desc:'代工制造业固有的低毛利率(7-8%)限制盈利空间上限',probability:'高',impact:'中等',mitigation:'提升JDM占比+高附加值产品结构优化'},
                {name:'上游GPU供应风险',level:'high',desc:'核心GPU芯片供应受制于NVIDIA产能分配',probability:'中等',impact:'重大',mitigation:'深化NVIDIA战略合作+拓展AMD/自研ASIC方案'},
                {name:'PB估值回归风险',level:'medium',desc:'PB 6.21X显著高于EMS行业均值(2-3X)',probability:'中等',impact:'中等',mitigation:'高分红率(55%)提供安全边际+业绩增长消化估值'},
                {name:'存货减值风险',level:'medium',desc:'AI订单备货期存货大幅膨胀',probability:'中低',impact:'中等',mitigation:'动态订单管理+JIT供应链优化'},
            ],
            verdict:{
                bull:['全球AI服务器绝对龙头，市占率超40%','2025年营收9029亿元(+48%)、净利润353亿元(+52%)','AI CapEx超级周期2025-2028年确定性强','高分红率55.12%(股息率3.7%)兼具成长+价值属性'],
                bear:['毛利率仅7.5%，代工制造业属性限制盈利上限','客户集中度极高(前五大占比~70%)','PB 6.21X严重偏高于EMS行业均值','经营性现金流远低于净利润，现金转化率偏低'],
                catalysts:['GB300/Rubin架构量产交付','2026Q1业绩超预期验证增长持续性','全球CSP CapEx指引上调','NVIDIA新一代GPU平台大规模部署'],
                positioning:'🟢 AI算力核心Beta标的。建议仓位8-12%。',
                rating:'buy',rating_text:'📈 积极买入 / AI算力核心配置',
                summary:'工业富联是全球AI算力基础设施的绝对龙头，2025年营收突破9000亿元(+48%)，净利润352.86亿元(+52%)。JDM模式深度绑定全球头部CSP，订单能见度延伸至2027年。PE 29X在AI CapEx超级周期背景下估值合理。核心风险在于客户集中度和毛利率天花板。建议仓位8-12%。'
            },
            financials:{
                years:['2019','2020','2021','2022','2023','2024','2025'],
                revenue:[4086.9,4317.9,4396.1,5118.5,4763.4,6091.4,9028.9],
                net_income:[186.1,174.3,200.1,200.7,210.2,232.2,352.9],
                gross_margin:[8.4,8.3,8.3,7.3,7.6,7.1,7.5],
                net_margin:[4.6,4.0,4.6,3.9,4.4,3.8,3.9],
                cloud_revenue:[1629,1804,1776,2124,2005,3194,6027],
                ai_server_pct:[5,8,12,18,25,40,66.7],
                biz_split:{'云计算':66.7,'通信及移动网络':33.0,'其他':0.3}
            }
        };
    },

    buildKPIs(d) {
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail',indicator:d.trust_score>=70?'● 可投':'◐ 谨慎'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:'营收+48% · 净利+52%',level:d.modules.financial.score>=70?'pass':'warn'},
            {label:'AI算力护城河',icon:'🤖',value:d.modules.ai_moat.score,suffix:'',sub:'全球AI服务器份额>40%',level:'pass',indicator:'🟢 绝对龙头'},
            {label:'供应链韧性',icon:'🔗',value:d.modules.supply_chain.score,suffix:'',sub:'客户集中度为核心关切',level:d.modules.supply_chain.score>=70?'pass':'warn',indicator:'⚠ 需关注'},
            {label:'估值合理性',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:d.modules.valuation.score>=70?'pass':'warn'},
            {label:'成长动能',icon:'🚀',value:d.modules.growth.score,suffix:'',sub:'AI CapEx超级周期驱动',level:'pass',indicator:'🟢 强劲'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(14,165,233,0.2)');
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#38bdf8'},{offset:1,color:'#0ea5e9'}]},borderRadius:[4,4,0,0]}},
                {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.12)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        core.initChart('chart-margins')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,max:12},
            series:[
                {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.15)'},{offset:1,color:'transparent'}]}},
                    markLine:{silent:true,data:[{yAxis:8,label:{show:true,formatter:'行业均值 8%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
                {name:'净利率',type:'line',data:f.net_margin,smooth:true,lineStyle:{color:'#06b6d4',width:2,type:'dashed'},itemStyle:{color:'#22d3ee'},symbol:'circle',symbolSize:6}
            ]
        });
        core.initChart('chart-cloud')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis},
            yAxis:[{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},position:'right',max:100,...S.axis,splitLine:{show:false}}],
            series:[
                {name:'云计算营收',type:'bar',data:f.cloud_revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#a78bfa'},{offset:1,color:'#8b5cf6'}]},borderRadius:[4,4,0,0]}},
                {name:'AI服务器占比',type:'line',yAxisIndex:1,data:f.ai_server_pct,smooth:true,lineStyle:{color:'#f43f5e',width:2.5},itemStyle:{color:'#fb7185'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(244,63,94,0.12)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        const bs=f.biz_split;
        core.initChart('chart-segments')?.setOption({
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(14,165,233,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(bs).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#0ea5e9','#8b5cf6','#475569']}]
        });
    }
});
