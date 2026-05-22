/**
 * strategy_gem.js — GEM 双重动量策略 V3.0 前端渲染 (Production)
 *
 * API: GET /api/v1/gem_strategy
 * 数据路径: response.data.market_overview / response.data.signals
 *
 * 渲染区域:
 *   Hero    → 4 KPI stats
 *   Zone 1  → 信号面板 + V3.0保护状态 + 权重条
 *   Zone1.5 → 5维评分雷达 + 综合评分条
 *   Zone 2  → 12列资产排行表
 */

// IIFE 避免与 strategy.js 的全局 _setText/_setColor 冲突
(function() {
'use strict';

var _gemCache = null;

// ═══════════════════════════════════════════
//  公开入口 (window 暴露)
// ═══════════════════════════════════════════
window.loadGemStrategy = async function(forceRefresh) {
    forceRefresh = forceRefresh || false;
    var btn = document.getElementById('gem-load-btn');
    var status = document.getElementById('gem-load-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 加载中...'; }
    if (status) status.textContent = '⏳ 正在获取跨市场数据...';

    try {
        var url = forceRefresh ? '/api/v1/gem_strategy?refresh=1' : '/api/v1/gem_strategy';
        var resp = await fetch(url);
        if (!resp.ok) {
            _showError(status, 'HTTP ' + resp.status);
            return;
        }
        var json = await resp.json();
        if (json.status !== 'success') {
            _showError(status, json.message || json.error || '未知错误');
            return;
        }

        _gemCache = json;
        renderGemStrategy(json);

        var now = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        if (status) status.innerHTML = '<span style="color:#34d399;">✅ 已加载</span> · ' + now;
    } catch (e) {
        console.error('[GEM] load error:', e);
        var errMsg = (e.message || '').indexOf('Failed to fetch') >= 0
            ? '无法连接服务器 · 请确认后端已启动'
            : e.message;
        _showError(status, errMsg);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '⚡ 加载实时数据'; }
    }
};

// ═══════════════════════════════════════════
//  核心渲染
// ═══════════════════════════════════════════
function renderGemStrategy(json) {
    var ov = (json.data && json.data.market_overview) || {};
    var signals = (json.data && json.data.signals) || [];

    // ── Hero KPI ──
    var sigLabel = ov.signal_label || '—';
    var sigType = ov.signal_type || 'hold';
    var sigColor = sigType === 'buy' ? '#34d399' : (sigType === 'cash' ? '#f87171' : '#fbbf24');
    _set('gem-hero-signal', sigLabel, sigColor);
    _set('gem-hero-position', (ov.total_position || 0) + '%');
    _set('gem-hero-score', (ov.composite_score || 0).toFixed(1), '#fbbf24');

    // ── Zone 1: 信号面板 ──
    _set('gem-sig-type', sigLabel, sigColor);
    _set('gem-sig-asset', ov.selected_asset || '—');
    _set('gem-sig-abs', ov.abs_momentum_pass ? '✓ 通过' : '✗ 未通过',
         ov.abs_momentum_pass ? '#34d399' : '#f87171');
    _set('gem-sig-dual', ov.conviction_label || '—',
         ov.signals_agree ? '#a78bfa' : '#f59e0b');

    // ── 权重条 ──
    _renderWeightBars(ov.target_weights, signals);

    // ── V3.0 保护状态 ──
    _renderV3Features(ov, signals);

    // ── Regime ──
    var regimeMap = { BULL:{icon:'🟢',color:'#34d399'}, RANGE:{icon:'🟡',color:'#fbbf24'}, BEAR:{icon:'🔴',color:'#f87171'}, CRASH:{icon:'💀',color:'#ef4444'} };
    var r = regimeMap[ov.regime] || regimeMap.RANGE;
    _set('gem-regime', r.icon + ' ' + (ov.regime || 'RANGE'), r.color);
    _set('gem-regime-cap', (ov.regime_cap || 0) + '%', '#fbbf24');

    // ── Zone 1.5: 评分维度 ──
    _renderScoreDimensions(ov);

    // ── Zone 2: 资产排行 ──
    _renderAssetTable(signals);

    // ── 操作提示面板 ──
    _renderActionPanel(ov, signals);
}

// ═══════════════════════════════════════════
//  Zone 1: 权重条
// ═══════════════════════════════════════════
function _renderWeightBars(weights, signals) {
    var wc = document.getElementById('gem-weights-bars');
    if (!wc || !weights) return;
    var entries = Object.entries(weights).sort(function(a, b) { return b[1] - a[1]; });
    var colors = ['#38bdf8', '#34d399', '#fbbf24', '#a78bfa', '#f87171', '#fb923c', '#94a3b8'];

    wc.innerHTML = entries.map(function(entry, i) {
        var code = entry[0], pct = entry[1];
        var name = _codeName(code, signals);
        var color = colors[i % colors.length];
        return '<div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">' +
            '<div style="width:90px; font-size:0.72rem; color:#cbd5e1; text-align:right; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + name + '</div>' +
            '<div style="flex:1; height:22px; background:rgba(255,255,255,0.04); border-radius:6px; overflow:hidden;">' +
                '<div style="height:100%; width:' + pct + '%; background:' + color + '; border-radius:6px; transition:width 0.6s ease;"></div>' +
            '</div>' +
            '<div style="width:48px; font-size:0.78rem; font-weight:700; color:' + color + '; text-align:right;">' + pct + '%</div>' +
        '</div>';
    }).join('');
}

// ═══════════════════════════════════════════
//  Zone 1: V3.0 保护状态
// ═══════════════════════════════════════════
function _renderV3Features(ov, signals) {
    // SMA
    var sma = ov.sma_filter_active;
    var smaFiltered = ov.sma_filtered || {};
    var smaFailed = Object.entries(smaFiltered).filter(function(e) { return !e[1]; }).map(function(e) { return _codeName(e[0], signals); });
    _set('gem-f-sma-icon', sma ? '✅' : '⏸️');
    _set('gem-f-sma-detail', sma
        ? (smaFailed.length > 0 ? '已过滤: ' + smaFailed.join(', ') : '全部资产价格 > SMA200 ✓')
        : '未启用');

    // VolTarget
    var vol = ov.vol_scale || {};
    _set('gem-f-vol-icon', vol.active ? '🔻' : '✅');
    _set('gem-f-vol-detail', vol.active
        ? '组合波动 ' + (vol.port_vol || 0).toFixed(1) + '% → 缩放至 ' + ((vol.scale || 1) * 100).toFixed(0) + '%'
        : '组合波动率在目标范围内 ✓');

    // Dual confirm
    _set('gem-f-dual-icon', ov.signals_agree ? '✅' : '⚠️');
    _set('gem-f-dual-detail', ov.signals_agree
        ? '9M与7M窗口一致 · 信念度 ' + ((ov.conviction || 0) * 100).toFixed(0) + '%'
        : '9M与7M窗口不一致 · 信念度降至 ' + ((ov.conviction || 0) * 100).toFixed(0) + '%');

    // Corr dedup
    _set('gem-f-corr-icon', '✅');
    _set('gem-f-corr-detail', 'SP500/NASDAQ 同组去重 · 最多选1');
}

// ═══════════════════════════════════════════
//  Zone 1.5: 5维评分 (生产级可视化)
// ═══════════════════════════════════════════
function _renderScoreDimensions(ov) {
    var dims = ov.score_dimensions || {};
    var composite = ov.composite_score || 0;

    // 维度定义: [key, html_id, label, color, weight_label]
    var dimDefs = [
        ['excess_return', 'gem-d-excess',     '超额收益', '#38bdf8', '40%'],
        ['conviction',    'gem-d-conviction', '置信度',   '#a78bfa', '20%'],
        ['rank_quality',  'gem-d-rank',       '排名稳定', '#34d399', '15%'],
        ['breadth',       'gem-d-breadth',    '市场广度', '#fbbf24', '15%'],
        ['mdd_penalty',   'gem-d-mdd',        '路径质量', '#f87171', '10%'],
    ];

    for (var i = 0; i < dimDefs.length; i++) {
        var key = dimDefs[i][0], id = dimDefs[i][1], color = dimDefs[i][3];
        var dim = dims[key] || {};
        var score = dim.score || 0;
        var raw = dim.raw;

        // 主分数
        var el = document.getElementById(id);
        if (el) {
            el.innerHTML = '<span style="font-size:1.5rem; font-weight:900; color:' + color + ';">' +
                score.toFixed(0) + '</span>' +
                '<span style="font-size:0.65rem; color:#475569; margin-left:2px;">/100</span>';
        }
    }

    // 综合评分
    _set('gem-score-value', composite.toFixed(1) + ' / 100', _scoreColor(composite));
    var bar = document.getElementById('gem-score-bar');
    if (bar) {
        // 延迟触发动画
        setTimeout(function() { bar.style.width = Math.min(composite, 100) + '%'; }, 100);
    }
}

// ═══════════════════════════════════════════
//  Zone 2: 12列资产排行表
// ═══════════════════════════════════════════
function _renderAssetTable(signals) {
    var tbody = document.getElementById('gem-asset-tbody');
    if (!tbody) return;

    if (!signals.length) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:#64748b;">无数据</td></tr>';
        return;
    }

    // 找到入选/未入选分界 (有权重的资产)
    var selectedCount = signals.filter(function(s) { return (s.target_weight || 0) > 0 || s.signal === 'buy'; }).length;

    tbody.innerHTML = signals.map(function(s, i) {
        var isBuy = s.signal === 'buy';
        var isCash = s.signal === 'cash';
        var weight = s.target_weight || 0;
        var isSelected = weight > 0 || isBuy;

        // 行样式: 入选资产发光, 现金信号高亮, 候选资产暗淡
        var rowStyle = '';
        if (isBuy && weight > 0) {
            rowStyle = 'background:linear-gradient(90deg,rgba(16,185,129,0.08),rgba(16,185,129,0.02)); border-left:3px solid #10b981;';
        } else if (isBuy) {
            rowStyle = 'background:rgba(16,185,129,0.04);';
        } else if (isCash) {
            rowStyle = 'background:rgba(239,68,68,0.03);';
        }

        // 排名: 金牌前2, 银色其余
        var rankColor = i < 2 ? '#fbbf24' : '#64748b';
        var rankIcon = i === 0 ? '🥇' : (i === 1 ? '🥈' : (i + 1));

        // 标的列: 合并 名称 + 代码 + 国旗
        var code = (s.ts_code || '').split('.')[0];
        var mktFlag = s.market === 'CN' ? '🇨🇳' : (s.market === 'US' ? '🇺🇸' : (s.market === 'JP' ? '🇯🇵' : '🏳️'));
        var nameCell = '<div style="display:flex; align-items:center; gap:8px;">' +
            '<span style="font-size:0.85rem;">' + mktFlag + '</span>' +
            '<div>' +
                '<div style="font-weight:600; color:' + (isSelected ? '#f0f4f8' : '#94a3b8') + '; font-size:0.82rem; line-height:1.3;">' + (s.name || '') + '</div>' +
                '<div style="font-family:\'Outfit\',monospace; font-size:0.68rem; color:#64748b;">' + code + '</div>' +
            '</div>' +
        '</div>';

        // 回报: 条件着色
        var ret9m = s.return_12m || 0;
        var ret7m = s.return_6m != null ? s.return_6m : 0;
        var retColor = function(v) { return v > 5 ? '#34d399' : (v > 0 ? '#6ee7b7' : (v < -5 ? '#f87171' : (v < 0 ? '#fca5a5' : '#94a3b8'))); };

        // Sharpe: 条件着色
        var sharpe = s.sharpe || 0;
        var sharpeColor = sharpe >= 1.5 ? '#34d399' : (sharpe >= 0.8 ? '#38bdf8' : (sharpe >= 0.3 ? '#fbbf24' : '#f87171'));

        // 波动率: 高波动警告
        var vol = s.vol_ann || 0;
        var volColor = vol > 30 ? '#f87171' : (vol > 20 ? '#fbbf24' : '#94a3b8');

        // MDD: 梯度着色
        var mdd = s.mdd || 0;
        var mddColor = mdd < -20 ? '#ef4444' : (mdd < -10 ? '#f87171' : (mdd < -5 ? '#fbbf24' : '#94a3b8'));

        // QDII
        var haircut = s.qdii_haircut || 0;
        var qdiiCell = haircut > 0
            ? '<span style="color:#fb923c; font-weight:600;">-' + haircut.toFixed(1) + '%</span>'
            : '<span style="color:#475569;">—</span>';

        // 信号: 增强视觉
        var sigBadge;
        if (isBuy) {
            sigBadge = '<span style="display:inline-flex; align-items:center; gap:3px; padding:3px 10px; border-radius:20px; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.3); color:#34d399; font-weight:800; font-size:0.72rem; letter-spacing:0.5px;">● BUY</span>';
        } else if (isCash) {
            sigBadge = '<span style="display:inline-flex; align-items:center; gap:3px; padding:3px 10px; border-radius:20px; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.25); color:#f87171; font-weight:700; font-size:0.72rem;">◆ CASH</span>';
        } else {
            sigBadge = '<span style="display:inline-flex; align-items:center; gap:3px; padding:3px 10px; border-radius:20px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); color:#64748b; font-size:0.72rem;">○ HOLD</span>';
        }

        // 权重: 有权重显示mini bar
        var weightCell;
        if (weight > 0) {
            weightCell = '<div style="display:flex; align-items:center; gap:6px; justify-content:center;">' +
                '<div style="width:40px; height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden;">' +
                    '<div style="height:100%; width:' + Math.min(weight * 2, 100) + '%; background:linear-gradient(90deg,#38bdf8,#6366f1); border-radius:3px;"></div>' +
                '</div>' +
                '<span style="font-weight:800; color:#38bdf8; font-size:0.82rem;">' + weight.toFixed(1) + '%</span>' +
            '</div>';
        } else {
            weightCell = '<span style="color:#475569;">—</span>';
        }

        // 分隔线: 入选资产和候选资产之间
        var separator = '';
        if (selectedCount > 0 && i === selectedCount - 1 && i < signals.length - 1) {
            separator = '<tr><td colspan="10" style="padding:0; height:2px; background:linear-gradient(90deg,transparent,rgba(99,102,241,0.3),transparent);"></td></tr>';
        }

        return '<tr style="' + rowStyle + '">' +
            '<td style="text-align:center; font-weight:800; color:' + rankColor + '; font-size:0.85rem;">' + rankIcon + '</td>' +
            '<td>' + nameCell + '</td>' +
            '<td style="text-align:center; color:' + retColor(ret9m) + '; font-weight:700;">' + ret9m.toFixed(1) + '%</td>' +
            '<td style="text-align:center; color:' + retColor(ret7m) + '; font-size:0.82rem;">' + ret7m.toFixed(1) + '%</td>' +
            '<td style="text-align:center; color:' + sharpeColor + '; font-weight:700;">' + sharpe.toFixed(2) + '</td>' +
            '<td style="text-align:center; color:' + volColor + ';">' + vol.toFixed(1) + '%</td>' +
            '<td style="text-align:center; color:' + mddColor + ';">' + mdd.toFixed(1) + '%</td>' +
            '<td style="text-align:center; font-size:0.78rem;">' + qdiiCell + '</td>' +
            '<td style="text-align:center;">' + sigBadge + '</td>' +
            '<td style="text-align:center;">' + weightCell + '</td>' +
        '</tr>' + separator;
    }).join('');
}

