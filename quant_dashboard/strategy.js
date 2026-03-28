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

        // 评分位映射：CRASH=0, BEAR=8, RANGE=15, BULL=20
        const regimeScoreMap = { CRASH: 0, BEAR: 8, RANGE: 15, BULL: 20 };
        const score = regimeScoreMap[regime] ?? 15;

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
    const mom  = parseInt(document.getElementById('calc-mom')?.value  || 0);
    const reg  = parseInt(document.getElementById('calc-regime')?.value || 0);
    const vol  = parseInt(document.getElementById('calc-vol')?.value  || 0);
    const rsi  = parseInt(document.getElementById('calc-rsi')?.value  || 0);
    const vlt  = parseInt(document.getElementById('calc-vlt')?.value  || 0);

    const total = mom + reg + vol + rsi + vlt;

    // ── 状态自适应门槛 ──
    // 优先使用 calc-regime 下拉框的值推断市场状态门槛
    // (下拉框是用户手动控制的主权，要始终响应)
    let gate;
    if (reg === 20) {
        gate = 65; // BULL 牛市
    } else if (reg === 12) {
        gate = 68; // RANGE 震荡
    } else {
        gate = 75; // BEAR 熊市 (reg === 0)
    }
    const halfGate  = Math.round(gate * 0.85);  // 半仓线约在门槛的85%
    const fullGate  = Math.min(gate + 15, 95);  // 满仓线

    const numEl  = document.getElementById('calc-score-num');
    const barEl  = document.getElementById('calc-score-bar');
    const vrdEl  = document.getElementById('calc-verdict');
    const actEl  = document.getElementById('calc-action');
    const thEl   = document.getElementById('calc-threshold-hint');

    if (numEl) numEl.textContent = total;
    if (barEl) barEl.style.width = total + '%';
    if (thEl)  thEl.textContent  = `当前市场门槛: 全仓≥${fullGate} | 标准≥${gate} | 半仓≥${halfGate}`;

    let color, verdict, action;
    if (total >= fullGate) {
        color = '#10b981'; verdict = '🟢 全仓入场';
        action = `综合评分 ${total} 分（≥${fullGate}满仓线），信号极强。建议建仓至单标的上限，止损按当前状态止损线执行，追踪止盈 T1+15% / T2+25%。`;
    } else if (total >= gate) {
        color = '#22d3ee'; verdict = '🔵 标准入场';
        action = `综合评分 ${total} 分（≥${gate}达标），信号达标。建议建仓 2/3，等候量能确认后加到满仓。`;
    } else if (total >= halfGate) {
        color = '#fbbf24'; verdict = '🟡 半仓观察';
        action = `综合评分 ${total} 分（≥${halfGate}半仓线），信号偏弱。建议建仓上限的 50%，等调仓日重新评估，不主动追涨。`;
    } else {
        color = '#f87171'; verdict = '❌ 不入场';
        action = `综合评分 ${total} 分（<${halfGate}），信号不足。建议观望，等动量 Z 分提升或市场状态改善。`;
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
    const divIds = ['div-calc-regime','div-calc-rsi','div-calc-bias','div-calc-yield','div-calc-boll','div-calc-vol'];
    divIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', calcDividendScore);
    });
});

