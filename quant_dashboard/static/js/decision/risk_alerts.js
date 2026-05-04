/**
 * AlphaCore V21.2 · 风险面板 + 预警模块
 * ======================================
 * - 投委会日报 (generateReport / showReportModal / downloadReport)
 * - 相关性热力图 + MCTR 风险贡献 (loadCorrelationMatrix)
 * - 信号预警系统 (pollAlerts / renderAlertPanel / showAlertToast)
 * - 数据新鲜度状态栏 (renderFreshnessBar / startAlertPolling)
 *
 * 依赖: _getChart, _fmt, API_BASE (from _infra.js)
 */
// ═══════════════════════════════════════════════════
//  V21.0: 投委会日报生成器
// ═══════════════════════════════════════════════════

let _currentReportMarkdown = '';
let _currentReportDate = '';

async function generateReport() {
    const btn = document.getElementById('btn-daily-report');
    const origText = btn.textContent;
    btn.textContent = '⏳ 生成中...';
    btn.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/daily-report`, {
            signal: AbortSignal.timeout(20000),
        });
        const data = await resp.json();
        if (data.status === 'success' && data.markdown) {
            _currentReportMarkdown = data.markdown;
            _currentReportDate = data.date || new Date().toISOString().slice(0, 10);
            showReportModal(data.markdown);
        } else {
            alert(`日报生成失败: ${data.error || '未知错误'}`);
        }
    } catch (e) {
        if (e.name === 'TimeoutError') {
            alert('日报生成超时，请稍后重试');
        } else {
            console.error('Report generation failed:', e);
            alert('日报生成异常，请检查服务器状态');
        }
    } finally {
        btn.textContent = origText;
        btn.disabled = false;
    }
}

function showReportModal(markdown) {
    const overlay = document.getElementById('report-overlay');
    const content = document.getElementById('report-content');
    content.textContent = markdown;
    overlay.classList.add('active');
    // ESC 关闭
    document.addEventListener('keydown', _reportEscHandler);
}

function closeReportModal(e) {
    // 如果是点击事件，只有点击 overlay 本身才关闭
    if (e && e.target && !e.target.classList.contains('report-overlay')) return;
    const overlay = document.getElementById('report-overlay');
    overlay.classList.remove('active');
    document.removeEventListener('keydown', _reportEscHandler);
}

function _reportEscHandler(e) {
    if (e.key === 'Escape') closeReportModal();
}

async function copyReport() {
    const btn = document.getElementById('btn-copy-report');
    try {
        await navigator.clipboard.writeText(_currentReportMarkdown);
        btn.textContent = '✅ 已复制';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.textContent = '📋 复制全文';
            btn.classList.remove('copied');
        }, 2000);
    } catch (e) {
        // Fallback: textarea copy
        const ta = document.createElement('textarea');
        ta.value = _currentReportMarkdown;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        btn.textContent = '✅ 已复制';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.textContent = '📋 复制全文';
            btn.classList.remove('copied');
        }, 2000);
    }
}

function downloadReport() {
    const blob = new Blob([_currentReportMarkdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `AlphaCore_日报_${_currentReportDate}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}


// ═══════════════════════════════════════════════════
//  V21.1: 持仓相关性热力图 + MCTR 风险贡献
// ═══════════════════════════════════════════════════

let _corrLoaded = false;

async function loadCorrelationMatrix() {
    if (_corrLoaded) return;
    try {
        const resp = await fetch(`${API_BASE}/correlation-matrix`);
        const data = await resp.json();
        if (data.status === 'success') {
            renderCorrHeatmap(data);
            renderMCTRBar(data);
            renderHighCorrPairs(data.high_corr_pairs || []);
            _corrLoaded = true;
        } else {
            const msg = data.message || '持仓不足';
            _showCorrEmpty('corr-heatmap-chart', msg);
            _showCorrEmpty('mctr-bar-chart', msg);
        }
    } catch (e) {
        console.warn('Correlation load:', e);
        _showCorrEmpty('corr-heatmap-chart', '加载异常');
        _showCorrEmpty('mctr-bar-chart', '加载异常');
    }
}

