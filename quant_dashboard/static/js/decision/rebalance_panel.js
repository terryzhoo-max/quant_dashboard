/**
 * AlphaCore V5.0 · 策略配额偏离 + R1~R5 压力测试
 * decision/rebalance_panel.js · v53
 *
 * 职责分工:
 *   position-path → 个股交易指令 (T/T+2/T+5 三阶段)
 *   本面板        → 子策略配额偏离可视化 + 极端场景模拟
 */

(function () {
    'use strict';

    const STRAT = {
        mr:  { label: '均值回归', color: '#3b82f6', icon: '📊' },
        div: { label: '红利防御', color: '#f59e0b', icon: '💰' },
        mom: { label: '动量轮动', color: '#ef4444', icon: '🚀' },
        gem: { label: '全球配置', color: '#8b5cf6', icon: '🌍' },
        erp: { label: '债券底仓', color: '#10b981', icon: '🏦' },
    };

    function fmt(n) {
        if (Math.abs(n) >= 10000) return (n / 10000).toFixed(1) + '万';
        return Math.round(n).toLocaleString();
    }

    async function loadRebalancePanel() {
        const $summary = document.getElementById('rebalance-summary');
        const $alloc = document.getElementById('rebal-alloc-grid');
        const $stress = document.getElementById('rebal-stress');
        if (!$summary) return;

        console.log('[V5-Rebal] loading...');

        // ── 加载态 ──
        $summary.textContent = '⏳ 加载中...';

        let rebalOk = false, stressOk = false;

        try {
            // 并行拉取两个 API
            const [rebalRaw, stressRaw] = await Promise.all([
                fetch('/api/v1/portfolio/rebalance').then(r => {
                    console.log('[V5-Rebal] rebalance HTTP:', r.status);
                    return r.json();
                }).catch(e => { console.warn('[V5-Rebal] rebalance fetch fail:', e); return null; }),
                fetch('/api/v1/portfolio/stress-test').then(r => {
                    console.log('[V5-Rebal] stress HTTP:', r.status);
                    return r.json();
                }).catch(e => { console.warn('[V5-Rebal] stress fetch fail:', e); return null; }),
            ]);

            console.log('[V5-Rebal] rebalRaw:', rebalRaw?.status, rebalRaw?.data?.status);
            console.log('[V5-Rebal] stressRaw:', stressRaw?.status, stressRaw?.data?.status);

            // 解包: R.ok() 嵌套 → data 层有 status
            const rb = rebalRaw?.data?.status === 'success' ? rebalRaw.data
                     : rebalRaw?.status === 'success' && rebalRaw?.summary ? rebalRaw
                     : null;
            const st = stressRaw?.data?.status === 'success' ? stressRaw.data
                     : stressRaw?.status === 'success' && stressRaw?.scenarios ? stressRaw
                     : null;

            // ═══ 策略配额偏离 ═══
            if (rb && rb.summary) {
                rebalOk = true;
                const s = rb.summary;
                const bd = s.strategy_breakdown;

                // 摘要
                const regimeLabel = ['', '极低估', '低估', '中性', '偏高', '过热'][s.regime] || '';
                $summary.innerHTML = `R${s.regime} <span style="color:#64748b;font-size:0.65rem">${regimeLabel}</span> · ${s.current_pct.toFixed(0)}%→${s.target_pct.toFixed(0)}%`;

                // 配额条
                let html = '<div class="rebal-section-header">子策略配额偏离</div>';
                html += '<div class="rebal-bars">';

                const totalTarget = Object.values(bd).reduce((a, v) => a + v.target_mv, 0) || 1;

                for (const [key, v] of Object.entries(bd)) {
                    const meta = STRAT[key] || { label: key, color: '#64748b', icon: '•' };
                    const curPct = v.current_mv / totalTarget * 100;
                    const tgtPct = v.target_mv / totalTarget * 100;
                    const overunder = v.delta_mv > 500 ? 'over' : (v.delta_mv < -500 ? 'under' : 'ok');
                    const deltaStr = Math.abs(v.delta_mv) < 500 ? '均衡'
                        : (v.delta_mv > 0 ? '+' : '') + fmt(v.delta_mv);

                    html += `
                    <div class="rebal-bar-row" data-status="${overunder}">
                        <span class="rebal-bar-icon">${meta.icon}</span>
                        <span class="rebal-bar-label">${meta.label}</span>
                        <span class="rebal-bar-alloc">${v.alloc_pct}%</span>
                        <div class="rebal-bar-track">
                            <div class="rebal-bar-fill" style="width:${Math.min(curPct, 100).toFixed(0)}%;background:${meta.color};"></div>
                            <div class="rebal-bar-marker" style="left:${Math.min(tgtPct, 100).toFixed(0)}%"></div>
                        </div>
                        <span class="rebal-bar-delta ${overunder}">${deltaStr}</span>
                    </div>`;
                }
                html += '</div>';

                // 偏离度总结
                const maxDev = Math.max(...Object.values(bd).map(v => Math.abs(v.delta_mv)));
                const worstKey = Object.entries(bd).sort((a, b) => Math.abs(b[1].delta_mv) - Math.abs(a[1].delta_mv))[0];
                if (worstKey && Math.abs(worstKey[1].delta_mv) > 5000) {
                    const wLabel = STRAT[worstKey[0]]?.label || worstKey[0];
                    const wDelta = worstKey[1].delta_mv;
                    const wClass = wDelta > 0 ? 'over' : 'under';
                    html += `<div class="rebal-deviation-alert ${wClass}">
                        ⚠ 最大偏离: ${wLabel} ${wDelta > 0 ? '超配' : '欠配'} ${fmt(Math.abs(wDelta))}
                    </div>`;
                }

                $alloc.innerHTML = html;
            }

            // ═══ 压力测试 ═══
            if (st && st.scenarios) {
                stressOk = true;
                const sc = st.scenarios;
                const ra = st.risk_assessment;

                let html = '<div class="rebal-section-header">R1~R5 极端情景模拟</div>';
                html += '<div class="rebal-stress-grid">';

                for (const rk of ['R1', 'R2', 'R3', 'R4', 'R5']) {
                    const d = sc[rk];
                    if (!d || d.error) continue;

                    const severity = rk === 'R5' ? 'critical' : (rk === 'R4' ? 'warn' : 'normal');
                    const isCurrent = Math.abs(d.delta_pct) < 2;
                    const regimeEmoji = ['', '🟢', '🟡', '⚪', '🟠', '🔴'][parseInt(rk[1])];

                    html += `
                    <div class="rebal-stress-cell ${severity} ${isCurrent ? 'active' : ''}">
                        <div class="stress-emoji">${regimeEmoji}</div>
                        <div class="stress-regime">${rk}</div>
                        <div class="stress-target">${d.target_pct}%</div>
                        <div class="stress-delta">${d.delta_pct > 0 ? '+' : ''}${d.delta_pct.toFixed(0)}%</div>
                        <div class="stress-sell">${d.total_sell > 0 ? '卖' + fmt(d.total_sell) : '—'}</div>
                    </div>`;
                }
                html += '</div>';

                // 风险徽章
                if (ra) {
                    const riskMap = {
                        HIGH: { cls: 'danger', icon: '🔴', text: '高风险' },
                        MEDIUM: { cls: 'warn', icon: '🟡', text: '中等' },
                        LOW: { cls: 'safe', icon: '🟢', text: '可控' },
                    };
                    const rm = riskMap[ra.liquidity_risk] || riskMap.LOW;
                    html += `
                    <div class="rebal-risk-row ${rm.cls}">
                        <span class="risk-icon">${rm.icon}</span>
                        <span class="risk-label">流动性风险</span>
                        <span class="risk-value">${rm.text}</span>
                        <span class="risk-detail">R5清仓 ${ra.r5_liquidation_days.toFixed(1)}天 · 单日上限 ${fmt(ra.max_daily_sell)}</span>
                    </div>`;

                    if (ra.liquidity_risk === 'HIGH') {
                        $summary.innerHTML += ' · <span style="color:#fca5a5">⚠ 流动性HIGH</span>';
                    }
                }

                $stress.innerHTML = html;
            }

            // 最终状态
            if (!rebalOk && !stressOk) {
                $summary.textContent = '⚠ 服务未就绪';
                $alloc.innerHTML = '<div class="rebal-empty">调仓引擎未返回数据，请确认服务已启动</div>';
            }

            console.log('[V5-Rebal] done. rebal=%s, stress=%s', rebalOk, stressOk);

        } catch (e) {
            console.error('[V5-Rebal] fatal:', e);
            $summary.textContent = '⚠ 加载异常';
            $alloc.innerHTML = `<div class="rebal-empty">错误: ${e.message}</div>`;
        }
    }

    // 3s 延迟 (非关键路径)
    setTimeout(loadRebalancePanel, 3000);
})();
