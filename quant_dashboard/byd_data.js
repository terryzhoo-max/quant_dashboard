/**
 * AlphaCore · 比亚迪 审计数据文件 (Phase 3A)
 * 纯数据 + 图表配置，渲染逻辑由 audit_core.js 驱动
 */
AuditCore.init({
    companyName: '比亚迪',
    themeColor: '#10b981',
    themeColorRgba: 'rgba(16,185,129,',
    localStorageKey: 'alphacore_byd_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        financial:   { icon:'💰', color:'#10b981', label:'财务健康', weight:25 },
        technology:  { icon:'🔋', color:'#3b82f6', label:'技术护城河', weight:20 },
        competition: { icon:'⚔️', color:'#f59e0b', label:'竞争格局', weight:20 },
        valuation:   { icon:'📊', color:'#8b5cf6', label:'估值合理性', weight:15 },
        growth:      { icon:'🚀', color:'#06b6d4', label:'成长动能', weight:20 },
    },
    shortLabels: { financial:'财务', technology:'技术', competition:'竞争', valuation:'估值', growth:'成长' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'💰 正在审计 [1/5] 财务健康… 营收·利润率·ROE·现金流·杠杆率' },
        { t:600, text:'🔋 正在审计 [2/5] 技术护城河… 刀片电池·e平台·智驾·芯片·专利' },
        { t:900, text:'⚔️ 正在审计 [3/5] 竞争格局… 市占率·价格战·海外壁垒·品牌' },
        { t:1200, text:'📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA·股息' },
        { t:1500, text:'🚀 正在审计 [5/5] 成长动能… 销量增速·海外扩张·电池外供·智能化' },
        { t:1800, text:'✅ 五维穿透审计完成，正在生成报告…' },
    ],

    buildData() {
        const modules = {
            financial: { score:84, grade:'B', checks:[
                {name:'营收增长',score:92,status:'pass',detail:'2025E营收约8,850亿元(+18.5%)，连续5年高速增长',explanation:'比亚迪营收由汽车(约75%)、手机部件(约20%)及电池(约5%)三大板块驱动',threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%'},
                {name:'净利润',score:88,status:'pass',detail:'归母净利润约520亿元(+22.8%)，EPS约17.86元',explanation:'规模效应+出海溢价驱动利润率持续改善'},
                {name:'毛利率',score:80,status:'pass',detail:'综合毛利率约22.8%，汽车业务毛利率约25.5%',explanation:'垂直整合带来成本优势',threshold:'🟢 >20% | 🟡 15-20% | 🔴 <15%'},
                {name:'ROE',score:78,status:'pass',detail:'ROE约19.5%(2024: 18.6%)',explanation:'重资产扩张阶段ROE受压，趋势向好'},
                {name:'资产负债率',score:65,status:'warn',detail:'资产负债率约74.8%，有息负债超2,000亿元',explanation:'经营性负债占比超60%，实质风险可控',action:'关注有息负债/总负债比率变化趋势',threshold:'🟢 <65% | 🟡 65-80% | 🔴 >80%'},
                {name:'自由现金流',score:82,status:'pass',detail:'经营性现金流约850亿元，FCF约280亿元',explanation:'高CAPEX源于产能扩张，经营现金流充沛'},
            ]},
            technology: { score:91, grade:'A', checks:[
                {name:'电池技术',score:95,status:'pass',detail:'刀片电池全球领先，磷酸铁锂电池能量密度达180Wh/kg',explanation:'刀片电池通过针刺测试已成为行业标杆'},
                {name:'电驱平台',score:92,status:'pass',detail:'e平台3.0覆盖全系车型，CTB一体化技术全球首创',explanation:'电池车身一体化使车身刚度提升70%'},
                {name:'智能驾驶',score:68,status:'warn',detail:'天神之眼高阶智驾系统搭载率约40%',explanation:'城市NOA已覆盖300+城市',action:'跟踪比亚迪智驾团队规模扩张'},
                {name:'半导体芯片',score:88,status:'pass',detail:'自研SiC MOSFET芯片，车规级IGBT市占率国内第一',explanation:'自研芯片实现电驱效率提升8%+'},
                {name:'研发投入',score:90,status:'pass',detail:'2025E研发费用约520亿元(营收占比约5.9%)',explanation:'研发投入规模全球车企第一梯队',threshold:'🟢 >5% | 🟡 3-5% | 🔴 <3%'},
                {name:'专利壁垒',score:85,status:'pass',detail:'累计专利申请超48,000件',explanation:'核心技术专利构成强大技术壁垒'},
            ]},
            competition: { score:72, grade:'B', checks:[
                {name:'国内市占率',score:88,status:'pass',detail:'2025年国内新能源乘用车市占率约36.2%',explanation:'市占率超过后三名之和'},
                {name:'全球排名',score:85,status:'pass',detail:'2025全球新能源汽车销量第一(约462万辆)',explanation:'大幅超过特斯拉(约180万辆)'},
                {name:'价格战风险',score:50,status:'warn',detail:'5-30万价格带竞争全面白热化',explanation:'成本优势可承受价格战，但毛利率承压',action:'监控走量车型终端成交价变化'},
                {name:'海外竞争壁垒',score:60,status:'warn',detail:'欧盟关税17.0%，美国市场基本关闭',explanation:'加速海外建厂',action:'跟踪匈牙利工厂投产进度'},
                {name:'品牌向上突破',score:72,status:'pass',detail:'腾势/仰望/方程豹三大高端品牌矩阵',explanation:'高端品牌ASP提升显著但销量占比仍低'},
            ]},
            valuation: { score:62, grade:'C', checks:[
                {name:'PE估值',score:65,status:'warn',detail:'PE(TTM) ~18.5X(forward ~17X)',explanation:'处于传统车企与科技公司估值之间',threshold:'🟢 <20X | 🟡 20-30X | 🔴 >30X'},
                {name:'PB估值',score:58,status:'warn',detail:'PB ~3.8X',explanation:'回归合理区间',threshold:'🟢 <3.0X | 🟡 3.0-6.0X | 🔴 >6.0X'},
                {name:'EV/EBITDA',score:70,status:'pass',detail:'EV/EBITDA ~11.0X',explanation:'估值回调至合理区间'},
                {name:'DCF内在价值',score:78,status:'pass',detail:'乐观/中性/悲观估值：440/380/290 元(当前¥340)',explanation:'当前低估约12%'},
                {name:'股息率',score:60,status:'warn',detail:'股息率约1.0%，分红率约18%',explanation:'大量资本用于产能扩张',threshold:'🟢 >2% | 🟡 1-2% | 🔴 <1%'},
            ]},
            growth: { score:90, grade:'A', checks:[
                {name:'销量增速',score:90,status:'pass',detail:'2025年新能源汽车销量约462万辆(+41.3%)',explanation:'产品矩阵覆盖6-100万元全价格带'},
                {name:'海外扩张',score:88,status:'pass',detail:'2026海外销量指引上调至150万辆',explanation:'东南亚、拉美、欧洲三大市场同步发力'},
                {name:'电池外供',score:78,status:'pass',detail:'弗迪电池外供比例持续提升至约35%',explanation:'2025E营收约400亿元'},
                {name:'智能化升级',score:78,status:'pass',detail:'高阶智驾+智能座舱搭载率快速提升至55%',explanation:'智能化溢价提升+高端车型占比增加'},
                {name:'全球建厂',score:85,status:'pass',detail:'五大海外工厂同步推进',explanation:'本地化生产规避关税壁垒',action:'关注匈牙利工厂2026投产节点'},
                {name:'新业务探索',score:75,status:'pass',detail:'大模型赋能智能座舱+云辇智能底盘',explanation:'技术外溢形成多个百亿级业务增量'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'比亚迪',ticker_a:'002594.SZ',ticker_h:'1211.HK',
            market_cap:'9,880亿',price:'340.00',pe:'18.5',pb:'3.80',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules, audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'价格战持续白热化',level:'critical',desc:'国内新能源车市场价格战从10-20万蔓延至全价格带',probability:'高',impact:'重大',mitigation:'垂直整合成本优势+规模效应'},
                {name:'海外关税壁垒升级',level:'critical',desc:'欧盟加征17.0%反补贴关税，美国关税100%封锁',probability:'高',impact:'重大',mitigation:'海外建厂本地化+技术授权合作'},
                {name:'智能驾驶技术差距',level:'high',desc:'高阶智驾能力落后于华为/小鹏约1-2代',probability:'中等',impact:'中等',mitigation:'加大智驾研发投入'},
                {name:'产能过剩风险',level:'high',desc:'2026年行业总产能可能超需求30%以上',probability:'中等',impact:'重大',mitigation:'灵活调整产能+出口消化'},
                {name:'原材料价格波动',level:'medium',desc:'碳酸锂价格仍有波动性',probability:'低',impact:'中等',mitigation:'长期锁价协议+锂矿自有资源'},
                {name:'技术路线不确定性',level:'medium',desc:'固态电池等新技术可能颠覆格局',probability:'低',impact:'轻微',mitigation:'多技术路线并行布局'},
            ],
            verdict:{
                bull:['全球新能源车销量冠军(462万辆)','垂直整合构成全球最强成本护城河','海外销量指引上调至150万辆','forward PE ~17X已进入合理偏低区间'],
                bear:['国内价格战升级至全价格带','欧美关税壁垒升级','智能驾驶技术落后约1-2代','2025销量增速难以持续'],
                catalysts:['匈牙利工厂2026投产','高端品牌月销突破1万辆','弗迪电池外供大客户放量','第二代刀片电池量产'],
                positioning:'✅ 核心龙头标的。当前PE 18.5X已进入合理偏低区间，建议仓位10-15%。',
                rating:'buy',rating_text:'📈 积极配置 / 回调即加仓',
                summary:'比亚迪是全球新能源汽车龙头，2025年交付约462万辆NEV(+41.3%)。垂直整合构建了全球最深的成本护城河。当前PE 18.5X已回调至合理偏低区间，DCF显示低估约12%。建议采取"核心长仓+积极加仓"策略。'
            },
            financials:{
                years:['2019','2020','2021','2022','2023','2024','2025E'],
                revenue:[1277,1566,2161,4241,6023,7467,8850],
                net_income:[16.1,42.3,30.5,166.2,300.4,402.0,520.0],
                gross_margin:[16.3,19.4,17.4,20.4,20.2,21.9,22.8],
                roe:[6.2,12.8,7.6,23.1,21.5,18.6,19.5],
                ev_sales:[42.7,18.9,59.4,186.4,302.4,427.2,550.0],
                phev_sales:[19.5,11.8,27.3,94.6,143.9,248.5,310.0],
                bev_sales:[23.2,7.1,32.1,91.8,158.5,178.7,240.0],
                revenue_split:{'汽车业务':75,'手机部件及组装':20,'电池及储能':5}
            }
        };
    },

    buildKPIs(d) {
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail',indicator:d.trust_score>=70?'● 可投':d.trust_score>=55?'◐ 谨慎':'✖ 高危'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:`营收+18.5% · ROE ${d.financials.roe[6]}%`,level:d.modules.financial.score>=70?'pass':'warn'},
            {label:'技术护城河',icon:'🔋',value:d.modules.technology.score,suffix:'',sub:'刀片电池+e平台全球领先',level:'pass',indicator:'🥇 顶级'},
            {label:'竞争格局',icon:'⚔️',value:d.modules.competition.score,suffix:'',sub:'全球EV销量冠军·价格战承压',level:d.modules.competition.score>=70?'pass':'warn',indicator:d.modules.competition.score>=70?'● 领先':'⚠ 承压'},
            {label:'估值合理性',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:d.modules.valuation.score>=70?'pass':'warn',indicator:'◐ 合理偏高'},
            {label:'成长动能',icon:'🚀',value:d.modules.growth.score,suffix:'',sub:'销量CAGR +28% · 海外+60%',level:'pass',indicator:'● 强劲'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(16,185,129,0.2)');
        // 1. Revenue & Net Income
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#34d399'},{offset:1,color:'#10b981'}]},borderRadius:[4,4,0,0]}},
                {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.12)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        // 2. Margins
        core.initChart('chart-margins')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,max:30},
            series:[
                {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,lineStyle:{color:'#10b981',width:2.5},itemStyle:{color:'#34d399'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(16,185,129,0.15)'},{offset:1,color:'transparent'}]}},
                    markLine:{silent:true,data:[{yAxis:18,label:{show:true,formatter:'行业均值 18%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
                {name:'ROE',type:'line',data:f.roe,smooth:true,lineStyle:{color:'#8b5cf6',width:2,type:'dashed'},itemStyle:{color:'#a78bfa'},symbol:'circle',symbolSize:6}
            ]
        });
        // 3. EV Sales
        core.initChart('chart-sales')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'万辆',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'纯电(BEV)',type:'bar',data:f.bev_sales,barWidth:'30%',stack:'sales',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#06b6d4'},{offset:1,color:'#0891b2'}]}}},
                {name:'插混(PHEV)',type:'bar',data:f.phev_sales,barWidth:'30%',stack:'sales',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#34d399'},{offset:1,color:'#10b981'}]},borderRadius:[4,4,0,0]}},
                {name:'总销量',type:'line',data:f.ev_sales,smooth:true,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7}
            ]
        });
        // 4. Revenue Split
        const rs=f.revenue_split;
        core.initChart('chart-segments')?.setOption({
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(16,185,129,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(rs).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#10b981','#3b82f6','#f59e0b']}]
        });
    }
});
