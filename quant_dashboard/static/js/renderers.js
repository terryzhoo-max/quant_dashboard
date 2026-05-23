// ══════════════════════════════════════════
// AlphaCore · Renderers (O3 模块化拆分)
// 纯 DOM 渲染: Signal/ERP/Capital/Heatmap/
// AIAE Thermometer/Decision Summary/Alert/
// Global Pulse/Intelligence Feed/Sparkline
// ══════════════════════════════════════════

function renderSignalCard(signalData) {
    if (!signalData) return;

    const cardEl = el('card-signal');
    const consensusCountEl = el('signal-consensus-count');
    const consensusLabelEl = el('signal-consensus-label');
    const matrixEl = el('signal-matrix');
    const descEl = el('desc-signal');

    // V10.0: 新结构化数据 (有 strategies 数组 + v10_ 字段)
    if (signalData.strategies && Array.isArray(signalData.strategies)) {
        const hasV10 = signalData.v10_score !== undefined;

        // 共振摘要: V10.0 加权得分 + 方向标签 + 置信度
        if (consensusCountEl) {
            if (hasV10) {
                const score = signalData.v10_score;
                const sign = score >= 0 ? '+' : '';
                const scoreColor = score > 15 ? '#10b981' : (score < -15 ? '#ef4444' : '#94a3b8');
                // 得分数值 + 迷你进度条
                const gaugePct = Math.min(100, Math.max(0, (score + 100) / 2)); // -100→0%, +100→100%
                const gaugeColor = score > 15 ? 'rgba(16,185,129,0.6)' : (score < -15 ? 'rgba(239,68,68,0.6)' : 'rgba(148,163,184,0.3)');
                consensusCountEl.innerHTML = `<span class="v10-score" style="color:${scoreColor}">${sign}${score.toFixed(1)}</span>
                    <span class="v10-gauge"><span class="v10-gauge-fill" style="width:${gaugePct}%;background:${gaugeColor}"></span><span class="v10-gauge-center"></span></span>`;
            } else {
                consensusCountEl.textContent = signalData.consensus || '--';
            }
        }
        if (consensusLabelEl) {
            const label = hasV10 ? signalData.v10_label : (signalData.consensus_label || '同步中');
            const dir = hasV10 ? signalData.v10_direction : 'neutral';
            const conf = hasV10 ? signalData.v10_confidence : '';

            // V10.0: 五档状态色 (含 strong-bear)
            let labelClass = 'sig-neutral';
            if (hasV10) {
                if (dir === 'bull' && signalData.v10_score >= 30) labelClass = 'sig-bull';
                else if (dir === 'bull') labelClass = 'sig-mild-bull';
                else if (dir === 'bear' && signalData.v10_score <= -30) labelClass = 'sig-strong-bear';
                else if (dir === 'bear') labelClass = 'sig-bear';
            } else {
                const ups = (signalData.consensus || '').match(/(\d+)\/5/);
                const upCount = ups ? parseInt(ups[1], 10) : 0;
                labelClass = upCount >= 4 ? 'sig-bull' : (upCount >= 3 ? 'sig-mild-bull' : (upCount <= 1 ? 'sig-bear' : 'sig-neutral'));
            }

            // 方向 emoji
            const dirEmoji = dir === 'bull' ? '📈' : (dir === 'bear' ? '📉' : '➖');
            // 置信度 badge
            const confBadge = conf ? ` <span class="sig-confidence sig-conf-${conf}">${conf === 'high' ? '高' : conf === 'medium' ? '中' : '低'}置信</span>` : '';
            consensusLabelEl.innerHTML = `${dirEmoji} ${label}${confBadge}`;
            consensusLabelEl.className = 'signal-consensus-label ' + labelClass;
        }

        // 整体卡片光晕: V10.0 方向驱动
        if (cardEl) {
            const dir = hasV10 ? signalData.v10_direction : signalData.status;
            cardEl.classList.remove('active-glow', 'bear-glow');
            if (dir === 'bull' || dir === 'up') cardEl.classList.add('active-glow');
            else if (dir === 'bear') cardEl.classList.add('bear-glow');
        }

        // 五行策略矩阵: V10.0 含强度条 + 权重
        if (matrixEl) {
            matrixEl.innerHTML = signalData.strategies.map((s, i) => {
                const dirClass = s.direction === 'up' ? 'sig-dir-up' :
                                 s.direction === 'down' ? 'sig-dir-down' :
                                 s.direction === 'mixed' ? 'sig-dir-mixed' : 'sig-dir-neutral';
                const strength = s.strength != null ? s.strength : 0;
                const weight = s.weight != null ? (s.weight * 100).toFixed(0) : '';

                // 强度条: 双向 [-1,+1] → 中心在50%
                const barPct = Math.abs(strength) * 50;
                const barDir = strength >= 0 ? 'right' : 'left';
                const barColor = strength > 0.1 ? '#10b981' : (strength < -0.1 ? '#ef4444' : '#64748b');
                const strengthLabel = (strength >= 0 ? '+' : '') + strength.toFixed(2);

                // 权重 pill
                const weightPill = weight ? `<span class="sig-weight">${weight}%</span>` : '';

                return `<div class="signal-row ${dirClass}" style="animation-delay:${i * 40}ms">
                    <span class="sig-icon">${s.icon}</span>
                    <span class="sig-name">${s.name}${weightPill}</span>
                    <span class="sig-signal">${s.signal}</span>
                    <span class="sig-strength-wrap">
                        <span class="sig-strength-track">
                            <span class="sig-strength-center"></span>
                            <span class="sig-strength-bar sig-bar-${barDir}" style="width:${barPct}%;background:${barColor}"></span>
                        </span>
                        <span class="sig-strength-val" style="color:${barColor}">${strengthLabel}</span>
                    </span>
                    <span class="sig-dot ${dirClass}"></span>
                </div>`;
            }).join('');
        }

        // 描述行: V10.0 精简格式
        if (descEl) {
            if (hasV10) {
                const legacy = signalData.v10_legacy || {};
                const legacyStr = legacy.ups !== undefined ? ` · (${legacy.ups}↑ ${legacy.downs}↓)` : '';
                descEl.textContent = `加权共振 ${signalData.v10_label}${legacyStr}`;
            } else {
                descEl.textContent = `${signalData.consensus} · ${signalData.consensus_label}`;
            }
        }
    } else {
        // 降级: 旧格式 (value/trend/status) 兼容渲染
        if (consensusCountEl) consensusCountEl.textContent = signalData.value || '--';
        if (consensusLabelEl) {
            consensusLabelEl.textContent = '';
            consensusLabelEl.className = 'signal-consensus-label';
        }
        if (matrixEl) matrixEl.innerHTML = '';
        if (descEl) descEl.textContent = signalData.trend || '监控五大策略共振情况';
        if (cardEl) {
            if (signalData.status === 'up') cardEl.classList.add('active-glow');
            else cardEl.classList.remove('active-glow');
        }
    }
}

/**
 * V8.2: ERP 卡片专用渲染器
 * 修正语义: ERP ↑ = 股票便宜 = 利好 (绿色), ERP ↓ = 股票贵 = 利空 (红色)
 * 数据源字段: value, trend, desc, status, erp_pct, signal_label
 */
function renderErpCard(erpData) {
    if (!erpData) return;

    const valEl = el('val-erp');
    const trendEl = el('trend-erp');
    const descEl = el('desc-erp');
    const absLabel = el('erp-abs-label');
    const pctLabel = el('erp-pct-label');
    const pctBar = el('bar-erp-pct');
    const signalPill = el('erp-signal-pill');
    const cardEl = el('card-erp');

    // 1. 主值 + Trend Badge
    if (valEl) {
        valEl.innerHTML = `${erpData.value} <span class="trend" id="trend-erp">${erpData.trend || '--'}</span>`;
        // V3.0: 阈值从后端 erp_thresholds 读取, 消除硬编码漂移
        const erpVal = parseFloat(erpData.value) || 0;
        const thresh = erpData.erp_thresholds || { bullish: 5.0, bearish: 3.5 };
        let colorClass = 'erp-neutral';
        if (erpVal >= thresh.bullish) colorClass = 'erp-bullish';
        else if (erpVal < thresh.bearish) colorClass = 'erp-bearish';
        valEl.className = `stat-value ${colorClass}`;
    }

    // 2. 双维度标签
    if (absLabel && erpData.desc) {
        // desc 格式: "偏低估 · 4Y分位10.8%"
        const parts = (erpData.desc || '').split('·').map(s => s.trim());
        const absText = parts[0] || '--';
        absLabel.textContent = absText;
        // 颜色: 根据绝对值标签判定
        absLabel.className = 'erp-abs-label';
        if (/低估|极度低估/.test(absText)) absLabel.classList.add('erp-val-bull');
        else if (/高估|极度高估/.test(absText)) absLabel.classList.add('erp-val-bear');
    }

    // 3. 分位标签 + 进度条
    const pctVal = erpData.erp_pct != null ? erpData.erp_pct : 50;
    if (pctLabel) {
        pctLabel.textContent = `4Y分位 ${typeof pctVal === 'number' ? pctVal.toFixed(1) : pctVal}%`;
    }
    if (pctBar) {
        pctBar.style.width = `${Math.min(100, Math.max(0, pctVal))}%`;
    }

    // 4. 信号 Pill (标配持有 / 超配 / 减配)
    if (signalPill) {
        const sig = erpData.signal_label || '--';
        signalPill.textContent = sig;
        signalPill.className = 'erp-signal-pill';
        if (/超配|加仓|满配/.test(sig)) signalPill.classList.add('sig-bull');
        else if (/减配|清仓|观望/.test(sig)) signalPill.classList.add('sig-bear');
        else signalPill.classList.add('sig-neutral');
    }

    // 5. 描述行
    if (descEl) {
        descEl.textContent = `股债溢价 ${erpData.value || '--'} · 信号: ${erpData.signal_label || '--'}`;
    }

    // 6. 卡片光晕: ERP >= 5% 且 status='up' 时点亮
    if (cardEl) {
        if (erpData.status === 'up') cardEl.classList.add('active-glow');
        else cardEl.classList.remove('active-glow');
    }
}

