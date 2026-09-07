// ══════════════════════════════════════════
// AlphaCore · Dashboard Orchestrator (V28.0)
// O3 模块化: 本文件仅负责编排
// 依赖: ui_utils.js, renderers.js, data_fetch.js
// ══════════════════════════════════════════

function updateDashboard(marketData) {
    if (marketData.macro_cards) {
        // 1. 更新顶部卡片数值
        if (marketData.macro_cards.vix) {
            updateCardUI('card-vix', 'val-vix', 'trend-vix', marketData.macro_cards.vix);
            // V4.2 新增: VIX 风格描述与分位条
            const vix = marketData.macro_cards.vix;
            const vixRegimeEl = document.getElementById('val-vix-regime');
            if (vixRegimeEl && vix.regime) {
                vixRegimeEl.innerText = vix.regime;
                vixRegimeEl.className = `vix-regime-box ${vix.class}`;
            }
            if (document.getElementById('desc-vix')) document.getElementById('desc-vix').innerText = vix.desc || "接入实时全球避险情绪水温";
            const vixBar = document.getElementById('bar-vix-range');
            if (vix.available === false) {
                if (document.getElementById('val-vix-percentile')) document.getElementById('val-vix-percentile').innerText = 'Range: --';
                if (vixBar) vixBar.style.width = '0%';
            } else {
                if (document.getElementById('val-vix-percentile')) document.getElementById('val-vix-percentile').innerText = `Range: ${vix.percentile}%`;
                if (vixBar) vixBar.style.width = `${vix.percentile}%`;
            }
        }
        // V8.2: ERP 专用渲染管线 (替代通用 updateCardUI)
        if (marketData.macro_cards.erp) {
            renderErpCard(marketData.macro_cards.erp);
        }
        
        // V10.0: A+H 跨境流量专用渲染管线 (compact card)
        renderCapitalCard(marketData.macro_cards.capital_a, marketData.macro_cards.capital_h);

        // V9.0: 五策略信号矩阵 (专用渲染管线)
        renderSignalCard(marketData.macro_cards.signal);

        // V5.0: 全局 Regime 状态横幅
        if (marketData.macro_cards.regime_banner) {
            const rb = marketData.macro_cards.regime_banner;
            const banner = document.getElementById('regime-banner');
            const dot = document.getElementById('rb-dot');
            const regimeEl = document.getElementById('rb-regime');
            const tempEl = document.getElementById('rb-temp');
            const adviceEl = document.getElementById('rb-advice');
            const vixEl = document.getElementById('rb-vix');
            const capEl = document.getElementById('rb-capital');
            
            if (regimeEl) regimeEl.innerText = rb.regime || '—';
            if (tempEl) tempEl.innerText = `${rb.temp}°`;
            if (adviceEl) adviceEl.innerText = rb.advice || '—';
            if (vixEl) vixEl.innerText = `VIX ${rb.vix} ${rb.vix_label || ''}`;
            if (capEl) capEl.innerText = `资金 Z:${rb.z_capital > 0 ? '+' : ''}${rb.z_capital}`;
            
            // 状态颜色
            if (banner && dot) {
                let colorClass = 'rb-neutral';
                if (rb.temp > 65) colorClass = 'rb-bull';
                else if (rb.temp < 35) colorClass = 'rb-bear';
                banner.className = `regime-banner glass-panel ${colorClass}`;
                dot.className = `rb-dot ${colorClass}`;
            }
            
            // V7.0: AIAE 状态标签
            const aiaeEl = document.getElementById('rb-aiae');
            if (aiaeEl && rb.aiae_regime_cn) {
                aiaeEl.innerText = `🌡️ AIAE ${rb.aiae_regime_cn} Cap${rb.aiae_cap}%`;
                const ar = rb.aiae_regime || 3;
                aiaeEl.style.borderColor = ar <= 2 ? 'rgba(16,185,129,0.5)' : ar >= 4 ? 'rgba(239,68,68,0.5)' : 'rgba(245,158,11,0.5)';
            }
        }
    }
    
    // 3.5 AIAE 温度计渲染
    if (marketData.macro_cards && marketData.macro_cards.aiae_thermometer) {
        renderAIAEThermometer(marketData.macro_cards.aiae_thermometer);
    }

    // V8.0: 系统健康指示器 (模块 D)
    renderSystemHealth(marketData);

    // 4. V6.0 情绪与持仓枢纽渲染 (Sentiment & Position Hub)
    if (marketData.macro_cards && marketData.macro_cards.market_temp) {
        renderPositionHub(marketData.macro_cards.market_temp);
    }

    // 4.5 V2.0 明日交易计划渲染管线
    if (marketData.macro_cards && marketData.macro_cards.tomorrow_plan) {
        const plan = marketData.macro_cards.tomorrow_plan;
        const planCardEl = el('card-tomorrow-plan');
        const anchorPanelEl = el('plan-anchor-panel');
        const disclaimerEl = el('plan-disclaimer');
        const lockReasonLabels = {
            missing: 'AIAE 数据缺失',
            decision_locked: '质量或风控未通过',
            timestamp_missing_or_invalid: '时间戳无效',
            stale: 'AIAE 数据已过期',
            invalid_payload: 'AIAE 决策字段无效',
            unverifiable: 'AIAE 状态不可验证'
        };
        // 旧缓存中的 VIX 四档响应没有 primary_regime；前端同样必须 fail closed。
        const planLocked = plan.decision_locked === true || plan.mode === 'locked' || !plan.primary_regime;

        if (planLocked) {
            const lockLabel = lockReasonLabels[plan.lock_reason] || lockReasonLabels.unverifiable;
            const lockMessage = plan.lock_message || `${lockLabel}，停止生成交易指令`;
            if (planCardEl) planCardEl.classList.add('plan-locked');
            if (anchorPanelEl) anchorPanelEl.classList.add('plan-anchor-locked');

            const badgeEl = el('tag-current-regime');
            if (badgeEl) {
                badgeEl.innerText = `🔒 决策锁定 · ${lockLabel}`;
                badgeEl.className = 'regime-badge regime-badge-locked';
                badgeEl.style.borderColor = 'rgba(239,68,68,0.5)';
                badgeEl.style.color = '#f87171';
            }

            if (el('plan-anchor-tier')) el('plan-anchor-tier').innerText = '🔒';
            if (el('plan-anchor-value')) {
                el('plan-anchor-value').innerText = '--';
                el('plan-anchor-value').style.color = '#94a3b8';
            }
            if (el('plan-anchor-cap-val')) el('plan-anchor-cap-val').innerText = '--%';
            if (el('plan-anchor-cap-bar')) el('plan-anchor-cap-bar').style.width = '0%';
            if (el('plan-anchor-erp')) {
                el('plan-anchor-erp').innerText = 'ERP --';
                el('plan-anchor-erp').className = 'plan-anchor-erp';
            }
            if (el('plan-anchor-slope')) el('plan-anchor-slope').innerText = '斜率 --';
            ['plan-risk-margin', 'plan-risk-slope', 'plan-risk-fund'].forEach(id => {
                const riskEl = el(id);
                if (riskEl) {
                    riskEl.innerText = '--';
                    riskEl.className = 'plan-risk-val';
                }
            });

            const matrixEl = el('matrix-content-v2');
            if (matrixEl) {
                matrixEl.replaceChildren();
                const lockedState = document.createElement('div');
                lockedState.className = 'matrix-locked-state';
                const icon = document.createElement('span');
                icon.className = 'matrix-locked-icon';
                icon.textContent = '🔒';
                const text = document.createElement('span');
                text.textContent = '五档矩阵已停用：AIAE 主轴尚未通过状态、质量与新鲜度校验';
                lockedState.append(icon, text);
                matrixEl.appendChild(lockedState);
            }

            const directivesEl = el('plan-directives');
            if (directivesEl) {
                directivesEl.replaceChildren();
                const directive = document.createElement('div');
                directive.className = 'plan-directive priority-risk risk-critical';
                const icon = document.createElement('span');
                icon.className = 'plan-directive-icon';
                icon.textContent = '🔒';
                const text = document.createElement('span');
                text.className = 'plan-directive-text';
                text.textContent = lockMessage;
                directive.append(icon, text);
                directivesEl.appendChild(directive);
            }

            const scenarioEl = el('plan-scenarios-v2');
            if (scenarioEl) {
                scenarioEl.replaceChildren();
                const status = document.createElement('div');
                status.className = 'scenario-tag-v2 type-locked';
                status.textContent = '⏸ 待 AIAE 数据恢复并通过校验后自动解锁';
                scenarioEl.appendChild(status);
            }
            if (disclaimerEl) disclaimerEl.innerText = 'AlphaCore V7.0 · 决策锁定期间不输出仓位与交易建议';
        } else if (plan.primary_regime) {
            // === V2.0 新版渲染 ===
            const pr = plan.primary_regime;
            const vd = plan.validators || {};
            const rp = plan.risk_panel || {};
            if (planCardEl) planCardEl.classList.remove('plan-locked');
            if (anchorPanelEl) anchorPanelEl.classList.remove('plan-anchor-locked');
            if (disclaimerEl) disclaimerEl.innerText = 'AlphaCore V7.0 · AIAE五档 × ERP双维 × VIX风控 Protocol';

            // 1. Header Badge
            const badgeEl = el('tag-current-regime');
            if (badgeEl) {
                badgeEl.innerText = `${pr.emoji} ${pr.cn} Cap${pr.cap}%`;
                badgeEl.className = 'regime-badge';
                badgeEl.style.borderColor = pr.tier <= 2 ? 'rgba(16,185,129,0.4)' : pr.tier >= 4 ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.4)';
                badgeEl.style.color = pr.tier <= 2 ? '#10b981' : pr.tier >= 4 ? '#ef4444' : '#f59e0b';
            }

            // 2. 左侧决策锚面板
            if (el('plan-anchor-tier')) el('plan-anchor-tier').innerText = pr.emoji;
            if (el('plan-anchor-value')) {
                const aiaeValue = Number(pr.aiae_v1);
                el('plan-anchor-value').innerText = Number.isFinite(aiaeValue) ? aiaeValue.toFixed(1) : '--';
                const colors = {1:'#10b981',2:'#3b82f6',3:'#eab308',4:'#f97316',5:'#ef4444'};
                el('plan-anchor-value').style.color = colors[pr.tier] || '#eab308';
            }
            if (el('plan-anchor-cap-val')) el('plan-anchor-cap-val').innerText = `${pr.cap}%`;
            if (el('plan-anchor-cap-bar')) el('plan-anchor-cap-bar').style.width = `${pr.cap}%`;

            // ERP pill
            const erpPill = el('plan-anchor-erp');
            if (erpPill && vd.erp) {
                erpPill.innerText = `ERP ${vd.erp.value}% ${vd.erp.label}`;
                erpPill.className = 'plan-anchor-erp' + (vd.erp.erp_tier === 'bull' ? ' erp-bull' : vd.erp.erp_tier === 'bear' ? ' erp-bear' : '');
            }

            // Slope
            if (el('plan-anchor-slope') && rp.slope) {
                const sl = rp.slope;
                const arrow = sl.direction === 'rising' ? '↗' : sl.direction === 'falling' ? '↘' : '→';
                el('plan-anchor-slope').innerText = `斜率 ${sl.value >= 0 ? '+' : ''}${sl.value} ${arrow}`;
            }

            // Risk indicators
            const setRisk = (elId, val, threshold, decimals) => {
                const e = el(elId);
                if (e) {
                    const valid = Number.isFinite(val);
                    e.innerText = valid ? val.toFixed(decimals ?? 1) + '%' : '--';
                    e.className = 'plan-risk-val' + (valid ? ' ' + (val > threshold ? 'risk-danger' : val > threshold * 0.7 ? 'risk-warning' : 'risk-safe') : '');
                }
            };
            setRisk('plan-risk-margin', rp.margin_heat?.value, rp.margin_heat?.threshold || 3.5, 1);
            setRisk('plan-risk-slope', Math.abs(rp.slope?.value || 0), rp.slope?.threshold || 1.5, 2);
            setRisk('plan-risk-fund', rp.fund_position?.value, rp.fund_position?.threshold || 90, 0);

            // 3. 五档矩阵
            const matrixEl = el('matrix-content-v2');
            if (matrixEl && plan.regime_matrix) {
                matrixEl.innerHTML = plan.regime_matrix.map(m => {
                    const tierLabel = ['','Ⅰ','Ⅱ','Ⅲ','Ⅳ','Ⅴ'][m.tier] || m.tier;
                    return `<div class="matrix-row-v2 tier-${m.tier} ${m.active ? 'tier-active' : ''}">
                        <div class="col-tier-v2">${m.emoji} ${tierLabel}</div>
                        <div class="col-range-v2">${m.range}</div>
                        <div class="col-action-v2">${m.action}</div>
                        <div class="col-cap-v2">${m.cap_range}</div>
                    </div>`;
                }).join('');
            }

            // 4. 核心指令 (3行)
            const directivesEl = el('plan-directives');
            if (directivesEl && plan.directives) {
                directivesEl.innerHTML = plan.directives.map(d => {
                    let extraClass = `priority-${d.priority}`;
                    if (d.priority === 'risk' && d.color === '#ef4444') extraClass += ' risk-critical';
                    else if (d.priority === 'risk' && d.color === '#f97316') extraClass += ' risk-active';
                    return `<div class="plan-directive ${extraClass}" style="border-left-color:${d.color}">
                        <span class="plan-directive-icon">${d.icon}</span>
                        <span class="plan-directive-text">${d.text}</span>
                    </div>`;
                }).join('');
            }

            // 5. 情景标签
            const scenarioEl = el('plan-scenarios-v2');
            if (scenarioEl && plan.scenarios) {
                const typeIcons = {aiae_upgrade: '📈', vix_alert: '🚨', erp_shift: '📉'};
                scenarioEl.innerHTML = plan.scenarios.map(s =>
                    `<div class="scenario-tag-v2 type-${s.type || ''}">${typeIcons[s.type] || '🔄'} ${s.condition}: ${s.action}</div>`
                ).join('');
            }
        }
    }


    // 5. 更新行业热力图 (Sector Heatmap)
    if (marketData.sector_heatmap) {
        renderHeatmap('heatmap-grid', marketData.sector_heatmap);
    }
    
    // 6. 买入/卖出区已下沉至策略详情页 (V8.0)
    
    // 2. 更新策略监控卡片 (5策略)
    if (marketData.strategy_status) {
        updateStrategyCard('mr', marketData.strategy_status.mr);
        updateStrategyCard('mom', marketData.strategy_status.mom);
        updateStrategyCard('div', marketData.strategy_status.div);
        updateStrategyCard('erp', marketData.strategy_status.erp);
        updateStrategyCard('aiae', marketData.strategy_status.aiae);
    }
}

