// AlphaCore · 策略中心页面 JS
const API_URL = '';

// ====== 通用折叠组件 (Phase 1 提取) ======
function toggleAccordion(trigger) {
    const body = trigger.nextElementSibling;
    if (!body) return;
    const isOpen = body.style.display !== 'none';
    body.style.display = isOpen ? 'none' : 'block';
    const arrow = trigger.querySelector('.acc-arrow');
    if (arrow) arrow.style.transform = isOpen ? 'rotate(-90deg)' : 'rotate(0deg)';
}

// ====== 计算器自动填入市场状态 ======
async function autoFillCalcRegime() {
    const btn = document.getElementById('calc-auto-fill-btn');
    const statusEl = document.getElementById('calc-auto-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 识别中...'; }

    try {
        const resp = await fetch(`${API_URL}/api/v1/market/regime`, { cache: 'no-cache' });
        const data = await resp.json();
        const regime = data.regime || 'RANGE';

        // 评分位映射：与 renderRegime() / HTML <select> 保持一致
        const regimeScoreMap = { CRASH: 0, BEAR: 0, RANGE: 12, BULL: 20 };
        const score = regimeScoreMap[regime] ?? 12;

        const sel = document.getElementById('calc-regime');
        if (sel) {
            sel.value = score;
            calcSignalScore();
        }

        // 状态提示
        const icons = { BULL: '🟢', RANGE: '🟡', BEAR: '🔴', CRASH: '🚨' };
        const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.textContent = `✅ 已自动同步：${icons[regime] || ''} ${regime} 市场状态（${data.regime_desc || ''}）— ${ts} 更新`;
        }
    } catch(e) {
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.style.background = 'rgba(239,68,68,0.08)';
            statusEl.style.color = '#f87171';
            statusEl.style.borderColor = 'rgba(239,68,68,0.2)';
            statusEl.textContent = `⚠️ 自动填入失败：${e.message}`;
        }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '📡 自动填入市场状态'; }
    }
}

// ====== 实时信号评分计算器 (V3.0 · 状态自适应门槛) ======
function calcSignalScore() {
    // ── 读取7个维度输入值 ──
    const s1  = parseInt(document.getElementById('calc-rsi')?.value     || 10);  // ① RSI深度
    const s2  = parseInt(document.getElementById('calc-rsi-dir')?.value  || 8);   // ② RSI动量方向
    const s3  = parseInt(document.getElementById('calc-bias')?.value    || 13);   // ③ BIAS乖离率
    const s4  = parseInt(document.getElementById('calc-vlt')?.value     || 10);   // ④ 布林带%B
    const s5  = parseInt(document.getElementById('calc-vol')?.value     || 6);    // ⑤ 量比（parseInt自动处理6_low→6, 10_low→10）
    const s6  = parseInt(document.getElementById('calc-trend')?.value   || 7);    // ⑥ 趋势位置
    const s7  = parseInt(document.getElementById('calc-kline')?.value   || 3);    // ⑦ K线形态
    const reg = parseInt(document.getElementById('calc-regime')?.value  || 12);   // 市场环境(门槛用)

    const total = Math.min(100, s1 + s2 + s3 + s4 + s5 + s6 + s7);

    // ── 市场状态自适应门槛 ──
    let gate;
    if (reg === 20)      gate = 75;  // BULL牛市：门槛降低（回调即机会）
    else if (reg === 12) gate = 68;  // RANGE震荡：标准
    else                 gate = 78;  // BEAR熊市：严格（防接飞刀）
    const halfGate = Math.round(gate * 0.85);
    const fullGate = Math.min(gate + 15, 95);

    // ── 更新UI ──
    const numEl  = document.getElementById('calc-score-num');
    const barEl  = document.getElementById('calc-score-bar');
    const vrdEl  = document.getElementById('calc-verdict');
    const actEl  = document.getElementById('calc-action');
    const thEl   = document.getElementById('calc-threshold-hint');
    const bbEl   = document.getElementById('calc-breakdown-bar');

    if (numEl) numEl.textContent = total;
    if (barEl) barEl.style.width = total + '%';
    if (thEl)  thEl.textContent  = `当前市场门槛: 全仓≥${fullGate} · 标准≥${gate} · 半仓≥${halfGate}`;

    // ── 7维度彩色分布条 ──
    if (bbEl) {
        const dims = [
            { val: s1, max: 25, color: '#60a5fa' },   // ① 蓝
            { val: s2, max: 15, color: '#a78bfa' },   // ② 紫 ✨
            { val: s3, max: 20, color: '#2dd4bf' },   // ③ 青
            { val: s4, max: 15, color: '#22d3ee' },   // ④ 蓝绿
            { val: s5, max: 10, color: '#34d399' },   // ⑤ 绿
            { val: s6, max: 10, color: '#fbbf24' },   // ⑥ 黄
            { val: s7, max:  5, color: '#fb923c' },   // ⑦ 橙 ✨
        ];
        bbEl.innerHTML = dims.map(d =>
            `<div style="flex:${d.val};background:${d.color};opacity:${d.val>0?0.85:0.12};border-radius:1px;transition:flex 0.4s ease;min-width:${d.val>0?2:1}px;" title="${d.val}/${d.max}分"></div>`
        ).join('');

        // 明细标签文本
        const bText = document.getElementById('calc-breakdown-text');
        if (bText) bText.textContent =
            `①${s1} ②${s2} ③${s3} ④${s4} ⑤${s5} ⑥${s6} ⑦${s7}`;
    }

    // ── 颜色 + 判决 ──
    let color, verdict, action;
    if (total >= fullGate) {
        color = '#10b981'; verdict = '🟢 全仓入场';
        action = `评分 ${total}分（≥${fullGate}满仓线）信号极强。建议建仓至单标的上限，执行当前Regime止损线，追踪止盈 T1+15% / T2+25%。`;
    } else if (total >= gate) {
        color = '#22d3ee'; verdict = '🔵 标准入场';
        action = `评分 ${total}分（≥${gate}达标）信号达标。建议建仓 2/3，量能确认后加至满仓。`;
    } else if (total >= halfGate) {
        color = '#fbbf24'; verdict = '🟡 半仓观察';
        action = `评分 ${total}分（≥${halfGate}半仓线）信号偏弱。建议建仓上限的 50%，调仓日重新评估。`;
    } else {
        color = '#f87171'; verdict = '❌ 不入场';
        action = `评分 ${total}分（<${halfGate}）信号不足。建议观望，等待 RSI 动量好转（②维度）或市场状态改善。`;
    }

    if (numEl) numEl.style.color = color;
    if (barEl) {
        const grad = total >= fullGate
            ? 'linear-gradient(90deg,#10b981,#6ee7b7)'
            : total >= gate ? 'linear-gradient(90deg,#06b6d4,#22d3ee)'
            : total >= halfGate ? 'linear-gradient(90deg,#f59e0b,#fbbf24)'
            : 'linear-gradient(90deg,#ef4444,#f87171)';
        barEl.style.background = grad;
    }
    if (vrdEl) {
        vrdEl.textContent = verdict;
        vrdEl.style.borderColor = color + '44';
        vrdEl.style.background  = color + '11';
        vrdEl.style.color = color;
    }
    if (actEl) actEl.textContent = action;
}

// 初始化计算器默认结果 + 事件绑定（用 delegation 防止 tab 隐藏时丢失绑定）
document.addEventListener('DOMContentLoaded', () => {
    calcSignalScore();
    calcDividendScore();
    // 确保 tab 切换后也能实时响应
    const calcIds = ['calc-mom','calc-regime','calc-vol','calc-rsi','calc-vlt'];
    calcIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', calcSignalScore);
    });
    const divIds = ['div-calc-regime','div-calc-rsi','div-calc-bias','div-calc-yield','div-calc-boll','div-calc-vol','div-calc-rsi-dir'];
    divIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', calcDividendScore);
    });
});

// ====== 💰 红利策略专属评分器 V4.0 · 对齐后端 score_etf() ======
// 七维因子：市场环境(15) + RSI(18) + 乖离率(18) + 股息率(20) + 布林(10) + 波动率(9) + RSI动量方向(10) = 100
function calcDividendScore() {
    const regime  = document.getElementById('div-calc-regime')?.value  || 'RANGE';
    const rsiVal  = parseInt(document.getElementById('div-calc-rsi')?.value  || 9);
    const biasVal = parseInt(document.getElementById('div-calc-bias')?.value || 7);
    const yldVal  = parseInt(document.getElementById('div-calc-yield')?.value || 12);
    const bollVal = parseInt(document.getElementById('div-calc-boll')?.value  || 6);
    const volVal  = parseInt(document.getElementById('div-calc-vol')?.value   || 9);
    const rsiDirVal = parseInt(document.getElementById('div-calc-rsi-dir')?.value || 4);

    // 维度1：市场环境得分（V4.0降权至15分）
    const envScore = { BULL: 15, RANGE: 10, BEAR: 4, CRASH: 0 }[regime] ?? 10;

    const total = Math.min(envScore + rsiVal + biasVal + yldVal + bollVal + volVal + rsiDirVal, 100);

    // 状态自适应门槛
    const gates = { BULL: 55, RANGE: 65, BEAR: 75, CRASH: 999 };
    const gate     = gates[regime] ?? 65;
    const fullGate = Math.min(gate + 15, 95);
    const halfGate = Math.round(gate * 0.85);

    const numEl = document.getElementById('div-score-num');
    const barEl = document.getElementById('div-score-bar');
    const vrdEl = document.getElementById('div-verdict');
    const actEl = document.getElementById('div-action');
    const thEl  = document.getElementById('div-threshold-hint');

    if (numEl) numEl.textContent = total;
    if (barEl) barEl.style.width = Math.min(total, 100) + '%';
    if (thEl)  thEl.textContent  = `${regime}模式门槛: 全仓≥${fullGate} | 标准≥${gate} | 半仓≥${halfGate}`;

    let color, verdict, action;

    if (regime === 'CRASH') {
        color = '#f87171';
        verdict = '💥 熔断禁入';
        action = '当前处于CRASH熔断状态，禁止任何新建仓。高股息(>6%)已持仓不强制清仓，等待CRASH解除后恢复正常判断。';
    } else if (total >= fullGate) {
        color = '#10b981';
        verdict = '🟢 全仓入场';
        action = `红利评分 ${total} 分（≥${fullGate}满仓线），信号极强。建议按${regime}模式仓位上限建仓，启动止盈止损追踪。`;
    } else if (total >= gate) {
        color = '#60a5fa';
        verdict = '🔵 标准入场';
        action = `红利评分 ${total} 分（≥${gate}达标），建议建仓单标的基准权重，等候股息率或RSI进一步改善时加到满仓。`;
    } else if (total >= halfGate) {
        color = '#fbbf24';
        verdict = '🟡 半仓观察';
        action = `红利评分 ${total} 分（≥${halfGate}半仓线），信号偏弱。建议建仓基准权重的50%，密切关注RSI下探或股息率提升。`;
    } else {
        color = '#f87171';
        verdict = '❌ 不入场';
        action = `红利评分 ${total} 分（<${halfGate}），信号不足。建议观望，等待RSI下探至35以下或乖离率达到-2%以下。`;
    }

    if (numEl) numEl.style.color = color;
    if (barEl) {
        const grad = total >= fullGate
            ? 'linear-gradient(90deg,#10b981,#6ee7b7)'
            : total >= gate   ? 'linear-gradient(90deg,#3b82f6,#60a5fa)'
            : total >= halfGate ? 'linear-gradient(90deg,#f59e0b,#fbbf24)'
            : 'linear-gradient(90deg,#ef4444,#f87171)';
        barEl.style.background = grad;
    }
    if (vrdEl) {
        vrdEl.textContent    = verdict;
        vrdEl.style.borderColor = color + '44';
        vrdEl.style.background  = color + '11';
        vrdEl.style.color       = color;
    }
    if (actEl) actEl.textContent = action;

    // 联动红利趋势 tab 的状态高亮
    ['bull','range','bear','crash'].forEach(r => {
        const el = document.getElementById(`div-regime-${r}`);
        if (el) {
            el.style.opacity = (regime.toLowerCase() === r) ? '1' : '0.4';
            el.style.transform = (regime.toLowerCase() === r) ? 'scale(1.02)' : 'scale(1)';
        }
    });
}



// ====== ⚡ 均值回归 V4.0 · 当前激活参数自动加载 ======
const _MR_REGIME_META = {
    BULL:  { icon:'🟢', name:'BULL',  sub:'牛市',    color:'#34d399', bg:'rgba(16,185,129,0.10)', border:'rgba(16,185,129,0.3)' },
    RANGE: { icon:'🟡', name:'RANGE', sub:'震荡',    color:'#fbbf24', bg:'rgba(245,158,11,0.10)', border:'rgba(245,158,11,0.3)' },
    BEAR:  { icon:'🔴', name:'BEAR',  sub:'熊市',    color:'#f87171', bg:'rgba(239,68,68,0.10)',  border:'rgba(239,68,68,0.3)'  },
    CRASH: { icon:'🚨', name:'CRASH', sub:'崩盘警戒',color:'#ff4444', bg:'rgba(239,0,0,0.15)',    border:'rgba(239,0,0,0.4)'    },
};

