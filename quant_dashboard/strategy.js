// AlphaCore · 策略中心页面 JS
const API_URL = 'http://127.0.0.1:8000';

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
let _erpLoaded = false;
let _erpLastFetchTime = 0;          // 上次拉取时间戳 (ms)
let _erpCountdownTimer = null;      // P1: 倒计时定时器
let _erpGaugeChart = null;
let _erpHistoryChart = null;
const ERP_COOLDOWN_MS = 5 * 60 * 1000;  // 5 分钟冷却

// P1: 注入变化高亮 CSS
(function injectERPHighlightCSS() {
    if (document.getElementById('erp-highlight-style')) return;
    const style = document.createElement('style');
    style.id = 'erp-highlight-style';
    style.textContent = `
        @keyframes erpValueFlash {
            0% { background: rgba(245,158,11,0.35); }
            100% { background: transparent; }
        }
        .erp-value-changed {
            animation: erpValueFlash 1.2s ease-out;
            border-radius: 4px;
        }
    `;
    document.head.appendChild(style);
})();

/**
 * P1: 启动/重启倒计时显示
 */
function startERPCountdown() {
    if (_erpCountdownTimer) clearInterval(_erpCountdownTimer);
    const el = document.getElementById('erp-refresh-countdown');
    if (!el) return;
    _erpCountdownTimer = setInterval(() => {
        const elapsed = Date.now() - _erpLastFetchTime;
        const remaining = Math.max(0, ERP_COOLDOWN_MS - elapsed);
        if (remaining <= 0) {
            el.textContent = '可刷新';
            el.style.color = '#10b981';
            clearInterval(_erpCountdownTimer);
            _erpCountdownTimer = null;
        } else {
            const mins = Math.floor(remaining / 60000);
            const secs = Math.floor((remaining % 60000) / 1000);
            el.textContent = `${mins}m${secs.toString().padStart(2,'0')}s 后可刷新`;
            el.style.color = '#475569';
        }
    }, 1000);
}

/**
 * P1: 检测数值变化并添加高亮动画
 */
function highlightERPChanges(oldSnap, newSnap) {
    if (!oldSnap || !newSnap) return;
    const pairs = [
        ['erp-val-erp',    oldSnap.erp_value,    newSnap.erp_value],
        ['erp-val-pe',     oldSnap.pe_ttm,       newSnap.pe_ttm],
        ['erp-val-yield',  oldSnap.yield_10y,    newSnap.yield_10y],
    ];
    pairs.forEach(([id, oldVal, newVal]) => {
        if (oldVal != null && newVal != null && oldVal !== newVal) {
            const el = document.getElementById(id);
            if (el) {
                el.classList.remove('erp-value-changed');
                void el.offsetWidth;  // force reflow
                el.classList.add('erp-value-changed');
            }
        }
    });
}

let _erpPrevSnapshot = null;  // P1: 保存上次快照用于变化比较

/**
 * 刷新按钮入口 — 带 5 分钟冷却 + Loading 状态
 */
async function refreshERPData() {
    const btn = document.getElementById('erp-refresh-btn');
    const elapsed = Date.now() - _erpLastFetchTime;
    
    // 5 分钟冷却检查
    if (_erpLoaded && elapsed < ERP_COOLDOWN_MS) {
        const remaining = Math.ceil((ERP_COOLDOWN_MS - elapsed) / 60000);
        // 闪烁提示
        if (btn) {
            const orig = btn.innerHTML;
            btn.innerHTML = '✅ 数据仍为最新';
            btn.style.borderColor = 'rgba(16,185,129,0.4)';
            btn.style.color = '#10b981';
            setTimeout(() => {
                btn.innerHTML = orig;
                btn.style.borderColor = 'rgba(245,158,11,0.3)';
                btn.style.color = '#f59e0b';
            }, 1500);
        }
        return;
    }
    
    // 解锁 + 设置 Loading 状态
    _erpLoaded = false;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ 刷新中...';
        btn.style.opacity = '0.6';
    }
    
    try {
        await loadERPTimingData();
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔄 刷新实时数据';
            btn.style.opacity = '1';
        }
    }
}

async function loadERPTimingData() {
    if (_erpLoaded) return;
    
    // Loading 状态: 信号 Badge
    const sigLabel = document.getElementById('erp-signal-label');
    const sigEmoji = document.getElementById('erp-signal-emoji');
    if (sigLabel) { sigLabel.textContent = '刷新中...'; sigLabel.style.color = '#f59e0b'; }
    if (sigEmoji) sigEmoji.textContent = '⏳';
    
    try {
        const resp = await fetch('/api/v1/strategy/erp-timing');
        const json = await resp.json();
        if (json.status !== 'success' || !json.data) { console.error('ERP API error:', json); return; }
        const data = json.data;

        // V2.1: 降级状态检测 — 引擎返回 fallback 时显示警告
        const bar = document.getElementById('erp-identity-bar');
        if (data.status === 'fallback') {
            if (bar) {
                bar.style.borderLeftColor = '#f59e0b';
                bar.style.boxShadow = '0 0 20px rgba(245,158,11,0.3)';
            }
            const badge = document.getElementById('erp-resonance-badge');
            if (badge) {
                badge.textContent = '⚠️ 数据降级模式';
                badge.style.background = 'rgba(245,158,11,0.15)';
                badge.style.color = '#f59e0b';
            }
        }
        // P1: 变化高亮 (比较新旧快照)
        const newSnap = data.current_snapshot || {};
        highlightERPChanges(_erpPrevSnapshot, newSnap);
        _erpPrevSnapshot = { ...newSnap };
        
        renderERPSnapshot(data);
        renderERPAlerts(data.alerts || []);
        renderERPTradeHub(data.trade_rules || {});
        renderERPDimBars(data.dimensions, data.encyclopedia || {});
        renderERPGauge(data.signal, data.trade_rules);
        if (data.chart && data.chart.status === 'success') renderERPHistoryChart(data.chart, data);
        renderERPEncyclopedia(data.encyclopedia || {});
        renderERPDiagnosis(data.diagnosis || []);
        // 头部徽章
        const sig = data.signal || {};
        const tr = data.trade_rules || {};
        document.getElementById('erp-signal-emoji').textContent = sig.emoji || '?';
        const lbl = document.getElementById('erp-signal-label');
        lbl.textContent = sig.label || '--'; lbl.style.color = sig.color || '#94a3b8';
        document.getElementById('erp-signal-position').textContent = '\u5EFA\u8BAE\u4ED3\u4F4D ' + (sig.position||'--') + ' \u00B7 \u5F97\u5206 ' + (sig.score||'--');
        document.getElementById('erp-resonance-badge').textContent = tr.resonance_label || '';
        document.getElementById('erp-update-time').textContent = '\u6700\u540E\u66F4\u65B0: ' + new Date().toLocaleString('zh-CN');
        // 脉冲动画
        const alerts = data.alerts || [];
        const hasPulse = alerts.some(a => a.pulse);
        if (hasPulse) {
            const bar = document.getElementById('erp-identity-bar');
            const pulseAlert = alerts.find(a => a.pulse);
            const pulseColor = pulseAlert.level === 'danger' ? '#ef4444' : (pulseAlert.level === 'opportunity' ? '#10b981' : '#f59e0b');
            bar.style.boxShadow = '0 0 20px ' + pulseColor + '40';
            bar.style.borderLeftColor = pulseColor;
        }
        _erpLoaded = true;
        _erpLastFetchTime = Date.now();
        
        // P1: 启动倒计时
        startERPCountdown();
        
    } catch (e) {
        console.error('ERP load error:', e);
        // 错误恢复: 保持 _erpLoaded = false 允许重试
        if (sigLabel) { sigLabel.textContent = '加载失败'; sigLabel.style.color = '#ef4444'; }
        if (sigEmoji) sigEmoji.textContent = '❌';
    }
}


function renderERPSnapshot(data) {
    const snap = data.current_snapshot || {};
    const dims = data.dimensions || {};
    const m1 = dims.m1_trend?.m1_info || {};
    const vol = dims.volatility?.vol_info || {};
    const credit = dims.credit?.credit_info || {};
    // ERP
    const erpEl = document.getElementById('erp-val-erp');
    erpEl.textContent = (snap.erp_value || '--') + '%';
    erpEl.style.color = snap.erp_value >= 5 ? '#10b981' : (snap.erp_value >= 3.5 ? '#f59e0b' : '#ef4444');
    document.getElementById('erp-sub-erp').textContent = '\u8FD14\u5E74 ' + (snap.erp_percentile || '--') + '% \u5206\u4F4D';
    const trendErp = document.getElementById('erp-trend-erp');
    if (snap.erp_value >= 5) { trendErp.textContent = '\u2191'; trendErp.style.color = '#10b981'; }
    else if (snap.erp_value < 3.5) { trendErp.textContent = '\u2193'; trendErp.style.color = '#ef4444'; }
    else { trendErp.textContent = '\u2192'; trendErp.style.color = '#f59e0b'; }
    // PE
    document.getElementById('erp-val-pe').textContent = (snap.pe_ttm || '--') + 'x';
    document.getElementById('erp-sub-pe').textContent = '\u76C8\u5229\u6536\u76CA\u7387 ' + (snap.earnings_yield || '--') + '%';
    // 10Y
    document.getElementById('erp-val-yield').textContent = (snap.yield_10y || '--') + '%';
    // M1
    const m1El = document.getElementById('erp-val-m1');
    m1El.textContent = (m1.current ?? '--') + '%';
    m1El.style.color = m1.current > 0 ? '#10b981' : '#ef4444';
    document.getElementById('erp-sub-m1').textContent = 'M2 \u540C\u6BD4: ' + (m1.m2_yoy ?? '--') + '%';
    const trendM1 = document.getElementById('erp-trend-m1');
    if (m1.direction === 'rising') { trendM1.textContent = '\u2191'; trendM1.style.color = '#10b981'; }
    else { trendM1.textContent = '\u2193'; trendM1.style.color = '#ef4444'; }
    // Vol
    const volEl = document.getElementById('erp-val-vol');
    volEl.textContent = (vol.current ?? '--');
    volEl.style.color = vol.regime === 'calm' ? '#10b981' : (vol.regime === 'extreme_panic' ? '#ef4444' : '#94a3b8');
    document.getElementById('erp-sub-vol').textContent = (vol.pct ?? '--') + '% \u5206\u4F4D | ' + ({calm:'\u5E73\u9759',normal:'\u6B63\u5E38',high:'\u504F\u9AD8',extreme_panic:'\u6050\u614C'}[vol.regime]||'--');
    // Credit
    const creditEl = document.getElementById('erp-val-credit');
    const scissor = m1.scissor ?? credit.scissor ?? '--';
    creditEl.textContent = (typeof scissor === 'number' ? (scissor >= 0 ? '+' : '') + scissor.toFixed(1) : scissor) + '%';
    creditEl.style.color = scissor >= -2 ? '#10b981' : '#f59e0b';
    document.getElementById('erp-sub-credit').textContent = scissor >= 0 ? '\u8D44\u91D1\u6D3B\u5316' : '\u8D44\u91D1\u6C89\u6DC0';
}

function renderERPAlerts(alerts) {
    const banner = document.getElementById('erp-alert-banner');
    if (!alerts.length || (alerts.length === 1 && alerts[0].level === 'normal')) { banner.style.display = 'none'; return; }
    const colorMap = { danger: '#ef4444', warning: '#f59e0b', opportunity: '#10b981', normal: '#64748b' };
    banner.style.display = 'flex';
    banner.style.cssText += 'display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;';
    banner.innerHTML = alerts.filter(a => a.level !== 'normal').map(a => {
        const c = colorMap[a.level] || '#64748b';
        const pulse = a.pulse ? 'animation:erpPulse 2s infinite;' : '';
        return '<div style="font-size:0.7rem;padding:4px 10px;border-radius:6px;background:' + c + '15;border:1px solid ' + c + '40;color:' + c + ';' + pulse + '">' + a.icon + ' ' + a.text + '</div>';
    }).join('');
    // 注入脉冲动画CSS
    if (!document.getElementById('erp-pulse-style')) {
        const style = document.createElement('style');
        style.id = 'erp-pulse-style';
        style.textContent = '@keyframes erpPulse{0%,100%{opacity:1;box-shadow:0 0 8px rgba(245,158,11,0.3)}50%{opacity:0.7;box-shadow:0 0 16px rgba(245,158,11,0.6)}}';
        document.head.appendChild(style);
    }
}

function renderERPTradeHub(trade) {
    // 信号等级条
    const levelBar = document.getElementById('erp-signal-level-bar');
    const levels = ['cash','underweight','reduce','hold','buy','strong_buy'];
    const levelLabels = ['\u6E05\u4ED3','\u4F4E\u914D','\u51CF\u4ED3','\u6807\u914D','\u4E70\u5165','\u5F3A\u4E70'];
    const levelColors = ['#ef4444','#f97316','#f59e0b','#3b82f6','#34d399','#10b981'];
    if (levelBar) {
        levelBar.innerHTML = levels.map((l, i) => {
            const active = l === trade.signal_key;
            return '<div style="width:' + (active ? '40' : '20') + 'px;height:8px;border-radius:4px;background:' + (active ? levelColors[i] : 'rgba(100,116,139,0.2)') + ';transition:all 0.5s;" title="' + levelLabels[i] + '"></div>';
        }).join('');
    }
    // ETF
    const etfC = document.getElementById('erp-etf-advice');
    if (etfC && trade.etf_advice) {
        etfC.innerHTML = trade.etf_advice.map(e => {
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(100,116,139,0.1);border-radius:4px;">' +
                '<div><span style="font-size:0.75rem;color:#e2e8f0;">' + e.etf.name + '</span><span style="font-size:0.6rem;color:#64748b;margin-left:6px;">' + e.etf.code + '</span></div>' +
                '<div style="text-align:right;"><span style="font-size:0.8rem;font-weight:700;color:#f59e0b;">' + e.ratio + '</span><div style="font-size:0.55rem;color:#64748b;">' + e.reason + '</div></div></div>';
        }).join('');
    }
    // 止盈 — V2.1: 动态触发标注 (与海外版对齐)
    const tpC = document.getElementById('erp-take-profit');
    if (tpC && trade.take_profit) {
        tpC.innerHTML = trade.take_profit.map(r => {
            const triggered = r.triggered;
            const bg = triggered
                ? 'background:rgba(16,185,129,0.18);border-left:3px solid #10b981;box-shadow:0 0 8px rgba(16,185,129,0.15);'
                : 'background:rgba(16,185,129,0.06);border-left:2px solid rgba(16,185,129,0.3);';
            const currentTag = r.current
                ? ' <span style="color:#64748b;font-size:0.58rem;margin-left:4px;">[' + r.current + ']</span>'
                : '';
            const statusIcon = triggered ? '✅ ' : '';
            return '<div style="font-size:0.65rem;padding:5px 8px;border-radius:5px;' + bg + 'transition:all 0.3s;">' +
                '<div style="color:' + (triggered ? '#10b981' : '#6ee7b7') + ';font-weight:' + (triggered ? '700' : '400') + ';">' + statusIcon + r.trigger + currentTag + '</div>' +
                '<div style="color:#94a3b8;margin-top:2px;font-size:0.6rem;">\u2192 ' + r.action + '</div></div>';
        }).join('');
    }
    // 止损 — V2.1: 动态触发标注
    const slC = document.getElementById('erp-stop-loss');
    if (slC && trade.stop_loss) {
        slC.innerHTML = trade.stop_loss.map(r => {
            const c = r.color || '#f59e0b';
            const triggered = r.triggered;
            const bg = triggered
                ? 'background:' + c + '20;border-left:3px solid ' + c + ';box-shadow:0 0 8px ' + c + '25;'
                : 'background:' + c + '08;border-left:2px solid ' + c + '40;';
            const currentTag = r.current
                ? ' <span style="color:#64748b;font-size:0.58rem;margin-left:4px;">[' + r.current + ']</span>'
                : '';
            const statusIcon = triggered ? '✅ ' : '';
            return '<div style="font-size:0.65rem;padding:5px 8px;border-radius:5px;' + bg + 'transition:all 0.3s;">' +
                '<div style="color:' + c + ';font-weight:' + (triggered ? '700' : '400') + ';">' + statusIcon + r.trigger + currentTag + '</div>' +
                '<div style="color:#94a3b8;margin-top:2px;font-size:0.6rem;">\u2192 ' + r.action + '</div></div>';
        }).join('');
    }
}

