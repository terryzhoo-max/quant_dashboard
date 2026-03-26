// AlphaCore · 策略中心页面 JS
const API_URL = 'http://127.0.0.1:8000';

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