/**
 * V10.0: 主力动向 (A+H 跨境监控) 专用渲染器
 * 目标 DOM IDs:
 *   val-capital-a-compact / trend-capital-a-compact  (北向数值+趋势)
 *   val-capital-h-compact / trend-capital-h-compact  (南向数值+趋势)
 *   cap-dir-a / cap-dir-h                            (方向指示灯)
 *   cap-resonance-pill                               (共振标签)
 *   bar-cap-z / cap-z-val                            (Z合力条+数值)
 *   desc-capital                                     (卡片底部描述)
 *   card-capital                                     (卡片光晕)
 *
 * 后端数据结构 (capital_a):
 *   value: "A: 151.4 亿", trend: "北向稳步流入", status: "up",
 *   z_score: 0.85, raw_5d: 151.4,
 *   resonance: "双多共振", resonance_status: "bull", z_composite: 1.65
 */
function renderCapitalCard(capA, capH) {
    // === 北向 ===
    if (capA) {
        const valA = el('val-capital-a-compact');
        const trendA = el('trend-capital-a-compact');
        const dirA = el('cap-dir-a');
        if (valA) valA.textContent = capA.value || '--';
        if (trendA) {
            trendA.textContent = capA.z_score != null ? `Z:${capA.z_score > 0 ? '+' : ''}${capA.z_score}` : (capA.trend || '--');
            trendA.className = 'cap-flow-trend ' +
                (capA.status === 'up' ? 'flow-up' : capA.status === 'down' ? 'flow-down' : 'flow-neutral');
        }
        if (dirA) {
            dirA.className = 'cap-flow-dir ' +
                (capA.status === 'up' ? 'dir-up' : capA.status === 'down' ? 'dir-down' : 'dir-neutral');
        }

        // 共振标签 pill
        const pillEl = el('cap-resonance-pill');
        if (pillEl) {
            const resonance = capA.resonance || '—';
            const rStatus = capA.resonance_status || 'neutral';
            pillEl.textContent = resonance;
            pillEl.className = 'cap-resonance-pill res-' + rStatus;
        }

        // Z 合力条
        const zComposite = capA.z_composite != null ? capA.z_composite : 0;
        const zBarEl = el('bar-cap-z');
        const zValEl = el('cap-z-val');
        if (zBarEl) {
            // 将 Z-score (-3 ~ +3) 映射到 0-100%
            const zPct = Math.min(100, Math.max(0, 50 + zComposite * 15));
            zBarEl.style.width = `${zPct}%`;
            zBarEl.className = 'cap-z-bar ' +
                (zComposite > 0.5 ? 'z-bull' : zComposite < -0.5 ? 'z-bear' : 'z-neutral');
        }
        if (zValEl) {
            zValEl.textContent = `${zComposite > 0 ? '+' : ''}${zComposite.toFixed(2)}`;
            zValEl.style.color = zComposite > 0.5 ? '#10b981' : (zComposite < -0.5 ? '#ef4444' : '#f59e0b');
        }
    }

    // === 南向 ===
    if (capH) {
        const valH = el('val-capital-h-compact');
        const trendH = el('trend-capital-h-compact');
        const dirH = el('cap-dir-h');
        if (valH) valH.textContent = capH.value || '--';
        if (trendH) {
            trendH.textContent = capH.z_score != null ? `Z:${capH.z_score > 0 ? '+' : ''}${capH.z_score}` : (capH.trend || '--');
            trendH.className = 'cap-flow-trend ' +
                (capH.status === 'up' ? 'flow-up' : capH.status === 'down' ? 'flow-down' : 'flow-neutral');
        }
        if (dirH) {
            dirH.className = 'cap-flow-dir ' +
                (capH.status === 'up' ? 'dir-up' : capH.status === 'down' ? 'dir-down' : 'dir-neutral');
        }
    }

    // === 卡片光晕 + 描述 ===
    const cardEl = el('card-capital');
    if (cardEl) {
        const isUp = (capA && capA.status === 'up') || (capH && capH.status === 'up');
        if (isUp) cardEl.classList.add('active-glow');
        else cardEl.classList.remove('active-glow');
    }

    const descEl = el('desc-capital');
    if (descEl && capA && capH) {
        descEl.textContent = `北向: ${capA.trend} · 南向: ${capH.trend}`;
    }
}

function renderExecutionLists(listContainer, listData) {
    if (!listContainer || !listData) return;
    
    listContainer.innerHTML = ''; // Clear processing text
    
    if (listData.length === 0) {
        listContainer.innerHTML = `<li><div style="color: #64748b; padding: 10px;">当前无符合条件标的</div></li>`;
        return;
    }
    
    listData.forEach(item => {
        const li = document.createElement('li');
        // 根据评分和买卖逻辑确定分数颜色
        let scoreClass = '';
        if (item.badgeClass === 'buy') {
            if (item.score >= 75) scoreClass = 'score-high';
            else if (item.score >= 60) scoreClass = 'score-mid';
            else scoreClass = 'score-low';
        } else { // danger_zone or sell
            if (item.score <= 30) scoreClass = 'score-danger';
            else scoreClass = 'score-low';
        }
            
        li.innerHTML = `
            <div class="stock-info">
                <span class="stock-name">${item.name}</span>
                <span class="stock-code">${item.code}</span>
            </div>
            <div class="stock-metrics">
                <div class="score-pill ${scoreClass}">评分: ${item.score || '--'}</div>
                <div class="metric-row">
                    <span class="metric">${item.metric || 'PE: ' + item.pe + 'x'}</span>
                    <span class="badge ${item.badgeClass}">${item.badge}</span>
                </div>
            </div>
        `;
        listContainer.appendChild(li);
    });
}

/**
 * V6.0 情绪与持仓枢纽渲染引擎
 */
function renderPositionHub(temp) {
    const vixMult = temp.market_vix_multiplier || 1.0;
    const hubEl = document.getElementById('card-sentiment-hub');
    
    // === 左栏: 心态指引 ===
    if (el('val-mindset')) el('val-mindset').innerText = temp.mindset || "侦测中...";
    
    // 温度颜色区域 (CSS data attribute 切换)
    if (hubEl) {
        let zone = 'warm';
        if (temp.value < 35) zone = 'cold';
        else if (temp.value > 65) zone = 'hot';
        hubEl.setAttribute('data-temp-zone', zone);
    }
    
    // 宏观微标签: 资金Z + ERP
    if (el('val-capital-z') && temp.z_capital !== undefined) {
        const zVal = temp.z_capital;
        el('val-capital-z').innerText = `${zVal > 0 ? '+' : ''}${zVal.toFixed(2)}`;
        el('val-capital-z').style.color = zVal > 0.5 ? '#10b981' : (zVal < -0.5 ? '#ef4444' : '#f59e0b');
    }
    if (el('val-erp-tag') && temp.hub_factors && temp.hub_factors.erp_value) {
        el('val-erp-tag').innerText = temp.hub_factors.erp_value.label;
        const erpScore = temp.hub_factors.erp_value.score;
        el('val-erp-tag').style.color = erpScore >= 70 ? '#10b981' : (erpScore >= 40 ? '#f59e0b' : '#ef4444');
    }

    // V26.0: ERP 百分位极端告警 pill (中栏列头)
    const erpWarnPill = el('hub-erp-warn-pill');
    if (erpWarnPill && temp.hub_factors && temp.hub_factors.erp_value) {
        const erpS = temp.hub_factors.erp_value.score;
        if (erpS <= 10) {
            erpWarnPill.className = 'hub-erp-warn-pill erp-warn-active';
            erpWarnPill.innerText = `⚠ ERP P${Math.round(erpS)}%`;
        } else if (erpS >= 90) {
            erpWarnPill.className = 'hub-erp-warn-pill erp-bull-active';
            erpWarnPill.innerText = `✦ ERP P${Math.round(erpS)}%`;
        } else {
            erpWarnPill.className = 'hub-erp-warn-pill';
            erpWarnPill.innerText = '';
        }
    }
    
    // === 中栏: 仓位研判面板 ===
    if (el('val-pos-advice')) el('val-pos-advice').innerText = temp.advice;
    
    // 仓位进度条 (优先从 strategy_positions.total 数值字段读取, 正则降级)
    let posPercent = 30;
    if (temp.strategy_positions && temp.strategy_positions.total != null) {
        posPercent = temp.strategy_positions.total;
    } else {
        const posMatch = (temp.advice || '').match(/(\d+)%/);
        if (posMatch) posPercent = parseInt(posMatch[1], 10);
    }
    if (el('bar-pos-advice')) {
        el('bar-pos-advice').style.width = `${posPercent}%`;
        // V11.0: 用后端 advice_tier (1-5) 驱动颜色, 消除 emoji 匹配脆弱性
        const tier = temp.advice_tier || 3;
        const tierColors = {1: '#10b981', 2: '#3b82f6', 3: '#eab308', 4: '#f97316', 5: '#ef4444'};
        el('bar-pos-advice').style.background = tierColors[tier] || '#eab308';
    }
    
    // 置信度
    if (temp.hub_confidence !== undefined) {
        const conf = temp.hub_confidence;
        if (el('val-confidence')) el('val-confidence').innerText = conf;
        if (el('conf-fill')) el('conf-fill').style.width = `${conf}%`;
    }
    
    // 五因子条形图
    if (temp.hub_factors) {
        const factorMap = {
            'vix':     { barId: 'fbar-vix',     scoreId: 'fscore-vix',     data: temp.hub_factors.vix_fear },
            'capital': { barId: 'fbar-capital',  scoreId: 'fscore-capital', data: temp.hub_factors.capital_flow },
            'temp':    { barId: 'fbar-temp',     scoreId: 'fscore-temp',    data: temp.hub_factors.macro_temp },
            'erp':     { barId: 'fbar-erp',      scoreId: 'fscore-erp',     data: temp.hub_factors.erp_value },
            'signal':  { barId: 'fbar-signal',   scoreId: 'fscore-signal',  data: temp.hub_factors.aiae_regime },
            'aiae':    { barId: 'fbar-aiae',     scoreId: 'fscore-aiae',    data: temp.hub_factors.aiae_temp }
        };
        
        for (const [key, cfg] of Object.entries(factorMap)) {
            if (!cfg.data) continue;
            const barEl = el(cfg.barId);
            const scoreEl = el(cfg.scoreId);
            
            if (barEl) {
                barEl.style.width = `${cfg.data.score}%`;
                // 颜色分级
                barEl.className = 'factor-bar';
                if (cfg.data.score >= 65) barEl.classList.add('score-high');
                else if (cfg.data.score >= 35) barEl.classList.add('score-mid');
                else barEl.classList.add('score-low');
            }
            if (scoreEl) {
                scoreEl.innerText = Math.round(cfg.data.score);
                // [P3] 因子分数颜色联动
                scoreEl.className = 'factor-score';
                if (cfg.data.score >= 65) scoreEl.classList.add('score-color-high');
                else if (cfg.data.score >= 35) scoreEl.classList.add('score-color-mid');
                else scoreEl.classList.add('score-color-low');
            }
        }
    }
    
    // === 右栏: 策略配仓 (合并自原配仓总览) ===
    // 策略权重条
    if (temp.regime_weights) {
        const rw = temp.regime_weights;
        // 策略卡片权重 pill 更新 (5策略)
        if (el('weight-mr'))  el('weight-mr').innerText  = `${(rw.mr * 100).toFixed(0)}%权重`;
        if (el('weight-mom')) el('weight-mom').innerText = `${(rw.mom * 100).toFixed(0)}%权重`;
        if (el('weight-div')) el('weight-div').innerText = `${(rw.div * 100).toFixed(0)}%权重`;
        if (el('weight-erp')) el('weight-erp').innerText = `${((rw.erp || 0) * 100).toFixed(0)}%权重`;
        if (el('weight-aiae')) el('weight-aiae').innerText = `${((rw.aiae_etf || 0) * 100).toFixed(0)}%权重`;
        
        // 堆叠条 (5策略)
        const updateBar = (id, key, label) => {
            const b = el(id);
            if (b) {
                b.style.width = `${((rw[key] || 0) * 100).toFixed(0)}%`;
                const span = b.querySelector('span');
                if (span) span.innerText = `${label} ${((rw[key] || 0) * 100).toFixed(0)}%`;
            }
        };
        updateBar('bar-div', 'div', '红利');
        updateBar('bar-mr',  'mr',  '均值');
        updateBar('bar-mom', 'mom', '动量');
        updateBar('bar-erp', 'erp', 'ERP');
        updateBar('bar-aiae', 'aiae_etf', 'AIAE');
    }
    
    // 各策略名义仓位
    if (temp.strategy_positions) {
        const sp = temp.strategy_positions;
        if (el('val-alloc-total')) el('val-alloc-total').innerText = `总仓位: ${sp.total}%`;
        const setPos = (id, val) => { const e = el(id); if (e) e.innerText = `${val}%`; };
        setPos('val-pos-div', sp.div_pos);
        setPos('val-pos-mr',  sp.mr_pos);
        setPos('val-pos-mom', sp.mom_pos);
        setPos('val-pos-erp', sp.erp_pos || 0);
        setPos('val-pos-aiae', sp.aiae_pos || 0);
    }
    
    // 策略过滤器状态
    if (temp.strategy_filters) {
        const sf = temp.strategy_filters;
        const setFilter = (id, val) => { const e = el(id); if (e) e.innerText = val === '正常' ? '' : val; };
        setFilter('filter-div', sf.div);
        setFilter('filter-mr',  sf.mr);
        setFilter('filter-mom', sf.mom);
    }
    
    // N5: 持仓周期标签联动后端 holding_cycle_a
    if (temp.holding_cycle_a && el('val-cycle-a')) {
        el('val-cycle-a').innerText = temp.holding_cycle_a;
    }
}