function renderERPDimBars(dims, encyclopedia) {
    const container = document.getElementById('erp-dim-bars');
    if (!container || !dims) return;
    const order = ['erp_abs', 'erp_pct', 'm1_trend', 'volatility', 'credit'];
    const icons = { erp_abs: '\uD83D\uDCCA', erp_pct: '\uD83D\uDCD0', m1_trend: '\uD83D\uDCA7', volatility: '\uD83C\uDF0A', credit: '\uD83D\uDD17' };
    const encKeys = { erp_abs: 'erp_abs', erp_pct: 'erp_pct', m1_trend: 'm1_trend', volatility: 'volatility', credit: 'credit' };
    container.innerHTML = order.map(key => {
        const d = dims[key];
        if (!d) return '';
        const barColor = d.score >= 70 ? '#10b981' : (d.score >= 40 ? '#f59e0b' : '#ef4444');
        const weightPct = Math.round(d.weight * 100);
        const enc = encyclopedia[encKeys[key]];
        const encHtml = enc ? '<div id="erp-enc-' + key + '" style="display:none;margin-top:6px;padding:8px;background:rgba(59,130,246,0.08);border-radius:6px;border:1px solid rgba(59,130,246,0.2);font-size:0.63rem;color:#cbd5e1;line-height:1.6;">' +
            '<div style="color:#60a5fa;font-weight:600;margin-bottom:3px;">' + enc.title + '</div>' +
            '<div>\uD83D\uDCD6 ' + enc.what + '</div>' +
            '<div>\u2753 ' + enc.why + '</div>' +
            '<div style="color:#f59e0b;">\u26A0\uFE0F ' + enc.alert + '</div>' +
            '<div style="color:#64748b;">\uD83D\uDCDC ' + enc.history + '</div></div>' : '';
        return '<div>' +
            '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;">' +
            '<span style="font-size:0.78rem;color:#e2e8f0;">' + (icons[key]||'') + ' ' + d.label + ' <span style="color:#64748b;font-size:0.65rem;">(' + weightPct + '%)</span>' +
            (enc ? ' <span style="cursor:pointer;font-size:0.65rem;" onclick="var e=document.getElementById(\'erp-enc-' + key + '\');e.style.display=e.style.display===\'none\'?\'block\':\'none\';">\u2139\uFE0F</span>' : '') +
            '</span>' +
            '<span style="font-size:0.82rem;font-weight:700;color:' + barColor + ';">' + d.score + '</span></div>' +
            '<div style="height:8px;background:rgba(100,116,139,0.2);border-radius:4px;overflow:hidden;position:relative;">' +
            '<div style="height:100%;width:' + d.score + '%;background:linear-gradient(90deg,' + barColor + '80,' + barColor + ');border-radius:4px;transition:width 0.8s ease;"></div>' +
            '<div style="position:absolute;top:0;left:35%;width:1px;height:100%;background:rgba(255,255,255,0.15);"></div>' +
            '<div style="position:absolute;top:0;left:70%;width:1px;height:100%;background:rgba(255,255,255,0.15);"></div></div>' +
            '<div style="font-size:0.63rem;color:#94a3b8;margin-top:3px;">' + (d.desc || '') + '</div>' +
            encHtml + '</div>';
    }).join('');
}

function renderERPGauge(signal, trade) {
    const dom = document.getElementById('erp-gauge-chart');
    if (!dom) return;
    if (_erpGaugeChart) _erpGaugeChart.dispose();
    _erpGaugeChart = echarts.init(dom);
    const score = signal.score || 50;
    const color = signal.color || '#64748b';
    _erpGaugeChart.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
            center: ['50%', '60%'], radius: '88%',
            itemStyle: { color: color },
            progress: { show: true, width: 16, roundCap: true },
            pointer: { show: false },
            axisLine: { lineStyle: { width: 16, color: [[0.25, '#ef4444'], [0.40, '#f59e0b'], [0.55, '#3b82f6'], [0.70, '#34d399'], [1, '#10b981']] } },
            axisTick: { show: false }, splitLine: { show: false },
            axisLabel: {
                distance: 22, fontSize: 9, color: '#64748b',
                formatter: function(v) { if(v===0) return '\u6E05\u4ED3'; if(v===25) return '\u4F4E\u914D'; if(v===40) return '\u51CF\u4ED3'; if(v===55) return '\u6807\u914D'; if(v===70) return '\u4E70\u5165'; if(v===100) return ''; return ''; }
            },
            detail: {
                valueAnimation: true, fontSize: 26, fontWeight: 'bold', color: color,
                offsetCenter: [0, '10%'],
                formatter: function(v) { return v + '\n' + (signal.label || ''); }
            },
            data: [{ value: score }]
        }]
    });
    // 信号矩阵
    const matrix = document.getElementById('erp-signal-matrix');
    if (matrix && trade) {
        matrix.innerHTML = (trade.resonance_label || '') + ' | \u4ED3\u4F4D\u5EFA\u8BAE: <span style="color:' + color + ';font-weight:700;">' + (signal.position || '--') + '</span>';
    }
}