async function loadMrCurrentParams(force = false) {
    const loadEl   = document.getElementById('mr-params-loading');
    const resultEl = document.getElementById('mr-params-result');
    const btn      = document.getElementById('mr-params-refresh-btn');
    if (loadEl)  loadEl.style.display = 'flex';
    if (resultEl) resultEl.style.display = 'none';
    if (btn)    { btn.disabled = true; btn.textContent = '⏳ 识别中...'; }

    try {
        // ── 统一 API：与信号评分系统共用相同 endpoint 和算法 ──
        const resp = await fetch(`${API_URL}/api/v1/market/regime`, {
            cache: 'no-cache',
            signal: AbortSignal.timeout(12000)
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const mkt = await resp.json();
        if (mkt.status === 'error') throw new Error(mkt.message);

        const regime = mkt.regime || 'RANGE';

        // 从 mr_per_regime_params.json 补充 MR 专属参数
        let mrParams = {}, allRegs = {}, needsR = false;
        try {
            const r2 = await fetch('./mr_per_regime_params.json?' + Date.now());
            if (r2.ok) {
                const jd = await r2.json();
                needsR = jd.next_optimize_after
                    ? new Date() >= new Date(jd.next_optimize_after) : false;
                const capMap  = { BEAR: 0.65, RANGE: 0.80, BULL: 0.35 };
                const gateMap = { BEAR: 78,   RANGE: 68,   BULL: 60   };
                Object.entries(jd.regimes || {}).forEach(([r, v]) => {
                    allRegs[r] = { params: v.params, pos_cap: capMap[r] || 0.65,
                                   score_gate: gateMap[r] || 68,
                                   combined_score: v.combined_score,
                                   train_alpha: v.train_kpi?.alpha,
                                   valid_alpha: v.valid_kpi?.alpha };
                });
                mrParams = allRegs[regime]?.params || {};
            }
        } catch(_) { /* use market API defaults */ }

        _renderMrActiveParams({
            regime:           regime,
            params:           mrParams,
            pos_cap:          (mkt.pos_cap || 66) / 100,
            score_gate:       mkt.score_gate || 68,
            all_regimes:      allRegs,
            needs_reoptimize: needsR,
            csi300:           mkt.csi300,
            ma120:            mkt.ma120,
            regime_desc:      mkt.regime_desc,
        });
    } catch(e) {
        if (loadEl) loadEl.innerHTML =
            '<span style="color:#f87171;">⚠️ 无法连接后端，请检查服务器是否运行</span>';
        console.warn('[MR V4.0] loadMrCurrentParams failed:', e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🔄 重新识别'; }
    }
}

function _renderMrActiveParams(data) {
    const regime = data.regime  || 'RANGE';
    const params = data.params  || {};
    const posCap = data.pos_cap || 0.80;
    const gate   = data.score_gate || 68;
    const allReg = data.all_regimes || {};
    const needR  = data.needs_reoptimize;
    const meta   = _MR_REGIME_META[regime] || _MR_REGIME_META['RANGE'];

    const loadEl   = document.getElementById('mr-params-loading');
    const resultEl = document.getElementById('mr-params-result');
    if (loadEl)   loadEl.style.display  = 'none';
    if (resultEl) resultEl.style.display = 'block';

    const badge = document.getElementById('mr-regime-badge');
    if (badge) {
        badge.style.background   = meta.bg;
        badge.style.borderColor  = meta.border;
        badge.className = badge.className.replace(/regime-\w+-glow/g, '');
        badge.classList.add(`regime-${regime.toLowerCase()}-glow`);
    }

    const _t = (id, txt, color) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = txt;
        if (color) el.style.color = color;
    };
    _t('mr-regime-icon', meta.icon);
    _t('mr-regime-name', meta.name, meta.color);
    _t('mr-regime-sub',  meta.sub);
    _t('mr-ap-trend',  `MA${params.N_trend || 90}`, '#34d399');
    _t('mr-ap-rsibuy', params.rsi_buy  != null ? String(params.rsi_buy)          : '—', '#34d399');
    _t('mr-ap-rsisell',params.rsi_sell != null ? String(params.rsi_sell)         : '—', '#f87171');
    _t('mr-ap-bias',   params.bias_buy != null ? `${params.bias_buy}%`           : '—', '#fbbf24');
    _t('mr-ap-sl',     params.stop_loss!= null ? `-${(params.stop_loss*100).toFixed(0)}%` : '—', '#f87171');
    _t('mr-ap-poscap', `${Math.round(posCap*100)}%`, '#34d399');
    _t('mr-ap-gate',   `${gate}分`, '#fbbf24');
    _t('mr-ap-time',   new Date().toLocaleTimeString('zh-CN'));

    const reoptBanner = document.getElementById('mr-reopt-banner');
    if (reoptBanner) reoptBanner.style.display = needR ? 'block' : 'none';

    const tbody = document.getElementById('mr-regime-table-body');
    if (tbody) {
        const capMap  = { BEAR:65, RANGE:80, BULL:35 };
        const descMap = { BEAR:'🔴 熊市', RANGE:'🟡 震荡', BULL:'🟢 牛市' };
        tbody.innerHTML = ['BEAR','RANGE','BULL'].map(r => {
            const p = allReg[r]?.params || {};
            const isActive = r === regime;
            const s = isActive ? `background:${_MR_REGIME_META[r].bg};font-weight:700;` : '';
            return `<tr style="${s}">
                <td>${descMap[r]}${isActive ? ' ◀当前' : ''}</td>
                <td>MA${p.N_trend||'—'}</td>
                <td>${p.rsi_buy  !=null?'≤'+p.rsi_buy:'—'}</td>
                <td>${p.rsi_sell !=null?'≥'+p.rsi_sell:'—'}</td>
                <td>${p.bias_buy !=null?p.bias_buy+'%':'—'}</td>
                <td>${p.stop_loss!=null?'-'+(p.stop_loss*100).toFixed(0)+'%':'—'}</td>
                <td>${capMap[r]||'—'}%</td>
            </tr>`;
        }).join('');
    }

    // 联动信号评分：自动设置 Regime 下拉
    const regSel = document.getElementById('calc-regime');
    if (regSel) {
        const regVal = { BULL:20, RANGE:12, BEAR:0, CRASH:0 }[regime];
        if (regVal != null) { regSel.value = String(regVal); calcSignalScore(); }
    }
}

// 页面打开自动识别
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadMrCurrentParams, 500);
});

// ====== 📊 均值回归 V3.0 回测验证 — 净值曲线渲染 ======
let _mrBacktestChart = null;

async function loadMrBacktestData() {
    const btn    = document.getElementById('mr-load-btn');
    const status = document.getElementById('mr-load-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 加载中...'; }
    if (status) status.textContent = '正在读取回测结果...';

    try {
        // 通过后端 API 获取（避免 CORS 限制）
        const resp = await fetch(`${API_URL}/api/v1/mr_backtest_results`, {
            signal: AbortSignal.timeout(8000)
        });
        if (!resp.ok) throw new Error(`API ${resp.status}`);
        const data = await resp.json();
        _renderMrBacktest(data);
        if (status) status.textContent = `✅ 数据加载成功 · 生成于 ${(data.generated_at || '').slice(0,10)}`;
    } catch (e) {
        // Fallback: 请求静态文件
        try {
            const resp2 = await fetch('./mr_optimization_results.json?' + Date.now());
            if (!resp2.ok) throw new Error('本地文件不存在');
            const data = await resp2.json();
            _renderMrBacktest(data);
            if (status) status.textContent = `✅ 本地数据加载成功 · 生成于 ${(data.generated_at || '').slice(0,10)}`;
        } catch (e2) {
            if (status) status.textContent = `❌ 加载失败：请先运行 mr_regime_backtest.py 生成数据`;
        }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🔄 刷新回测净值曲线'; }
    }
}

function _renderMrBacktest(data) {
    // 更新 KPI 卡片
    const kpi = data.regime_overlay_kpi || data.best_valid || {};
    const fmt  = (v, suffix='%') => v != null ? (v > 0 ? '+' : '') + v.toFixed(1) + suffix : '—';

    const setEl = (id, txt, color) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = txt;
        if (color) el.style.color = color;
    };

    setEl('mr-kpi-annret', fmt(kpi.ann_ret), kpi.ann_ret >= 0 ? '#34d399' : '#f87171');
    setEl('mr-kpi-alpha',  fmt(kpi.alpha),   kpi.alpha  >= 0 ? '#60a5fa' : '#f87171');
    setEl('mr-kpi-sharpe', kpi.sharpe != null ? kpi.sharpe.toFixed(3) : '—',
           kpi.sharpe >= 1.0 ? '#34d399' : kpi.sharpe >= 0.5 ? '#a78bfa' : '#fbbf24');
    setEl('mr-kpi-maxdd',  kpi.max_dd != null ? kpi.max_dd.toFixed(2) + '%' : '—',
           kpi.max_dd >= -10 ? '#34d399' : kpi.max_dd >= -20 ? '#fbbf24' : '#f87171');
    setEl('mr-kpi-calmar', kpi.calmar != null ? kpi.calmar.toFixed(3) : '—',
           kpi.calmar >= 1.5 ? '#34d399' : kpi.calmar >= 0.8 ? '#a78bfa' : '#fbbf24');

    // 净值曲线（ECharts）
    const chartEl = document.getElementById('mr-equity-chart');
    if (!chartEl || typeof echarts === 'undefined') return;

    const dates  = data.regime_equity_dates  || data.equity_dates  || [];
    const equity = data.regime_equity_values || data.equity_values || [];
    const bm     = data.regime_bm_values     || data.bm_values     || [];
    const labels = data.regime_labels        || [];

    // 颜色带区：BULL/RANGE/BEAR
    const markAreas = [];
    let areaStart = null, prevReg = null;
    const regColor = { BULL:'rgba(16,185,129,0.07)', RANGE:'rgba(99,102,241,0.05)', BEAR:'rgba(239,68,68,0.07)' };

    dates.forEach((d, i) => {
        const reg = labels[i] || 'RANGE';
        if (reg !== prevReg) {
            if (areaStart !== null && prevReg) {
                markAreas.push([
                    { xAxis: areaStart, itemStyle: { color: regColor[prevReg] || 'transparent' } },
                    { xAxis: dates[i - 1] }
                ]);
            }
            areaStart = d; prevReg = reg;
        }
    });
    if (areaStart && prevReg) {
        markAreas.push([
            { xAxis: areaStart, itemStyle: { color: regColor[prevReg] || 'transparent' } },
            { xAxis: dates[dates.length - 1] }
        ]);
    }

    if (_mrBacktestChart) { _mrBacktestChart.dispose(); }
    _mrBacktestChart = echarts.init(chartEl, 'dark');

    const option = {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis', axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(15,23,42,0.95)', borderColor: 'rgba(99,102,241,0.3)',
            textStyle: { color: '#e2e8f0', fontSize: 12 },
            formatter: params => {
                const d = params[0].axisValue;
                const reg = labels[params[0].dataIndex] || 'RANGE';
                const regLabel = { BULL:'🟢 牛市', RANGE:'🟡 震荡', BEAR:'🔴 熊市' }[reg] || reg;
                let html = `<div style="font-weight:700;margin-bottom:4px">${d} · ${regLabel}</div>`;
                params.forEach(p => {
                    const v = ((p.value - 1)*100).toFixed(2);
                    html += `<div>${p.marker}${p.seriesName}: <b>${v > 0 ? '+' : ''}${v}%</b> (净值 ${p.value.toFixed(4)})</div>`;
                });
                return html;
            }
        },
        legend: { data: ['策略净值(Regime)', '沪深300ETF'], textStyle: { color:'#94a3b8' }, top: 8 },
        grid: { left:'3%', right:'4%', bottom:'8%', top:'40px', containLabel: true },
        xAxis: {
            type:'category', data: dates,
            axisLine:{ lineStyle:{ color:'rgba(255,255,255,0.1)' } },
            axisLabel:{ color:'#64748b', fontSize:10,
                formatter: v => v.slice(0,7) },
            splitLine:{ show:false }
        },
        yAxis: {
            type:'value', name:'净值',
            axisLine:{ lineStyle:{ color:'rgba(255,255,255,0.1)' } },
            axisLabel:{ color:'#64748b', fontSize:10, formatter: v => v.toFixed(2) },
            splitLine:{ lineStyle:{ color:'rgba(255,255,255,0.06)' } }
        },
        series: [
            {
                name:'策略净值(Regime)', type:'line', data: equity,
                lineStyle:{ width:2.5, color:'#60a5fa' },
                itemStyle:{ color:'#60a5fa' }, smooth:true, symbol:'none',
                markArea: markAreas.length ? { silent:true, data: markAreas } : undefined,
                areaStyle:{ color:{ type:'linear', x:0,y:0,x2:0,y2:1,
                    colorStops:[{offset:0,color:'rgba(96,165,250,0.18)'},{offset:1,color:'rgba(96,165,250,0.02)'}]}},
            },
            {
                name:'沪深300ETF', type:'line', data: bm,
                lineStyle:{ width:1.5, color:'#94a3b8', type:'dashed' },
                itemStyle:{ color:'#94a3b8' }, smooth:true, symbol:'none',
            }
        ],
        dataZoom: [
            { type:'inside', start:0, end:100 },
            { type:'slider', height:18, bottom:0, borderColor:'rgba(255,255,255,0.08)',
              fillerColor:'rgba(99,102,241,0.15)', handleStyle:{ color:'#6366f1' } }
        ]
    };
    _mrBacktestChart.setOption(option);
    window.addEventListener('resize', () => _mrBacktestChart && _mrBacktestChart.resize());
}

// 页面加载后自动尝试渲染（如有缓存数据）
document.addEventListener('DOMContentLoaded', () => {
    // 延迟200ms等ECharts和DOM就绪
    setTimeout(loadMrBacktestData, 200);
});

// ====== ⚡ 红利评分器实时同步系统 ======
// 缓存最近一次 API 返回的 signals 供切换 ETF 时复用
let _divRealtimeCache = null;

/**
 * 主同步函数 —— 点击"⚡ 实时同步"按钮触发
 * 1. 调用 /api/v1/dividend_strategy（当前市场状态）
 * 2. 把选中 ETF 的 RSI/BIAS/TTM/布林带 自动映射到下拉框
 * 3. 渲染排行榜
 */