// ═══════════════════════════════════════════
//  操作提示面板 (机构级)
// ═══════════════════════════════════════════
function _renderActionPanel(ov, signals) {
    var panel = document.getElementById('gem-action-panel');
    if (!panel) return;

    var sigType = ov.signal_type || 'hold';
    var html = '';

    // ── 1. 主操作卡 ──
    var actionCfg = _getActionConfig(sigType, ov);
    html += '<div class="gem-action-card" style="' + actionCfg.cardStyle + '">';
    html += '  <div class="gem-action-header">';
    html += '    <div class="gem-action-badge" style="' + actionCfg.badgeStyle + '">' + actionCfg.badge + '</div>';
    html += '    <div class="gem-action-title" style="color:' + actionCfg.color + ';">' + actionCfg.title + '</div>';
    html += '    <div class="gem-action-sub">' + actionCfg.subtitle + '</div>';
    html += '  </div>';

    // 执行步骤
    if (actionCfg.steps.length > 0) {
        html += '  <div class="gem-action-steps">';
        for (var i = 0; i < actionCfg.steps.length; i++) {
            html += '    <div class="gem-action-step">';
            html += '      <span class="gem-step-num">' + (i + 1) + '</span>';
            html += '      <span>' + actionCfg.steps[i] + '</span>';
            html += '    </div>';
        }
        html += '  </div>';
    }
    html += '</div>';

    // ── 2. 上下文警告条 ──
    var alerts = _collectAlerts(ov);
    if (alerts.length > 0) {
        html += '<div class="gem-alerts-row">';
        for (var j = 0; j < alerts.length; j++) {
            var a = alerts[j];
            html += '<div class="gem-alert-chip" style="background:' + a.bg + '; border-color:' + a.border + '; color:' + a.color + ';">';
            html += '  <span>' + a.icon + '</span> ' + a.text;
            html += '</div>';
        }
        html += '</div>';
    }

    panel.innerHTML = html;
    panel.style.display = 'block';
}