function renderERPHistoryChart(chart, signalData) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom) return;
    if (_erpHistoryChart) _erpHistoryChart.dispose();
    _erpHistoryChart = echarts.init(dom);
    const stats = chart.stats || {};
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);

    // V3.0: 动态标题
    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) {
        const yrs = stats.date_range_years || '?';
        titleEl.textContent = '\u{1F4C8} ERP \u5386\u53F2\u8D70\u52BF (\u8FD1' + yrs + '\u5E74) \u00B7 \u56DB\u6863\u533A\u95F4\u53EF\u89C6\u5316';
    }

    // V3.0: KPI 卡片
    renderERPChartKPIs(stats, signalData);

    // V3.0: markArea 四档色带 (对标 AIAE History Chart 模式)
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
            name: '\u5F53\u524D', symbol: 'pin', symbolSize: 44,
            itemStyle: { color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
            label: { formatter: '{@[1]}%', color: '#fff', fontSize: 10, fontWeight: 700 }
        });
    }
    // 极值标注
    const extremes = stats.extremes || [];
    extremes.forEach(e => {
        markPointData.push({
            coord: [e.date, e.value],
            name: e.type === 'max' ? '\u5386\u53F2\u6700\u9AD8' : '\u5386\u53F2\u6700\u4F4E',
            symbol: e.type === 'max' ? 'triangle' : 'arrow',
            symbolSize: 12, symbolRotate: e.type === 'min' ? 180 : 0,
            itemStyle: { color: e.type === 'max' ? '#10b981' : '#ef4444' },
            label: { show: true, formatter: e.value + '%', fontSize: 9, color: e.type === 'max' ? '#10b981' : '#ef4444', position: e.type === 'max' ? 'top' : 'bottom' }
        });
    });

    // 区间判定函数
    function getZoneLabel(v) {
        if (v >= (stats.strong_buy_line || 99)) return '\uD83D\uDFE2 \u5F3A\u4E70\u533A';
        if (v >= (stats.overweight_line || 99)) return '\uD83D\uDD35 \u8D85\u914D\u533A';
        if (v >= (stats.underweight_line || -99)) return '\u26AA \u4E2D\u6027\u533A';
        if (v >= (stats.danger_line || -99)) return '\uD83D\uDFE0 \u4F4E\u914D\u533A';
        return '\uD83D\uDD34 \u5371\u9669\u533A';
    }

    const legendData = ['ERP', 'PE-TTM', '10Y\u56FD\u503A'];
    if (hasM1) legendData.push('M1\u540C\u6BD4');

    _erpHistoryChart.setOption({
        tooltip: {
            trigger: 'axis', backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155',
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
            selected: { '10Y\u56FD\u503A': false }
        },
        toolbox: {
            right: 20, top: 0,
            feature: {
                saveAsImage: { title: '\u4FDD\u5B58', pixelRatio: 2, backgroundColor: '#0f172a' },
                restore: { title: '\u91CD\u7F6E' }
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
                        { yAxis: stats.mean, label: { formatter: '\u5747\u503C ' + stats.mean + '%', color: '#94a3b8', fontSize: 9 }, lineStyle: { color: '#64748b' } },
                        { yAxis: stats.overweight_line, label: { formatter: '\u8D85\u914D ' + stats.overweight_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98166' } },
                        { yAxis: stats.underweight_line, label: { formatter: '\u4F4E\u914D ' + stats.underweight_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444466' } },
                        { yAxis: stats.strong_buy_line, label: { formatter: '\u5F3A\u4E70 ' + stats.strong_buy_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98140', type: 'dotted' } },
                        { yAxis: stats.danger_line, label: { formatter: '\u5371\u9669 ' + stats.danger_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444440', type: 'dotted' } }
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
                name: '10Y\u56FD\u503A', type: 'line', data: chart.yield_10y, yAxisIndex: 0,
                lineStyle: { color: '#ef4444', width: 1, type: 'dotted' },
                itemStyle: { color: '#ef4444' }, symbol: 'none'
            },
            hasM1 ? {
                name: 'M1\u540C\u6BD4', type: 'line', data: chart.m1_yoy, yAxisIndex: 2,
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
    // V3.0: resize handler
    window.addEventListener('resize', () => _erpHistoryChart && _erpHistoryChart.resize());
}

// V3.0: ERP 图表 KPI 统计卡片
function renderERPChartKPIs(stats, signalData) {
    const container = document.getElementById('erp-chart-kpis');
    if (!container) return;
    const sig = signalData || {};
    const snap = sig.current_snapshot || {};
    const pct = snap.erp_percentile || '--';
    const deviation = stats.current_vs_mean;
    const devColor = deviation > 0 ? '#10b981' : (deviation < -5 ? '#ef4444' : '#f59e0b');
    const devSign = deviation > 0 ? '+' : '';

    container.innerHTML = [
        { label: '\u5F53\u524D ERP', value: (stats.current || '--') + '%', color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
        { label: '\u5747\u503C\u504F\u79BB', value: devSign + deviation + '%', color: devColor },
        { label: '\u8FD14\u5E74\u5206\u4F4D', value: pct + '%', color: pct >= 70 ? '#10b981' : (pct <= 30 ? '#ef4444' : '#94a3b8') },
        { label: '\u8D85\u914D\u533A\u5360\u6BD4', value: (stats.buy_zone_pct || '--') + '%', color: '#10b981' },
    ].map(k => `<div style="flex:1;background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 12px;text-align:center;">
        <div style="font-size:0.65rem;color:#64748b;margin-bottom:3px;">${k.label}</div>
        <div style="font-size:1.1rem;font-weight:800;color:${k.color};">${k.value}</div>
    </div>`).join('');
}

function renderERPEncyclopedia(enc) {
    const body = document.getElementById('erp-encyclopedia-body');
    if (!body || !enc) return;
    const order = ['erp_abs', 'erp_pct', 'm1_trend', 'volatility', 'credit'];
    const colors = ['#f59e0b', '#8b5cf6', '#3b82f6', '#ec4899', '#06b6d4'];
    body.innerHTML = order.map((key, i) => {
        const e = enc[key];
        if (!e) return '';
        const c = colors[i];
        return '<div style="background:rgba(15,23,42,0.6);border:1px solid ' + c + '30;border-radius:8px;padding:12px;">' +
            '<div style="font-size:0.8rem;font-weight:600;color:' + c + ';margin-bottom:6px;">' + e.title + '</div>' +
            '<div style="font-size:0.65rem;color:#cbd5e1;line-height:1.7;">' +
            '<div style="margin-bottom:4px;">\uD83D\uDCD6 <b>\u662F\u4EC0\u4E48:</b> ' + e.what + '</div>' +
            '<div style="margin-bottom:4px;">\u2753 <b>\u4E3A\u4EC0\u4E48\u91CD\u8981:</b> ' + e.why + '</div>' +
            '<div style="margin-bottom:4px;color:#f59e0b;">\u26A0\uFE0F <b>\u8B66\u793A:</b> ' + e.alert + '</div>' +
            '<div style="color:#64748b;">\uD83D\uDCDC <b>\u5386\u53F2:</b> ' + e.history + '</div></div></div>';
    }).join('');
}

function renderERPDiagnosis(cards) {
    const container = document.getElementById('erp-diagnosis-cards');
    if (!container) return;
    const typeMap = {
        success: { bg: 'rgba(16,185,129,0.08)', border: '#10b981', icon: '\u2705' },
        info:    { bg: 'rgba(59,130,246,0.08)', border: '#3b82f6', icon: '\u2139\uFE0F' },
        warning: { bg: 'rgba(245,158,11,0.08)', border: '#f59e0b', icon: '\u26A0\uFE0F' },
        danger:  { bg: 'rgba(239,68,68,0.08)',  border: '#ef4444', icon: '\uD83D\uDEA8' }
    };
    container.innerHTML = cards.map(c => {
        const style = typeMap[c.type] || typeMap.info;
        return '<div style="background:' + style.bg + ';border:1px solid ' + style.border + '33;border-left:3px solid ' + style.border + ';border-radius:8px;padding:10px 12px;">' +
            '<div style="font-size:0.75rem;font-weight:600;color:' + style.border + ';margin-bottom:3px;">' + style.icon + ' ' + c.title + '</div>' +
            '<div style="font-size:0.65rem;color:#cbd5e1;line-height:1.5;">' + c.text + '</div></div>';
    }).join('');
}

// 窗口resize
let _usErpChart = null, _jpErpChart = null, _hkErpChart = null;
window.addEventListener('resize', () => {
    if (_erpGaugeChart) _erpGaugeChart.resize();
    if (_erpHistoryChart) _erpHistoryChart.resize();
    if (_usErpChart) _usErpChart.resize();
    if (_jpErpChart) _jpErpChart.resize();
    if (_hkErpChart) _hkErpChart.resize();
    if (_usGaugeChart) _usGaugeChart.resize();
    if (_jpGaugeChart) _jpGaugeChart.resize();
    if (_hkGaugeChart) _hkGaugeChart.resize();
});

// ============================================================
// 🌐 海外ERP择时 V2.0 — 渲染引擎 (升级版)
// ============================================================
let _globalERPData = null;
let _usGaugeChart = null, _jpGaugeChart = null, _hkGaugeChart = null;

async function loadGlobalERP() {
    const btn = document.getElementById('global-erp-refresh');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 加载中...'; }
    try {
        const resp = await fetch('/api/v1/strategy/erp-global');
        const json = await resp.json();
        if (json.status === 'success') {
            _globalERPData = json;
            renderRegionPanel('us', json.us, '#3b82f6');
            renderRegionPanel('jp', json.jp, '#dc2626');
            // HK panel (use hk_hsi as primary)
            if (json.hk_hsi) {
                renderRegionPanel('hk', json.hk_hsi, '#a855f7');
            }
            renderGlobalAlerts('us', json.us);
            renderGlobalAlerts('jp', json.jp);
            if (json.hk_hsi) {
                renderGlobalAlerts('hk', json.hk_hsi);
            }
            renderGlobalComparison(json.global_comparison);
            renderGlobalEncyclopedia(json.us, json.jp, json.hk_hsi);
            if (json.us && json.us.chart) renderRegionChart('us', json.us.chart, '#3b82f6');
            if (json.jp && json.jp.chart) renderRegionChart('jp', json.jp.chart, '#dc2626');
            if (json.hk_hsi && json.hk_hsi.chart) renderRegionChart('hk', json.hk_hsi.chart, '#a855f7');
            const t = document.getElementById('global-erp-update-time');
            if (t) t.textContent = '更新: ' + new Date().toLocaleTimeString('zh-CN');
        } else {
            console.error('[Global ERP] Error:', json.message);
        }
    } catch (e) { console.error('[Global ERP] Fetch failed:', e); }
    if (btn) { btn.disabled = false; btn.innerHTML = '🔄 刷新全球数据'; }
}

// ---- 警示横幅 ----
function renderGlobalAlerts(region, data) {
    if (!data) return;
    const alerts = data.alerts || [];
    const el = document.getElementById('global-alert-' + region);
    if (!el) return;
    const danger = alerts.filter(a => a.level === 'danger' || a.level === 'opportunity');
    if (!danger.length) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    const flag = region === 'us' ? '🇺🇸' : region === 'jp' ? '🇯🇵' : '🇭🇰';
    el.innerHTML = danger.map(a => {
        const bg = a.level === 'danger' ? 'rgba(239,68,68,0.08)' : 'rgba(16,185,129,0.08)';
        const bc = a.level === 'danger' ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)';
        const pulse = a.pulse ? 'animation:pulse-glow 2s infinite;' : '';
        return '<div style="padding:7px 14px;border:1px solid '+bc+';background:'+bg+';border-radius:8px;font-size:0.72rem;color:#e2e8f0;'+pulse+'">' +
            flag + ' ' + a.icon + ' ' + a.text + '</div>';
    }).join('');
}

// ---- 信号色带 V2.0 ----
function renderSignalLevelBar(elId, currentKey) {
    const el = document.getElementById(elId);
    if (!el) return;
    const levels = [
        {k:'strong_buy',c:'#10b981',l:'SB'},{k:'buy',c:'#34d399',l:'B'},{k:'hold',c:'#3b82f6',l:'H'},
        {k:'reduce',c:'#f59e0b',l:'R'},{k:'underweight',c:'#f97316',l:'UW'},{k:'cash',c:'#ef4444',l:'C'}
    ];
    el.innerHTML = levels.map(lv => {
        const active = lv.k === currentKey;
        return '<div style="width:18px;height:10px;border-radius:3px;background:' + lv.c + (active ? '' : '22') + ';' +
            (active ? 'box-shadow:0 0 8px '+lv.c+';transform:scaleY(1.4);' : '') + '" title="'+lv.l+'"></div>';
    }).join('');
}

// ---- 仪表盘 V2.0 (放大+渐变弧线) ----
function renderMiniGauge(elId, score, color) {
    const el = document.getElementById(elId);
    if (!el) return;
    const chart = echarts.init(el);
    if (elId.startsWith('us')) _usGaugeChart = chart;
    else if (elId.startsWith('jp')) _jpGaugeChart = chart;
    else if (elId.startsWith('hk')) _hkGaugeChart = chart;
    chart.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
            pointer: { show: true, length: '60%', width: 4, itemStyle: { color: color } },
            axisLine: { lineStyle: { width: 12, color: [[0.25,'#ef4444'],[0.45,'#f59e0b'],[0.65,'#3b82f6'],[0.85,'#34d399'],[1,'#10b981']] } },
            axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
            detail: { show: true, offsetCenter: [0, '70%'], fontSize: 11, color: '#94a3b8',
                formatter: v => v.toFixed(0) + '分' },
            data: [{ value: score }]
        }]
    });
}

// ---- 主面板渲染 V2.0 ----
function renderRegionPanel(region, data, accentColor) {
    if (!data) return;
    const snap = data.current_snapshot || {};
    const sig = data.signal || {};
    const dims = data.dimensions || {};
    const trade = data.trade_rules || {};

    const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setC = (id, c) => { const el = document.getElementById(id); if (el) el.style.color = c; };

    // Hero ERP Card
    const erpVal = (snap.erp_value||0);
    setT(region+'-val-erp', erpVal.toFixed(2) + '%');
    setC(region+'-val-erp', erpVal >= 3 ? '#10b981' : erpVal >= 1 ? '#f59e0b' : '#ef4444');
    // Hero card border glow based on signal
    const heroCard = document.getElementById(region+'-hero-card');
    if (heroCard) {
        heroCard.style.borderColor = (sig.color||accentColor) + '44';
        heroCard.style.boxShadow = '0 0 24px ' + (sig.color||accentColor) + '15';
    }

    // Aux metrics
    setT(region+'-val-pe', (snap.pe_ttm||0).toFixed(1) + 'x');
    setT(region+'-val-yield', (snap.yield_10y||0).toFixed(2) + '%');
    setT(region+'-sub-pe', 'E/Y ' + (snap.earnings_yield||0).toFixed(1) + '%');

    if (region === 'us') {
        const vix = (dims.vix||{}).vix_info || {};
        const fed = (dims.fed_liquidity||{}).fed_info || {};
        const crd = (dims.credit_spread||{}).credit_info || {};
        setT('us-val-vix', (vix.current||0).toFixed(1));
        setC('us-val-vix', (vix.current||0)>=30?'#ef4444':(vix.current||0)>=20?'#f59e0b':'#10b981');
        setT('us-sub-vix', vix.regime==='extreme_panic'?'极端恐慌':vix.regime==='high_fear'?'高恐慌':vix.regime==='elevated_high'?'明显偏高':vix.regime==='elevated'?'偏高':vix.regime==='mild_elevated'?'略偏高':vix.regime==='normal'?'正常':vix.regime==='complacent'?'偏低':'--');
        setT('us-val-rate', (fed.current||0).toFixed(2)+'%');
        setC('us-val-rate', fed.direction==='easing'?'#10b981':'#f59e0b');
        setT('us-sub-rate', fed.direction==='easing'?'宽松':'紧缩');
        setT('us-val-credit', (crd.spread||0).toFixed(1)+'%');
        setC('us-val-credit', (crd.spread||0)<=3?'#10b981':(crd.spread||0)<=5?'#f59e0b':'#ef4444');
        setT('us-sub-credit', (crd.raw_bps||0)+'bps '+(crd.trend==='tightening'?'收窄':'走阔'));
    } else if (region === 'jp') {
        const yen = (dims.yen_trend||{}).yen_info || {};
        const vol = (dims.volatility||{}).vol_info || {};
        const rate = (dims.rate_env||{}).rate_info || {};
        setT('jp-val-yen', (yen.current||0).toFixed(1));
        setC('jp-val-yen', (yen.current||0)>155?'#ef4444':(yen.current||0)>145?'#f59e0b':'#10b981');
        setT('jp-sub-yen', yen.direction==='weakening'?'日元贬值':'日元升值');
        setT('jp-val-vol', (vol.current||0).toFixed(1)+'%');
        setC('jp-val-vol', vol.regime==='extreme_panic'?'#ef4444':vol.regime==='high'?'#f59e0b':'#10b981');
        setT('jp-sub-vol', vol.pct?(vol.pct.toFixed(0)+'%分位'):'--');
        setT('jp-val-rate', (rate.jgb_now||0).toFixed(3)+'%');
        setC('jp-val-rate', rate.jgb_direction==='rising'?'#ef4444':'#10b981');
        setT('jp-sub-rate', rate.jgb_direction==='rising'?'上行(收紧)':rate.jgb_direction==='falling'?'下行(宽松)':'稳定');
    } else if (region === 'hk') {
        // HK-specific aux metrics
        const sb = (dims.southbound||{}).sb_info || {};
        const vol = (dims.vhsi||{}).vol_info || {};
        const rspread = (dims.rate_spread||{}).spread_info || {};
        // Blended Rf
        setT('hk-val-yield', (snap.blended_rf||snap.yield_10y||0).toFixed(2)+'%');
        // Southbound
        const sbWeekly = sb.weekly||0;
        setT('hk-val-sb', (sbWeekly>=0?'+':'')+sbWeekly.toFixed(0)+'亿');
        setC('hk-val-sb', sbWeekly>0?'#10b981':'#ef4444');
        setT('hk-sub-sb', sb.direction==='inflow'?'净流入':'净流出');
        // HSI Vol
        setT('hk-val-vol', (vol.current||0).toFixed(1)+'%');
        setC('hk-val-vol', vol.regime==='extreme_panic'?'#ef4444':vol.regime==='high'?'#f59e0b':'#10b981');
        setT('hk-sub-vol', vol.pct?(vol.pct.toFixed(0)+'%分位'):'--');
        // Rate spread
        const spread = rspread.spread||0;
        setT('hk-val-spread', (spread>=0?'+':'')+spread.toFixed(1)+'%');
        setC('hk-val-spread', spread>2.5?'#ef4444':spread>1.5?'#f59e0b':'#10b981');
        setT('hk-sub-spread', rspread.trend==='widening'?'走阔↑':rspread.trend==='narrowing'?'收窄↓':'稳定');
    }

    // Signal Decision Banner V2.0
    const banner = document.getElementById(region+'-signal-banner');
    if (banner && sig.color) {
        banner.style.background = (sig.color||'#94a3b8') + '12';
        banner.style.borderColor = (sig.color||'#94a3b8') + '44';
    }
    setT(region+'-composite-score', sig.score||'--');
    setC(region+'-composite-score', sig.color||'#94a3b8');
    const sigLabel = document.getElementById(region+'-signal-label');
    if (sigLabel) {
        sigLabel.textContent = (sig.emoji||'')+' '+(sig.label||'');
        sigLabel.style.color = sig.color||'#94a3b8';
    }
    const sigPos = document.getElementById(region+'-signal-pos');
    if (sigPos) sigPos.textContent = '仓位: '+(sig.position||'--');

    // Signal level bar
    renderSignalLevelBar(region+'-signal-level-bar', sig.key||'hold');

    // Signal badge
    const badge = document.getElementById(region+'-signal-badge');
    if (badge) {
        badge.textContent = (sig.emoji||'') + ' ' + (sig.label||'');
        badge.style.background = (sig.color||'#94a3b8') + '22';
        badge.style.color = sig.color||'#94a3b8';
        badge.style.border = '1px solid '+(sig.color||'#94a3b8')+'44';
    }

    // ETF配置
    const etfEl = document.getElementById(region+'-etf-advice');
    if (etfEl && trade.etf_advice) {
        etfEl.innerHTML = trade.etf_advice.map(e =>
            '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(100,116,139,0.1);"><span>'+(e.etf?e.etf.name:'')+'</span><span style="color:#fbbf24;font-weight:600;">'+e.ratio+'</span></div>'
        ).join('');
    }

    // 止盈规则
    const tpEl = document.getElementById(region+'-take-profit');
    if (tpEl && trade.take_profit) {
        tpEl.innerHTML = trade.take_profit.map(r => {
            const triggered = r.triggered;
            const bg = triggered ? 'background:rgba(16,185,129,0.12);border-left:2px solid #10b981;padding-left:6px;border-radius:3px;' : '';
            const currentTag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.58rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:2px 0;margin-bottom:2px;'+bg+'"><span style="color:#10b981;">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+currentTag+'</div>';
        }).join('');
    }

    // 止损规则
    const slEl = document.getElementById(region+'-stop-loss');
    if (slEl && trade.stop_loss) {
        slEl.innerHTML = trade.stop_loss.map(r => {
            const triggered = r.triggered;
            const trigColor = r.color || '#f59e0b';
            const bg = triggered ? 'background:rgba('+(trigColor==='#10b981'?'16,185,129':'239,68,68')+',0.12);border-left:2px solid '+trigColor+';padding-left:6px;border-radius:3px;' : '';
            const currentTag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.58rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:2px 0;margin-bottom:2px;'+bg+'"><span style="color:'+trigColor+';">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+currentTag+'</div>';
        }).join('');
    }

    // 共振标签
    const resEl = document.getElementById('global-resonance-'+region);
    if (resEl && trade.resonance_label) {
        const flag = region==='us'?'🇺🇸':region==='jp'?'🇯🇵':'🇭🇰';
        resEl.textContent = flag + ' ' + trade.resonance_label;
    }

    // 仪表盘 V2.0 (放大)
    setTimeout(() => renderMiniGauge(region+'-gauge-chart', sig.score||0, accentColor), 50);

    // 五维评分条 V2.0 (增强版)
    const barsEl = document.getElementById(region+'-dim-bars');
    if (barsEl) {
        barsEl.innerHTML = Object.keys(dims).map(k => {
            const d = dims[k]; const s = d.score||0;
            const w = d.weight?(d.weight*100).toFixed(0)+'%':'';
            const bc = s>=70?'#10b981':s>=40?'#f59e0b':'#ef4444';
            return '<div class="erp-dim-row">' +
                '<span class="erp-dim-label">'+(d.label||k)+' <span class="erp-dim-weight">'+w+'</span></span>' +
                '<div class="erp-dim-track"><div class="erp-dim-fill" style="width:'+s+'%;background:linear-gradient(90deg,'+bc+'cc,'+bc+');"></div></div>' +
                '<span class="erp-dim-score" style="color:'+bc+';">'+s.toFixed(0)+'</span></div>';
        }).join('');
    }

    // 诊断卡片 V2.0 (2列)
    const diagEl = document.getElementById(region+'-diagnosis');
    if (diagEl && data.diagnosis) {
        const typeMap = {
            success: {bg:'rgba(16,185,129,0.06)',border:'#10b981',icon:'✅'},
            info: {bg:'rgba(59,130,246,0.06)',border:'#3b82f6',icon:'ℹ️'},
            warning: {bg:'rgba(245,158,11,0.06)',border:'#f59e0b',icon:'⚠️'},
            danger: {bg:'rgba(239,68,68,0.06)',border:'#ef4444',icon:'🔴'}
        };
        diagEl.innerHTML = data.diagnosis.map(c => {
            const st = typeMap[c.type]||typeMap.info;
            return '<div style="background:'+st.bg+';border:1px solid '+st.border+'33;border-left:3px solid '+st.border+';border-radius:8px;padding:10px 12px;">' +
                '<div style="font-size:0.68rem;font-weight:700;color:'+st.border+';margin-bottom:4px;">'+st.icon+' '+c.title+'</div>' +
                '<div style="font-size:0.6rem;color:#cbd5e1;line-height:1.5;">'+c.text+'</div></div>';
        }).join('');
    }
}

// ---- 规则百科 ----
function renderGlobalEncyclopedia(usData, jpData, hkData) {
    const el = document.getElementById('global-encyclopedia-body');
    if (!el) return;
    const usEnc = (usData||{}).encyclopedia || {};
    const jpEnc = (jpData||{}).encyclopedia || {};
    const hkEnc = (hkData||{}).encyclopedia || {};
    let html = '<div><h4 style="margin:0 0 8px;font-size:0.8rem;color:#60a5fa;">🇺🇸 美股五维指标</h4>';
    for (const [k,v] of Object.entries(usEnc)) {
        html += '<div style="background:rgba(59,130,246,0.04);border:1px solid rgba(59,130,246,0.15);border-radius:6px;padding:8px;margin-bottom:6px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:#60a5fa;margin-bottom:3px;">'+v.title+'</div>' +
            '<div style="font-size:0.62rem;color:#cbd5e1;line-height:1.5;">' +
            '<b style="color:#94a3b8;">是什么:</b> '+v.what+'<br>' +
            '<b style="color:#94a3b8;">为什么:</b> '+v.why+'<br>' +
            '<b style="color:#f59e0b;">⚠️ 警示:</b> <span style="color:#f59e0b;">'+v.alert+'</span>' +
            (v.history ? '<br><b style="color:#94a3b8;">📊 历史:</b> '+v.history : '') +
            '</div></div>';
    }
    html += '</div><div><h4 style="margin:0 0 8px;font-size:0.8rem;color:#f87171;">🇯🇵 日本五维指标</h4>';
    for (const [k,v] of Object.entries(jpEnc)) {
        html += '<div style="background:rgba(220,38,38,0.04);border:1px solid rgba(220,38,38,0.15);border-radius:6px;padding:8px;margin-bottom:6px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:#f87171;margin-bottom:3px;">'+v.title+'</div>' +
            '<div style="font-size:0.62rem;color:#cbd5e1;line-height:1.5;">' +
            '<b style="color:#94a3b8;">是什么:</b> '+v.what+'<br>' +
            '<b style="color:#94a3b8;">为什么:</b> '+v.why+'<br>' +
            '<b style="color:#f59e0b;">⚠️ 警示:</b> <span style="color:#f59e0b;">'+v.alert+'</span>' +
            '</div></div>';
    }
    html += '</div>';
    // HK Encyclopedia
    if (Object.keys(hkEnc).length > 0) {
        html += '<div style="grid-column:1/-1;"><h4 style="margin:0 0 8px;font-size:0.8rem;color:#c084fc;">🇭🇰 港股五维指标</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">';
        for (const [k,v] of Object.entries(hkEnc)) {
            html += '<div style="background:rgba(168,85,247,0.04);border:1px solid rgba(168,85,247,0.15);border-radius:6px;padding:8px;">' +
                '<div style="font-size:0.72rem;font-weight:600;color:#c084fc;margin-bottom:3px;">'+v.title+'</div>' +
                '<div style="font-size:0.62rem;color:#cbd5e1;line-height:1.5;">' +
                '<b style="color:#94a3b8;">是什么:</b> '+v.what+'<br>' +
                '<b style="color:#94a3b8;">为什么:</b> '+v.why+'<br>' +
                '<b style="color:#f59e0b;">⚠️ 警示:</b> <span style="color:#f59e0b;">'+v.alert+'</span>' +
                '</div></div>';
        }
        html += '</div></div>';
    }
    el.innerHTML = html;
}

// ---- 三地对比 V2.0 (含皇冠动画) ----
function renderGlobalComparison(gc) {
    if (!gc) return;
    const setT = (id,v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
    const setCS = (id,c) => { const el=document.getElementById(id); if(el) el.style.color=c; };
    const scores = {};
    ['cn','us','jp','hk'].forEach(r => {
        const d = gc[r]||{};
        scores[r] = d.score||0;
        setT('global-'+r+'-erp', (d.erp||0).toFixed(2)+'%');
        setT('global-'+r+'-score', '得分: '+(d.score||0).toFixed(0));
        const sigEl = document.getElementById('global-'+r+'-signal');
        if (sigEl) { sigEl.textContent = (d.emoji||'')+' '+(d.label||'--'); sigEl.style.color = d.color||'#94a3b8'; }

        // 决策矩阵表格
        setT('gm-'+r+'-pe', (d.pe||0).toFixed(1)+'x');
        setT('gm-'+r+'-yield', (d.yield||0).toFixed(2)+'%');
        const erpCell = document.getElementById('gm-'+r+'-erp');
        if (erpCell) { erpCell.textContent = (d.erp||0).toFixed(2)+'%'; erpCell.style.color = (d.erp||0)>=3?'#10b981':(d.erp||0)>=1?'#f59e0b':'#ef4444'; }
        const scoreCell = document.getElementById('gm-'+r+'-score');
        if (scoreCell) { scoreCell.textContent = (d.score||0).toFixed(0); scoreCell.style.color = d.color||'#94a3b8'; }
        const sigCell = document.getElementById('gm-'+r+'-signal');
        if (sigCell) { sigCell.textContent = (d.emoji||'')+' '+(d.label||'--'); sigCell.style.color = d.color||'#94a3b8'; }
    });

    // V2.0: 皇冠动画 — 最高分卡片获得皇冠
    const maxScore = Math.max(scores.cn||0, scores.us||0, scores.jp||0, scores.hk||0);
    ['cn','us','jp','hk'].forEach(r => {
        const card = document.getElementById('global-'+r+'-card');
        const crown = document.getElementById('global-'+r+'-crown');
        const d = gc[r]||{};
        if (card) {
            if (scores[r] === maxScore && maxScore > 0) {
                card.classList.add('winner');
                card.style.borderColor = (d.color||'#fbbf24') + '88';
                card.style.boxShadow = '0 0 24px '+(d.color||'#fbbf24')+'25';
                if (crown) { crown.style.display = 'block'; crown.innerHTML = '<span class="erp-crown">👑</span>'; }
            } else {
                card.classList.remove('winner');
                card.style.boxShadow = 'none';
                if (crown) crown.style.display = 'none';
            }
        }
    });

    const advEl = document.getElementById('global-advice');
    if (advEl && gc.advice) advEl.textContent = '🌍 ' + gc.advice;

    // 配置比例条
    const allocBar = document.getElementById('global-allocation-bar');
    const allocText = document.getElementById('global-allocation-text');
    if (allocBar && gc.allocation) {
        const alloc = gc.allocation;
        const colors = {cn:'#ef4444', us:'#3b82f6', jp:'#dc2626', hk:'#a855f7'};
        const flags = {cn:'🇨🇳', us:'🇺🇸', jp:'🇯🇵', hk:'🇭🇰'};
        allocBar.innerHTML = ['cn','us','jp','hk'].map(r => {
            const pct = alloc[r] || 0;
            return '<div style="width:'+pct+'%;background:linear-gradient(135deg,'+colors[r]+','+colors[r]+'bb);display:flex;align-items:center;justify-content:center;font-size:0.72rem;color:white;font-weight:700;transition:width 0.6s;">'+flags[r]+' '+pct+'%</div>';
        }).join('');
    }
    if (allocText && gc.allocation_text) {
        allocText.textContent = gc.allocation_text;
    }
}

// ---- ERP走势图 V2.0 (含买卖区间阴影) ----
function renderRegionChart(region, chart, color) {
    if (!chart || chart.status !== 'success') return;
    const el = document.getElementById(region+'-erp-chart');
    if (!el) return;
    const instance = echarts.init(el);
    if (region === 'us') _usErpChart = instance;
    else if (region === 'jp') _jpErpChart = instance;
    else if (region === 'hk') _hkErpChart = instance;
    const stats = chart.stats || {};
    instance.setOption({
        backgroundColor: 'transparent',
        grid: { top: 30, right: 12, bottom: 30, left: 40 },
        tooltip: { trigger:'axis', backgroundColor:'rgba(15,23,42,0.95)', borderColor:color+'44',
            textStyle:{color:'#e2e8f0',fontSize:11},
            formatter: p => { if (!p.length) return ''; let s='<b>'+p[0].axisValue+'</b><br/>'; p.forEach(i=>s+='<span style="color:'+i.color+'">●</span> '+i.seriesName+': <b>'+i.value+'%</b><br/>'); return s; }
        },
        xAxis: { type:'category', data:chart.dates, axisLabel:{color:'#64748b',fontSize:9,formatter:v=>v.substring(2,7)}, axisLine:{lineStyle:{color:'#334155'}} },
        yAxis: { type:'value', axisLabel:{color:'#64748b',fontSize:10,formatter:'{value}%'}, splitLine:{lineStyle:{color:'#1e293b'}} },
        series: [
            { name:'ERP', type:'line', data:chart.erp, smooth:true,
              lineStyle:{color:color,width:2.5},
              areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:color+'44'},{offset:1,color:color+'05'}]}},
              itemStyle:{color:color}, symbol:'none' },
            { name:'超配线', type:'line', data:chart.dates.map(()=>stats.overweight_line),
              lineStyle:{color:'#10b981',type:'dashed',width:1}, symbol:'none', itemStyle:{color:'#10b981'} },
            { name:'低配线', type:'line', data:chart.dates.map(()=>stats.underweight_line),
              lineStyle:{color:'#ef4444',type:'dashed',width:1}, symbol:'none', itemStyle:{color:'#ef4444'} },
        ]
    });
}

// Tab切换钩子
(function() {
    document.querySelectorAll('.st-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            if (this.dataset.report === 'st-aiae-global' && !_globalAIAEData) {
                setTimeout(loadGlobalAIAE, 100);
            }
            if (this.dataset.report === 'st-erp-global' && !_globalERPData) {
                setTimeout(loadGlobalERP, 100);
            }
            if (this.dataset.report === 'st-rates-strategy' && !_ratesData) {
                setTimeout(loadRatesStrategy, 100);
            }
        });
    });
})();

