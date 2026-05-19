/**
 * AlphaCore · 策略健康度面板 (V27.0 P1-C)
 * ==========================================
 * 从 strategy/run-all + decision/accuracy 聚合数据
 * 为每个策略引擎渲染"信号灯 + 信号标签 + 准确率"
 */
(function () {
    'use strict';

    const SIGNAL_MAP = {
        buy:       { label: '看多', cls: 'vital-buy',  dot: '#34d399' },
        sell:      { label: '看空', cls: 'vital-sell', dot: '#f87171' },
        sell_half: { label: '减仓', cls: 'vital-sell', dot: '#fb923c' },
        sell_weak: { label: '弱空', cls: 'vital-sell', dot: '#fb923c' },
        hold:      { label: '持有', cls: 'vital-hold', dot: '#fbbf24' },
    };

    // ── 信号标签渲染 ──
    function renderSignalBadge(signal, score) {
        const info = SIGNAL_MAP[signal] || SIGNAL_MAP.hold;
        const scoreStr = score != null ? ` · ${score}分` : '';
        return `<span class="${info.cls}">${info.label}${scoreStr}</span>`;
    }

    // ── 从 strategy/run-all 提取策略信号 ──
    function extractStrategyVitals(runAllData) {
        const g = runAllData.global || {};
        const confidence = g.confidence || {};
        const strategies = runAllData.strategies || {};
        const aiae = g.aiae || {};

        const vitals = {};

        // MR
        const mrSignals = strategies.mr?.buy_signals || strategies.mr?.signals || [];
        const mrBuy = mrSignals.filter(s => s.signal === 'buy').length;
        const mrSell = mrSignals.filter(s => s.signal && s.signal.startsWith('sell')).length;
        vitals.mr = {
            signal: mrBuy > mrSell ? 'buy' : mrSell > mrBuy ? 'sell' : 'hold',
            score: confidence.mr || 0,
            detail: `${mrBuy}买/${mrSell}卖`,
        };

        // MOM
        const momSignals = strategies.mom?.signals || [];
        const momBuy = momSignals.filter(s => s.signal === 'buy').length;
        vitals.mom = {
            signal: momBuy > 0 ? 'buy' : 'hold',
            score: confidence.mom || 0,
            detail: `${momBuy} 只进攻标的`,
        };

        // DIV
        const divSignals = strategies.div?.signals || [];
        const divBuy = divSignals.filter(s => s.signal === 'buy').length;
        vitals.div = {
            signal: divBuy > 0 ? 'buy' : 'hold',
            score: confidence.div || 0,
            detail: `${divBuy} 只买入信号`,
        };

        // ERP
        const erpOv = strategies.erp?.market_overview || {};
        const erpSig = erpOv.signal_key || 'hold';
        vitals.erp = {
            signal: erpSig,
            score: erpOv.composite_score || confidence.erp || 0,
            detail: `ERP Score ${erpOv.composite_score || '--'}`,
        };

        // AIAE
        const aiaeRegime = aiae.regime || 3;
        const aiaeSig = aiaeRegime <= 2 ? 'buy' : aiaeRegime >= 4 ? 'sell' : 'hold';
        vitals.aiae = {
            signal: aiaeSig,
            score: confidence.aiae_etf || 0,
            detail: `R${aiaeRegime} ${aiae.regime_cn || ''} Cap${aiae.aiae_cap || '--'}%`,
        };

        return vitals;
    }

    // ── 渲染到DOM ──
    function renderVitals(vitals, accuracy) {
        const keys = ['mr', 'mom', 'div', 'erp', 'aiae'];

        for (const key of keys) {
            const v = vitals[key];
            if (!v) continue;

            const signalEl = document.getElementById(`vital-${key}-signal`);
            if (signalEl) signalEl.innerHTML = renderSignalBadge(v.signal, v.score);

            const dotEl = document.querySelector(`#vital-${key} .vital-dot`);
            if (dotEl) {
                const info = SIGNAL_MAP[v.signal] || SIGNAL_MAP.hold;
                dotEl.style.color = info.dot;
            }

            const accEl = document.getElementById(`vital-${key}-acc`);
            if (accEl && accuracy && accuracy[key] != null) {
                const accVal = accuracy[key];
                const accColor = accVal >= 60 ? '#34d399' : accVal >= 40 ? '#fbbf24' : '#f87171';
                accEl.innerHTML = `准确率 <span style="color:${accColor};font-weight:600;">${accVal}%</span>`;
            }
        }
    }

    // ── 加载 ──
    async function loadHealthData() {
        try {
            // 从已有的 dashboard 数据中获取策略信息
            // strategy/run-all 通常在 script.js 中已经加载过，我们用 fetch 重新取一份轻量数据
            const [runAllResp, accResp] = await Promise.allSettled([
                fetch('/api/v1/strategy/run-all'),
                fetch('/api/v1/decision/accuracy'),
            ]);

            let vitals = null;
            if (runAllResp.status === 'fulfilled' && runAllResp.value.ok) {
                const runAllJson = await runAllResp.value.json();
                if (runAllJson.data || runAllJson.status === 'success') {
                    vitals = extractStrategyVitals(runAllJson.data || runAllJson);
                }
            }

            let accuracy = null;
            if (accResp.status === 'fulfilled' && accResp.value.ok) {
                const accJson = await accResp.value.json();
                const stats = accJson.data || accJson;
                // Convert accuracy stats to per-strategy format
                if (Array.isArray(stats)) {
                    accuracy = {};
                    for (const s of stats) {
                        const key = s.strategy?.toLowerCase().replace('mean_reversion', 'mr')
                            .replace('momentum', 'mom').replace('dividend', 'div')
                            .replace('erp_timing', 'erp').replace('aiae', 'aiae');
                        if (key && s.accuracy_pct != null) {
                            accuracy[key] = Math.round(s.accuracy_pct);
                        }
                    }
                }
            }

            if (vitals) {
                renderVitals(vitals, accuracy);
                const tsEl = document.getElementById('strat-health-ts');
                if (tsEl) tsEl.textContent = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
            }
        } catch (err) {
            console.warn('[StratHealth] Load error:', err);
        }
    }

    // ── 注入CSS ──
    function injectStyles() {
        if (document.getElementById('ac-vital-styles')) return;
        const style = document.createElement('style');
        style.id = 'ac-vital-styles';
        style.textContent = `
            .strat-vital {
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 8px;
                padding: 10px 12px;
                transition: border-color 0.2s;
            }
            .strat-vital:hover { border-color: rgba(99,102,241,0.3); }
            .vital-head {
                display: flex; align-items: center; gap: 6px;
                font-size: 0.75rem; color: rgba(255,255,255,0.5); margin-bottom: 6px;
            }
            .vital-dot { font-size: 0.6rem; }
            .vital-name { font-weight: 500; }
            .vital-metric { font-size: 0.9rem; font-weight: 600; margin-bottom: 4px; }
            .vital-sub { font-size: 0.68rem; color: rgba(255,255,255,0.35); font-family: 'Outfit', sans-serif; }
            .vital-buy { color: #34d399; }
            .vital-sell { color: #f87171; }
            .vital-hold { color: #fbbf24; }
        `;
        document.head.appendChild(style);
    }

    function init() {
        injectStyles();
        // Delay slightly to not compete with dashboard's main data load
        setTimeout(loadHealthData, 3000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
