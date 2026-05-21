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
            _showError(status, json.message || '加载失败');
            return;
        }

        _gemCache = json;
        renderGemStrategy(json);

        var now = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        if (status) status.innerHTML = '<span style="color:#34d399;">✅ 已加载</span> · ' + now;
    } catch (e) {
        console.error('[GEM] load error:', e);
        _showError(status, e.message);
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
//  Zone 1.5: 5维评分
// ═══════════════════════════════════════════
function _renderScoreDimensions(ov) {
    var dims = ov.score_dimensions || {};
    var composite = ov.composite_score || 0;

    // 各维度分数
    var d = {
        excess:     dims.excess_return  || {},
        conviction: dims.conviction     || {},
        rank:       dims.rank_quality   || {},
        breadth:    dims.breadth        || {},
        mdd:        dims.mdd_penalty    || {},
    };

    _set('gem-d-excess',     (d.excess.score || 0).toFixed(0));
    _set('gem-d-conviction', (d.conviction.score || 0).toFixed(0));
    _set('gem-d-rank',       (d.rank.score || 0).toFixed(0));
    _set('gem-d-breadth',    (d.breadth.score || 0).toFixed(0));
    _set('gem-d-mdd',        (d.mdd.score || 0).toFixed(0));

    // 综合评分
    _set('gem-score-value', composite.toFixed(1), _scoreColor(composite));
    var bar = document.getElementById('gem-score-bar');
    if (bar) bar.style.width = Math.min(composite, 100) + '%';
}

// ═══════════════════════════════════════════
//  Zone 2: 12列资产排行表
// ═══════════════════════════════════════════
function _renderAssetTable(signals) {
    var tbody = document.getElementById('gem-asset-tbody');
    if (!tbody) return;

    if (!signals.length) {
        tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; color:#64748b;">无数据</td></tr>';
        return;
    }

    tbody.innerHTML = signals.map(function(s, i) {
        var isBuy = s.signal === 'buy';
        var rowBg = isBuy ? 'background:rgba(16,185,129,0.04);' : '';
        var rankColor = i < 2 ? '#fbbf24' : '#64748b';

        var sigBadge = isBuy
            ? '<span class="st-signal-tag st-tag-buy">● BUY</span>'
            : (s.signal === 'cash'
                ? '<span class="st-signal-tag st-tag-sell">◆ CASH</span>'
                : '<span class="st-signal-tag st-tag-hold">○ HOLD</span>');

        var mkt = s.market === 'CN' ? '🇨🇳' : (s.market === 'US' ? '🇺🇸' : (s.market === 'JP' ? '🇯🇵' : '🏳️'));
        var ret9m = (s.return_12m || 0);
        var ret7m = s.return_6m != null ? s.return_6m : 0;
        var retColor = function(v) { return v > 0 ? '#34d399' : (v < 0 ? '#f87171' : '#94a3b8'); };
        var haircut = s.qdii_haircut || 0;
        var weight = s.target_weight || 0;

        return '<tr style="' + rowBg + '">' +
            '<td style="font-weight:800; color:' + rankColor + ';">' + (i + 1) + '</td>' +
            '<td style="font-family:\'Outfit\',monospace; font-size:0.75rem; color:#94a3b8;">' + ((s.ts_code || '').split('.')[0]) + '</td>' +
            '<td style="font-weight:600; color:#e2e8f0;">' + (s.name || '') + '</td>' +
            '<td style="font-size:0.75rem;">' + mkt + '</td>' +
            '<td style="color:' + retColor(ret9m) + '; font-weight:700;">' + ret9m.toFixed(1) + '%</td>' +
            '<td style="color:' + retColor(ret7m) + '; font-size:0.78rem;">' + ret7m.toFixed(1) + '%</td>' +
            '<td style="color:#38bdf8; font-weight:600;">' + (s.sharpe || 0).toFixed(2) + '</td>' +
            '<td style="color:#94a3b8;">' + (s.vol_ann || 0).toFixed(1) + '%</td>' +
            '<td style="color:#f87171;">' + (s.mdd || 0).toFixed(1) + '%</td>' +
            '<td style="color:' + (haircut > 0 ? '#fb923c' : '#475569') + '; font-size:0.75rem;">' + (haircut > 0 ? '-' + haircut.toFixed(1) + '%' : '—') + '</td>' +
            '<td>' + sigBadge + '</td>' +
            '<td style="font-weight:700; color:' + (weight > 0 ? '#38bdf8' : '#475569') + ';">' + (weight > 0 ? weight.toFixed(1) + '%' : '—') + '</td>' +
        '</tr>';
    }).join('');
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
