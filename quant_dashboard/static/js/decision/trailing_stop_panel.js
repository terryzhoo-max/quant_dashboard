/**
 * AlphaCore · 持仓跟踪止盈 · 执行闭环面板
 * decision/trailing_stop_panel.js · v2
 *
 * 信息层次 (机构风控视角: 先结论, 再行动, 再证据):
 *   ① 结论条     一句话: 下一交易日开盘前要处理什么 + 数据血缘 (收盘日 / 日终提交 / 环境 / 参数版本)
 *   ② 风险读数   已越线占比 · 组合热度 vs 上限 · 有效独立押注 · 执行纪律
 *   ③ 行动队列   EXIT > DECIDE > TRIM > RESIZE/集中度 > 再入场 > 数据 (按优先级, 每项可直接操作)
 *   ④ 持仓       按状态分组; 每行 60 日走势 + 止损线路径 + 距离条 + 阶段 + 风险
 *   ⑤ 明细页签   日间变化 · 条件单 · 再入场 · 亏损加仓 · 回合复盘 · 审计 · 方法与数据
 *
 * 数据源: GET /api/v1/portfolio/trailing-stops (只读; 新收盘未提交时服务端自动补跑日终)
 * 原则:   规则先于判断; 收盘确认、次日执行; 人工推翻必须写理由并留痕。
 */