async function loadDividendRealtime() {
    const btn    = document.getElementById('div-sync-btn');
    const status = document.getElementById('div-sync-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 同步中...'; }
    if (status) status.textContent = '正在获取实时数据，请稍候...';

    const regime = document.getElementById('div-calc-regime')?.value || 'RANGE';

    try {
        const resp = await fetch(`/api/v1/dividend_strategy?regime=${regime}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        const signals = data?.data?.signals;
        if (!signals || !signals.length) throw new Error('无信号数据');

        _divRealtimeCache = signals;

        // 渲染排行榜
        renderDivLeaderboard(signals, regime);

        // 自动填充（选中ETF 或 评分最高者）
        const selected = document.getElementById('div-etf-select')?.value || '';
        const hit = selected
            ? signals.find(s => (s.code + '.SH') === selected || (s.code + '.SZ') === selected || s.code === selected.replace(/\.[A-Z]+$/, ''))
            : [...signals].sort((a, b) => b.signal_score - a.signal_score)[0];

        if (hit) fillDivInputsFromSignal(hit, regime);

        const now = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        if (status) status.innerHTML = `<span style="color:#34d399;">✓ 已同步</span> · ${now} · ${signals.length}/8只ETF`;

    } catch(e) {
        console.error('[div-sync]', e);
        if (status) status.innerHTML = `<span style="color:#f87171;">同步失败：${e.message}</span> · 请检查后端服务`;
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '⚡ 实时同步指标'; }
    }
}

/** ETF 选择器切换 —— 直接用缓存重填，不重调 API */
function onDivEtfChange() {
    if (!_divRealtimeCache) { loadDividendRealtime(); return; }
    const regime   = document.getElementById('div-calc-regime')?.value || 'RANGE';
    const selected = document.getElementById('div-etf-select')?.value || '';
    const hit = selected
        ? _divRealtimeCache.find(s => (s.code + '.SH') === selected || (s.code + '.SZ') === selected || s.code === selected.replace(/\.[A-Z]+$/, ''))
        : [..._divRealtimeCache].sort((a, b) => b.signal_score - a.signal_score)[0];
    if (hit) fillDivInputsFromSignal(hit, regime);
}

/**
 * 将 API signal 自动映射到六维下拉框
 * schema: { rsi, bias, boll_pos, ttm_yield, signal_score, close, name, code }
 */
function fillDivInputsFromSignal(sig, regime) {
    // RSI 映射
    const rsi = sig.rsi ?? 50;
    const rsiOpt = rsi <= 30 ? '20' : rsi <= 35 ? '15' : rsi <= 40 ? '10' : rsi <= 50 ? '5' : '0';
    setSelectValue('div-calc-rsi', rsiOpt);

    // BIAS 映射
    const bias = sig.bias ?? 0;
    const biasOpt = bias <= -3.0 ? '20' : bias <= -2.0 ? '15' : bias <= 0 ? '8' : '0';
    setSelectValue('div-calc-bias', biasOpt);

    // TTM 股息率 映射
    const ttm = sig.ttm_yield ?? 4.0;
    const yldOpt = ttm >= 5.0 ? '20' : ttm >= 4.0 ? '12' : ttm >= 3.0 ? '5' : '0';
    setSelectValue('div-calc-yield', yldOpt);

    // 布林带位置 映射（boll_pos 是 0-100%）
    const bp = sig.boll_pos ?? 50;
    const bollOpt = bp <= 5 ? '10' : bp <= 35 ? '6' : bp <= 70 ? '2' : '0';
    setSelectValue('div-calc-boll', bollOpt);

    // 波动率：红利ETF固有低波，默认满分
    setSelectValue('div-calc-vol', '10');

    // 触发重新计算
    calcDividendScore();

    // 高亮排行榜卡片
    document.querySelectorAll('.div-lb-card').forEach(c => {
        const isActive = c.dataset.code === sig.code;
        c.style.borderColor = isActive ? 'rgba(96,165,250,0.6)' : 'rgba(255,255,255,0.08)';
        c.style.background  = isActive ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.02)';
    });
}

/** 安全设置 select value */
function setSelectValue(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    for (let opt of el.options) {
        if (opt.value === val) { el.value = val; return; }
    }
}

/**
 * 前端补算单只ETF评分（与后端 score_etf() 完全对齐）
 * 在 signal_score 字段缺失时作为兜底
 */
function computeDivScore(s, regime) {
    const envScore = { BULL: 20, RANGE: 12, BEAR: 5, CRASH: 0 }[regime] ?? 12;

    const rsi = s.rsi ?? 50;
    const rsiScore = rsi <= 30 ? 20 : rsi <= 35 ? 15 : rsi <= 40 ? 10 : rsi <= 50 ? 5 : 0;

    const bias = s.bias ?? 0;
    const biasScore = bias <= -3.0 ? 20 : bias <= -2.0 ? 15 : bias <= 0 ? 8 : 0;

    const ttm = s.ttm_yield ?? 4.0;
    const yldScore = ttm >= 5.0 ? 20 : ttm >= 4.0 ? 12 : ttm >= 3.0 ? 5 : 0;

    const bp = s.boll_pos ?? 50;
    const bollScore = bp <= 5 ? 10 : bp <= 35 ? 6 : bp <= 70 ? 2 : 0;

    const volScore = 10; // 红利ETF固有低波

    return Math.min(envScore + rsiScore + biasScore + yldScore + bollScore + volScore, 100);
}

/**
 * 渲染8只ETF评分排行榜（4列网格，按分降序，可点击切换）
 */
function renderDivLeaderboard(signals, regime) {
    const lb   = document.getElementById('div-leaderboard');
    const list = document.getElementById('div-leaderboard-list');
    if (!lb || !list) return;

    // 对每个 signal 补全前端计算的分数（后端缺字段时兜底）
    const enriched = signals.map(s => ({
        ...s,
        _score: (s.signal_score != null) ? s.signal_score : computeDivScore(s, regime)
    }));
    const sorted = [...enriched].sort((a, b) => b._score - a._score);
    const gates  = { BULL: 55, RANGE: 65, BEAR: 75, CRASH: 999 };
    const gate   = gates[regime] ?? 65;

    list.innerHTML = sorted.map((s, i) => {
        const score = s._score ?? 0;
        const sigEl = s.signal === 'buy'  ? '<span style="color:#10b981;font-weight:700;">买入▲</span>'
                    : s.signal === 'sell' ? '<span style="color:#f87171;font-weight:700;">卖出▼</span>'
                    :                       '<span style="color:#fbbf24;">持有━</span>';
        const barColor = score >= gate + 15 ? '#10b981'
                       : score >= gate      ? '#60a5fa'
                       : score >= gate * 0.85 ? '#fbbf24' : '#f87171';
        const rank = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i+1}`;

        return `<div class="div-lb-card" data-code="${s.code}"
             onclick="selectDivEtfFromBoard('${s.code}')"
             style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.08);
                    border-radius:10px; padding:10px 12px; cursor:pointer; transition:all 0.2s;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:0.7rem; color:#a78bfa; font-weight:700;">${rank}</span>
                ${sigEl}
            </div>
            <div style="font-size:0.72rem; color:#e2e8f0; font-weight:600; margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${s.name}">${s.name}</div>
            <div style="font-size:0.65rem; color:var(--text-muted); margin-bottom:8px;">${s.code} · ¥${s.close}</div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <span style="font-size:0.65rem; color:var(--text-muted);">评分</span>
                <span style="font-size:1.05rem; font-weight:900; color:${barColor};">${score}</span>
            </div>
            <div style="height:4px; background:rgba(255,255,255,0.06); border-radius:2px; overflow:hidden;">
                <div style="height:100%; width:${Math.min(score,100)}%; background:${barColor}; border-radius:2px;"></div>
            </div>
            <div style="font-size:0.62rem; color:var(--text-muted); margin-top:5px;">RSI ${s.rsi} · TTM ${s.ttm_yield}%</div>
        </div>`;
    }).join('');

    lb.style.display = 'block';
}

/** 排行榜卡片点击 → 更新选择器 + 填充指标 */
function selectDivEtfFromBoard(code) {
    // code 形如 "515100"（无后缀），尝试两种后缀
    const sel = document.getElementById('div-etf-select');
    if (sel) {
        const matchSH = code + '.SH';
        const matchSZ = code + '.SZ';
        let found = false;
        for (let opt of sel.options) {
            if (opt.value === matchSH || opt.value === matchSZ) {
                sel.value = opt.value; found = true; break;
            }
        }
        if (!found) sel.value = '';
    }
    onDivEtfChange();
}


// ====== 市场环境自动识别 ======
const REGIME_CACHE_KEY = 'alphacore_regime_cache';
// 盘中(09:30-15:00)2分钟刷新 / 盘后15分钟
function _getRegimeCacheTTL() {
    const h = new Date().getHours(), m = new Date().getMinutes();
    const inSession = (h === 9 && m >= 30) || (h >= 10 && h < 15);
    return inSession ? 2 * 60 * 1000 : 15 * 60 * 1000;
}
const REGIME_CACHE_TTL = _getRegimeCacheTTL();

async function loadMarketRegime(forceRefresh = false) {
    const loadEl  = document.getElementById('regime-loading');
    const resEl   = document.getElementById('regime-result');
    const errEl   = document.getElementById('regime-error');
    const btnEl   = document.getElementById('regime-refresh-btn');

    if (!loadEl) return; // tab not yet rendered

    // Check cache
    if (!forceRefresh) {
        try {
            const cached = JSON.parse(sessionStorage.getItem(REGIME_CACHE_KEY) || 'null');
            if (cached && (Date.now() - cached._ts) < REGIME_CACHE_TTL) {
                renderRegime(cached);
                return;
            }
        } catch(_) {}
    }

    // Show loading
    loadEl.style.display = 'flex';
    resEl.style.display  = 'none';
    errEl.style.display  = 'none';
    if (btnEl) { btnEl.disabled = true; btnEl.textContent = '⏳ 识别中...'; }

    try {
        const resp = await fetch(`${API_URL}/api/v1/market/regime`, { cache: 'no-cache' });
        const data = await resp.json();

        if (data.status !== 'ok') throw new Error(data.message || 'API error');

        data._ts = Date.now();
        sessionStorage.setItem(REGIME_CACHE_KEY, JSON.stringify(data));
        renderRegime(data);
    } catch (err) {
        loadEl.style.display = 'none';
        errEl.style.display  = 'block';
        errEl.innerHTML = `⚠️ 市场识别失败：${err.message || '网络异常'}，请点击「重新识别」。`;
    } finally {
        if (btnEl) { btnEl.disabled = false; btnEl.textContent = '🔄 重新识别'; }
    }
}

function renderRegime(d) {
    const loadEl = document.getElementById('regime-loading');
    const resEl  = document.getElementById('regime-result');
    if (!resEl) return;
    loadEl.style.display = 'none';
    resEl.style.display  = 'block';

    const clr = d.regime_color || '#fbbf24';
    const p   = d.optimal_params || {};

    // Badge — use API color directly (no local meta dependency)
    const badge = document.getElementById('regime-badge');
    if (badge) {
        badge.style.borderColor = clr + '55';
        badge.style.background  = clr + '15';
        const regKey = (d.regime || 'RANGE').toLowerCase();
        badge.className = badge.className.replace(/regime-\w+-glow/g, '');
        badge.classList.add(`regime-${regKey}-glow`);
    }
    _setText('regime-icon-text', d.regime_icon  || '🟡');
    _setText('regime-name-cn',   d.regime_cn    || d.regime);
    _setText('regime-name-en',   (d.regime || 'RANGE') + ' MODE');
    _setColor('regime-name-cn',  clr);
    _setText('regime-desc-text', d.regime_desc  || '');

    // Metrics
    _setText('rm-csi',    d.csi300?.toFixed(0) ?? '—');
    _setText('rm-ma120',  d.ma120?.toFixed(0)  ?? '—');

    // Field names matched to backend
    const r5  = d.ret5d  ?? 0;
    const r20 = d.ret20d ?? 0;
    const el5  = document.getElementById('rm-ret5');
    const el20 = document.getElementById('rm-ret20');
    if (el5)  { el5.textContent  = (r5  >= 0 ? '+' : '') + r5.toFixed(2)  + '%'; el5.style.color  = r5  >= 0 ? '#10b981' : '#f87171'; }
    if (el20) { el20.textContent = (r20 >= 0 ? '+' : '') + r20.toFixed(2) + '%'; el20.style.color = r20 >= 0 ? '#10b981' : '#f87171'; }

    const slope = d.ma120_slope5 ?? 0;
    const slopeEl = document.getElementById('rm-slope');
    if (slopeEl) {
        slopeEl.textContent = (slope >= 0 ? '↑ +' : '↓ ') + slope.toFixed(4);
        slopeEl.style.color = slope >= 0 ? '#10b981' : '#f87171';
    }
    _setText('rm-vol', (d.vol20d?.toFixed(1) ?? '—') + '%');

    // Adaptive params
    _setText('rm-p-topn',  p.top_n           ?? 3);
    _setText('rm-p-rb',    p.rebalance_days  ?? 5);
    _setText('rm-p-poscap',p.pos_cap         ?? 66);
    const slETF = p.stop_loss ?? -8;
    _setText('rm-p-sl', `ETF${slETF} / 股-10`);
    _setText('rm-p-gate',  p.entry_threshold ?? 65);
    _setText('regime-param-note', p.note || '');

    // Sync gate score display
    _setText('regime-sync-gate', p.entry_threshold ?? 65);
    _setColor('regime-sync-gate', clr);

    // Auto-sync to calc-regime dropdown
    const regEl = document.getElementById('calc-regime');
    if (regEl) {
        const regVal = d.regime === 'BULL' ? '20' : d.regime === 'BEAR' ? '0' : '12';
        regEl.value = regVal;
        calcSignalScore();
    }

    // V3.1: 自动同步市场状态到红利专属评分器
    const divRegEl = document.getElementById('div-calc-regime');
    if (divRegEl) {
        const regime = d.regime || 'RANGE';
        // 映射：BULL/RANGE/BEAR/CRASH
        const validRegimes = ['BULL', 'RANGE', 'BEAR', 'CRASH'];
        divRegEl.value = validRegimes.includes(regime) ? regime : 'RANGE';
        calcDividendScore();
    }

    // Apply regime-specific color to panel border
    const panel = document.getElementById('regime-panel');
    if (panel) panel.style.borderColor = clr + '44';

    // V4.2: 联动入场门槛决策台动态数字
    const regimeKey = (d.regime || 'RANGE');
    const gateMap = { BULL: 75, RANGE: 68, BEAR: 78 };
    const curGate = gateMap[regimeKey] || 68;
    const curHalf = Math.round(curGate * 0.85);
    const curFull = Math.min(curGate + 15, 95);
    _setText('gate-reject', `< ${curHalf}`);
    _setText('gate-half',   `≥ ${curHalf}`);
    _setText('gate-standard', `≥ ${curGate}`);
    _setText('gate-full',   `≥ ${curFull}`);
    _setText('hero-entry-gate', `${regimeKey} ≥${curGate}分`);
}