// 🏦 利率择时引擎 V1.5 — JS渲染
// ═══════════════════════════════════════════════
let _ratesData = null;
let _ratesGaugeChart = null;
let _ratesMainChart = null;

async function loadRatesStrategy() {
    const btn = document.getElementById('rates-refresh-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 加载中...'; }
    try {
        const resp = await fetch('/api/v1/strategy/rates');
        const json = await resp.json();
        if (json.status === 'success' && json.data) {
            _ratesData = json.data;
            renderRatesPanel(json.data);
            const t = document.getElementById('rates-update-time');
            if (t) t.textContent = '更新: ' + new Date().toLocaleTimeString('zh-CN');
        } else {
            console.error('[Rates] Error:', json.message || json);
        }
    } catch (e) { console.error('[Rates] Fetch failed:', e); }
    if (btn) { btn.disabled = false; btn.innerHTML = '🔄 刷新利率数据'; }
}

function renderRatesPanel(data) {
    if (!data) return;
    const snap = data.current_snapshot || {};
    const dims = data.dimensions || {};
    const signal = data.signal || {};
    const trade = data.trade_rules || {};
    const trSig = trade.signal || signal;

    const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setC = (id, c) => { const el = document.getElementById(id); if (el) el.style.color = c; };

    const rcn = snap.regime_cn || {};

    // === Regime Badge (Hero) ===
    const regBadge = document.getElementById('rates-regime-badge');
    if (regBadge && data.buy_sell_zones) {
        const bsz = data.buy_sell_zones;
        regBadge.textContent = bsz.regime_label || '';
        regBadge.style.background = (bsz.conclusion_color||'#94a3b8') + '22';
        regBadge.style.color = bsz.conclusion_color||'#94a3b8';
        regBadge.style.border = '1px solid '+(bsz.conclusion_color||'#94a3b8')+'44';
    }

    // === ZONE 1: 快照卡片 (中文Regime + alert hint) ===
    setT('rates-val-10y', (snap.yield_10y||0).toFixed(2) + '%');
    setC('rates-val-10y', (snap.yield_10y||0)>=4.5?'#10b981':(snap.yield_10y||0)>=3.5?'#f59e0b':'#ef4444');
    const ylInfo = (dims.yield_level||{}).yield_info || {};
    setT('rates-sub-10y', (rcn.yield_level||'--') + ' | 分位'+(ylInfo.pct||0).toFixed(0)+'%');

    setT('rates-val-2y', (snap.yield_2y||0).toFixed(2) + '%');
    setC('rates-val-2y', '#e2e8f0');
    setT('rates-sub-2y', '短端 | Fed映射');

    const spreadBps = snap.spread_bps || 0;
    setT('rates-val-spread', (spreadBps >= 0 ? '+' : '') + spreadBps.toFixed(0) + 'bps');
    setC('rates-val-spread', spreadBps < 0 ? '#ef4444' : spreadBps < 50 ? '#f59e0b' : '#10b981');
    setT('rates-sub-spread', (rcn.curve||'--') + (spreadBps < 0 ? ' ⚠️' : ''));

    setT('rates-val-real', (snap.real_yield||0).toFixed(2) + '%');
    setC('rates-val-real', (snap.real_yield||0)>=2?'#10b981':(snap.real_yield||0)>=1?'#f59e0b':'#ef4444');
    setT('rates-sub-real', (rcn.real_yield||'--'));

    const momInfo = (dims.yield_momentum||{}).momentum_info || {};
    const chg3m = momInfo.chg_3m_bps || 0;
    setT('rates-val-momentum', (chg3m >= 0 ? '+' : '') + chg3m.toFixed(0) + 'bps');
    setC('rates-val-momentum', chg3m < -30 ? '#10b981' : chg3m > 30 ? '#ef4444' : '#f59e0b');
    setT('rates-sub-momentum', (rcn.momentum||'--') + (chg3m < 0 ? ' 📉' : ' 📈'));

    setT('rates-val-bei', (snap.breakeven||0).toFixed(2) + '%');
    setC('rates-val-bei', (snap.breakeven||0) > 2.5 ? '#ef4444' : '#e2e8f0');
    setT('rates-sub-bei', '通胀预期');

    // Alert hints
    const hints = data.alert_hints || {};
    setT('rates-hint-10y', hints.yield_10y || '');
    setT('rates-hint-2y', hints.yield_2y || '');
    setT('rates-hint-spread', hints.spread || '');
    setT('rates-hint-real', hints.real_yield || '');
    setT('rates-hint-momentum', hints.momentum || '');
    setT('rates-hint-bei', hints.bei || '');

    // === ZONE 2: 信号badge ===
    const badge = document.getElementById('rates-signal-badge');
    if (badge) {
        badge.textContent = (trSig.emoji||'') + ' ' + (trSig.label||'');
        badge.style.background = (trSig.color||'#94a3b8') + '22';
        badge.style.color = trSig.color||'#94a3b8';
        badge.style.border = '1px solid '+(trSig.color||'#94a3b8')+'44';
    }

    // ETF
    const etfEl = document.getElementById('rates-etf-advice');
    if (etfEl && trade.etf_advice) {
        etfEl.innerHTML = trade.etf_advice.map(e =>
            '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(100,116,139,0.1);"><span>'+(e.etf?e.etf.name:'')+'</span><span style="color:#fbbf24;font-weight:600;">'+e.ratio+'</span></div>'
        ).join('');
    }

    // 止盈 (动态高亮)
    const tpEl = document.getElementById('rates-take-profit');
    if (tpEl && trade.take_profit) {
        tpEl.innerHTML = trade.take_profit.map(r => {
            const triggered = r.triggered;
            const bg = triggered ? 'background:rgba(16,185,129,0.12);border-left:2px solid #10b981;padding-left:6px;border-radius:3px;' : '';
            const tag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.6rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:3px 0;margin-bottom:3px;'+bg+'"><span style="color:#10b981;">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+tag+'</div>';
        }).join('');
    }

    // 止损 (动态高亮)
    const slEl = document.getElementById('rates-stop-loss');
    if (slEl && trade.stop_loss) {
        slEl.innerHTML = trade.stop_loss.map(r => {
            const triggered = r.triggered;
            const trigColor = r.color || '#f59e0b';
            const bg = triggered ? 'background:rgba('+(trigColor==='#10b981'?'16,185,129':'239,68,68')+',0.12);border-left:2px solid '+trigColor+';padding-left:6px;border-radius:3px;' : '';
            const tag = triggered && r.current ? ' <span style="color:#f59e0b;font-size:0.6rem;">[✅'+r.current+']</span>' : '';
            return '<div style="padding:3px 0;margin-bottom:3px;'+bg+'"><span style="color:'+trigColor+';">▸</span> '+r.trigger+' → <b>'+r.action+'</b>'+tag+'</div>';
        }).join('');
    }

    // === 综合得分 + 信号标签 ===
    setT('rates-composite-score', trSig.score || '--');
    setC('rates-composite-score', trSig.color || '#94a3b8');
    const sigLabel = document.getElementById('rates-signal-label');
    if (sigLabel) {
        sigLabel.textContent = (trSig.emoji||'')+' '+(trSig.label||'')+' ('+(trSig.position||'')+')';
        sigLabel.style.color = trSig.color||'#94a3b8';
    }

    // 仪表盘
    setTimeout(() => renderRatesGauge(trSig.score||0), 50);

    // 五维评分条 (新增desc行)
    const barsEl = document.getElementById('rates-dim-bars');
    if (barsEl) {
        barsEl.innerHTML = Object.keys(dims).map(k => {
            const d = dims[k]; const s = d.score||0;
            const w = d.weight?(d.weight*100).toFixed(0)+'%':'';
            const bc = s>=70?'#10b981':s>=40?'#f59e0b':'#ef4444';
            const desc = d.desc ? '<div style="font-size:0.48rem;color:#64748b;margin-top:1px;line-height:1.2;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'+d.desc+'</div>' : '';
            return '<div style="margin-bottom:5px;">' +
                '<div style="display:flex;align-items:center;gap:5px;">' +
                '<span style="font-size:0.6rem;color:#94a3b8;width:62px;text-align:right;flex-shrink:0;">'+d.label+'<span style="color:#475569;font-size:0.5rem;"> '+w+'</span></span>' +
                '<div style="flex:1;height:5px;background:rgba(30,41,59,0.8);border-radius:3px;overflow:hidden;">' +
                '<div style="width:'+s+'%;height:100%;background:'+bc+';border-radius:3px;transition:width 0.6s;"></div></div>' +
                '<span style="font-size:0.6rem;color:'+bc+';width:24px;text-align:right;">'+s.toFixed(0)+'</span></div>'+desc+'</div>';
        }).join('');
    }

    // === ZONE 4: 配置比例条 ===
    const allocBar = document.getElementById('rates-allocation-bar');
    if (allocBar && trSig.stock_pct !== undefined) {
        const items = [
            {label:'📈 股票', pct:trSig.stock_pct, color:'#f59e0b'},
            {label:'🏦 债券', pct:trSig.bond_pct, color:'#c084fc'},
            {label:'🥇 黄金', pct:trSig.gold_pct, color:'#fbbf24'},
        ];
        allocBar.innerHTML = items.map(i =>
            '<div style="width:'+i.pct+'%;background:'+i.color+';display:flex;align-items:center;justify-content:center;font-size:0.72rem;color:white;font-weight:600;transition:width 0.5s;">'+i.label+' '+i.pct+'%</div>'
        ).join('');
        setT('rates-alloc-stock', '📈 股票 '+trSig.stock_pct+'%');
        setT('rates-alloc-bond', '🏦 债券 '+trSig.bond_pct+'%');
        setT('rates-alloc-gold', '🥇 黄金 '+trSig.gold_pct+'%');
        setT('rates-alloc-duration', '久期: '+trSig.duration);
    }

    // === 决策汇总区 ===
    if (data.buy_sell_zones) renderRatesDecisionZone(data.buy_sell_zones);

    // === 警示 ===
    renderRatesAlerts(data.alerts || []);

    // === 诊断 ===
    renderRatesDiagnosis(data.diagnosis || []);

    // === Tooltips ===
    if (data.card_tooltips) setupRatesTooltips(data.card_tooltips);

    // === 走势图 ===
    if (data.chart) renderRatesChart(data.chart);
}