(function () {
    'use strict';

    const BASE = '/api/v1/portfolio';
    const ST = {
        RED:     { cls: 'red',    tag: '已触发',   order: 0, group: '已触发 · 次日开盘卖出' },
        LEGACY:  { cls: 'legacy', tag: '遗留待决', order: 1, group: '遗留待决 · 跟踪前已越线' },
        ACTION:  { cls: 'action', tag: '分批止盈', order: 2, group: '分批止盈待执行' },
        YELLOW:  { cls: 'yellow', tag: '临近',     order: 3, group: '临近止损线 (< 0.5 ATR)' },
        GREEN:   { cls: 'green',  tag: '持有',     order: 4, group: '正常持有' },
        NO_DATA: { cls: 'nodata', tag: '无行情',   order: 5, group: '行情缺失' },
    };
    const ACT = {
        EXIT: ['red', '卖出'], DECIDE: ['legacy', '决策'], TRIM: ['action', '止盈'], RESIZE: ['amber', '减仓'],
        HEAT: ['amber', '热度'], CONCENTRATION: ['amber', '集中度'], REENTRY: ['blue', '再入场'],
        IMPORT: ['muted', '数据'], SYNC: ['muted', '数据'], DRAWDOWN: ['red', '回撤'], DD_BUDGET: ['amber', '预算'],
        RESTATE: ['muted', '重述'],
    };
    const ANCHOR = {
        exact: '台账精确', pre_window: '早于台账', approx: '近似', rebaselined: '已重设',
        unknown: '快照日', no_history: '无台账', inferred_cost: '成本反推', manual: '人工设定',
    };
    const CLS = { stock: '个股', theme_etf: '主题', broad_etf: '宽基' };
    const TABS = [
        ['changes', '日间变化'], ['orders', '条件单'], ['reentry', '再入场'], ['adds', '亏损加仓'],
        ['review', '回合复盘'], ['audit', '审计日志'], ['method', '方法与数据'],
    ];

    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const num = (v) => (v == null || v === '' || isNaN(v)) ? null : Number(v);
    const fx = (v, d = 2) => num(v) == null ? '--' : Number(v).toFixed(d);
    const pct = (v, d = 1) => num(v) == null ? '--' : `${(Number(v) * 100).toFixed(d)}%`;
    const spct = (v, d = 1) => num(v) == null ? '--' : `${v > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`;
    const isEtf = (code) => /^(1|5)/.test(code || '');
    const px = (v, code) => num(v) == null ? '--' : Number(v).toFixed(isEtf(code) ? 3 : 2);
    const money = (v) => {
        const n = num(v);
        if (n == null) return '--';
        return Math.abs(n) >= 10000 ? `${(n / 10000).toFixed(1)}万` : Math.round(n).toLocaleString();
    };
    const api = (url, opt) => (window.AC && typeof AC.secureFetch === 'function') ? AC.secureFetch(url, opt) : fetch(url, opt);
    const postJson = (url, body) => api(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    }).then((r) => r.json());
    const store = {
        get: (k, dflt) => { try { return localStorage.getItem(k) ?? dflt; } catch (_) { return dflt; } },
        set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* 私有模式 */ } },
    };

    let _last = null;
    let _autoRefreshed = false;
    let _tab = store.get('ts_tab', 'changes');
    let _reviewCache = null;

    // ═══════════════ ① 结论条 ═══════════════
    function verdict(d) {
        const acts = d.actions || [];
        const s = d.summary || {};
        const h = d.heat || {};
        const urgent = acts.filter((a) => a.priority <= 3);
        let level = 'ok';
        let text = '全部持仓在止损线内, 按收盘确认规则继续持有';
        const bk = d.drawdown?.brake || {};
        if (s.RED) { level = 'red'; text = `${s.RED} 只已触发止损, 规则要求下一交易日开盘卖出`; }
        else if (bk.tier) {
            level = bk.tier >= 2 ? 'red' : 'legacy';
            text = `组合净值回撤 ${pct(Math.abs(bk.dd))} · ${bk.label}${bk.reduce_value ? `, 需降仓约 ${money(bk.reduce_value)}` : ''}; 回撤恢复前禁止加仓`
                + (s.LEGACY ? `; 另有 ${s.LEGACY} 只遗留越线待决` : '');
        } else if (s.LEGACY) {
            level = 'legacy';
            text = `${s.LEGACY} 只持仓在系统跟踪前已越过止损线 (占总资产 ${pct(h.breached_pct, 0)}), 需在下一交易日开盘前逐只决策`;
        } else if (s.ACTION) { level = 'action'; text = `${s.ACTION} 只进入分批止盈, 卖出约 1/3 锁定利润`; }
        else if (acts.length) { level = 'amber'; text = acts[0].title; }
        const eod = d.eod || {};
        const meta = d.meta || {};
        const prov = [
            `收盘 ${esc(d.as_of || '--')}`,
            eod.committed_now ? '刚完成日终提交' : (eod.last_as_of === d.as_of ? '日终已提交' : '日终未提交'),
            `环境 ${esc(d.regime || '--')}`,
            `参数 ${esc(meta.config_hash || '--')}`,
        ].join(' · ');
        return `
        <div class="ts-verdict ${level}">
            <div class="ts-verdict-main">
                <div class="ts-verdict-kicker">${urgent.length ? `下一交易日开盘前 · ${urgent.length} 项待处理` : '今日结论'}</div>
                <div class="ts-verdict-text">${esc(text)}</div>
                <div class="ts-verdict-prov">${prov}</div>
            </div>
            <div class="ts-verdict-tools">
                <button class="ts-icon-btn" data-act="import" title="导入通达信历史成交 (可多选, 自动去重)">导入成交</button>
                <button class="ts-icon-btn" data-act="scan" title="扫描 data_lake/trade_imports 文件夹">扫描文件夹</button>
                <button class="ts-icon-btn" data-act="run" title="同步行情 + 重算 + 日终提交 + 推送">同步并重算</button>
                <input type="file" id="ts-file" accept=".txt,.csv,.xls,.tsv" multiple hidden>
            </div>
        </div>`;
    }

    // ═══════════════ ② 风险读数 ═══════════════
    function meter(value, limit, max) {
        const v = Math.max(0, Math.min(1, (num(value) || 0) / max));
        const l = limit == null ? null : Math.max(0, Math.min(1, limit / max));
        return `<div class="ts-meter"><i style="width:${(v * 100).toFixed(1)}%"></i>${l == null ? '' : `<b style="left:${(l * 100).toFixed(1)}%"></b>`}</div>`;
    }

    function kpis(d) {
        const h = d.heat || {};
        const c = d.correlation || {};
        const disc = d.discipline || {};
        const ad = d.averaging_down || {};
        const breachCls = (h.breached_pct || 0) > 0.2 ? 'bad' : (h.breached_pct || 0) > 0 ? 'warn' : '';
        const heatCls = h.over_limit ? 'bad' : (h.heat_pct || 0) > (h.limit_pct || 1) * 0.75 ? 'warn' : '';
        const neffCls = c.n_eff != null && c.n_eff < 2 ? 'bad' : c.n_eff != null && c.n_eff < 4 ? 'warn' : '';
        const bk = d.drawdown?.brake;
        const tiers = d.drawdown?.policy?.tiers || [];
        const ddMax = (tiers[tiers.length - 1]?.dd || 0.28) * 1.25;
        const ddCard = bk ? `
            <button class="ts-kpi ts-kpi-dd ${bk.tier >= 2 ? 'bad' : bk.tier ? 'warn' : ''}" data-act="goto-dd" title="查看组合回撤">
                <span>组合回撤 · ${bk.tier ? `${bk.tier} 档` : '未触发'}</span><b>−${pct(Math.abs(bk.dd || 0))}</b>
                <div class="ts-meter ts-meter-dd"><i style="width:${Math.min(100, Math.abs(bk.dd || 0) / ddMax * 100).toFixed(1)}%"></i>${tiers.map((t) => `<b style="left:${(t.dd / ddMax * 100).toFixed(1)}%"></b>`).join('')}</div>
                <em>仓位上限 ${bk.cap_pct}% · 当前 ${bk.invested_pct ?? '--'}%</em>
            </button>` : '';
        return `
        <div class="ts-kpis ${bk ? 'has-dd' : ''}">${ddCard}
            <div class="ts-kpi ${breachCls}">
                <span>已越过止损线</span><b>${pct(h.breached_pct, 0)}</b>
                ${meter(h.breached_pct, null, 1)}
                <em>${money(h.breached_market_value)} / 总资产 ${money(d.equity)}</em>
            </div>
            <div class="ts-kpi ${heatCls}">
                <span>组合热度</span><b>${pct(h.heat_pct)}</b>
                ${meter(h.heat_pct, h.limit_pct, Math.max(0.2, (h.limit_pct || 0.12) * 1.6))}
                <em>所有持仓同时打到止损线的亏损 · 上限 ${pct(h.limit_pct, 0)}</em>
            </div>
            <div class="ts-kpi ${neffCls}">
                <span>有效独立押注</span><b>${c.n_eff == null ? '--' : fx(c.n_eff, 1)}<small> / ${c.n ?? '--'} 只</small></b>
                ${meter(c.avg_corr, null, 1)}
                <em>60 日市值加权平均相关 ${c.avg_corr == null ? '--' : fx(c.avg_corr, 2)}</em>
            </div>
            <div class="ts-kpi ${ad.after_breach_count ? 'bad' : ad.count ? 'warn' : ''}">
                <span>执行纪律</span><b>${disc.score == null ? '—' : `${disc.score}分`}</b>
                <div class="ts-kpi-sub">亏损加仓 ${ad.count || 0} 笔 · ${money(ad.amount)}${ad.after_breach_count ? ` · <i>越线后 ${ad.after_breach_count} 笔</i>` : ''}</div>
                <em>${disc.score == null ? '跟踪期内尚无触发事件' : `按时 ${disc.on_time} · 逾期 ${disc.overdue} · 推翻 ${disc.overridden}`}</em>
            </div>
        </div>`;
    }

    // ═══════════════ ③ 行动队列 ═══════════════
    function actionButtons(a) {
        const code = esc(a.ts_code || '');
        if (a.type === 'DECIDE') {
            return `<button class="ts-mini warn" data-act="rebaseline" data-code="${code}">保留 · 重新承保</button>
                    <button class="ts-mini ghost" data-act="goto" data-code="${code}">查看走势</button>`;
        }
        if (a.type === 'TRIM') return `<button class="ts-mini" data-act="ack" data-code="${code}" data-stage="2">已在台账外执行</button>`;
        if (a.type === 'IMPORT') return '<button class="ts-mini" data-act="import">导入成交</button>';
        if (a.type === 'SYNC') return '<button class="ts-mini" data-act="run">同步行情</button>';
        if (a.type === 'DRAWDOWN') return '<button class="ts-mini ghost" data-act="goto-dd">查看回撤</button>';
        if (a.ts_code) return `<button class="ts-mini ghost" data-act="goto" data-code="${code}">查看</button>`;
        return '';
    }

    function actions(d) {
        const list = d.actions || [];
        if (!list.length) {
            return '<div class="ts-block"><div class="ts-block-title">行动队列</div><div class="ts-empty">无待办 · 按规则继续持有</div></div>';
        }
        const items = list.map((a, i) => {
            const [cls, tag] = ACT[a.type] || ['muted', a.type];
            return `
            <div class="ts-act ${cls}">
                <div class="ts-act-rank">${i + 1}</div>
                <span class="ts-act-tag ${cls}">${esc(tag)}</span>
                <div class="ts-act-body">
                    <div class="ts-act-title">${esc(a.title)}${a.value ? `<span class="ts-act-val">${money(a.value)}</span>` : ''}</div>
                    <div class="ts-act-detail">${esc(a.detail || '')}</div>
                </div>
                <div class="ts-act-ops">${actionButtons(a)}</div>
            </div>`;
        }).join('');
        return `<div class="ts-block"><div class="ts-block-title">行动队列 <em>按优先级 · 规则要求的先于判断类的</em></div>
            <div class="ts-acts">${items}</div></div>`;
    }

    // ═══════════════ ③b 组合回撤 (MDD) ═══════════════
    const TIER_CLS = ['ok', 'warm', 'hot', 'hot'];

    // 双联图: 上 = 净值与高水位; 下 = 水下曲线 (自高点回撤), 档位为水平色带 —— 档位线是常数, 不随高水位漂移, 一眼读出离下一档多远
    // 按容器实际像素宽度绘制 (viewBox = 像素), 文字不被拉伸; 尺寸变化时重绘
    function ddChart(dd, width) {
        const c = dd.curve;
        if (!c || !c.nav || c.nav.length < 2) return '<div class="ts-empty">台账覆盖期不足两个交易日, 暂无净值曲线</div>';
        const tiers = dd.policy?.tiers || [];
        const n = c.nav.length;
        const W = Math.max(280, Math.round(width || 600)), L = 40, R = W < 420 ? 54 : 66;
        const T1 = 18, H1 = 60;                // 净值面板 (标题在面板上方, 不压线)
        const T2 = T1 + H1 + 24, H2 = 112;     // 水下面板
        const H = T2 + H2 + 20;
        const X = (i) => L + (i / (n - 1)) * (W - L - R);
        const lo1 = Math.min(...c.nav) * 0.995, hi1 = Math.max(...c.hwm) * 1.005;
        const Y1 = (v) => T1 + (1 - (v - lo1) / (hi1 - lo1)) * H1;
        const uw = c.nav.map((v, i) => v / c.hwm[i] - 1);
        const deepest = Math.min(...uw);
        const floor = Math.min(deepest - 0.02, -((tiers[tiers.length - 1]?.dd || 0.28) + 0.04));
        const Y2 = (v) => T2 + (v / floor) * H2;
        const line = (arr, Y) => arr.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('');
        const edges = [0].concat(tiers.map((t) => -t.dd), [floor]);
        const bands = edges.slice(0, -1).map((top, k) => {
            const y0 = Y2(top), y1 = Y2(Math.max(edges[k + 1], floor));
            const lbl = k === 0 ? '正常' : `${k} 档 ≤${tiers[k - 1].cap}%`;
            return `<rect x="${L}" y="${y0.toFixed(1)}" width="${W - L - R}" height="${Math.max(0, y1 - y0).toFixed(1)}" class="ts-dd-band b${k}"/>
                ${k ? `<line x1="${L}" x2="${W - R}" y1="${y0.toFixed(1)}" y2="${y0.toFixed(1)}" class="ts-dd-bandline b${k}"/>
                <text x="${W - R + 6}" y="${(y0 + 10).toFixed(1)}" class="ts-dd-blabel b${k}">−${Math.round(tiers[k - 1].dd * 100)}%</text>
                <text x="${W - R + 6}" y="${(y0 + 21).toFixed(1)}" class="ts-dd-blabel sub b${k}">${lbl}</text>` : ''}`;
        }).join('');
        const uwArea = `${line(uw, Y2)}L${X(n - 1).toFixed(1)},${Y2(0).toFixed(1)}L${X(0).toFixed(1)},${Y2(0).toFixed(1)}Z`;
        const ev = (dd.brake?.events || []).map((e) => {
            const i = c.d.indexOf((e.date || '').slice(5));
            if (i < 0) return '';
            return `<g class="ts-dd-ev ${e.dir}"><line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${T1}" y2="${(T2 + H2).toFixed(1)}"/>
                <circle cx="${X(i).toFixed(1)}" cy="${Y2(uw[i]).toFixed(1)}" r="3.5"><title>${esc(e.date)} 回撤 ${pct(Math.abs(e.dd))} → ${e.to} 档</title></circle></g>`;
        }).join('');
        const last = uw[n - 1];
        const xl = [0, Math.floor((n - 1) / 2), n - 1].map((i) => `<text x="${X(i).toFixed(1)}" y="${H - 5}" class="ts-dd-axis" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${esc(c.d[i])}</text>`).join('');
        const yl = `<text x="${L - 6}" y="${(Y1(c.hwm[n - 1]) + 3).toFixed(1)}" class="ts-dd-axis" text-anchor="end">${fx(c.hwm[n - 1], 3)}</text>
            <text x="${L - 6}" y="${(Y2(0) + 3).toFixed(1)}" class="ts-dd-axis" text-anchor="end">0%</text>`;
        return `<svg class="ts-dd-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
                aria-label="组合净值与水下回撤曲线, 当前回撤 ${pct(Math.abs(last))}">
            <text x="${L}" y="${T1 - 8}" class="ts-dd-ptitle">净值 / 高水位</text>
            <path d="${line(c.hwm, Y1)}" class="ts-dd-hwm"/><path d="${line(c.nav, Y1)}" class="ts-dd-nav"/>
            <text x="${L}" y="${T2 - 8}" class="ts-dd-ptitle">水下曲线 · 自高点回撤</text>
            ${bands}<path d="${uwArea}" class="ts-dd-uw"/><path d="${line(uw, Y2)}" class="ts-dd-uwline"/>
            ${ev}${yl}${xl}
            <circle cx="${X(n - 1).toFixed(1)}" cy="${Y2(last).toFixed(1)}" r="3.5" class="ts-dd-last"/>
            <text x="${(X(n - 1) - 6).toFixed(1)}" y="${(Y2(last) + 15).toFixed(1)}" class="ts-dd-now" text-anchor="end">${pct(last)}</text>
        </svg>`;
    }

    function ddLadder(dd) {
        const b = dd.brake || {};
        const tiers = dd.policy?.tiers || [];
        const cur = Math.abs(b.dd || 0);
        const rows = [{ dd: 0, cap: 100 }].concat(tiers).map((t, k) => {
            const on = (b.tier || 0) === k;
            return `<li class="ts-dd-step ${on ? 'on' : ''} t${k}" ${on ? 'aria-current="step"' : ''}>
                <span class="ts-dd-step-k">${k} 档</span>
                <span class="ts-dd-step-trig">${k ? `回撤 ≥ ${Math.round(t.dd * 100)}%` : `回撤 < ${Math.round((tiers[0]?.dd || 0) * 100)}%`}</span>
                <span class="ts-dd-step-cap">≤ ${t.cap}%</span>
                ${on ? `<i>当前 −${(cur * 100).toFixed(1)}%${k ? ' · 禁止加仓' : ''}</i>` : ''}</li>`;
        }).join('');
        const tail = b.tier
            ? `回撤收窄到 ${pct(Math.abs(b.rerisk_at_dd || 0))} 以内 (收复谷底以来 ${Math.round((dd.policy?.rerisk_recover || 0.5) * 100)}%) 回到 ${b.tier - 1} 档${b.next_trigger_dd ? `; 跌至 −${Math.round(Math.abs(b.next_trigger_dd) * 100)}% 进入 ${b.tier + 1} 档` : ''}`
            : (tiers[0] ? `距一档触发还有 ${pct(Math.max(0, tiers[0].dd - cur))}` : '');
        return `<ol class="ts-dd-ladder" aria-label="刹车档位">${rows}</ol><div class="ts-dd-note">${esc(tail)}</div>`;
    }

    function ddProgress(b) {
        const pg = b.progress;
        if (!pg) return '';
        const p = Math.max(0, Math.min(1, pg.pct || 0));
        const viol = pg.violation_count
            ? `<div class="ts-dd-viol bad">⚠ 刹车生效后仍买入 ${pg.violation_count} 笔 · ${money(pg.violation_amount)}</div>`
            : pg.pre_live_buys
                ? `<div class="ts-dd-viol">回放: 若刹车自 ${esc(pg.since)} 已启用, 其后 ${pg.pre_live_buys} 笔加仓 (${money(pg.pre_live_amount)}) 本会被拦截</div>`
                : '';
        return `<div class="ts-dd-progress">
            <div class="ts-dd-progress-head"><span>刹车执行 · 自 ${esc(pg.since)}</span><b>${pct(p, 0)}</b></div>
            <div class="ts-dd-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(p * 100)}"><i style="width:${(p * 100).toFixed(1)}%"></i></div>
            <div class="ts-dd-progress-sub">已净卖出 ${money(pg.executed)} · 剩余 ${money(pg.remaining)}</div>${viol}</div>`;
    }

    function ddPlan(p) {
        if (!p || !(p.items || []).length) return '';
        const STEP = { 1: ['red', '已触发'], 2: ['legacy', '遗留越线'], 3: ['amber', '超预算'], 4: ['muted', '等比'] };
        const rows = p.items.map((i) => {
            const [cls, tag] = STEP[i.step] || ['muted', ''];
            return `<tr><td><span class="ts-act-tag ${cls}">${tag}</span></td>
                <td><b>${esc(i.name)}</b> <span class="ts-muted">${esc(i.ts_code)}</span></td>
                <td class="ts-num">${Number(i.qty).toLocaleString()}</td><td class="ts-num">${px(i.price, i.ts_code)}</td>
                <td class="ts-num">${money(i.value)}</td><td class="ts-num">${i.remaining_qty ? Number(i.remaining_qty).toLocaleString() : '清仓'}</td>
                <td class="ts-dd-why">${esc(i.reason)}</td></tr>`;
        }).join('');
        const open = store.get('ts_dd_plan', '1') === '1';
        return `<details class="ts-dd-plan" ${open ? 'open' : ''} data-store="ts_dd_plan">
            <summary class="ts-dd-plan-head"><b>降仓清单 · ${p.items.length} 笔</b><span>合计 ${money(p.total)} / 需 ${money(p.target)} · 执行后仓位约 ${p.after_invested_pct ?? '--'}%</span>
                <button class="ts-mini ghost" data-act="copy-plan">复制清单</button></summary>
            <div class="ts-table-wrap"><table class="ts-table compact ts-dd-plan-table"><thead><tr><th>依据</th><th>标的</th><th>卖出</th><th>参考价</th><th>金额</th><th>剩余</th><th>说明</th></tr></thead>
            <tbody>${rows}</tbody></table></div>
            <div class="ts-muted">${esc(p.note || '')}</div></details>`;
    }

    function drawdownBlock(d) {
        const dd = d.drawdown;
        if (!dd || dd.status !== 'ok') {
            return dd ? `<section class="ts-block ts-dd" id="ts-dd"><div class="ts-block-title">组合回撤 (MDD)</div><div class="ts-banner ${dd.status === 'error' ? 'err' : 'info'}">${esc(dd.error || '缺少行情, 暂无法计算组合净值')}</div></section>` : '';
        }
        const b = dd.brake || {};
        const re = dd.realized || {};
        const pf = dd.proforma || {};
        const fc = dd.forecast || {};
        const prob = fc.prob || {};
        const lastTier = (dd.policy?.tiers || []).slice(-1)[0];
        const inv = num(b.invested_pct);
        const mx = num(fc.max_exposure_for_budget);
        const cell = (cls, k, v, sub) => `<div class="ts-dd-cell ${cls}"><span>${k}</span><b>${v}</b><em>${sub}</em></div>`;
        const base = dd.baseline;
        const pxy = re.proxy || {};
        const fa = fc.assumptions || {};
        const tcls = TIER_CLS[b.tier || 0] || 'hot';
        const notes = [];
        if ((pxy.codes || []).length) {
            notes.push(`ⓘ ${pxy.codes.length} 只已清仓标的本地无行情 (${pxy.codes.map(esc).join(', ')}): 以台账成交价为锚、其余持仓收益桥接估算, 占组合市值平均 ${pct(pxy.avg_share)} / 最高 ${pct(pxy.max_share)}; 补齐真实行情后自动替换`);
        } else if (re.missing_px_days) {
            notes.push(`⚠ 有 ${re.missing_px_days} 天存在缺行情持仓, 当日按其余持仓收益计入`);
        }
        const eb = d.equity_basis || {};
        if (eb.basis === 'broker_snapshot') notes.push('ⓘ 缺少现金字段, 总资产沿用券商快照 (与最新收盘市值可能错配)');
        const restate = (dd.restatement || []).map((r) =>
            `<div class="ts-banner warn">档位重述: ${esc(r.date)} 已发布 ${r.published_tier} 档 → 按当前数据重算为 ${r.restated_tier} 档 (台账或行情更新改变了历史净值; 原发布记录保留)</div>`).join('');
        const open = store.get('ts_dd_open', '1') === '1';
        return `<section class="ts-block ts-dd ${tcls} ${open ? '' : 'collapsed'}" id="ts-dd" aria-labelledby="ts-dd-h">
            <header class="ts-dd-head">
                <h4 id="ts-dd-h">组合回撤 · 分档刹车</h4>
                <span class="ts-dd-pill ${tcls}">${b.tier ? `${esc(b.label)}` : '未触发'}</span>
                <span class="ts-dd-headnum">−${pct(Math.abs(b.dd ?? 0))}<small> 自 ${esc(re.hwm_date || '--')} 高点</small></span>
                <span class="ts-dd-headmeta">${base ? `基准自 ${esc(base.date)}` : '实盘高水位'} · 剔除资金进出 · 收盘确认</span>
                <button class="ts-mini ghost ts-dd-toggle" data-act="dd-toggle" aria-expanded="${open}" aria-controls="ts-dd-body">${open ? '收起' : '展开'}</button>
            </header>
            <div class="ts-dd-body" id="ts-dd-body">
                ${restate}
                <div class="ts-dd-grid">
                    <div class="ts-dd-chartbox" id="ts-dd-chartbox">${ddChart(dd)}</div>
                    <aside class="ts-dd-side">${ddLadder(dd)}${ddProgress(b)}</aside>
                </div>
                <div class="ts-dd-cells">
                    ${cell(inv != null && inv > (b.cap_pct ?? 100) ? 'bad' : '', '仓位 / 上限', `${inv ?? '--'}%<small> / ${b.cap_pct ?? 100}%</small>`,
                        b.reduce_value ? `需降仓 ${money(b.reduce_value)}` : '在上限内')}
                    ${cell('', '回本所需', `+${pct(re.recovery_needed, 0)}`, `水下 ${re.days_underwater ?? '--'} 个交易日 · Ulcer ${fx((re.ulcer || 0) * 100, 1)}`)}
                    ${cell((pf.current_dd || 0) < -0.3 ? 'bad' : '', '当前持仓回看', `−${pct(Math.abs(pf.current_dd || 0))}`,
                        `若一直持有今天的组合 · 高点 ${esc(pf.hwm_date || '--')}`)}
                    ${cell((prob['28'] || 0) > 0.5 ? 'bad' : (prob['20'] || 0) > 0.5 ? 'warn' : '', '未来一年最大回撤', `中位 −${pct(Math.abs(fc.mdd_median || 0), 0)}`,
                        `95% 情形 −${pct(Math.abs(fc.mdd_p95 || 0), 0)} · 触及三档 ${pct(prob['28'], 0)}<br><span title="${esc(fa.vol || '')}">${esc(fa.drift || '')}</span>`)}
                    ${cell(mx != null && inv != null && inv / 100 > mx + 0.05 ? 'warn' : '', `预算 ${lastTier ? Math.round(lastTier.dd * 100) : '--'}% 下仓位`, `≤ ${pct(mx, 0)}`,
                        `年化波动 ${pct(fc.ann_vol, 0)} · 95% 情形不破预算`)}
                </div>
                ${notes.map((x) => `<div class="ts-muted ts-dd-note2">${x}</div>`).join('')}
                ${ddPlan(b.plan)}
                <footer class="ts-dd-foot">
                    <span class="ts-muted">${base ? `回撤基准 ${esc(base.date)}: ${esc(base.reason)}` : '重设基准 = 放弃本次刹车, 只在大额追加/撤出资金或投资政策变更时使用; 需写明理由并留痕。'}</span>
                    ${base ? '<button class="ts-mini ghost" data-act="dd-baseline-clear">撤销基准</button>'
                           : '<button class="ts-mini ghost" data-act="dd-baseline">重设回撤基准</button>'}
                </footer>
            </div>
        </section>`;
    }

    // ═══════════════ ④ 持仓: 走势 + 止损路径 ═══════════════
    function spark(r) {
        const p = r.path;
        if (!p || !p.c || p.c.length < 2) return '<div class="ts-spark-empty">—</div>';
        const W = 168, H = 44, PAD = 3;
        const vals = p.c.concat(p.s.filter((v) => v != null));
        let lo = Math.min(...vals), hi = Math.max(...vals);
        const cost = num(r.cost);
        const costIn = cost != null && cost >= lo - (hi - lo) * 0.25 && cost <= hi + (hi - lo) * 0.25;
        if (costIn) { lo = Math.min(lo, cost); hi = Math.max(hi, cost); }
        const span = (hi - lo) || hi * 0.01 || 1;
        const n = p.c.length;
        const X = (i) => PAD + (i / (n - 1)) * (W - 2 * PAD);
        const Y = (v) => PAD + (1 - (v - lo) / span) * (H - 2 * PAD);
        const line = p.c.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('');
        let stopPath = '';
        let started = false;
        p.s.forEach((v, i) => {
            if (v == null) { started = false; return; }
            stopPath += started ? `H${X(i).toFixed(1)}V${Y(v).toFixed(1)}` : `M${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
            started = true;
        });
        const st = (ST[r.status] || ST.NO_DATA).cls;
        const last = p.c[n - 1];
        const lastStop = p.s[n - 1];
        const below = lastStop != null && last < lastStop;
        const costEl = costIn
            ? `<line x1="${PAD}" x2="${W - PAD}" y1="${Y(cost).toFixed(1)}" y2="${Y(cost).toFixed(1)}" class="ts-sp-cost"/>`
            : '';
        const costTag = !costIn && cost != null ? `<text x="${W - PAD}" y="9" class="ts-sp-label" text-anchor="end">成本 ${px(cost, r.ts_code)} ↑</text>` : '';
        return `<svg class="ts-spark ${st}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" preserveAspectRatio="none" role="img"
            aria-label="${esc(r.name)} 近 60 日收盘与止损线">
            ${costEl}<path d="${line}" class="ts-sp-price"/>${stopPath ? `<path d="${stopPath}" class="ts-sp-stop"/>` : ''}
            <path d="M${X(n - 1).toFixed(1)},${Y(last).toFixed(1)}h0" class="ts-sp-dot ${below ? 'below' : ''}"/>${costTag}
        </svg>`;
    }

    function distBar(r) {
        if (r.status === 'NO_DATA') return '';
        const a = num(r.distance_atr);
        if (a == null) return '';
        const capped = Math.max(-3, Math.min(6, a));
        const zero = 3 / 9 * 100;
        const pos = (capped + 3) / 9 * 100;
        const left = Math.min(zero, pos), width = Math.abs(pos - zero);
        return `<div class="ts-dist ${a < 0 ? 'neg' : a < 0.5 ? 'near' : ''}" title="距止损线 ${fx(a, 1)} ATR (刻度 −3 ~ +6 ATR)"><i style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%"></i><b style="left:${zero.toFixed(1)}%"></b></div>`;
    }

    function stagePips(r) {
        if (r.stage == null) return '--';
        const names = ['初始', '保本', '跟踪'];
        return `<div class="ts-pips" title="${esc(r.stage_label || '')}">${[0, 1, 2].map((i) =>
            `<i class="${i <= r.stage ? 'on' : ''}"></i>`).join('')}<span>${names[r.stage] || ''}</span></div>`;
    }

    function rowOps(r) {
        let ops = '';
        if (r.status === 'LEGACY') ops += `<button class="ts-mini warn" data-act="rebaseline" data-code="${esc(r.ts_code)}">重新承保</button>`;
        if (r.status === 'ACTION' && r.pending_partial) ops += `<button class="ts-mini" data-act="ack" data-code="${esc(r.ts_code)}" data-stage="${r.pending_partial.stage}">已执行</button>`;
        if (!['exact', 'rebaselined'].includes(r.anchor_quality)) {
            ops += `<button class="ts-mini ghost" data-act="anchor" data-code="${esc(r.ts_code)}" data-cur="${esc(r.anchor_date || '')}">建仓日</button>`;
        }
        if (r.status !== 'NO_DATA') {
            ops += `<button class="ts-mini ghost" data-act="sleeve" data-code="${esc(r.ts_code)}" data-to="${r.sleeve === 'core' ? 'satellite' : 'core'}"
                title="底仓: 5/6×ATR 宽止损, 不分批">${r.sleeve === 'core' ? '设为卫星' : '设为底仓'}</button>`;
        }
        return ops;
    }

    function row(r) {
        const st = ST[r.status] || ST.NO_DATA;
        const ru = r.reunderwrite;
        const sub = [];
        if (ru && ru.max_qty != null) {
            sub.push(`若保留: 新止损 ${px(ru.new_stop, r.ts_code)} (−${pct(ru.stop_distance_pct, 0)}) · 单票预算内最多 ${ru.max_qty.toLocaleString()} 股${ru.reduce_qty ? ` · <i class="ts-neg">需减 ${ru.reduce_qty.toLocaleString()}</i>` : ''}`);
        }
        if (r.risk_excess_qty) sub.push(`<i class="ts-neg">超单票风险预算 · 应减 ${r.risk_excess_qty.toLocaleString()} 股</i>`);
        if ((r.data_lag_days || 0) > 1) sub.push(`<i class="ts-neg">行情滞后 ${r.data_lag_days} 日</i>`);
        const gainCls = (r.gain_pct || 0) >= 0 ? 'ts-pos' : 'ts-neg';
        const dAtr = num(r.distance_atr);
        return `
        <tr class="ts-row ${st.cls}" id="ts-row-${esc(r.ts_code)}">
            <td data-label="标的" class="ts-name"><b>${esc(r.name)}</b>
                <span>${esc(r.ts_code)} · ${CLS[r.asset_class] || '--'}${r.sleeve === 'core' ? ' · 底仓' : ''} · 仓位 ${pct(r.weight, 1)}</span></td>
            <td data-label="60日走势 / 止损线" class="ts-chart">${spark(r)}</td>
            <td data-label="现价 / 盈亏" class="ts-num">${px(r.close, r.ts_code)}
                <span>成本 ${px(r.cost, r.ts_code)} · <i class="${gainCls}">${spct(r.gain_pct)}</i></span></td>
            <td data-label="收盘确认线" class="ts-num"><b>${px(r.stop, r.ts_code)}</b>
                <span>${r.status === 'NO_DATA' || dAtr == null ? '--' : (dAtr < 0 ? `已低于 ${fx(-dAtr, 1)} ATR` : `距 ${fx(dAtr, 1)} ATR · ${pct(r.distance_pct)}`)}</span>${distBar(r)}</td>
            <td data-label="阶段" class="ts-num">${stagePips(r)}
                <span>${r.params ? `${r.params.init_k}/${r.params.trail_k}×ATR · ${r.params.trail_start_r}R 起跟` : ''}</span></td>
            <td data-label="到止损风险" class="ts-num">${r.open_risk == null ? '—' : money(r.open_risk)}
                <span>${r.risk_pct == null ? (r.status === 'LEGACY' || r.status === 'RED' ? '已越线' : '') : pct(r.risk_pct, 2) + ' 总资产'}</span></td>
            <td data-label="建仓锚点" class="ts-num">${esc(r.anchor_date || '--')}
                <span title="${esc(r.anchor_note || '')}">${ANCHOR[r.anchor_quality] || esc(r.anchor_quality || '')}</span></td>
            <td data-label="" class="ts-ops">${rowOps(r)}</td>
        </tr>
        ${sub.length ? `<tr class="ts-subrow ${st.cls}"><td colspan="8">${sub.join(' · ')}</td></tr>` : ''}`;
    }

    function positions(d) {
        const rows = d.positions || [];
        if (!rows.length) return '<div class="ts-empty">暂无持仓。请先在「组合」页导入资金股份查询。</div>';
        const groups = {};
        rows.forEach((r) => { (groups[r.status] = groups[r.status] || []).push(r); });
        const body = Object.keys(groups).sort((a, b) => (ST[a]?.order ?? 9) - (ST[b]?.order ?? 9)).map((k) => {
            const g = groups[k];
            const st = ST[k] || ST.NO_DATA;
            const mv = g.reduce((s, r) => s + (r.market_value || 0), 0);
            const collapsed = k === 'GREEN' && g.length > 6 && store.get('ts_green_open', '0') !== '1';
            return `<tbody class="ts-group ${st.cls} ${collapsed ? 'collapsed' : ''}" data-group="${k}">
                <tr class="ts-group-head"><td colspan="8">
                    <button class="ts-group-toggle" data-act="toggle-group" data-group="${k}">
                        <span class="ts-dot ${st.cls}"></span>${esc(st.group)} <b>${g.length}</b>
                        <em>${money(mv)} · 总资产 ${pct(mv / (d.equity || 1), 0)}</em><i class="ts-caret"></i></button></td></tr>
                ${g.map(row).join('')}</tbody>`;
        }).join('');
        return `<div class="ts-block"><div class="ts-block-title">持仓 <em>灰线 收盘 · 彩色阶梯 收盘后生效的止损线 (只升不降) · 虚线 成本</em></div>
            <div class="ts-table-wrap"><table class="ts-table ts-pos-table">
            <thead><tr><th>标的</th><th>60日走势 / 止损线</th><th>现价 / 盈亏</th><th>收盘确认线</th><th>阶段</th>
            <th>到止损风险</th><th>建仓锚点</th><th></th></tr></thead>${body}</table></div></div>`;
    }

    // ═══════════════ ⑤ 页签 ═══════════════
    function tabChanges(d) {
        const c = d.changes || {};
        if (!c.items || !c.items.length) {
            return `<div class="ts-empty">${esc(c.note || (c.base ? `与 ${c.base} 日终相比无变化` : '暂无上一交易日快照'))}</div>`;
        }
        return `<div class="ts-muted">对比基准: ${esc(c.base)} 日终快照</div><ul class="ts-changes">${c.items.map((i) =>
            `<li class="${esc(i.type)}"><b>${esc(i.name || i.ts_code)}</b><span>${esc(i.text)}</span></li>`).join('')}</ul>`;
    }

    function tabOrders(d) {
        const o = d.orders || [];
        if (!o.length) return '<div class="ts-empty">暂无需要挂出的条件单</div>';
        return `<div class="ts-tab-tools"><span class="ts-muted">收盘确认线由系统每日 15:50 核对; 券商条件单只作兜底, 防跳空与盘中急跌</span>
            <button class="ts-mini ghost" data-act="copy-orders">复制清单</button></div>
            <div class="ts-table-wrap"><table class="ts-table compact"><thead><tr><th>标的</th><th>类型</th><th>触发价</th><th>数量</th><th>说明</th></tr></thead>
            <tbody>${o.map((x) => `<tr><td>${esc(x.name)}<span>${esc(x.ts_code)}</span></td><td>${esc(x.type)}</td>
            <td class="ts-num">${x.trigger == null ? '—' : esc(x.trigger)}</td><td class="ts-num">${Number(x.qty).toLocaleString()}</td>
            <td class="ts-note">${esc(x.note)}</td></tr>`).join('')}</tbody></table></div>`;
    }

    function tabReentry(d) {
        const list = d.reentry || [];
        if (!list.length) return '<div class="ts-empty">近 180 天没有清仓的标的</div>';
        const S = { TRIGGER: ['action', '今日触发'], ABOVE: ['green', '已在线上'], WAIT: ['nodata', '等待'], NO_DATA: ['nodata', '无行情'] };
        return `<div class="ts-muted">校准结果的前提: 止损离场后按规则回补 (主题 ETF 20 日新高 / 宽基·个股 上穿 MA60), 否则会系统性错过反弹</div>
            <div class="ts-table-wrap"><table class="ts-table compact"><thead><tr><th>标的</th><th>信号</th><th>规则</th><th>现价 / 触发线</th><th>最近清仓</th></tr></thead>
            <tbody>${list.map((x) => {
                const [c, t] = S[x.state] || S.NO_DATA;
                return `<tr><td>${esc(x.name)}<span>${esc(x.ts_code)} · ${CLS[x.asset_class] || ''}</span></td>
                <td><span class="ts-badge ${c}">${t}</span></td><td>${esc(x.rule || '')}</td>
                <td class="ts-num">${x.close ?? '--'}<span>触发线 ${x.level ?? '--'} (${spct(x.gap_pct)})</span></td>
                <td class="ts-num">${esc(x.last_sell)}<span>@ ${x.last_sell_price ?? '--'}</span></td></tr>`;
            }).join('')}</tbody></table></div>`;
    }

    function tabAdds(d) {
        const ad = d.averaging_down || {};
        if (!ad.count) return '<div class="ts-empty">台账内没有亏损中加仓的记录</div>';
        return `<div class="ts-muted">机构纪律: 只在盈利仓位上加仓; 越线后加仓等于绕过止损。共 ${ad.count} 笔 · ${money(ad.amount)}, 其中越线后 ${ad.after_breach_count || 0} 笔 · ${money(ad.after_breach_amount)}</div>
            <div class="ts-table-wrap"><table class="ts-table compact"><thead><tr><th>标的</th><th>日期</th><th>价格 · 数量</th><th>相对成本</th><th>性质</th></tr></thead>
            <tbody>${(ad.items || []).map((i) => `<tr><td>${esc(i.name)}<span>${esc(i.ts_code)}</span></td>
            <td class="ts-num">${esc(i.date)}</td><td class="ts-num">${i.price} · ${Number(i.qty).toLocaleString()}</td>
            <td class="ts-num ts-neg">${spct(i.below_cost_pct)}</td>
            <td>${i.after_breach ? '<span class="ts-badge red">越线后加仓</span>' : '<span class="ts-badge yellow">低于成本</span>'}</td></tr>`).join('')}</tbody></table></div>`;
    }

    function tabReview() {
        if (!_reviewCache) return '<div class="ts-empty">复盘计算中…</div>';
        const v = _reviewCache;
        if (v.error) return `<div class="ts-empty">复盘暂不可用: ${esc(v.error)}</div>`;
        const s = v.summary || {};
        if (!v.trips?.length) return '<div class="ts-empty">台账中尚无已完成回合 (0 → 持仓 → 0)。持续导入历史成交后可复盘。</div>';
        return `<div class="ts-muted">共 ${s.count} 个回合 · 胜率 ${pct(s.win_rate, 0)} · 平均利润回吐 ${s.avg_giveback == null ? '--' : pct(s.avg_giveback, 0)} · 规则更优 ${s.rule_better} / 更差 ${s.rule_worse}</div>
            <div class="ts-table-wrap"><table class="ts-table compact"><thead><tr><th>标的</th><th>持有</th><th>实际收益</th><th>最大浮盈</th><th>利润回吐</th><th>规则离场</th><th>规则 − 实际</th></tr></thead>
            <tbody>${v.trips.map((t) => `<tr><td>${esc(t.name || t.ts_code)}<span>${esc(t.ts_code)}</span></td>
            <td class="ts-num">${esc(t.entry_date)} → ${esc(t.exit_date)}</td>
            <td class="ts-num ${(t.ret || 0) >= 0 ? 'ts-pos' : 'ts-neg'}">${spct(t.ret)}</td><td class="ts-num">${spct(t.mfe_pct)}</td>
            <td class="ts-num">${t.giveback == null ? '--' : pct(t.giveback, 0)}</td>
            <td class="ts-num">${t.rule_exit_date ? `${esc(t.rule_exit_date)} · ${spct(t.rule_ret)}` : '未触发'}</td>
            <td class="ts-num ${(t.rule_minus_actual || 0) >= 0 ? 'ts-pos' : 'ts-neg'}">${t.rule_minus_actual == null ? '--' : spct(t.rule_minus_actual)}</td></tr>`).join('')}</tbody></table></div>
            <div class="ts-muted">规则离场按收盘确认、次日开盘成交 (一字跌停顺延) 并扣 0.2% 往返费用估算; 样本少时仅作参考, 不据此单点调参。</div>`;
    }

    function tabAudit(d) {
        const a = d.audit || [];
        if (!a.length) return '<div class="ts-empty">暂无人工操作记录</div>';
        const L = { start_tracking: '开始跟踪', rebaseline: '重新承保', set_anchor: '设定建仓日', clear_anchor: '恢复自动锚点',
            set_sleeve: '底仓/卫星', ack_stage: '确认分批已执行', drawdown_baseline: '重设回撤基准',
            drawdown_baseline_clear: '撤销回撤基准' };
        return `<div class="ts-muted">所有人工推翻都留痕; 重新承保与建仓日设定必须填写理由</div><ul class="ts-audit">${a.map((x) =>
            `<li><time>${esc((x.at || '').replace('T', ' '))}</time><b>${esc(L[x.action] || x.action)}</b><span>${esc(x.ts_code === '*' ? '' : x.ts_code)}</span><em>${esc(x.detail || '')}</em></li>`).join('')}</ul>`;
    }

    function tabMethod(d) {
        const p = d.params || {};
        const c = p.classes || {};
        const cal = p.calibration || {};
        const m = d.meta || {};
        const led = d.ledger || {};
        const one = (k, lbl) => c[k] ? `<tr><td>${lbl}</td><td class="ts-num">${c[k].init_atr_mult}×ATR</td><td class="ts-num">${c[k].trail_atr_mult}×ATR</td>
            <td class="ts-num">${c[k].trail_start_r}R</td><td class="ts-num">${pct(c[k].partial_fraction, 0)}</td><td>${c[k].reentry === 'breakout20' ? '20 日新高' : '上穿 MA60'}</td></tr>` : '';
        return `<div class="ts-method">
            <div><div class="ts-block-title">参数 (按资产类别校准)</div>
            <div class="ts-table-wrap"><table class="ts-table compact"><thead><tr><th>类别</th><th>初始止损</th><th>跟踪距离</th><th>起跟</th><th>分批</th><th>再入场</th></tr></thead>
            <tbody>${one('theme_etf', '主题 ETF')}${one('broad_etf', '宽基 ETF')}${one('stock', '个股')}</tbody></table></div>
            <p class="ts-muted">≥${p.breakeven_r}R 止损上移至保本; 止损线只升不降; 拆分/分红按交易所前收盘连续化。单票到止损风险 ≤ 总资产 ${pct(p.risk_per_position_pct, 0)}, 组合热度上限 ${pct(p.heat_limit_pct, 0)}。</p></div>
            <div><div class="ts-block-title">校准与数据血缘</div><dl class="ts-dl">
                <dt>校准</dt><dd>${esc(cal.version || '')} · ${esc(cal.universe || '')}</dd>
                <dt>检验</dt><dd>${esc(cal.split || '')}; ${esc(cal.execution || '')}</dd>
                <dt>引擎</dt><dd>${esc(m.engine || '')} · schema v${esc(m.schema_version || '')} · 参数 ${esc(m.config_hash || '')}</dd>
                <dt>行情</dt><dd>${esc(m.price_as_of_min || '--')} ~ ${esc(m.price_as_of_max || '--')}</dd>
                <dt>台账</dt><dd>${led.trades || 0} 笔 ${led.date_from ? `(${esc(led.date_from)} → ${esc(led.date_to)})` : ''} · ${esc(led.import_note || '')}</dd>
                <dt>文档</dt><dd>docs/trailing_stop_calibration.md · 重跑校准: python -m strategies.trailing_stop_calibration</dd>
            </dl></div></div>`;
    }

    const TAB_RENDER = { changes: tabChanges, orders: tabOrders, reentry: tabReentry, adds: tabAdds, review: tabReview, audit: tabAudit, method: tabMethod };

    function tabs(d) {
        const counts = {
            changes: (d.changes?.items || []).length, orders: (d.orders || []).length,
            reentry: (d.reentry || []).filter((x) => x.state === 'TRIGGER').length,
            adds: d.averaging_down?.count || 0, audit: (d.audit || []).length,
        };
        if (!TAB_RENDER[_tab]) _tab = 'changes';
        return `<div class="ts-block ts-tabs-block">
            <div class="ts-tabs" role="tablist">${TABS.map(([k, l]) =>
                `<button role="tab" aria-selected="${k === _tab}" class="ts-tab ${k === _tab ? 'on' : ''}" data-act="tab" data-tab="${k}">${l}${counts[k] ? `<i>${counts[k]}</i>` : ''}</button>`).join('')}</div>
            <div class="ts-tab-body" id="ts-tab-body">${TAB_RENDER[_tab](d)}</div></div>`;
    }

    function syncNote(d) {
        const need = d.price_sync_needed || [];
        if (!need.length) return '';
        const ps = d.price_sync || {};
        const txt = ps.started ? `已在后台同步 ${need.length} 只持仓的日线行情, 约 1 分钟后自动刷新`
            : ps.reason === '同步进行中' ? '行情同步进行中, 稍后自动刷新' : `${need.length} 只持仓缺行情或行情滞后, 可点「同步并重算」`;
        return `<div class="ts-banner info">${esc(txt)}: ${need.map(esc).join(', ')}</div>`;
    }

    // ═══════════════ 交互 ═══════════════
    function msg(html, cls = '') {
        const el = document.getElementById('ts-msg');
        if (el) { el.className = `ts-banner ${cls || 'info'}`; el.innerHTML = html; el.hidden = !html; }
    }

    async function importOne(file) {
        const fd = new FormData();
        fd.append('file', file);
        try {
            const res = await (await api(`${BASE}/trades/import`, { method: 'POST', body: fd })).json();
            if (res.status !== 'success') return [false, `${esc(file.name)}: ${esc(res.message)}`];
            const d = res.data;
            const skipped = Object.entries(d.skipped || {}).map(([k, v]) => `${{ repo: '逆回购', cash: '资金/红利', zero_qty: '零数量' }[k] || k} ${v}`).join(' · ');
            return [true, `${esc(file.name)}: ${esc(d.date_from)} → ${esc(d.date_to)} · 解析 ${d.parsed} 笔 · 新增 ${d.added} · 重复 ${d.duplicates}${skipped ? ` · 跳过 ${esc(skipped)}` : ''}${d.error_count ? ` · ${d.error_count} 行未识别` : ''}`];
        } catch (e) {
            return [false, `${esc(file.name)}: ${esc(e.message)}`];
        }
    }

    async function importFiles(files) {
        msg(`解析 ${files.length} 个文件…`);
        const res = [];
        for (const f of files) res.push(await importOne(f));
        msg(res.map(([ok, t]) => `${ok ? '✅' : '❌'} ${t}`).join('<br>'), res.every(([ok]) => ok) ? 'ok' : 'err');
        _reviewCache = null;
        await load(true);
    }

    async function onClick(ev) {
        const btn = ev.target.closest('[data-act]');
        if (!btn || !document.getElementById('trailing-stop-panel')?.contains(btn)) return;
        const act = btn.dataset.act;
        const code = btn.dataset.code;
        try {
            if (act === 'import') {
                document.getElementById('ts-file')?.click();
            } else if (act === 'scan') {
                btn.disabled = true;
                const r = await (await api(`${BASE}/trades/scan`, { method: 'POST' })).json();
                const files = r.data?.files || [];
                msg(r.status === 'success'
                    ? `${esc(r.message)}${files.length ? '<br>' + files.map((f) => `${f.status === 'ok' ? '✅' : '❌'} ${esc(f.file)} ${f.status === 'ok' ? `新增 ${f.added} · 重复 ${f.duplicates}` : esc(f.message || '')}`).join('<br>') : ''}`
                    : `❌ ${esc(r.message)}`, r.status === 'success' ? 'ok' : 'err');
                await load(true);
            } else if (act === 'run') {
                btn.disabled = true; btn.textContent = '同步中…';
                const r = await (await api(`${BASE}/trailing-stops/run`, { method: 'POST' })).json();
                msg(r.status === 'success' ? '✅ 已同步行情、重算并完成日终提交' : `❌ ${esc(r.message)}`, r.status === 'success' ? 'ok' : 'err');
                await load(true);
            } else if (act === 'tab') {
                _tab = btn.dataset.tab;
                store.set('ts_tab', _tab);
                document.querySelectorAll('#trailing-stop-panel .ts-tab').forEach((b) => {
                    const on = b.dataset.tab === _tab;
                    b.classList.toggle('on', on); b.setAttribute('aria-selected', String(on));
                });
                const body = document.getElementById('ts-tab-body');
                if (_tab === 'review' && !_reviewCache) {
                    body.innerHTML = tabReview();
                    try {
                        const r = await (await api(`${BASE}/trades/review`)).json();
                        _reviewCache = r.status === 'success' ? r.data : { error: r.message };
                    } catch (e) { _reviewCache = { error: e.message }; }
                }
                if (_tab === btn.dataset.tab) body.innerHTML = TAB_RENDER[_tab](_last || {});
            } else if (act === 'toggle-group') {
                const g = btn.closest('.ts-group');
                g.classList.toggle('collapsed');
                if (btn.dataset.group === 'GREEN') store.set('ts_green_open', g.classList.contains('collapsed') ? '0' : '1');
            } else if (act === 'goto') {
                const tr = document.getElementById(`ts-row-${code}`);
                if (tr) {
                    tr.closest('.ts-group')?.classList.remove('collapsed');
                    tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    tr.classList.add('flash'); setTimeout(() => tr.classList.remove('flash'), 1600);
                }
            } else if (act === 'copy-plan') {
                ev.preventDefault();
                const p = _last?.drawdown?.brake?.plan;
                const text = (p?.items || []).map((i) => `${i.name}(${i.ts_code})\t卖出\t${i.qty}\t${i.reason}`).join('\n');
                await navigator.clipboard?.writeText(text);
                btn.textContent = '已复制';
            } else if (act === 'goto-dd') {
                const sec = document.getElementById('ts-dd');
                if (sec?.classList.contains('collapsed')) sec.querySelector('[data-act="dd-toggle"]')?.click();
                sec?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } else if (act === 'dd-toggle') {
                const sec = document.getElementById('ts-dd');
                const open = sec.classList.toggle('collapsed') === false;
                btn.textContent = open ? '收起' : '展开';
                btn.setAttribute('aria-expanded', String(open));
                store.set('ts_dd_open', open ? '1' : '0');
                if (open) fitDdChart();
            } else if (act === 'dd-baseline') {
                const b = _last?.drawdown?.brake || {};
                const today = (_last?.as_of || '').slice(0, 10);
                const date = prompt(`重设组合回撤基准 (YYYY-MM-DD)\n\n自该日起重新计算高水位, 当前 ${b.label || '刹车'} 将随之解除。\n这是对风控规则的人工推翻, 将写入审计日志; 机构做法是只在资本重新承保 (如追加/撤出大额资金、投资政策变更) 时使用。`, today);
                if (!date || !date.trim()) return;
                const reason = prompt('重设理由 (≥4 字):') || '';
                if (!reason.trim()) return;
                const r = await postJson(`${BASE}/drawdown/baseline`, { date: date.trim(), reason });
                msg(r.status === 'success' ? `✅ ${esc(r.message)}` : `❌ ${esc(r.message)}`, r.status === 'success' ? 'ok' : 'err');
                await load(true);
            } else if (act === 'dd-baseline-clear') {
                if (!confirm('撤销回撤基准, 恢复按实盘高水位计算?')) return;
                const r = await postJson(`${BASE}/drawdown/baseline`, { date: '', reason: '' });
                msg(r.status === 'success' ? `✅ ${esc(r.message)}` : `❌ ${esc(r.message)}`, r.status === 'success' ? 'ok' : 'err');
                await load(true);
            } else if (act === 'rebaseline') {
                const r0 = (_last?.positions || []).find((x) => x.ts_code === code) || {};
                const ru = r0.reunderwrite || {};
                const reason = prompt(`重新承保 ${r0.name || code}\n\n这是对「已越过止损线」的人工推翻, 将写入审计日志。\n以最新收盘为新起点: 新止损 ${ru.new_stop ?? '--'}, 单票风险预算内最多 ${ru.max_qty ?? '--'} 股${ru.reduce_qty ? `, 需减 ${ru.reduce_qty} 股` : ''}。\n注意: 同板块持仓高度相关, 多只同时保留时应按一个整体核定预算。\n\n请填写保留理由 (≥4 字):`);
                if (!reason) return;
                const r = await postJson(`${BASE}/trailing-stops/${encodeURIComponent(code)}/rebaseline`, { reason });
                msg(r.status === 'success' ? `✅ ${esc(r0.name || code)} 已重新承保 (已留痕)` : `❌ ${esc(r.message)}`, r.status === 'success' ? 'ok' : 'err');
                await load(true);
            } else if (act === 'anchor') {
                const date = prompt(`设定 ${code} 的本轮建仓日 (YYYY-MM-DD)\n用于确定高水位起点与建仓时的波动幅度; 留空 = 恢复自动推断。\n当前: ${btn.dataset.cur || '--'}`, btn.dataset.cur || '');
                if (date === null) return;
                let reason = '';
                if (date.trim()) {
                    reason = prompt('依据 (如: 券商对账单显示 2026-06-12 首次买入):') || '';
                    if (!reason.trim()) return;
                }
                const r = await postJson(`${BASE}/trailing-stops/${encodeURIComponent(code)}/anchor`, { date: date.trim(), reason });
                msg(r.status === 'success' ? `✅ ${esc(code)} ${esc(r.message)}` : `❌ ${esc(r.message)}`, r.status === 'success' ? 'ok' : 'err');
                await load(true);
            } else if (act === 'sleeve') {
                const r = await postJson(`${BASE}/trailing-stops/${encodeURIComponent(code)}/sleeve`, { sleeve: btn.dataset.to });
                if (r.status !== 'success') msg(`❌ ${esc(r.message)}`, 'err');
                await load(true);
            } else if (act === 'ack') {
                if (!confirm(`确认 ${code} 的分批止盈已在其他账户/渠道执行?`)) return;
                await postJson(`${BASE}/trailing-stops/${encodeURIComponent(code)}/ack`, { stage: Number(btn.dataset.stage) });
                await load(true);
            } else if (act === 'copy-orders') {
                const text = (_last?.orders || []).map((o) => `${o.name}(${o.ts_code})\t${o.type}\t${o.trigger ?? ''}\t${o.qty}`).join('\n');
                await navigator.clipboard?.writeText(text);
                btn.textContent = '已复制';
            }
        } catch (e) {
            if (!e.isCancelled) msg(`❌ ${esc(e.message)}`, 'err');
        }
    }

    function summaryChips(d) {
        const s = d.summary || {};
        const bk = d.drawdown?.brake;
        const chips = (bk?.tier ? `<span class="ts-chip ${bk.tier >= 2 ? 'red' : 'legacy'}">回撤 ${bk.tier} 档 −${pct(Math.abs(bk.dd), 0)}</span>` : '')
            + Object.keys(ST).filter((k) => s[k] && k !== 'GREEN')
            .map((k) => `<span class="ts-chip ${ST[k].cls}">${ST[k].tag} ${s[k]}</span>`).join('');
        return chips || '<span class="ts-chip green">全部在线内</span>';
    }

    async function load(keepMsg) {
        const $panel = document.getElementById('trailing-stop-panel');
        const $body = document.getElementById('ts-body');
        const $sum = document.getElementById('ts-summary');
        if (!$panel || !$body) return;
        const prev = keepMsg ? document.getElementById('ts-msg') : null;
        const prevHtml = prev && !prev.hidden ? [prev.innerHTML, prev.className] : null;
        if (!keepMsg) $body.innerHTML = '<div class="ts-skeleton"><i></i><i></i><i></i></div>';
        try {
            const raw = await (await api(`${BASE}/trailing-stops`)).json();
            if (raw.status !== 'success') throw new Error(raw.message || '后端返回失败');
            const d = raw.data;
            _last = d;
            const s = d.summary || {};
            const worst = Object.keys(ST).find((k) => s[k]) || 'GREEN';
            $panel.dataset.level = (d.drawdown?.brake?.tier >= 2 && worst !== 'RED') ? 'red' : ST[worst].cls;
            if ($sum) $sum.innerHTML = summaryChips(d);
            $body.innerHTML = `${verdict(d)}<div class="ts-banner" id="ts-msg" hidden></div>${syncNote(d)}
                ${kpis(d)}${actions(d)}${drawdownBlock(d)}${positions(d)}${tabs(d)}`;
            fitDdChart();
            if (prevHtml) { const m = document.getElementById('ts-msg'); m.innerHTML = prevHtml[0]; m.className = prevHtml[1]; m.hidden = false; }
            document.getElementById('ts-file')?.addEventListener('change', (e) => {
                const fs = Array.from(e.target.files || []);
                if (fs.length) importFiles(fs);
                e.target.value = '';
            });
            if (d.price_sync?.started && !_autoRefreshed) {
                _autoRefreshed = true;
                setTimeout(() => load(true), 75000);
            }
        } catch (e) {
            console.warn('[TrailingStop] load failed:', e);
            if ($sum) $sum.textContent = '暂不可用';
            $body.innerHTML = `<div class="ts-banner err">跟踪止盈暂不可用: ${esc(e.message)} <button class="ts-mini" onclick="loadTrailingStopPanel()">重试</button></div>`;
        }
    }

    function fitDdChart() {
        const box = document.getElementById('ts-dd-chartbox');
        if (!box || !_last?.drawdown || !box.clientWidth) return;
        const w = Math.round(box.clientWidth);
        if (box.dataset.w === String(w)) return;
        box.dataset.w = String(w);
        box.innerHTML = ddChart(_last.drawdown, w);
    }
    let _fitTimer = null;
    window.addEventListener('resize', () => { clearTimeout(_fitTimer); _fitTimer = setTimeout(fitDdChart, 150); });

    document.addEventListener('click', onClick);
    document.addEventListener('toggle', (e) => {
        const el = e.target;
        if (el instanceof HTMLDetailsElement && el.dataset.store && el.closest('#trailing-stop-panel')) store.set(el.dataset.store, el.open ? '1' : '0');
    }, true);
    window.loadTrailingStopPanel = load;
    document.addEventListener('DOMContentLoaded', () => setTimeout(() => load(false), 800));
})();