function _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
function _setColor(id, color) {
    const el = document.getElementById(id);
    if (el) el.style.color = color;
}


document.addEventListener('DOMContentLoaded', () => {
    // 导航
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const href = item.getAttribute('href');
            if (!href || href === '#') e.preventDefault();
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });

    // 实时时间
    function updateTime() {
        const now = new Date();
        const pad = n => n.toString().padStart(2, '0');
        const el = document.getElementById('st-time');
        if (el) el.textContent = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    }
    updateTime();
    setInterval(updateTime, 1000);

    // 策略标签切换
    const tabs = document.querySelectorAll('.st-tab');
    const reports = document.querySelectorAll('.st-report');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.dataset.report;
            tabs.forEach(t => t.classList.remove('active'));
            reports.forEach(r => r.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(targetId);
            if (target) target.classList.add('active');
            document.querySelector('.dashboard').scrollTo({ top: 0, behavior: 'smooth' });
            // 切换到信号评分系统时自动触发市场识别
            if (targetId === 'st-signal-rules') {
                setTimeout(() => loadMarketRegime(), 100);
            }
            // 切换到ERP择时时自动加载数据
            if (targetId === 'st-erp-timing') {
                setTimeout(() => loadERPTimingData(), 100);
            }
            // 切换到AIAE宏观仓位时自动加载数据
            if (targetId === 'st-aiae-position') {
                setTimeout(() => loadAIAEReport(), 100);
            }
        });
    });
});

// ====== 全局策略执行函数 V2.0 ======
async function runStrategy() {
    const btn = document.getElementById('st-run-btn');
    const timeEl = document.getElementById('st-data-time');
    const strategyType = document.getElementById('st-strategy-select')?.value || 'run-all';

    const safelySetText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    const safelySetHTML = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

    // 隐藏所有结果区
    ['st-results-mr', 'st-results-dt', 'st-results-mom', 'exec-zone1', 'exec-zone23', 'exec-zone4', 'exec-zone5', 'exec-zone6'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    if (btn) { btn.disabled = true; btn.textContent = '⏳ 运行中...'; }

    // === run-all 模式 ===
    if (strategyType === 'run-all') {
        const progressBar = document.getElementById('exec-progress-bar');
        const progressText = document.getElementById('exec-progress-text');
        if (progressBar) progressBar.style.display = 'block';

        // 进度动画
        const setProgress = (stage, text) => {
            for (let i = 1; i <= 5; i++) {
                const seg = document.getElementById(`prog-seg-${i}`);
                if (seg) seg.style.background = i <= stage ? 'linear-gradient(90deg, #6366f1, #8b5cf6)' : 'rgba(255,255,255,0.06)';
            }
            if (progressText) progressText.textContent = text;
        };
        setProgress(1, '🔄 正在并行拉取4策略数据...');

        try {
            const timer2 = setTimeout(() => setProgress(2, '📊 均值回归 + 红利趋势 + 动量轮动 + ERP择时 + AIAE标的池计算中...'), 5000);
            const timer3 = setTimeout(() => setProgress(3, '🔗 五策略共振分析 + AIAE主控仓位调节中...'), 12000);

            const resp = await fetch(`${API_URL}/api/v1/strategy/run-all`);
            const json = await resp.json();

            clearTimeout(timer2); clearTimeout(timer3);
            setProgress(4, '✅ 完成！正在渲染仪表盘...');

            if (json.status !== 'success') throw new Error(json.message || '全量运行失败');

            if (timeEl) timeEl.textContent = `数据截至 ${json.timestamp.substring(0, 16).replace('T', ' ')}`;

            // 渲染V2.0仪表盘
            renderExecutionDashboard(json.data, { safelySetText, safelySetHTML });

            setTimeout(() => { if (progressBar) progressBar.style.display = 'none'; }, 1500);

        } catch (err) {
            setProgress(0, `❌ ${err.message}`);
            console.error('[run-all]', err);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '🚀 运行策略'; }
        }
        return;
    }

    // === Legacy 单策略模式 ===
    try {
        let endpoint;
        if (strategyType === 'dividend-trend') endpoint = `${API_URL}/api/v1/dividend_strategy`;
        else if (strategyType === 'momentum') endpoint = `${API_URL}/api/v1/momentum_strategy`;
        else endpoint = `${API_URL}/api/v1/strategy`;

        const resp = await fetch(endpoint);
        const json = await resp.json();
        if (json.status !== 'success') throw new Error(json.message || '策略执行失败');
        if (timeEl) timeEl.textContent = `数据截至 ${json.timestamp.substring(0, 16).replace('T', ' ')}`;

        const mrResults = document.getElementById('st-results-mr');
        const dtResults = document.getElementById('st-results-dt');
        const momResults = document.getElementById('st-results-mom');

        if (strategyType === 'dividend-trend') {
            renderDividendResults(json.data, { safelySetText, safelySetHTML });
            if (dtResults) dtResults.style.display = 'block';
        } else if (strategyType === 'momentum') {
            renderMomentumResults(json.data, { safelySetText, safelySetHTML });
            if (momResults) momResults.style.display = 'block';
        } else {
            renderMeanReversionResults(json.data, { safelySetText, safelySetHTML });
            if (mrResults) mrResults.style.display = 'block';
        }
    } catch (err) {
        console.error('[strategy]', err);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🚀 运行策略'; }
    }
}

// ====== V2.0 执行仪表盘总入口 ======
function renderExecutionDashboard(data, helpers) {
    const { safelySetText, safelySetHTML } = helpers;
    const g = data.global || {};
    const resonance = data.resonance || {};
    const risk = data.risk_overlay || {};

    // --- Zone 1: 仪表盘 + KPI ---
    const zone1 = document.getElementById('exec-zone1');
    if (zone1) zone1.style.display = 'block';

    // 仪表盘
    const pos = g.total_position || 0;
    safelySetText('exec-gauge-label', pos + '%');
    renderExecGauge(pos);

    // 仪表盘下方 regime cap 注释 (V2.0: AIAE×ERP 双维决策)
    const regimeCapEl = document.getElementById('exec-gauge-regime-cap');
    if (regimeCapEl) {
        const regimeCN = { 'BULL': '牛市', 'RANGE': '震荡', 'BEAR': '熊市', 'CRASH': '危机' };
        const aiae = g.aiae || {};
        const regimeEmoji = {1:'🟢',2:'🔵',3:'🟡',4:'🟠',5:'🔴'};
        if (aiae.override_active) {
            regimeCapEl.textContent = `手动覆盖Cap ${g.regime_cap}% (原始 ${aiae.original_cap}%)`;
            regimeCapEl.style.color = '#ef4444';
        } else {
            const erpTierText = aiae.erp_score_tier || '🟡中性';
            const _regimeNumeral = {1:'Ⅰ',2:'Ⅱ',3:'Ⅲ',4:'Ⅳ',5:'Ⅴ'};
            const _statusTag = {1:'满配进攻',2:'标准建仓',3:'均衡持有',4:'系统减仓',5:'清仓防守'};
            const _regimeCapColors = {1:'#10b981',2:'#3b82f6',3:'#eab308',4:'#f97316',5:'#ef4444'};
            const numeral = _regimeNumeral[aiae.regime] || 'Ⅲ';
            regimeCapEl.textContent = `${regimeEmoji[aiae.regime] || '🟡'}${numeral}${aiae.regime_cn || '中性均衡'} × ERP${erpTierText} → ${_statusTag[aiae.regime] || '均衡持有'} [Floor${aiae.regime_floor || '?'}%-Cap${g.regime_cap || 100}%]`;
            regimeCapEl.style.color = _regimeCapColors[aiae.regime] || '#94a3b8';
        }
    }

    // AIAE 主控状态徽章 (V2.0: 增加ERP联动标识)
    const aiaeBadge = document.getElementById('exec-aiae-badge');
    if (aiaeBadge && g.aiae) {
        const a = g.aiae;
        const regimeEmoji = {1:'🟢',2:'🔵',3:'🟡',4:'🟠',5:'🔴'};
        const erpTierText = a.erp_score_tier || '🟡中性';
        aiaeBadge.textContent = `🌡️ AIAE ${regimeEmoji[a.regime]||''} ${a.regime_cn} × ERP${erpTierText} · V1=${(a.aiae_value||0).toFixed(1)}% · Cap ${a.aiae_cap}%`;
        aiaeBadge.style.borderColor = a.regime <= 2 ? 'rgba(16,185,129,0.4)' : a.regime >= 4 ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.4)';
    }

    // 权重条动态更新 (V2.1: AIAE×ERP联合权重 → flex + tooltip + 百分比标签)
    const w = g.weights || {};
    if (w.mr !== undefined) {
        const gwMr = document.getElementById('gw-mr');
        const gwDiv = document.getElementById('gw-div');
        const gwMom = document.getElementById('gw-mom');
        const gwErp = document.getElementById('gw-erp');
        const gwAiae = document.getElementById('gw-aiae');
        if (gwMr)   { gwMr.style.flex = w.mr;        gwMr.title = `均值回归 ${Math.round(w.mr*100)}%`; }
        if (gwDiv)  { gwDiv.style.flex = w.div;       gwDiv.title = `红利趋势 ${Math.round(w.div*100)}%`; }
        if (gwMom)  { gwMom.style.flex = w.mom;       gwMom.title = `行业动量 ${Math.round(w.mom*100)}%`; }
        if (gwErp)  { gwErp.style.flex = w.erp;       gwErp.title = `ERP择时 ${Math.round(w.erp*100)}%`; }
        if (gwAiae) { gwAiae.style.flex = w.aiae_etf || 0.25; gwAiae.title = `AIAE宏观 ${Math.round((w.aiae_etf||0.25)*100)}%`; }
        // 更新权重百分比文本 (如存在)
        const gwPctLabels = document.querySelectorAll('.gw-pct-label');
        if (gwPctLabels.length >= 5) {
            gwPctLabels[0].textContent = `${Math.round(w.mr*100)}%`;
            gwPctLabels[1].textContent = `${Math.round(w.div*100)}%`;
            gwPctLabels[2].textContent = `${Math.round(w.mom*100)}%`;
            gwPctLabels[3].textContent = `${Math.round(w.erp*100)}%`;
            gwPctLabels[4].textContent = `${Math.round((w.aiae_etf||0.25)*100)}%`;
        }
    }
    // 权重条下方：各策略信心度 (5策略)
    const conf = g.confidence || {};
    const confLabels = document.querySelectorAll('.gw-conf-label');
    if (confLabels.length >= 5) {
        confLabels[0].textContent = `MR ${conf.mr || 0}%`;
        confLabels[1].textContent = `DIV ${conf.div || 0}%`;
        confLabels[2].textContent = `MOM ${conf.mom || 0}%`;
        confLabels[3].textContent = `ERP ${conf.erp || 0}%`;
        confLabels[4].textContent = `AIAE ${conf.aiae_etf || 0}%`;
    }

    // KPI cards
    const regimeMap = { 'BULL': '🟢 牛市', 'RANGE': '🟡 震荡', 'BEAR': '🟠 熊市', 'CRASH': '🔴 危机' };
    const regimeColor = { 'BULL': '#10b981', 'RANGE': '#eab308', 'BEAR': '#f59e0b', 'CRASH': '#ef4444' };
    safelySetHTML('exec-regime', `<span style="color:${regimeColor[g.regime] || '#3b82f6'}">${regimeMap[g.regime] || g.regime}</span>`);
    safelySetHTML('exec-buy-total', `<span style="color:#10b981">${g.total_buy || 0} 只</span>`);
    safelySetHTML('exec-sell-total', `<span style="color:#ef4444">${g.total_sell || 0} 只</span>`);
    safelySetHTML('exec-consistency', g.consistency === 'high'
        ? '<span style="color:#10b981">✅ 高一致</span>'
        : '<span style="color:#f59e0b">⚠️ 分歧</span>');
    safelySetText('exec-resonance-count', resonance.total_overlap || 0);
    safelySetHTML('exec-vol-alerts', risk.alert_count > 0
        ? `<span style="color:#ef4444">${risk.alert_count} 只</span>`
        : '<span style="color:#10b981">0</span>');

    // 新增KPI: ERP评分 + 覆盖标的
    const erpScore = g.erp_score || 0;
    const erpColor = erpScore >= 55 ? '#10b981' : erpScore >= 40 ? '#f59e0b' : '#ef4444';
    safelySetHTML('exec-erp-score', `<span style="color:${erpColor}">${erpScore}</span>`);
    const totalCoverage = (data.strategies.mr?.signals?.length || 0) + (data.strategies.div?.signals?.length || 0) + (data.strategies.mom?.signals?.length || 0) + (data.strategies.erp?.signals?.length || 0) + (data.strategies.aiae_etf?.signals?.length || 0);
    safelySetHTML('exec-coverage', `<span style="color:#a78bfa">${totalCoverage} <span style="font-size:0.6rem;color:var(--text-muted)">只</span></span>`);

    // --- Zone 2+3: 行动信号 + 风险预警 ---
    const zone23 = document.getElementById('exec-zone23');
    if (zone23) zone23.style.display = 'block';
    renderTopSignals(data.strategies, helpers);
    renderRiskOverlay(risk, helpers);

    // --- Zone 4: 信号矩阵 ---
    const zone4 = document.getElementById('exec-zone4');
    if (zone4) zone4.style.display = 'block';

    // 全局存储策略数据供tab切换使用
    window._execStrategies = data.strategies;
    renderHeatmapTable('mr', data.strategies.mr);
    renderHeatmapTable('div', data.strategies.div);
    renderHeatmapTable('mom', data.strategies.mom);
    renderHeatmapTable('erp', data.strategies.erp);
    renderHeatmapTable('aiae_etf', data.strategies.aiae_etf);

    // 更新tab计数
    const mrSigs = (data.strategies.mr?.signals || []).length;
    const divSigs = (data.strategies.div?.signals || []).length;
    const momSigs = (data.strategies.mom?.signals || []).length;
    const erpSigs = (data.strategies.erp?.signals || []).length;
    const aiaeSigs = (data.strategies.aiae_etf?.signals || []).length;
    safelySetText('exec-mr-count', mrSigs);
    safelySetText('exec-div-count', divSigs);
    safelySetText('exec-mom-count', momSigs);
    safelySetText('exec-erp-count', erpSigs);
    safelySetText('exec-aiae-count', aiaeSigs);

    // ERP宏观评分徽章 (erpScore 已在上方声明)
    const erpBadge = document.getElementById('erp-macro-score-badge');
    if (erpBadge) {
        erpBadge.textContent = `综合分: ${erpScore}`;
        erpBadge.style.color = erpScore >= 55 ? '#10b981' : erpScore >= 40 ? '#f59e0b' : '#ef4444';
    }

    // ERP仓位屏障警告
    if (g.erp_cap_active) {
        const capWarning = document.createElement('div');
        capWarning.className = 'erp-cap-warning';
        capWarning.innerHTML = `⚠️ <strong>ERP宏观屏障激活</strong>：宏观评分 ${g.erp_score} ≤ 40，全局仓位上限已压至 <strong>30%</strong>。当前市场环境不利于权益配置。`;
        zone1?.querySelector('.st-section')?.prepend(capWarning);
    }

    // --- 智能预警横幅 ---
    renderSmartAlert(g, risk, resonance);

    // --- Zone 5: 共振分析 ---
    const zone5 = document.getElementById('exec-zone5');
    if (zone5) zone5.style.display = 'block';
    renderResonancePanel(resonance, helpers);

    // --- Zone 6: 规则百科 ---
    const zone6 = document.getElementById('exec-zone6');
    if (zone6) zone6.style.display = 'block';
}