function renderHeatmap(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    // N3: 空状态兜底
    if (!data || data.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:40px 20px;color:#64748b;font-size:0.85rem;">📡 暂无行业轮动数据 · 请等待后端数据刷新</div>';
        return;
    }
    
    container.innerHTML = data.map(sector => {
        let intensityClass = '';
        const chg = sector.change;
        const trend5d = sector.trend_5d || 0;
        const rps = sector.rps || 0;
        
        if (chg >= 1.5) intensityClass = 'up-high';
        else if (chg >= 0.5) intensityClass = 'up-mid';
        else if (chg > 0) intensityClass = 'up-low';
        else if (chg <= -1.5) intensityClass = 'down-high';
        else if (chg <= -0.5) intensityClass = 'down-mid';
        else if (chg < 0) intensityClass = 'down-low';
        
        const sign = chg > 0 ? '+' : '';
        const trendSign = trend5d > 0 ? '+' : '';
        
        // 提示信息
        const tooltip = `5日累计: ${trendSign}${trend5d}% | RPS: ${rps} | MR: ${sector.mr_signal || '-'} | MOM: ${sector.mom_signal || '-'}`;
        
        // V5.0 信号角标
        let badges = '';
        if (sector.mr_signal === 'BUY' || sector.mr_signal === '买入') badges += '<span class="hm-badge hm-buy">📐</span>';
        else if (sector.mr_signal === 'SELL' || sector.mr_signal === '卖出') badges += '<span class="hm-badge hm-sell">📐</span>';
        if (sector.mom_signal === 'BUY' || sector.mom_signal === '买入') badges += '<span class="hm-badge hm-buy">🚀</span>';
        
        return `
            <div class="heatmap-cell ${intensityClass}" title="${tooltip}">
                ${badges ? `<div class="hm-badges">${badges}</div>` : ''}
                <span class="sector-name">${sector.name}</span>
                <span class="sector-change">${sign}${chg.toFixed(2)}%</span>
                <span class="sector-rps">5D:${trendSign}${trend5d.toFixed(1)}% · R:${rps}</span>
            </div>
        `;
    }).join('');
}

// Init when DOM loaded
document.addEventListener('DOMContentLoaded', () => {
    
    // 发起网络数据请求
    fetchQuantData();
    
    // UI/UX 亮点: 全局自动定时同步 (3分钟)
    setInterval(() => {
        if (!_isWarmingUp) {
            console.log("⌚ 全局定时同步触发...");
            fetchQuantData();
        }
    }, 180000);

    // 绑定刷新按钮事件 (V11.0: 防抖 + disable 防止并发)
    const refreshBtn = document.getElementById('refresh-btn');
    if(refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            if (refreshBtn.disabled) return;
            refreshBtn.disabled = true;
            const originalText = refreshBtn.innerText;
            refreshBtn.innerText = '拉取中...';
            refreshBtn.style.opacity = '0.6';
            
            // 如果处于预热状态，强制清掉 timer，走手动请求
            clearTimeout(_pollingTimer);
            
            fetchQuantData().finally(() => {
                setTimeout(() => {
                    refreshBtn.innerText = originalText;
                    refreshBtn.disabled = false;
                    refreshBtn.style.opacity = '1';
                }, 500);
            });
        });
    }

    // 导航交互动效
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const href = item.getAttribute('href');
            if (!href || href === '#') {
                e.preventDefault();
            }
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });

    // ERP 历史走势图异步加载
    fetchAndRenderERPChart();

    // V8.0: 新增模块异步加载 (不阻塞主数据流)
    fetchAndRenderGlobalPulse();
    fetchAndRenderIntelligenceFeed();

    // 辅助决策模块: 延迟加载 (避免与 dashboard-data 竞争)
    setTimeout(() => {
        fetchDecisionSummary();
        fetchAlertBell();
    }, 800);

    // 预警铃铛交互
    const bellWrap = document.getElementById('alert-bell-wrap');
    if (bellWrap) {
        bellWrap.addEventListener('click', (e) => {
            e.stopPropagation();
            bellWrap.classList.toggle('open');
        });
        document.addEventListener('click', () => bellWrap.classList.remove('open'));
    }
});

// ====== ERP 历史走势 V3.0 · 四档区间可视化 (近11.3年) ======

let _erpDashboardChart = null;

/**
 * 从后端拉取 ERP 择时引擎数据并渲染图表
 * 降级策略: 后端未启动时显示友好提示
 */
async function fetchAndRenderERPChart() {
    const loadingEl = document.getElementById('erp-chart-loading');
    const chartEl = document.getElementById('erp-history-chart');
    
    if (!chartEl) return;
    
    // ECharts 库检测
    if (typeof echarts === 'undefined') {
        if (loadingEl) loadingEl.innerHTML = '⚠️ ECharts 可视化库未加载，图表不可用';
        return;
    }
    
    try {
        const resp = await fetch('/api/v1/strategy/erp-timing');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        
        if (json.status === 'success' && json.data && json.data.chart && json.data.chart.status === 'success') {
            // 隐藏 loading，显示图表
            if (loadingEl) loadingEl.style.display = 'none';
            chartEl.style.display = 'block';
            renderERPDashboardChart(json.data.chart, json.data);
        } else {
            if (loadingEl) loadingEl.innerHTML = '⚠️ ERP 数据暂不可用 (' + (json.message || '格式异常') + ')';
        }
    } catch (err) {
        console.warn('[ERP Chart] 拉取失败，降级处理:', err);
        if (loadingEl) {
            loadingEl.innerHTML = '📡 请启动 <code style="background:rgba(96,165,250,0.15);padding:2px 6px;border-radius:4px;color:#60a5fa;">python main.py</code> 以获取 ERP 历史数据';
        }
    }
}

/**
 * 渲染 ERP 历史走势 V3.0 · 四档区间可视化 (移植自 strategy.js)
 * 特性: markArea色带 + dataZoom缩放 + 极值标注 + M1叠加 + KPI卡片
 */