function _showCorrEmpty(domId, msg) {
    const el = document.getElementById(domId);
    if (el) el.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:0.85rem;">${msg}</div>`;
}

function renderCorrHeatmap(data) {
    const chart = _getChart('corr-heatmap-chart');
    if (!chart) return;

    const names = data.names.map(n => n.length > 6 ? n.slice(0, 5) + '…' : n);
    const fullNames = data.names;
    const matrix = data.correlation_matrix;
    const n = names.length;

    // 转换为 ECharts heatmap 数据: [x, y, value]
    const heatData = [];
    for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
            heatData.push([j, i, matrix[i][j]]);
        }
    }

    chart.setOption({
        tooltip: {
            formatter: p => {
                const xi = p.data[0], yi = p.data[1], v = p.data[2];
                const level = Math.abs(v) > 0.9 ? '🔴 极高' : Math.abs(v) > 0.7 ? '🟠 高' : Math.abs(v) > 0.4 ? '🟡 中' : '🟢 低';
                return `<b>${fullNames[yi]}</b> ↔ <b>${fullNames[xi]}</b><br/>ρ = ${v.toFixed(3)}<br/>相关性: ${level}`;
            }
        },
        grid: { left: 90, right: 20, top: 10, bottom: 60 },
        xAxis: {
            type: 'category', data: names, position: 'bottom',
            axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 30 },
            axisTick: { show: false }, axisLine: { show: false },
        },
        yAxis: {
            type: 'category', data: names,
            axisLabel: { color: '#94a3b8', fontSize: 10 },
            axisTick: { show: false }, axisLine: { show: false },
        },
        visualMap: {
            min: -1, max: 1, calculable: false, show: true,
            orient: 'horizontal', left: 'center', bottom: 0,
            itemWidth: 12, itemHeight: 100,
            textStyle: { color: '#64748b', fontSize: 10 },
            inRange: {
                color: ['#3b82f6', '#60a5fa', '#cbd5e1', '#fbbf24', '#f97316', '#ef4444']
            }
        },
        series: [{
            type: 'heatmap', data: heatData,
            itemStyle: { borderColor: '#1e2235', borderWidth: 2, borderRadius: 3 },
            label: {
                show: n <= 8,
                formatter: p => p.data[2].toFixed(2),
                fontSize: 10, color: '#e2e8f0',
            },
            emphasis: {
                itemStyle: { borderColor: '#a78bfa', borderWidth: 2 }
            }
        }]
    });
}

