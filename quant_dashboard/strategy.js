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
    const results = document.getElementById('st-results');
    const timeEl = document.getElementById('st-data-time');

    // 禁用按钮 + 显示加载
    btn.disabled = true;
    btn.textContent = '⏳ 运行中...';
    loading.style.display = 'flex';
    results.style.display = 'none';

    try {
        const resp = await fetch(`${API_URL}/api/v1/strategy`);
        const json = await resp.json();

        if (json.status !== 'success') {
            throw new Error(json.message || '策略执行失败');
        }

        const data = json.data;
        const ov = data.market_overview;

        // 更新数据时间
        timeEl.textContent = `数据截至 ${json.timestamp.substring(0, 16).replace('T', ' ')}`;

        // 渲染市场概览
        document.getElementById('ov-avg-dev').textContent = ov.avg_deviation + '%';
        document.getElementById('ov-max-dev').innerHTML = `${ov.max_deviation.name}<br><small style="color:var(--text-muted)">${ov.max_deviation.value}%</small>`;
        document.getElementById('ov-buy-count').textContent = ov.signal_count.buy;
        document.getElementById('ov-sell-count').textContent = ov.signal_count.sell;
        document.getElementById('ov-total-pos').textContent = ov.total_suggested_position + '%';
        document.getElementById('ov-above3').textContent = `${ov.above_3pct}只 · ${ov.market_divergence}`;

        // 渲染买入信号列表
        renderActionList('st-buy-list', data.buy_signals, 'buy');
        renderActionList('st-sell-list', data.sell_signals, 'sell');

        // 渲染完整信号表
        renderSignalTable(data.signals);
        document.getElementById('st-total-count').textContent = data.signals.length;

        // 错误信息
        if (data.errors && data.errors.length > 0) {
            const errDiv = document.getElementById('st-errors');
            errDiv.style.display = 'block';
            document.getElementById('st-error-list').innerHTML = data.errors.map(e =>
                `<p style="font-size:0.82rem;color:var(--text-muted);padding:4px 0;">${e.code} ${e.name}: ${e.error}</p>`
            ).join('');
        }

        loading.style.display = 'none';
        results.style.display = 'block';

    } catch (err) {
        loading.style.display = 'none';
        results.style.display = 'block';
        document.getElementById('st-table-body').innerHTML =
            `<tr><td colspan="12" style="text-align:center;color:#ef4444;padding:40px;">❌ ${err.message}<br><small style="color:var(--text-muted)">请确认后端已启动：python main.py</small></td></tr>`;
    } finally {
        btn.disabled = false;
        btn.textContent = '🚀 运行策略';
    }
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
    
    tbody.innerHTML = signals.map(s => {
        const rowClass = s.signal === 'buy' ? 'st-row-buy' : (s.signal === 'sell' || s.signal === 'sell_weak' ? 'st-row-sell' : '');
        const signalTag = getSignalTag(s.signal);

        return `<tr class="${rowClass}">
            <td style="font-weight:600;color:#fff">${s.name}</td>
            <td style="font-family:monospace;color:#60a5fa;font-size:0.75rem">${s.code}</td>
            <td>${s.close}</td>
            <td style="color:${s.deviation >= 3 ? '#fbbf24' : 'inherit'};font-weight:${s.deviation >= 3 ? '700' : '400'}">${s.deviation}%</td>
            <td style="color:${s.rsi <= 28 ? '#10b981' : (s.rsi >= 72 ? '#ef4444' : 'inherit')}">${s.rsi}</td>
            <td>${signalTag}</td>
            <td style="font-weight:600">${s.suggested_position > 0 ? s.suggested_position + '%' : '—'}</td>
        </tr>`;
    }).join('');
}

function getSignalTag(signal) {
    const map = {
        'buy': '<span class="st-signal-tag st-tag-buy">🟢 买入</span>',
        'sell': '<span class="st-signal-tag st-tag-sell">🔴 卖出</span>',
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