function _getActionConfig(sigType, ov) {
    var weights = ov.target_weights || {};
    var entries = Object.entries(weights).filter(function(e) { return e[1] > 0; });
    var assetList = entries.map(function(e) {
        var name = _codeName(e[0], null);
        return name + ' ' + e[1] + '%';
    }).join(' · ');
    var aiae = ov.aiae || {};
    var rfRate = (ov.risk_free_rate || 1.5).toFixed(1);
    var bestRet = (ov.best_12m_return || 0).toFixed(1);
    var aiaeV1 = aiae.aiae_v1 != null ? Number(aiae.aiae_v1).toFixed(1) : '?';
    var marginHeat = aiae.margin_heat != null ? Number(aiae.margin_heat).toFixed(1) : '?';
    var r4Thresh = aiae.r4_threshold || 23;
    var r5Thresh = aiae.r5_threshold || 30;

    // ── R4 比例限仓信号 ──
    if (sigType === 'buy' && aiae.r4_capped) {
        var gemCap = aiae.gem_cap || 0;
        var preCap = aiae.pre_cap_pos || 0;
        return {
            badge: '⚠️ R4 限仓信号',
            title: '持有 ' + (ov.selected_asset || '—') + ' · 仓位压缩至 ' + gemCap + '%',
            subtitle: 'AIAE R4 偏热 (V1=' + aiaeV1 + '%): 矩阵仓位 ' + (aiae.matrix_pos || 0) + '% × GEM配额 ' + (aiae.gem_alloc || 0) + '% = 上限 ' + gemCap + '%',
            color: '#fb923c',
            cardStyle: 'background:linear-gradient(135deg,rgba(249,115,22,0.08),rgba(20,24,34,0.6)); border-color:rgba(249,115,22,0.3);',
            badgeStyle: 'background:rgba(249,115,22,0.15); border-color:rgba(249,115,22,0.3); color:#fb923c;',
            steps: [
                'AIAE R4 比例限仓: 建议仓位 ' + preCap + '% → 压缩至 <strong>' + gemCap + '%</strong>，剩余资金转入银华日利 (511880)',
                '按目标权重配置: <strong>' + (assetList || '待确认') + '</strong>，严禁超配',
                '降温触发: AIAE 回落至 <strong>' + (r4Thresh - 2) + '%</strong> 以下 → 解除限仓；升至 <strong>' + r5Thresh + '%+</strong> → 触发 R5 清仓',
                '月度复查清单: · AIAE 环比斜率 > +1.5pt 需立即减仓 · 融资占比 > 3.0% 需提高警觉 · 当前融资占比: ' + marginHeat + '%',
            ],
        };
    }

    // ── 正常 BUY 信号 (增强版) ──
    if (sigType === 'buy') {
        var steps = [];
        steps.push('确认 AIAE 主控仓位 ≤ ' + (ov.regime_cap || 70) + '% (当前 Regime: ' + (ov.regime || 'RANGE') + ', AIAE R' + (aiae.regime || '?') + ' = ' + aiaeV1 + '%)');
        if (entries.length > 0) {
            steps.push('按目标权重配置: <strong>' + assetList + '</strong>');
        }
        if (ov.vol_scale && ov.vol_scale.active) {
            steps.push('VolTarget 触发缩放 → 实际仓位乘以 ' + ((ov.vol_scale.scale || 1) * 100).toFixed(0) + '%, 剩余配现金');
        }
        steps.push('止盈纪律: 9M 回报 > 30% 时考虑部分获利了结，追踪 AIAE 斜率变化');
        steps.push('月度定检: GEM 为月度调仓策略，每月 1 号复查信号，避免日内追踪');
        return {
            badge: '📈 BUY 买入信号',
            title: '持有 ' + (ov.selected_asset || '—'),
            subtitle: '总仓位 ' + (ov.total_position || 0) + '% · 综合评分 ' + (ov.composite_score || 0).toFixed(1) + '/100',
            color: '#34d399',
            cardStyle: 'background:linear-gradient(135deg,rgba(16,185,129,0.08),rgba(20,24,34,0.6)); border-color:rgba(16,185,129,0.3);',
            badgeStyle: 'background:rgba(16,185,129,0.15); border-color:rgba(16,185,129,0.3); color:#34d399;',
            steps: steps,
        };
    } else if (sigType === 'fallthrough_6040') {
        return {
            badge: '🛡️ 60/40 防御信号',
            title: '全资产负收益 · 启用 60/40 防御组合',
            subtitle: '沪深300 60% + 黄金ETF 40%',
            color: '#fbbf24',
            cardStyle: 'background:linear-gradient(135deg,rgba(245,158,11,0.08),rgba(20,24,34,0.6)); border-color:rgba(245,158,11,0.3);',
            badgeStyle: 'background:rgba(245,158,11,0.15); border-color:rgba(245,158,11,0.3); color:#fbbf24;',
            steps: [
                '全部权益类资产 9M 回报为负 → 触发股债双杀防御',
                '按 60/40 配置: <strong>沪深300 60% + 黄金ETF 40%</strong>',
                '复查清单: · 9M 最优资产回报转正 · 沪深300 站稳 SMA200 · 跳出条件满足 2 项以上方可恢复正常配置',
            ],
        };
    } else {
        // ── CASH 信号 (增强版: 区分触发原因, 提供可观察复查清单) ──
        var reason, stepsArr;

        if (aiae.forced_cash) {
            // R5 强制现金
            reason = aiae.reason || 'AIAE R5 极端过热: 强制清仓权益类';
            stepsArr = [
                '清仓所有权益类持仓 → 转入 <strong>银华日利 (511880)</strong> 或活期理财',
                '严禁抄底: AIAE > ' + r5Thresh + '% 且绝对动量未确认前禁止入场',
                '复查清单 (至少满足 3 项方可入场): '
                    + '<br>　① AIAE 月度值回落至 <strong>' + r4Thresh + '%</strong> 以下 (当前: ' + aiaeV1 + '%)'
                    + '<br>　② 沪深300 价格站稳 200日均线 (SMA200)'
                    + '<br>　③ 9M 最优资产回报 > Shibor 1Y ' + rfRate + '% (当前: ' + bestRet + '%)'
                    + '<br>　④ 融资占比回落至 2.0% 以下 (当前: ' + marginHeat + '%)',
                '操作纪律: 连续 <strong>2 个月</strong>满足上述条件中的 3 项以上再入场，单月触发不作数',
            ];
        } else if (ov.market_stress) {
            // 全市场压力
            reason = '全市场压力: 所有资产 9M 回报均为负';
            stepsArr = [
                '清仓所有权益类持仓 → 转入 <strong>银华日利 (511880)</strong>',
                '股债双杀环境下严禁抄底，等待市场出清',
                '复查清单: '
                    + '<br>　① 9M 最优资产回报转正 (当前: ' + bestRet + '%)'
                    + '<br>　② 7M 确认窗口回报同步转正'
                    + '<br>　③ 沪深300 站稳 SMA200 均线',
                '操作纪律: 连续 2 月绝对动量通过 + 双窗口一致方可入场',
            ];
        } else {
            // 绝对动量未通过
            reason = '绝对动量未通过 (最优资产 9M 回报 ' + bestRet + '% ≤ Shibor 1Y ' + rfRate + '%)';
            stepsArr = [
                '清仓所有权益类持仓 → 转入 <strong>银华日利 (511880)</strong> 或活期理财',
                '不要抄底: 绝对动量未确认前禁止入场',
                '复查清单: '
                    + '<br>　① 9M 最优资产回报 > Shibor 1Y ' + rfRate + '% (当前: ' + bestRet + '%)'
                    + '<br>　② 7M 确认窗口回报同步转正'
                    + '<br>　③ 沪深300 站稳 SMA200 均线',
                '操作纪律: 连续 <strong>2 个月</strong>绝对动量通过 + 双窗口一致方可入场',
            ];
        }

        return {
            badge: '🔴 CASH 防御信号',
            title: '全仓现金 · 等待动量恢复',
            subtitle: reason,
            color: '#f87171',
            cardStyle: 'background:linear-gradient(135deg,rgba(239,68,68,0.08),rgba(20,24,34,0.6)); border-color:rgba(239,68,68,0.3);',
            badgeStyle: 'background:rgba(239,68,68,0.15); border-color:rgba(239,68,68,0.3); color:#f87171;',
            steps: stepsArr,
        };
    }
}