// ====== 💰 红利策略专属评分器 V3.1 ======
// 六维因子：市场环境 + RSI(9) + 乖离率 + 股息率估值 + 布林带位置 + 波动率
// 评分满分：100分，门槛随市场状态自适应
function calcDividendScore() {
    const regime  = document.getElementById('div-calc-regime')?.value  || 'RANGE';
    const rsiVal  = parseInt(document.getElementById('div-calc-rsi')?.value  || 10);
    const biasVal = parseInt(document.getElementById('div-calc-bias')?.value || 8);
    const yldVal  = parseInt(document.getElementById('div-calc-yield')?.value || 12);
    const bollVal = parseInt(document.getElementById('div-calc-boll')?.value  || 6);
    const volVal  = parseInt(document.getElementById('div-calc-vol')?.value   || 10);

    // 维度1：市场环境得分
    const envScore = { BULL: 20, RANGE: 12, BEAR: 5, CRASH: 0 }[regime] ?? 12;

    const total = envScore + rsiVal + biasVal + yldVal + bollVal + volVal;

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

    // Badge
    const badge = document.getElementById('regime-badge');
    if (badge) {
        badge.style.background  = meta.bg;
        badge.style.borderColor = meta.border;
        badge.className = badge.className.replace(/regime-\w+-glow/g, '');
        badge.classList.add(`regime-${regime.toLowerCase()}-glow`);
    }
    if (badge) {
        badge.style.borderColor = clr + '55';
        badge.style.background  = clr + '15';
    }
    _setText('regime-icon-text', d.regime_icon  || '🟡');
    _setText('regime-name-cn',   d.regime_cn    || d.regime);
    _setText('regime-name-en',   (d.regime || 'RANGE') + ' MODE');
    _setColor('regime-name-cn',  clr);
    _setText('regime-desc-text', d.regime_desc  || '');

    // Metrics
    _setText('rm-csi',    d.csi300?.toFixed(0) ?? '—');
    _setText('rm-ma120',  d.ma120?.toFixed(0)  ?? '—');

    const r5  = d.ret5d  ?? 0;
    const r20 = d.ret20d ?? 0;
    const el5  = document.getElementById('rm-ret5');
    const el20 = document.getElementById('rm-ret20');
    if (el5)  { el5.textContent  = (r5  >= 0 ? '+' : '') + r5.toFixed(2)  + '%'; el5.style.color  = r5  >= 0 ? '#10b981' : '#f87171'; }
    if (el20) { el20.textContent = (r20 >= 0 ? '+' : '') + r20.toFixed(2) + '%'; el20.style.color = r20 >= 0 ? '#10b981' : '#f87171'; }

    const slope = d.ma120_slope5 ?? 0;
    const slopeEl = document.getElementById('rm-slope');
    if (slopeEl) {
        slopeEl.textContent = (slope >= 0 ? '↑ +' : '↓ ') + slope.toFixed(2);
        slopeEl.style.color = slope >= 0 ? '#10b981' : '#f87171';
    }
    _setText('rm-vol', (d.vol20d?.toFixed(1) ?? '—') + '%');

    // Adaptive params
    _setText('rm-p-topn',  p.top_n           ?? 3);
    _setText('rm-p-rb',    p.rebalance_days  ?? 5);
    _setText('rm-p-poscap',p.pos_cap         ?? 66);
    _setText('rm-p-sl',    p.stop_loss       ?? -8);
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
        });
    });
});

// ====== 全局策略执行函数 ======
async function runStrategy() {
    const btn = document.getElementById('st-run-btn');
    const loading = document.getElementById('st-loading');
    const timeEl = document.getElementById('st-data-time');
    const strategyType = document.getElementById('st-strategy-select')?.value || 'mean-reversion';

    // 助手函数：安全设置内容
    const safelySetText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };
    const safelySetHTML = (id, html) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    };

    // 重置：隐藏所有结果区
    const mrResults = document.getElementById('st-results-mr');
    const dtResults = document.getElementById('st-results-dt');
    const momResults = document.getElementById('st-results-mom');
    if (mrResults) mrResults.style.display = 'none';
    if (dtResults) dtResults.style.display = 'none';
    if (momResults) momResults.style.display = 'none';

    // 禁用按钮 + 显示加载
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 运行中...'; }
    if (loading) loading.style.display = 'flex';

    // 更新加载文案
    const loadingP = loading?.querySelector('p');
    if (loadingP) {
        if (strategyType === 'dividend-trend') {
            loadingP.textContent = '正在拉取红利ETF收盘数据并计算趋势信号...';
        } else if (strategyType === 'momentum') {
            loadingP.textContent = '正在获取板块数据、评估市场环境、计算动量排名...';
        } else {
            loadingP.textContent = '正在拉取全量ETF数据并计算共振信号...';
        }
    }

    try {
        let endpoint;
        if (strategyType === 'dividend-trend') {
            endpoint = `${API_URL}/api/v1/dividend_strategy`;
        } else if (strategyType === 'momentum') {
            endpoint = `${API_URL}/api/v1/momentum_strategy`;
        } else {
            endpoint = `${API_URL}/api/v1/strategy`;
        }

        const resp = await fetch(endpoint);
        const json = await resp.json();

        if (json.status !== 'success') throw new Error(json.message || '策略执行失败');

        if (timeEl) {
            timeEl.textContent = `数据截至 ${json.timestamp.substring(0, 16).replace('T', ' ')}`;
        }

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

        if (loading) loading.style.display = 'none';

    } catch (err) {
        if (loading) loading.style.display = 'none';

        // 在对应的表格中显示错误
        const errorTarget = strategyType === 'dividend-trend' ? 'dt-table-body'
            : strategyType === 'momentum' ? 'mom-table-body' : 'st-table-body';
        const resultTarget = strategyType === 'dividend-trend' ? dtResults
            : strategyType === 'momentum' ? momResults : mrResults;
        if (resultTarget) resultTarget.style.display = 'block';
        safelySetHTML(errorTarget,
            `<tr><td colspan="12" style="text-align:center;color:#ef4444;padding:40px;">❌ ${err.message}<br><small style="color:var(--text-muted)">请确认后端已启动：python main.py</small></td></tr>`
        );
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🚀 运行策略'; }
    }
}