// ====== 仪表盘渲染 ======
function renderExecGauge(value) {
    const container = document.getElementById('exec-gauge-container');
    if (!container || typeof echarts === 'undefined') return;

    let chart = echarts.getInstanceByDom(container);
    if (!chart) chart = echarts.init(container, 'dark');

    const color = value >= 60 ? '#10b981' : value >= 30 ? '#eab308' : '#ef4444';
    chart.setOption({
        series: [{
            type: 'gauge', startAngle: 180, endAngle: 0, min: 0, max: 100,
            radius: '100%', center: ['50%', '85%'],
            progress: { show: true, width: 14, roundCap: true, itemStyle: { color } },
            pointer: { show: false },
            axisLine: { lineStyle: { width: 14, color: [[1, 'rgba(255,255,255,0.06)']] } },
            axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
            detail: { show: false },
            data: [{ value: Math.min(value, 100) }]
        }]
    });
}

// ====== 智能预警横幅渲染 ======
function renderSmartAlert(g, risk, resonance) {
    const el = document.getElementById('exec-smart-alert');
    if (!el) return;

    let level, icon, title, sub;

    if (g.regime === 'CRASH') {
        level = 'crash'; icon = '🚨'; title = '危机模式！建议空仓避险';
        sub = '市场处于极端下跌状态，所有策略信号均暂停。待市场稳定后重新评估。';
    } else if ((g.aiae?.erp_tier || '') === 'bear') {
        level = 'danger'; icon = '🛡️'; title = `ERP看空(${g.erp_score}分) × AIAE联合调节：权重已切换至防御模式`;
        sub = 'JOINT_WEIGHTS矩阵已自动增配红利+AIAE权重、削减MR/MOM，无需手动干预。待ERP≥55再恢复进攻。';
    } else if (g.consistency !== 'high') {
        level = 'warning'; icon = '⚠️'; title = '策略方向分歧，建议降低仓位或观望';
        sub = '多个策略对市场方向判断不一致。分歧时建议按单策略仓位上限执行，不叠加。';
    } else if ((risk.alert_count || 0) >= 3) {
        level = 'caution'; icon = '⚡'; title = `${risk.alert_count}只标的波动率异常，注意持仓分散`;
        sub = '30日年化波动率超过25%的标的较多。建议单只仓位不超过总仓的20%，避免集中风险。';
    } else {
        level = 'ok'; icon = '✅'; title = '市场环境正常，策略信号可执行';
        sub = `5策略一致看${g.regime === 'BULL' ? '多' : '稳'}，共振标的 ${resonance.total_overlap || 0} 只。按评分优先级执行即可。`;
    }

    el.style.display = 'block';
    el.innerHTML = `<div class="smart-alert smart-alert-${level}">
        <span class="smart-alert-icon">${icon}</span>
        <div class="smart-alert-text">
            <div>${title}</div>
            <div class="smart-alert-sub">${sub}</div>
        </div>
    </div>`;
}

// ====== Top 行动信号渲染 ======
function renderTopSignals(strategies, { safelySetHTML }) {
    const allSignals = [];
    ['mr', 'div', 'mom', 'erp', 'aiae_etf'].forEach(key => {
        const sigs = strategies[key]?.signals || [];
        sigs.forEach(s => {
            if (s.signal === 'buy' || s.signal === 'sell' || s.signal === 'sell_half' || s.signal === 'sell_weak') {
                allSignals.push({ ...s, source: key });
            }
        });
    });

    const sourceLabel = { mr: '均值回归', div: '红利趋势', mom: '动量轮动', erp: 'ERP择时', aiae_etf: 'AIAE标的' };
    const buys = allSignals.filter(s => s.signal === 'buy').sort((a, b) => (b.signal_score || 0) - (a.signal_score || 0)).slice(0, 3);
    const sells = allSignals.filter(s => s.signal !== 'buy').sort((a, b) => (a.signal_score || 100) - (b.signal_score || 100)).slice(0, 3);

    let html = '';
    if (buys.length === 0 && sells.length === 0) {
        html = '<p style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:16px 0;">当前无强信号</p>';
    }
    buys.forEach(s => {
        const srcTag = `<span class="source-tag source-${s.source}">${sourceLabel[s.source]}</span>`;
        html += `<div class="top-signal-card top-signal-buy">
            <div><strong style="color:#fff;font-size:0.88rem;">${s.name || ''}${srcTag}</strong>
            <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">${s.ts_code || s.code || ''}</div></div>
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="st-ai-score st-ai-score-buy">${s.signal_score || 0}分</span>
                <span style="font-size:0.78rem;color:var(--text-muted)">${s.suggested_position || 0}%</span>
            </div></div>`;
    });
    sells.forEach(s => {
        const srcTag = `<span class="source-tag source-${s.source}">${sourceLabel[s.source]}</span>`;
        html += `<div class="top-signal-card top-signal-sell">
            <div><strong style="color:#fff;font-size:0.88rem;">${s.name || ''}${srcTag}</strong>
            <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">${s.ts_code || s.code || ''}</div></div>
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="st-ai-score st-ai-score-sell">${s.signal_score || 0}分</span>
                <span style="font-size:0.78rem;color:var(--text-muted)">${s.suggested_position || 0}%</span>
            </div></div>`;
    });

    safelySetHTML('exec-top-signals', html);
}

// ====== 风险预警渲染 ======
function renderRiskOverlay(risk, { safelySetHTML }) {
    let html = '';
    const conc = risk.concentration || {};
    if (conc.top_sector && conc.top_sector !== 'N/A') {
        html += `<div class="risk-alert-item risk-concentration">
            <span style="font-size:1.1rem;">📊</span>
            <div><strong style="color:#fbbf24;font-size:0.82rem;">行业集中度</strong>
            <div style="font-size:0.78rem;color:var(--text-muted);margin-top:2px;">最集中板块：${conc.top_sector} (${conc.ratio})</div></div></div>`;
    }
    const volAlerts = risk.volatility_alerts || [];
    if (volAlerts.length > 0) {
        html += `<div class="risk-alert-item">
            <span style="font-size:1.1rem;">⚡</span>
            <div><strong style="color:#f87171;font-size:0.82rem;">高波动标的 (${volAlerts.length}只)</strong>
            <div style="font-size:0.78rem;color:var(--text-muted);margin-top:2px;">${volAlerts.map(v => `${v.name} ${v.vol_30d}%`).join(' / ')}</div></div></div>`;
    }
    if (!html) html = '<p style="color:#10b981;font-size:0.85rem;text-align:center;padding:16px 0;">✅ 风险正常，无预警</p>';
    safelySetHTML('exec-risk-overlay', html);
}

// ====== 热力紧凑表渲染 ======
function renderHeatmapTable(strategyKey, strategyData) {
    const tbody = document.getElementById(`exec-tbody-${strategyKey}`);
    if (!tbody) return;

    const signals = strategyData?.signals || [];
    if (signals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px;">暂无数据</td></tr>';
        return;
    }

    // 按信号排序：buy > hold > sell
    const signalOrder = { buy: 0, hold: 1, sell: 2, sell_half: 2, sell_weak: 2 };
    signals.sort((a, b) => (signalOrder[a.signal] || 1) - (signalOrder[b.signal] || 1) || (b.signal_score || 0) - (a.signal_score || 0));

    let html = '';
    signals.forEach(s => {
        const score = s.signal_score || 0;
        const tier = score >= 85 ? 5 : score >= 70 ? 4 : score >= 50 ? 3 : score >= 30 ? 2 : 1;
        const signal = s.signal || 'hold';
        const tagClass = signal === 'buy' ? 'st-tag-buy' : (signal.includes('sell') ? 'st-tag-sell' : 'st-tag-hold');
        const tagLabel = signal === 'buy' ? '买入' : signal === 'sell_half' ? '减半' : signal.includes('sell') ? '卖出' : '持有';
        const rowClass = signal === 'buy' ? 'st-row-buy' : signal.includes('sell') ? 'st-row-sell' : '';

        // 关键因子紧凑展示 + 阈值着色
        let factors = '';
        if (strategyKey === 'mr') {
            const pctBcls = s.pctB !== undefined ? (s.pctB < 0.2 ? 'f-val-good' : s.pctB > 0.8 ? 'f-val-danger' : '') : '';
            const rsicls = s.rsi3 !== undefined ? (s.rsi3 < 20 ? 'f-val-good' : s.rsi3 > 80 ? 'f-val-danger' : '') : '';
            const biascls = s.bias !== undefined ? (s.bias < -5 ? 'f-val-good' : s.bias > 5 ? 'f-val-danger' : '') : '';
            factors = `<span class="f-key">%B:</span><span class="f-val ${pctBcls}">${s.pctB !== undefined ? s.pctB.toFixed(2) : '-'}</span> <span class="f-key">RSI:</span><span class="f-val ${rsicls}">${s.rsi3 !== undefined ? Math.round(s.rsi3) : '-'}</span> <span class="f-key">BIAS:</span><span class="f-val ${biascls}">${s.bias !== undefined ? s.bias.toFixed(1) + '%' : '-'}</span>`;
        } else if (strategyKey === 'div') {
            const divcls = s.dividend_yield !== undefined ? (s.dividend_yield > 6 ? 'f-val-good' : s.dividend_yield < 3 ? 'f-val-warn' : '') : '';
            const rsicls = s.rsi_14 !== undefined ? (s.rsi_14 < 30 ? 'f-val-good' : s.rsi_14 > 70 ? 'f-val-danger' : '') : '';
            factors = `<span class="f-key">DIV:</span><span class="f-val ${divcls}">${s.dividend_yield !== undefined ? s.dividend_yield.toFixed(1) + '%' : '-'}</span> <span class="f-key">RSI:</span><span class="f-val ${rsicls}">${s.rsi_14 !== undefined ? Math.round(s.rsi_14) : '-'}</span> <span class="f-key">BIAS:</span><span class="f-val">${s.bias !== undefined ? s.bias.toFixed(1) + '%' : '-'}</span>`;
        } else if (strategyKey === 'erp') {
            const m1cls = s.m1_yoy !== undefined ? (s.m1_yoy > 0 ? 'f-val-good' : 'f-val-danger') : '';
            factors = `<span class="f-key">ERP:</span><span class="f-val">${s.erp_abs !== undefined ? s.erp_abs.toFixed(2) + '%' : '-'}</span> <span class="f-key">分位:</span><span class="f-val">${s.erp_pct !== undefined ? s.erp_pct.toFixed(0) + '%' : '-'}</span> <span class="f-key">M1:</span><span class="f-val ${m1cls}">${s.m1_yoy !== undefined ? s.m1_yoy.toFixed(1) + '%' : '-'}</span>`;
        } else if (strategyKey === 'aiae_etf') {
            // V4.0: AIAE ETF专属因子展示
            const regimeEmoji = {1:'🟢',2:'🔵',3:'🟡',4:'🟠',5:'🔴'};
            factors = `<span class="f-key">档位:</span><span class="f-val">${regimeEmoji[s.aiae_regime] || ''} ${s.aiae_regime || '-'}</span> <span class="f-key">类型:</span><span class="f-val">${s.etf_type || s.style || '-'}</span> <span class="f-key">仓位:</span><span class="f-val" style="color:#fbbf24;font-weight:700;">${s.suggested_position || 0}%</span>`;
        } else {
            const momcls = s.momentum_20d !== undefined ? (s.momentum_20d > 5 ? 'f-val-good' : s.momentum_20d < -3 ? 'f-val-danger' : '') : '';
            const volcls = s.volume_ratio !== undefined ? (s.volume_ratio > 1.5 ? 'f-val-good' : s.volume_ratio < 0.7 ? 'f-val-warn' : '') : '';
            factors = `<span class="f-key">MOM:</span><span class="f-val ${momcls}">${s.momentum_20d !== undefined ? s.momentum_20d.toFixed(1) + '%' : '-'}</span> <span class="f-key">VOL:</span><span class="f-val ${volcls}">${s.volume_ratio !== undefined ? s.volume_ratio.toFixed(1) + 'x' : '-'}</span> <span class="f-key">RSI:</span><span class="f-val">${s.rsi_14 !== undefined ? Math.round(s.rsi_14) : '-'}</span>`;
        }

        html += `<tr class="${rowClass}">
            <td style="font-weight:600;color:#fff;">${s.name || '-'}</td>
            <td style="font-family:monospace;font-size:0.72rem;color:var(--text-muted);">${s.ts_code || s.code || '-'}</td>
            ${strategyKey === 'erp' ? `<td>${(() => { const styleMap = {'核心宽基':'erp-style-core','中盘成长':'erp-style-growth','防御红利':'erp-style-yield','港股宽基':'erp-style-hk'}; return `<span class="erp-style-tag ${styleMap[s.style] || 'erp-style-core'}">${s.style || '-'}</span>`; })()}</td>` : ''}
            ${strategyKey === 'aiae_etf' ? `<td><span style="font-size:0.72rem;color:#fbbf24;">${s.etf_type || s.style || '-'}</span></td>` : ''}
            <td><span class="score-cell score-tier-${tier}">${score}</span></td>
            ${strategyKey === 'aiae_etf' ? `<td><span style="font-size:0.72rem;color:var(--text-muted);">${s.style || '-'}</span></td>` : `<td class="factor-compact">${factors}</td>`}
            <td><span class="st-signal-tag ${tagClass}">${tagLabel}</span></td>
            <td style="font-weight:700;color:#fff;">${s.suggested_position || 0}%</td>
        </tr>`;
    });
    tbody.innerHTML = html;
}