function _collectAlerts(ov) {
    var alerts = [];

    // Whipsaw
    var ws = ov.whipsaw || {};
    if (ws.active) {
        alerts.push({icon:'⚡', text:'Whipsaw 保护: ' + (ws.message || '连续换仓, 延迟确认中'),
            bg:'rgba(245,158,11,0.08)', border:'rgba(245,158,11,0.2)', color:'#fbbf24'});
    }

    // AIAE
    var aiae = ov.aiae || {};
    if (aiae.active && aiae.regime >= 4) {
        alerts.push({icon:'🚨', text:'AIAE R' + aiae.regime + ' 强制防御: 禁止持有权益类',
            bg:'rgba(239,68,68,0.1)', border:'rgba(239,68,68,0.25)', color:'#f87171'});
    } else if (aiae.active && aiae.cap_applied) {
        alerts.push({icon:'📉', text:'AIAE 仓位约束: ' + aiae.pre_cap_pos + '% → ' + (ov.total_position || 0) + '%',
            bg:'rgba(245,158,11,0.08)', border:'rgba(245,158,11,0.2)', color:'#fbbf24'});
    }

    // VolTarget
    var vol = ov.vol_scale || {};
    if (vol.active) {
        alerts.push({icon:'📊', text:'VolTarget 触发: 组合波动 ' + (vol.port_vol || 0).toFixed(1) + '% > 14% → 缩放至 ' + ((vol.scale || 1) * 100).toFixed(0) + '%',
            bg:'rgba(14,165,233,0.08)', border:'rgba(14,165,233,0.2)', color:'#38bdf8'});
    }

    // Dual window disagreement
    if (!ov.signals_agree && ov.signal_type === 'buy') {
        alerts.push({icon:'⚠️', text:'双窗口分歧: 9M与7M最优资产不一致 · 信念度降至 ' + ((ov.conviction || 0) * 100).toFixed(0) + '%',
            bg:'rgba(139,92,246,0.08)', border:'rgba(139,92,246,0.2)', color:'#a78bfa'});
    }

    // SMA filtered
    if (ov.sma_filter_active) {
        var filtered = ov.sma_filtered || {};
        var failed = Object.entries(filtered).filter(function(e) { return !e[1]; });
        if (failed.length > 0) {
            var names = failed.map(function(e) { return _codeName(e[0], null); }).join(', ');
            alerts.push({icon:'📉', text:'SMA-200 过滤: ' + names + ' 价格低于均线已剔除',
                bg:'rgba(100,116,139,0.08)', border:'rgba(100,116,139,0.2)', color:'#94a3b8'});
        }
    }

    // Regime warning
    if (ov.regime === 'BEAR' || ov.regime === 'CRASH') {
        var icon = ov.regime === 'CRASH' ? '💀' : '🔴';
        alerts.push({icon:icon, text:ov.regime + ' 状态: 仓位上限 ' + (ov.regime_cap || 0) + '% · 控制风险敞口',
            bg:'rgba(239,68,68,0.08)', border:'rgba(239,68,68,0.2)', color:'#f87171'});
    }

    return alerts;
}

// ═══════════════════════════════════════════
//  私有 Helpers
// ═══════════════════════════════════════════
function _set(id, text, color) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (color) el.style.color = color;
}

function _showError(el, msg) {
    if (el) el.innerHTML = '<span style="color:#f87171;">❌ ' + msg + '</span>';
}

function _scoreColor(score) {
    if (score >= 80) return '#34d399';
    if (score >= 60) return '#38bdf8';
    if (score >= 40) return '#fbbf24';
    return '#f87171';
}

function _codeName(code, signals) {
    if (signals) {
        var s = signals.find(function(x) { return x.ts_code === code || x.code === code; });
        if (s) return s.name;
    }
    var map = {
        '510300.SH':'沪深300', '510500.SH':'中证500', '159915.SZ':'创业板',
        '513500.SH':'标普500', '159941.SZ':'纳指', '513000.SH':'日经',
        '518880.SH':'黄金', '511880.SH':'银华日利'
    };
    return map[code] || code;
}

})();
