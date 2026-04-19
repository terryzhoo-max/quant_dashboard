/**
 * AlphaCore · 东方财富 审计数据文件 (Phase 3A)
 */
AuditCore.init({
    companyName: '东方财富',
    themeColor: '#2563eb',
    themeColorRgba: 'rgba(37,99,235,',
    localStorageKey: 'alphacore_em_audit_history_v3',
    kpiDashboardId: 'audit-kpi-dashboard',
    chartsGridId: 'audit-charts-grid',
    MODULES: {
        financial:   { icon:'💰', color:'#10b981', label:'财务健康', weight:25 },
        platform:    { icon:'🌐', color:'#2563eb', label:'平台生态', weight:20 },
        competition: { icon:'⚔️', color:'#f59e0b', label:'竞争格局', weight:20 },
        valuation:   { icon:'📊', color:'#8b5cf6', label:'估值合理性', weight:15 },
        growth:      { icon:'🚀', color:'#06b6d4', label:'成长动能', weight:20 },
    },
    shortLabels: { financial:'财务', platform:'平台', competition:'竞争', valuation:'估值', growth:'成长' },
    SECTIONS: ['audit-identity','trust-hero','audit-kpi-dashboard','audit-overview','audit-charts-grid','audit-risk-matrix','audit-verdict','audit-timeline'],
    loadingSteps: [
        { t:300, text:'💰 正在审计 [1/5] 财务健康… 营收·净利润·毛利率·ROE·手续费收入' },
        { t:600, text:'🌐 正在审计 [2/5] 平台生态… 天天基金·APP矩阵·股吧·Choice·AI赋能' },
        { t:900, text:'⚔️ 正在审计 [3/5] 竞争格局… 经纪市占率·基金代销·佣金率·牌照·同花顺' },
        { t:1200, text:'📊 正在审计 [4/5] 估值合理性… PE·PB·DCF·EV/EBITDA·股息率' },
        { t:1500, text:'🚀 正在审计 [5/5] 成长动能… 基金代销恢复·两融弹性·财富管理·海外' },
        { t:1800, text:'✅ 五维穿透审计完成，正在生成报告…' },
    ],

    buildData() {
        const modules = {
            financial: { score:82, grade:'B', checks:[
                {name:'营收增长',score:85,status:'pass',detail:'2025年营收约185亿元(+22.5%)，基金代销+经纪+两融三引擎共振',explanation:'受益于A股日均成交额突破1.5万亿元',threshold:'🟢 >15% | 🟡 5-15% | 🔴 <5%'},
                {name:'净利润',score:88,status:'pass',detail:'归母净利润约105亿元(+28.0%)，EPS约0.66元',explanation:'牛市催化下利润弹性极强'},
                {name:'毛利率',score:90,status:'pass',detail:'综合毛利率约72%，互联网金融平台属性',explanation:'轻资产互联网模式毛利率远超传统券商(35-45%)',threshold:'🟢 >60% | 🟡 40-60% | 🔴 <40%'},
                {name:'ROE',score:78,status:'pass',detail:'ROE约14.8%(2024: 12.5%)，市场回暖推动',explanation:'互联网券商ROE与市场活跃度高度相关',threshold:'🟢 >15% | 🟡 10-15% | 🔴 <10%'},
                {name:'资产负债率',score:72,status:'pass',detail:'资产负债率约62%，有息负债约480亿元',explanation:'券商行业负债率天然偏高，东方财富杠杆低于行业均值68%'},
                {name:'手续费收入',score:80,status:'pass',detail:'手续费及佣金净收入约95亿元(+25%)',explanation:'佣金率下行趋势下，以量补价'},
            ]},
            platform: { score:88, grade:'A', checks:[
                {name:'天天基金代销规模',score:92,status:'pass',detail:'天天基金非货基保有量约8,500亿元，独立平台第一',explanation:'中国最大独立基金销售平台'},
                {name:'东方财富APP矩阵',score:90,status:'pass',detail:'APP月活约5,200万，Choice金融终端覆盖超80%专业投资者',explanation:'行情+代销+数据+社区全矩阵'},
                {name:'股吧社区生态',score:82,status:'pass',detail:'注册用户超3亿，日均发帖约120万条',explanation:'内容生态形成用户黏性飞轮'},
                {name:'数据终端壁垒',score:85,status:'pass',detail:'Choice金融终端付费用户约18万',explanation:'对标Wind/Bloomberg的国产金融数据终端'},
                {name:'用户增长趋势',score:78,status:'pass',detail:'2025年新增开户约280万户，累计约2,800万户',explanation:'互联网获客成本约200元/户，远低于传统券商'},
                {name:'AI赋能进展',score:72,status:'pass',detail:'AI智投助手上线，覆盖60%用户',explanation:'AI赋能提升用户体验，尚处早期'},
            ]},
            competition: { score:75, grade:'B', checks:[
                {name:'经纪市占率',score:78,status:'pass',detail:'A股经纪业务市占率约4.2%，互联网券商第一',explanation:'以互联网模式差异化竞争'},
                {name:'基金代销竞争',score:72,status:'pass',detail:'非货基代销市占率4.8%，面临蚂蚁(15%)、招行(8%)竞争',explanation:'费率战持续',action:'关注基金销售费率改革'},
                {name:'佣金率下行压力',score:55,status:'warn',detail:'行业平均佣金率已降至万1.5，仍有下行空间',explanation:'零佣金趋势不可逆',action:'监控佣金率变化趋势'},
                {name:'牌照优势',score:85,status:'pass',detail:'持有证券、基金销售、期货、保险代销全牌照',explanation:'全牌照优势实现一站式金融服务'},
                {name:'同花顺竞争',score:68,status:'warn',detail:'同花顺MAU约6,800万，AI能力更强',explanation:'赛道略有差异：工具vs交易',action:'跟踪AI产品迭代速度'},
            ]},
            valuation: { score:60, grade:'C', checks:[
                {name:'PE估值',score:52,status:'warn',detail:'PE(TTM) ~32X，高于传统券商(12-18X)',explanation:'互联网金融享有科技属性溢价',threshold:'🟢 <25X | 🟡 25-40X | 🔴 >40X'},
                {name:'PB估值',score:55,status:'warn',detail:'PB ~3.2X，高于传统券商PB中位数1.2X',explanation:'轻资产模式PB天然偏高',threshold:'🟢 <2.5X | 🟡 2.5-4.0X | 🔴 >4.0X'},
                {name:'EV/EBITDA',score:62,status:'warn',detail:'EV/EBITDA ~22X，高于券商行业中位数10X',explanation:'高EV/EBITDA反映平台化溢价'},
                {name:'DCF内在价值',score:68,status:'pass',detail:'乐观/中性/悲观估值：28/22/16 元(当前¥21.5)',explanation:'中性估值与当前接近，安全边际约2%'},
                {name:'股息率',score:62,status:'warn',detail:'股息率约1.2%，分红率约28%',explanation:'互联网公司偏低分红属正常',threshold:'🟢 >2% | 🟡 1-2% | 🔴 <1%'},
            ]},
            growth: { score:80, grade:'B', checks:[
                {name:'基金代销恢复',score:82,status:'pass',detail:'天天基金非货基保有量+18%，结构性牛市催化',explanation:'基金行业从寒冬复苏'},
                {name:'两融业务弹性',score:85,status:'pass',detail:'两融余额约280亿元(+35%)，利差约4.5%',explanation:'市场活跃时两融弹性极大'},
                {name:'财富管理转型',score:75,status:'pass',detail:'投顾签约资产约450亿元',explanation:'买方投顾试点推进'},
                {name:'机构业务拓展',score:68,status:'warn',detail:'机构客户覆盖率约35%',explanation:'面临Wind的强力竞争',action:'跟踪Choice终端渗透进度'},
                {name:'市场周期依赖',score:55,status:'warn',detail:'营收与A股成交量相关系数0.85+',explanation:'本质是A股牛熊市Beta放大器',action:'关注日均成交额是否跌破1万亿'},
                {name:'海外业务布局',score:60,status:'warn',detail:'港股通交易市占率约1.5%',explanation:'海外业务起步阶段'},
            ]}
        };
        let wS=0,tW=0;
        for(const[k,mod] of Object.entries(modules)){const w=this.MODULES[k].weight;wS+=mod.score*w;tW+=w;}
        const ts=Math.round(wS/tW), tg=ts>=85?'A':ts>=70?'B':ts>=55?'C':'D';
        let pass=0,warn=0,fail=0,total=0;
        for(const mod of Object.values(modules)){for(const c of mod.checks){total++;if(c.status==='pass')pass++;else if(c.status==='warn')warn++;else fail++;}}
        return {
            company:'东方财富',ticker:'300059.SZ',
            market_cap:'2,918亿',price:'18.48',pe:'28.0',pb:'2.76',
            trust_score:ts,trust_grade:tg,pass_count:pass,warn_count:warn,fail_count:fail,total_checks:total,
            modules,audit_time:new Date().toLocaleString('zh-CN',{hour12:false}),
            risks:[
                {name:'市场周期性风险',level:'critical',desc:'营收/利润与A股成交量高度正相关',probability:'中等',impact:'致命',mitigation:'多元化收入+财富管理转型'},
                {name:'佣金率持续下行',level:'high',desc:'行业佣金率已降至万1.5且仍有下行趋势',probability:'高',impact:'重大',mitigation:'增值服务变现+两融利差'},
                {name:'基金代销费率改革',level:'high',desc:'监管推动基金销售费率市场化改革',probability:'高',impact:'中等',mitigation:'以规模换利润+买方投顾转型'},
                {name:'同花顺AI竞争',level:'medium',desc:'同花顺AI金融领域投入更大',probability:'中等',impact:'中等',mitigation:'加大AI研发+利用交易闭环优势'},
                {name:'监管政策风险',level:'medium',desc:'证监会对互联网金融监管趋严',probability:'低',impact:'中等',mitigation:'全牌照合规优势'},
                {name:'估值压缩风险',level:'medium',desc:'PE 32X处于合理上沿',probability:'中等',impact:'中等',mitigation:'严格止损纪律+仓位控制'},
            ],
            verdict:{
                bull:['A股最大互联网券商，全牌照+平台生态','天天基金非货基保有量8,500亿元，独立第一','毛利率72%远超传统券商','2025年营收+22.5%/净利润+28%'],
                bear:['与A股成交量相关系数0.85+，Beta属性极强','佣金率下行趋势不可逆','PE 32X处于合理偏高区间','同花顺AI能力更强'],
                catalysts:['A股日均成交突破2万亿','买方投顾试点全面推广','天天基金非货基保有量突破1万亿','AI智投大规模落地'],
                positioning:'✅ 牛市弹性标的。建议仓位5-8%。',
                rating:'buy',rating_text:'📈 趋势跟踪 / 牛市加仓',
                summary:'东方财富是A股唯一的互联网金融全生态平台。2025年受益于牛市回暖，营收185亿元(+22.5%)，净利润105亿元(+28%)。毛利率72%的轻资产模式使其盈利弹性远超传统券商。主要风险为高度周期性及佣金率持续下行。当前PE 32X合理偏高。'
            },
            financials:{
                years:['2019','2020','2021','2022','2023','2024','2025E'],
                revenue:[50.4,82.4,131.0,112.0,146.5,151.0,185.0],
                net_income:[18.5,48.0,85.5,51.6,81.0,82.0,105.0],
                gross_margin:[65.2,68.5,72.8,70.1,71.5,71.8,72.0],
                roe:[8.2,16.5,22.8,10.5,14.2,12.5,14.8],
                fund_aum:[2800,4200,7500,5200,6500,7200,8500],
                margin_balance:[85,120,180,110,160,210,280],
                biz_split:{'经纪业务':35,'基金代销':28,'利息净收入':22,'数据服务':8,'其他':7}
            }
        };
    },

    buildKPIs(d) {
        return [
            {label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':'warn',indicator:d.trust_score>=70?'● 可投':'◐ 谨慎'},
            {label:'财务健康',icon:'💰',value:d.modules.financial.score,suffix:'',sub:'营收+22.5% · 毛利率72%',level:'pass'},
            {label:'平台生态',icon:'🌐',value:d.modules.platform.score,suffix:'',sub:'天天基金+股吧+Choice全生态',level:'pass',indicator:'🥇 顶级'},
            {label:'竞争格局',icon:'⚔️',value:d.modules.competition.score,suffix:'',sub:'互联网券商第一·佣金率承压',level:'pass',indicator:'● 领先'},
            {label:'估值合理性',icon:'📊',value:d.modules.valuation.score,suffix:'',sub:`PE ${d.pe}X · PB ${d.pb}X`,level:'warn',indicator:'◐ 合理偏高'},
            {label:'成长动能',icon:'🚀',value:d.modules.growth.score,suffix:'',sub:'基金代销恢复·两融弹性',level:'pass',indicator:'● 强劲'},
        ];
    },

    renderCharts(d, core) {
        const f=d.financials, S=core.CHART_STYLES, tt=core.tooltip('rgba(37,99,235,0.2)');
        core.initChart('chart-revenue')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'亿元',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},
            series:[
                {name:'营收',type:'bar',data:f.revenue,barWidth:'38%',itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#60a5fa'},{offset:1,color:'#2563eb'}]},borderRadius:[4,4,0,0]}},
                {name:'净利润',type:'line',data:f.net_income,smooth:true,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.12)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        core.initChart('chart-margins')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis}, yAxis:{type:'value',name:'%',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,max:80},
            series:[
                {name:'毛利率',type:'line',data:f.gross_margin,smooth:true,lineStyle:{color:'#2563eb',width:2.5},itemStyle:{color:'#60a5fa'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(37,99,235,0.15)'},{offset:1,color:'transparent'}]}},
                    markLine:{silent:true,data:[{yAxis:45,label:{show:true,formatter:'券商均值 45%',color:'#4ade80',fontSize:9,position:'insideEndTop'},lineStyle:{color:'rgba(74,222,128,0.3)',type:'dashed',width:1}}]}},
                {name:'ROE',type:'line',data:f.roe,smooth:true,lineStyle:{color:'#8b5cf6',width:2,type:'dashed'},itemStyle:{color:'#a78bfa'},symbol:'circle',symbolSize:6}
            ]
        });
        core.initChart('chart-platform')?.setOption({
            grid:S.grid, tooltip:tt, legend:S.legend,
            xAxis:{type:'category',data:f.years,...S.axis},
            yAxis:[{type:'value',name:'亿元(基金)',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis},{type:'value',name:'亿元(两融)',nameTextStyle:{color:'#64748b',fontSize:10},...S.axis,splitLine:{show:false}}],
            series:[
                {name:'基金保有量',type:'bar',data:f.fund_aum,barWidth:'30%',yAxisIndex:0,itemStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#60a5fa'},{offset:1,color:'#2563eb'}]},borderRadius:[4,4,0,0]}},
                {name:'两融余额',type:'line',data:f.margin_balance,smooth:true,yAxisIndex:1,lineStyle:{color:'#f59e0b',width:2.5},itemStyle:{color:'#fbbf24'},symbol:'circle',symbolSize:7,
                    areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(245,158,11,0.1)'},{offset:1,color:'transparent'}]}}}
            ]
        });
        const rs=f.biz_split;
        core.initChart('chart-segments')?.setOption({
            tooltip:{trigger:'item',formatter:'{b}: {c}%',backgroundColor:'rgba(15,23,42,0.92)',borderColor:'rgba(37,99,235,0.2)',textStyle:{color:'#e2e8f0',fontSize:12}},
            legend:{bottom:4,textStyle:{color:'#94a3b8',fontSize:9},itemWidth:10,itemHeight:8},
            series:[{type:'pie',radius:['38%','68%'],center:['50%','46%'],data:Object.entries(rs).map(([k,v])=>({name:k,value:v})),label:{show:false},
                emphasis:{label:{show:true,color:'#e2e8f0',fontSize:11,fontWeight:700}},
                itemStyle:{borderColor:'rgba(15,23,42,0.9)',borderWidth:3},color:['#2563eb','#f59e0b','#10b981','#8b5cf6','#475569']}]
        });
    }
});
