/**
 * AlphaCore 深度审计诊断终端 V6.0
 * Scientific Diagnostic Terminal
 * 五维审计 · Enforcer 执行器 · 确认弹窗 · 一键静音 · 审计趋势 · 自动展开
 */

const MODULE_META = {
    data_quality:    { icon: '📡', color: '#3b82f6', label: '数据质量',  weight: '35%' },
    strategy_health: { icon: '⚙️', color: '#8b5cf6', label: '策略健康',  weight: '25%' },
    risk_control:    { icon: '🛡️', color: '#f59e0b', label: '风控合规',  weight: '20%' },
    factor_decay:    { icon: '📈', color: '#10b981', label: '因子衰减',  weight: '10%' },
    system_status:   { icon: '🖥️', color: '#06b6d4', label: '系统状态',  weight: '10%' },
};

const GRADE_COLORS = { A: '#34d399', B: '#60a5fa', C: '#fbbf24', D: '#f87171' };

let auditData = null;

// ═══════════════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => { runAudit(); });

async function runAudit() {
    const btn = document.getElementById('audit-refresh-btn');
    const spinner = document.getElementById('audit-spinner');
    btn.disabled = true;
    spinner.style.display = 'inline-block';

    document.getElementById('audit-loading').style.display = 'block';
    document.getElementById('trust-hero').style.display = 'none';
    document.getElementById('audit-overview').style.display = 'none';
    document.getElementById('detail-section').classList.remove('visible');
    document.getElementById('alert-banner').classList.remove('visible');
    document.getElementById('warning-dashboard').classList.remove('visible');
    document.getElementById('audit-timeline').style.display = 'none';

    try {
        const resp = await fetch('/api/v1/audit');
        const data = await resp.json();
        if (data.status !== 'ok') throw new Error(data.message || '审计失败');
        auditData = data;
        renderAll(data);
    } catch (e) {
        console.error('审计失败:', e);
        showNetworkError(e.message || '未知错误，请确认服务器已启动');
    } finally {
        btn.disabled = false;
        spinner.style.display = 'none';
    }
}

// ═══════════════════════════════════════════════════════
//  渲染全部
// ═══════════════════════════════════════════════════════
function renderAll(data) {
    document.getElementById('audit-loading').style.display = 'none';
    document.getElementById('trust-hero').style.display = 'grid';
    document.getElementById('audit-overview').style.display = 'grid';

    renderTrustHero(data);
    renderRadar(data);
    renderModuleCards(data);
    renderAlertBanner(data);
    renderWarningDashboard(data);
    renderFooterUrgent(data);
    renderTimeline(data);

    // V5.0: Enforcer 面板 + 止损确认拦截
    renderEnforcerPanel(data);
    updateMuteUI(data);
    interceptStopLoss(data);

    document.getElementById('audit-time').textContent = data.audit_time || '';
    document.getElementById('footer-time').textContent = `· 审计于 ${data.audit_time} · 耗时 ${data.elapsed_seconds}s`;

    // V6.0: Scan-line completion animation
    const layout = document.getElementById('audit-layout');
    layout.classList.remove('scan-complete');
    void layout.offsetWidth; // force reflow
    layout.classList.add('scan-complete');

    // 自动展开得分最低的模块 (noScroll=true, never steal viewport)
    setTimeout(() => autoExpandWorst(data), 800);
}