// ====== 均值回归结果渲染 ======
function renderMeanReversionResults(data, { safelySetText, safelySetHTML }) {
    const ov = data.market_overview;
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

// ====== 红利趋势结果渲染 ======
function renderDividendResults(data, { safelySetText, safelySetHTML }) {
    const ov = data.market_overview;
    safelySetText('dt-trend-up', `${ov.trend_up_count} / 8`);
    safelySetText('dt-buy-count', ov.buy_count + ' 只');
    safelySetText('dt-sell-count', ov.sell_count + ' 只');
    safelySetText('dt-total-pos', ov.total_suggested_pos + '%');

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
    container.innerHTML = items.map(s => `
        <div class="st-action-item">
            <div class="st-ai-info">
                <span class="st-ai-name">${s.name}</span>
                <span class="st-ai-code">${s.code}</span>
            </div>
            <div class="st-ai-meta">
                <span class="st-ai-score ${type === 'buy' ? 'st-ai-score-buy' : 'st-ai-score-sell'}">${type === 'buy' ? '建仓' : '清仓'}</span>
                <span class="st-ai-pos">${s.suggested_position > 0 ? s.suggested_position + '%' : '0%'}</span>
            </div>
        </div>
    `).join('');
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

        return `<tr class="${rowClass}">
            <td style="font-weight:600;color:#fff;">${s.name}</td>
            <td style="font-family:monospace;color:#60a5fa;font-size:0.75rem;">${s.code}</td>
            <td>${s.close}</td>
            <td style="color:${yieldColor};font-weight:${yieldWeight}">${s.ttm_yield}%</td>
            <td style="color:var(--text-muted)">${s.ma120 || s.ma100}</td>
            <td>${trendTag}</td>
            <td style="color:${rsiColor}">${s.rsi}</td>
            <td style="color:${biasColor}">${s.bias > 0 ? '+' : ''}${s.bias}%</td>
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
                <span class="st-ai-code">${s.code}</span>
            </div>
            <div class="st-ai-meta">
                <span class="st-ai-score ${type === 'buy' ? 'st-ai-score-buy' : 'st-ai-score-sell'}">${s.score}分</span>
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

        return `<tr class="${rowClass}">
            <td style="font-weight:600;color:#fff">${s.name}</td>
            <td style="font-family:monospace;color:#60a5fa;font-size:0.75rem">${s.code}</td>
            <td>${s.close}</td>
            <td style="color:${s.percent_b <= 0 ? '#10b981' : (s.percent_b >= 1 ? '#ef4444' : 'inherit')};font-weight:${s.percent_b <= 0 || s.percent_b >= 1 ? '700' : '400'}">${s.percent_b}</td>
            <td style="color:${s.rsi_3 <= 10 ? '#10b981' : (s.rsi_3 >= 90 ? '#ef4444' : 'inherit')}">${s.rsi_3}</td>
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
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);padding:40px;">暂无信号数据</td></tr>';
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