// ====== Tab切换 ======
function switchExecTab(key) {
    ['mr', 'div', 'mom', 'erp', 'aiae_etf'].forEach(k => {
        const table = document.getElementById(`exec-table-${k}`);
        if (table) table.style.display = k === key ? 'block' : 'none';
    });
    document.querySelectorAll('.exec-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.strategy === key);
    });
}

// ====== 共振面板渲染 ======
function renderResonancePanel(resonance, { safelySetHTML }) {
    const panel = document.getElementById('exec-resonance-panel');
    if (!panel) return;
    let html = '';

    const renderCard = (item, type) => {
        const typeClass = type === 'buy' ? 'resonance-strong-buy' : type === 'sell' ? 'resonance-strong-sell' : 'resonance-divergence';
        const typeLabel = type === 'buy' ? '🟢 强共振买入' : type === 'sell' ? '🔴 强共振卖出' : '⚠️ 信号分歧';
        const dotFor = (sig) => sig === 'buy' ? 'dot-buy' : sig?.includes('sell') ? 'dot-sell' : sig === '-' ? 'dot-none' : 'dot-hold';

        const hitCount = Object.values(item.signals || {}).filter(v => v !== '-').length;
        const hitBadge = hitCount >= 3 ? `<span class="resonance-hit-badge hit-strong">命中 ${hitCount}/5</span>` : `<span class="resonance-hit-badge hit-weak">命中 ${hitCount}/5</span>`;

        return `<div class="resonance-card ${typeClass}">
            <div style="font-weight:700;color:#fff;font-size:0.88rem;margin-bottom:6px;">${item.name}${hitBadge}</div>
            <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:10px;">${item.code}</div>
            <div style="display:flex;gap:12px;font-size:0.78rem;">
                <span><span class="resonance-signal-dot ${dotFor(item.signals?.mr)}"></span>MR</span>
                <span><span class="resonance-signal-dot ${dotFor(item.signals?.div)}"></span>DIV</span>
                <span><span class="resonance-signal-dot ${dotFor(item.signals?.mom)}"></span>MOM</span>
                <span><span class="resonance-signal-dot ${dotFor(item.signals?.erp)}"></span>ERP</span>
                <span><span class="resonance-signal-dot ${dotFor(item.signals?.aiae)}" style="box-shadow:0 0 4px rgba(245,158,11,0.5);"></span>AIAE</span>
            </div>
            <div style="margin-top:8px;font-size:0.72rem;font-weight:600;color:${type === 'buy' ? '#10b981' : type === 'sell' ? '#ef4444' : '#f59e0b'};">${typeLabel}</div>
        </div>`;
    };

    (resonance.consensus_buy || []).forEach(item => { html += renderCard(item, 'buy'); });
    (resonance.consensus_sell || []).forEach(item => { html += renderCard(item, 'sell'); });
    (resonance.divergence || []).forEach(item => { html += renderCard(item, 'divergence'); });

    if (!html) {
        html = `<div style="grid-column:1/-1;text-align:center;padding:24px;color:var(--text-muted);font-size:0.85rem;">
            暂无跨策略重叠标的 — 4个策略标的池独立，无交叉信号
        </div>`;
    }

    panel.innerHTML = html;
}

// ====== 均值回归结果渲染 V4.2 ======
function renderMeanReversionResults(data, { safelySetText, safelySetHTML }) {
    const ov = data.market_overview;
    // V4.2: Regime KPI
    const firstSignal = data.signals?.[0];
    const regime = firstSignal?.regime || 'RANGE';
    const regimeColors = { 'BULL': '#10b981', 'RANGE': '#3b82f6', 'BEAR': '#f59e0b', 'CRASH': '#ef4444' };
    const regimeCN = { 'BULL': '🟢 牛市', 'RANGE': '🟡 震荡', 'BEAR': '🟠 熊市', 'CRASH': '🔴 危机' };
    safelySetHTML('ov-regime', `<span style="color:${regimeColors[regime] || '#3b82f6'}">${regimeCN[regime] || regime}</span>`);
    safelySetText('ov-avg-dev', ov.avg_deviation + '%');
    safelySetHTML('ov-max-dev', `${ov.max_deviation.name}<br><small style="color:var(--text-muted)">${ov.max_deviation.value}%</small>`);
    safelySetText('ov-buy-count', ov.signal_count.buy);
    safelySetText('ov-sell-count', ov.signal_count.sell);
    safelySetText('ov-total-pos', ov.total_suggested_position + '%');
    safelySetText('ov-above3', `${ov.above_3pct}只 · ${ov.market_divergence}`);

    renderActionList('st-buy-list', data.buy_signals, 'buy');
    renderActionList('st-sell-list', data.sell_signals, 'sell');
    renderSignalTable(data.signals);
    safelySetText('st-total-count', data.signals.length);

    const errDiv = document.getElementById('st-errors');
    if (data.errors?.length > 0 && errDiv) {
        errDiv.style.display = 'block';
        safelySetHTML('st-error-list', data.errors.map(e =>
            `<p style="font-size:0.82rem;color:var(--text-muted);padding:4px 0;">${e.code} ${e.name}: ${e.error}</p>`
        ).join(''));
    }
}

// ====== 红利趋势结果渲染 V4.0 ======
function renderDividendResults(data, { safelySetText, safelySetHTML }) {
    const ov = data.market_overview;
    // V4.0: Regime + Cap KPI
    const regime = data.regime_params?.regime || data.regime || 'RANGE';
    const regimeColors = { 'BULL': '#10b981', 'RANGE': '#3b82f6', 'BEAR': '#f59e0b', 'CRASH': '#ef4444' };
    const regimeCN = { 'BULL': '🟢 牛市', 'RANGE': '🟡 震荡', 'BEAR': '🟠 熊市', 'CRASH': '🔴 危机' };
    safelySetHTML('dt-regime', `<span style="color:${regimeColors[regime] || '#3b82f6'}">${regimeCN[regime] || regime}</span>`);
    safelySetText('dt-trend-up', `${ov.trend_up_count} / 8`);
    safelySetText('dt-buy-count', ov.buy_count + ' 只');
    safelySetText('dt-sell-count', ov.sell_count + ' 只');
    safelySetText('dt-total-pos', ov.total_suggested_pos + '%');
    safelySetText('dt-pos-cap', (ov.pos_cap || data.regime_params?.pos_cap || '—') + '%');

    // V4.0: XV Banner
    const xvWarnings = data.signals.filter(s => s.xv_warning);
    const xvBanner = document.getElementById('dt-xv-banner');
    const xvMsg = document.getElementById('dt-xv-message');
    if (xvWarnings.length > 0 && xvBanner) {
        xvBanner.style.display = 'block';
        const names = xvWarnings.map(s => s.name).join(', ');
        if (xvMsg) xvMsg.textContent = `${names} — 均值回归引擎检测到技术面偏弱信号，建议缩减仓位`;
    } else if (xvBanner) {
        xvBanner.style.display = 'none';
    }

    // 操作建议双栏
    renderDividendActionList('dt-buy-list', data.signals.filter(s => s.signal === 'buy'), 'buy');
    renderDividendActionList('dt-sell-list', data.signals.filter(s => s.signal === 'sell'), 'sell');

    // 全标的表格
    renderDividendTable(data.signals);

    // 错误展示
    const errDiv = document.getElementById('dt-errors');
    if (data.errors?.length > 0 && errDiv) {
        errDiv.style.display = 'block';
        safelySetHTML('dt-error-list', data.errors.map(e =>
            `<p style="font-size:0.82rem;color:var(--text-muted);padding:4px 0;">${e.code} ${e.name}: ${e.error}</p>`
        ).join(''));
    }
}

function renderDividendActionList(containerId, items, type) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!items || items.length === 0) {
        container.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:20px 0;">暂无${type === 'buy' ? '买入' : '卖出'}信号</p>`;
        return;
    }
    container.innerHTML = items.map(s => {
        const score = s.signal_score || 0;
        const scoreColor = getScoreColor(score);
        const xvIcon = s.xv_warning ? ' ⚠️' : '';
        return `
        <div class="st-action-item">
            <div class="st-ai-info">
                <span class="st-ai-name">${s.name}${xvIcon}</span>
                <span class="st-ai-code">${s.code}</span>
            </div>
            <div class="st-ai-meta">
                <span class="st-ai-score ${type === 'buy' ? 'st-ai-score-buy' : 'st-ai-score-sell'}" style="color:${scoreColor}">${score}分</span>
                <span class="st-ai-pos">${s.suggested_position > 0 ? s.suggested_position + '%' : '0%'}</span>
            </div>
        </div>`;
    }).join('');
}

function renderDividendTable(signals) {
    const tbody = document.getElementById('dt-table-body');
    if (!tbody) return;

    // 按信号排序：买入 > 持有 > 卖出
    const order = { 'buy': 1, 'hold': 2, 'sell': 5 };
    signals.sort((a, b) => (order[a.signal] || 99) - (order[b.signal] || 99));

    tbody.innerHTML = signals.map(s => {
        const rowClass = s.signal === 'buy' ? 'st-row-buy' : (s.signal === 'sell' ? 'st-row-sell' : '');
        const signalTag = getSignalTag(s.signal);
        const trendTag = s.trend === 'UP'
            ? '<span style="color:#10b981;font-weight:700;">↑ 向上</span>'
            : '<span style="color:#ef4444;font-weight:700;">↓ 向下</span>';
        const rsiColor = s.rsi <= 30 ? '#10b981' : (s.rsi >= 72 ? '#ef4444' : 'inherit');
        const biasColor = s.bias <= -5 ? '#10b981' : (s.bias >= 15 ? '#ef4444' : 'inherit');
        const yieldColor = s.ttm_yield >= 6.0 ? '#ef4444' : (s.ttm_yield >= 5.0 ? '#f59e0b' : '#10b981');
        const yieldWeight = s.ttm_yield >= 6.0 ? '800' : '600';
        // V4.0 new dimensions
        const score = s.signal_score || 0;
        const scoreColor = getScoreColor(score);
        const rsiSlope = s.rsi_slope5 || 0;
        const rsiDirIcon = rsiSlope > 2 ? '↑↑' : (rsiSlope > 0 ? '↑' : (rsiSlope > -2 ? '→' : '↓'));
        const rsiDirColor = rsiSlope > 0 ? '#10b981' : (rsiSlope < -2 ? '#ef4444' : '#94a3b8');
        const vol30d = s.vol_30d || 0;
        const volColor = vol30d > 25 ? '#ef4444' : (vol30d > 18 ? '#f59e0b' : '#10b981');
        const xvTag = s.xv_warning ? '<span style="color:#fbbf24">⚠️</span>' : '<span style="color:#10b981">✅</span>';

        return `<tr class="${rowClass}">
            <td style="font-weight:600;color:#fff;">${s.name}</td>
            <td style="font-family:monospace;color:#60a5fa;font-size:0.75rem;">${s.code}</td>
            <td>${s.close}</td>
            <td style="color:${scoreColor};font-weight:700">${score}</td>
            <td style="color:${yieldColor};font-weight:${yieldWeight}">${s.ttm_yield}%</td>
            <td>${trendTag}</td>
            <td style="color:${rsiColor}">${s.rsi}</td>
            <td style="color:${rsiDirColor}">${rsiDirIcon} ${rsiSlope > 0 ? '+' : ''}${rsiSlope}</td>
            <td style="color:${biasColor}">${s.bias > 0 ? '+' : ''}${s.bias}%</td>
            <td style="color:${volColor}">${vol30d}%</td>
            <td>${xvTag}</td>
            <td>${signalTag}</td>
            <td style="font-weight:600">${s.suggested_position > 0 ? s.suggested_position + '%' : '—'}</td>
        </tr>`;
    }).join('');
}