function renderERPDashboardChart(chart, signalData) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom || typeof echarts === 'undefined') return;
    
    if (_erpDashboardChart) _erpDashboardChart = AC.disposeChart(_erpDashboardChart);
    _erpDashboardChart = AC.registerChart(echarts.init(dom));
    
    const stats = chart.stats || {};
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);

    // V3.0: 动态标题 (保留 section-icon 和 subtitle-pill 结构)
    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) {
        const yrs = stats.date_range_years || '?';
        // 只更新文本节点，不覆盖子元素 (icon/pill)
        const textNodes = Array.from(titleEl.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
        if (textNodes.length > 0) {
            textNodes.forEach(n => n.textContent = '');
            textNodes[0].textContent = ' ERP 估值走势 (近' + yrs + '年) ';
        }
    }

    // V3.0: KPI 卡片
    renderERPDashboardKPIs(stats, signalData);

    // V3.0: markArea 四档色带
    const markAreaData = [
        [{ yAxis: stats.strong_buy_line, itemStyle: { color: 'rgba(16,185,129,0.08)' } }, { yAxis: (stats.max || 8) + 0.5 }],
        [{ yAxis: stats.overweight_line, itemStyle: { color: 'rgba(16,185,129,0.03)' } }, { yAxis: stats.strong_buy_line }],
        [{ yAxis: stats.underweight_line, itemStyle: { color: 'transparent' } }, { yAxis: stats.overweight_line }],
        [{ yAxis: stats.danger_line, itemStyle: { color: 'rgba(239,68,68,0.04)' } }, { yAxis: stats.underweight_line }],
        [{ yAxis: (stats.min || 2) - 0.5, itemStyle: { color: 'rgba(239,68,68,0.08)' } }, { yAxis: stats.danger_line }],
    ];

    // V3.0: markPoint — 当前值 + 历史极值
    const markPointData = [];
    const lastDate = chart.dates[chart.dates.length - 1];
    if (stats.current != null) {
        markPointData.push({
            coord: [lastDate, stats.current],
            name: '当前', symbol: 'pin', symbolSize: 44,
            itemStyle: { color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
            label: { formatter: '{@[1]}%', color: '#fff', fontSize: 10, fontWeight: 700 }
        });
    }
    const extremes = stats.extremes || [];
    extremes.forEach(e => {
        markPointData.push({
            coord: [e.date, e.value],
            name: e.type === 'max' ? '历史最高' : '历史最低',
            symbol: e.type === 'max' ? 'triangle' : 'arrow',
            symbolSize: 12, symbolRotate: e.type === 'min' ? 180 : 0,
            itemStyle: { color: e.type === 'max' ? '#10b981' : '#ef4444' },
            label: { show: true, formatter: e.value + '%', fontSize: 9, color: e.type === 'max' ? '#10b981' : '#ef4444', position: e.type === 'max' ? 'top' : 'bottom' }
        });
    });

    // 区间判定函数
    function getZoneLabel(v) {
        if (v >= (stats.strong_buy_line || 99)) return '\uD83D\uDFE2 强买区';
        if (v >= (stats.overweight_line || 99)) return '\uD83D\uDD35 超配区';
        if (v >= (stats.underweight_line || -99)) return '\u26AA 中性区';
        if (v >= (stats.danger_line || -99)) return '\uD83D\uDFE0 低配区';
        return '\uD83D\uDD34 危险区';
    }

    const legendData = ['ERP', 'PE-TTM', '10Y国债'];
    if (hasM1) legendData.push('M1同比');
    
    _erpDashboardChart.setOption({
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: '#334155',
            textStyle: { fontSize: 11, color: '#e2e8f0' },
            formatter: function(params) {
                let r = '<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">' + params[0].axisValue + '</div>';
                params.forEach(p => {
                    if (p.value != null) {
                        const unit = p.seriesName === 'PE-TTM' ? 'x' : '%';
                        r += '<div>' + p.marker + ' ' + p.seriesName + ': <b>' + p.value + unit + '</b></div>';
                    }
                });
                // 找到 ERP 值并标注区间
                const erpParam = params.find(p => p.seriesName === 'ERP');
                if (erpParam && erpParam.value != null) {
                    r += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;">' + getZoneLabel(erpParam.value) + '</div>';
                }
                return r;
            }
        },
        legend: {
            data: legendData, top: 0,
            textStyle: { color: '#94a3b8', fontSize: 10 },
            selected: { '10Y国债': false }
        },
        toolbox: {
            right: 20, top: 0,
            feature: {
                saveAsImage: { title: '保存', pixelRatio: 2, backgroundColor: '#0f172a' },
                restore: { title: '重置' }
            },
            iconStyle: { borderColor: '#64748b' }
        },
        grid: { top: 40, bottom: 55, left: 50, right: hasM1 ? 90 : 50 },
        dataZoom: [
            { type: 'inside', start: 65, end: 100 },
            { type: 'slider', height: 16, bottom: 4, borderColor: 'rgba(255,255,255,0.06)',
              fillerColor: 'rgba(245,158,11,0.12)', handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
              textStyle: { color: '#64748b', fontSize: 9 },
              dataBackground: { lineStyle: { color: '#334155' }, areaStyle: { color: 'rgba(245,158,11,0.05)' } }
            }
        ],
        xAxis: {
            type: 'category', data: chart.dates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 10, formatter: function(v) { return v.substring(0, 7); } },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: [
            { type: 'value', name: 'ERP %', nameTextStyle: { color: '#64748b', fontSize: 10 },
              axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
              splitLine: { lineStyle: { color: 'rgba(100,116,139,0.08)' } }
            },
            { type: 'value', name: 'PE-TTM', position: 'right',
              nameTextStyle: { color: '#3b82f6', fontSize: 10 },
              axisLabel: { color: '#3b82f680', fontSize: 9 },
              splitLine: { show: false }
            },
            hasM1 ? {
                type: 'value', name: 'M1%', nameTextStyle: { color: '#a78bfa', fontSize: 10 },
                position: 'right', offset: 40,
                axisLabel: { color: '#a78bfa', fontSize: 9, formatter: '{value}%' },
                splitLine: { show: false }
            } : null
        ].filter(Boolean),
        series: [
            {
                name: 'ERP', type: 'line', data: chart.erp, yAxisIndex: 0,
                lineStyle: { color: '#f59e0b', width: 2.5, shadowColor: 'rgba(245,158,11,0.2)', shadowBlur: 4 },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none', z: 10,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(245,158,11,0.12)' },
                            { offset: 1, color: 'rgba(245,158,11,0)' }
                        ]
                    }
                },
                markLine: {
                    silent: true, symbol: 'none', lineStyle: { type: 'dashed', width: 1 },
                    data: [
                        { yAxis: stats.mean, label: { formatter: '均值 ' + stats.mean + '%', color: '#94a3b8', fontSize: 9 }, lineStyle: { color: '#64748b' } },
                        { yAxis: stats.overweight_line, label: { formatter: '超配 ' + stats.overweight_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98166' } },
                        { yAxis: stats.underweight_line, label: { formatter: '低配 ' + stats.underweight_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444466' } },
                        { yAxis: stats.strong_buy_line, label: { formatter: '强买 ' + stats.strong_buy_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98140', type: 'dotted' } },
                        { yAxis: stats.danger_line, label: { formatter: '危险 ' + stats.danger_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444440', type: 'dotted' } }
                    ]
                },
                markArea: { silent: true, data: markAreaData },
                markPoint: {
                    data: markPointData,
                    animation: true, animationDuration: 600
                }
            },
            {
                name: 'PE-TTM', type: 'line', data: chart.pe_ttm, yAxisIndex: 1,
                lineStyle: { color: '#3b82f6', width: 1.5, type: 'dashed' },
                itemStyle: { color: '#3b82f6' }, symbol: 'none'
            },
            {
                name: '10Y国债', type: 'line', data: chart.yield_10y, yAxisIndex: 0,
                lineStyle: { color: '#ef4444', width: 1, type: 'dotted' },
                itemStyle: { color: '#ef4444' }, symbol: 'none'
            },
            hasM1 ? {
                name: 'M1同比', type: 'line', data: chart.m1_yoy, yAxisIndex: 2,
                lineStyle: { color: '#a78bfa', width: 2, type: 'solid' },
                itemStyle: { color: '#a78bfa' },
                symbol: 'none', smooth: true,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [{offset:0,color:'rgba(167,139,250,0.10)'},{offset:1,color:'rgba(167,139,250,0)'}]
                    }
                }
            } : null
        ].filter(Boolean)
    });
}

/**
 * V3.0: ERP 图表 KPI 统计卡片 (Dashboard 版)
 */
function renderERPDashboardKPIs(stats, signalData) {
    const container = document.getElementById('erp-chart-kpis');
    if (!container) return;
    const snap = (signalData && signalData.current_snapshot) || {};
    const pct = snap.erp_percentile || '--';
    const deviation = stats.current_vs_mean;
    const devColor = deviation > 0 ? '#10b981' : (deviation < -5 ? '#ef4444' : '#f59e0b');
    const devSign = deviation > 0 ? '+' : '';

    container.innerHTML = [
        { label: '当前 ERP', value: (stats.current || '--') + '%', color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
        { label: '均值偏离', value: devSign + deviation + '%', color: devColor },
        { label: '近4年分位', value: pct + '%', color: pct >= 70 ? '#10b981' : (pct <= 30 ? '#ef4444' : '#94a3b8') },
        { label: '超配区占比', value: (stats.buy_zone_pct || '--') + '%', color: '#10b981' },
    ].map(k => `<div style="flex:1;background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 12px;text-align:center;">
        <div style="font-size:0.65rem;color:#64748b;margin-bottom:3px;">${k.label}</div>
        <div style="font-size:1.1rem;font-weight:800;color:${k.color};">${k.value}</div>
    </div>`).join('');
}

// ERP 图表 + AIAE 仪表盘 — resize 由 AC (alphacore_utils.js) 统一管理
let _aiaeThermGauge = null;

// ====================================================================
//  AIAE 温度计 · 量化总览精简渲染引擎
// ====================================================================

function renderAIAEThermometer(d) {
    if (!d) return;
    // 使用全局 el() 工具函数

    // ── 仪表盘大字 ──
    const v1 = d.aiae_v1 || 0;
    if (el('aiae-thermo-val')) el('aiae-thermo-val').textContent = v1.toFixed(1);

    // ── ECharts 小仪表盘 ──
    try {
        const gaugeEl = el('aiae-thermo-gauge');
        if (gaugeEl && typeof echarts !== 'undefined') {
            if (_aiaeThermGauge) _aiaeThermGauge = AC.disposeChart(_aiaeThermGauge);
            _aiaeThermGauge = AC.registerChart(echarts.init(gaugeEl));
            const rc = d.regime_color || '#eab308';
            _aiaeThermGauge.setOption({
                series: [{
                    type: 'gauge',
                    startAngle: 200,
                    endAngle: -20,
                    min: 0,
                    max: 50,
                    pointer: {
                        show: true, length: '55%', width: 3.5,
                        itemStyle: { color: rc, shadowColor: rc, shadowBlur: 6 },
                        icon: 'triangle'
                    },
                    anchor: {
                        show: true, size: 8,
                        itemStyle: { color: '#0f172a', borderColor: rc, borderWidth: 2 }
                    },
                    axisLine: {
                        lineStyle: {
                            width: 12,
                            color: [
                                [0.24, '#10b981'], [0.32, '#3b82f6'],
                                [0.48, '#eab308'], [0.64, '#f97316'], [1, '#ef4444']
                            ]
                        }
                    },
                    axisTick: { length: 6, distance: -12, lineStyle: { color: 'auto', width: 1 } },
                    splitLine: { length: 10, distance: -12, lineStyle: { color: 'auto', width: 1.5 } },
                    splitNumber: 5,
                    axisLabel: {
                        distance: -30, color: '#64748b', fontSize: 8,
                        formatter: function(val) {
                            var m = {0:'0',10:'10',20:'20',30:'30',40:'40',50:'50'};
                            return m[val] || '';
                        }
                    },
                    detail: { show: false },
                    data: [{ value: Math.min(Math.max(v1, 0), 50) }],
                    animationDuration: 1000,
                    animationEasingUpdate: 'cubicOut'
                }]
            });
        }
    } catch(e) { console.warn('[AIAE Thermo] gauge skip:', e); }

    // ── 档位徽章 ──
    const regimeEl = el('aiae-thermo-regime');
    if (regimeEl) {
        regimeEl.textContent = (d.regime_emoji || '🟡') + ' ' + (d.regime_cn || '中性均衡');
        regimeEl.style.color = d.regime_color || '#eab308';
        regimeEl.style.borderColor = (d.regime_color || '#eab308') + '66';
        regimeEl.style.background = (d.regime_color || '#eab308') + '18';
    }

    // ── 月环比斜率 ──
    const slopeEl = el('aiae-thermo-slope');
    if (slopeEl) {
        const slope = d.slope || 0;
        const dir = d.slope_direction || 'flat';
        const arrow = dir === 'rising' ? '↗' : (dir === 'falling' ? '↘' : '→');
        slopeEl.textContent = '月环比: ' + arrow + ' ' + (slope > 0 ? '+' : '') + slope;
        slopeEl.style.color = dir === 'rising' ? '#f97316' : (dir === 'falling' ? '#10b981' : '#94a3b8');
    }

    // ── 五档高亮 ──
    const tiers = document.querySelectorAll('#aiae-thermo-tiers .at-tier');
    tiers.forEach(t => {
        const tier = parseInt(t.dataset.tier);
        t.classList.toggle('active', tier === d.regime);
    });

    // ── Cap 仓位 ──
    const cap = d.cap || 0;
    if (el('aiae-thermo-cap')) el('aiae-thermo-cap').textContent = cap + '%';
    if (el('aiae-thermo-cap-bar')) el('aiae-thermo-cap-bar').style.width = cap + '%';

    // ── 三大预警 ──
    // 融资热度
    const mh = d.margin_heat || 0;
    if (el('at-warn-margin')) {
        el('at-warn-margin').textContent = mh + '%';
        el('at-warn-margin').style.color = mh > 3.5 ? '#ef4444' : mh > 2.5 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-margin-bar')) {
        el('at-warn-margin-bar').style.width = Math.min(mh / 5 * 100, 100) + '%';
        el('at-warn-margin-bar').style.background = mh > 3.5 ? '#ef4444' : mh > 2.5 ? '#f59e0b' : '#10b981';
    }
    // 月斜率
    const absSlope = Math.abs(d.slope || 0);
    if (el('at-warn-slope')) {
        el('at-warn-slope').textContent = (d.slope > 0 ? '+' : '') + (d.slope || 0);
        el('at-warn-slope').style.color = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-slope-bar')) {
        el('at-warn-slope-bar').style.width = Math.min(absSlope / 3 * 100, 100) + '%';
        el('at-warn-slope-bar').style.background = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981';
    }
    // 基金仓位
    const fp = d.fund_position || 0;
    if (el('at-warn-fund')) {
        el('at-warn-fund').textContent = fp + '%';
        el('at-warn-fund').style.color = fp > 90 ? '#ef4444' : fp > 85 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-fund-bar')) {
        el('at-warn-fund-bar').style.width = Math.min(fp / 100 * 100, 100) + '%';
        el('at-warn-fund-bar').style.background = fp > 90 ? '#ef4444' : fp > 85 ? '#f59e0b' : '#10b981';
    }

    // ── 数据来源 ──
    if (el('at-src-simple')) el('at-src-simple').textContent = 'AIAE_简: ' + (d.aiae_simple || 0) + '%';
    if (el('at-src-erp')) el('at-src-erp').textContent = 'ERP: ' + (d.erp_value || 0) + '%';

    // ── 操作指引 (按档位) ──
    const actionMap = {
        1: '🟢 Ⅰ级恐慌 · 分3批满仓进攻，越跌越买。优先宽基ETF (300/50/500)',
        2: '🔵 Ⅱ级低配 · 标准建仓区，按节奏买入。不因波动减仓，坚定持有',
        3: '🟡 Ⅲ级中性 · 维持均衡仓位，有纪律持有。到目标价就卖，不贪婪',
        4: '🟠 Ⅳ级偏热 · 禁止新开仓。每周减5%总仓位，优先清退高波动标的',
        5: '🔴 Ⅴ级过热 · 绝对禁止买入！3天内完成清仓，无例外执行'
    };
    if (el('aiae-thermo-action-text')) {
        el('aiae-thermo-action-text').textContent = actionMap[d.regime] || actionMap[3];
    }
}

// ═══════════════════════════════════════════════════
// Visual Excellence V2.0: 快速行动条数据绑定
// ═══════════════════════════════════════════════════

// ── 快速决策行动条 数据绑定 ──
// 挂钩到已有 renderPositionHub 数据流 (零额外 API 调用)
(function() {
    const _origRenderHub = window.renderPositionHub;
    if (!_origRenderHub) return;

    window.renderPositionHub = function(temp) {
        // 先执行原始渲染逻辑
        _origRenderHub(temp);

        // 同步更新快速行动条
        const qaMindset = document.getElementById('qa-mindset');
        const qaPos = document.getElementById('qa-pos');
        const qaConfFill = document.getElementById('qa-conf-fill');
        const qaConfVal = document.getElementById('qa-conf-val');
        const qaStrip = document.getElementById('quick-action-strip');

        if (!qaStrip) return; // 非主页则跳过

        // 提取仓位百分比 (复用 Hub 逻辑)
        let posPercent = 30;
        if (temp.strategy_positions && temp.strategy_positions.total != null) {
            posPercent = temp.strategy_positions.total;
        } else {
            const posMatch = (temp.advice || '').match(/(\d+)%/);
            if (posMatch) posPercent = parseInt(posMatch[1], 10);
        }

        const tier = temp.advice_tier || 3;

        if (qaMindset) {
            qaMindset.textContent = temp.mindset || '侦测中...';
            // 颜色联动
            const tierBorderColors = {1:'#10b981',2:'#3b82f6',3:'#f59e0b',4:'#f97316',5:'#ef4444'};
            const tierBgColors = {1:'rgba(16,185,129,0.12)',2:'rgba(59,130,246,0.12)',3:'rgba(245,158,11,0.12)',4:'rgba(249,115,22,0.12)',5:'rgba(239,68,68,0.12)'};
            qaMindset.style.borderLeftColor = tierBorderColors[tier] || '#f59e0b';
            qaMindset.style.background = tierBgColors[tier] || 'rgba(245,158,11,0.12)';
        }

        if (qaPos) {
            qaPos.textContent = posPercent + '%';
        }

        if (temp.hub_confidence !== undefined) {
            if (qaConfFill) qaConfFill.style.width = `${temp.hub_confidence}%`;
            if (qaConfVal) qaConfVal.textContent = Math.round(temp.hub_confidence);
        }

        // 行动条边框色跟随档位
        if (qaStrip) {
            const stripBorderColors = {1:'rgba(16,185,129,0.3)',2:'rgba(59,130,246,0.3)',3:'rgba(245,158,11,0.2)',4:'rgba(249,115,22,0.3)',5:'rgba(239,68,68,0.3)'};
            qaStrip.style.borderColor = stripBorderColors[tier] || 'rgba(245,158,11,0.2)';
        }
    };
})();

// ═══════════════════════════════════════════════════════════
//  辅助决策模块 · Decision Support Module
//  从 /api/v1/decision/hub + /alerts 拉取数据
// ═══════════════════════════════════════════════════════════

let _decisionHubData = null; // 全局缓存，供 renderPositionHub 共振使用

async function fetchDecisionSummary() {
    try {
        const resp = await fetch('/api/v1/decision/hub');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const hub = await resp.json();
        _decisionHubData = hub;
        renderDecisionSummary(hub);
        renderDecisionSupport(hub);
    } catch (err) {
        console.warn('[Decision Support] 加载降级:', err.message);
        renderDecisionSummaryFallback();
    }
}

function renderDecisionSummary(hub) {
    const jcs = hub.jcs || {};
    const score = jcs.score || 0;
    const level = jcs.level || 'medium';
    const conflicts = hub.conflicts || {};
    const conflictList = conflicts.conflicts || [];
    const actionableConflicts = conflictList.filter(c => c.severity === 'high' || c.severity === 'medium');

    // ── JCS 环形分数 ──
    const jcsFill = el('qa-jcs-fill');
    const jcsScore = el('qa-jcs-score');
    const CIRC = 2 * Math.PI * 18; // r=18
    if (jcsFill) {
        const pct = Math.min(100, Math.max(0, score));
        const dashLen = (pct / 100) * CIRC;
        jcsFill.setAttribute('stroke-dasharray', `${dashLen} ${CIRC - dashLen}`);
        const strokeColor = score >= 70 ? '#10b981' : score >= 40 ? '#f59e0b' : '#ef4444';
        jcsFill.style.stroke = strokeColor;
    }
    if (jcsScore) jcsScore.textContent = Math.round(score);

    // ── 主结论 (直接消费后端 action_plan) ──
    const actionLabel = el('qa-action-label');
    const reasoning = el('qa-reasoning');
    const snapshot = hub.snapshot || {};
    const plan = hub.action_plan || {};

    // 优先使用后端精算的 action_label，fallback 到 regime 映射
    if (actionLabel) {
        if (plan.action_label) {
            const planIcon = plan.action_icon || '⚖️';
            actionLabel.textContent = `${planIcon} ${plan.action_label}`;
        } else {
            const actionMap = {1:'🟢 满配进攻',2:'🔵 标准建仓',3:'🟡 均衡持有',4:'🟠 系统减仓',5:'🔴 清仓防守'};
            actionLabel.textContent = actionMap[snapshot.aiae_regime || 3] || actionMap[3];
        }
    }

    // 构造 reasoning: 优先用后端 reasoning，fallback 拼接
    if (reasoning) {
        if (plan.reasoning) {
            reasoning.textContent = plan.reasoning;
        } else {
            const parts = [];
            if (jcs.label) parts.push(`JCS ${jcs.label}`);
            if (snapshot.erp_val != null) parts.push(`ERP ${snapshot.erp_val}%`);
            if (snapshot.vix_val != null) parts.push(`VIX ${snapshot.vix_val}`);
            reasoning.textContent = parts.join(' · ') || '数据同步中...';
        }
    }

    // ── 矛盾徽章 ──
    const conflictBadge = el('qa-conflict-badge');
    const conflictCount = el('qa-conflict-count');
    if (actionableConflicts.length > 0) {
        if (conflictBadge) conflictBadge.style.display = 'flex';
        if (conflictCount) conflictCount.textContent = actionableConflicts.length;
    } else {
        if (conflictBadge) conflictBadge.style.display = 'none';
    }
}

function renderDecisionSummaryFallback() {
    const actionLabel = el('qa-action-label');
    const reasoning = el('qa-reasoning');
    if (actionLabel) actionLabel.textContent = '决策中枢离线';
    if (reasoning) reasoning.textContent = '启动 main.py 后自动连接';
}

function renderDecisionSupport(hub) {
    const snapshot = hub.snapshot || {};
    const jcs = hub.jcs || {};
    const conflicts = hub.conflicts || {};
    const conflictList = conflicts.conflicts || [];
    const plan = hub.action_plan || {};

    // ═══════ 左栏: 仓位缺口 (P0修复: 直接读后端 action_plan) ═══════
    const currentPos = plan.current_position != null && plan.current_position >= 0
        ? plan.current_position : null;
    const targetPos = plan.position_target != null
        ? plan.position_target : (snapshot.suggested_position || 55);
    const gap = plan.position_gap != null
        ? plan.position_gap : (currentPos != null ? targetPos - currentPos : null);

    if (el('ds-gap-current')) {
        el('ds-gap-current').textContent = currentPos != null ? currentPos.toFixed(1) + '%' : '--';
    }
    if (el('ds-gap-target')) {
        el('ds-gap-target').textContent = targetPos + '%';
    }

    const deltaEl = el('ds-gap-delta');
    if (deltaEl && gap != null) {
        const sign = gap > 0 ? '+' : '';
        deltaEl.textContent = sign + gap.toFixed(1) + 'pp';
        deltaEl.className = 'ds-gap-delta ' + (gap > 2 ? 'gap-positive' : gap < -2 ? 'gap-negative' : 'gap-zero');
    } else if (deltaEl) {
        deltaEl.textContent = '--';
        deltaEl.className = 'ds-gap-delta gap-zero';
    }

    const noteEl = el('ds-gap-note');
    if (noteEl && gap != null) {
        if (Math.abs(gap) <= 2) noteEl.textContent = '✅ 仓位接近目标，无需调整';
        else if (gap > 0) noteEl.textContent = `📈 可加仓 ${gap.toFixed(1)}pp，建议分 2-3 批执行`;
        else noteEl.textContent = `📉 需减仓 ${Math.abs(gap).toFixed(1)}pp，优先清退高波动标的`;
    } else if (noteEl) {
        noteEl.textContent = '仓位数据不可用';
    }

    // ECharts 半圆仪表
    const ringEl = el('ds-gap-ring');
    const displayCurrent = currentPos != null ? currentPos : (snapshot.suggested_position || 55);
    if (ringEl && typeof echarts !== 'undefined') {
        const gapChart = AC.registerChart(echarts.init(ringEl));
        const gapColor = gap != null ? (gap > 2 ? '#10b981' : gap < -2 ? '#ef4444' : '#f59e0b') : '#64748b';
        const safeTarget = Math.min(targetPos, 100);
        gapChart.setOption({
            series: [{
                type: 'gauge', startAngle: 200, endAngle: -20,
                min: 0, max: 100,
                pointer: {
                    show: true, length: '55%', width: 3,
                    itemStyle: { color: gapColor, shadowColor: gapColor, shadowBlur: 4 },
                    icon: 'triangle'
                },
                anchor: { show: true, size: 6, itemStyle: { color: '#0f172a', borderColor: gapColor, borderWidth: 2 } },
                axisLine: {
                    lineStyle: {
                        width: 10,
                        color: [[displayCurrent/100, '#3b82f6'], [safeTarget/100, 'rgba(255,255,255,0.06)'], [1, 'rgba(255,255,255,0.03)']]
                    }
                },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: { show: false },
                detail: { show: false },
                data: [{ value: displayCurrent }],
                animationDuration: 1000
            }]
        });
    }

    // ═══════ 中栏: 信号矛盾 (P1修复: 字段名 conflicts.conflicts) ═══════
    const actionableConflicts = conflictList.filter(c => c.severity === 'high' || c.severity === 'medium');
    const totalEl = el('ds-conflict-total');
    const summaryEl = el('ds-conflict-summary');
    const listEl = el('ds-conflict-list');

    if (totalEl) {
        const count = actionableConflicts.length;
        totalEl.textContent = count === 0 ? '✓ 0' : count;
        totalEl.className = 'ds-conflict-total ' + (
            count === 0 ? 'ct-clean' : count >= 2 ? 'ct-danger' : 'ct-warn'
        );
    }

    if (summaryEl) {
        summaryEl.textContent = conflicts.matrix_summary
            || (actionableConflicts.length === 0
                ? '各引擎方向一致，信号共振'
                : `检测到 ${actionableConflicts.length} 条可操作矛盾信号`);
    }

    if (listEl) {
        if (actionableConflicts.length === 0) {
            listEl.innerHTML = '<div class="ds-conflict-clean">🟢 信号共振 · 无引擎冲突</div>';
        } else {
            listEl.innerHTML = actionableConflicts.map(c => {
                const sevClass = c.severity === 'high' ? 'sev-high' : 'sev-medium';
                // 从 desc 字段解析引擎对比 (后端格式: "AIAE偏热(减仓) × ERP看多(加仓)")
                let engineTags = '';
                const descMatch = (c.desc || '').match(/^(\S+?)[偏看处].*[×x]\s*(\S+?)[偏看处]/i);
                if (descMatch) {
                    engineTags = `
                        <div class="ds-conflict-engines">
                            <span class="ds-conflict-engine-tag">${descMatch[1]}</span>
                            <span class="ds-conflict-vs">×</span>
                            <span class="ds-conflict-engine-tag">${descMatch[2]}</span>
                        </div>`;
                }
                return `
                    <div class="ds-conflict-item ${sevClass}">
                        ${engineTags}
                        <div class="ds-conflict-desc">${c.desc || '--'}</div>
                        ${c.action ? `<div class="ds-conflict-action">→ ${c.action}</div>` : ''}
                    </div>`;
            }).join('');
        }
    }

    // ═══════ 右栏: 执行建议 (P0修复: 直接消费 action_plan) ═══════
    const heroEl = el('ds-action-hero');
    const iconEl = el('ds-action-icon');
    const textEl = el('ds-action-text');
    const directivesEl = el('ds-action-directives');
    const nextEl = el('ds-action-next');

    // 行动标签: 优先用后端 action_plan，fallback 到简单 3 档
    const actionIcon = plan.action_icon || '⚖️';
    const actionText = plan.action_label || '均衡持有';
    const confidence = plan.confidence || 'medium';
    const heroClassMap = { high: 'action-bullish', low: 'action-bearish', medium: 'action-neutral' };
    // 精细化: 基于 action_label 内容判断 hero 样式
    let heroClass = heroClassMap[confidence] || 'action-neutral';
    if (/加仓|进攻/.test(actionText)) heroClass = 'action-bullish';
    else if (/减仓|防守|清仓|暂停/.test(actionText)) heroClass = 'action-bearish';

    if (heroEl) heroEl.className = 'ds-action-hero ' + heroClass;
    if (iconEl) iconEl.textContent = actionIcon;
    if (textEl) textEl.textContent = actionText;

    // 指令列表: 消费 action_plan 的结构化字段
    if (directivesEl) {
        const items = [];
        // top_signals: 后端引擎级信号摘要
        const signals = plan.top_signals || [];
        signals.forEach(s => items.push({ icon: '📡', text: s }));
        // risk_note: 风控提示 (含仓位缺口分析)
        if (plan.risk_note) items.push({ icon: '🛡️', text: plan.risk_note });
        // ERP 估值状态
        if (items.length === 0 && snapshot.erp_val != null) {
            const erpAction = snapshot.erp_val >= 5 ? '估值吸引力高' : snapshot.erp_val <= 3 ? '估值偏贵' : '估值中性';
            items.push({ icon: '📊', text: `ERP ${snapshot.erp_val}% → ${erpAction}` });
        }
        // 矛盾提示
        if (actionableConflicts.length > 0) {
            items.push({ icon: '⚠️', text: `${actionableConflicts.length} 条矛盾未解，建议保守执行` });
        }

        directivesEl.innerHTML = items.slice(0, 4).map(d => `
            <div class="ds-directive-item">
                <span class="ds-directive-icon">${d.icon}</span>
                <span class="ds-directive-text">${d.text}</span>
            </div>`).join('');
    }

    // 下次检查: 用后端 next_check，fallback 到 SWR TTL
    if (nextEl) {
        if (plan.next_check) {
            nextEl.textContent = `📋 ${plan.next_check}`;
        } else {
            const now = new Date();
            const next = new Date(now.getTime() + 5 * 60 * 1000);
            nextEl.textContent = `下次同步: ${next.getHours()}:${String(next.getMinutes()).padStart(2, '0')}`;
        }
    }
}


// ═══════════════════════════════════════════════════════════
//  预警铃铛 · Alert Bell
// ═══════════════════════════════════════════════════════════

async function fetchAlertBell() {
    try {
        const resp = await fetch('/api/v1/decision/alerts?limit=5');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        renderAlertBell(json);
    } catch (err) {
        console.warn('[Alert Bell] 加载降级:', err.message);
    }
}

function renderAlertBell(data) {
    const badge = el('alert-bell-badge');
    const list = el('alert-bell-list');
    const unread = data.unread_count || 0;
    const alerts = data.alerts || [];

    if (badge) {
        if (unread > 0) {
            badge.style.display = 'flex';
            badge.textContent = unread > 9 ? '9+' : unread;
        } else {
            badge.style.display = 'none';
        }
    }

    if (list) {
        if (alerts.length === 0) {
            list.innerHTML = '<div class="abp-empty">🟢 暂无预警 · 信号正常</div>';
        } else {
            list.innerHTML = alerts.map(a => {
                const sevClass = a.severity === 'high' ? 'abp-sev-high' : a.severity === 'medium' ? 'abp-sev-medium' : 'abp-sev-low';
                const icon = a.severity === 'high' ? '🔴' : a.severity === 'medium' ? '🟡' : '🔵';
                const time = a.created_at ? new Date(a.created_at).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
                return `
                    <a href="./decision.html#alerts" class="abp-item ${sevClass}">
                        <span class="abp-item-icon">${icon}</span>
                        <div class="abp-item-body">
                            <div class="abp-item-title">${a.title || a.message || '--'}</div>
                            <div class="abp-item-meta">${a.source || ''} · ${time}</div>
                        </div>
                    </a>`;
            }).join('');
        }
    }
}


// ═══════════════════════════════════════════════════════════
//  V8.0 模块 D: 系统健康指示器 (System Health Indicator)
// ═══════════════════════════════════════════════════════════

function renderSystemHealth(marketData) {
    const dotEl = el('sys-health-dot');
    const labelEl = el('sys-health-label');
    if (!dotEl || !labelEl) return;

    // 从 dashboard-data 响应中提取置信度和降级信息
    const mc = marketData.macro_cards || {};
    const temp = mc.market_temp || {};
    const isFallback = marketData._meta_is_fallback || false;
    const isStale = marketData._meta_is_stale || false;
    const degradedModules = temp.degraded_modules || marketData.degraded_modules || [];
    const confidence = temp.temp_confidence || 'unknown';

    // 数据年龄计算
    const timestamp = marketData.timestamp || marketData._timestamp;
    let freshnessText = '--';
    let ageMinutes = 0;
    if (timestamp) {
        const dataTime = new Date(timestamp);
        ageMinutes = Math.floor((Date.now() - dataTime.getTime()) / 60000);
        if (ageMinutes < 1) freshnessText = '刚刚';
        else if (ageMinutes < 60) freshnessText = `${ageMinutes}分钟前`;
        else freshnessText = `${Math.floor(ageMinutes / 60)}小时前`;
    }

    // 健康状态判定
    let healthClass, healthLabel;
    if (isStale || ageMinutes > 120) {
        healthClass = 'health-error';
        healthLabel = '数据陈旧';
    } else if (isFallback || degradedModules.length >= 2 || confidence === 'low') {
        healthClass = 'health-warn';
        healthLabel = '部分降级';
    } else {
        healthClass = 'health-ok';
        healthLabel = '正常';
    }

    dotEl.className = `sys-health-dot ${healthClass}`;
    labelEl.textContent = healthLabel;

    // V2.0: Label 颜色 + 容器背景跟随状态
    const shLabelMap = {'health-ok': 'sh-ok', 'health-warn': 'sh-warn', 'health-error': 'sh-error'};
    labelEl.className = `sys-health-label ${shLabelMap[healthClass] || ''}`;

    const indicatorEl = el('sys-health-indicator');
    if (indicatorEl) {
        indicatorEl.classList.remove('shi-ok', 'shi-warn', 'shi-error');
        const shiMap = {'health-ok': 'shi-ok', 'health-warn': 'shi-warn', 'health-error': 'shi-error'};
        indicatorEl.classList.add(shiMap[healthClass] || '');
    }

    // 弹出面板详情
    const shpFreshness = el('shp-freshness');
    const shpConfidence = el('shp-confidence');
    const shpDegraded = el('shp-degraded');
    const shpBackend = el('shp-cache-backend');

    if (shpFreshness) {
        shpFreshness.textContent = freshnessText;
        shpFreshness.style.color = ageMinutes > 60 ? '#ef4444' : ageMinutes > 15 ? '#f59e0b' : '#10b981';
    }
    if (shpConfidence) {
        const confMap = { high: '🟢 高', medium: '🟡 中', low: '🔴 低' };
        shpConfidence.textContent = confMap[confidence] || '⚪ 未知';
    }
    if (shpDegraded) {
        shpDegraded.textContent = degradedModules.length > 0 ? degradedModules.join(', ') : '无';
        shpDegraded.style.color = degradedModules.length > 0 ? '#f59e0b' : '#10b981';
    }
    if (shpBackend) {
        shpBackend.textContent = marketData._cache_backend || 'Memory';
    }
}

// ═══════════════════════════════════════════════════════════
//  V8.0 模块 B: 全球市场脉搏 (Global Market Pulse)
// ═══════════════════════════════════════════════════════════

async function fetchAndRenderGlobalPulse() {
    const gridEl = el('gp-grid');
    const timeEl = el('gp-update-time');
    const advicePill = el('gp-advice-pill');
    if (!gridEl) return;

    try {
        const resp = await fetch('/api/v1/strategy/erp-global');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();

        if (json.status !== 'success' || !json.global_comparison) {
            throw new Error('数据格式异常');
        }

        const gc = json.global_comparison;
        const alloc = gc.allocation || {};
        const gp = gc.global_position || {};
        const CIRC = 2 * Math.PI * 15.9; // SVG ring circumference

        const regions = [
            { key: 'cn', flag: '🇨🇳', name: 'A股' },
            { key: 'us', flag: '🇺🇸', name: '美股' },
            { key: 'jp', flag: '🇯🇵', name: '日股' },
            { key: 'hk', flag: '🇭🇰', name: '港股' },
        ];

        regions.forEach(r => {
            const card = gridEl.querySelector(`.gp-card[data-region="${r.key}"]`);
            if (!card) return;
            const d = gc[r.key] || {};
            const score = d.score || 0;
            const erpVal = d.erp || 0;
            const allocPct = alloc[r.key] || 0;
            const sigColor = d.color || '#f59e0b';

            // 1. 移除骨架
            card.classList.remove('gp-skeleton');

            // 2. 多空分类
            let cardClass = 'gp-neutral';
            let sigClass = 'sig-neutral';
            if (score >= 60) { cardClass = 'gp-bull'; sigClass = 'sig-bull'; }
            else if (score <= 35) { cardClass = 'gp-bear'; sigClass = 'sig-bear'; }
            card.classList.remove('gp-bull', 'gp-bear', 'gp-neutral');
            card.classList.add(cardClass);

            // 3. ERP 主数值
            const erpEl = card.querySelector('.gp-erp-val');
            if (erpEl) erpEl.textContent = erpVal.toFixed(2);

            // 4. Score Ring (SVG)
            const ringFill = card.querySelector('.gp-ring-fill');
            const ringText = card.querySelector('.gp-ring-text');
            if (ringFill) {
                const pct = Math.min(100, Math.max(0, score));
                ringFill.setAttribute('stroke-dasharray', `${pct} ${100 - pct}`);
                ringFill.style.stroke = sigColor;
            }
            if (ringText) ringText.textContent = Math.round(score);

            // 5. PE / Yield
            const peEl = card.querySelector('[data-field="pe"]');
            const yieldEl = card.querySelector('[data-field="yield"]');
            if (peEl) peEl.textContent = (d.pe || 0).toFixed(1) + 'x';
            if (yieldEl) yieldEl.textContent = (d.yield || 0).toFixed(2) + '%';

            // 6. Signal Badge
            const sigBadge = card.querySelector('.gp-sig-badge');
            if (sigBadge) {
                sigBadge.textContent = `${d.emoji || ''} ${d.label || '--'}`;
                sigBadge.className = `gp-sig-badge ${sigClass}`;
            }

            // 7. Mini Allocation Bar
            const allocFillMini = card.querySelector('.gp-alloc-fill-mini');
            const allocPctEl = card.querySelector('.gp-alloc-pct');
            if (allocFillMini) {
                allocFillMini.style.width = `${allocPct}%`;
                allocFillMini.style.background = sigColor;
            }
            if (allocPctEl) allocPctEl.textContent = `${allocPct}%`;
        });

        // — Footer: Equity track —
        const equityFill = el('gp-equity-fill');
        const equityPct = el('gp-equity-pct');
        const allocText = el('gp-alloc-text');
        if (equityFill && gp.equity_pct != null) {
            equityFill.style.width = `${gp.equity_pct}%`;
            equityFill.style.background = `linear-gradient(90deg, ${gp.color || '#3b82f6'}, ${gp.color || '#10b981'}88)`;
        }
        if (equityPct) equityPct.textContent = `${gp.equity_pct || '--'}%`;
        if (allocText) allocText.textContent = gc.allocation_text || '--';

        // — Header advice pill —
        if (advicePill && gp.label) {
            advicePill.textContent = `${gp.emoji || ''} ${gp.label} ${gp.position || ''}`;
            advicePill.style.color = gp.color || 'var(--accent)';
            advicePill.style.borderColor = `${gp.color || 'var(--accent)'}33`;
            advicePill.style.background = `${gp.color || 'var(--accent)'}18`;
        }

        // — Update time —
        if (timeEl && json.updated_at) {
            const dt = new Date(json.updated_at);
            timeEl.textContent = `${dt.getHours()}:${String(dt.getMinutes()).padStart(2, '0')} 更新`;
        }

    } catch (err) {
        console.warn('[Global Pulse] 加载失败, 保留骨架:', err.message);
        if (timeEl) timeEl.textContent = '数据待同步';
    }
}

// ═══════════════════════════════════════════════════════════
//  V8.0 模块 A: NLP 情报流 (Intelligence Feed)
// ═══════════════════════════════════════════════════════════

async function fetchAndRenderIntelligenceFeed() {
    const cardsEl = el('intel-cards');
    const scanTimeEl = el('intel-scan-time');
    const emptyEl = el('intel-empty');
    const scanBtn = el('intel-scan-btn');
    if (!cardsEl) return;

    // — 手动扫描按钮 —
    if (scanBtn && !scanBtn._bound) {
        scanBtn._bound = true;
        scanBtn.addEventListener('click', async () => {
            scanBtn.classList.add('scanning');
            scanBtn.querySelector('.intel-scan-icon').textContent = '⏳';
            if (scanTimeEl) scanTimeEl.textContent = '扫描中…';
            try {
                const r = await fetch('/api/v1/intelligence/scan', { method: 'POST' });
                const j = await r.json();
                if (j.status === 'success') {
                    await fetchAndRenderIntelligenceFeed();
                } else {
                    if (scanTimeEl) scanTimeEl.textContent = '扫描失败';
                }
            } catch (e) {
                console.warn('[Intel] 扫描失败:', e.message);
                if (scanTimeEl) scanTimeEl.textContent = '网络异常';
            } finally {
                scanBtn.classList.remove('scanning');
                scanBtn.querySelector('.intel-scan-icon').textContent = '⚡';
            }
        });
    }

    try {
        const resp = await fetch('/api/v1/intelligence/latest');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();

        const data = json.data || json;
        const events = data.events || [];

        if (events.length === 0) {
            if (emptyEl) emptyEl.style.display = 'flex';
            if (scanTimeEl && data.scan_time) {
                const d = new Date(data.scan_time);
                scanTimeEl.textContent = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')} · 无事件`;
            } else if (scanTimeEl) {
                scanTimeEl.textContent = '待命';
            }
            return;
        }

        // 有事件: 渲染卡片
        if (emptyEl) emptyEl.style.display = 'none';

        const catMap = {
            macro: { label: '宏观', cls: 'cat-macro' },
            industry: { label: '行业', cls: 'cat-industry' },
            stock: { label: '个股', cls: 'cat-stock' },
            risk: { label: '风险', cls: 'cat-risk' },
        };

        const html = events.slice(0, 6).map(ev => {
            const cat = catMap[ev.category] || catMap.macro;
            const impact = Math.min(Math.max(Math.round(ev.impact_score || 0), 0), 10);
            const isCritical = impact >= 7;
            const impactPct = impact * 10;

            // Impact 颜色梯度
            let impactColor = '#10b981'; // green
            if (impact >= 7) impactColor = '#ef4444';
            else if (impact >= 5) impactColor = '#f59e0b';

            // ── V9.1: 智能操作信号推导 ──
            const text = (ev.title || '') + (ev.summary || '');
            const scenario = ev.scenario_hint || '';
            let actionSignal = null; // { icon, label, color, bgColor, borderColor }

            // 1. 风险警示 (最高优先级)
            if (ev.category === 'risk' || /暴雷|违约|制裁|黑天鹅|暴跌|跌停|熔断|退市|爆仓|危机/.test(text)) {
                actionSignal = { icon: '🚨', label: '风险警示', color: '#fca5a5', bgColor: 'rgba(239,68,68,0.12)', borderColor: 'rgba(239,68,68,0.25)' };
            }
            // 2. 利空回避
            else if (/减持|下滑|亏损|问询|澄清|负面|大跌|业绩不及|下调|警告/.test(text) && impact >= 5) {
                actionSignal = { icon: '📉', label: '利空回避', color: '#fb923c', bgColor: 'rgba(249,115,22,0.1)', borderColor: 'rgba(249,115,22,0.2)' };
            }
            // 3. 买入信号 (场景匹配)
            else if (/golden_cross|erp_extreme/.test(scenario)) {
                actionSignal = { icon: '📈', label: '买入信号', color: '#34d399', bgColor: 'rgba(16,185,129,0.12)', borderColor: 'rgba(16,185,129,0.25)' };
            }
            // 4. 利好关注
            else if (/增持|回购|突破|利好|大涨|涨停|分红|创新高|超预期/.test(text)) {
                actionSignal = { icon: '🟢', label: '利好关注', color: '#6ee7b7', bgColor: 'rgba(16,185,129,0.08)', borderColor: 'rgba(16,185,129,0.15)' };
            }
            // 5. 宏观提示
            else if (ev.category === 'macro' && impact >= 6) {
                actionSignal = { icon: '📊', label: '宏观关注', color: '#93c5fd', bgColor: 'rgba(59,130,246,0.08)', borderColor: 'rgba(59,130,246,0.15)' };
            }
            // 6. 行业轮动
            else if (ev.category === 'industry' && /布局|转型|政策|补贴|扶持/.test(text)) {
                actionSignal = { icon: '🔄', label: '行业轮动', color: '#c4b5fd', bgColor: 'rgba(139,92,246,0.08)', borderColor: 'rgba(139,92,246,0.15)' };
            }

            const signalHtml = actionSignal
                ? `<div class="intel-action-signal" style="background:${actionSignal.bgColor}; border-color:${actionSignal.borderColor}; color:${actionSignal.color};">
                       <span class="intel-signal-icon">${actionSignal.icon}</span>
                       <span class="intel-signal-label">${actionSignal.label}</span>
                   </div>`
                : '';

            // 受影响资产标签
            const assets = (ev.affected_assets || []).slice(0, 3);
            const assetHtml = assets.length > 0
                ? `<div class="intel-assets">${assets.map(a => `<span class="intel-asset-tag">${a}</span>`).join('')}</div>`
                : '';

            return `<div class="intel-card ${isCritical ? 'intel-critical' : ''} ${cat.cls}">
                <div class="intel-card-header">
                    <span class="intel-category ${cat.cls}">${cat.label}</span>
                    ${signalHtml}
                    <div class="intel-impact-bar">
                        <div class="intel-impact-track"><div class="intel-impact-fill" style="width:${impactPct}%;background:${impactColor}"></div></div>
                        <span class="intel-impact-val" style="color:${impactColor}">${impact}</span>
                    </div>
                </div>
                <div class="intel-title">${ev.title || '--'}</div>
                <div class="intel-summary">${ev.summary || ''}</div>
                ${assetHtml}
            </div>`;
        }).join('');

        cardsEl.innerHTML = html;

        if (scanTimeEl && data.scan_time) {
            const d = new Date(data.scan_time);
            scanTimeEl.textContent = `${events.length}条 · ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
        }

    } catch (err) {
        console.warn('[Intelligence Feed] 加载失败:', err.message);
        if (scanTimeEl) scanTimeEl.textContent = '离线';
    }
}

// ═══════════════════════════════════════════════════════════
//  V8.0 模块 C: AIAE 历史趋势迷你图 (Sparkline)
// ═══════════════════════════════════════════════════════════

let _aiaeSparklineChart = null;

function renderAIAESparkline(history) {
    const dom = el('aiae-sparkline-chart');
    if (!dom || typeof echarts === 'undefined') return;
    if (!history || history.length < 2) return;

    if (_aiaeSparklineChart) _aiaeSparklineChart = AC.disposeChart(_aiaeSparklineChart);
    _aiaeSparklineChart = AC.registerChart(echarts.init(dom));

    const dates = history.map(h => h.date || h.month || '');
    const values = history.map(h => h.aiae_v1 || h.value || 0);

    _aiaeSparklineChart.setOption({
        grid: { top: 6, bottom: 6, left: 4, right: 4 },
        xAxis: { type: 'category', data: dates, show: false, boundaryGap: false },
        yAxis: {
            type: 'value', show: false,
            min: 0, max: 50,
        },
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: '#334155',
            textStyle: { fontSize: 10, color: '#e2e8f0' },
            formatter: function(params) {
                if (!params[0]) return '';
                return `<div style="font-size:0.68rem;color:#64748b">${params[0].name}</div><div style="font-weight:700">AIAE ${params[0].value}%</div>`;
            }
        },
        series: [{
            type: 'line',
            data: values,
            symbol: 'none',
            lineStyle: { color: '#eab308', width: 2 },
            areaStyle: {
                color: {
                    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: 'rgba(234,179,8,0.20)' },
                        { offset: 1, color: 'rgba(234,179,8,0)' }
                    ]
                }
            },
            markArea: {
                silent: true,
                data: [
                    [{ yAxis: 0, itemStyle: { color: 'rgba(16,185,129,0.06)' } }, { yAxis: 12.5 }],
                    [{ yAxis: 12.5, itemStyle: { color: 'rgba(59,130,246,0.04)' } }, { yAxis: 17 }],
                    [{ yAxis: 17, itemStyle: { color: 'transparent' } }, { yAxis: 23 }],
                    [{ yAxis: 23, itemStyle: { color: 'rgba(249,115,22,0.04)' } }, { yAxis: 30 }],
                    [{ yAxis: 30, itemStyle: { color: 'rgba(239,68,68,0.06)' } }, { yAxis: 50 }],
                ]
            },
            markLine: {
                silent: true, symbol: 'none',
                lineStyle: { type: 'dotted', width: 0.5, color: 'rgba(255,255,255,0.1)' },
                data: [
                    { yAxis: 12.5 }, { yAxis: 17 }, { yAxis: 23 }, { yAxis: 30 }
                ],
                label: { show: false }
            }
        }]
    });
}

// ── 注入 AIAE Sparkline 到 AIAE 温度计渲染流 ──
(function() {
    const _origRenderThermo = window.renderAIAEThermometer;
    if (!_origRenderThermo) return;

    window.renderAIAEThermometer = function(d) {
        _origRenderThermo(d);

        // 尝试从 AIAE 报告中获取历史数据
        if (d && d.history && d.history.length >= 2) {
            renderAIAESparkline(d.history);
        } else {
            // 尝试异步获取
            _fetchAIAEHistory();
        }
    };
})();

let _aiaeHistoryFetched = false;

async function _fetchAIAEHistory() {
    if (_aiaeHistoryFetched) return;
    _aiaeHistoryFetched = true;

    try {
        const resp = await fetch('/api/v1/strategy/erp-timing');
        if (!resp.ok) return;
        const json = await resp.json();

        // 从 AIAE report 获取历史 (尝试多种路径)
        let history = null;
        if (json.data && json.data.aiae_history) {
            history = json.data.aiae_history;
        }

        // 如果没有专门的 AIAE 历史, 用 ERP 数据构造简化趋势
        if (!history && json.data && json.data.chart && json.data.chart.erp) {
            const erp = json.data.chart.erp;
            const dates = json.data.chart.dates;
            if (erp && dates && erp.length > 12) {
                // 取最后 12 个月的月末数据
                history = [];
                const step = Math.floor(erp.length / 12);
                for (let i = 0; i < 12; i++) {
                    const idx = Math.min(erp.length - 1, (i + 1) * step);
                    if (erp[idx] != null) {
                        history.push({ date: dates[idx], value: erp[idx] });
                    }
                }
            }
        }

        if (history && history.length >= 2) {
            renderAIAESparkline(history);
        }
    } catch (e) {
        console.warn('[AIAE Sparkline] 历史数据获取失败:', e.message);
    }
}