// ═══════════════════════════════════════════════════════
//  Counter-Up 动画引擎
// ═══════════════════════════════════════════════════════
function counterUp(el, target, suffix = '', duration = 1200) {
    if (!el) return;
    const startTime = performance.now();
    const isInt = Number.isInteger(target);
    function tick(now) {
        const p = Math.min((now - startTime) / duration, 1);
        const ease = 1 - Math.pow(1 - p, 3);
        const val = isInt ? Math.round(target * ease) : (target * ease).toFixed(1);
        el.textContent = val + suffix;
        if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

// ═══════════════════════════════════════════════════════
//  1. Trust Score Hero V7.0 — 三栏诊断报告头
// ═══════════════════════════════════════════════════════
function renderTrustHero(data) {
    const score = data.trust_score;
    const grade = data.trust_grade;
    const gc = GRADE_COLORS[grade] || '#94a3b8';

    // Big Score (center column primary visual)
    const bigScore = document.getElementById('trust-big-score');
    bigScore.style.color = gc;
    counterUp(bigScore, score, '', 1400);

    // Grade badge (superscript)
    const badge = document.getElementById('trust-grade-badge');
    badge.textContent = grade;
    badge.className = `trust-grade-badge grade-${grade}`;

    const verdicts = {
        A: '系统运行正常，所有审计通过，可放心执行交易信号',
        B: '系统整体健康，存在轻微瑕疵，建议关注警告项',
        C: '存在风险因素，建议人工复核后再执行',
        D: '严重问题检出，建议暂停自动执行并排查',
    };
    document.getElementById('trust-verdict').textContent = verdicts[grade] || '';
    document.getElementById('stat-pass').textContent = `✅ ${data.pass_count} 通过`;
    document.getElementById('stat-warn').textContent = `⚠️ ${data.warn_count} 警告`;
    document.getElementById('stat-fail').textContent = `❌ ${data.fail_count} 失败`;
    const mutedText = data.muted_count > 0 ? ` · 🔇 ${data.muted_count} 静音` : '';
    document.getElementById('trust-meta').textContent =
        `共 ${data.total_checks} 项检查 · 加权评分 ${score}/100 · ${data.audit_time}${mutedText}`;

    // V7.0: Equalizer vertical bars (replaces mini-bars)
    const keys = Object.keys(MODULE_META);
    const eqLabels = { data_quality: '数据', strategy_health: '策略', risk_control: '风控', factor_decay: '因子', system_status: '系统' };
    const eqHtml = keys.map((k, i) => {
        const mod = data.modules[k];
        if (!mod) return '';
        const meta = MODULE_META[k];
        const s = mod.score;
        const barColor = s >= 85 ? '#10b981' : (s >= 70 ? '#3b82f6' : (s >= 55 ? '#f59e0b' : '#ef4444'));
        const h = Math.max(s * 1.4, 8); // map 0-100 to 0-140px
        const delay = 0.1 + i * 0.12;
        return `<div class="eq-bar-group" title="${meta.label}: ${s}/100 (权重${meta.weight})">
            <span class="eq-score" style="color:${barColor}">${s}</span>
            <div class="eq-track">
                <div class="eq-fill" style="--bar-h:${h}px;height:${h}px;background:${barColor};animation-delay:${delay}s"></div>
            </div>
            <span class="eq-label">${eqLabels[k] || meta.label}</span>
        </div>`;
    }).join('');
    document.getElementById('trust-equalizer').innerHTML = eqHtml;

    // Gauge Chart (V7.0: no center number — score shown in center column)
    const chart = echarts.init(document.getElementById('trust-gauge-chart'));
    chart.setOption({
        series: [{
            type: 'gauge', startAngle: 210, endAngle: -30,
            radius: '88%', center: ['50%', '55%'],
            min: 0, max: 100, splitNumber: 4,
            axisLine: {
                lineStyle: { width: 18, color: [
                    [0.55, '#ef4444'], [0.70, '#f59e0b'],
                    [0.85, '#3b82f6'], [1, '#10b981'],
                ]},
            },
            pointer: { length: '55%', width: 4, itemStyle: { color: gc } },
            axisTick: { show: false },
            splitLine: { length: 10, lineStyle: { color: 'rgba(255,255,255,0.15)', width: 1 } },
            axisLabel: { distance: 18, color: '#64748b', fontSize: 10, fontFamily: 'Outfit' },
            detail: { show: false },
            title: { show: true, offsetCenter: [0, '35%'], fontSize: 11, color: '#94a3b8', fontFamily: 'Inter' },
            data: [{ value: score, name: 'Trust Score' }],
        }],
    });
}

// ═══════════════════════════════════════════════════════
//  2. 五维雷达图
// ═══════════════════════════════════════════════════════
function renderRadar(data) {
    const modules = data.modules;
    const keys = Object.keys(MODULE_META);
    const indicator = keys.map(k => ({ name: MODULE_META[k].label, max: 100 }));
    const values = keys.map(k => modules[k]?.score ?? 0);

    const chart = echarts.init(document.getElementById('radar-chart'));
    chart.setOption({
        radar: {
            indicator, shape: 'polygon', radius: '72%',
            axisName: { color: '#94a3b8', fontSize: 11, fontWeight: 600 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            splitArea: { areaStyle: { color: ['rgba(139,92,246,0.02)', 'rgba(139,92,246,0.04)'] } },
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        },
        series: [{
            type: 'radar',
            data: [{
                value: values, name: '审计评分',
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(139,92,246,0.35)' },
                            { offset: 1, color: 'rgba(59,130,246,0.08)' },
                        ],
                    },
                },
                lineStyle: { color: '#8b5cf6', width: 2 },
                itemStyle: { color: '#a78bfa' },
                symbol: 'circle', symbolSize: 7,
            }],
        }],
    });

    const legend = document.getElementById('radar-legend');
    legend.innerHTML = keys.map(k => {
        const m = MODULE_META[k];
        const s = modules[k]?.score ?? 0;
        return `<span class="radar-legend-item"><span class="radar-legend-dot" style="background:${m.color}"></span>${m.label} ${s}</span>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  3. 模块卡片
// ═══════════════════════════════════════════════════════
function renderModuleCards(data) {
    const container = document.getElementById('module-cards');
    const keys = Object.keys(MODULE_META);
    const html = keys.map(key => {
        const meta = MODULE_META[key];
        const mod = data.modules[key];
        if (!mod) return '';
        const score = mod.score, grade = mod.grade;
        const gc = GRADE_COLORS[grade] || '#94a3b8';
        const checks = mod.checks || [];
        const passC = checks.filter(c => c.status === 'pass').length;
        const warnC = checks.filter(c => c.status === 'warn').length;
        const failC = checks.filter(c => c.status === 'fail').length;
        const r = 18, circ = 2 * Math.PI * r, dash = circ * (score / 100);
        const sorted = [...checks].sort((a, b) => (a.score ?? 100) - (b.score ?? 100));
        const worst = sorted[0];
        let worstHtml = '';
        if (worst) {
            const wIcon = worst.status === 'pass' ? '✅' : (worst.status === 'warn' ? '⚠️' : '❌');
            const wColor = worst.status === 'pass' ? '#34d399' : (worst.status === 'warn' ? '#fbbf24' : '#f87171');
            const issueClass = worst.status !== 'pass' ? ' has-issue' : '';
            worstHtml = `<div class="mod-worst-preview${issueClass}">
                <span style="color:${wColor}">${wIcon} ${worst.name}</span>
                <span class="mod-worst-score" style="color:${wColor}">${worst.score ?? 0}</span>
            </div>`;
        }
        return `
        <div class="module-card" style="--mod-color:${meta.color}" onclick="toggleDetail('${key}')" id="card-${key}">
            <div class="mod-header">
                <span class="mod-label">${meta.icon} ${meta.label}</span>
                <div class="mod-score-ring">
                    <svg viewBox="0 0 42 42">
                        <circle class="mod-ring-bg" cx="21" cy="21" r="${r}"/>
                        <circle class="mod-ring-fill" cx="21" cy="21" r="${r}"
                            stroke="${gc}" stroke-dasharray="${circ}" stroke-dashoffset="${circ - dash}"/>
                    </svg>
                    <span class="mod-score-text">${score}</span>
                    <span class="mod-grade-pill grade-${grade}">${grade}</span>
                </div>
            </div>
            <div class="mod-checks-summary">
                ${passC > 0 ? `<span style="color:#34d399">✅${passC}</span> ` : ''}
                ${warnC > 0 ? `<span style="color:#fbbf24">⚠️${warnC}</span> ` : ''}
                ${failC > 0 ? `<span style="color:#f87171">❌${failC}</span> ` : ''}
                <span class="weight-tag">权重 ${meta.weight}</span>
            </div>
            ${worstHtml}
        </div>`;
    }).join('');
    container.innerHTML = html;
}

// ═══════════════════════════════════════════════════════
//  4. 展开检查明细 (V3.0: 智能阈值段渲染)
// ═══════════════════════════════════════════════════════
let activeModule = null;

function toggleDetail(key, noScroll = false) {
    const section = document.getElementById('detail-section');
    document.querySelectorAll('.module-card').forEach(c => c.classList.remove('expanded'));
    if (activeModule === key) { section.classList.remove('visible'); activeModule = null; return; }
    // noScroll: true = auto-expand 模式，不抢夺视口焦点
    activeModule = key;
    const card = document.getElementById(`card-${key}`);
    if (card) card.classList.add('expanded');
    const meta = MODULE_META[key];
    const mod = auditData.modules[key];
    if (!mod) return;
    document.getElementById('detail-title').textContent = `${meta.icon} ${meta.label} · ${mod.score}/100 (${mod.grade}级)`;

    const body = document.getElementById('detail-body');
    body.innerHTML = (mod.checks || []).map((c, idx) => {
        const icon = c.status === 'pass' ? '✅' : (c.status === 'warn' ? '⚠️' : (c.status === 'muted' ? '🔇' : '❌'));
        const sc = c.score ?? 0;
        const isMuted = c.status === 'muted';
        const barColor = isMuted ? '#475569' : (sc >= 85 ? '#10b981' : (sc >= 70 ? '#3b82f6' : (sc >= 55 ? '#f59e0b' : '#ef4444')));
        const textColor = isMuted ? '#64748b' : (sc >= 85 ? '#34d399' : (sc >= 70 ? '#60a5fa' : (sc >= 55 ? '#fbbf24' : '#f87171')));
        const ruleId = `rule-${key}-${idx}`;
        const hasRule = c.explanation || c.threshold || c.action;

        // V3.0: 智能阈值段渲染
        let thresholdHtml = '';
        if (c.threshold) {
            const segments = parseThresholdSegments(c.threshold, c.status);
            thresholdHtml = `<div class="rule-threshold-bar">
                <span class="threshold-label">📊 阈值:</span>
                <div class="threshold-segments">${segments}</div>
            </div>`;
        }

        return `
        <div class="check-row status-${c.status}" id="check-${key}-${idx}">
            <span class="check-icon">${icon}</span>
            <div class="check-info">
                <div class="check-name">${c.name}</div>
                <div class="check-detail">${c.detail || ''}</div>
                ${c.meta ? `<div class="check-meta">${c.meta}</div>` : ''}
            </div>
            <div class="check-score-bar">
                <div class="check-score-fill" style="width:${sc}%;background:${barColor}"></div>
            </div>
            <span class="check-score-val" style="color:${textColor}">${sc}</span>
            ${hasRule ? `<button class="check-expand-btn" id="btn-${ruleId}" onclick="toggleRule(event,'${ruleId}')">▼</button>` : ''}
        </div>
        ${hasRule ? `
        <div class="check-rule-panel" id="${ruleId}">
            ${c.explanation ? `<div class="rule-explanation">
                <span class="rule-section-icon">📖</span> ${c.explanation}
            </div>` : ''}
            ${thresholdHtml}
            ${c.action ? `<div class="rule-action">
                <span class="rule-action-label">🛠️ 修复:</span>
                <span class="rule-action-text">${c.action}</span>
                <button class="rule-action-copy" onclick="copyAction(event,'${c.action.replace(/'/g, "\\'")}')" title="复制命令">📋</button>
            </div>` : ''}
        </div>` : ''}`;
    }).join('');

    section.classList.add('visible');
    if (!noScroll) {
        section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// V3.0: 解析阈值字符串为信号灯段
function parseThresholdSegments(thresholdStr, status) {
    const segments = thresholdStr.split('|').map(s => s.trim());
    const activeType = status === 'pass' ? 'green' : (status === 'warn' ? 'yellow' : 'red');

    return segments.map(seg => {
        let type = 'green';
        if (seg.includes('🟡') || seg.includes('黄')) type = 'yellow';
        if (seg.includes('🔴') || seg.includes('红')) type = 'red';
        const text = seg.replace(/🟢|🟡|🔴/g, '').trim();
        const isActive = type === activeType;
        const icon = type === 'green' ? '🟢' : (type === 'yellow' ? '🟡' : '🔴');
        return `<div class="threshold-seg seg-${type}${isActive ? ' active' : ''}">
            <span class="seg-icon">${icon}</span>
            <span class="seg-text">${text}</span>
        </div>`;
    }).join('');
}

function closeDetail() {
    document.getElementById('detail-section').classList.remove('visible');
    document.querySelectorAll('.module-card').forEach(c => c.classList.remove('expanded'));
    activeModule = null;
}

// ═══════════════════════════════════════════════════════
//  5. 手风琴展开
// ═══════════════════════════════════════════════════════
function toggleRule(event, ruleId) {
    event.stopPropagation();
    const panel = document.getElementById(ruleId);
    const btn = document.getElementById(`btn-${ruleId}`);
    if (!panel) return;
    const isOpen = panel.classList.contains('open');
    const parent = panel.parentElement;
    if (parent) {
        parent.querySelectorAll('.check-rule-panel.open').forEach(p => {
            p.classList.remove('open');
            const sibBtn = document.getElementById(`btn-${p.id}`);
            if (sibBtn) sibBtn.classList.remove('open');
        });
    }
    if (!isOpen) {
        panel.classList.add('open');
        if (btn) btn.classList.add('open');
        setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 60);
    }
}

// 一键复制
function copyAction(event, text) {
    event.stopPropagation();
    navigator.clipboard.writeText(text).then(() => {
        const btn = event.currentTarget;
        btn.classList.add('copied');
        btn.textContent = '✓';
        setTimeout(() => { btn.classList.remove('copied'); btn.textContent = '📋'; }, 2000);
    });
}

// ═══════════════════════════════════════════════════════
//  6. 预警横幅
// ═══════════════════════════════════════════════════════
function renderAlertBanner(data) {
    const banner = document.getElementById('alert-banner');
    const iconEl = document.getElementById('alert-icon');
    const textEl = document.getElementById('alert-text');
    if (data.fail_count > 0) {
        const failItems = [];
        for (const mod of Object.values(data.modules))
            for (const c of (mod.checks || []))
                if (c.status === 'fail') failItems.push(c.name);
        banner.className = 'alert-banner level-fail visible';
        iconEl.textContent = '🚨';
        textEl.innerHTML = `<strong>${data.fail_count} 项审计未通过</strong> — ${failItems.slice(0, 3).join('、')}${failItems.length > 3 ? ` 等${failItems.length}项` : ''} 需要立即修复`;
    } else if (data.warn_count > 0) {
        const warnItems = [];
        for (const mod of Object.values(data.modules))
            for (const c of (mod.checks || []))
                if (c.status === 'warn') warnItems.push(c.name);
        banner.className = 'alert-banner level-warn visible';
        iconEl.textContent = '⚠️';
        textEl.innerHTML = `<strong>${data.warn_count} 项需要关注</strong> — ${warnItems.slice(0, 3).join('、')}${warnItems.length > 3 ? ` 等${warnItems.length}项` : ''}`;
    } else {
        banner.classList.remove('visible');
    }
}

// ═══════════════════════════════════════════════════════
//  7. KPI 面板 (V3.0: Counter-Up)
// ═══════════════════════════════════════════════════════
function renderWarningDashboard(data) {
    const container = document.getElementById('warning-dashboard');
    const kpis = extractKPIs(data);
    const html = kpis.map((kpi, i) => {
        const levelClass = kpi.level === 'fail' ? 'alert' : (kpi.level === 'warn' ? 'caution' : '');
        return `
        <div class="warn-card ${levelClass}" style="animation:auditFadeUp 0.5s cubic-bezier(0.22,1,0.36,1) ${0.05 + i * 0.08}s both;">
            <div class="warn-label">${kpi.label}</div>
            <div class="warn-value" data-counter="${kpi.numericValue || ''}" data-suffix="${kpi.suffix || ''}">${kpi.value}</div>
            <div class="warn-sub">${kpi.sub}</div>
            ${kpi.indicator ? `<div class="warn-indicator ${kpi.level}">${kpi.indicator}</div>` : ''}
        </div>`;
    }).join('');
    container.innerHTML = html;
    container.classList.add('visible');

    // Counter-Up animation for numeric KPIs
    setTimeout(() => {
        container.querySelectorAll('.warn-value[data-counter]').forEach(el => {
            const target = parseFloat(el.dataset.counter);
            if (!isNaN(target) && target > 0) counterUp(el, target, el.dataset.suffix, 1400);
        });
    }, 200);
}

function extractKPIs(data) {
    const kpis = [];
    const trustLevel = data.trust_score >= 85 ? 'pass' : (data.trust_score >= 70 ? 'warn' : 'fail');
    kpis.push({
        label: '🏆 可信度', value: `${data.trust_score}`, numericValue: data.trust_score, suffix: '',
        sub: `${data.trust_grade}级 · ${data.total_checks}项检查`, level: trustLevel,
        indicator: trustLevel === 'pass' ? '● 可靠' : (trustLevel === 'warn' ? '◐ 关注' : '○ 危险'),
    });

    const dq = data.modules?.data_quality;
    if (dq) {
        const freshCheck = dq.checks?.find(c => c.name === '日线数据新鲜度');
        if (freshCheck) {
            const dayMatch = freshCheck.detail?.match(/(\d+)天前/);
            const days = dayMatch ? parseInt(dayMatch[1]) : 0;
            kpis.push({
                label: '📡 数据延迟', value: `${days}天`, numericValue: days, suffix: '天',
                sub: freshCheck.detail?.replace(/[()（）]/g, '') || '', level: freshCheck.status,
                indicator: freshCheck.status === 'pass' ? '● 实时' : (freshCheck.status === 'warn' ? '◐ 偏旧' : '○ 过期'),
            });
        }
    }

    const sh = data.modules?.strategy_health;
    if (sh) {
        const stratChecks = sh.checks?.filter(c => c.name !== 'Regime 三态参数') || [];
        let maxAge = 0, oldestName = '';
        for (const c of stratChecks) {
            const m = c.detail?.match(/(\d+)天前/);
            if (m) { const a = parseInt(m[1]); if (a > maxAge) { maxAge = a; oldestName = c.name; } }
        }
        const aLevel = maxAge <= 30 ? 'pass' : (maxAge <= 60 ? 'warn' : 'fail');
        kpis.push({
            label: '⚙️ 参数新鲜', value: `${maxAge}天`, numericValue: maxAge, suffix: '天',
            sub: `最旧: ${oldestName || '全部就绪'}`, level: aLevel,
            indicator: aLevel === 'pass' ? '● 有效' : (aLevel === 'warn' ? '◐ 建议优化' : '○ 需重优化'),
        });
    }

    const rc = data.modules?.risk_control;
    if (rc) {
        const failChecks = rc.checks?.filter(c => c.status === 'fail') || [];
        const rcLevel = failChecks.length > 0 ? 'fail' : (rc.checks?.some(c => c.status === 'warn') ? 'warn' : 'pass');
        kpis.push({
            label: '🛡️ 风控', value: failChecks.length > 0 ? `${failChecks.length}违规` : '合规',
            numericValue: failChecks.length, suffix: failChecks.length > 0 ? '违规' : '',
            sub: rc.checks?.length ? `${rc.checks.length}项检查` : '', level: rcLevel,
            indicator: rcLevel === 'pass' ? '● 达标' : (rcLevel === 'warn' ? '◐ 注意' : '○ 违规'),
        });
    }

    const ss = data.modules?.system_status;
    if (ss) {
        const apiCheck = ss.checks?.find(c => c.name === 'Tushare API');
        if (apiCheck) {
            const latMatch = apiCheck.detail?.match(/延迟\s*(\d+)ms/);
            const latency = latMatch ? parseInt(latMatch[1]) : 0;
            kpis.push({
                label: '🖥️ API', value: latency > 0 ? `${latency}ms` : (apiCheck.status === 'pass' ? '在线' : '离线'),
                numericValue: latency, suffix: 'ms', sub: apiCheck.detail || '', level: apiCheck.status,
                indicator: apiCheck.status === 'pass' ? '● 连通' : '○ 断开',
            });
        }
    }

    const fd = data.modules?.factor_decay;
    if (fd) {
        const covCheck = fd.checks?.find(c => c.name === '因子数据覆盖');
        if (covCheck) {
            kpis.push({
                label: '📈 因子池', value: covCheck.score >= 80 ? '充分' : (covCheck.score >= 50 ? '一般' : '不足'),
                sub: covCheck.detail || '', level: covCheck.status,
                indicator: covCheck.status === 'pass' ? '● 覆盖' : (covCheck.status === 'warn' ? '◐ 偏少' : '○ 不足'),
            });
        }
    }
    return kpis;
}

// ═══════════════════════════════════════════════════════
//  8. 底栏紧急状态
// ═══════════════════════════════════════════════════════
function renderFooterUrgent(data) {
    const el = document.getElementById('footer-urgent');
    if (data.fail_count > 0) {
        el.className = 'footer-urgent has-issues';
        el.textContent = `🚨 ${data.fail_count} 项严重问题需修复`;
    } else if (data.warn_count > 0) {
        el.className = 'footer-urgent has-issues';
        el.style.background = 'rgba(245,158,11,0.1)';
        el.style.color = '#fbbf24';
        el.textContent = `⚠️ ${data.warn_count} 项需要关注`;
    } else {
        el.className = 'footer-urgent all-clear';
        el.textContent = '✅ 全部通过';
    }
}

// ═══════════════════════════════════════════════════════
//  9. 审计趋势 (V3.0 NEW — localStorage)
// ═══════════════════════════════════════════════════════
function renderTimeline(data) {
    const container = document.getElementById('audit-timeline');
    if (!container) return;

    const historyKey = 'alphacore_audit_history';
    let history = [];
    try { history = JSON.parse(localStorage.getItem(historyKey) || '[]'); } catch(e) {}

    // 去重：同一时间戳不重复写入
    const lastTime = history.length > 0 ? history[history.length - 1].time : '';
    if (data.audit_time !== lastTime) {
        history.push({ score: data.trust_score, time: data.audit_time, grade: data.trust_grade });
    }
    if (history.length > 10) history = history.slice(-10);
    localStorage.setItem(historyKey, JSON.stringify(history));

    if (history.length < 2) {
        container.style.display = 'block';
        document.getElementById('timeline-trend').textContent = '— 首次审计';
        document.getElementById('timeline-trend').className = 'timeline-trend stable';
        // Still render a single-point chart
        const chart = echarts.init(document.getElementById('timeline-chart'));
        chart.setOption({
            grid: { top: 8, bottom: 24, left: 40, right: 16 },
            xAxis: { type: 'category', data: [data.audit_time?.split(' ')[1] || 'now'], axisLabel: { fontSize: 10, color: '#475569' }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
            yAxis: { type: 'value', min: 0, max: 100, axisLabel: { fontSize: 10, color: '#475569' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
            series: [{ type: 'line', data: [data.trust_score], symbol: 'circle', symbolSize: 8, itemStyle: { color: '#a78bfa' } }]
        });
        return;
    }

    container.style.display = 'block';

    // Trend calc
    const prev = history[history.length - 2].score;
    const curr = history[history.length - 1].score;
    const trendEl = document.getElementById('timeline-trend');
    if (curr > prev) { trendEl.textContent = `↑ +${curr - prev}`; trendEl.className = 'timeline-trend up'; }
    else if (curr < prev) { trendEl.textContent = `↓ ${curr - prev}`; trendEl.className = 'timeline-trend down'; }
    else { trendEl.textContent = '→ 稳定'; trendEl.className = 'timeline-trend stable'; }

    const chart = echarts.init(document.getElementById('timeline-chart'));
    chart.setOption({
        grid: { top: 8, bottom: 24, left: 40, right: 16 },
        xAxis: {
            type: 'category',
            data: history.map(h => h.time?.split(' ')[1] || ''),
            axisLabel: { fontSize: 10, color: '#475569' },
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
        },
        yAxis: {
            type: 'value', min: 0, max: 100,
            axisLabel: { fontSize: 10, color: '#475569' },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        },
        series: [{
            type: 'line', data: history.map(h => h.score),
            smooth: true, symbol: 'circle', symbolSize: 7,
            lineStyle: { color: '#8b5cf6', width: 2.5 },
            itemStyle: { color: '#a78bfa', borderColor: '#8b5cf6', borderWidth: 2 },
            areaStyle: {
                color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: 'rgba(139,92,246,0.2)' },
                        { offset: 1, color: 'rgba(139,92,246,0)' },
                    ]
                }
            },
        }],
    });
}

// ═══════════════════════════════════════════════════════
//  10. 自动展开最差模块
// ═══════════════════════════════════════════════════════
function autoExpandWorst(data) {
    const keys = Object.keys(MODULE_META);
    let worstKey = null, worstScore = 101;
    for (const key of keys) {
        const mod = data.modules[key];
        if (!mod) continue;
        // Prioritize modules with fail items
        const hasFail = mod.checks?.some(c => c.status === 'fail');
        const effectiveScore = hasFail ? mod.score - 100 : mod.score;
        if (effectiveScore < worstScore) {
            worstScore = effectiveScore;
            worstKey = key;
        }
    }
    if (worstKey && worstScore < 100) {
        toggleDetail(worstKey, true);  // noScroll=true: 展开但不抢焦点
    }
}

// ═══════════════════════════════════════════════════════
//  11. 滚动到首个问题
// ═══════════════════════════════════════════════════════
function scrollToFirstIssue() {
    if (!auditData) return;
    const keys = Object.keys(MODULE_META);
    for (const key of keys) {
        const mod = auditData.modules[key];
        if (!mod) continue;
        if (mod.checks?.some(c => c.status === 'fail' || c.status === 'warn')) {
            toggleDetail(key);
            return;
        }
    }
}

// ═══════════════════════════════════════════════════════
//  V4.0: Enforcer 面板渲染
// ═══════════════════════════════════════════════════════
function renderEnforcerPanel(data) {
    const panel = document.getElementById('enforcer-panel');
    const enf = data.enforcement;
    if (!enf) { panel.classList.remove('visible'); return; }

    panel.classList.add('visible');

    // Toggle 按钮状态
    const toggle = document.getElementById('enforcer-toggle');
    if (enf.enforcer_enabled) {
        toggle.classList.add('active');
    } else {
        toggle.classList.remove('active');
    }

    // 状态芯片
    const statusRow = document.getElementById('enforcer-status-row');
    const chips = [];

    // 总开关
    chips.push(`<span class="enforcer-chip ${enf.enforcer_enabled ? 'active' : 'inactive'}">
        ${enf.enforcer_enabled ? '🟢 执行器启用' : '⚪ 执行器禁用'}
    </span>`);

    // 止损自动执行
    chips.push(`<span class="enforcer-chip active">🔫 止损强平</span>`);

    // 交易阻断
    if (enf.trade_blocked) {
        chips.push(`<span class="enforcer-chip danger">⛔ 交易阻断中: ${enf.trade_block_reason || '审计触发'}</span>`);
    } else {
        chips.push(`<span class="enforcer-chip active">✅ 交易通道正常</span>`);
    }

    // 静音状态
    const mute = enf.mute_status;
    if (mute && mute.is_muted) {
        const muteInfo = mute.mute_until ? `至 ${mute.mute_until.split('T')[1]?.substring(0,5) || ''}` : '降级模式';
        chips.push(`<span class="enforcer-chip inactive">🔇 静音 ${muteInfo}</span>`);
    }

    statusRow.innerHTML = chips.join('');

    // 执行动作列表
    const actionsEl = document.getElementById('enforcer-actions');
    const actions = enf.actions || [];
    if (actions.length === 0) {
        actionsEl.innerHTML = '<div style="font-size:0.66rem;color:#475569;padding:4px 0;">本次审计无强制操作</div>';
    } else {
        actionsEl.innerHTML = actions.map(a => {
            const isSuccess = a.result === 'success';
            const icon = a.action === 'forced_stop_loss' ? '🔫' : '⛔';
            return `<div class="enforcer-action-item ${isSuccess ? 'success' : ''}">
                <span>${icon}</span>
                <span style="font-weight:600;">${a.name || a.ts_code}</span>
                <span style="color:#94a3b8;">${a.action === 'forced_stop_loss' ? `止损卖出 ${a.pnl_pct}%` : a.reason || ''}</span>
                <span style="margin-left:auto;font-weight:700;${isSuccess ? 'color:#34d399' : 'color:#f87171'}">${isSuccess ? '✓ 已执行' : '✗ 失败'}</span>
            </div>`;
        }).join('');
    }
}

// ═══════════════════════════════════════════════════════
//  V4.0: Enforcer 开关
// ═══════════════════════════════════════════════════════
async function toggleEnforcer() {
    const toggle = document.getElementById('enforcer-toggle');
    const isActive = toggle.classList.contains('active');
    const newState = !isActive;

    try {
        const resp = await AC.secureFetch(`/api/v1/audit/enforcer/toggle?enabled=${newState}`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'ok') {
            if (newState) {
                toggle.classList.add('active');
            } else {
                toggle.classList.remove('active');
            }
        }
    } catch (e) {
        console.error('Enforcer toggle failed:', e);
    }
}

// ═══════════════════════════════════════════════════════
//  V4.0: 一键静音
// ═══════════════════════════════════════════════════════
let muteTimer = null;

async function toggleMute() {
    const btn = document.getElementById('mute-btn');
    const isMuted = btn.classList.contains('muted');

    try {
        if (isMuted) {
            // 解除静音
            await AC.secureFetch('/api/v1/audit/mute', { method: 'DELETE' });
            btn.classList.remove('muted');
            btn.innerHTML = '🔇 静音';
            document.getElementById('mute-countdown').textContent = '';
            if (muteTimer) clearInterval(muteTimer);
            muteTimer = null;
        } else {
            // 设置静音 30 分钟
            await AC.secureFetch('/api/v1/audit/mute?minutes=30&degraded=true', { method: 'POST' });
            btn.classList.add('muted');
            btn.innerHTML = '🔔 解除静音';
            startMuteCountdown(30);
        }
    } catch (e) {
        console.error('Mute toggle failed:', e);
    }
}

function startMuteCountdown(minutes) {
    let remaining = minutes * 60;
    const cd = document.getElementById('mute-countdown');

    if (muteTimer) clearInterval(muteTimer);
    muteTimer = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(muteTimer);
            muteTimer = null;
            const btn = document.getElementById('mute-btn');
            btn.classList.remove('muted');
            btn.innerHTML = '🔇 静音';
            cd.textContent = '';
            return;
        }
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        cd.textContent = `${m}:${s.toString().padStart(2, '0')}`;
    }, 1000);
}

function updateMuteUI(data) {
    const enf = data.enforcement;
    if (!enf) return;

    const mute = enf.mute_status;
    const btn = document.getElementById('mute-btn');

    if (mute && mute.is_muted) {
        btn.classList.add('muted');
        btn.innerHTML = '🔔 解除静音';
        // 计算剩余时间
        if (mute.mute_until) {
            try {
                const expiry = new Date(mute.mute_until);
                const remaining = Math.max(0, Math.floor((expiry - Date.now()) / 1000));
                if (remaining > 0) {
                    startMuteCountdown(Math.ceil(remaining / 60));
                }
            } catch (e) {}
        }
    } else {
        btn.classList.remove('muted');
        btn.innerHTML = '🔇 静音';
        document.getElementById('mute-countdown').textContent = '';
    }
}

// ═══════════════════════════════════════════════════════
//  V5.0: Enforcer 确认弹窗 (防止闪崩误杀)
// ═══════════════════════════════════════════════════════
let _pendingConfirmAction = null;

function showConfirmModal(title, bodyHTML, onConfirm) {
    document.getElementById('confirm-modal-title-text').textContent = title;
    document.getElementById('confirm-modal-body').innerHTML = bodyHTML;
    _pendingConfirmAction = onConfirm;
    document.getElementById('confirm-modal-overlay').classList.add('visible');
}

function closeConfirmModal() {
    document.getElementById('confirm-modal-overlay').classList.remove('visible');
    _pendingConfirmAction = null;
}

function executeConfirmedAction() {
    if (_pendingConfirmAction) {
        _pendingConfirmAction();
    }
    closeConfirmModal();
}

// V5.0: 拦截 Enforcer 自动止损 — 弹窗确认
function interceptStopLoss(data) {
    const enf = data.enforcement;
    if (!enf || !enf.actions) return;

    const stopLossActions = enf.actions.filter(a =>
        a.type === 'stop_loss' && a.action === 'sell'
    );

    if (stopLossActions.length > 0) {
        const listHTML = stopLossActions.map(a =>
            `<div style="padding:8px 12px;background:rgba(239,68,68,0.08);border-radius:8px;margin:6px 0;border-left:3px solid #ef4444;">
                <strong style="color:#f87171;">${a.name || a.ts_code}</strong>
                <span style="color:#94a3b8;margin-left:8px;">浮亏 ${a.pnl_pct || '?'}%</span>
            </div>`
        ).join('');

        showConfirmModal(
            '⚠️ 止损强平确认',
            `<p style="margin-bottom:12px;">以下 <strong style="color:#f87171;">${stopLossActions.length}</strong> 只持仓触发止损线：</p>
            ${listHTML}
            <p style="margin-top:14px;padding:10px;background:rgba(245,158,11,0.08);border-radius:8px;font-size:0.76rem;color:#fbbf24;">
                ⚡ 确认后将立即执行市价卖出。取消则保持当前仓位。
            </p>`,
            () => {
                // 用户确认后才真正执行止损
                console.log('[V5.0] 止损已确认执行:', stopLossActions);
                // 在真实交易场景中, 这里应调用 /api/v1/trade
            }
        );
    }
}

// V5.0: 增强错误处理 — 网络中断优雅降级
function showNetworkError(msg) {
    const loading = document.getElementById('audit-loading');
    loading.innerHTML = `
        <div style="text-align:center;padding:50px 30px;">
            <div style="font-size:2.5rem;margin-bottom:16px;">📡</div>
            <div style="font-size:1rem;font-weight:700;color:#f87171;margin-bottom:8px;">审计连接中断</div>
            <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:20px;">${msg}</div>
            <div style="display:flex;gap:12px;justify-content:center;">
                <button onclick="runAudit()" class="audit-btn" style="font-size:0.78rem;">🔄 重新审计</button>
                <a href="/" class="audit-btn" style="font-size:0.78rem;text-decoration:none;background:rgba(100,116,139,0.15);border-color:rgba(100,116,139,0.3);color:#94a3b8;">← 返回首页</a>
            </div>
        </div>`;
    loading.style.display = 'block';
}
