/**
 * AlphaCore V21.2 · 波段守卫模块
 * ================================
 * - fetchSwingGuard (异步获取 + 重试)
 * - renderSwingGuard (卡片渲染)
 * - _updateSwingGuardFreshness (数据新鲜度标签)
 *
 * 依赖: API_BASE (from _infra.js)
 */
// ═══════════════════════════════════════════════════
//  Phase 2: 全球宽基波段守卫 (Swing Guard)
// ═══════════════════════════════════════════════════

async function fetchSwingGuard(retries = 2) {
    const grid = document.getElementById('swing-guard-grid');
    if (!grid) return;
    
    grid.innerHTML = '<div class="loading-spinner">⏳ 拉取7大ETF最新信号...</div>';
    
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            const resp = await AC.secureFetch(`${API_BASE}/swing-guard`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const result = await resp.json();
            
            if (result.status === 'success') {
                renderSwingGuard(result.data);
                // V2: 数据新鲜度标签
                _updateSwingGuardFreshness(result);
                return;
            } else {
                throw new Error(result.error || '后端返回失败');
            }
        } catch (e) {
            console.warn(`Swing Guard 第 ${attempt + 1} 次尝试失败:`, e.message);
            if (attempt < retries) {
                grid.innerHTML = `<div class="loading-spinner">⏳ 数据源冷启动中... 重试 ${attempt + 2}/${retries + 1}</div>`;
                await new Promise(r => setTimeout(r, 3000));
            } else {
                grid.innerHTML = `<div class="loading-spinner" style="display:flex;flex-direction:column;align-items:center;gap:12px;">
                    <span>⚠️ 波段守卫数据暂时不可用</span>
                    <span style="font-size:0.75rem;color:#64748b;">${e.message}</span>
                    <button class="sg-refresh-btn" onclick="fetchSwingGuard()" style="margin-top:4px;">↻ 重试</button>
                </div>`;
                console.error("Swing Guard fetch error (all retries exhausted):", e);
            }
        }
    }
}

function _updateSwingGuardFreshness(result) {
    const header = document.querySelector('.swing-guard-header');
    if (!header) return;
    // 移除旧标签
    const old = header.querySelector('.sg-freshness');
    if (old) old.remove();
    
    const badge = document.createElement('span');
    badge.className = 'sg-freshness';
    
    if (!result.cached) {
        badge.textContent = '🟢 实时';
        badge.style.cssText = 'font-size:0.72rem;color:#6ee7b7;margin-right:8px;font-weight:600;';
    } else if (result.stale) {
        const mins = Math.round((result.age_seconds || 0) / 60);
        badge.textContent = `🟡 ${mins}m前 · 刷新中`;
        badge.style.cssText = 'font-size:0.72rem;color:#fcd34d;margin-right:8px;font-weight:600;';
    } else {
        const mins = Math.round((result.age_seconds || 0) / 60);
        badge.textContent = `⚡ ${mins}m前`;
        badge.style.cssText = 'font-size:0.72rem;color:#94a3b8;margin-right:8px;font-weight:600;';
    }
    
    // 插入到刷新按钮之前
    const btn = header.querySelector('.sg-refresh-btn');
    if (btn) btn.parentNode.insertBefore(badge, btn);
}

function renderSwingGuard(data) {
    const grid = document.getElementById('swing-guard-grid');
    if (!grid) return;
    
    if (!data || Object.keys(data).length === 0) {
        grid.innerHTML = '<div class="loading-spinner">暂无波段监测数据</div>';
        return;
    }
    
    const statusStyles = { 
        "GREEN": { card: "sg-status-green", text: "sg-text-green", bg: "sg-bg-green" }, 
        "YELLOW": { card: "sg-status-yellow", text: "sg-text-yellow", bg: "sg-bg-yellow" }, 
        "RED": { card: "sg-status-red", text: "sg-text-red", bg: "sg-bg-red" }, 
        "UNKNOWN": { card: "", text: "sg-text-neutral", bg: "sg-bg-neutral" }, 
        "ERROR": { card: "sg-status-red", text: "sg-text-red", bg: "sg-bg-red" } 
    };
    const emojis = { "GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "UNKNOWN": "⚪", "ERROR": "❌" };
    
    let html = '';
    
    // Sort logic to put RED on top
    const entries = Object.entries(data).sort((a, b) => {
        const order = {"RED":0, "YELLOW":1, "GREEN":2};
        const stA = a[1].status || "UNKNOWN";
        const stB = b[1].status || "UNKNOWN";
        return (order[stA]??3) - (order[stB]??3);
    });
    
    entries.forEach(([assetId, info]) => {
        const st = info.status || "UNKNOWN";
        const style = statusStyles[st] || statusStyles["UNKNOWN"];
        const emoji = emojis[st] || "⚪";
        
        const action = info.action || '--';
        const rawBuffer = info.buffer_pct !== undefined ? info.buffer_pct : 0;
        const bufferStr = info.buffer_pct !== undefined ? (rawBuffer * 100).toFixed(1) + '%' : '--';
        const reason = info.reason || '';
        const name = info.asset_name || assetId;
        
        // Energy Bar Logic (Max ref is 12%)
        let barWidth = Math.max(0, Math.min(100, (rawBuffer / 0.12) * 100));
        let barColor = st === 'GREEN' ? '#10b981' : (st === 'YELLOW' ? '#f59e0b' : '#ef4444');
        let flashClass = rawBuffer <= 0.005 ? 'flash' : ''; // Flash if buffer is negative or very close to 0
        if (st === 'RED') barWidth = 100; // If red, fill the bar with red flashing
        
        html += `
            <div class="sg-card ${style.card}">
                <div class="sg-header">
                    <div class="sg-title">${emoji} ${name}</div>
                    <div class="sg-badge ${style.bg}">${action}</div>
                </div>
                
                <div class="sg-data-row">
                    <span class="sg-data-label">安全垫缓冲</span>
                    <span class="sg-data-value ${rawBuffer < 0 ? 'sg-text-red' : style.text}">${bufferStr}</span>
                </div>
                
                <div class="sg-buffer-track">
                    <div class="sg-buffer-fill ${flashClass}" style="width: ${barWidth}%; background: ${barColor};"></div>
                </div>
                
                <div class="sg-footer">
                    ${reason}
                </div>
            </div>
        `;
    });
    
    grid.innerHTML = html;
}