function renderActionList(containerId, items, type) {
    const container = document.getElementById(containerId);
    if (!items || items.length === 0) {
        container.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:20px 0;">暂无${type === 'buy' ? '买入' : '卖出'}信号</p>`;
        return;
    }

    container.innerHTML = items.map(s => `
        <div class="st-action-item">
            <div class="st-ai-info">
                <span class="st-ai-name">${s.name}</span>
                <span class="st-ai-code">${s.ts_code || s.code}</span>
            </div>
            <div class="st-ai-meta">
                <span class="st-ai-score ${type === 'buy' ? 'st-ai-score-buy' : 'st-ai-score-sell'}">${s.signal_score || 0}分</span>
                <span class="st-ai-pos">${s.suggested_position}%</span>
            </div>
        </div>
    `).join('');
}

function renderSignalTable(signals) {
    const tbody = document.getElementById('st-table-body');
    if (!tbody) return;
    
    // 按信号排序：买入 > 持有 > 减仓/注意 > 卖出
    const order = { 'buy': 1, 'hold': 2, 'sell_weak': 3, 'sell_half': 4, 'sell': 5 };
    signals.sort((a, b) => (order[a.signal] || 99) - (order[b.signal] || 99));

    tbody.innerHTML = signals.map(s => {
        const rowClass = s.signal === 'buy' ? 'st-row-buy' : (s.signal === 'sell' || s.signal === 'sell_weak' || s.signal === 'sell_half' ? 'st-row-sell' : '');
        const signalTag = getSignalTag(s.signal);
        // V4.2 new columns
        const score = s.signal_score || 0;
        const scoreColor = getScoreColor(score);
        const rsiSlope = s.rsi_slope5 || 0;
        const rsiDirIcon = rsiSlope > 2 ? '↑↑' : (rsiSlope > 0 ? '↑' : (rsiSlope > -2 ? '→' : '↓'));
        const rsiDirColor = rsiSlope > 0 ? '#10b981' : (rsiSlope < -2 ? '#ef4444' : '#94a3b8');
        const klineMap = { 'hammer': '🔨 锤子', 'doji': '✖ 十字星', 'engulfing': '🟢 包裹', 'neutral': '—' };
        const klineTag = klineMap[s.kline_pattern] || '—';

        return `<tr class="${rowClass}">
            <td style="font-weight:600;color:#fff">${s.name}</td>
            <td style="font-family:monospace;color:#60a5fa;font-size:0.75rem">${s.ts_code || s.code}</td>
            <td>${s.close}</td>
            <td style="color:${scoreColor};font-weight:700">${score}</td>
            <td style="color:${s.percent_b <= 0 ? '#10b981' : (s.percent_b >= 1 ? '#ef4444' : 'inherit')};font-weight:${s.percent_b <= 0 || s.percent_b >= 1 ? '700' : '400'}">${s.percent_b}</td>
            <td style="color:${s.rsi_3 <= 10 ? '#10b981' : (s.rsi_3 >= 90 ? '#ef4444' : 'inherit')}">${s.rsi_3}</td>
            <td style="color:${rsiDirColor};font-size:0.8rem">${rsiDirIcon} ${rsiSlope > 0 ? '+' : ''}${rsiSlope}</td>
            <td style="font-size:0.8rem;color:var(--text-muted)">${klineTag}</td>
            <td>${signalTag}</td>
            <td style="font-weight:600">${s.suggested_position > 0 ? s.suggested_position + '%' : '—'}</td>
        </tr>`;
    }).join('');
}

function getSignalTag(signal) {
    const map = {
        'buy': '<span class="st-signal-tag st-tag-buy">🟢 买入</span>',
        'sell': '<span class="st-signal-tag st-tag-sell">🔴 清仓</span>',
        'sell_half': '<span class="st-signal-tag st-tag-sell" style="background:rgba(234,179,8,0.2);color:#eab308;border-color:rgba(234,179,8,0.3)">🟠 减仓止盈</span>',
        'sell_weak': '<span class="st-signal-tag st-tag-weak">⚠️ 注意</span>',
        'hold': '<span class="st-signal-tag st-tag-hold">— 持有</span>'
    };
    return map[signal] || map['hold'];
}

function getScoreColor(score) {
    if (score >= 85) return '#10b981';
    if (score >= 75) return '#3b82f6';
    if (score >= 60) return '#f59e0b';
    return '#94a3b8';
}

// ====== 动量轮动结果渲染 ======
function renderMomentumResults(data, { safelySetText, safelySetHTML }) {
    const ov = data.market_overview;

    // KPI
    safelySetHTML('mom-regime', ov.regime_label || '—');
    safelySetText('mom-cap', ov.position_cap + '%');
    safelySetHTML('mom-top1', `${ov.top1_name}<br><small style="color:var(--text-muted)">${ov.top1_momentum > 0 ? '+' : ''}${ov.top1_momentum}%</small>`);
    safelySetText('mom-avg', (ov.avg_momentum > 0 ? '+' : '') + ov.avg_momentum + '%');
    safelySetText('mom-buy-count', ov.buy_count + ' 只');
    safelySetText('mom-sell-count', ov.sell_count + ' 只');

    // 三层过滤详情
    safelySetText('mom-l1', ov.layer1_trend || '—');
    safelySetText('mom-l2', ov.layer2_vix !== undefined ? ov.layer2_vix.toString() : '—');
    safelySetText('mom-l3', ov.layer3_crash ? '⚠️ 触发空仓' : '✅ 正常');
    safelySetText('mom-total-pos', ov.total_suggested_pos + '%');

    // 操作建议
    renderMomentumActionList('mom-buy-list', data.buy_signals, 'buy');
    renderMomentumActionList('mom-sell-list', data.sell_signals, 'sell');

    // 信号表
    renderMomentumTable(data.signals);
    safelySetText('mom-total-count', data.signals?.length || 0);

    // 错误
    const errDiv = document.getElementById('mom-errors');
    if (data.errors?.length > 0 && errDiv) {
        errDiv.style.display = 'block';
        safelySetHTML('mom-error-list', data.errors.map(e =>
            `<p style="font-size:0.82rem;color:var(--text-muted);padding:4px 0;">${e.code} ${e.name}: ${e.error}</p>`
        ).join(''));
    }
}

function renderMomentumActionList(containerId, items, type) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!items || items.length === 0) {
        container.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:20px 0;">暂无${type === 'buy' ? '买入' : '卖出'}信号</p>`;
        return;
    }
    container.innerHTML = items.map(s => `
        <div class="st-action-item">
            <div class="st-ai-info">
                <span class="st-ai-name">${s.name}</span>
                <span class="st-ai-code">${s.code} · ${s.group || ''}</span>
            </div>
            <div class="st-ai-meta">
                <span class="st-ai-score ${type === 'buy' ? 'st-ai-score-buy' : 'st-ai-score-sell'}">#${s.rank || '-'} ${s.momentum_pct > 0 ? '+' : ''}${s.momentum_pct}%</span>
                <span class="st-ai-pos">${s.suggested_position > 0 ? s.suggested_position + '%' : '0%'}</span>
            </div>
        </div>
    `).join('');
}

function renderMomentumTable(signals) {
    const tbody = document.getElementById('mom-table-body');
    if (!tbody) return;
    if (!signals || signals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--text-muted);padding:40px;">暂无信号数据</td></tr>';
        return;
    }

    // 按信号排序：买入 > 持有 > 注意 > 卖出
    const order = { 'buy': 1, 'hold': 2, 'sell_weak': 3, 'sell': 5 };
    signals.sort((a, b) => (order[a.signal] || 99) - (order[b.signal] || 99));

    tbody.innerHTML = signals.map(s => {
        const rowClass = s.signal === 'buy' ? 'st-row-buy' : (s.signal === 'sell' || s.signal === 'sell_weak' ? 'st-row-sell' : '');
        const signalTag = getSignalTag(s.signal);
        const momColor = s.momentum_pct > 5 ? '#10b981' : (s.momentum_pct > 0 ? '#34d399' : (s.momentum_pct > -3 ? '#fbbf24' : '#ef4444'));
        const volRatioColor = s.volume_ratio >= 1.5 ? '#10b981' : (s.volume_ratio >= 0.8 ? 'inherit' : '#ef4444');
        const rsiColor = s.rsi <= 30 ? '#10b981' : (s.rsi >= 70 ? '#ef4444' : 'inherit');
        const rankBg = s.rank <= 5 ? 'rgba(245,158,11,0.15)' : 'transparent';
        const rankColor = s.rank <= 3 ? '#fbbf24' : (s.rank <= 5 ? '#fcd34d' : 'var(--text-muted)');

        return `<tr class="${rowClass}">
            <td style="text-align:center;font-weight:800;color:${rankColor};background:${rankBg};border-radius:8px 0 0 8px;">${s.rank || '-'}</td>
            <td style="font-weight:600;color:#fff;">${s.name}</td>
            <td style="font-family:monospace;color:#60a5fa;font-size:0.75rem;">${s.code}</td>
            <td style="font-size:0.8rem;color:var(--text-muted)">${s.group || '—'}</td>
            <td>${s.close}</td>
            <td style="color:${momColor};font-weight:700;">${s.momentum_pct > 0 ? '+' : ''}${s.momentum_pct}%</td>
            <td style="color:${volRatioColor}">${s.volume_ratio}x</td>
            <td style="color:var(--text-muted)">${s.hist_vol}%</td>
            <td style="color:${rsiColor}">${s.rsi}</td>
            <td>${signalTag}</td>
            <td style="font-weight:600">${s.suggested_position > 0 ? s.suggested_position + '%' : '—'}</td>
        </tr>`;
    }).join('');
}

// ====================================================================
//  V2.0 回测实验室 JS 函数
// ====================================================================

async function runMomentumBacktest() {
    const btn = document.getElementById('bt-run-btn');
    const statusEl = document.getElementById('bt-status-text');
    const perfSection = document.getElementById('bt-perf-section');
    const chartSection = document.getElementById('bt-chart-section');
    const monthlySection = document.getElementById('bt-monthly-section');

    const topN = document.getElementById('bt-top-n')?.value || 4;
    const rebalance = document.getElementById('bt-rebalance')?.value || 10;
    const window_ = document.getElementById('bt-window')?.value || 20;
    const stopLoss = document.getElementById('bt-stoploss')?.value || -0.08;

    if (btn) { btn.disabled = true; btn.textContent = '⏳ 计算中...'; }
    if (statusEl) statusEl.textContent = '正在运行向量化回测，请稍候...';

    try {
        const url = `${API_URL}/api/v1/strategy/momentum-backtest?top_n=${topN}&rebalance_days=${rebalance}&mom_s_window=${window_}&stop_loss=${stopLoss}`;
        const resp = await fetch(url);
        const json = await resp.json();

        if (json.status !== 'success') throw new Error(json.message || '回测失败');

        const p = json.performance;

        // 更新状态
        const excessSign = p.excess_cagr >= 0 ? '+' : '';
        if (statusEl) statusEl.textContent = `✅ 回测完成 · 超额: ${excessSign}${p.excess_cagr}%/年`;

        // 显示绩效矩阵
        updateKPIs(p);
        if (perfSection) perfSection.style.display = 'block';

        // 净值曲线
        if (chartSection) chartSection.style.display = 'block';
        renderNavChart(p);

        // 月度热力图
        renderMonthlyHeatmap(p.monthly_returns || {});
        if (monthlySection) monthlySection.style.display = 'block';

    } catch (err) {
        if (statusEl) statusEl.textContent = `❌ 错误: ${err.message}`;
        console.error('Backtest error:', err);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🚀 运行回测'; }
    }
}

function updateKPIs(p) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const fmt = (v, suffix = '%', sign = true) => v != null ? `${sign && v > 0 ? '+' : ''}${v}${suffix}` : '—';

    set('kpi-excess-cagr', fmt(p.excess_cagr));
    set('kpi-cagr', fmt(p.cagr));
    set('kpi-maxdd', fmt(p.max_drawdown, '%', false));
    set('kpi-sharpe', p.sharpe ?? '—');
    set('kpi-ir', p.information_ratio ?? '—');
    set('kpi-winrate', fmt(p.excess_win_rate));
    set('kpi-s-cagr', fmt(p.cagr));
    set('kpi-b-cagr', fmt(p.benchmark_cagr));
    set('kpi-s-dd', fmt(p.max_drawdown, '%', false));
    set('kpi-b-dd', fmt(p.benchmark_max_dd, '%', false));
    set('kpi-te', fmt(p.tracking_error, '%', false));
    set('kpi-calmar', p.calmar ?? '—');
    set('kpi-vol', fmt(p.ann_vol, '%', false));
}

function renderNavChart(p) {
    const chartEl = document.getElementById('bt-nav-chart');
    if (!chartEl || !window.echarts) return;

    const chart = echarts.init(chartEl, 'dark');
    const hasBench = p.benchmark_values && p.benchmark_values.length > 0;
    const dates = p.dates || [];

    const series = [
        {
            name: '动量轮动 V2.0',
            type: 'line',
            data: p.portfolio_values || [],
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 2.5, color: '#fbbf24' },
            areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(251,191,36,0.18)' }, { offset: 1, color: 'rgba(251,191,36,0)' }] } },
        }
    ];

    if (hasBench) {
        series.push({
            name: '沪深300ETF',
            type: 'line',
            data: p.benchmark_values,
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 1.5, color: '#60a5fa', type: 'dashed' },
        });
    }

    chart.setOption({
        backgroundColor: 'transparent',
        grid: { left: 60, right: 30, top: 40, bottom: 50 },
        xAxis: { type: 'category', data: dates, axisLabel: { color: '#64748b', fontSize: 10 }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } } },
        yAxis: { type: 'value', axisLabel: { color: '#64748b', fontSize: 10, formatter: v => v.toFixed(2) }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
        legend: { data: series.map(s => s.name), textStyle: { color: '#94a3b8', fontSize: 11 }, top: 8 },
        tooltip: { trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: 'rgba(255,255,255,0.06)', textStyle: { color: '#fff', fontSize: 11 }, formatter: params => {
            let html = `<div style="margin-bottom:4px;color:#94a3b8;font-size:10px;">${params[0]?.axisValue}</div>`;
            params.forEach(p => { html += `<div>${p.seriesName}: <strong>${p.value?.toFixed(4)}</strong></div>`; });
            return html;
        }},
        series
    });

    window.addEventListener('resize', () => chart.resize());
}

