/**
 * AlphaCore · 波动率仓位预算面板 (机构风控视角)
 * decision/vol_budget_panel.js · v3
 *
 * 数据源: GET /api/v1/portfolio/vol-budget[?refresh=1]  (services/portfolio_vol.build_decision_view)
 * 原则:   先看约束, 再看信号; 上限是天花板, 不是目标; 只读, 不下单
 *
 * 信息层级 (由粗到细, 一屏只回答一个问题):
 *   风险条   能不能加仓? 偏离多少? 风险多大?                (始终可见)
 *   上限标尺 哪一层约束在起作用? 实际仓位压线多少?          (始终可见)
 *   页签     概览 · 风险归因 · 尾部与情景 · 执行草案 · 方法与数据
 *
 * 工程: 纯渲染函数 (state → HTML) + 事件委托 (无内联 onclick, 兼容 CSP);
 *       刷新时保留旧内容, 失败不清屏; 页签记忆仅为本机便利 (localStorage, 失败静默)。
 */

(function () {
    'use strict';

    const API = '/api/v1/portfolio/vol-budget';
    const TAB_KEY = 'ac.vb.tab';
    const LEVEL = {
        danger:  { cls: 'danger',  tag: '超预算' },
        warning: { cls: 'warning', tag: '需处理' },
        ok:      { cls: 'ok',      tag: '预算内' },
        room:    { cls: 'room',    tag: '有空间' },
        unknown: { cls: 'unknown', tag: '数据不足' },
    };
    const RULE_LABEL = { static: '静态', vol: '波动', gap: '跌停' };
    const BUCKET_CLS = { star: 'b-star', chinext: 'b-chinext', main: 'b-main', bse: 'b-bse', etf: 'b-etf' };
    const TABS = [
        ['overview', '概览'],
        ['attribution', '风险归因'],
        ['tail', '尾部与情景'],
        ['execution', '执行草案'],
        ['data', '方法与数据'],
    ];

    const state = { view: null, tab: readTab(), sort: 'risk', expanded: false, loading: false };

    // ── 格式化 ──
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const num = (v) => (v == null || v === '' || isNaN(v)) ? null : Number(v);
    const pct = (v, d = 0) => num(v) == null ? '--' : `${Number(v).toFixed(d)}%`;
    const rpct = (v, d = 0) => num(v) == null ? '--' : `${(Number(v) * 100).toFixed(d)}%`;
    const fx = (v, d = 2) => num(v) == null ? '--' : Number(v).toFixed(d);
    const signed = (v, d = 0, unit = 'pp') => num(v) == null ? '--' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}${unit}`;
    const money = (v) => {
        const n = num(v);
        if (n == null) return '--';
        const a = Math.abs(n);
        const s = a >= 1e8 ? `${(a / 1e8).toFixed(2)}亿` : a >= 1e4 ? `${(a / 1e4).toFixed(1)}万` : Math.round(a).toLocaleString();
        return `${n < 0 ? '-' : ''}¥${s}`;
    };
    const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
    const mmdd = (d) => d ? String(d).slice(5) : '--';

    function readTab() {
        try { const t = localStorage.getItem(TAB_KEY); if (TABS.some(([k]) => k === t)) return t; } catch (e) { /* 无痕/禁用存储 */ }
        return 'overview';
    }
    function writeTab(t) { try { localStorage.setItem(TAB_KEY, t); } catch (e) { /* 忽略 */ } }

    const doFetch = (url) => (window.AC && typeof AC.secureFetch === 'function') ? AC.secureFetch(url) : fetch(url);

    // ═══════════════════════════════════════════════
    //  风险条: 结论 + 关键读数 + 数据时点
    // ═══════════════════════════════════════════════
    function renderStrip(v) {
        const lv = LEVEL[v.verdict?.level] || LEVEL.unknown;
        const p = v.portfolio || {};
        const rp = p.replay || {};
        const dq = p.data_quality || {};
        const pv = num(p.portfolio_vol), tv = num(p.target_vol);
        const volCls = pv != null && tv != null ? (pv > tv * 1.5 ? 'danger' : pv > tv ? 'warning' : 'ok') : '';
        const bets = num(p.effective_bets);
        const betsCls = bets == null ? '' : bets < 2 ? 'danger' : bets < 4 ? 'warning' : 'ok';
        const mdd = num(rp.current?.max_drawdown_pct);
        const mddCls = mdd == null ? '' : mdd < -25 ? 'danger' : mdd < -15 ? 'warning' : 'ok';
        const meta = p.meta || {};
        const cell = (label, value, sub, cls = '') => `
            <div class="vb-stat ${cls}"><div class="vb-stat-l">${label}</div>
                <div class="vb-stat-v">${value}</div><div class="vb-stat-s">${sub}</div></div>`;
        return `
        <section class="vb-strip ${lv.cls}" aria-label="波动预算结论">
            <div class="vb-strip-head">
                <span class="vb-badge ${lv.cls}"><i></i>${lv.tag}</span>
                <div class="vb-verdict-text" role="heading" aria-level="3">${esc(v.verdict?.text || '--')}</div>
                <span class="vb-chip-s">约束 · ${esc(v.verdict?.binding_label || '—')}</span>
                <span class="vb-chip-s ${v.verdict?.enforced ? 'hard' : ''}">${v.verdict?.enforced ? '合规硬阻断' : '合规软警告'}</span>
                <span class="vb-strip-time" title="行情最新日 / 持仓导入日 / 计算时间">
                    行情 ${mmdd(dq.price_asof)} · 持仓 ${mmdd(p.as_of)} · ${esc((meta.computed_at || '').slice(11, 16) || '--')}${meta.cache === 'hit' ? ' 缓存' : ''}
                    <button type="button" class="vb-btn" data-vb-action="refresh" ${state.loading ? 'disabled' : ''} aria-label="重新计算">${state.loading ? '计算中' : '重算'}</button>
                </span>
            </div>
            <p class="vb-instr">${esc(v.verdict?.instruction || '')}</p>
            <div class="vb-stats">
                ${cell('有效上限', pct(v.effective_cap_pct, 0), '取最严约束')}
                ${cell('实际仓位', pct(v.actual_pct, 0), `偏离 <b class="vb-gap ${lv.cls}">${signed(v.gap_pp)}</b>`)}
                ${cell('组合年化波动', rpct(pv, 0), `目标 ${rpct(tv, 0)}${p.vol_range ? ` · 区间 ${rpct(p.vol_range.low)}–${rpct(p.vol_range.high)}` : ''}`, volCls)}
                ${cell('有效独立押注', bets == null ? '--' : bets.toFixed(1), `${(p.positions || []).length} 个持仓 · 相关 ${fx(p.avg_corr)}`, betsCls)}
                ${cell('一年回放最大回撤', pct(mdd, 1), `按当前持仓 · ${money(rp.current?.max_drawdown_amt)}`, mddCls)}
                ${cell('1日 95% ES', money(rp.current?.es_1d_95_amt ?? p.pre_trade?.current?.var_1d_95_amt),
                       rp.tail_multiplier ? `历史口径 · 正态的 ${fx(rp.tail_multiplier, 1)}×` : '正态近似')}
            </div>
        </section>`;
    }

    // ═══════════════════════════════════════════════
    //  上限标尺: 一根 0–100% 轴上看清每层约束与实际仓位
    // ═══════════════════════════════════════════════
    function renderRuler(v) {
        const steps = Object.fromEntries((v.waterfall || []).map((s) => [s.key, s]));
        const eff = num(v.effective_cap_pct), act = num(v.actual_pct);
        const bind = v.verdict?.binding === 'portfolio_budget' ? 'portfolio' : v.verdict?.binding === 'aiae_vol' ? 'market' : null;
        // 同值约束合并成一个标记 (如 AIAE 60% 未被刹车压低时 "AIAE = 刹车后 60%"), 相邻标记错行避免重叠
        const groups = [];
        [['aiae', 'AIAE'], ['market', '刹车后'], ['portfolio', '波动预算']].forEach(([k, short]) => {
            const val = num(steps[k]?.value);
            if (val == null) return;
            const g = groups.find((x) => Math.abs(x.val - val) < 0.05);
            if (g) { g.keys.push(k); g.names.push(short); } else groups.push({ val, keys: [k], names: [short] });
        });
        groups.sort((a, b) => a.val - b.val);
        const marks = groups.map((g, gi) => {
            const row = gi % 2;                    // 交替上下两行: 窄屏上相距 20pp 的标记也不会重叠
            const title = g.keys.map((k) => `${steps[k].label} ${pct(steps[k].value, 1)} · ${steps[k].note || ''}`).join('\n');
            return `<div class="vb-mark ${g.keys.map((k) => 'm-' + k).join(' ')} ${g.keys.includes(bind) ? 'bind' : ''} row${row}"
                         style="left:${clamp(g.val, 0, 100)}%" title="${esc(title)}"><span>${g.names.join(' = ')} ${pct(g.val)}</span></div>`;
        }).join('');
        const over = eff != null && act != null && act > eff;
        const lv = v.verdict?.level || 'unknown';
        const legend = (v.waterfall || []).map((s) => `
            <li class="${s.key === bind ? 'bind' : ''} ${s.key === 'effective' ? 'eff' : ''}">
                <span class="vb-lg-k">${esc(s.label)}</span>
                <span class="vb-lg-v">${num(s.value) == null ? '—' : pct(s.value, s.value % 1 ? 1 : 0)}</span>
                <span class="vb-lg-n">${s.key === bind ? '<em>最严</em>' : ''}${esc(s.note || '')}</span>
            </li>`).join('');
        return `
        <section class="vb-ruler-wrap" aria-label="仓位上限标尺">
            <div class="vb-ruler" role="img" aria-label="有效上限 ${pct(eff)}, 实际仓位 ${pct(act)}">
                <div class="vb-ruler-track">
                    ${eff != null ? `<div class="vb-ruler-safe" style="width:${clamp(eff, 0, 100)}%"></div>` : ''}
                    ${act != null ? `<div class="vb-ruler-act ${lv}" style="width:${clamp(act, 0, 100)}%"></div>` : ''}
                    ${over ? `<div class="vb-ruler-over" style="left:${clamp(eff, 0, 100)}%;width:${clamp(act - eff, 0, 100)}%"></div>` : ''}
                    ${eff != null ? `<div class="vb-ruler-eff" style="left:${clamp(eff, 0, 100)}%"><span>有效上限 ${pct(eff)}</span></div>` : ''}
                </div>
                <div class="vb-ruler-marks">${marks}</div>
                <div class="vb-ruler-axis"><span>0</span><span>25</span><span>50</span><span>75</span><span>100%</span></div>
            </div>
            <ol class="vb-legend">${legend}</ol>
        </section>`;
    }

    // ═══════════════════════════════════════════════
    //  页签: 概览
    // ═══════════════════════════════════════════════
    function renderOverview(v) {
        const p = v.portfolio || {}, m = v.market || {};
        const ratio = num(m.ratio), trig = num(m.trigger_ratio) || 2;
        const scale = Math.max(3, trig * 1.5);
        const mCls = m.status === 'stale' || m.status === 'missing' ? 'warning'
            : (m.brake_on ? 'danger' : (ratio != null && ratio > trig * 0.75 ? 'warning' : 'ok'));
        const mNote = m.status === 'stale' ? '数据过期 · 保守系数' : m.status === 'missing' ? '数据缺失 · 保守系数'
            : m.brake_on ? `刹车中 · 系数 ${fx(m.factor)}` : `未触发 · 系数 ${fx(m.factor)}`;
        const tv = num(p.target_vol);
        const cur = tv != null ? `${Math.round(tv * 100)}%` : null;
        const chips = Object.entries(p.equity_by_target || {}).map(([t, eq]) =>
            `<li class="${t === cur ? 'on' : ''}"><b>${esc(t)}</b><span>${pct(eq)}</span></li>`).join('');
        const breach = num(p.breach_count) || 0;
        return `
        <div class="vb-cols">
            <div>
                <h4 class="vb-h">风险集中在哪 <span>权重 vs 风险贡献 · 按跌停幅度分桶</span></h4>
                ${renderBuckets(p)}
                <h4 class="vb-h">风险最大的三个持仓</h4>
                <ol class="vb-top">${(p.top_risk || []).map((t) =>
                    `<li><span>${esc(t.name)}</span><b>${rpct(t.risk_share, 1)}</b></li>`).join('') || '<li class="vb-muted">--</li>'}</ol>
            </div>
            <div>
                <h4 class="vb-h">约束读数</h4>
                <div class="vb-kpis">
                    <div class="vb-kpi ${breach ? 'danger' : 'ok'}">
                        <div class="vb-kpi-l">超单票上限</div>
                        <div class="vb-kpi-v">${breach}<small> 只</small></div>
                        <div class="vb-kpi-s">${breach ? `超额约 ${money(p.cap_excess_amount)}` : '上限 = min(静态, k/σ, 跌停)'}</div>
                    </div>
                    <div class="vb-kpi">
                        <div class="vb-kpi-l">满仓结构波动</div>
                        <div class="vb-kpi-v">${rpct(p.sleeve_vol)}</div>
                        <div class="vb-kpi-s">目标 ÷ 结构 = 最大仓位 ${pct(p.max_equity_pct, 0)}</div>
                    </div>
                    <div class="vb-kpi vb-wide ${mCls}">
                        <div class="vb-kpi-l">市场尾部刹车 · ${esc(m.index_code || '沪深300')}</div>
                        <div class="vb-kpi-v">${ratio == null ? '--' : ratio.toFixed(2) + '×'}<small> 自适应基准</small></div>
                        <div class="vb-gauge"><div class="vb-gauge-fill" style="width:${ratio == null ? 0 : clamp(ratio / scale * 100, 0, 100).toFixed(1)}%"></div>
                            <div class="vb-gauge-trig" style="left:${(trig / scale * 100).toFixed(1)}%"><span>触发 ${trig.toFixed(1)}×</span></div></div>
                        <div class="vb-kpi-s">${esc(mNote)} · σ ${rpct(m.sigma_hat, 1)} / 基准 ${rpct(m.baseline, 1)} · ${esc(m.trade_date || '--')}</div>
                    </div>
                    <div class="vb-kpi vb-wide">
                        <div class="vb-kpi-l">目标波动 → 最大仓位 <span class="vb-muted">(个人风险偏好, strategy_runtime.json)</span></div>
                        <ul class="vb-sens">${chips || '<li class="vb-muted">--</li>'}</ul>
                    </div>
                </div>
            </div>
        </div>`;
    }

    function renderBuckets(p) {
        const bs = p.risk_by_bucket || [];
        if (!bs.length) return '<div class="vb-muted">--</div>';
        const inv = num(p.invested_pct) || 100;
        const bar = (field, scale) => bs.map((b) => {
            const val = field === 'w' ? (num(b.weight_pct) || 0) / inv : (num(b.risk_share) || 0);
            return `<span class="${BUCKET_CLS[b.key] || ''}" style="width:${(val * 100 * scale).toFixed(2)}%" title="${esc(b.label)} ${(val * 100).toFixed(1)}%"></span>`;
        }).join('');
        const rows = bs.map((b) => {
            const rpw = num(b.risk_per_weight);
            return `<tr><td><i class="vb-dot ${BUCKET_CLS[b.key] || ''}"></i>${esc(b.label)}<span class="vb-code">${b.count}只</span></td>
                <td class="vb-r">${pct(b.weight_pct, 1)}</td><td class="vb-r">${rpct(b.risk_share, 1)}</td>
                <td class="vb-r ${rpw != null && rpw > 1.1 ? 'vb-bad' : rpw != null && rpw < 0.9 ? 'vb-good' : ''}">${rpw == null ? '--' : rpw.toFixed(2) + '×'}</td></tr>`;
        }).join('');
        return `
            <div class="vb-stack"><label>权重</label><div class="vb-stack-bar">${bar('w', 1)}</div></div>
            <div class="vb-stack"><label>风险</label><div class="vb-stack-bar">${bar('r', 1)}</div></div>
            <table class="vb-table vb-compact"><thead><tr><th>分桶</th><th class="vb-r">权重</th><th class="vb-r">风险贡献</th>
                <th class="vb-r" title="风险贡献 ÷ 权重占比: >1 表示承担了超出权重的风险">风险/权重</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    // ═══════════════════════════════════════════════
    //  页签: 风险归因 (持仓级)
    // ═══════════════════════════════════════════════
    const SORTS = {
        risk: ['风险贡献', (a, b) => (b.risk_share || 0) - (a.risk_share || 0)],
        weight: ['权重', (a, b) => (b.weight_pct || 0) - (a.weight_pct || 0)],
        rpw: ['风险/权重', (a, b) => (b.risk_per_weight || 0) - (a.risk_per_weight || 0)],
        over: ['超限', (a, b) => (b.over_cap_pp || 0) - (a.over_cap_pp || 0)],
    };

    function renderAttribution(v) {
        const p = v.portfolio || {};
        const rows = [...(p.positions || [])].sort(SORTS[state.sort][1]);
        if (!rows.length) return '<div class="vb-empty">无持仓</div>';
        const inv = num(p.invested_pct) || 100;
        const maxV = Math.max(...rows.map((r) => Math.max((r.risk_share || 0) * 100, (r.weight_pct || 0) / inv * 100)), 1);
        const TOP = 10;
        const shown = state.expanded ? rows : rows.slice(0, TOP);
        const body = shown.map((r) => {
            const over = num(r.over_cap_pp) > 0;
            const wShare = (num(r.weight_pct) || 0) / inv * 100;
            const rc = (num(r.risk_share) || 0) * 100;
            const rpw = num(r.risk_per_weight);
            const flags = [
                r.vol_source === 'proxy' ? '<span class="vb-flag" title="缺少行情, 使用代理波动">估</span>' : '',
                r.price_stale ? `<span class="vb-flag" title="最后行情日 ${esc(r.last_price_date)}">旧</span>` : '',
                r.beta_estimated && r.vol_source !== 'proxy' ? '<span class="vb-flag" title="β 为同类中位数">β估</span>' : '',
            ].join('');
            return `
            <tr class="${over ? 'over' : ''}">
                <td class="vb-name"><i class="vb-dot ${BUCKET_CLS[r.bucket] || ''}"></i>${esc(r.name)}<span class="vb-code">${esc(r.ts_code)}</span>${flags}</td>
                <td class="vb-r">${pct(r.weight_pct, 1)}</td>
                <td class="vb-r">${rpct(r.vol)}</td>
                <td class="vb-r">${fx(r.beta_theme)}</td>
                <td class="vb-dual" title="权重占比 ${wShare.toFixed(1)}% · 风险贡献 ${rc.toFixed(1)}%">
                    <div class="vb-dual-t"><span class="w" style="width:${(wShare / maxV * 100).toFixed(1)}%"></span>
                        <span class="r" style="width:${(rc / maxV * 100).toFixed(1)}%"></span></div>
                    <b>${rc.toFixed(1)}%</b></td>
                <td class="vb-r ${rpw != null && rpw > 1.15 ? 'vb-bad' : rpw != null && rpw < 0.85 ? 'vb-good' : ''}">${rpw == null ? '--' : rpw.toFixed(2) + '×'}</td>
                <td class="vb-r">${pct(r.cap_pct, 1)}<span class="vb-rule">${esc(RULE_LABEL[r.cap_rule] || r.cap_rule || '')}</span></td>
                <td class="vb-r ${over ? 'vb-bad' : 'vb-dim'}">${over ? signed(r.over_cap_pp, 1) : '—'}</td>
                <td class="vb-r vb-strong">${pct(r.target_pct, 1)}</td>
            </tr>`;
        }).join('');
        const sortBtns = Object.entries(SORTS).map(([k, [label]]) =>
            `<button type="button" class="vb-seg ${k === state.sort ? 'on' : ''}" data-vb-sort="${k}" aria-pressed="${k === state.sort}">${label}</button>`).join('');
        const rest = rows.length - TOP;
        return `
        <div class="vb-toolbar"><h4 class="vb-h">持仓风险归因 <span>灰 = 权重占比 · 色 = 风险贡献 (Euler 分解)</span></h4>
            <div class="vb-segs" role="group" aria-label="排序">${sortBtns}</div></div>
        <div class="vb-table-wrap">
            <table class="vb-table">
                <thead><tr><th>持仓</th><th class="vb-r">权重</th><th class="vb-r">年化波动</th><th class="vb-r" title="对科创50 的 β">β科创50</th>
                    <th>权重 vs 风险</th><th class="vb-r" title="风险贡献 ÷ 权重占比">风险/权重</th><th class="vb-r">单票上限</th><th class="vb-r">超限</th>
                    <th class="vb-r" title="推荐草案执行后的权重">草案</th></tr></thead>
                <tbody>${body}</tbody>
            </table>
        </div>
        ${rest > 0 ? `<button type="button" class="vb-btn vb-more" data-vb-action="expand">${state.expanded ? '收起' : `展开其余 ${rest} 个持仓`}</button>` : ''}
        <p class="vb-hint">风险/权重 &gt; 1: 该持仓承担的风险多于它占用的资金。标记: 估 = 代理波动, 旧 = 行情过期, β估 = 同类中位数。</p>`;
    }

    // ═══════════════════════════════════════════════
    //  页签: 尾部与情景
    // ═══════════════════════════════════════════════
    function renderTail(v) {
        const p = v.portfolio || {};
        const rp = p.replay;
        const pt = p.pre_trade || {};
        const rows = [
            ['1日 95% VaR · 正态', pt.current?.var_1d_95_amt, pt.after?.var_1d_95_amt],
            ['1日 95% VaR · 历史', rp?.current?.var_1d_95_amt, rp?.after?.var_1d_95_amt],
            ['1日 95% ES · 正态', rp?.normal_es_1d_95_amt, null],
            ['1日 95% ES · 历史', rp?.current?.es_1d_95_amt, rp?.after?.es_1d_95_amt],
            ['20日 95% ES · 正态', pt.current?.es_20d_95_amt, pt.after?.es_20d_95_amt],
            ['最差单日 · 历史', rp?.current?.worst_day_amt, rp?.after?.worst_day_amt],
            ['最大回撤 · 历史', rp?.current?.max_drawdown_amt, rp?.after?.max_drawdown_amt],
        ].filter((r) => num(r[1]) != null).map(([k, a, b]) => `
            <tr><td>${k}</td><td class="vb-r">${money(-Math.abs(a))}</td><td class="vb-r vb-strong">${num(b) == null ? '—' : money(-Math.abs(b))}</td></tr>`).join('');
        return `
        <div class="vb-cols">
            <div>
                <h4 class="vb-h">一年回放 <span>${rp ? `${esc(rp.start)} → ${esc(rp.end)} · ${rp.window} 日` : '数据不足'}</span></h4>
                ${rp ? renderReplayChart(rp) : '<div class="vb-empty">回放需要主题指数与持仓行情</div>'}
                ${rp ? `<p class="vb-hint">${esc(rp.note)}${num(rp.fill_share) ? `; ${(rp.fill_share * 100).toFixed(1)}% 的数据点用 β×科创50 填补` : ''}。</p>` : ''}
            </div>
            <div>
                <h4 class="vb-h">损失度量 <span>金额按账户 ${money(p.total_asset)}</span></h4>
                <table class="vb-table vb-compact"><thead><tr><th>口径</th><th class="vb-r">当前</th><th class="vb-r">执行草案后</th></tr></thead>
                    <tbody>${rows}</tbody></table>
                ${rp?.tail_multiplier ? `<p class="vb-hint">历史 ES ÷ 正态 ES = <b>${fx(rp.tail_multiplier, 2)}×</b>: ${rp.tail_multiplier > 1.15 ? '尾部明显厚于正态, 以历史口径为准' : '尾部与正态近似接近'}。</p>` : ''}
            </div>
        </div>
        ${renderStress(p)}`;
    }

    function renderReplayChart(rp) {
        const path = rp.path || {};
        const a = path.current || [], b = path.after || [], d = path.dates || [];
        if (a.length < 2) return '';
        const all = a.concat(b);
        const lo = Math.min(...all), hi = Math.max(...all);
        const pad = (hi - lo) * 0.08 || 0.01;
        const y0 = lo - pad, y1 = hi + pad;
        const W = 600, H = 170;
        const X = (i) => (i / (a.length - 1)) * W;
        const Y = (v) => H - ((v - y0) / (y1 - y0)) * H;
        const line = (arr) => arr.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('');
        const base = Y(1);
        const pk = d.indexOf(rp.current?.mdd_peak_date), tr = d.indexOf(rp.current?.mdd_trough_date);
        // 回撤区间: 用最近的降采样点近似
        const near = (date) => { let k = 0; for (let i = 0; i < d.length; i++) if (d[i] <= date) k = i; return k; };
        const pi = pk >= 0 ? pk : near(rp.current?.mdd_peak_date || ''), ti = tr >= 0 ? tr : near(rp.current?.mdd_trough_date || '');
        const ticks = [y1 - pad, (y0 + y1) / 2, y0 + pad].map((v) =>
            `<span style="top:${(Y(v) / H * 100).toFixed(1)}%">${((v - 1) * 100).toFixed(0)}%</span>`).join('');
        return `
        <div class="vb-chart" data-vb-chart>
            <div class="vb-chart-y">${ticks}</div>
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
                ${ti > pi ? `<rect class="dd" x="${X(pi).toFixed(1)}" y="0" width="${(X(ti) - X(pi)).toFixed(1)}" height="${H}"></rect>` : ''}
                <line class="base" x1="0" x2="${W}" y1="${base.toFixed(1)}" y2="${base.toFixed(1)}"></line>
                <path class="cur" d="${line(a)}"></path>
                <path class="aft" d="${line(b)}"></path>
                <line class="cursor" x1="0" x2="0" y1="0" y2="${H}" style="display:none"></line>
            </svg>
            <div class="vb-chart-read" aria-live="polite"></div>
            <div class="vb-chart-x"><span>${esc(d[0])}</span><span>${esc(d[d.length - 1])}</span></div>
            <script type="application/json" class="vb-chart-data">${JSON.stringify({ d, a, b }).replace(/</g, '\\u003c')}</script>
        </div>
        <div class="vb-chart-legend">
            <span class="cur">当前持仓 ${pct(rp.current?.period_return_pct, 1)} · 回撤 ${pct(rp.current?.max_drawdown_pct, 1)}</span>
            <span class="aft">执行草案 ${pct(rp.after?.period_return_pct, 1)} · 回撤 ${pct(rp.after?.max_drawdown_pct, 1)}</span>
            <span class="dd">最大回撤区间</span>
        </div>`;
    }

    function renderStress(p) {
        const st = p.stress || [];
        if (!st.length) return '';
        const worst = Math.max(...st.map((x) => Math.abs(num(x.current_pct) || 0)), 1);
        const rows = st.map((x) => {
            const c = Math.abs(num(x.current_pct) || 0), a = Math.abs(num(x.after_pct) || 0);
            return `<tr>
                <td><div class="vb-strong">${esc(x.name)}</div><div class="vb-hint vb-tight">${esc(x.desc)}</div></td>
                <td class="vb-loss"><div class="vb-loss-t"><span class="c" style="width:${(c / worst * 100).toFixed(1)}%"></span>
                    <span class="a" style="width:${(a / worst * 100).toFixed(1)}%"></span></div></td>
                <td class="vb-r">${money(x.current_amt)}<div class="vb-hint vb-tight">${pct(x.current_pct, 1)}</div></td>
                <td class="vb-r vb-strong">${money(x.after_amt)}<div class="vb-hint vb-tight">${pct(x.after_pct, 1)}</div></td></tr>`;
        }).join('');
        return `
        <h4 class="vb-h">压力情景 <span>瞬时冲击 · β 线性近似 · 浅色 = 当前, 深色 = 执行草案后</span></h4>
        <div class="vb-table-wrap"><table class="vb-table">
            <thead><tr><th>情景</th><th>损失对比</th><th class="vb-r">当前</th><th class="vb-r">执行草案后</th></tr></thead>
            <tbody>${rows}</tbody></table></div>
        <p class="vb-hint">β 用 250 日数据估计; 缺行情的个股取同类中位数。未计入跌停无法止损带来的连锁损失。</p>`;
    }

    // ═══════════════════════════════════════════════
    //  页签: 执行草案
    // ═══════════════════════════════════════════════
    function renderExecution(v) {
        const p = v.portfolio || {};
        const plan = p.trim_plan || [];
        const tc = p.trim_compare || {};
        const liq = p.liquidity || {};
        const after = p.after_trim || {};
        if (!plan.length) {
            return `<div class="vb-empty">当前无需减仓。${renderDiversifiers(p)}</div>`;
        }
        const rec = tc.recommended;
        const mRow = (key, label) => {
            const m = tc[key] || {};
            return `<tr class="${rec === key ? 'vb-rec' : ''}"><td>${label}${rec === key ? '<span class="vb-rec-tag">推荐</span>' : ''}</td>
                <td class="vb-r">${money(m.turnover_amt)}</td><td class="vb-r">${pct(m.invested_pct, 1)}</td>
                <td class="vb-r">${fx(m.effective_bets)}</td><td class="vb-r">${pct(m.max_weight_pct, 1)}</td><td class="vb-r">${rpct(m.top3_risk_share)}</td></tr>`;
        };
        const maxCut = Math.max(...plan.map((t) => num(t.reduce_amount) || 0), 1);
        const rows = plan.map((t) => {
            const capPart = Math.min(num(t.cap_part_amount) || 0, num(t.reduce_amount) || 0);
            const rest = (num(t.reduce_amount) || 0) - capPart;
            return `<tr><td class="vb-name">${esc(t.name)}<span class="vb-code">${esc(t.ts_code)}</span>${t.vol_source === 'proxy' ? '<span class="vb-flag">估</span>' : ''}</td>
                <td class="vb-r">${pct(t.from_pct, 1)} → <b>${pct(t.to_pct, 1)}</b></td>
                <td class="vb-r">${rpct(t.mcr)}</td>
                <td class="vb-cut" title="压单票上限 ${money(capPart)} · 降总仓位 ${money(rest)}">
                    <div class="vb-cut-t"><span class="cap" style="width:${(capPart / maxCut * 100).toFixed(1)}%"></span><span class="lvl" style="width:${(rest / maxCut * 100).toFixed(1)}%"></span></div></td>
                <td class="vb-r">${money(-t.reduce_amount)}</td>
                <td class="vb-r vb-dim">${t.adv_participation_pct == null ? '--' : fx(t.adv_participation_pct, 2) + '%'}</td></tr>`;
        }).join('');
        const liqTxt = liq.covered
            ? `单笔最多占 20 日成交额 ${fx(liq.max_participation_pct, 2)}%, 按 ${Math.round((liq.participation_rate || 0.1) * 100)}% 参与率均可当日完成 (${liq.covered}/${liq.total} 只有成交额数据)`
            : '缺少成交额数据';
        return `
        <div class="vb-exec-sum">
            <div><span>合计减仓</span><b>${money(after.total_reduce_amount)}</b></div>
            <div><span>执行后仓位</span><b>${pct(after.invested_pct, 1)}</b></div>
            <div><span>执行后波动</span><b>${rpct(after.portfolio_vol, 1)}</b></div>
            <div><span>流动性</span><b>${liq.covered ? fx(liq.max_participation_pct, 2) + '%' : '--'}</b><em>最大成交额占比</em></div>
        </div>
        <h4 class="vb-h">两种草案 <span>${esc(tc.rule || '')} · 本次最小换手少交易 ${fx(tc.saving_pct, 1)}%</span></h4>
        <div class="vb-table-wrap"><table class="vb-table vb-compact">
            <thead><tr><th>方案</th><th class="vb-r">换手</th><th class="vb-r">执行后仓位</th><th class="vb-r">独立押注</th><th class="vb-r">最大单票</th><th class="vb-r">前三风险</th></tr></thead>
            <tbody>${mRow('proportional', '等比缩放 · 保持结构')}${mRow('min_turnover', '最小换手 · 先卖边际风险最高')}</tbody></table></div>
        <h4 class="vb-h">逐笔草案 (推荐方案) <span><i class="vb-sw cap"></i>压到单票上限 <i class="vb-sw lvl"></i>降总仓位</span></h4>
        <div class="vb-table-wrap"><table class="vb-table">
            <thead><tr><th>持仓</th><th class="vb-r">权重</th><th class="vb-r" title="每单位权重对组合波动的边际贡献">边际风险</th><th>构成</th>
                <th class="vb-r">减仓金额</th><th class="vb-r">占成交额</th></tr></thead>
            <tbody>${rows}</tbody></table></div>
        <p class="vb-hint">流动性: ${esc(liqTxt)} — 约束在纪律, 不在流动性。执行: 分 3–5 个交易日、固定时段下单, 先做超单票上限部分; 盘中不临时改单。本面板只读, 不下单。</p>
        ${renderDiversifiers(p)}`;
    }

    function renderDiversifiers(p) {
        const ds = p.diversifiers || [];
        if (!ds.length) return '';
        const cards = ds.map((d) => {
            const fr = (d.frontier || []).map((f, i) => `
                <li class="${i === 1 ? 'pick' : ''}"><span>主题 ${pct(f.theme_pct)}</span><b>+${pct(f.add_pct)}</b><em>总 ${pct(f.total_pct)}</em></li>`).join('');
            return `<div class="vb-div">
                <div class="vb-div-h"><span class="vb-strong">${esc(d.name)}</span><span class="vb-code">${esc(d.ts_code)}</span>
                    <span class="vb-div-m">σ ${rpct(d.vol)} · 样本相关 ${fx(d.corr_to_portfolio)}${d.short_sample ? ' <span class="vb-flag" title="样本不足 250 日">样本短</span>' : ''}</span></div>
                <ul class="vb-front">${fr}</ul></div>`;
        }).join('');
        return `
        <h4 class="vb-h">风险预算再利用 <span>同样 ${rpct(p.target_vol)} 目标波动下, 主题仓位与低相关资产的权衡</span></h4>
        <div class="vb-divs">${cards}</div>
        <p class="vb-hint">降风险 ≠ 全部换成现金。可配仓位按压力相关 max(样本, ${fx(ds[0]?.stress_corr_floor)}) 计算: 危机时相关性上升, 不用短样本的负相关放大规模。仅为测算, 不构成买入建议。</p>`;
    }

    // ═══════════════════════════════════════════════
    //  页签: 方法与数据
    // ═══════════════════════════════════════════════
    function renderData(v) {
        const p = v.portfolio || {};
        const dq = p.data_quality || {};
        const meta = p.meta || {};
        const cav = (v.caveats || []).map((c) => `<li>${esc(c)}</li>`).join('');
        const meth = (v.method || []).map((c) => `<li>${esc(c)}</li>`).join('');
        const kv = (k, val) => `<div><dt>${k}</dt><dd>${val}</dd></div>`;
        return `
        <div class="vb-cols">
            <div>
                ${cav ? `<h4 class="vb-h warn">使用前须知</h4><ul class="vb-list warn">${cav}</ul>` : ''}
                <h4 class="vb-h">数据质量</h4>
                <dl class="vb-dl">
                    ${kv('行情覆盖', `${fx(dq.coverage_pct, 0)}% 权重`)}
                    ${kv('代理波动', dq.proxy_names?.length ? esc(dq.proxy_names.join('、')) : '无')}
                    ${kv('行情过期', dq.stale_names?.length ? esc(dq.stale_names.join('、')) : '无')}
                    ${kv('行情日期', `${esc(dq.oldest_price_date || '--')} ~ ${esc(dq.price_asof || '--')}`)}
                    ${kv('最短样本', `${dq.min_obs || '--'} 日`)}
                    ${kv('持仓快照', `${esc(p.as_of || '--')}${dq.positions_age_days != null ? ` (${dq.positions_age_days} 天前)` : ''}`)}
                </dl>
            </div>
            <div>
                <h4 class="vb-h">方法</h4><ul class="vb-list">${meth}</ul>
                <h4 class="vb-h">审计</h4>
                <dl class="vb-dl mono">
                    ${kv('schema', esc(meta.schema || v.schema || '--'))}
                    ${kv('指纹', esc(meta.fingerprint || '--'))}
                    ${kv('计算于', esc(meta.computed_at || '--'))}
                    ${kv('耗时', meta.elapsed_ms != null ? `${meta.elapsed_ms} ms${meta.cache === 'hit' ? ' (缓存命中)' : ''}` : '--')}
                </dl>
            </div>
        </div>`;
    }

    // ═══════════════════════════════════════════════
    //  组装 + 交互
    // ═══════════════════════════════════════════════
    const TAB_RENDER = { overview: renderOverview, attribution: renderAttribution, tail: renderTail, execution: renderExecution, data: renderData };

    function tabBadge(k, v) {
        const p = v.portfolio || {};
        if (k === 'attribution' && num(p.breach_count)) return `<em class="danger">${p.breach_count}</em>`;
        if (k === 'execution' && (p.trim_plan || []).length) return `<em>${p.trim_plan.length}</em>`;
        if (k === 'data' && (v.caveats || []).length) return `<em class="warning">${v.caveats.length}</em>`;
        return '';
    }

    function render($body) {
        const v = state.view;
        if (!v) return;
        const tabs = TABS.map(([k, label]) => `
            <button type="button" role="tab" id="vb-tab-${k}" aria-controls="vb-pane" aria-selected="${k === state.tab}"
                tabindex="${k === state.tab ? 0 : -1}" class="vb-tab ${k === state.tab ? 'on' : ''}" data-vb-tab="${k}">${label}${tabBadge(k, v)}</button>`).join('');
        $body.innerHTML = `
            ${renderStrip(v)}
            ${renderRuler(v)}
            <nav class="vb-tabs" role="tablist" aria-label="波动预算视图">${tabs}</nav>
            <div class="vb-pane" id="vb-pane" role="tabpanel" aria-labelledby="vb-tab-${state.tab}">${TAB_RENDER[state.tab](v)}</div>`;
        $body.classList.toggle('vb-busy', state.loading);
        bindChart($body);
    }

    function bindChart($body) {
        const box = $body.querySelector('[data-vb-chart]');
        if (!box) return;
        let data;
        try { data = JSON.parse(box.querySelector('.vb-chart-data').textContent); } catch (e) { return; }
        const svg = box.querySelector('svg'), cursor = svg.querySelector('.cursor'), read = box.querySelector('.vb-chart-read');
        const n = data.a.length;
        const show = (clientX) => {
            const rect = svg.getBoundingClientRect();
            const i = clamp(Math.round((clientX - rect.left) / rect.width * (n - 1)), 0, n - 1);
            const x = i / (n - 1) * 600;
            cursor.setAttribute('x1', x); cursor.setAttribute('x2', x); cursor.style.display = '';
            read.innerHTML = `<b>${esc(data.d[i])}</b> 当前 <span class="cur">${((data.a[i] - 1) * 100).toFixed(1)}%</span> · 草案 <span class="aft">${((data.b[i] - 1) * 100).toFixed(1)}%</span>`;
            read.style.left = `${clamp(i / (n - 1) * 100, 12, 78)}%`;
            read.classList.add('on');
        };
        svg.addEventListener('pointermove', (e) => show(e.clientX));
        svg.addEventListener('pointerleave', () => { cursor.style.display = 'none'; read.classList.remove('on'); });
    }

    function bindEvents($body) {
        if ($body.dataset.vbBound) return;
        $body.dataset.vbBound = '1';
        $body.addEventListener('click', (e) => {
            const t = e.target.closest('[data-vb-tab],[data-vb-sort],[data-vb-action]');
            if (!t) return;
            if (t.dataset.vbTab) { state.tab = t.dataset.vbTab; writeTab(state.tab); render($body); $body.querySelector(`#vb-tab-${state.tab}`)?.focus(); }
            else if (t.dataset.vbSort) { state.sort = t.dataset.vbSort; render($body); }
            else if (t.dataset.vbAction === 'expand') { state.expanded = !state.expanded; render($body); }
            else if (t.dataset.vbAction === 'refresh') { loadVolBudgetPanel({ refresh: true }); }
        });
        $body.addEventListener('keydown', (e) => {
            const t = e.target.closest('[data-vb-tab]');
            if (!t || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
            e.preventDefault();
            const i = TABS.findIndex(([k]) => k === state.tab);
            const j = e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length;
            state.tab = TABS[j][0]; writeTab(state.tab); render($body);
            $body.querySelector(`#vb-tab-${state.tab}`)?.focus();
        });
    }

    function renderSummary($summary, v) {
        if (!$summary) return;
        const lv = LEVEL[v.verdict?.level] || LEVEL.unknown;
        const p = v.portfolio || {};
        $summary.innerHTML = `<span class="vb-badge sm ${lv.cls}"><i></i>${lv.tag}</span>
            有效上限 <b>${pct(v.effective_cap_pct)}</b> · 实际 <b>${pct(v.actual_pct)}</b>
            · 波动 <b>${rpct(p.portfolio_vol)}</b>/${rpct(p.target_vol)}
            · 约束: ${esc(v.verdict?.binding_label || '—')}`;
    }

    async function loadVolBudgetPanel(opts = {}) {
        const $panel = document.getElementById('vol-budget-panel');
        const $body = document.getElementById('vb-body');
        const $summary = document.getElementById('vb-summary');
        if (!$panel || !$body || state.loading) return;
        bindEvents($body);
        state.loading = true;
        if (state.view) render($body);
        else $body.innerHTML = '<div class="vb-loading" role="status"><span class="vb-spin"></span>计算组合波动与约束…</div>';
        try {
            const resp = await doFetch(opts.refresh ? `${API}?refresh=true` : API);
            const raw = await resp.json();
            const v = raw?.data ?? raw;
            if (raw?.status !== 'success' || !v || (v.status === 'insufficient' && !v.portfolio)) {
                throw new Error(raw?.message || '数据不足');
            }
            state.view = v;
            state.loading = false;
            $panel.dataset.level = (LEVEL[v.verdict?.level] || LEVEL.unknown).cls;
            renderSummary($summary, v);
            render($body);
        } catch (e) {
            state.loading = false;
            console.warn('[VolBudget] load failed:', e);
            if (state.view) {                      // 刷新失败: 保留上一次结果, 只提示
                render($body);
                $body.insertAdjacentHTML('afterbegin', `<div class="vb-alert" role="alert">重算失败, 显示的是上一次结果: ${esc(e.message)}</div>`);
                return;
            }
            if ($summary) $summary.textContent = '暂不可用';
            $body.innerHTML = `<div class="vb-empty">波动预算暂不可用: ${esc(e.message)}。确认持仓已导入、服务已完成预热后刷新。</div>`;
        }
    }

    window.loadVolBudgetPanel = loadVolBudgetPanel;
    document.addEventListener('DOMContentLoaded', () => setTimeout(loadVolBudgetPanel, 600));
})();