function renderMCTRBar(data) {
    const chart = _getChart('mctr-bar-chart');
    if (!chart) return;

    const details = data.mctr_details;
    const names = details.map(d => d.name.length > 8 ? d.name.slice(0, 7) + '…' : d.name);
    const fullNames = details.map(d => d.name);
    const rcs = details.map(d => d.risk_contribution);
    const weights = details.map(d => d.weight);
    const mctrs = details.map(d => d.mctr);
    const industries = details.map(d => d.industry);

    // 风险贡献 vs 权重 差异 → 颜色
    const barColors = details.map(d => {
        const ratio = d.weight > 0 ? d.risk_contribution / d.weight : 1;
        if (ratio > 1.5) return '#ef4444';      // 风险贡献远超权重
        if (ratio > 1.1) return '#f97316';      // 略超
        if (ratio > 0.9) return '#a78bfa';      // 均衡
        return '#34d399';                        // 风险贡献低于权重 (分散化良好)
    });

    // ECharts bar chart: Y轴从下到上, 需反转使最大风险贡献在顶部
    const rNames = [...names].reverse();
    const rRcs = [...rcs].reverse();
    const rBarColors = [...barColors].reverse();
    const rWeights = [...weights].reverse();

    chart.setOption({
        tooltip: {
            formatter: p => {
                const ri = p.dataIndex;
                const oi = details.length - 1 - ri;  // 原始索引
                const ratio = weights[oi] > 0 ? (rcs[oi] / weights[oi]).toFixed(2) : '--';
                const riskLabel = ratio > 1.5 ? '⚠️ 风险集中' : ratio > 1.1 ? '🟡 略高' : ratio < 0.9 ? '🟢 分散化' : '均衡';
                return `<b>${fullNames[oi]}</b> (${industries[oi]})<br/>` +
                    `风险贡献: <b>${rcs[oi].toFixed(1)}%</b><br/>` +
                    `仓位权重: ${weights[oi].toFixed(1)}%<br/>` +
                    `MCTR: ${mctrs[oi].toFixed(4)}<br/>` +
                    `贡献/权重: ${ratio}x ${riskLabel}`;
            }
        },
        grid: { left: 90, right: 60, top: 20, bottom: 30 },
        xAxis: {
            type: 'value',
            axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
            splitLine: { lineStyle: { color: 'rgba(148,163,184,0.08)' } },
        },
        yAxis: {
            type: 'category', data: rNames,
            axisLabel: { color: '#cbd5e1', fontSize: 11 },
            axisTick: { show: false }, axisLine: { show: false },
        },
        series: [{
            type: 'bar', data: rRcs.map((v, i) => ({
                value: v,
                itemStyle: { color: rBarColors[i], borderRadius: [0, 4, 4, 0] }
            })),
            barWidth: '55%',
            label: {
                show: true, position: 'right',
                formatter: p => `${p.value.toFixed(1)}%`,
                fontSize: 10, color: '#94a3b8',
            },
        },
        // 参考线: 仓位权重 (菱形散点)
        {
            type: 'scatter', symbol: 'diamond', symbolSize: 8,
            data: rWeights,
            itemStyle: { color: 'rgba(148,163,184,0.5)' },
            tooltip: { formatter: p => `仓位权重: ${p.value.toFixed(1)}%` },
        }]
    });
}

function renderHighCorrPairs(pairs) {
    const el = document.getElementById('corr-high-pairs');
    if (!el) return;
    if (!pairs || pairs.length === 0) {
        el.innerHTML = '<div class="corr-pairs-ok">🟢 未发现高相关持仓对 (|ρ| > 0.7)，分散化良好</div>';
        return;
    }
    let html = '<div class="corr-pairs-warn">⚠️ 高相关持仓对:</div><div class="corr-pairs-list">';
    pairs.forEach(p => {
        const cls = p.level === 'extreme' ? 'corr-pair-extreme' : 'corr-pair-high';
        html += `<span class="corr-pair-tag ${cls}">${p.a} ↔ ${p.b}: ρ=${p.corr.toFixed(2)}</span>`;
    });
    html += '</div>';
    el.innerHTML = html;
}


// ═══════════════════════════════════════════════════
//  V21.2: 信号预警系统
// ═══════════════════════════════════════════════════

let _lastAlertIds = new Set();
let _alertPollTimer = null;

async function pollAlerts() {
    try {
        const resp = await fetch(`${API_BASE}/alerts?limit=20`);
        const data = await resp.json();
        if (data.status !== 'success') return;

        // 更新 badge
        const badge = document.getElementById('alert-badge');
        if (badge) {
            if (data.unread_count > 0) {
                badge.textContent = data.unread_count > 99 ? '99+' : data.unread_count;
                badge.style.display = '';
            } else {
                badge.style.display = 'none';
            }
        }

        // 检测新预警 → Toast
        const alerts = data.alerts || [];
        alerts.forEach(a => {
            if (!a.acknowledged && !_lastAlertIds.has(a.id)) {
                showAlertToast(a);
            }
        });
        _lastAlertIds = new Set(alerts.map(a => a.id));

        // 更新面板内容
        renderAlertPanel(alerts);
    } catch (e) {
        console.warn('Alert poll error:', e);
    }
}