function renderMonthlyHeatmap(monthlyReturns) {
    const tbody = document.getElementById('bt-monthly-body');
    if (!tbody) return;

    // 解析月度数据 -> {year: {month: return}}
    const byYear = {};
    for (const [dateStr, val] of Object.entries(monthlyReturns)) {
        const d = new Date(dateStr);
        const y = d.getFullYear();
        const m = d.getMonth() + 1;
        if (!byYear[y]) byYear[y] = {};
        byYear[y][m] = val;
    }

    const years = Object.keys(byYear).sort();
    const months = [1,2,3,4,5,6,7,8,9,10,11,12];

    tbody.innerHTML = years.map(year => {
        const yd = byYear[year];
        const yearTotal = months.reduce((acc, m) => acc + (yd[m] || 0), 0);
        const cells = months.map(m => {
            const v = yd[m];
            if (v == null) return `<td style="padding:8px; text-align:center; color:var(--text-muted)">—</td>`;
            const intensity = Math.min(Math.abs(v) / 15, 1);
            const bg = v > 0
                ? `rgba(16,185,129,${0.1 + intensity * 0.4})`
                : `rgba(239,68,68,${0.1 + intensity * 0.4})`;
            const color = v > 0 ? '#10b981' : '#f87171';
            return `<td style="padding:8px; text-align:center; background:${bg}; border-radius:4px; color:${color}; font-weight:600;">${v > 0 ? '+' : ''}${v.toFixed(1)}%</td>`;
        }).join('');

        const totalColor = yearTotal > 0 ? '#fcd34d' : '#f87171';
        return `<tr>
            <td style="padding:8px; text-align:left; font-weight:700; color:#fff;">${year}</td>
            ${cells}
            <td style="padding:8px; text-align:center; font-weight:800; color:${totalColor};">${yearTotal > 0 ? '+' : ''}${yearTotal.toFixed(1)}%</td>
        </tr>`;
    }).join('');
}

async function runMomentumOptimize() {
    const btn = document.getElementById('bt-opt-btn');
    const resultsDiv = document.getElementById('bt-opt-results');

    if (btn) { btn.disabled = true; btn.textContent = '⏳ 网格搜索中 (约60秒)...'; }

    try {
        const resp = await fetch(`${API_URL}/api/v1/strategy/momentum-optimize`);
        const json = await resp.json();

        if (json.status !== 'success') throw new Error(json.message || '优化失败');

        const d = json.data;
        const bp = d.best_params;
        const perf = d.in_sample_perf;
        const oos = d.out_of_sample_perf || {};

        // 最优参数展示
        const bestParamsEl = document.getElementById('bt-best-params');
        if (bestParamsEl) {
            bestParamsEl.innerHTML = `
                <div style="display:flex; flex-wrap:wrap; gap:16px; color:#fcd34d; font-weight:600;">
                    <span>Top N: <strong>${bp.top_n}</strong></span>
                    <span>调仓周期: <strong>${bp.rebalance_days}日</strong></span>
                    <span>动量窗口: <strong>${bp.mom_s_window}日</strong></span>
                    <span>权重_短期: <strong>${bp.w_mom_s}</strong></span>
                    <span>止损: <strong>${bp.stop_loss != null ? bp.stop_loss * 100 + '%' : '不设置'}</strong></span>
                </div>
                <div style="margin-top:12px; display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; font-size:0.8rem;">
                    <div style="background:rgba(16,185,129,0.05); border:1px solid rgba(16,185,129,0.2); border-radius:8px; padding:12px;">
                        <div style="color:var(--text-muted); margin-bottom:4px;">样本内 超额CAGR</div>
                        <div style="font-size:1.2rem; font-weight:800; color:#10b981;">${perf.excess_cagr != null ? '+' + perf.excess_cagr + '%' : '—'}</div>
                    </div>
                    <div style="background:rgba(99,102,241,0.05); border:1px solid rgba(99,102,241,0.2); border-radius:8px; padding:12px;">
                        <div style="color:var(--text-muted); margin-bottom:4px;">样本内 夏普比率</div>
                        <div style="font-size:1.2rem; font-weight:800; color:#a78bfa;">${perf.sharpe ?? '—'}</div>
                    </div>
                    <div style="background:rgba(245,158,11,0.05); border:1px solid rgba(245,158,11,0.2); border-radius:8px; padding:12px;">
                        <div style="color:var(--text-muted); margin-bottom:4px;">样本外 超额CAGR</div>
                        <div style="font-size:1.2rem; font-weight:800; color:#fcd34d;">${oos.excess_cagr != null ? (oos.excess_cagr >= 0 ? '+' : '') + oos.excess_cagr + '%' : '待验证'}</div>
                    </div>
                </div>
            `;
        }

        // Top 10 参数表
        const top10Body = document.getElementById('bt-top10-body');
        if (top10Body && d.top10_params) {
            top10Body.innerHTML = d.top10_params.map((r, idx) => {
                const medal = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${r.rank}`;
                return `<tr>
                    <td style="font-weight:700;color:#fcd34d;">${medal}</td>
                    <td style="color:#10b981;font-weight:700;">${r.score}</td>
                    <td style="color:${r.excess_cagr > 0 ? '#10b981' : '#f87171'};">${r.excess_cagr != null ? (r.excess_cagr >= 0 ? '+' : '') + r.excess_cagr + '%' : '—'}</td>
                    <td>${r.sharpe ?? '—'}</td>
                    <td style="color:#f87171;">${r.max_dd != null ? r.max_dd + '%' : '—'}</td>
                    <td>${r.ir ?? '—'}</td>
                    <td>${r.params.top_n}</td>
                    <td>${r.params.rebalance_days}</td>
                    <td>${r.params.mom_s_window}</td>
                    <td style="color:${r.params.stop_loss ? '#f87171' : 'var(--text-muted)'};">${r.params.stop_loss != null ? r.params.stop_loss * 100 + '%' : '无'}</td>
                </tr>`;
            }).join('');
        }

        if (resultsDiv) resultsDiv.style.display = 'block';

    } catch (err) {
        alert(`优化失败: ${err.message}`);
        console.error('Optimize error:', err);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🔬 重新搜索'; }
    }
}


// ═══════════════════════════════════════════════════════════
//  Custom Pool Manager  V1.0
//  Storage key: alphacore_pool_{strategy}
//  Only affects real-time execution, NOT backtest
// ═══════════════════════════════════════════════════════════

const CUSTOM_POOL_CONFIG = {
    'mean-reversion': { maxCount: 10, stockCap: 8,  etfCap: 15 },
    'dividend-trend': { maxCount: 8,  stockCap: 8,  etfCap: 15 },
    'momentum':       { maxCount: 8,  stockCap: 10, etfCap: 15 },
};

function _poolKey(strategy) { return 'alphacore_pool_' + strategy; }
function _loadPool(strategy) { try { return JSON.parse(localStorage.getItem(_poolKey(strategy)) || '[]'); } catch { return []; } }
function _savePool(strategy, items) { localStorage.setItem(_poolKey(strategy), JSON.stringify(items)); }

function _normalizeCode(raw) {
    raw = raw.trim().toUpperCase().replace(/[^\dA-Z.]/g, '');
    if (!raw) return null;
    if (raw.includes('.')) return raw;
    const num = parseInt(raw, 10);
    if (isNaN(num)) return null;
    if ((num >= 600000 && num <= 699999) || (num >= 500000 && num <= 519999)) return raw + '.SH';
    if ((num >= 0 && num <= 399999) || (num >= 150000 && num <= 169999)) return raw + '.SZ';
    return raw + '.SH';
}

async function lookupCustomName(strategy) {
    const input = document.getElementById('custom-input-' + strategy);
    const nameDiv = document.getElementById('custom-name-' + strategy);
    if (!input || !nameDiv) return null;
    const raw = input.value.trim();
    if (!raw) { nameDiv.textContent = '请输入代码'; nameDiv.style.color = '#fbbf24'; return null; }
    const code = _normalizeCode(raw);
    if (!code) { nameDiv.textContent = '格式错误'; nameDiv.style.color = '#f87171'; return null; }
    input.value = code;
    nameDiv.textContent = '查询中...';
    nameDiv.style.color = 'var(--text-muted)';
    try {
        const res = await fetch('/api/v1/stock/name?ts_code=' + encodeURIComponent(code));
        const data = await res.json();
        const tc = { stock:'#60a5fa', etf:'#34d399', index:'#a78bfa', unknown:'#fbbf24', cached:'#34d399' };
        nameDiv.textContent = data.name;
        nameDiv.style.color = tc[data.type] || '#fff';
        nameDiv.dataset.resolvedName = data.name;
        nameDiv.dataset.resolvedType = data.type;
        return data;
    } catch {
        nameDiv.textContent = code; nameDiv.style.color = '#fbbf24';
        nameDiv.dataset.resolvedName = code; nameDiv.dataset.resolvedType = 'unknown';
        return { ts_code: code, name: code, type: 'unknown' };
    }
}

async function lookupAndAdd(strategy) {
    const data = await lookupCustomName(strategy);
    if (!data) return;
    addCustomStock(strategy, data.ts_code, data.name, data.type);
}

function addCustomStock(strategy, code, name, type) {
    const cfg = CUSTOM_POOL_CONFIG[strategy] || { maxCount: 10, stockCap: 8, etfCap: 15 };
    const items = _loadPool(strategy);
    if (items.find(function(i){ return i.code === code; })) { alert(code + ' 已在自选池中'); return; }
    if (items.length >= cfg.maxCount) { alert('当前策略自选池上限为 ' + cfg.maxCount + ' 只'); return; }
    const capSelect = document.getElementById('custom-cap-' + strategy);
    const capPct = capSelect ? parseInt(capSelect.value, 10) : (type === 'etf' ? cfg.etfCap : cfg.stockCap);
    items.push({ code: code, name: name, type: type, cap: capPct, addedAt: new Date().toISOString().slice(0,10) });
    _savePool(strategy, items);
    renderCustomChips(strategy);
}

function removeCustomStock(strategy, code) {
    _savePool(strategy, _loadPool(strategy).filter(function(i){ return i.code !== code; }));
    renderCustomChips(strategy);
}

function clearCustomPool(strategy) {
    if (!confirm('确认清空「' + strategy + '」策略的全部自选标的？')) return;
    _savePool(strategy, []);
    renderCustomChips(strategy);
}

function renderCustomChips(strategy) {
    const container = document.getElementById('custom-chips-' + strategy);
    const countEl = document.getElementById('custom-count-' + strategy);
    const cfg = CUSTOM_POOL_CONFIG[strategy] || { maxCount: 10 };
    if (!container) return;
    const items = _loadPool(strategy);
    const tc = {
        stock:   { bg:'rgba(96,165,250,0.12)',  bdr:'rgba(96,165,250,0.3)',  txt:'#93c5fd', lbl:'股' },
        etf:     { bg:'rgba(52,211,153,0.1)',   bdr:'rgba(52,211,153,0.25)', txt:'#34d399', lbl:'ETF' },
        index:   { bg:'rgba(167,139,250,0.1)',  bdr:'rgba(167,139,250,0.25)',txt:'#c4b5fd', lbl:'指' },
        unknown: { bg:'rgba(251,191,36,0.08)',  bdr:'rgba(251,191,36,0.25)', txt:'#fbbf24', lbl:'?' },
        cached:  { bg:'rgba(52,211,153,0.1)',   bdr:'rgba(52,211,153,0.25)', txt:'#34d399', lbl:'ETF' },
    };
    if (items.length === 0) {
        container.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;align-self:center;">暂无自选标的 · 请在上方输入代码并追加</span>';
    } else {
        container.innerHTML = items.map(function(item) {
            const c = tc[item.type] || tc.unknown;
            return '<div style="display:inline-flex;align-items:center;gap:6px;background:' + c.bg + ';border:1px solid ' + c.bdr + ';border-radius:20px;padding:5px 12px 5px 8px;font-size:0.8rem;">' +
                '<span style="background:' + c.bdr + ';color:' + c.txt + ';border-radius:10px;padding:0 5px;font-size:0.65rem;font-weight:700;">' + c.lbl + '</span>' +
                '<span style="color:' + c.txt + ';font-weight:700;">' + item.code.split('.')[0] + '</span>' +
                '<span style="color:#e2e8f0;">' + item.name + '</span>' +
                '<span style="color:var(--text-muted);font-size:0.7rem;">&#8804;' + item.cap + '%</span>' +
                '<button onclick="removeCustomStock(\''+strategy+'\',\''+item.code+'\')" style="background:none;border:none;color:rgba(255,255,255,0.4);cursor:pointer;padding:0 0 0 4px;font-size:1rem;line-height:1;" title="移除">&#x2715;</button>' +
                '</div>';
        }).join('');
    }
    if (countEl) countEl.textContent = '已追加：' + items.length + ' 只 / 上限 ' + cfg.maxCount + ' 只';
}

function getFullPool(strategy) {
    return _loadPool(strategy).map(function(item) {
        return { ts_code: item.code, name: item.name, type: item.type, cap: item.cap / 100, is_custom: true };
    });
}

function initAllCustomPools() {
    ['mean-reversion', 'dividend-trend', 'momentum'].forEach(function(s) { renderCustomChips(s); });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllCustomPools);
} else {
    initAllCustomPools();
}

// ====== ERP择时引擎 V2.0 · 前端渲染模块 ======

// ============================================================
// ERP择时模块 → strategy_erp.js
// AIAE仓位模块 → strategy_aiae.js
// 海外策略模块 → treasury.js
// ============================================================
