// ══════════════════════════════════════════
// AlphaCore · Data Fetch (O3 模块化拆分)
// API 调用 + 智能轮询
// ══════════════════════════════════════════

async function fetchQuantData() {
    try {
        const response = await fetch(API_URL);
        if (!response.ok) {
            throw new Error(`HTTP 异常: ${response.status}`);
        }
        const result = await response.json();
        
        // V14.0纯缓存读取：支持返回旧数据但带 stale 标记，或返回 warming_up 状态
        if (result.status === 'success' || (result.data && Object.keys(result.data).length > 0)) {
            if (_isWarmingUp && result.status === 'success') {
                showToast('✅ 并发同步完成，实盘数据已加载', 'success');
                _isWarmingUp = false;
            }
            
            if (result.is_stale && result.status === 'warming_up') {
                 showToast('🟡 系统后台维护中，当前展示快照', 'warning');
            } else if (result.is_stale) {
                 showToast('🔶 数据延期警告，展示陈旧缓存', 'error');
            }
            
            updateDashboard(result.data);
            
            // 更新最后拉取时间
            const date = new Date(result.timestamp || Date.now());
            document.getElementById('system-time').innerText = 
                `${date.toLocaleDateString()} ${date.toLocaleTimeString()} · 已连接 AlphaCore API · ${result.is_stale ? '数据延期' : '数据实时同步中'}`;
                
        } else if (result.status === 'warming_up') {
            console.log("后台引擎首次预热中...");
            if (!_isWarmingUp) {
                showToast('🟡 引擎预热中，正在自动智能同步...', 'warning');
                _isWarmingUp = true;
            }
            document.getElementById('system-time').innerText = "🟡 " + result.message + " (自动同步中...)";
            
            // 如果页面是空的，先拿Fallback撑一下门面
            const vixVal = document.getElementById('val-vix');
            if (vixVal && (!vixVal.innerText.trim() || vixVal.innerText.includes('--'))) {
                showFallbackData();
            }
            
            // UI/UX 亮点: Smart Polling 智能轮询
            clearTimeout(_pollingTimer);
            _pollingTimer = setTimeout(fetchQuantData, 2000);
            return;
        } else {
            console.error("后端返回错误:", result.message);
            document.getElementById('system-time').innerText = `API 错误: ${result.message}`;
            showToast(`❌ API 错误: ${result.message}`, 'error');
        }
    } catch (error) {
        console.warn("未能连接到本地 FastAPI 后端，展示模拟本地挂载数据...", error);
        document.getElementById('system-time').innerText = "⚠️ 离线模式 · 请启动 main.py 获取实时数据";
        showToast('⚠️ 离线模式: 无法连接 AlphaCore 后端', 'error');
        showFallbackData();
    }
}