function renderRatesGauge(score) {
    const el = document.getElementById('rates-gauge-chart');
    if (!el) return;
    if (_ratesGaugeChart) _ratesGaugeChart.dispose();
    _ratesGaugeChart = echarts.init(el);
    _ratesGaugeChart.setOption({
        series: [{
            type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
            pointer: { show: true, length: '55%', width: 3, itemStyle: { color: '#c084fc' } },
            axisLine: { lineStyle: { width: 8, color: [[0.2,'#ef4444'],[0.35,'#f97316'],[0.5,'#f59e0b'],[0.65,'#94a3b8'],[0.8,'#3b82f6'],[1,'#10b981']] } },
            axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
            detail: { show: false }, data: [{ value: score }]
        }]
    });
}

function renderRatesAlerts(alerts) {
    const el = document.getElementById('rates-alerts');
    if (!el) return;
    if (!alerts.length) { el.style.display = 'none'; return; }
    el.style.display = 'flex';
    el.innerHTML = alerts.map(a => {
        const bg = a.level==='danger'?'rgba(239,68,68,0.08)':a.level==='opportunity'?'rgba(16,185,129,0.08)':'rgba(245,158,11,0.08)';
        const bc = a.level==='danger'?'rgba(239,68,68,0.3)':a.level==='opportunity'?'rgba(16,185,129,0.3)':'rgba(245,158,11,0.3)';
        const pulse = a.pulse ? 'animation:pulse 2s infinite;' : '';
        return '<div style="padding:6px 14px;border:1px solid '+bc+';background:'+bg+';border-radius:6px;font-size:0.72rem;color:#e2e8f0;'+pulse+'">🏦 '+a.icon+' '+a.text+'</div>';
    }).join('');
}

function renderRatesDiagnosis(diagnosis) {
    const diagEl = document.getElementById('rates-diagnosis');
    if (!diagEl || !diagnosis.length) return;
    const typeMap = {
        success: {bg:'rgba(16,185,129,0.06)',border:'#10b981',icon:'✅'},
        info: {bg:'rgba(59,130,246,0.06)',border:'#3b82f6',icon:'ℹ️'},
        warning: {bg:'rgba(245,158,11,0.06)',border:'#f59e0b',icon:'⚠️'},
        danger: {bg:'rgba(239,68,68,0.06)',border:'#ef4444',icon:'🔴'}
    };
    diagEl.innerHTML = diagnosis.map(c => {
        const st = typeMap[c.type]||typeMap.info;
        return '<div style="background:'+st.bg+';border:1px solid '+st.border+'33;border-left:2px solid '+st.border+';border-radius:6px;padding:7px 9px;">' +
            '<div style="font-size:0.65rem;font-weight:600;color:'+st.border+';margin-bottom:2px;">'+st.icon+' '+c.title+'</div>' +
            '<div style="font-size:0.58rem;color:#cbd5e1;line-height:1.4;">'+c.text+'</div></div>';
    }).join('');
}

function renderRatesEncyclopedia(enc) {
    // V1.5: 百科已改为tooltip模式，此函数保留但不渲染
}

// === V1.5: 买卖决策汇总区 ===
function renderRatesDecisionZone(bsz) {
    const el = document.getElementById('rates-decision-zone');
    if (!el || !bsz) return;
    el.style.display = 'block';

    const renderConds = (items, color) => items.map(c => {
        const icon = c.met ? '<span style="color:#10b981;">✅</span>' : '<span style="color:#475569;">❌</span>';
        const valStyle = c.met ? 'color:#fbbf24;font-weight:600;' : 'color:#64748b;';
        return '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;">' +
            icon + '<span style="color:#cbd5e1;font-size:0.68rem;">' + c.cond + '</span>' +
            '<span style="'+valStyle+'font-size:0.65rem;margin-left:auto;">' + c.val + '</span>' +
            '<span style="font-size:0.55rem;color:#64748b;">' + c.why + '</span></div>';
    }).join('');

    el.innerHTML = 
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
        '<span style="font-size:0.82rem;font-weight:700;color:#c084fc;">📊 买卖决策汇总</span>' +
        '<div style="padding:4px 14px;border-radius:20px;font-size:0.72rem;font-weight:700;background:'+(bsz.conclusion_color||'#94a3b8')+'22;color:'+(bsz.conclusion_color||'#94a3b8')+';border:1px solid '+(bsz.conclusion_color||'#94a3b8')+'44;">'+bsz.conclusion+'</div></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">' +
        // 债券买入区
        '<div style="background:rgba(16,185,129,0.04);border:1px solid rgba(16,185,129,0.15);border-radius:8px;padding:10px;">' +
        '<div style="font-size:0.7rem;font-weight:600;color:#10b981;margin-bottom:6px;">🟢 债券买入区 <span style="font-size:0.6rem;color:#64748b;">'+bsz.bond_met+'/'+bsz.bond_buy.length+'</span></div>' +
        renderConds(bsz.bond_buy, '#10b981') + '</div>' +
        // 股票买入区
        '<div style="background:rgba(249,115,22,0.04);border:1px solid rgba(249,115,22,0.15);border-radius:8px;padding:10px;">' +
        '<div style="font-size:0.7rem;font-weight:600;color:#f97316;margin-bottom:6px;">🟠 股票超配区 <span style="font-size:0.6rem;color:#64748b;">'+bsz.stock_met+'/'+bsz.stock_buy.length+'</span></div>' +
        renderConds(bsz.stock_buy, '#f97316') + '</div>' +
        // 避险区
        '<div style="background:rgba(239,68,68,0.04);border:1px solid rgba(239,68,68,0.15);border-radius:8px;padding:10px;">' +
        '<div style="font-size:0.7rem;font-weight:600;color:#ef4444;margin-bottom:6px;">🔴 避险防御区 <span style="font-size:0.6rem;color:#64748b;">'+bsz.defense_met+'/'+bsz.defense.length+'</span></div>' +
        renderConds(bsz.defense, '#ef4444') + '</div>' +
        '</div>';
}

// === V1.5: 卡片Tooltip ===
let _ratesActiveTooltips = null;
function setupRatesTooltips(tips) {
    _ratesActiveTooltips = tips;
    const popup = document.getElementById('rates-tooltip-popup');
    if (!popup) return;
    document.querySelectorAll('.rates-card-tip').forEach(card => {
        card.addEventListener('mouseenter', function(e) {
            const key = this.dataset.tipKey;
            const tip = _ratesActiveTooltips[key];
            if (!tip) return;
            document.getElementById('rates-tip-title').textContent = tip.title || '';
            document.getElementById('rates-tip-desc').textContent = tip.desc || '';
            document.getElementById('rates-tip-logic').textContent = '📐 ' + (tip.logic || '');
            document.getElementById('rates-tip-alert').textContent = tip.alert || '';
            document.getElementById('rates-tip-history').textContent = tip.history ? '📊 ' + tip.history : '';
            const rect = this.getBoundingClientRect();
            popup.style.left = Math.min(rect.left, window.innerWidth - 300) + 'px';
            popup.style.top = (rect.bottom + 8) + 'px';
            popup.style.display = 'block';
        });
        card.addEventListener('mouseleave', function() {
            popup.style.display = 'none';
        });
    });
}

function renderRatesChart(chart) {
    if (!chart || chart.status !== 'success') return;
    const el = document.getElementById('rates-chart');
    if (!el) return;
    if (_ratesMainChart) _ratesMainChart.dispose();
    _ratesMainChart = echarts.init(el);
    const lines = chart.lines || {};

    const series = [
        { name:'10Y Yield', type:'line', data:chart.yields_10y, smooth:true,
          lineStyle:{color:'#c084fc',width:2},
          areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#c084fc33'},{offset:1,color:'#c084fc05'}]}},
          itemStyle:{color:'#c084fc'}, symbol:'none', yAxisIndex:0 },
    ];

    // 利差曲线 (第二Y轴)
    if (chart.spreads) {
        series.push({
            name:'10Y-2Y利差', type:'bar', data:chart.spreads,
            itemStyle:{ color: function(p) { return p.data < 0 ? '#ef444488' : '#10b98144'; } },
            barWidth: '60%', yAxisIndex:1
        });
    }

    // 参考线 (带文字标注)
    if (lines.high_zone) {
        series.push({ name:'超配债券区('+lines.high_zone+'%)', type:'line', data:chart.dates.map(()=>lines.high_zone),
            lineStyle:{color:'#10b981',type:'dashed',width:1}, symbol:'none', itemStyle:{color:'#10b981'}, yAxisIndex:0 });
    }
    if (lines.neutral) {
        series.push({ name:'中性区('+lines.neutral+'%)', type:'line', data:chart.dates.map(()=>lines.neutral),
            lineStyle:{color:'#94a3b8',type:'dotted',width:1}, symbol:'none', itemStyle:{color:'#94a3b8'}, yAxisIndex:0 });
    }
    if (lines.low_zone) {
        series.push({ name:'全股票区('+lines.low_zone+'%)', type:'line', data:chart.dates.map(()=>lines.low_zone),
            lineStyle:{color:'#ef4444',type:'dashed',width:1}, symbol:'none', itemStyle:{color:'#ef4444'}, yAxisIndex:0 });
    }

    const yAxes = [
        { type:'value', name:'Yield(%)', position:'left', axisLabel:{color:'#64748b',fontSize:9,formatter:'{value}%'}, splitLine:{lineStyle:{color:'#1e293b'}}, nameTextStyle:{color:'#64748b',fontSize:9} }
    ];
    if (chart.spreads) {
        yAxes.push({ type:'value', name:'Spread(%)', position:'right', axisLabel:{color:'#64748b',fontSize:9,formatter:'{value}%'}, splitLine:{show:false}, nameTextStyle:{color:'#64748b',fontSize:9} });
    }

    _ratesMainChart.setOption({
        backgroundColor: 'transparent',
        grid: { top: 32, right: chart.spreads ? 55 : 10, bottom: 28, left: 45 },
        legend: { top: 0, textStyle:{color:'#94a3b8',fontSize:9}, itemWidth:14, itemHeight:8 },
        tooltip: { trigger:'axis', backgroundColor:'rgba(15,23,42,0.95)', borderColor:'#c084fc44',
            textStyle:{color:'#e2e8f0',fontSize:10},
            formatter: function(p) { if (!p.length) return ''; let s='<b>'+p[0].axisValue+'</b><br/>'; p.forEach(i => { if (i.value !== undefined) s+='<span style="color:'+i.color+'">●</span> '+i.seriesName+': <b>'+i.value+'%</b><br/>'; }); return s; }
        },
        xAxis: { type:'category', data:chart.dates, axisLabel:{color:'#64748b',fontSize:8,formatter:v=>v.substring(2,7)}, axisLine:{lineStyle:{color:'#334155'}} },
        yAxis: yAxes,
        series: series,
    });
}

// ====================================================================
//  AIAE 宏观仓位管控模块 V2.0
//  琥珀金色系 · ECharts仪表盘 · 五档markArea色带 · 脉冲信号卡片
// ====================================================================

let _aiaeData = null;
let _aiaeLoading = false;

