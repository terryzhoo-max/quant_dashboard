/**
 * strategy_gem.js — GEM 双重动量策略 V3.0 前端渲染
 *
 * API: GET /api/v1/gem_strategy
 * 数据路径: response.data.market_overview / response.data.signals
 */

// IIFE 避免与 strategy.js 的全局 _setText 冲突
(function() {
'use strict';

let _gemCache = null;

// 暴露为全局函数供 HTML onclick 和 tab callback 调用
window.loadGemStrategy = async function(forceRefresh) {
    forceRefresh = forceRefresh || false;
    const btn = document.getElementById('gem-load-btn');
    const status = document.getElementById('gem-load-status');
    if (btn) btn.disabled = true;
    if (status) status.textContent = '⏳ 加载中...';

    try {
        const url = forceRefresh ? '/api/v1/gem_strategy?refresh=1' : '/api/v1/gem_strategy';
        const resp = await fetch(url);
        if (!resp.ok) {
            if (status) status.textContent = '❌ HTTP ' + resp.status;
            return;
        }
        const json = await resp.json();

        if (json.status !== 'success') {
            if (status) status.textContent = '❌ ' + (json.message || '加载失败');
            return;
        }

        _gemCache = json;
        renderGemStrategy(json);
        if (status) status.textContent = '✅ ' + new Date().toLocaleTimeString();
    } catch (e) {
        console.error('GEM load error:', e);
        if (status) status.textContent = '❌ 网络错误: ' + e.message;
    } finally {
        if (btn) btn.disabled = false;
    }
};

function renderGemStrategy(json) {
    const ov = json.data?.market_overview || {};
    const signals = json.data?.signals || [];

    // ── Hero stats ──
    const sigLabel = ov.signal_label || '—';
    const sigColor = ov.signal_type === 'buy' ? '#34d399' : (ov.signal_type === 'hold' ? '#fbbf24' : '#f87171');
    _set('gem-hero-signal', sigLabel, sigColor);
    _set('gem-hero-position', (ov.total_position || 0) + '%', '#34d399');
    _set('gem-hero-score', ov.composite_score || '—', '#fbbf24');

    // ── Signal grid ──
    _set('gem-sig-type', sigLabel, sigColor);
    _set('gem-sig-asset', ov.selected_asset || '—');
    _set('gem-sig-abs', ov.abs_momentum_pass ? '✓ 通过' : '✗ 未通过',
         ov.abs_momentum_pass ? '#34d399' : '#f87171');
    _set('gem-sig-dual', ov.conviction_label || '—',
         ov.signals_agree ? '#a78bfa' : '#f59e0b');

    // ── Target weights bars ──
    const wc = document.getElementById('gem-weights-bars');
    if (wc && ov.target_weights) {
        const entries = Object.entries(ov.target_weights).sort(function(a, b) { return b[1] - a[1]; });
        const colors = ['#38bdf8', '#34d399', '#fbbf24', '#a78bfa', '#f87171', '#fb923c', '#94a3b8'];
        wc.innerHTML = entries.map(function(entry, i) {
            var code = entry[0], pct = entry[1];
            const name = _codeName(code, signals);
            const color = colors[i % colors.length];
            return '<div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">' +
                '<div style="width:90px; font-size:0.72rem; color:#cbd5e1; text-align:right; white-space:nowrap;">' + name + '</div>' +
                '<div style="flex:1; height:22px; background:rgba(255,255,255,0.04); border-radius:6px; overflow:hidden; position:relative;">' +
                    '<div style="height:100%; width:' + pct + '%; background:' + color + '; border-radius:6px; transition:width 0.6s;"></div>' +
                '</div>' +
                '<div style="width:45px; font-size:0.78rem; font-weight:700; color:' + color + '; text-align:right;">' + pct + '%</div>' +
            '</div>';
        }).join('');
    }

    // ── V3.0 feature indicators ──
    // SMA
    const sma = ov.sma_filter_active;
    const smaFiltered = ov.sma_filtered || {};
    const smaFailed = Object.entries(smaFiltered).filter(function(e) { return !e[1]; }).map(function(e) { return _codeName(e[0], signals); });
    _set('gem-f-sma-icon', sma ? '✅' : '⏸️');
    _set('gem-f-sma-detail', sma
        ? (smaFailed.length > 0 ? '已过滤: ' + smaFailed.join(', ') : '全部资产价格 > SMA200 ✓')
        : '未启用');

    // VolTarget
    const vol = ov.vol_scale || {};
    _set('gem-f-vol-icon', vol.active ? '🔻' : '✅');
    _set('gem-f-vol-detail', vol.active
        ? '组合波动 ' + (vol.port_vol || 0).toFixed(1) + '% → 缩放 ' + ((vol.scale || 1) * 100).toFixed(0) + '%'
        : '组合波动率在目标范围内');

    // Dual confirm
    _set('gem-f-dual-icon', ov.signals_agree ? '✅' : '⚠️');
    _set('gem-f-dual-detail', ov.signals_agree
        ? '9M与7M窗口一致 · 信念度 ' + ((ov.conviction || 0) * 100).toFixed(0) + '%'
        : '9M与7M窗口不一致 · 降低信念');

    // Corr dedup
    _set('gem-f-corr-icon', '✅');
    _set('gem-f-corr-detail', 'SP500/NASDAQ 同组去重 · 最多选1');

    // ── Regime ──
    const regimeMap = { BULL: {icon:'🟢', color:'#34d399'}, RANGE: {icon:'🟡', color:'#fbbf24'}, BEAR: {icon:'🔴', color:'#f87171'}, CRASH: {icon:'💀', color:'#ef4444'} };
    const r = regimeMap[ov.regime] || regimeMap.RANGE;
    _set('gem-regime', r.icon + ' ' + (ov.regime || 'RANGE'), r.color);
    _set('gem-regime-cap', (ov.regime_cap || 0) + '%', '#fbbf24');

    // ── Asset table ──
    const tbody = document.getElementById('gem-asset-tbody');
    if (tbody) {
        tbody.innerHTML = signals.map(function(s, i) {
            const sigBadge = s.signal === 'buy'
                ? '<span style="color:#34d399; font-weight:700;">● BUY</span>'
                : '<span style="color:#64748b;">○ HOLD</span>';
            const mkt = s.market === 'CN' ? '🇨🇳' : (s.market === 'US' ? '🇺🇸' : (s.market === 'JP' ? '🇯🇵' : ''));
            const volDisplay = (s.vol_ann || 0).toFixed(1);
            return '<tr style="' + (s.signal === 'buy' ? 'background:rgba(16,185,129,0.04);' : '') + '">' +
                '<td style="font-weight:700; color:' + (i < 2 ? '#fbbf24' : '#64748b') + ';">' + (i + 1) + '</td>' +
                '<td style="font-family:\'Outfit\',monospace; font-size:0.78rem; color:#94a3b8;">' + ((s.ts_code || '').split('.')[0]) + '</td>' +
                '<td style="font-weight:600;">' + (s.name || '') + '</td>' +
                '<td>' + mkt + ' ' + (s.market || '') + '</td>' +
                '<td style="color:' + ((s.return_12m || 0) > 0 ? '#34d399' : '#f87171') + '; font-weight:700;">' + (s.return_12m || 0).toFixed(1) + '%</td>' +
                '<td style="color:#94a3b8;">' + volDisplay + '%</td>' +
                '<td style="color:#f87171;">' + (s.mdd || 0).toFixed(1) + '%</td>' +
                '<td>' + sigBadge + '</td>' +
                '<td style="font-weight:700; color:#38bdf8;">' + (s.signal_score || 0).toFixed(1) + '</td>' +
            '</tr>';
        }).join('');
    }
}

// ── 私有 helpers (不污染全局) ──
function _set(id, text, color) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (color) el.style.color = color;
}

function _codeName(code, signals) {
    var s = signals.find(function(x) { return x.ts_code === code || x.code === code; });
    if (s) return s.name;
    var map = {'510300.SH':'沪深300','510500.SH':'中证500','159915.SZ':'创业板','513500.SH':'标普500',
               '159941.SZ':'纳指','513000.SH':'日经','518880.SH':'黄金','511880.SH':'银华日利'};
    return map[code] || code;
}

})();
