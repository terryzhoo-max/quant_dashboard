/**
 * AlphaCore · 紫金矿业 审计数据文件 (Phase 3A)
 */
AuditCore.init({
    companyName: '紫金矿业',
    themeColor: '#f59e0b',
    themeColorRgba: 'rgba(245,158,11,',
    localStorageKey: 'alphacore_zijin_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        financial:  { icon:'💰', color:'#10b981', label:'财务健康', weight:25 },
        resource:   { icon:'⛏️', color:'#f59e0b', label:'资源禀赋', weight:20 },
        global_risk:{ icon:'🌍', color:'#ef4444', label:'全球化风险', weight:20 },
        valuation:  { icon:'📊', color:'#3b82f6', label:'估值合理性', weight:15 },
        growth:     { icon:'🚀', color:'#8b5cf6', label:'成长动能', weight:20 },
    },
    shortLabels: { financial:'财务', resource:'资源', global_risk:'地缘', valuation:'估值', growth:'成长' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'💰 正在审计 [1/5] 财务健康… 营收·利润率·ROE·现金流·杠杆率' },
        { t:600, text:'⛏️ 正在审计 [2/5] 资源禀赋… 金资源量·铜资源量·矿山成本·储量替换' },
        { t:900, text:'🌍 正在审计 [3/5] 全球化风险… 刚果(金)·汇率·ESG·政策支持' },
        { t:1200, text:'📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA·股息率' },
        { t:1500, text:'🚀 正在审计 [5/5] 成长动能… 产量增速·金属价格·并购扩张·产业链' },
        { t:1800, text:'✅ 五维穿透审计完成，正在生成报告…' },
    ],

    buildData() {
        const modules = {
            financial: { score:82, grade:'B', checks:[
                {name:'营收增长',score:88,status:'pass',detail:'2025年营收约3,580亿元(+16.0%)，连续6年双位数增长',explanation:'矿业公司营收受金属价格与产量双因子驱动',threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%'},
                {name:'净利润',score:85,status:'pass',detail:'归母净利润约355亿元(+10.6%)，EPS约1.34元',explanation:'2024年归母净利润321亿元，同比+51.5%，基数效应下2025增速回归常态'},
                {name:'毛利率',score:78,status:'pass',detail:'综合毛利率约18.5%，矿产金毛利率约55%，矿产铜毛利率约38%',explanation:'矿业行业毛利率波动大，紫金矿业受益于低成本矿山组合',threshold:'🟢 >15% | 🟡 10-15% | 🔴 <10%'},
                {name:'ROE',score:80,status:'pass',detail:'ROE约22.8%(2024: 23.6%)，持续高于行业均值15%',explanation:'高ROE反映管理层优秀的资本配置能力与资源整合效率'},
                {name:'资产负债率',score:62,status:'warn',detail:'资产负债率约58.2%，有息负债超1,200亿元',explanation:'激进并购扩张导致杠杆较高，但矿业行业重资产属性下尚属可控',action:'关注利息覆盖率及现金流偿债能力',threshold:'🟢 <50% | 🟡 50-65% | 🔴 >65%'},
                {name:'自由现金流',score:72,status:'pass',detail:'经营性现金流约580亿元，FCF约220亿元(CAPEX约360亿元)',explanation:'矿业公司FCF取决于金属价格景气度'},
            ]},
            resource: { score:90, grade:'A', checks:[
                {name:'黄金资源量',score:95,status:'pass',detail:'黄金资源量约3,200吨(含权)，全球第三大金矿企业',explanation:'2024矿产金76.5吨(+12.6%)，2025E约88吨'},
                {name:'铜资源量',score:92,status:'pass',detail:'铜资源量约7,600万吨(含权)，全球前五铜矿企业',explanation:'2024矿产铜115万吨(+6.2%)，Kamoa-Kakula贡献增量'},
                {name:'锌资源量',score:78,status:'pass',detail:'锌资源量约1,100万吨，矿产锌约48万吨(2024)',explanation:'锌板块盈利贡献约8%，提供多元化对冲'},
                {name:'资源自给率',score:88,status:'pass',detail:'矿产金/铜/锌自给率分别约95%/82%/90%',explanation:'高资源自给率确保利润率与供应安全'},
                {name:'矿山成本控制',score:85,status:'pass',detail:'矿产金AISC约1,050美元/盎司，矿产铜C1成本约1.45美元/磅',explanation:'低成本优势是抵御金属价格下行的核心护城河',threshold:'🟢 AISC<1200 | 🟡 1200-1500 | 🔴 >1500'},
                {name:'储量替换率',score:82,status:'pass',detail:'储量替换率约130%，新发现矿体+并购双重补充',explanation:'储量持续增长是矿企可持续经营的核心指标'},
            ]},
            global_risk: { score:55, grade:'C', checks:[
                {name:'地缘集中度',score:48,status:'warn',detail:'海外营收占比约42%，刚果(金)/塞尔维亚/巴新等高风险地区资产占比约35%',explanation:'刚果(金)政治不稳定性+矿业税收政策波动为核心风险因子',action:'跟踪刚果(金)矿业法修订及特许权费率变化'},
                {name:'刚果(金)风险',score:38,status:'fail',detail:'Kamoa-Kakula铜矿占铜产量约30%，刚果(金)政局不稳+矿业税改风险',explanation:'2025年刚果(金)拟提高矿业特许权使用费率至8-10%',action:'评估特许权费率上调对铜板块毛利率的影响'},
                {name:'汇率风险',score:65,status:'warn',detail:'大量海外资产以美元计价，人民币汇率波动影响约±15亿元/年',explanation:'矿业公司天然具有美元资产敞口'},
                {name:'环保合规',score:60,status:'warn',detail:'ESG评级BBB(MSCI)，尾矿库管理与碳中和承诺有待提升',explanation:'海外矿山环保标准趋严，合规成本逐年增加约5-8%'},
                {name:'政策支持',score:75,status:'pass',detail:'国内矿业龙头地位稳固，"走出去"战略获政策背书',explanation:'一带一路+矿产资源安全战略提供稳定的政策环境'},
            ]},
            valuation: { score:65, grade:'C', checks:[
                {name:'PE估值',score:58,status:'warn',detail:'PE(TTM) ~18.5X，高于全球矿业巨头(Barrick 14X)',explanation:'A股矿业龙头享有流动性溢价',threshold:'🟢 <15X | 🟡 15-25X | 🔴 >25X'},
                {name:'PB估值',score:52,status:'warn',detail:'PB ~3.8X，显著高于全球矿业中位数1.5X',explanation:'高ROE(22.8%)支撑较高PB定价',threshold:'🟢 <2.0X | 🟡 2.0-4.0X | 🔴 >4.0X'},
                {name:'EV/EBITDA',score:68,status:'pass',detail:'EV/EBITDA ~8.5X，处于全球矿企合理区间(6-10X)',explanation:'矿业行业EV/EBITDA估值更具横向可比性'},
                {name:'DCF内在价值',score:72,status:'pass',detail:'乐观/中性/悲观情景估值：22.5/18.0/13.5 元(当前¥19.8)',explanation:'中性情景显示当前股价略低于内在价值，安全边际约9%'},
                {name:'股息率',score:70,status:'pass',detail:'股息率约2.8%，分红率约38%',explanation:'矿业公司高分红是价值投资重要信号'},
            ]},
            growth: { score:85, grade:'A', checks:[
                {name:'产量增速',score:90,status:'pass',detail:'2024-2028E矿产金CAGR约15%，矿产铜CAGR约12%',explanation:'新矿投产推动产量高速增长'},
                {name:'金属价格趋势',score:82,status:'pass',detail:'国际金价$3,200+/盎司，铜价$9,800+/吨',explanation:'全球降息周期+地缘避险推高黄金'},
                {name:'并购扩张',score:88,status:'pass',detail:'2024年完成多项战略并购，资源版图持续扩大',explanation:'紫金矿业并购整合能力为国内矿企最强'},
                {name:'产业链延伸',score:75,status:'pass',detail:'向新能源材料(碳酸锂/镍)延伸布局',explanation:'第二增长曲线布局'},
                {name:'国产替代机遇',score:78,status:'pass',detail:'国内金铜资源自给率不足50%',explanation:'矿产资源安全纳入国家战略',action:'关注国内矿权审批加速'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'紫金矿业',ticker:'601899.SH',ticker_h:'2899.HK',
            market_cap:'5,246亿',price:'19.80',pe:'18.5',pb:'3.80',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules,audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'刚果(金)政治风险',level:'critical',desc:'Kamoa-Kakula铜矿所在刚果(金)政局不稳',probability:'高',impact:'重大',mitigation:'多元化矿区布局+政府关系维护'},
                {name:'金属价格回调风险',level:'critical',desc:'金价$3,200+/铜价$9,800+均处历史高位',probability:'中等',impact:'致命',mitigation:'AISC成本优势+多金属对冲'},
                {name:'海外资产减值风险',level:'high',desc:'大量海外并购资产存在商誉及矿权减值风险',probability:'中等',impact:'重大',mitigation:'保守减值测试+加速矿山达产'},
                {name:'ESG及环保风险',level:'high',desc:'尾矿库安全+碳排放政策趋严',probability:'中等',impact:'中等',mitigation:'ESG评级提升+绿色矿山建设'},
                {name:'资产负债率偏高',level:'medium',desc:'有息负债超1,200亿元',probability:'低',impact:'中等',mitigation:'经营现金流充沛+滚动再融资'},
                {name:'汇率波动风险',level:'medium',desc:'海外资产美元计价约占总资产42%',probability:'中等',impact:'轻微',mitigation:'自然对冲+适度外汇套保'},
            ],
            verdict:{
                bull:['全球第三大金矿+前五铜矿企业，资源禀赋全球顶级','矿产金/铜CAGR 15%/12%，增速远超全球矿业','低AISC成本构成抵御价格下行的核心护城河','ROE持续>22%，资本配置能力业内领先'],
                bear:['刚果(金)政治风险可能冲击铜板块30%产量','金铜价格处于历史高位，回调风险不容忽视','资产负债率58%偏高，并购节奏过于激进','PB 3.8X处于历史高位，估值溢价空间收窄'],
                catalysts:['黄金突破$3,500/盎司','西藏巨龙铜矿二期投产(2026H2)','Kamoa-Kakula三期满产','国内矿权审批加速'],
                positioning:'✅ 优质龙头标的。建议仓位8-12%。',
                rating:'buy',rating_text:'📈 战略性建仓 / 逢低加仓',
                summary:'紫金矿业是A股唯一具有全球顶级资源禀赋的矿业龙头，金铜双轮驱动下2025年营收预计达3,580亿元(+16%)。ROE持续>22%、AISC全球低位、储量替换率>130%构成三重护城河。主要风险为刚果(金)地缘政治不确定性及金属价格高位回调。当前PE 18.5X处于合理偏高区间。'
            },
            financials:{
                years:['2019','2020','2021','2022','2023','2024','2025E'],
                revenue:[1361,1715,2252,2703,2934,3086,3580],
                net_income:[42.8,65.1,157.0,200.4,211.8,321.0,355.0],
                gross_margin:[10.2,11.8,16.5,14.8,13.5,17.2,18.5],
                roe:[15.2,18.6,28.6,25.4,21.8,23.6,22.8],
                gold_output:[40.8,44.6,57.7,67.7,68.0,76.5,88.0],
                copper_output:[37.1,45.3,58.4,90.5,108.3,115.0,125.0],
                zinc_output:[31.2,35.6,38.5,42.0,44.8,48.0,52.0],
                biz_split:{'金矿':32,'铜矿':38,'锌矿':8,'冶炼加工':15,'其他':7}
            }
        };
    },

    buildKPIs(d) {
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':'warn',indicator:d.trust_score>=70?'● 可投':'◐ 谨慎'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:'营收+16% · ROE 22.8%',level:'pass'},
            {label:'资源禀赋',icon:'⛏️',value:d.modules.resource.score,suffix:'',sub:'全球第三大金矿企业',level:'pass',indicator:'🥇 顶级'},
            {label:'全球化风险',icon:'🌍',value:d.modules.global_risk.score,suffix:'',sub:'刚果(金)政治风险为核心制约',level:d.modules.global_risk.score>=55?'warn':'fail',indicator:'⚠ 中等'},
            {label:'估值合理性',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:'warn',indicator:'◐ 合理偏高'},
            {label:'成长动能',icon:'🚀',value:d.modules.growth.score,suffix:'',sub:'金铜CAGR 15%/12%',level:'pass',indicator:'● 强劲'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(245,158,11,0.2)');
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#fbbf24'},{offset:1,color:'#f59e0b'}]},borderRadius:[4,4,0,0]}},
                {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.12)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        core.initChart('chart-margins')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,max:35},
            series:[
                {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.15)'},{offset:1,color:'transparent'}]}},
                    markLine:{silent:true,data:[{yAxis:15,label:{show:true,formatter:'健康线 15%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
                {name:'ROE',type:'line',data:f.roe,smooth:true,lineStyle:{color:'#8b5cf6',width:2,type:'dashed'},itemStyle:{color:'#a78bfa'},symbol:'circle',symbolSize:6}
            ]
        });
        core.initChart('chart-production')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis},
            yAxis:[{type:'value',name:'吨(金)',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},{type:'value',name:'万吨(铜/锌)',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,splitLine:{show:false}}],
            series:[
                {name:'矿产金(吨)',type:'bar',data:f.gold_output,barWidth:'22%',yAxisIndex:0,itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#fcd34d'},{offset:1,color:'#f59e0b'}]},borderRadius:[3,3,0,0]}},
                {name:'矿产铜(万吨)',type:'line',data:f.copper_output,smooth:true,yAxisIndex:1,lineStyle:{color:'#c2410c',width:2.5},itemStyle:{color:'#ea580c'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(194,65,12,0.1)'},{offset:1,color:'transparent'}]}}},
                {name:'矿产锌(万吨)',type:'line',data:f.zinc_output,smooth:true,yAxisIndex:1,lineStyle:{color:'#06b6d4',width:2,type:'dashed'},itemStyle:{color:'#22d3ee'},symbol:'circle',symbolSize:5}
            ]
        });
        const rs=f.biz_split;
        core.initChart('chart-segments')?.setOption({
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(245,158,11,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(rs).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#fbbf24','#c2410c','#06b6d4','#6366f1','#475569']}]
        });
    }
});