function renderAlertPanel(alerts) {
    const el = document.getElementById('alert-list');
    if (!el) return;
    if (!alerts || alerts.length === 0) {
        el.innerHTML = '<div style="text-align:center;padding:20px;color:#64748b;font-size:0.82rem;">暂无预警</div>';
        return;
    }
    let html = '';
    alerts.forEach(a => {
        const severityCls = a.severity === 'critical' ? 'alert-item-critical' : 'alert-item-warning';
        const readCls = a.acknowledged ? 'alert-item-read' : '';
        const timeStr = a.created_at ? a.created_at.replace('T', ' ').slice(0, 16) : '';
        html += `<div class="alert-item ${severityCls} ${readCls}" onclick="ackAlert(${a.id}, this)">
            <div class="alert-item-title">${a.title}</div>
            <div class="alert-item-detail">${a.detail}</div>
            <div class="alert-item-meta">${timeStr} · ${a.acknowledged ? '已读' : '未读'}</div>
        </div>`;
    });
    el.innerHTML = html;
}

function toggleAlertPanel() {
    const panel = document.getElementById('alert-panel');
    if (panel) {
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
}

// 点击外部关闭面板
document.addEventListener('click', e => {
    const wrap = document.getElementById('alert-bell-wrap');
    const panel = document.getElementById('alert-panel');
    if (wrap && panel && !wrap.contains(e.target)) {
        panel.style.display = 'none';
    }
});

async function ackAlert(id, el) {
    try {
        await fetch(`${API_BASE}/alerts/${id}/ack`, { method: 'POST' });
        if (el) el.classList.add('alert-item-read');
        pollAlerts(); // 刷新 badge
    } catch (e) { console.warn('Ack error:', e); }
}

async function ackAllAlerts() {
    try {
        await fetch(`${API_BASE}/alerts/ack-all`, { method: 'POST' });
        pollAlerts();
    } catch (e) { console.warn('Ack all error:', e); }
}

function showAlertToast(alert) {
    const container = document.getElementById('alert-toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `alert-toast alert-toast-${alert.severity || 'warning'}`;
    toast.innerHTML = `
        <div class="alert-toast-title">${alert.title}</div>
        <div class="alert-toast-body">${alert.detail}</div>
        <button class="alert-toast-close" onclick="this.parentElement.remove()">✕</button>
    `;
    container.appendChild(toast);
    // 触发动画
    requestAnimationFrame(() => toast.classList.add('alert-toast-show'));
    // 8 秒后自动消失
    setTimeout(() => {
        toast.classList.remove('alert-toast-show');
        setTimeout(() => toast.remove(), 400);
    }, 8000);
}

// ═══════════════════════════════════════════════════════
//  V21.2: 数据新鲜度状态栏
// ═══════════════════════════════════════════════════════
function renderFreshnessBar(freshness, timestamp, dataDate, dateConsistent) {
    const bar = document.getElementById('data-freshness-bar');
    if (!bar) return;

    const time = timestamp ? new Date(timestamp).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}) : '--:--';
    const pills = Object.entries(freshness).map(([key, f]) => {
        const isOk = f.status === 'ok';
        const icon = isOk ? '✅' : '⚠️';
        const cls = isOk ? 'fresh-ok' : 'fresh-stale';
        const ageStr = isOk && f.age_min >= 0 ? `${f.age_min}m` : '—';
        const dateInfo = f.data_date ? ` [${f.data_date}]` : '';
        return `<span class="fresh-pill ${cls}" title="${f.label}: ${isOk ? ageStr + ' ago' : '数据缺失'}${dateInfo}">${icon} ${f.label}</span>`;
    }).join('');

    // 交易日标识 + 跨引擎日期一致性警告
    const dateBadge = dataDate ? `<span class="fresh-date">📅 ${dataDate}</span>` : '';
    const warnBadge = dateConsistent === false ? '<span class="fresh-pill fresh-stale" title="各引擎数据日期不一致">⚠️ 日期错配</span>' : '';

    bar.innerHTML = `<span class="fresh-time">🕐 数据截至 ${time}</span>${dateBadge}${pills}${warnBadge}`;
}

function startAlertPolling() {
    pollAlerts(); // 立即执行一次
    _alertPollTimer = setInterval(pollAlerts, 60000); // 每 60 秒轮询
}