async function loadAIAEReport(forceRefresh = false) {
    if (_aiaeLoading) return;
    if (_aiaeData && !forceRefresh) {
        renderAIAEUI(_aiaeData);
        return;
    }

    _aiaeLoading = true;
    const statusEl = document.getElementById('aiae-load-status');
    const loadBtn = document.getElementById('aiae-load-btn');
    const refreshBtn = document.getElementById('aiae-refresh-btn');
    if (statusEl) statusEl.textContent = '⏳ 正在连接 Tushare 数据源...';
    if (loadBtn) { loadBtn.disabled = true; loadBtn.innerHTML = '⏳ 加载中...'; }
    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const endpoint = forceRefresh ? '/api/v1/aiae/refresh' : '/api/v1/aiae/report';
        const resp = await fetch(endpoint);
        const json = await resp.json();

        if (json.status === 'success' && json.data) {
            _aiaeData = json.data;
            try {
                renderAIAEUI(_aiaeData);
            } catch(renderErr) {
                console.warn('[AIAE] Partial render error (non-blocking):', renderErr);
            }
            if (statusEl) {
                const st = _aiaeData.status === 'fallback' ? '⚠️ 降级数据' : '✅ 实时数据';
                statusEl.textContent = st + ' · ' + new Date().toLocaleTimeString();
            }
            if (loadBtn) loadBtn.innerHTML = '✅ 数据已加载';
            setTimeout(() => { if (loadBtn) loadBtn.innerHTML = '⚡ 加载实时数据'; }, 2000);
        } else {
            if (statusEl) statusEl.textContent = `❌ ${json.message || '加载失败'}`;
            if (loadBtn) loadBtn.innerHTML = '❌ 重试';
            setTimeout(() => { if (loadBtn) loadBtn.innerHTML = '⚡ 加载实时数据'; }, 3000);
        }
    } catch (e) {
        console.error('[AIAE] Load error:', e);
        if (statusEl) statusEl.textContent = `❌ 网络异常: ${e.message}`;
        if (loadBtn) loadBtn.innerHTML = '❌ 重试';
        setTimeout(() => { if (loadBtn) loadBtn.innerHTML = '⚡ 加载实时数据'; }, 3000);
    } finally {
        _aiaeLoading = false;
        if (loadBtn) loadBtn.disabled = false;
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

function renderAIAEUI(data) {
    if (!data) return;
    const c = data.current;
    const p = data.position;
    const cv = data.cross_validation;
    const ri = c.regime_info;

    // ── Hero Stats ──
    const $v = document.getElementById('aiae-hero-value');
    const $r = document.getElementById('aiae-hero-regime');
    const $p = document.getElementById('aiae-hero-position');
    const $e = document.getElementById('aiae-hero-erp');
    if ($v) $v.textContent = c.aiae_v1 + '%';
    if ($r) { $r.textContent = `${ri.emoji} ${ri.cn}`; $r.style.color = ri.color; }
    if ($p) $p.textContent = p.matrix_position + '%';
    if ($e) { $e.textContent = cv.verdict; $e.style.color = cv.color; }

    // ── ZONE 1: ECharts Gauge ──
    try { renderAIAEGauge(c.aiae_v1, c.regime, ri); } catch(e) { console.warn('[AIAE] gauge skip:', e); }
    const $gl = document.getElementById('aiae-gauge-label');
    const $gr = document.getElementById('aiae-gauge-regime');
    const $sl = document.getElementById('aiae-slope-indicator');
    if ($gl) $gl.textContent = c.aiae_v1;
    if ($gr) { $gr.textContent = `${ri.emoji} ${ri.name}`; $gr.style.color = ri.color; }
    if ($sl) {
        const slope = c.slope;
        const arrow = slope.direction === 'rising' ? '↗' : (slope.direction === 'falling' ? '↘' : '→');
        $sl.textContent = `月环比斜率: ${arrow} ${slope.slope > 0 ? '+' : ''}${slope.slope}`;
        $sl.style.color = slope.direction === 'rising' ? '#f97316' : (slope.direction === 'falling' ? '#10b981' : '#94a3b8');
    }

    // ── Regime cards highlight ──
    document.querySelectorAll('.aiae-regime-card').forEach(card => {
        const r = parseInt(card.dataset.regime);
        card.classList.toggle('active', r === c.regime);
    });

    // ── Data source cards ──
    const $ds = document.getElementById('aiae-data-simple');
    const $dm = document.getElementById('aiae-data-margin');
    const $df = document.getElementById('aiae-data-fund');
    if ($ds) $ds.textContent = c.aiae_simple + '%';
    if ($dm) $dm.textContent = c.margin_heat + '%';
    if ($df) $df.textContent = c.fund_position + '%';

    // ── ZONE 2: Matrix highlight ──
    renderAIAEMatrix(p, cv);

    // ── Allocations ──
    renderAIAEAllocs(p.allocations, p.matrix_position);

    // ── Cross validation ──
    const $cv = document.getElementById('aiae-cross-validation');
    if ($cv) {
        $cv.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;">
                <span class="aiae-cross-stars">${cv.confidence_stars}</span>
                <span class="aiae-cross-verdict" style="color:${cv.color};">${cv.verdict}</span>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px;line-height:1.6;">
                AIAE Ⅳ${c.regime}级 × ERP ${p.erp_value}% (${cv.erp_level}) · 置信度 ${cv.confidence}/5
            </div>
        `;
    }

    // ── ZONE 3: History chart ──
    try { if (data.chart) renderAIAEHistoryChart(data.chart, c.aiae_v1); } catch(e) { console.warn('[AIAE] chart skip:', e); }

    // ── History summary current value ──
    const $hc = document.getElementById('aiae-hist-current');
    if ($hc) $hc.textContent = c.aiae_v1 + '%';

    // ── ZONE 4: Signals ──
    renderAIAESignals(data.signals);

    // ── Warning Indicators ──
    try { renderAIAEWarnings(c); } catch(e) { console.warn('[AIAE] warnings skip:', e); }

    // ── Action Dashboard ──
    try { renderAIAEActionDashboard(c.regime, ri, p.matrix_position); } catch(e) { console.warn('[AIAE] action skip:', e); }
}

// ── Warning Indicators V2.1 ──
function renderAIAEWarnings(c) {
    // Margin heat
    const mVal = c.margin_heat || 0;
    const $mV = document.getElementById('aiae-warn-margin-val');
    const $mB = document.getElementById('aiae-warn-margin-bar');
    const $mC = document.getElementById('aiae-warn-margin');
    if ($mV) { $mV.textContent = mVal + '%'; $mV.style.color = mVal > 3.5 ? '#ef4444' : mVal > 2.5 ? '#f59e0b' : '#10b981'; }
    if ($mB) { $mB.style.width = Math.min(mVal / 5 * 100, 100) + '%'; $mB.style.background = mVal > 3.5 ? '#ef4444' : mVal > 2.5 ? '#f59e0b' : '#10b981'; }
    if ($mC) { $mC.className = 'aiae-warning-card ' + (mVal > 3.5 ? 'warn-danger' : mVal > 2.5 ? 'warn-caution' : 'warn-ok'); }

    // Slope
    const sVal = c.slope?.slope || 0;
    const absSlope = Math.abs(sVal);
    const $sV = document.getElementById('aiae-warn-slope-val');
    const $sB = document.getElementById('aiae-warn-slope-bar');
    const $sC = document.getElementById('aiae-warn-slope');
    if ($sV) { $sV.textContent = (sVal > 0 ? '+' : '') + sVal; $sV.style.color = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981'; }
    if ($sB) { $sB.style.width = Math.min(absSlope / 3 * 100, 100) + '%'; $sB.style.background = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981'; }
    if ($sC) { $sC.className = 'aiae-warning-card ' + (absSlope > 1.5 ? 'warn-danger' : absSlope > 0.8 ? 'warn-caution' : 'warn-ok'); }

    // Fund position
    const fVal = c.fund_position || 0;
    const $fV = document.getElementById('aiae-warn-fund-val');
    const $fB = document.getElementById('aiae-warn-fund-bar');
    const $fC = document.getElementById('aiae-warn-fund');
    if ($fV) { $fV.textContent = fVal + '%'; $fV.style.color = fVal > 90 ? '#ef4444' : fVal > 85 ? '#f59e0b' : '#10b981'; }
    if ($fB) { $fB.style.width = Math.min(fVal / 100 * 100, 100) + '%'; $fB.style.background = fVal > 90 ? '#ef4444' : fVal > 85 ? '#f59e0b' : '#10b981'; }
    if ($fC) { $fC.className = 'aiae-warning-card ' + (fVal > 90 ? 'warn-danger' : fVal > 85 ? 'warn-caution' : 'warn-ok'); }
}

// ── Action Dashboard V2.1 (dynamic per regime) ──
function renderAIAEActionDashboard(regime, ri, matrixPos) {
    const actionData = {
        1: {
            buy: ['<b style="color:#10b981">AIAE<12% 满仓进攻模式</b>','分3批建仓，越跌越买','优先宽基ETF: 300/50/500/创业板','红利ETF同步配置底仓'],
            hold: ['每批完成后等待3-5天观察','不追高，只在下跌日建仓','总仓位控制在90-95%内'],
            sell: ['此档位禁止任何卖出操作','除非触发组合级-25%强制止损','耐心持有，等待市场修复']
        },
        2: {
            buy: ['<b style="color:#3b82f6">AIAE 12-16% 标准建仓区</b>','按节奏建仓，总目标仓位70-85%','宽基+红利均衡配置','ERP>4%时加大买入力度'],
            hold: ['已建仓位坚定持有','不因短期波动减仓','定期检查子策略配额是否到位'],
            sell: ['此档位不主动卖出','仅止损触发时被动减仓','子策略止损线: MR-8% DIV-5% MOM-7%']
        },
        3: {
            buy: ['<b style="color:#eab308">Ⅲ级不主动加仓</b>','仅在子策略出现强烈买入信号时小幅加仓','新增仓位限制在总仓5%以内'],
            hold: ['维持均衡仓位50-65%','有纪律持有，到目标价就卖','以宽基+红利为主，减少进攻型标的'],
            sell: ['到达止盈目标的标的及时卖出','密切监控AIAE是否向24%靠近','若接近24%开始做减仓准备']
        },
        4: {
            buy: ['<b style="color:#f97316">Ⅳ级禁止新开仓</b>','不追涨任何进攻型标的','仅保留现有红利型标的'],
            hold: ['总仓位压缩至25-40%','红利ETF可继续持有','进攻型标的逐步清退'],
            sell: ['<b style="color:#ef4444">每周减5%总仓位</b>','优先清退高波动标的','3-4周完成减仓至目标水位']
        },
        5: {
            buy: ['<b style="color:#ef4444">Ⅴ级·绝对禁止任何买入</b>','历史级泡沫信号','任何新仓位=与市场对赌'],
            hold: ['仅保留0-15%极低仓位','仅限红利防御型ETF','现金为王'],
            sell: ['<b style="color:#ef4444">3天内完成清仓</b>','无例外，不抄底','强制执行，无论盈亏']
        }
    };

    const d = actionData[regime] || actionData[3];
    const $buy = document.getElementById('aiae-action-buy-list');
    const $hold = document.getElementById('aiae-action-hold-list');
    const $sell = document.getElementById('aiae-action-sell-list');

    if ($buy) $buy.innerHTML = d.buy.map(t => `<li>${t}</li>`).join('');
    if ($hold) $hold.innerHTML = d.hold.map(t => `<li>${t}</li>`).join('');
    if ($sell) $sell.innerHTML = d.sell.map(t => `<li>${t}</li>`).join('');

    // Highlight active zone
    const cards = document.querySelectorAll('.aiae-action-card');
    cards.forEach(c => {
        c.style.opacity = '0.6';
        c.style.transform = '';
    });
    const activeMap = { 1: 0, 2: 0, 3: 1, 4: 2, 5: 2 };
    const activeIdx = activeMap[regime] ?? 1;
    if (cards[activeIdx]) {
        cards[activeIdx].style.opacity = '1';
        cards[activeIdx].style.transform = 'scale(1.03)';
    }
}

// ── ECharts Gauge V2.0 ──
function renderAIAEGauge(value, regime, ri) {
    const container = document.getElementById('aiae-gauge-container');
    if (!container || typeof echarts === 'undefined') return;
    if (window._aiaeGaugeChart) window._aiaeGaugeChart.dispose();
    window._aiaeGaugeChart = echarts.init(container);

    const v = Math.min(Math.max(value, 0), 50);

    window._aiaeGaugeChart.setOption({
        series: [{
            type: 'gauge',
            startAngle: 200,
            endAngle: -20,
            min: 0,
            max: 50,
            pointer: {
                show: true,
                length: '58%',
                width: 4,
                itemStyle: { color: ri.color, shadowColor: ri.color, shadowBlur: 8 },
                icon: 'triangle'
            },
            anchor: {
                show: true,
                size: 10,
                itemStyle: { color: '#0f172a', borderColor: ri.color, borderWidth: 3 }
            },
            axisLine: {
                lineStyle: {
                    width: 14,
                    color: [
                        [0.24, '#10b981'],   // Ⅰ: 0-12
                        [0.32, '#3b82f6'],   // Ⅱ: 12-16
                        [0.48, '#eab308'],   // Ⅲ: 16-24
                        [0.64, '#f97316'],   // Ⅳ: 24-32
                        [1, '#ef4444']       // Ⅴ: 32-50
                    ]
                }
            },
            axisTick: {
                length: 8,
                distance: -14,
                lineStyle: { color: 'auto', width: 1.5 }
            },
            splitLine: {
                length: 14,
                distance: -14,
                lineStyle: { color: 'auto', width: 2 }
            },
            splitNumber: 5,
            axisLabel: {
                distance: -36,
                color: '#64748b',
                fontSize: 9,
                formatter: function(val) {
                    var map = {0: '0', 10: '10', 12: 'Ⅰ', 16: 'Ⅱ', 20: '20', 24: 'Ⅲ', 30: '30', 32: 'Ⅳ', 40: '40', 50: '50'};
                    return map[val] || '';
                }
            },
            detail: { show: false },
            data: [{ value: v }],
            animationDuration: 1200,
            animationEasingUpdate: 'cubicOut'
        }]
    });
}

// ── History Chart V2.0 (五档 markArea 色带) ──
function renderAIAEHistoryChart(chart, currentValue) {
    const container = document.getElementById('aiae-history-chart');
    if (!container || typeof echarts === 'undefined') return;
    try {
        if (window._aiaeHistChart) window._aiaeHistChart.dispose();
        window._aiaeHistChart = echarts.init(container);

        // 五档区间色带
        const markAreaData = [
            [{ yAxis: 0, itemStyle: { color: 'rgba(16,185,129,0.06)' } }, { yAxis: 12 }],   // Ⅰ
            [{ yAxis: 12, itemStyle: { color: 'rgba(59,130,246,0.05)' } }, { yAxis: 16 }],   // Ⅱ
            [{ yAxis: 16, itemStyle: { color: 'rgba(234,179,8,0.05)' } }, { yAxis: 24 }],    // Ⅲ
            [{ yAxis: 24, itemStyle: { color: 'rgba(249,115,22,0.06)' } }, { yAxis: 32 }],   // Ⅳ
            [{ yAxis: 32, itemStyle: { color: 'rgba(239,68,68,0.06)' } }, { yAxis: 50 }],    // Ⅴ
        ];

        // 分界参考线
        const markLines = [12, 16, 24, 32].map(val => ({
            yAxis: val,
            lineStyle: { color: val <= 16 ? '#3b82f644' : (val <= 24 ? '#eab30844' : '#ef444444'), type: 'dashed', width: 1 },
            label: {
                formatter: val === 12 ? 'Ⅰ|Ⅱ' : (val === 16 ? 'Ⅱ|Ⅲ' : (val === 24 ? 'Ⅲ|Ⅳ' : 'Ⅳ|Ⅴ')),
                position: 'end', color: '#64748b', fontSize: 9
            }
        }));

        window._aiaeHistChart.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(245,158,11,0.3)',
                textStyle: { color: '#e2e8f0', fontSize: 11 },
                formatter: function(params) {
                    if (!params.length) return '';
                    const p = params[0];
                    const idx = chart.dates.indexOf(p.axisValue);
                    const label = idx >= 0 && chart.labels[idx] ? chart.labels[idx] : '';
                    // Determine tier
                    const val = p.value;
                    let tierLabel = '';
                    if (val < 12) tierLabel = '<span style="color:#10b981">Ⅰ级 极度恐慌</span>';
                    else if (val < 16) tierLabel = '<span style="color:#3b82f6">Ⅱ级 低配置区</span>';
                    else if (val < 24) tierLabel = '<span style="color:#eab308">Ⅲ级 中性均衡</span>';
                    else if (val < 32) tierLabel = '<span style="color:#f97316">Ⅳ级 偏热区域</span>';
                    else tierLabel = '<span style="color:#ef4444">Ⅴ级 极度过热</span>';

                    return '<b>' + p.axisValue + '</b><br/>' +
                        '<span style="color:#f59e0b">●</span> AIAE: <b>' + p.value + '%</b><br/>' +
                        tierLabel +
                        (label ? '<br/><span style="color:#94a3b8">' + label + '</span>' : '');
                }
            },
            grid: { left: 55, right: 30, top: 32, bottom: 32 },
            xAxis: {
                type: 'category', data: chart.dates, boundaryGap: false,
                axisLabel: { color: '#64748b', fontSize: 9, formatter: function(v) { return v.substring(0, 7); } },
                axisLine: { lineStyle: { color: '#334155' } }
            },
            yAxis: {
                type: 'value', min: 0, max: 50,
                axisLabel: { color: '#64748b', fontSize: 9, formatter: function(v) { return v + '%'; } },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
            },
            series: [{
                type: 'line', data: chart.values, smooth: true,
                symbol: 'circle', symbolSize: 10,
                lineStyle: { color: '#f59e0b', width: 3, shadowColor: 'rgba(245,158,11,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#f59e0b', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(245,158,11,0.25)' },
                            { offset: 1, color: 'rgba(245,158,11,0)' }
                        ]
                    }
                },
                label: {
                    show: true, fontSize: 8, color: '#f59e0b',
                    formatter: function(p) { return p.value + '%'; },
                    position: 'top'
                },
                markArea: { silent: true, data: markAreaData },
                markLine: { silent: true, symbol: 'none', data: markLines }
            }]
        });
    } catch(err) {
        console.warn('[AIAE] History chart error:', err);
    }
}


function renderAIAEMatrix(pos, cv) {
    const table = document.getElementById('aiae-matrix-table');
    if (!table) return;

    // Heatmap color function: 高仓位=绿, 低仓位=红
    function posColor(v) {
        if (v >= 80) return 'rgba(16,185,129,0.2)';
        if (v >= 60) return 'rgba(52,211,153,0.12)';
        if (v >= 40) return 'rgba(234,179,8,0.1)';
        if (v >= 20) return 'rgba(249,115,22,0.12)';
        return 'rgba(239,68,68,0.15)';
    }

    // 清除旧高亮 + 添加热力图
    const posValues = [[95,85,70,45,20],[90,80,65,40,15],[85,70,55,30,10],[75,60,40,20,5]];
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach((row, ri) => {
        const cells = row.querySelectorAll('td');
        cells.forEach((td, ci) => {
            td.classList.remove('aiae-matrix-active');
            if (ci > 0 && posValues[ri]) { // skip row label
                td.style.background = posColor(posValues[ri][ci-1]);
            }
        });
    });

    // 确定当前交叉位置并高亮
    const erpMap = { 'erp_gt6': 0, 'erp_4_6': 1, 'erp_2_4': 2, 'erp_lt2': 3 };
    const rowIdx = erpMap[pos.erp_level] ?? 2;
    const colIdx = Math.min(pos.regime - 1, 4);
    if (rows[rowIdx]) {
        const cells = rows[rowIdx].querySelectorAll('td');
        if (cells[colIdx + 1]) cells[colIdx + 1].classList.add('aiae-matrix-active');
    }

    const regimeNames = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
    const $verdict = document.getElementById('aiae-matrix-verdict');
    if ($verdict) {
        $verdict.innerHTML = '当前: <b style="color:#f59e0b">' + regimeNames[pos.regime] + '级</b>' +
            ' × <b style="color:#60a5fa">ERP ' + pos.erp_value + '%</b>' +
            ' → 建议总仓位 <b style="color:#10b981;font-size:1.1rem;">' + pos.matrix_position + '%</b>';
    }
}

function renderAIAEAllocs(allocs, totalPos) {
    if (!allocs) return;
    const strategies = ['mr', 'div', 'mom', 'erp'];
    strategies.forEach(key => {
        const a = allocs[key];
        if (!a) return;
        const $pct = document.getElementById(`aiae-alloc-${key}-pct`);
        const $pos = document.getElementById(`aiae-alloc-${key}-pos`);
        const $bar = document.getElementById(`aiae-alloc-${key}-bar`);
        if ($pct) $pct.textContent = a.pct + '%';
        if ($pos) $pos.textContent = a.position + '% 仓位';
        if ($bar) $bar.style.width = Math.min(a.pct, 100) + '%';
    });
}

function renderAIAESignals(signals) {
    const container = document.getElementById('aiae-signal-cards');
    if (!container || !signals || !signals.length) return;

    function hexToRgba(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r},${g},${b},${alpha})`;
    }

    container.innerHTML = signals.map((s, i) => {
        const c = s.color || '#f59e0b';
        const isMain = s.type === 'main' || i === 0;
        const icon = s.type === 'main' ? '🌡️' : (s.type === 'slope' ? '📐' : (s.type === 'margin' ? '💳' : '📡'));
        const mainClass = isMain ? ' aiae-signal-main' : '';
        const time = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
        return `<div class="aiae-signal-card${mainClass}" style="--signal-color:${c};">
            <div class="aiae-signal-icon">${icon}</div>
            <div>
                <div class="aiae-signal-text" style="color:${c}">${s.text}</div>
                <span class="aiae-signal-time">${time}</span>
            </div>
        </div>`;
    }).join('');
}

// 页面首次加载时，如果AIAE是默认active tab则自动加载
document.addEventListener('DOMContentLoaded', function() {
    const aiaeTab = document.querySelector('.st-tab[data-report="st-aiae-position"]');
    if (aiaeTab && aiaeTab.classList.contains('active')) {
        setTimeout(() => loadAIAEReport(), 500);
    }
});

// ── ECharts 全局 Resize Handler (防抖 200ms, 合并所有图表实例) ──
(function() {
    let _resizeTimer = null;
    window.addEventListener('resize', function() {
        clearTimeout(_resizeTimer);
        _resizeTimer = setTimeout(function() {
            if (typeof _ratesGaugeChart !== 'undefined' && _ratesGaugeChart) {
                try { _ratesGaugeChart.resize(); } catch(e) {}
            }
            if (typeof _ratesMainChart !== 'undefined' && _ratesMainChart) {
                try { _ratesMainChart.resize(); } catch(e) {}
            }
            if (window._aiaeGaugeChart) {
                try { window._aiaeGaugeChart.resize(); } catch(e) {}
            }
            if (window._aiaeHistChart) {
                try { window._aiaeHistChart.resize(); } catch(e) {}
            }
            if (window._gaiaeUsGauge) {
                try { window._gaiaeUsGauge.resize(); } catch(e) {}
            }
            if (window._gaiaeJpGauge) {
                try { window._gaiaeJpGauge.resize(); } catch(e) {}
            }
            if (window._gaiaeHkGauge) {
                try { window._gaiaeHkGauge.resize(); } catch(e) {}
            }
            if (window._gaiaeHistChart) {
                try { window._gaiaeHistChart.resize(); } catch(e) {}
            }
        }, 200);
    });
})();

// ====================================================================
//  海外 AIAE 宏观仓位管控模块 V1.1
//  US(蓝) + JP(红) 双面板 | 五档竖卡 | 警示指标 | 三地对比 | 合并操作区
// ====================================================================

let _globalAIAEData = null;
let _globalAIAELoading = false;

async function loadGlobalAIAE(forceRefresh = false) {
    if (_globalAIAELoading) return;
    if (_globalAIAEData && !forceRefresh) {
        renderGlobalAIAE(_globalAIAEData);
        return;
    }

    _globalAIAELoading = true;
    const btn = document.getElementById('gaiae-refresh-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 加载中...'; }

    try {
        const endpoint = forceRefresh ? '/api/v1/aiae_global/refresh' : '/api/v1/aiae_global/report';
        const resp = await fetch(endpoint);
        const json = await resp.json();
        if (json.status === 'success') {
            _globalAIAEData = json;
            renderGlobalAIAE(json);
            const t = document.getElementById('gaiae-update-time');
            if (t) t.textContent = new Date().toLocaleTimeString('zh-CN');
        } else {
            console.error('[GlobalAIAE] Error:', json.message);
        }
    } catch (e) {
        console.error('[GlobalAIAE] Fetch failed:', e);
    }
    if (btn) { btn.disabled = false; btn.innerHTML = '🔄 刷新'; }
    _globalAIAELoading = false;
}

function renderGlobalAIAE(json) {
    const us = json.us || {};
    const jp = json.jp || {};
    const hk = json.hk || {};
    const gc = json.global_comparison || {};

    // -- Region panels --
    renderGAIAERegionPanel('us', us, '#3b82f6');
    renderGAIAERegionPanel('jp', jp, '#dc2626');
    renderGAIAERegionPanel('hk', hk, '#a855f7');

    // Hero values
    const usV1 = (us.current||{}).aiae_v1 || 0;
    const jpV1 = (jp.current||{}).aiae_v1 || 0;
    const hkV1 = (hk.current||{}).aiae_v1 || 0;
    const usRI = (us.current||{}).regime_info || {};
    const jpRI = (jp.current||{}).regime_info || {};
    const hkRI = (hk.current||{}).regime_info || {};

    const $usV = document.getElementById('gaiae-us-value');
    const $jpV = document.getElementById('gaiae-jp-value');
    const $hkV = document.getElementById('gaiae-hk-value');
    const $usR = document.getElementById('gaiae-us-regime');
    const $jpR = document.getElementById('gaiae-jp-regime');
    const $hkR = document.getElementById('gaiae-hk-regime');
    if ($usV) $usV.textContent = usV1.toFixed(1) + '%';
    if ($jpV) $jpV.textContent = jpV1.toFixed(1) + '%';
    if ($hkV) $hkV.textContent = hkV1.toFixed(1) + '%';
    if ($usR) { $usR.textContent = (usRI.emoji||'') + ' ' + (usRI.cn||'--'); $usR.style.color = usRI.color||'#94a3b8'; }
    if ($jpR) { $jpR.textContent = (jpRI.emoji||'') + ' ' + (jpRI.cn||'--'); $jpR.style.color = jpRI.color||'#94a3b8'; }
    if ($hkR) { $hkR.textContent = (hkRI.emoji||'') + ' ' + (hkRI.cn||'--'); $hkR.style.color = hkRI.color||'#94a3b8'; }

    // Coldest market hero card
    const regionMap = { cn: '🇨🇳 A股', us: '🇺🇸 美股', jp: '🇯🇵 日股', hk: '🇭🇰 港股' };
    const $cold = document.getElementById('gaiae-coldest');
    const $coldL = document.getElementById('gaiae-coldest-label');
    const $coldCard = document.getElementById('gaiae-coldest-card');
    if ($cold) $cold.textContent = regionMap[gc.coldest] || '--';
    if ($coldL) $coldL.textContent = '超配优先 · 远离过热';
    if ($coldCard) $coldCard.classList.add('coldest-glow');

    // Matrices
    renderGAIAEMatrix('us', us);
    renderGAIAEMatrix('jp', jp);
    renderGAIAEMatrix('hk', hk);

    // 4-way comparison
    renderGAIAE3Way(gc);

    // Warning indicators
    renderGAIAEWarnings('us', us);
    renderGAIAEWarnings('jp', jp);
    renderGAIAEWarnings('hk', hk);

    // Consolidated actions
    renderGAIAEActionZone((us.current||{}).regime || 3, (jp.current||{}).regime || 3, (hk.current||{}).regime || 3);

    // Charts
    try { renderGAIAEHistoryChart(us.chart, jp.chart, hk.chart); } catch(e) { console.warn('[GAIAE] chart skip:', e); }
}

function renderGAIAERegionPanel(region, data, color) {
    if (!data || !data.current) return;
    const c = data.current;
    const ri = c.regime_info || {};

    // Gauge
    const max = region === 'us' ? 50 : (region === 'jp' ? 40 : 45);
    const bands = region === 'us'
        ? [[0.30,'#10b981'],[0.40,'#3b82f6'],[0.56,'#eab308'],[0.72,'#f97316'],[1,'#ef4444']]
        : region === 'jp'
        ? [[0.25,'#10b981'],[0.35,'#3b82f6'],[0.50,'#eab308'],[0.70,'#f97316'],[1,'#ef4444']]
        : [[0.18,'#10b981'],[0.31,'#3b82f6'],[0.49,'#eab308'],[0.67,'#f97316'],[1,'#ef4444']];

    try {
        const el = document.getElementById('gaiae-' + region + '-gauge');
        if (el && typeof echarts !== 'undefined') {
            const key = '_gaiae' + region.charAt(0).toUpperCase() + region.slice(1) + 'Gauge';
            if (window[key]) window[key].dispose();
            window[key] = echarts.init(el);
            window[key].setOption({
                series: [{
                    type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: max,
                    pointer: { show: true, length: '55%', width: 4, itemStyle: { color: ri.color || color, shadowColor: (ri.color||color), shadowBlur: 6 }, icon: 'triangle' },
                    anchor: { show: true, size: 8, itemStyle: { color: '#0f172a', borderColor: ri.color||color, borderWidth: 2 } },
                    axisLine: { lineStyle: { width: 12, color: bands } },
                    axisTick: { length: 6, distance: -12, lineStyle: { color: 'auto', width: 1 } },
                    splitLine: { length: 10, distance: -12, lineStyle: { color: 'auto', width: 1.5 } },
                    splitNumber: 5,
                    axisLabel: { distance: -28, color: '#64748b', fontSize: 8 },
                    detail: { show: false },
                    data: [{ value: Math.min(Math.max(c.aiae_v1, 0), max) }],
                    animationDuration: 1200
                }]
            });
        }
    } catch(e) { console.warn('[GAIAE] gauge error:', e); }

    // Gauge labels
    const $gv = document.getElementById('gaiae-' + region + '-gauge-val');
    const $gr = document.getElementById('gaiae-' + region + '-gauge-regime');
    if ($gv) $gv.textContent = c.aiae_v1.toFixed(1) + '%';
    if ($gr) { $gr.textContent = (ri.emoji||'') + ' ' + (ri.cn||'--') + ' · 建议仓位 ' + (data.position||{}).matrix_position + '%'; $gr.style.color = ri.color||'#94a3b8'; }

    // ⑤ Regime cards highlight
    const cardsEl = document.getElementById('gaiae-' + region + '-regime-cards');
    if (cardsEl) {
        cardsEl.querySelectorAll('.gaiae-rc').forEach(card => {
            card.classList.toggle('active', parseInt(card.dataset.regime) === c.regime);
        });
    }

    // Factor cards
    const $core = document.getElementById('gaiae-' + region + '-core');
    if ($core) $core.textContent = (c.aiae_core||0).toFixed(1) + '%';

    if (region === 'us') {
        const $margin = document.getElementById('gaiae-us-margin');
        const $aaii = document.getElementById('gaiae-us-aaii');
        if ($margin) $margin.textContent = (c.margin_heat||0).toFixed(2) + '%';
        if ($aaii) {
            const spread = (c.aaii_sentiment||{}).spread || 0;
            $aaii.textContent = (spread > 0 ? '+' : '') + spread.toFixed(0) + '%';
            $aaii.style.color = spread > 15 ? '#ef4444' : spread < -10 ? '#10b981' : '#e2e8f0';
        }
    } else if (region === 'jp') {
        const $margin = document.getElementById('gaiae-jp-margin');
        const $foreign = document.getElementById('gaiae-jp-foreign');
        if ($margin) $margin.textContent = (c.margin_heat||0).toFixed(2) + '%';
        if ($foreign) {
            const net = (c.foreign_flow||{}).net_buy_billion_jpy || 0;
            $foreign.textContent = (net > 0 ? '+' : '') + (net/100).toFixed(0) + '億円';
            $foreign.style.color = net > 2000 ? '#3b82f6' : net < -2000 ? '#ef4444' : '#e2e8f0';
        }
    } else if (region === 'hk') {
        const $sb = document.getElementById('gaiae-hk-southbound');
        const $ah = document.getElementById('gaiae-hk-ahpremium');
        if ($sb) {
            const sbHeat = c.southbound_heat || 0;
            // sbHeat from engine is already a percentage (e.g. 1.12 = 1.12%)
            $sb.textContent = sbHeat.toFixed(2) + '%';
            $sb.style.color = sbHeat > 1.5 ? '#ef4444' : sbHeat < 0.5 ? '#10b981' : '#e2e8f0';
        }
        if ($ah) {
            const ahVal = typeof c.ah_premium === 'object'
                ? (c.ah_premium.index_value || 135)
                : (typeof c.ah_premium === 'number' ? c.ah_premium : 135);
            $ah.textContent = ahVal.toFixed(0);
            $ah.style.color = ahVal > 145 ? '#10b981' : ahVal < 115 ? '#ef4444' : '#e2e8f0';
        }
    }

    // Signals
    const sigEl = document.getElementById('gaiae-' + region + '-signals');
    if (sigEl && data.signals) {
        sigEl.innerHTML = data.signals.map(s => {
            return '<div class="gaiae-signal-item" style="border-color:' + (s.color||'#f59e0b') + '"><span>' + s.text + '</span></div>';
        }).join('');
    }
}

// ② Warning indicators rendering
function renderGAIAEWarnings(region, data) {
    if (!data || !data.current) return;
    const c = data.current;
    const slope = (data.position||{}).slope || 0;

    if (region === 'us') {
        _setWarnIndicator('gaiae-us-warn-margin', 'gaiae-us-warn-margin-val', 'gaiae-us-warn-margin-bar',
            c.margin_heat || 0, '%', 1.5, 1.0);
        _setWarnIndicator('gaiae-us-warn-slope', 'gaiae-us-warn-slope-val', 'gaiae-us-warn-slope-bar',
            Math.abs(slope), '', 3.0, 1.5, slope);
        const spread = (c.aaii_sentiment||{}).spread || 0;
        _setWarnIndicator('gaiae-us-warn-aaii', 'gaiae-us-warn-aaii-val', 'gaiae-us-warn-aaii-bar',
            spread, '%', 20, 10);
    } else if (region === 'jp') {
        _setWarnIndicator('gaiae-jp-warn-margin', 'gaiae-jp-warn-margin-val', 'gaiae-jp-warn-margin-bar',
            c.margin_heat || 0, '%', 0.6, 0.4);
        _setWarnIndicator('gaiae-jp-warn-slope', 'gaiae-jp-warn-slope-val', 'gaiae-jp-warn-slope-bar',
            Math.abs(slope), '', 2.0, 1.0, slope);
        const foreign = (c.foreign_flow||{}).net_buy_billion_jpy || 0;
        _setWarnIndicator('gaiae-jp-warn-foreign', 'gaiae-jp-warn-foreign-val', 'gaiae-jp-warn-foreign-bar',
            foreign / 100, '億', 30, 15);
    } else if (region === 'hk') {
        // sbHeat is already a percentage from engine (e.g. 1.12 = 1.12%)
        const sbHeat = c.southbound_heat || 0;
        _setWarnIndicator('gaiae-hk-warn-sb', 'gaiae-hk-warn-sb-val', 'gaiae-hk-warn-sb-bar',
            sbHeat, '%', 2.0, 1.0);
        _setWarnIndicator('gaiae-hk-warn-slope', 'gaiae-hk-warn-slope-val', 'gaiae-hk-warn-slope-bar',
            Math.abs(slope), '', 2.5, 1.5, slope);
        const ahPremium = typeof c.ah_premium === 'object'
            ? (c.ah_premium.index_value || 135)
            : (typeof c.ah_premium === 'number' ? c.ah_premium : 135);
        _setWarnIndicator('gaiae-hk-warn-ah', 'gaiae-hk-warn-ah-val', 'gaiae-hk-warn-ah-bar',
            ahPremium, '', 145, 130);
    }
}

function _setWarnIndicator(cardId, valId, barId, value, unit, dangerThreshold, cautionThreshold, displayVal) {
    const card = document.getElementById(cardId);
    const $val = document.getElementById(valId);
    const $bar = document.getElementById(barId);
    if (!card) return;

    const dv = displayVal !== undefined ? displayVal : value;
    const absVal = Math.abs(value);
    const isDanger = absVal >= dangerThreshold;
    const isCaution = absVal >= cautionThreshold && !isDanger;

    card.className = 'gaiae-warn-card ' + (isDanger ? 'warn-danger' : isCaution ? 'warn-caution' : 'warn-ok');
    if ($val) {
        $val.textContent = (typeof dv === 'number' ? (dv > 0 ? '+' : '') + dv.toFixed(2) : dv) + unit;
        $val.style.color = isDanger ? '#ef4444' : isCaution ? '#f59e0b' : '#10b981';
    }
    if ($bar) {
        const pct = Math.min((absVal / dangerThreshold) * 100, 100);
        $bar.style.width = pct + '%';
        $bar.style.background = isDanger ? '#ef4444' : isCaution ? '#f59e0b' : '#10b981';
    }
}

function renderGAIAEMatrix(region, data) {
    if (!data || !data.position) return;
    const pos = data.position;
    const cv = data.cross_validation || {};

    // Cross-validation verdict
    const $cv = document.getElementById('gaiae-' + region + '-cv-verdict');
    if ($cv) {
        const regimeRN = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
        $cv.innerHTML = '当前: <b style="color:#f59e0b">' + (regimeRN[pos.regime]||pos.regime) + '级</b>' +
            ' × <b style="color:#60a5fa">ERP ' + (pos.erp_value||0).toFixed(1) + '%</b>' +
            ' → 建议仓位 <b style="color:' + (cv.color||'#10b981') + ';font-size:0.85rem">' + pos.matrix_position + '%</b>' +
            ' · <span style="color:' + (cv.color||'#94a3b8') + '">' + (cv.confidence_stars||'') + ' ' + (cv.verdict||'') + '</span>';
    }

    // Highlight active cell
    const table = document.getElementById('gaiae-' + region + '-matrix');
    if (!table) return;

    const erpMap_us = { 'erp_gt5': 0, 'erp_3_5': 1, 'erp_1_3': 2, 'erp_lt1': 3 };
    const erpMap_jp = { 'erp_gt4': 0, 'erp_2_4': 1, 'erp_0_2': 2, 'erp_lt0': 3 };
    const erpMap_hk = { 'erp_gt5': 0, 'erp_3_5': 1, 'erp_1_3': 2, 'erp_lt1': 3 };
    const erpMap = region === 'us' ? erpMap_us : (region === 'jp' ? erpMap_jp : erpMap_hk);
    const rowIdx = erpMap[pos.erp_level] ?? 2;
    const colIdx = Math.min((pos.regime||3) - 1, 4);

    // Color all cells
    const posValues = [[95,85,70,45,20],[90,80,65,40,15],[85,70,55,30,10],[75,60,40,20,5]];
    function posColor(v) {
        if (v >= 80) return 'rgba(16,185,129,0.15)';
        if (v >= 60) return 'rgba(52,211,153,0.08)';
        if (v >= 40) return 'rgba(234,179,8,0.08)';
        if (v >= 20) return 'rgba(249,115,22,0.08)';
        return 'rgba(239,68,68,0.1)';
    }
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach((row, ri) => {
        const cells = row.querySelectorAll('td');
        cells.forEach((td, ci) => {
            td.classList.remove('gaiae-cell-active');
            if (ci > 0 && posValues[ri]) { td.style.background = posColor(posValues[ri][ci-1]); }
        });
    });
    if (rows[rowIdx]) {
        const cells = rows[rowIdx].querySelectorAll('td');
        if (cells[colIdx + 1]) cells[colIdx + 1].classList.add('gaiae-cell-active');
    }
}

function renderGAIAE3Way(gc) {
    if (!gc) return;
    const regimeNames = {1: 'Ⅰ极度恐慌', 2: 'Ⅱ低配置区', 3: 'Ⅲ中性均衡', 4: 'Ⅳ偏热区域', 5: 'Ⅴ极度过热'};
    const regimeColors = {1: '#10b981', 2: '#3b82f6', 3: '#eab308', 4: '#f97316', 5: '#ef4444'};

    const $cn = document.getElementById('gaiae-3way-cn');
    const $us = document.getElementById('gaiae-3way-us');
    const $jp = document.getElementById('gaiae-3way-jp');
    const $hk = document.getElementById('gaiae-3way-hk');
    const $cnR = document.getElementById('gaiae-3way-cn-regime');
    const $usR = document.getElementById('gaiae-3way-us-regime');
    const $jpR = document.getElementById('gaiae-3way-jp-regime');
    const $hkR = document.getElementById('gaiae-3way-hk-regime');

    if ($cn) $cn.textContent = (gc.cn_aiae||0).toFixed(1) + '%';
    if ($us) $us.textContent = (gc.us_aiae||0).toFixed(1) + '%';
    if ($jp) $jp.textContent = (gc.jp_aiae||0).toFixed(1) + '%';
    if ($hk) $hk.textContent = (gc.hk_aiae||0).toFixed(1) + '%';
    if ($cnR) { $cnR.textContent = 'A股 ' + (regimeNames[gc.cn_regime]||'Ⅲ中性'); $cnR.style.color = regimeColors[gc.cn_regime]||'#94a3b8'; }
    if ($usR) { $usR.textContent = '美股 ' + (regimeNames[gc.us_regime]||'Ⅲ中性'); $usR.style.color = regimeColors[gc.us_regime]||'#94a3b8'; }
    if ($jpR) { $jpR.textContent = '日股 ' + (regimeNames[gc.jp_regime]||'Ⅲ中性'); $jpR.style.color = regimeColors[gc.jp_regime]||'#94a3b8'; }
    if ($hkR) { $hkR.textContent = '港股 ' + (regimeNames[gc.hk_regime]||'Ⅲ中性'); $hkR.style.color = regimeColors[gc.hk_regime]||'#94a3b8'; }

    // Crown animation on coldest market
    const coldest = gc.coldest || '';
    ['cn','us','jp','hk'].forEach(r => {
        const card = document.getElementById('gaiae-3way-card-' + r);
        if (card) {
            card.classList.toggle('is-coldest', r === coldest);
            // Add crown to flag
            const flagEl = card.querySelector('.gaiae-3way-flag');
            if (flagEl && r === coldest && !flagEl.querySelector('.gaiae-3way-crown')) {
                flagEl.innerHTML += ' <span class="gaiae-3way-crown">👑</span>';
            }
        }
    });

    const $rec = document.getElementById('gaiae-recommendation');
    if ($rec) $rec.textContent = '🌍 ' + (gc.recommendation || '加载中...');
}

// ③ Consolidated action zone rendering
function renderGAIAEActionZone(usRegime, jpRegime, hkRegime) {
    // Determine which zone is active
    // Buy: regime 1-2, Hold: regime 3, Sell: regime 4-5
    // Use the "hotter" regime to be conservative
    const maxRegime = Math.max(usRegime, jpRegime, hkRegime || 3);

    const $buy = document.getElementById('gaiae-az-buy');
    const $hold = document.getElementById('gaiae-az-hold');
    const $sell = document.getElementById('gaiae-az-sell');

    if ($buy) {
        $buy.classList.toggle('az-active', maxRegime <= 2);
        $buy.classList.toggle('az-dimmed', maxRegime > 2);
    }
    if ($hold) {
        $hold.classList.toggle('az-active', maxRegime === 3);
        $hold.classList.toggle('az-dimmed', maxRegime !== 3);
    }
    if ($sell) {
        $sell.classList.toggle('az-active', maxRegime >= 4);
        $sell.classList.toggle('az-dimmed', maxRegime < 4);
    }

    // Update action content based on actual regimes
    const _rn = {1:'Ⅰ', 2:'Ⅱ', 3:'Ⅲ', 4:'Ⅳ', 5:'Ⅴ'};
    const usLabel = '🇺🇸 美股 (' + (_rn[usRegime]||usRegime) + '级)';
    const jpLabel = '🇯🇵 日股 (' + (_rn[jpRegime]||jpRegime) + '级)';
    const hkLabel = '🇭🇰 港股 (' + (_rn[hkRegime]||hkRegime) + '级)';
    const buyData = {
        1: { us: ['<b>极低 → 满配进攻</b>', '分3批建仓 SPY/QQQ', '总仓位冲至90-95%'], jp: ['<b>極度悲観 → 全力買い</b>', '3批建仓 1306/1321', '総ポジション90-95%'], hk: ['<b>极度恐慌 → 满配</b>', '分3批建仓 159920/513130', '仓位冲至90-95%'] },
        2: { us: ['<b>标准建仓区</b>', '目标仓位70-85%', 'ERP为正时加大买入'], jp: ['<b>標準建倉区</b>', '目標70-85%', '積極的にETF配分'], hk: ['<b>标准建仓区</b>', '目标70-85%', '南向资金流入验证'] },
        3: { us: ['Ⅲ级不主动加仓', '新增限制5%以内', '等待回调机会'], jp: ['Ⅲ級 加倉なし', '新規5%以内', '押し目待ち'], hk: ['Ⅲ级不加仓', '新增限制5%以内', '等待南向/AH信号'] },
        4: { us: ['<b>Ⅳ级禁止新开仓</b>', '不追涨进攻型标的', '仅保留红利型'], jp: ['<b>Ⅳ級 新規禁止</b>', '攻撃型銘柄撤退', '高配当のみ保有'], hk: ['<b>Ⅳ级禁止新开</b>', '科技ETF逐步撤退', '仅保留红利低波'] },
        5: { us: ['<b>Ⅴ级 绝对禁止买入</b>', '历史级泡沫信号', '任何新仓=与市场对赌'], jp: ['<b>Ⅴ級 絶対禁止</b>', 'バブル警報発令', '新規ポジション厳禁'], hk: ['<b>Ⅴ级 绝对禁止</b>', '2018年1月级泡沫', '任何新仓=接盘'] }
    };
    const holdData = {
        1: { us: ['每批完成后等3-5天', '只在下跌日建仓', '90-95%上限'], jp: ['各批3-5日間隔', '下落日のみ建倉', '90-95%上限'], hk: ['每批等3-5天', '只在下跌日建', '90-95%上限'] },
        2: { us: ['已建仓位坚定持有', '不因短期波动减仓', '观察AIAE方向'], jp: ['既存ポジション堅持', '短期変動で減らさない', 'AIAE方向を観察'], hk: ['仓位坚定持有', '不因波动减仓', '观察南向方向'] },
        3: { us: ['维持50-65%均衡仓位', '到目标价就卖', '宽基+红利为主'], jp: ['50-65%バランス維持', '目標価で売却', 'ETF+高配当中心'], hk: ['维持50-65%均衡', '恒生ETF+红利低波', '关注AH溢价'] },
        4: { us: ['总仓位压缩至25-40%', '进攻型逐步清退', '红利ETF可继续'], jp: ['25-40%へ圧縮', '攻撃型段階的撤退', '高配当ETF継続可'], hk: ['压缩至25-40%', '科技ETF逐步清退', '红利低波可继续'] },
        5: { us: ['仅保留0-15%极低仓', '仅限红利防御型', '现金为王'], jp: ['0-15%極低ポジション', '防御型ETFのみ', 'キャッシュ・イズ・キング'], hk: ['仅保留0-15%', '仅限恒生红利低波', '现金/债券为王'] }
    };
    const sellData = {
        1: { us: ['此档位禁止卖出', '除非触发组合-25%止损', '耐心持有'], jp: ['売却禁止', '組合-25%止損のみ', '忍耐保有'], hk: ['禁止卖出', '除非止损-25%', '耐心持有'] },
        2: { us: ['不主动卖出', '仅止损触发时被动减', '子策略止损: -8%'], jp: ['自発的売却なし', '止損のみ反応', '個別止損: -7%'], hk: ['不主动卖出', '仅止损时被动减', '个股止损: -8%'] },
        3: { us: ['到达止盈目标及时卖', '监控AIAE走向', '接近上档做准备'], jp: ['利確目標で売却', 'AIAE動向監視', '上昇接近で準備'], hk: ['止盈目标及时卖', '监控南向+AIAE', '接近Ⅳ做准备'] },
        4: { us: ['<b>每周减5%总仓位</b>', '优先清退高波动', '3-4周完成减仓'], jp: ['<b>毎週5%ずつ減倉</b>', '高ボラ銘柄から撤退', '3-4週間で完了'], hk: ['<b>每周减5%仓位</b>', '优先清退科技ETF', '3-4周完成'] },
        5: { us: ['<b>3天内完成清仓</b>', '无例外，不抄底', '强制执行，无论盈亏'], jp: ['<b>3日以内に完全撤退</b>', '例外なし・底打ち買い禁止', '損益問わず強制執行'], hk: ['<b>3天内完成清仓</b>', '无例外，不抄底', '强制执行'] }
    };

    const $buyList = document.getElementById('gaiae-az-buy-list');
    const $holdList = document.getElementById('gaiae-az-hold-list');
    const $sellList = document.getElementById('gaiae-az-sell-list');

    function makeList(data, usR, jpR, hkR) {
        const ud = data[usR] || data[3];
        const jd = data[jpR] || data[3];
        const hd = data[hkR] || data[3];
        return '<li class="az-region-label" style="color:#3b82f6">' + usLabel + '</li>' +
            ud.us.map(t => '<li>' + t + '</li>').join('') +
            '<li class="az-region-label" style="color:#dc2626">' + jpLabel + '</li>' +
            jd.jp.map(t => '<li>' + t + '</li>').join('') +
            '<li class="az-region-label" style="color:#a855f7">' + hkLabel + '</li>' +
            hd.hk.map(t => '<li>' + t + '</li>').join('');
    }

    if ($buyList) $buyList.innerHTML = makeList(buyData, usRegime, jpRegime, hkRegime);
    if ($holdList) $holdList.innerHTML = makeList(holdData, usRegime, jpRegime, hkRegime);
    if ($sellList) $sellList.innerHTML = makeList(sellData, usRegime, jpRegime, hkRegime);
}

function renderGAIAEHistoryChart(usChart, jpChart, hkChart) {
    const el = document.getElementById('gaiae-history-chart');
    if (!el || typeof echarts === 'undefined') return;
    if (window._gaiaeHistChart) window._gaiaeHistChart.dispose();
    window._gaiaeHistChart = echarts.init(el);

    // Use US chart dates as x-axis (it has more data points typically)
    const usDates = usChart ? usChart.dates : [];
    const usValues = usChart ? usChart.values : [];
    const jpDates = jpChart ? jpChart.dates : [];
    const jpValues = jpChart ? jpChart.values : [];
    const hkDates = hkChart ? hkChart.dates : [];
    const hkValues = hkChart ? hkChart.values : [];

    // Merge dates
    const allDates = [...new Set([...usDates, ...jpDates, ...hkDates])].sort();
    const usMap = {}; usDates.forEach((d, i) => usMap[d] = usValues[i]);
    const jpMap = {}; jpDates.forEach((d, i) => jpMap[d] = jpValues[i]);
    const hkMap = {}; hkDates.forEach((d, i) => hkMap[d] = hkValues[i]);

    const usData = allDates.map(d => usMap[d] ?? null);
    const jpData = allDates.map(d => jpMap[d] ?? null);
    const hkData = allDates.map(d => hkMap[d] ?? null);

    // US five-tier mark areas
    const markAreaData = [
        [{ yAxis: 0, itemStyle: { color: 'rgba(16,185,129,0.05)' } }, { yAxis: 15 }],
        [{ yAxis: 15, itemStyle: { color: 'rgba(59,130,246,0.04)' } }, { yAxis: 20 }],
        [{ yAxis: 20, itemStyle: { color: 'rgba(234,179,8,0.04)' } }, { yAxis: 28 }],
        [{ yAxis: 28, itemStyle: { color: 'rgba(249,115,22,0.05)' } }, { yAxis: 36 }],
        [{ yAxis: 36, itemStyle: { color: 'rgba(239,68,68,0.05)' } }, { yAxis: 50 }],
    ];

    window._gaiaeHistChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(245,158,11,0.3)',
            textStyle: { color: '#e2e8f0', fontSize: 11 },
        },
        legend: { top: 0, textStyle: { color: '#94a3b8', fontSize: 10 } },
        grid: { left: 50, right: 20, top: 30, bottom: 30 },
        xAxis: {
            type: 'category', data: allDates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 8, formatter: function(v) { return v.substring(0, 7); } },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: {
            type: 'value', min: 0, max: 50,
            axisLabel: { color: '#64748b', fontSize: 8, formatter: function(v) { return v + '%'; } },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }
        },
        series: [
            {
                name: '🇺🇸 US AIAE', type: 'line', data: usData, smooth: true, connectNulls: true,
                symbol: 'circle', symbolSize: 8,
                lineStyle: { color: '#3b82f6', width: 2.5, shadowColor: 'rgba(59,130,246,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#3b82f6', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(59,130,246,0.15)' }, { offset: 1, color: 'rgba(59,130,246,0)' }]
                }},
                label: { show: true, fontSize: 7, color: '#3b82f6', formatter: function(p) { return p.value !== null ? p.value + '%' : ''; }, position: 'top' },
                markArea: { silent: true, data: markAreaData },
            },
            {
                name: '🇯🇵 JP AIAE', type: 'line', data: jpData, smooth: true, connectNulls: true,
                symbol: 'diamond', symbolSize: 8,
                lineStyle: { color: '#dc2626', width: 2.5, shadowColor: 'rgba(220,38,38,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#dc2626', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(220,38,38,0.12)' }, { offset: 1, color: 'rgba(220,38,38,0)' }]
                }},
                label: { show: true, fontSize: 7, color: '#dc2626', formatter: function(p) { return p.value !== null ? p.value + '%' : ''; }, position: 'bottom' },
            },
            {
                name: '🇭🇰 HK AIAE', type: 'line', data: hkData, smooth: true, connectNulls: true,
                symbol: 'rect', symbolSize: 7,
                lineStyle: { color: '#a855f7', width: 2.5, shadowColor: 'rgba(168,85,247,0.3)', shadowBlur: 6 },
                itemStyle: { color: '#a855f7', borderColor: '#0f172a', borderWidth: 2 },
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: 'rgba(168,85,247,0.12)' }, { offset: 1, color: 'rgba(168,85,247,0)' }]
                }},
                label: { show: true, fontSize: 7, color: '#a855f7', formatter: function(p) { return p.value !== null ? p.value + '%' : ''; }, position: 'insideTopRight' },
            }
        ]
    });
}

