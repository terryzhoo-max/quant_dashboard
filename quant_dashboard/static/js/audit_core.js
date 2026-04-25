/**
 * AlphaCore · 审计渲染引擎 V3.0 (Phase 3A)
 * 从 7 个审计 JS 中提取的共享渲染逻辑
 * 每个股票页面只需提供 config + buildData + renderCharts
 */
const AuditCore = {
    cfg: null, _data: null, _activeModule: null,
    GRADE_COLORS: { A:'#34d399', B:'#60a5fa', C:'#fbbf24', D:'#f87171' },
    CHART_STYLES: {
        grid: { top:40, bottom:28, left:55, right:20 },
        axis: { axisLabel:{fontSize:11,color:'#64748b',fontFamily:'Outfit'}, axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}, splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)',type:'dashed'}} },
        legend: { top:6, right:10, textStyle:{color:'#94a3b8',fontSize:10}, itemWidth:12, itemHeight:8 },
    },
    tooltip(borderColor) {
        return { trigger:'axis', backgroundColor:'rgba(15,23,42,0.92)', borderColor:borderColor||'rgba(16,185,129,0.2)', textStyle:{color:'#e2e8f0',fontSize:12,fontFamily:'Inter'}, padding:[10,14] };
    },

    // ── Init ──
    init(config) {
        this.cfg = config;
        document.addEventListener('DOMContentLoaded', () => this.runAudit());
    },

    counterUp(el, target, suffix, dur) {
        if(!el) return;
        const t0 = performance.now(), isInt = Number.isInteger(target);
        (function tick(now) {
            const p = Math.min((now-t0)/(dur||1200), 1), ease = 1-Math.pow(1-p,3);
            el.textContent = (isInt ? Math.round(target*ease) : (target*ease).toFixed(1)) + (suffix||'');
            if(p<1) requestAnimationFrame(tick);
        })(t0);
    },

    // ── Audit Runner ──
    runAudit() {
        const c = this.cfg;
        const btn = document.getElementById('audit-refresh-btn');
        const spinner = document.getElementById('audit-spinner');
        if(btn) btn.disabled = true;
        if(spinner) spinner.style.display = 'inline-block';
        document.getElementById('audit-loading').style.display = 'block';
        c.SECTIONS.forEach(id => { const el = document.getElementById(id); if(el){el.style.display='none';el.style.opacity='0';} });
        const ls = document.querySelector('.loading-status');
        if(c.loadingSteps) c.loadingSteps.forEach(s => { setTimeout(() => { if(ls) ls.textContent = s.text; }, s.t); });
        setTimeout(() => {
            this._data = c.buildData();
            this.renderAll(this._data);
            if(btn) btn.disabled = false;
            if(spinner) spinner.style.display = 'none';
        }, 2200);
    },

    // ── Render All ──
    renderAll(d) {
        const c = this.cfg;
        document.getElementById('audit-loading').style.display = 'none';
        const displayMap = { 'trust-hero':'grid', 'audit-overview':'grid' };
        displayMap[c.chartsGridId||'audit-charts-grid'] = 'grid';
        displayMap[c.kpiDashboardId||'audit-kpi-dashboard'] = 'grid';
        c.SECTIONS.forEach(id => { const el = document.getElementById(id); if(el) el.style.display = displayMap[id]||'block'; });

        this.renderIdentity(d);
        this.renderTrustHero(d);
        this.renderKPIDashboard(d);
        this.renderAlertBanner(d);
        this.renderRadar(d);
        this.renderModuleCards(d);
        if(c.renderCharts) c.renderCharts(d, this);
        this.renderRiskMatrix(d);
        this.renderVerdict(d);
        this.renderTimeline(d);

        document.getElementById('audit-time').textContent = d.audit_time;
        document.getElementById('footer-time').textContent = `· 审计于 ${d.audit_time}`;
        c.SECTIONS.forEach((id, i) => {
            const el = document.getElementById(id); if(!el) return;
            el.style.transform = 'translateY(12px)';
            setTimeout(() => { el.style.transition='opacity 0.5s ease, transform 0.5s cubic-bezier(0.22,1,0.36,1)'; el.style.opacity='1'; el.style.transform='translateY(0)'; }, 80*i);
        });
        const layout = document.getElementById('audit-layout');
        layout.classList.remove('scan-complete'); void layout.offsetWidth; layout.classList.add('scan-complete');
    },

    // ── 1. Identity ──
    renderIdentity(d) {
        document.getElementById('qs-mcap').textContent = d.market_cap;
        const priceEl = document.getElementById('qs-price');
        if(priceEl) priceEl.textContent = '¥'+d.price;
        const peEl = document.getElementById('qs-pe');
        if(peEl) { peEl.textContent = d.pe+'X'; const v=parseFloat(d.pe); peEl.style.color = v>30?'#f87171':v>20?'#fbbf24':'#34d399'; }
        const pbEl = document.getElementById('qs-pb');
        if(pbEl) pbEl.textContent = d.pb+'X';
    },

    // ── 2. Trust Hero ──
    renderTrustHero(d) {
        const c = this.cfg, gc = this.GRADE_COLORS[d.trust_grade]||'#94a3b8';
        const big = document.getElementById('trust-big-score');
        big.style.color = gc; this.counterUp(big, d.trust_score, '', 1400);
        const badge = document.getElementById('trust-grade-badge');
        badge.textContent = d.trust_grade; badge.className = `trust-grade-badge grade-${d.trust_grade}`;
        const verdicts = { A:'投资价值突出，各维度均衡优秀', B:'整体可投，存在结构性风险需关注', C:'风险与机会并存，需精选入场时机', D:'⚠️ 高风险标的，不建议重仓' };
        document.getElementById('trust-verdict').textContent = verdicts[d.trust_grade]||'';
        document.getElementById('stat-pass').textContent = `✅ ${d.pass_count} 优势`;
        document.getElementById('stat-warn').textContent = `⚠️ ${d.warn_count} 关注`;
        document.getElementById('stat-fail').textContent = `❌ ${d.fail_count} 风险`;
        document.getElementById('trust-meta').textContent = `共 ${d.total_checks} 项检查 · 加权评分 ${d.trust_score}/100 · ${d.audit_time}`;
        const keys = Object.keys(c.MODULES), sl = c.shortLabels||{};
        document.getElementById('trust-equalizer').innerHTML = keys.map((k,i) => {
            const s=d.modules[k].score, col=s>=85?'#10b981':s>=70?'#3b82f6':s>=55?'#f59e0b':'#ef4444', h=Math.max(s*1.4,8);
            return `<div class="eq-bar-group" title="${c.MODULES[k].label}: ${s}/100"><span class="eq-score" style="color:${col}">${s}</span><div class="eq-track"><div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${col};animation-delay:${0.1+i*0.12}s"></div></div><span class="eq-label">${sl[k]||k}</span></div>`;
        }).join('');
        const chart = (typeof AC!=='undefined') ? AC.registerChart(echarts.init(document.getElementById('trust-gauge-chart'))) : echarts.init(document.getElementById('trust-gauge-chart'));
        chart.setOption({ series:[{ type:'gauge', startAngle:210, endAngle:-30, radius:'88%', center:['50%','55%'], min:0, max:100, splitNumber:4,
            axisLine:{lineStyle:{width:18,color:[[0.55,'#ef4444'],[0.70,'#f59e0b'],[0.85,'#3b82f6'],[1,'#10b981']]}},
            pointer:{length:'55%',width:4,itemStyle:{color:gc}}, axisTick:{show:false},
            splitLine:{length:10,lineStyle:{color:'rgba(255,255,255,0.15)',width:1}},
            axisLabel:{distance:18,color:'#64748b',fontSize:10,fontFamily:'Outfit'},
            detail:{show:false}, title:{show:true,offsetCenter:[0,'35%'],fontSize:11,color:'#94a3b8'},
            data:[{value:d.trust_score,name:'投资可行性'}] }] });
    },

    // ── 3. Alert Banner ──
    renderAlertBanner(d) {
        const banner = document.getElementById('alert-banner');
        if(d.fail_count>0) {
            const items=[]; for(const mod of Object.values(d.modules)) for(const ck of mod.checks) if(ck.status==='fail') items.push(ck.name);
            banner.className='alert-banner level-fail visible';
            document.getElementById('alert-icon').textContent='🚨';
            document.getElementById('alert-text').innerHTML=`<strong>${d.fail_count} 项高风险</strong> — ${items.slice(0,3).join('、')}${items.length>3?` 等${items.length}项`:''} 需重点关注`;
        } else if(d.warn_count>0) {
            banner.className='alert-banner level-warn visible';
            document.getElementById('alert-icon').textContent='⚠️';
            document.getElementById('alert-text').innerHTML=`<strong>${d.warn_count} 项需要关注</strong>`;
        } else { banner.classList.remove('visible'); }
    },

    // ── 4. Radar ──
    renderRadar(d) {
        const c=this.cfg, keys=Object.keys(c.MODULES), tc=c.themeColor||'#10b981', tcR=c.themeColorRgba||'rgba(16,185,129,';
        const chart = (typeof AC!=='undefined') ? AC.registerChart(echarts.init(document.getElementById('radar-chart'))) : echarts.init(document.getElementById('radar-chart'));
        chart.setOption({
            radar:{indicator:keys.map(k=>({name:c.MODULES[k].label,max:100})),shape:'polygon',radius:'72%',
                axisName:{color:'#94a3b8',fontSize:11,fontWeight:600},
                splitLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}},splitArea:{areaStyle:{color:[tcR+'0.02)',tcR+'0.04)']}},
                axisLine:{lineStyle:{color:'rgba(255,255,255,0.08)'}}},
            series:[{type:'radar',data:[{value:keys.map(k=>d.modules[k].score),name:c.companyName+'审计',
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:tcR+'0.35)'},{offset:1,color:tcR+'0.08)'}]}},
                lineStyle:{color:tc,width:2},itemStyle:{color:tc},symbol:'circle',symbolSize:7}]}]
        });
        document.getElementById('radar-legend').innerHTML = keys.map(k => {
            const m=c.MODULES[k], s=d.modules[k].score;
            return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
        }).join('');
    },

    // ── 5. Module Cards ──
    renderModuleCards(d) {
        this._data = d; const c = this.cfg, GC = this.GRADE_COLORS;
        document.getElementById('module-cards').innerHTML = Object.entries(c.MODULES).map(([key,meta]) => {
            const mod=d.modules[key]; if(!mod) return '';
            const {score,grade,checks}=mod, gc=GC[grade]||'#94a3b8', r=18, circ=2*Math.PI*r, dash=circ*(score/100);
            const pC=checks.filter(x=>x.status==='pass').length, wC=checks.filter(x=>x.status==='warn').length, fC=checks.filter(x=>x.status==='fail').length;
            const worst=[...checks].sort((a,b)=>(a.score??100)-(b.score??100))[0];
            const wI=worst?.status==='pass'?'✅':worst?.status==='warn'?'⚠️':'❌';
            const wC2=worst?.status==='pass'?'#34d399':worst?.status==='warn'?'#fbbf24':'#f87171';
            return `<div class="module-card" style="--mod-color:${meta.color}" onclick="AuditCore.toggleDetail('${key}')" id="card-${key}">
                <div class="mod-header"><span class="mod-label">${meta.icon} ${meta.label}</span>
                    <div class="mod-score-ring"><svg viewBox="0 0 42 42"><circle class="mod-ring-bg" cx="21" cy="21" r="${r}"/><circle class="mod-ring-fill" cx="21" cy="21" r="${r}" stroke="${gc}" stroke-dasharray="${circ}" stroke-dashoffset="${circ-dash}"/></svg>
                    <span class="mod-score-text">${score}</span><span class="mod-grade-pill grade-${grade}">${grade}</span></div></div>
                <div class="mod-checks-summary">${pC>0?`<span style="color:#34d399">✅${pC}</span> `:''}${wC>0?`<span style="color:#fbbf24">⚠️${wC}</span> `:''}${fC>0?`<span style="color:#f87171">❌${fC}</span> `:''}
                    <span class="weight-tag">权重 ${meta.weight}%</span></div>
                ${worst?`<div class="mod-worst-preview${worst.status!=='pass'?' has-issue':''}"><span style="color:${wC2}">${wI} ${worst.name}</span><span class="mod-worst-score" style="color:${wC2}">${worst.score??0}</span></div>`:''}
            </div>`;
        }).join('');
    },

    // ── 6. Detail Expand ──
    toggleDetail(key, noScroll) {
        const section=document.getElementById('detail-section'), c=this.cfg, d=this._data;
        document.querySelectorAll('.module-card').forEach(x=>x.classList.remove('expanded'));
        if(this._activeModule===key){section.classList.remove('visible');this._activeModule=null;return;}
        this._activeModule=key;
        const card=document.getElementById(`card-${key}`); if(card)card.classList.add('expanded');
        const meta=c.MODULES[key], mod=d.modules[key]; if(!mod)return;
        document.getElementById('detail-title').textContent=`${meta.icon} ${meta.label} · ${mod.score}/100 (${mod.grade}级)`;
        document.getElementById('detail-body').innerHTML = mod.checks.map((ck,idx) => {
            const icon=ck.status==='pass'?'✅':ck.status==='warn'?'⚠️':'❌', sc=ck.score??0;
            const barC=sc>=85?'#10b981':sc>=70?'#3b82f6':sc>=55?'#f59e0b':'#ef4444';
            const txtC=sc>=85?'#34d399':sc>=70?'#60a5fa':sc>=55?'#fbbf24':'#f87171';
            const rid=`rule-${key}-${idx}`, hasRule=ck.explanation||ck.threshold||ck.action;
            let thH='';
            if(ck.threshold){const segs=ck.threshold.split('|').map(s=>s.trim()).map(seg=>{let t='green';if(seg.includes('🟡'))t='yellow';if(seg.includes('🔴'))t='red';const text=seg.replace(/🟢|🟡|🔴/g,'').trim();const isAct=t===(ck.status==='pass'?'green':ck.status==='warn'?'yellow':'red');return `<div class="threshold-seg seg-${t}${isAct?' active':''}"><span class="seg-icon">${t==='green'?'🟢':t==='yellow'?'🟡':'🔴'}</span><span class="seg-text">${text}</span></div>`;}).join('');thH=`<div class="rule-threshold-bar"><span class="threshold-label">📊 阈值:</span><div class="threshold-segments">${segs}</div></div>`;}
            return `<div class="check-row status-${ck.status}"><span class="check-icon">${icon}</span>
                <div class="check-info"><div class="check-name">${ck.name}</div><div class="check-detail">${ck.detail||''}</div></div>
                <div class="check-score-bar"><div class="check-score-fill" style="width:${sc}%;background:${barC}"></div></div>
                <span class="check-score-val" style="color:${txtC}">${sc}</span>
                ${hasRule?`<button class="check-expand-btn" id="btn-${rid}" onclick="AuditCore.toggleRule(event,'${rid}')">▼</button>`:''}</div>
            ${hasRule?`<div class="check-rule-panel" id="${rid}">
                ${ck.explanation?`<div class="rule-explanation"><span class="rule-section-icon">📖</span> ${ck.explanation}</div>`:''}
                ${thH}
                ${ck.action?`<div class="rule-action"><span class="rule-action-label">🛠️ 建议:</span><span class="rule-action-text">${ck.action}</span></div>`:''}
            </div>`:''}`;
        }).join('');
        section.classList.add('visible');
        if(!noScroll) section.scrollIntoView({behavior:'smooth',block:'nearest'});
    },

    toggleRule(e, rid) {
        e.stopPropagation();
        const panel=document.getElementById(rid), btn=document.getElementById(`btn-${rid}`); if(!panel)return;
        const isOpen=panel.classList.contains('open');
        panel.parentElement?.querySelectorAll('.check-rule-panel.open').forEach(p=>{p.classList.remove('open');const b=document.getElementById(`btn-${p.id}`);if(b)b.classList.remove('open');});
        if(!isOpen){panel.classList.add('open');if(btn)btn.classList.add('open');}
    },
    closeDetail() { document.getElementById('detail-section').classList.remove('visible'); document.querySelectorAll('.module-card').forEach(x=>x.classList.remove('expanded')); this._activeModule=null; },
    scrollToFirstIssue() {
        if(!this._data) return;
        for(const key of Object.keys(this.cfg.MODULES)) { if(this._data.modules[key]?.checks?.some(ck=>ck.status==='fail'||ck.status==='warn')){this.toggleDetail(key);return;} }
    },

    // ── 7. Risk Matrix ──
    renderRiskMatrix(d) {
        const badge=document.getElementById('rm-badge'), critCount=d.risks.filter(r=>r.level==='critical').length;
        badge.textContent = critCount>0?`${critCount} 项致命风险`:'风险可控';
        badge.className = `audit-rm-badge ${critCount>0?'high':'medium'}`;
        document.getElementById('audit-rm-body').innerHTML = d.risks.map(r => {
            const cls=r.level==='critical'?'risk-critical':r.level==='high'?'risk-high':r.level==='medium'?'risk-medium':'risk-low';
            const icon=r.level==='critical'?'🔴':r.level==='high'?'🟠':r.level==='medium'?'🟡':'🟢';
            return `<div class="audit-risk-item ${cls}"><div class="audit-risk-name">${icon} ${r.name}</div><div class="audit-risk-desc">${r.desc}</div>
                <div class="audit-risk-tags"><span class="audit-risk-tag probability">概率: ${r.probability}</span><span class="audit-risk-tag impact">影响: ${r.impact}</span><span class="audit-risk-tag mitigation">对冲: ${r.mitigation}</span></div></div>`;
        }).join('');
    },

    // ── 8. Verdict ──
    renderVerdict(d) {
        const v = d.verdict;
        document.getElementById('audit-verdict-body').innerHTML = `
            <div class="audit-verdict-card bull"><div class="audit-verdict-card-title">📈 看多逻辑</div><ul class="audit-verdict-list">${v.bull.map(x=>`<li>${x}</li>`).join('')}</ul></div>
            <div class="audit-verdict-card bear"><div class="audit-verdict-card-title">📉 看空逻辑</div><ul class="audit-verdict-list">${v.bear.map(x=>`<li>${x}</li>`).join('')}</ul></div>
            <div class="audit-verdict-card catalyst"><div class="audit-verdict-card-title">⚡ 关键催化剂</div><ul class="audit-verdict-list">${v.catalysts.map(x=>`<li>${x}</li>`).join('')}</ul></div>
            <div class="audit-verdict-card position"><div class="audit-verdict-card-title">🎯 仓位建议</div><ul class="audit-verdict-list"><li>${v.positioning}</li></ul></div>
            <div class="audit-conclusion-box"><div class="audit-conclusion-title">🏛️ 投资研判总结</div><div class="audit-conclusion-text">${v.summary}</div><div class="audit-conclusion-rating ${v.rating}">${v.rating_text}</div></div>`;
    },

    // ── 9. Timeline ──
    renderTimeline(d) {
        const c=this.cfg, container=document.getElementById('audit-timeline'); if(!container)return;
        const hk=c.localStorageKey||'alphacore_audit_history_v3';
        let hist=[]; try{hist=JSON.parse(localStorage.getItem(hk)||'[]');}catch(e){}
        const last=hist.length>0?hist[hist.length-1].time:'';
        if(d.audit_time!==last) hist.push({score:d.trust_score,time:d.audit_time,grade:d.trust_grade});
        if(hist.length>20) hist=hist.slice(-20);
        localStorage.setItem(hk,JSON.stringify(hist));
        container.style.display='block';
        const trendEl=document.getElementById('timeline-trend');
        if(hist.length<2){trendEl.textContent='— 首次审计';trendEl.className='timeline-trend stable';}
        else{const prev=hist[hist.length-2].score,curr=hist[hist.length-1].score;
            if(curr>prev){trendEl.textContent=`↑ +${curr-prev}`;trendEl.className='timeline-trend up';}
            else if(curr<prev){trendEl.textContent=`↓ ${curr-prev}`;trendEl.className='timeline-trend down';}
            else{trendEl.textContent='→ 稳定';trendEl.className='timeline-trend stable';}}
        const tc=c.themeColor||'#10b981', tcR=c.themeColorRgba||'rgba(16,185,129,';
        const chart = (typeof AC!=='undefined') ? AC.registerChart(echarts.init(document.getElementById('timeline-chart'))) : echarts.init(document.getElementById('timeline-chart'));
        chart.setOption({
            grid:{top:8,bottom:24,left:40,right:16},
            xAxis:{type:'category',data:hist.map(h=>h.time?.split(' ')[1]||'now'),axisLabel:{fontSize:10,color:'#475569'},axisLine:{lineStyle:{color:'rgba(255,255,255,0.06)'}}},
            yAxis:{type:'value',min:0,max:100,axisLabel:{fontSize:10,color:'#475569'},splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)'}},
                markLine:{silent:true,data:[{yAxis:70,label:{show:true,formatter:'可投线',color:'#4ade80',fontSize:9},lineStyle:{color:'rgba(74,222,128,0.2)',type:'dashed'}},{yAxis:55,label:{show:true,formatter:'警戒线',color:'#fbbf24',fontSize:9},lineStyle:{color:'rgba(251,191,36,0.2)',type:'dashed'}}]}},
            series:[{type:'line',data:hist.map(h=>h.score),smooth:true,symbol:'circle',symbolSize:7,
                lineStyle:{color:tc,width:2.5},itemStyle:{color:tc,borderColor:tc,borderWidth:2},
                areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:tcR+'0.2)'},{offset:1,color:tcR+'0)'}]}}}]
        });
    },

    // ── 10. KPI Dashboard ──
    renderKPIDashboard(d) {
        const c=this.cfg, el=document.getElementById(c.kpiDashboardId||'audit-kpi-dashboard'); if(!el)return;
        const accentMap={pass:'rgba(16,185,129,0.5)',warn:'rgba(245,158,11,0.5)',fail:'rgba(239,68,68,0.5)'};
        const colorMap={pass:'#34d399',warn:'#fbbf24',fail:'#f87171'};
        const kpis = c.buildKPIs ? c.buildKPIs(d) : [{label:'综合评分',icon:'🏆',value:d.trust_score,suffix:'/100',sub:`${d.trust_grade}级 · ${d.total_checks}项审计检查`,level:d.trust_score>=70?'pass':d.trust_score>=55?'warn':'fail'}];
        el.innerHTML = kpis.map((kpi,i) => {
            const accent=accentMap[kpi.level], color=colorMap[kpi.level];
            return `<div class="audit-kpi-card" style="--kpi-accent:${accent};animation:auditSlideUp 0.45s cubic-bezier(0.22,1,0.36,1) ${0.1+i*0.07}s both">
                <div class="audit-kpi-label">${kpi.icon} ${kpi.label}</div>
                <div class="audit-kpi-value" id="kpi-val-${i}" style="color:${color}">0${kpi.suffix||''}</div>
                <div class="audit-kpi-sub">${kpi.sub}</div>
                ${kpi.indicator?`<div class="audit-kpi-indicator ${kpi.level}">${kpi.indicator}</div>`:''}
            </div>`;
        }).join('');
        kpis.forEach((kpi,i) => { setTimeout(() => this.counterUp(document.getElementById(`kpi-val-${i}`),kpi.value,kpi.suffix||'',900), 200+i*100); });
    },

    // ── Chart Helper ──
    initChart(elId) {
        const el = document.getElementById(elId); if(!el) return null;
        return (typeof AC!=='undefined') ? AC.registerChart(echarts.init(el)) : echarts.init(el);
    }
};

// 全局快捷方式 (HTML onclick 兼容)
function closeDetail() { AuditCore.closeDetail(); }
function scrollToFirstIssue() { AuditCore.scrollToFirstIssue(); }
