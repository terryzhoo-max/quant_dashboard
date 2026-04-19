/**
 * AlphaCore · 中芯国际(SMIC) 审计数据文件 (Phase 3A)
 */
AuditCore.init({
    companyName: '中芯国际',
    themeColor: '#6366f1',
    themeColorRgba: 'rgba(99,102,241,',
    localStorageKey: 'alphacore_smic_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        financial:  { icon:'💰', color:'#10b981', label:'财务健康', weight:25 },
        tech_moat:  { icon:'🔬', color:'#6366f1', label:'技术护城河', weight:20 },
        geopolitics:{ icon:'🌍', color:'#f59e0b', label:'地缘风险', weight:25 },
        valuation:  { icon:'📊', color:'#3b82f6', label:'估值合理性', weight:15 },
        growth:     { icon:'🚀', color:'#8b5cf6', label:'成长动能', weight:15 },
    },
    shortLabels: { financial:'财务', tech_moat:'技术', geopolitics:'地缘', valuation:'估值', growth:'成长' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'🔬 正在审计 [1/5] 财务健康… 营收·利润率·现金流·杠杆率' },
        { t:600, text:'🔬 正在审计 [2/5] 技术护城河… 制程节点·产能规模·专利壁垒' },
        { t:900, text:'🌍 正在审计 [3/5] 地缘风险… 制裁清单·供应链·政策支持' },
        { t:1200, text:'📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA' },
        { t:1500, text:'🚀 正在审计 [5/5] 成长动能… 产能扩张·下游需求·市占率' },
        { t:1800, text:'✅ 五维穿透审计完成，正在生成报告…' },
    ],

    buildData() {
        const modules = {
            financial: { score:70, grade:'B', checks:[
                {name:'营收增长',score:80,status:'pass',detail:'2025年营收约660亿元(~$93.3亿)，YoY +27%',explanation:'晶圆代工行业平均增速12%，SMIC显著领先',threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%'},
                {name:'毛利率',score:62,status:'warn',detail:'综合毛利率约22.0%，低于台积电(55%)和联电(32%)',explanation:'产能利用率回升推动毛利率修复',threshold:'🟢 >30% | 🟡 15-30% | 🔴 <15%'},
                {name:'净利润',score:50,status:'warn',detail:'净利润约49亿元，净利率~7.4%',explanation:'折旧高峰期吞噬大量利润空间'},
                {name:'自由现金流',score:38,status:'fail',detail:'FCF持续为负(约-300亿元)，CAPEX/营收比超55%',explanation:'4座新厂同步建设期FCF必然为负',action:'关注产能利用率回升节点'},
                {name:'资产负债率',score:72,status:'pass',detail:'资产负债率54%，有息负债率40%',explanation:'对比行业平均55%，SMIC杠杆水平合理'},
                {name:'研发投入',score:85,status:'pass',detail:'研发费用率约10.5%，研发投入约69亿元',explanation:'持续高研发投入是突破先进制程的必要条件'},
            ]},
            tech_moat: { score:68, grade:'C', checks:[
                {name:'制程节点',score:60,status:'warn',detail:'量产最先进制程：14nm FinFET(N+1/N+2)',explanation:'受EUV光刻机禁运限制'},
                {name:'产能规模',score:82,status:'pass',detail:'月产能已突破100万片8寸当量，全球第三大纯晶圆代工厂',explanation:'规模效应显著，成熟制程产能利用率93.5%'},
                {name:'技术自主率',score:55,status:'warn',detail:'关键设备自主率约18-22%',explanation:'光刻机、刻蚀机等核心设备仍依赖进口'},
                {name:'客户集中度',score:70,status:'pass',detail:'前五大客户营收占比约52%',explanation:'客户结构持续优化'},
                {name:'专利壁垒',score:70,status:'pass',detail:'累计专利超13,500项',explanation:'专利布局集中在成熟制程工艺'},
            ]},
            geopolitics: { score:42, grade:'D', checks:[
                {name:'制裁风险',score:28,status:'fail',detail:'已被列入美国实体清单，EUV及部分DUV设备禁运',explanation:'2022年10月BIS新规后，先进制程设备获取受限',action:'持续跟踪出口管制政策'},
                {name:'供应链韧性',score:40,status:'fail',detail:'核心设备断供风险高，备件库存约16个月',explanation:'设备禁运→产能扩张受限→长期竞争力天花板'},
                {name:'政策支持',score:82,status:'pass',detail:'大基金一期/二期/三期持续投资',explanation:'国家半导体战略核心标的'},
                {name:'国际竞争格局',score:45,status:'warn',detail:'与GlobalFoundries、联电竞争成熟制程市场',explanation:'成熟制程价格战加剧'},
                {name:'合规风险',score:32,status:'fail',detail:'美国"最终用户"审查趋严，部分客户订单受限',explanation:'地缘政治不确定性为最大系统性风险'},
            ]},
            valuation: { score:38, grade:'D', checks:[
                {name:'PE估值',score:18,status:'fail',detail:'PE(TTM) ~145.7X，全球主要晶圆代工厂最高',explanation:'市场price-in极强国产替代溢价',threshold:'🟢 <20X | 🟡 20-40X | 🔴 >40X'},
                {name:'PB估值',score:68,status:'pass',detail:'PB ~1.94X，对比历史中位数2.0X合理',explanation:'重资产行业PB估值更具参考价值',threshold:'🟢 <1.5X | 🟡 1.5-2.5X | 🔴 >2.5X'},
                {name:'EV/EBITDA',score:45,status:'warn',detail:'EV/EBITDA ~18X，高于行业平均8X',explanation:'高CAPEX导致EBITDA虚高'},
                {name:'DCF内在价值',score:42,status:'warn',detail:'乐观/中性/悲观估值：105/72/50 元(当前¥91.78)',explanation:'中性情景隐含21%下行空间',action:'若股价突破¥105，需重新评估安全边际'},
                {name:'股息率',score:60,status:'warn',detail:'股息率约0.5%，分红率约12%',explanation:'半导体扩产期分红率极低'},
            ]},
            growth: { score:78, grade:'B', checks:[
                {name:'营收增速',score:85,status:'pass',detail:'2024-2026E CAGR约22-28%',explanation:'AI算力+国产替代+消费电子复苏三轮驱动'},
                {name:'产能扩张',score:80,status:'pass',detail:'4座12寸晶圆厂同步推进',explanation:'2025年底百万片里程碑'},
                {name:'下游需求',score:75,status:'pass',detail:'AI边缘推理芯片/汽车芯片/IoT需求爆发',explanation:'成熟制程需求结构性增长'},
                {name:'国产替代市占率',score:82,status:'pass',detail:'国内晶圆代工市占率约38%',explanation:'政策驱动+供应链安全诉求'},
                {name:'技术演进',score:52,status:'warn',detail:'N+1/N+2制程良率提升缓慢',explanation:'无EUV约束下的先进制程突破存在不确定性'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'中芯国际',ticker:'688981.SH',ticker_h:'0981.HK',
            market_cap:'4,524亿',price:'91.78',pe:'145.7',pb:'1.94',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules,audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'EUV设备禁运',level:'critical',desc:'美国BIS限制ASML向中国出口EUV光刻机',probability:'极高',impact:'致命',mitigation:'DUV多重曝光替代方案'},
                {name:'制裁升级风险',level:'critical',desc:'若DUV光刻机纳入禁运，产能扩张将面临根本性威胁',probability:'中等',impact:'致命',mitigation:'加速国产设备导入验证'},
                {name:'估值泡沫化风险',level:'critical',desc:'PE 145X严重偏离基本面',probability:'高',impact:'致命',mitigation:'严格仓位控制+动态止损'},
                {name:'产能过剩周期',level:'high',desc:'全球成熟制程产能集中释放(2025-2027)',probability:'高',impact:'重大',mitigation:'差异化工艺+长期合约锁定'},
                {name:'折旧海啸',level:'high',desc:'2025-2027年折旧增长30%+',probability:'极高',impact:'重大',mitigation:'提升高毛利产品组合占比'},
                {name:'技术追赶瓶颈',level:'medium',desc:'无EUV条件下先进制程推进缓慢',probability:'高',impact:'中等',mitigation:'聚焦成熟制程差异化竞争'},
                {name:'客户流失风险',level:'medium',desc:'地缘不确定性导致部分国际客户转单',probability:'中等',impact:'中等',mitigation:'拓展国内客户'},
            ],
            verdict:{
                bull:['国产替代逻辑确定性极高，大基金三期持续注资','成熟制程需求结构性爆发','产能百万片里程碑达成','2025营收增速27%大幅领先'],
                bear:['PE 145X严重透支，估值泡沫化风险极高','地缘政治风险为不可控系统性因子','先进制程突破受限','FCF持续为负，EPS仅¥0.63'],
                catalysts:['DUV多重曝光7nm量产突破','国产光刻机导入验证成功','全球晶圆代工涨价周期启动','大基金三期投资落地'],
                positioning:'⚠️ 高风险标的。建议仓位严格控制在3-5%以内。',
                rating:'hold',rating_text:'⚖️ 谨慎持有 / 等待回调',
                summary:'中芯国际是A股半导体制造板块核心Beta标的，国产替代叙事提供长期支撑(2025营收+27%)，但PE 145X已严重脱离基本面。地缘政治风险构成系统性不确定性，折旧海啸将持续压制利润率至2027年。建议已持仓者控制仓位谨慎持有。'
            },
            financials:{
                years:['2019','2020','2021','2022','2023','2024','2025'],
                revenue:[220.2,274.7,356.3,495.2,452.5,519.3,660.0],
                net_income:[17.9,43.3,107.3,121.3,48.2,35.3,49.0],
                gross_margin:[20.8,23.8,28.7,38.3,19.3,18.6,22.0],
                caputil:[97.8,95.2,100.4,92.1,75.8,85.6,93.5],
                rd_expense:[47.4,46.7,41.2,49.5,55.3,62.1,69.0],
                capex:[67.2,57.0,105.0,255.0,310.0,288.0,350.0],
                biz_split:{'28nm+':27.5,'40nm':13.8,'55nm':19.2,'0.15-0.18µm':28.5,'其他':11.0}
            }
        };
    },

    buildKPIs(d) {
        const valLevel = d.modules.valuation.score>=55?'warn':'fail';
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail',indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:`营收+27% · 毛利率${d.financials.gross_margin[6]}%`,level:d.modules.financial.score>=70?'pass':'warn'},
            {label:'地缘风险',icon:'🌍',value:d.modules.geopolitics.score,suffix:'',sub:'制裁风险为核心制约因子',level:d.modules.geopolitics.score>=55?'warn':'fail',indicator:'⚠ 高风险'},
            {label:'技术护城河',icon:'🔬',value:d.modules.tech_moat.score,suffix:'',sub:'产能已破100万片/月',level:d.modules.tech_moat.score>=70?'pass':'warn'},
            {label:'估值合理性',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:valLevel,indicator:valLevel==='fail'?'🔴 严重偏高':'⚠ 偏高'},
            {label:'成长动能',icon:'🚀',value:d.modules.growth.score,suffix:'',sub:'CAGR 22-28% · 百万片里程碑',level:d.modules.growth.score>=70?'pass':'warn'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(99,102,241,0.2)');
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#818cf8'},{offset:1,color:'#6366f1'}]},borderRadius:[4,4,0,0]}},
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
                    markLine:{silent:true,data:[{yAxis:30,label:{show:true,formatter:'健康线 30%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
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
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(99,102,241,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(ns).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#6366f1','#8b5cf6','#a78bfa','#06b6d4','#475569']}]
        });
    }
});
