// 移除过期 Chart.js 实例
// 后端 API 地址
const API_URL = '/api/v1/dashboard-data';

// 全局 DOM 查询工具 (消除各渲染函数重复声明)
const el = (id) => document.getElementById(id);

// 格式化函数
const formatTrend = (change, isInverse = false) => {
    // 对于某些指标（如资金流入），下跌可能判定为 down。对于 VIX，上涨代表恐慌。
    const sign = change > 0 ? '+' : '';
    const arrow = change > 0 ? '▲' : '▼';
    return `${arrow} ${sign}${change}%`;
};

// ====== UI/UX 平滑动画库 ======
function animateValueWithHTML(elementId, targetValueStr, trendHtml, duration = 800) {
    const obj = document.getElementById(elementId);
    if (!obj) return;
    
    const targetNum = parseFloat(targetValueStr);
    if (isNaN(targetNum)) {
        obj.innerHTML = `${targetValueStr} ${trendHtml}`;
        return;
    }
    
    const currentText = obj.childNodes[0] ? obj.childNodes[0].textContent.trim() : "0";
    const startNum = parseFloat(currentText) || 0;
    
    if (startNum === targetNum) {
        obj.innerHTML = `${targetValueStr} ${trendHtml}`;
        return;
    }
    
    let startTimestamp = null;
    const isInt = String(targetValueStr).indexOf('.') === -1;
    const decimals = isInt ? 0 : String(targetValueStr).split('.')[1].length;
    
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 4); // easeOutQuart
        const current = startNum + (targetNum - startNum) * ease;
        
        obj.innerHTML = `${current.toFixed(decimals)} ${trendHtml}`;
        if (progress < 1) {
            window.requestAnimationFrame(step);
        } else {
            obj.innerHTML = `${targetValueStr} ${trendHtml}`;
        }
    };
    window.requestAnimationFrame(step);
}

const updateCardUI = (cardId, valId, trendId, dataItem) => {
    if (!dataItem) return;
    
    const valEl = document.getElementById(valId);
    if (!valEl) {
        console.warn(`[UI] Element not found: ${valId}`);
        return;
    }
    
    const trendHtml = `<span class="trend" id="${trendId}">${dataItem.trend}</span>`;
    animateValueWithHTML(valId, dataItem.value, trendHtml);
    
    // Dynamically set highlight color based on status (up = green, down = red, neutral = gray etc)
    const cardEl = cardId ? document.getElementById(cardId) : null;
    if (dataItem.status === 'up') {
        valEl.classList.remove('highlight-down', 'highlight-neutral');
        valEl.classList.add('stat-value', 'highlight-up');
        if (cardEl) cardEl.classList.add('active-glow');
    } else if (dataItem.status === 'down') {
        valEl.classList.remove('highlight-up', 'highlight-neutral');
        valEl.classList.add('stat-value', 'highlight-down');
        if (cardEl) cardEl.classList.remove('active-glow');
    } else {
        valEl.classList.remove('highlight-up', 'highlight-down');
        valEl.classList.add('stat-value', 'highlight-neutral');
        if (cardEl) cardEl.classList.remove('active-glow');
    }
};

/**
 * V9.0: 五策略信号矩阵渲染器
 * 替代通用 updateCardUI()，为信号卡片提供专用结构化渲染
 */
function renderSignalCard(signalData) {
    if (!signalData) return;

    const cardEl = el('card-signal');
    const consensusCountEl = el('signal-consensus-count');
    const consensusLabelEl = el('signal-consensus-label');
    const matrixEl = el('signal-matrix');
    const descEl = el('desc-signal');

    // V9.0: 新结构化数据 (有 strategies 数组)
    if (signalData.strategies && Array.isArray(signalData.strategies)) {
        // 共振摘要
        if (consensusCountEl) consensusCountEl.textContent = signalData.consensus || '--';
        if (consensusLabelEl) {
            const label = signalData.consensus_label || '同步中';
            consensusLabelEl.textContent = label;
            // 状态色
            const ups = (signalData.consensus || '').match(/(\d+)\/5/);
            const upCount = ups ? parseInt(ups[1], 10) : 0;
            consensusLabelEl.className = 'signal-consensus-label ' +
                (upCount >= 4 ? 'sig-bull' : (upCount >= 3 ? 'sig-mild-bull' : (upCount <= 1 ? 'sig-bear' : 'sig-neutral')));
        }

        // 整体卡片光晕
        if (cardEl) {
            const st = signalData.status;
            if (st === 'up') cardEl.classList.add('active-glow');
            else cardEl.classList.remove('active-glow');
        }

        // 五行策略矩阵
        if (matrixEl) {
            matrixEl.innerHTML = signalData.strategies.map(s => {
                const dirClass = s.direction === 'up' ? 'sig-dir-up' :
                                 s.direction === 'down' ? 'sig-dir-down' :
                                 s.direction === 'mixed' ? 'sig-dir-mixed' : 'sig-dir-neutral';
                return `<div class="signal-row ${dirClass}">
                    <span class="sig-icon">${s.icon}</span>
                    <span class="sig-name">${s.name}</span>
                    <span class="sig-signal">${s.signal}</span>
                    <span class="sig-metric">${s.metric}</span>
                    <span class="sig-dot ${dirClass}"></span>
                </div>`;
            }).join('');
        }

        // 描述行: 共振摘要
        if (descEl) {
            descEl.textContent = `${signalData.consensus} · ${signalData.consensus_label}`;
        }
    } else {
        // 降级: 旧格式 (value/trend/status) 兼容渲染
        if (consensusCountEl) consensusCountEl.textContent = signalData.value || '--';
        if (consensusLabelEl) {
            consensusLabelEl.textContent = '';
            consensusLabelEl.className = 'signal-consensus-label';
        }
        if (matrixEl) matrixEl.innerHTML = '';
        if (descEl) descEl.textContent = signalData.trend || '监控五大策略共振情况';
        if (cardEl) {
            if (signalData.status === 'up') cardEl.classList.add('active-glow');
            else cardEl.classList.remove('active-glow');
        }
    }
}

/**
 * V8.2: ERP 卡片专用渲染器
 * 修正语义: ERP ↑ = 股票便宜 = 利好 (绿色), ERP ↓ = 股票贵 = 利空 (红色)
 * 数据源字段: value, trend, desc, status, erp_pct, signal_label
 */
function renderErpCard(erpData) {
    if (!erpData) return;

    const valEl = el('val-erp');
    const trendEl = el('trend-erp');
    const descEl = el('desc-erp');
    const absLabel = el('erp-abs-label');
    const pctLabel = el('erp-pct-label');
    const pctBar = el('bar-erp-pct');
    const signalPill = el('erp-signal-pill');
    const cardEl = el('card-erp');

    // 1. 主值 + Trend Badge
    if (valEl) {
        valEl.innerHTML = `${erpData.value} <span class="trend" id="trend-erp">${erpData.trend || '--'}</span>`;
        // V3.0: 阈值从后端 erp_thresholds 读取, 消除硬编码漂移
        const erpVal = parseFloat(erpData.value) || 0;
        const thresh = erpData.erp_thresholds || { bullish: 5.0, bearish: 3.5 };
        let colorClass = 'erp-neutral';
        if (erpVal >= thresh.bullish) colorClass = 'erp-bullish';
        else if (erpVal < thresh.bearish) colorClass = 'erp-bearish';
        valEl.className = `stat-value ${colorClass}`;
    }

    // 2. 双维度标签
    if (absLabel && erpData.desc) {
        // desc 格式: "偏低估 · 4Y分位10.8%"
        const parts = (erpData.desc || '').split('·').map(s => s.trim());
        const absText = parts[0] || '--';
        absLabel.textContent = absText;
        // 颜色: 根据绝对值标签判定
        absLabel.className = 'erp-abs-label';
        if (/低估|极度低估/.test(absText)) absLabel.classList.add('erp-val-bull');
        else if (/高估|极度高估/.test(absText)) absLabel.classList.add('erp-val-bear');
    }

    // 3. 分位标签 + 进度条
    const pctVal = erpData.erp_pct != null ? erpData.erp_pct : 50;
    if (pctLabel) {
        pctLabel.textContent = `4Y分位 ${typeof pctVal === 'number' ? pctVal.toFixed(1) : pctVal}%`;
    }
    if (pctBar) {
        pctBar.style.width = `${Math.min(100, Math.max(0, pctVal))}%`;
    }

    // 4. 信号 Pill (标配持有 / 超配 / 减配)
    if (signalPill) {
        const sig = erpData.signal_label || '--';
        signalPill.textContent = sig;
        signalPill.className = 'erp-signal-pill';
        if (/超配|加仓|满配/.test(sig)) signalPill.classList.add('sig-bull');
        else if (/减配|清仓|观望/.test(sig)) signalPill.classList.add('sig-bear');
        else signalPill.classList.add('sig-neutral');
    }

    // 5. 描述行
    if (descEl) {
        descEl.textContent = `股债溢价 ${erpData.value || '--'} · 信号: ${erpData.signal_label || '--'}`;
    }

    // 6. 卡片光晕: ERP >= 5% 且 status='up' 时点亮
    if (cardEl) {
        if (erpData.status === 'up') cardEl.classList.add('active-glow');
        else cardEl.classList.remove('active-glow');
    }
}

/**
 * V10.0: 主力动向 (A+H 跨境监控) 专用渲染器
 * 目标 DOM IDs:
 *   val-capital-a-compact / trend-capital-a-compact  (北向数值+趋势)
 *   val-capital-h-compact / trend-capital-h-compact  (南向数值+趋势)
 *   cap-dir-a / cap-dir-h                            (方向指示灯)
 *   cap-resonance-pill                               (共振标签)
 *   bar-cap-z / cap-z-val                            (Z合力条+数值)
 *   desc-capital                                     (卡片底部描述)
 *   card-capital                                     (卡片光晕)
 *
 * 后端数据结构 (capital_a):
 *   value: "A: 151.4 亿", trend: "北向稳步流入", status: "up",
 *   z_score: 0.85, raw_5d: 151.4,
 *   resonance: "双多共振", resonance_status: "bull", z_composite: 1.65
 */
function renderCapitalCard(capA, capH) {
    // === 北向 ===
    if (capA) {
        const valA = el('val-capital-a-compact');
        const trendA = el('trend-capital-a-compact');
        const dirA = el('cap-dir-a');
        if (valA) valA.textContent = capA.value || '--';
        if (trendA) {
            trendA.textContent = capA.z_score != null ? `Z:${capA.z_score > 0 ? '+' : ''}${capA.z_score}` : (capA.trend || '--');
            trendA.className = 'cap-flow-trend ' +
                (capA.status === 'up' ? 'flow-up' : capA.status === 'down' ? 'flow-down' : 'flow-neutral');
        }
        if (dirA) {
            dirA.className = 'cap-flow-dir ' +
                (capA.status === 'up' ? 'dir-up' : capA.status === 'down' ? 'dir-down' : 'dir-neutral');
        }

        // 共振标签 pill
        const pillEl = el('cap-resonance-pill');
        if (pillEl) {
            const resonance = capA.resonance || '—';
            const rStatus = capA.resonance_status || 'neutral';
            pillEl.textContent = resonance;
            pillEl.className = 'cap-resonance-pill res-' + rStatus;
        }

        // Z 合力条
        const zComposite = capA.z_composite != null ? capA.z_composite : 0;
        const zBarEl = el('bar-cap-z');
        const zValEl = el('cap-z-val');
        if (zBarEl) {
            // 将 Z-score (-3 ~ +3) 映射到 0-100%
            const zPct = Math.min(100, Math.max(0, 50 + zComposite * 15));
            zBarEl.style.width = `${zPct}%`;
            zBarEl.className = 'cap-z-bar ' +
                (zComposite > 0.5 ? 'z-bull' : zComposite < -0.5 ? 'z-bear' : 'z-neutral');
        }
        if (zValEl) {
            zValEl.textContent = `${zComposite > 0 ? '+' : ''}${zComposite.toFixed(2)}`;
            zValEl.style.color = zComposite > 0.5 ? '#10b981' : (zComposite < -0.5 ? '#ef4444' : '#f59e0b');
        }
    }

    // === 南向 ===
    if (capH) {
        const valH = el('val-capital-h-compact');
        const trendH = el('trend-capital-h-compact');
        const dirH = el('cap-dir-h');
        if (valH) valH.textContent = capH.value || '--';
        if (trendH) {
            trendH.textContent = capH.z_score != null ? `Z:${capH.z_score > 0 ? '+' : ''}${capH.z_score}` : (capH.trend || '--');
            trendH.className = 'cap-flow-trend ' +
                (capH.status === 'up' ? 'flow-up' : capH.status === 'down' ? 'flow-down' : 'flow-neutral');
        }
        if (dirH) {
            dirH.className = 'cap-flow-dir ' +
                (capH.status === 'up' ? 'dir-up' : capH.status === 'down' ? 'dir-down' : 'dir-neutral');
        }
    }

    // === 卡片光晕 + 描述 ===
    const cardEl = el('card-capital');
    if (cardEl) {
        const isUp = (capA && capA.status === 'up') || (capH && capH.status === 'up');
        if (isUp) cardEl.classList.add('active-glow');
        else cardEl.classList.remove('active-glow');
    }

    const descEl = el('desc-capital');
    if (descEl && capA && capH) {
        descEl.textContent = `北向: ${capA.trend} · 南向: ${capH.trend}`;
    }
}

let _pollingTimer = null;
let _isWarmingUp = false;

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

/** V14.0 UI/UX: 现代 Toast 通知系统 (替换过时的 _showBanner) */
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = message;
    
    container.appendChild(toast);
    
    // 强制重绘以触发动画
    toast.offsetHeight;
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400); // 等待 CSS 过渡结束
    }, 4000);
}

// 废弃的横幅函数作为空壳保留，防止其他旧代码报错
function _showBanner() {}
function _removeBanner() {}
function _removeOfflineBanner() {}

// 动态将数据注入到图表和 DOM
function updateDashboard(marketData) {
    if (marketData.macro_cards) {
        // 1. 更新顶部卡片数值
        if (marketData.macro_cards.vix) {
            updateCardUI('card-vix', 'val-vix', 'trend-vix', marketData.macro_cards.vix);
            // V4.2 新增: VIX 风格描述与分位条
            const vix = marketData.macro_cards.vix;
            const vixRegimeEl = document.getElementById('val-vix-regime');
            if (vixRegimeEl && vix.regime) {
                vixRegimeEl.innerText = vix.regime;
                vixRegimeEl.className = `vix-regime-box ${vix.class}`;
            }
            if (document.getElementById('desc-vix')) document.getElementById('desc-vix').innerText = vix.desc || "接入实时全球避险情绪水温";
            if (document.getElementById('val-vix-percentile')) document.getElementById('val-vix-percentile').innerText = `Range: ${vix.percentile}%`;
            const vixBar = document.getElementById('bar-vix-range');
            if (vixBar) vixBar.style.width = `${vix.percentile}%`;
        }
        // V8.2: ERP 专用渲染管线 (替代通用 updateCardUI)
        if (marketData.macro_cards.erp) {
            renderErpCard(marketData.macro_cards.erp);
        }
        
        // V10.0: A+H 跨境流量专用渲染管线 (compact card)
        renderCapitalCard(marketData.macro_cards.capital_a, marketData.macro_cards.capital_h);

        // V9.0: 五策略信号矩阵 (专用渲染管线)
        renderSignalCard(marketData.macro_cards.signal);

        // V5.0: 全局 Regime 状态横幅
        if (marketData.macro_cards.regime_banner) {
            const rb = marketData.macro_cards.regime_banner;
            const banner = document.getElementById('regime-banner');
            const dot = document.getElementById('rb-dot');
            const regimeEl = document.getElementById('rb-regime');
            const tempEl = document.getElementById('rb-temp');
            const adviceEl = document.getElementById('rb-advice');
            const vixEl = document.getElementById('rb-vix');
            const capEl = document.getElementById('rb-capital');
            
            if (regimeEl) regimeEl.innerText = rb.regime || '—';
            if (tempEl) tempEl.innerText = `${rb.temp}°`;
            if (adviceEl) adviceEl.innerText = rb.advice || '—';
            if (vixEl) vixEl.innerText = `VIX ${rb.vix} ${rb.vix_label || ''}`;
            if (capEl) capEl.innerText = `资金 Z:${rb.z_capital > 0 ? '+' : ''}${rb.z_capital}`;
            
            // 状态颜色
            if (banner && dot) {
                let colorClass = 'rb-neutral';
                if (rb.temp > 65) colorClass = 'rb-bull';
                else if (rb.temp < 35) colorClass = 'rb-bear';
                banner.className = `regime-banner glass-panel ${colorClass}`;
                dot.className = `rb-dot ${colorClass}`;
            }
            
            // V7.0: AIAE 状态标签
            const aiaeEl = document.getElementById('rb-aiae');
            if (aiaeEl && rb.aiae_regime_cn) {
                aiaeEl.innerText = `🌡️ AIAE ${rb.aiae_regime_cn} Cap${rb.aiae_cap}%`;
                const ar = rb.aiae_regime || 3;
                aiaeEl.style.borderColor = ar <= 2 ? 'rgba(16,185,129,0.5)' : ar >= 4 ? 'rgba(239,68,68,0.5)' : 'rgba(245,158,11,0.5)';
            }
        }
    }
    
    // 3.5 AIAE 温度计渲染
    if (marketData.macro_cards && marketData.macro_cards.aiae_thermometer) {
        renderAIAEThermometer(marketData.macro_cards.aiae_thermometer);
    }

    // 4. V6.0 情绪与持仓枢纽渲染 (Sentiment & Position Hub)
    if (marketData.macro_cards && marketData.macro_cards.market_temp) {
        renderPositionHub(marketData.macro_cards.market_temp);
    }

    // 4.5 V2.0 明日交易计划渲染管线
    if (marketData.macro_cards && marketData.macro_cards.tomorrow_plan) {
        const plan = marketData.macro_cards.tomorrow_plan;

        if (plan.primary_regime) {
            // === V2.0 新版渲染 ===
            const pr = plan.primary_regime;
            const vd = plan.validators || {};
            const rp = plan.risk_panel || {};

            // 1. Header Badge
            const badgeEl = el('tag-current-regime');
            if (badgeEl) {
                badgeEl.innerText = `${pr.emoji} ${pr.cn} Cap${pr.cap}%`;
                badgeEl.style.borderColor = pr.tier <= 2 ? 'rgba(16,185,129,0.4)' : pr.tier >= 4 ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.4)';
                badgeEl.style.color = pr.tier <= 2 ? '#10b981' : pr.tier >= 4 ? '#ef4444' : '#f59e0b';
            }

            // 2. 左侧决策锚面板
            if (el('plan-anchor-tier')) el('plan-anchor-tier').innerText = pr.emoji;
            if (el('plan-anchor-value')) {
                el('plan-anchor-value').innerText = pr.aiae_v1.toFixed(1);
                const colors = {1:'#10b981',2:'#3b82f6',3:'#eab308',4:'#f97316',5:'#ef4444'};
                el('plan-anchor-value').style.color = colors[pr.tier] || '#eab308';
            }
            if (el('plan-anchor-cap-val')) el('plan-anchor-cap-val').innerText = `${pr.cap}%`;
            if (el('plan-anchor-cap-bar')) el('plan-anchor-cap-bar').style.width = `${pr.cap}%`;

            // ERP pill
            const erpPill = el('plan-anchor-erp');
            if (erpPill && vd.erp) {
                erpPill.innerText = `ERP ${vd.erp.value}% ${vd.erp.label}`;
                erpPill.className = 'plan-anchor-erp' + (vd.erp.erp_tier === 'bull' ? ' erp-bull' : vd.erp.erp_tier === 'bear' ? ' erp-bear' : '');
            }

            // Slope
            if (el('plan-anchor-slope') && rp.slope) {
                const sl = rp.slope;
                const arrow = sl.direction === 'rising' ? '↗' : sl.direction === 'falling' ? '↘' : '→';
                el('plan-anchor-slope').innerText = `斜率 ${sl.value >= 0 ? '+' : ''}${sl.value} ${arrow}`;
            }

            // Risk indicators
            const setRisk = (elId, val, threshold, decimals) => {
                const e = el(elId);
                if (e) {
                    e.innerText = typeof val === 'number' ? val.toFixed(decimals || 1) + '%' : '--';
                    e.className = 'plan-risk-val ' + (val > threshold ? 'risk-danger' : val > threshold * 0.7 ? 'risk-warning' : 'risk-safe');
                }
            };
            setRisk('plan-risk-margin', rp.margin_heat?.value, rp.margin_heat?.threshold || 3.5, 1);
            setRisk('plan-risk-slope', Math.abs(rp.slope?.value || 0), rp.slope?.threshold || 1.5, 2);
            setRisk('plan-risk-fund', rp.fund_position?.value, rp.fund_position?.threshold || 90, 0);

            // 3. 五档矩阵
            const matrixEl = el('matrix-content-v2');
            if (matrixEl && plan.regime_matrix) {
                matrixEl.innerHTML = plan.regime_matrix.map(m => {
                    const tierLabel = ['','Ⅰ','Ⅱ','Ⅲ','Ⅳ','Ⅴ'][m.tier] || m.tier;
                    return `<div class="matrix-row-v2 tier-${m.tier} ${m.active ? 'tier-active' : ''}">
                        <div class="col-tier-v2">${m.emoji} ${tierLabel}</div>
                        <div class="col-range-v2">${m.range}</div>
                        <div class="col-action-v2">${m.action}</div>
                        <div class="col-cap-v2">${m.cap_range}</div>
                    </div>`;
                }).join('');
            }

            // 4. 核心指令 (3行)
            const directivesEl = el('plan-directives');
            if (directivesEl && plan.directives) {
                directivesEl.innerHTML = plan.directives.map(d => {
                    let extraClass = `priority-${d.priority}`;
                    if (d.priority === 'risk' && d.color === '#ef4444') extraClass += ' risk-critical';
                    else if (d.priority === 'risk' && d.color === '#f97316') extraClass += ' risk-active';
                    return `<div class="plan-directive ${extraClass}" style="border-left-color:${d.color}">
                        <span class="plan-directive-icon">${d.icon}</span>
                        <span class="plan-directive-text">${d.text}</span>
                    </div>`;
                }).join('');
            }

            // 5. 情景标签
            const scenarioEl = el('plan-scenarios-v2');
            if (scenarioEl && plan.scenarios) {
                const typeIcons = {aiae_upgrade: '📈', vix_alert: '🚨', erp_shift: '📉'};
                scenarioEl.innerHTML = plan.scenarios.map(s =>
                    `<div class="scenario-tag-v2 type-${s.type || ''}">${typeIcons[s.type] || '🔄'} ${s.condition}: ${s.action}</div>`
                ).join('');
            }
        } else {
            // === 旧版降级渲染 ===
            const badgeEl = el('tag-current-regime');
            if (badgeEl && plan.current_tactics) {
                badgeEl.innerText = `实时状态: ${plan.current_tactics.regime}`;
            }
            const matrixEl = el('matrix-content-v2');
            if (matrixEl && plan.regime_matrix) {
                matrixEl.innerHTML = plan.regime_matrix.map(m => `
                    <div class="matrix-row-v2 ${m.active ? 'tier-active tier-3' : ''}">
                        <div class="col-tier-v2">${m.regime || ''}</div>
                        <div class="col-range-v2">${m.vix_range || ''}</div>
                        <div class="col-action-v2">${m.tactics || ''}</div>
                        <div class="col-cap-v2">${m.pos || ''}</div>
                    </div>
                `).join('');
            }
            const directivesEl = el('plan-directives');
            if (directivesEl && plan.framework) {
                directivesEl.innerHTML = plan.framework.map(f => {
                    const isPrimary = f.includes('优先') || f.includes('核心');
                    return `<div class="plan-directive ${isPrimary ? 'priority-primary' : ''}">
                        <span class="plan-directive-text">${f}</span>
                    </div>`;
                }).join('');
            }
            const scenarioEl = el('plan-scenarios-v2');
            if (scenarioEl && plan.scenarios) {
                scenarioEl.innerHTML = plan.scenarios.map(s =>
                    `<div class="scenario-tag-v2">${s.case}: ${s.action}</div>`
                ).join('');
            }
        }
    }


    // 5. 更新行业热力图 (Sector Heatmap)
    if (marketData.sector_heatmap) {
        renderHeatmap('heatmap-grid', marketData.sector_heatmap);
    }
    
    // 6. 更新个股列表
    if (marketData.execution_lists) {
        renderExecutionLists(document.getElementById('list-buy-zone'), marketData.execution_lists.buy_zone);
        renderExecutionLists(document.getElementById('list-danger-zone'), marketData.execution_lists.danger_zone);
    }
    
    // 2. 更新策略监控卡片 (5策略)
    if (marketData.strategy_status) {
        updateStrategyCard('mr', marketData.strategy_status.mr);
        updateStrategyCard('mom', marketData.strategy_status.mom);
        updateStrategyCard('div', marketData.strategy_status.div);
        updateStrategyCard('erp', marketData.strategy_status.erp);
        updateStrategyCard('aiae', marketData.strategy_status.aiae);
    }
}

function renderExecutionLists(listContainer, listData) {
    if (!listContainer || !listData) return;
    
    listContainer.innerHTML = ''; // Clear processing text
    
    if (listData.length === 0) {
        listContainer.innerHTML = `<li><div style="color: #64748b; padding: 10px;">当前无符合条件标的</div></li>`;
        return;
    }
    
    listData.forEach(item => {
        const li = document.createElement('li');
        // 根据评分和买卖逻辑确定分数颜色
        let scoreClass = '';
        if (item.badgeClass === 'buy') {
            if (item.score >= 75) scoreClass = 'score-high';
            else if (item.score >= 60) scoreClass = 'score-mid';
            else scoreClass = 'score-low';
        } else { // danger_zone or sell
            if (item.score <= 30) scoreClass = 'score-danger';
            else scoreClass = 'score-low';
        }
            
        li.innerHTML = `
            <div class="stock-info">
                <span class="stock-name">${item.name}</span>
                <span class="stock-code">${item.code}</span>
            </div>
            <div class="stock-metrics">
                <div class="score-pill ${scoreClass}">评分: ${item.score || '--'}</div>
                <div class="metric-row">
                    <span class="metric">${item.metric || 'PE: ' + item.pe + 'x'}</span>
                    <span class="badge ${item.badgeClass}">${item.badge}</span>
                </div>
            </div>
        `;
        listContainer.appendChild(li);
    });
}

/**
 * V6.0 情绪与持仓枢纽渲染引擎
 */
function renderPositionHub(temp) {
    const vixMult = temp.market_vix_multiplier || 1.0;
    const hubEl = document.getElementById('card-sentiment-hub');
    
    // === 左栏: 心态指引 ===
    if (el('val-mindset')) el('val-mindset').innerText = temp.mindset || "侦测中...";
    
    // 温度颜色区域 (CSS data attribute 切换)
    if (hubEl) {
        let zone = 'warm';
        if (temp.value < 35) zone = 'cold';
        else if (temp.value > 65) zone = 'hot';
        hubEl.setAttribute('data-temp-zone', zone);
    }
    
    // 宏观微标签: 资金Z + ERP
    if (el('val-capital-z') && temp.z_capital !== undefined) {
        const zVal = temp.z_capital;
        el('val-capital-z').innerText = `${zVal > 0 ? '+' : ''}${zVal.toFixed(2)}`;
        el('val-capital-z').style.color = zVal > 0.5 ? '#10b981' : (zVal < -0.5 ? '#ef4444' : '#f59e0b');
    }
    if (el('val-erp-tag') && temp.hub_factors && temp.hub_factors.erp_value) {
        el('val-erp-tag').innerText = temp.hub_factors.erp_value.label;
        const erpScore = temp.hub_factors.erp_value.score;
        el('val-erp-tag').style.color = erpScore >= 70 ? '#10b981' : (erpScore >= 40 ? '#f59e0b' : '#ef4444');
    }
    
    // === 中栏: 仓位决策面板 ===
    if (el('val-pos-advice')) el('val-pos-advice').innerText = temp.advice;
    
    // 仓位进度条 (优先从 strategy_positions.total 数值字段读取, 正则降级)
    let posPercent = 30;
    if (temp.strategy_positions && temp.strategy_positions.total != null) {
        posPercent = temp.strategy_positions.total;
    } else {
        const posMatch = (temp.advice || '').match(/(\d+)%/);
        if (posMatch) posPercent = parseInt(posMatch[1], 10);
    }
    if (el('bar-pos-advice')) {
        el('bar-pos-advice').style.width = `${posPercent}%`;
        // V11.0: 用后端 advice_tier (1-5) 驱动颜色, 消除 emoji 匹配脆弱性
        const tier = temp.advice_tier || 3;
        const tierColors = {1: '#10b981', 2: '#3b82f6', 3: '#eab308', 4: '#f97316', 5: '#ef4444'};
        el('bar-pos-advice').style.background = tierColors[tier] || '#eab308';
    }
    
    // 置信度
    if (temp.hub_confidence !== undefined) {
        const conf = temp.hub_confidence;
        if (el('val-confidence')) el('val-confidence').innerText = conf;
        if (el('conf-fill')) el('conf-fill').style.width = `${conf}%`;
    }
    
    // 五因子条形图
    if (temp.hub_factors) {
        const factorMap = {
            'vix':     { barId: 'fbar-vix',     scoreId: 'fscore-vix',     data: temp.hub_factors.vix_fear },
            'capital': { barId: 'fbar-capital',  scoreId: 'fscore-capital', data: temp.hub_factors.capital_flow },
            'temp':    { barId: 'fbar-temp',     scoreId: 'fscore-temp',    data: temp.hub_factors.macro_temp },
            'erp':     { barId: 'fbar-erp',      scoreId: 'fscore-erp',     data: temp.hub_factors.erp_value },
            'signal':  { barId: 'fbar-signal',   scoreId: 'fscore-signal',  data: temp.hub_factors.aiae_regime },
            'aiae':    { barId: 'fbar-aiae',     scoreId: 'fscore-aiae',    data: temp.hub_factors.aiae_temp }
        };
        
        for (const [key, cfg] of Object.entries(factorMap)) {
            if (!cfg.data) continue;
            const barEl = el(cfg.barId);
            const scoreEl = el(cfg.scoreId);
            
            if (barEl) {
                barEl.style.width = `${cfg.data.score}%`;
                // 颜色分级
                barEl.className = 'factor-bar';
                if (cfg.data.score >= 65) barEl.classList.add('score-high');
                else if (cfg.data.score >= 35) barEl.classList.add('score-mid');
                else barEl.classList.add('score-low');
            }
            if (scoreEl) {
                scoreEl.innerText = Math.round(cfg.data.score);
                // [P3] 因子分数颜色联动
                scoreEl.className = 'factor-score';
                if (cfg.data.score >= 65) scoreEl.classList.add('score-color-high');
                else if (cfg.data.score >= 35) scoreEl.classList.add('score-color-mid');
                else scoreEl.classList.add('score-color-low');
            }
        }
    }
    
    // === 右栏: 策略配仓 (合并自原配仓总览) ===
    // 策略权重条
    if (temp.regime_weights) {
        const rw = temp.regime_weights;
        // 策略卡片权重 pill 更新 (5策略)
        if (el('weight-mr'))  el('weight-mr').innerText  = `${(rw.mr * 100).toFixed(0)}%权重`;
        if (el('weight-mom')) el('weight-mom').innerText = `${(rw.mom * 100).toFixed(0)}%权重`;
        if (el('weight-div')) el('weight-div').innerText = `${(rw.div * 100).toFixed(0)}%权重`;
        if (el('weight-erp')) el('weight-erp').innerText = `${((rw.erp || 0) * 100).toFixed(0)}%权重`;
        if (el('weight-aiae')) el('weight-aiae').innerText = `${((rw.aiae_etf || 0) * 100).toFixed(0)}%权重`;
        
        // 堆叠条 (5策略)
        const updateBar = (id, key, label) => {
            const b = el(id);
            if (b) {
                b.style.width = `${((rw[key] || 0) * 100).toFixed(0)}%`;
                const span = b.querySelector('span');
                if (span) span.innerText = `${label} ${((rw[key] || 0) * 100).toFixed(0)}%`;
            }
        };
        updateBar('bar-div', 'div', '红利');
        updateBar('bar-mr',  'mr',  '均值');
        updateBar('bar-mom', 'mom', '动量');
        updateBar('bar-erp', 'erp', 'ERP');
        updateBar('bar-aiae', 'aiae_etf', 'AIAE');
    }
    
    // 各策略名义仓位
    if (temp.strategy_positions) {
        const sp = temp.strategy_positions;
        if (el('val-alloc-total')) el('val-alloc-total').innerText = `总仓位: ${sp.total}%`;
        const setPos = (id, val) => { const e = el(id); if (e) e.innerText = `${val}%`; };
        setPos('val-pos-div', sp.div_pos);
        setPos('val-pos-mr',  sp.mr_pos);
        setPos('val-pos-mom', sp.mom_pos);
        setPos('val-pos-erp', sp.erp_pos || 0);
        setPos('val-pos-aiae', sp.aiae_pos || 0);
    }
    
    // 策略过滤器状态
    if (temp.strategy_filters) {
        const sf = temp.strategy_filters;
        const setFilter = (id, val) => { const e = el(id); if (e) e.innerText = val === '正常' ? '' : val; };
        setFilter('filter-div', sf.div);
        setFilter('filter-mr',  sf.mr);
        setFilter('filter-mom', sf.mom);
    }
    
    // N5: 持仓周期标签联动后端 holding_cycle_a
    if (temp.holding_cycle_a && el('val-cycle-a')) {
        el('val-cycle-a').innerText = temp.holding_cycle_a;
    }
}

function updateStrategyCard(prefix, data) {
    if (!data) return;
    
    // V5.0: 状态行（状态指示灯 + 状态文本）
    const statusRow = document.getElementById(`strat-status-row-${prefix}`);
    const statusText = document.getElementById(`strat-status-${prefix}`);
    if (statusText) statusText.innerText = data.status_text;
    if (statusRow) {
        const dotEl = statusRow.querySelector('.strat-dot');
        if (dotEl) dotEl.className = `strat-dot ${data.status_class}`;
        statusRow.className = `strat-status-row ${data.status_class}`;
    }
    
    const metric1El = document.getElementById(`strat-metric1-${prefix}`);
    if (metric1El) metric1El.innerText = data.metric1;
    
    const metric2El = document.getElementById(`strat-metric2-${prefix}`);
    if (metric2El) metric2El.innerText = data.metric2;
}

function showFallbackData() {
    const fallbackData = {
        macro_cards: {
            vix: { 
                value: 20.15, trend: "+5.2%", status: "up", 
                regime: "🟡 正常震荡", class: "vix-status-norm",
                desc: "市场常态，结构性调仓", percentile: 15.2
            },
            tomorrow_plan: {
                primary_regime: {
                    tier: 3, emoji: "🟡", cn: "中性均衡",
                    aiae_v1: 22.3, cap: 65, cap_range: "50-65%",
                    action: "均衡持有", action_detail: "有纪律地持有，到了就卖",
                },
                validators: {
                    erp: { value: 5.22, label: "偏低估", erp_tier: "bull", confirms: true },
                    vix: { value: 20.15, label: "🟡 正常震荡", risk_override: false, multiplier: 1.0 },
                },
                regime_matrix: [
                    { tier: 1, emoji: "🟢", cn: "极度恐慌", range: "<12%", cap_range: "90-95%", action: "满配进攻 · 越跌越买", vix_cross: "VIX>30时分批介入", active: false },
                    { tier: 2, emoji: "🔵", cn: "低配置区", range: "12-16%", cap_range: "70-85%", action: "标准建仓 · 不因波动减仓", vix_cross: "VIX<20加速建仓", active: false },
                    { tier: 3, emoji: "🟡", cn: "中性均衡", range: "16-24%", cap_range: "50-65%", action: "均衡持有 · 到了就卖", vix_cross: "VIX>30启动减仓", active: true },
                    { tier: 4, emoji: "🟠", cn: "偏热区域", range: "24-32%", cap_range: "25-40%", action: "系统减仓 · 每周减5%", vix_cross: "VIX<15警惕拥挤", active: false },
                    { tier: 5, emoji: "🔴", cn: "极度过热", range: ">32%", cap_range: "0-15%", action: "清仓防守 · 3天内完成", vix_cross: "任何VIX都清仓", active: false },
                ],
                directives: [
                    { priority: "primary", icon: "🎯", text: "AIAE 🟡 中性均衡 Cap65% → 均衡持有", color: "#eab308" },
                    { priority: "confirm", icon: "✅", text: "ERP 5.22% 偏低估 → 验证主轴方向", color: "#10b981" },
                    { priority: "risk", icon: "🛡️", text: "VIX 20.15 正常 → 风控不触发", color: "#94a3b8" },
                ],
                scenarios: [
                    { condition: "AIAE上行至Ⅳ级", action: "启动系统减仓至40%以下", type: "aiae_upgrade" },
                    { condition: "VIX突破30+", action: "风控降级Cap×0.75 + 增配红利", type: "vix_alert" },
                    { condition: "ERP跌破3%", action: "估值吸引力下降·降低进攻权重", type: "erp_shift" },
                ],
                risk_panel: {
                    margin_heat: { value: 2.1, threshold: 3.5, status: "safe" },
                    slope: { value: 0.3, threshold: 1.5, status: "safe", direction: "rising" },
                    fund_position: { value: 82.0, threshold: 90, status: "safe" },
                    overall_risk: "low",
                },
                framework: ["🎯 AIAE 🟡 中性均衡 Cap65% → 均衡持有", "✅ ERP 5.22% 偏低估 → 验证主轴方向", "🛡️ VIX 20.15 正常 → 风控不触发"],
                current_tactics: { regime: "🟡 Ⅲ级 中性均衡" },
            },
            capital_a: { value: "A: 151.4 亿", trend: "外资稳步买入", status: "up", z_score: 0.85, raw_5d: 151.4, resonance: "双多共振", resonance_status: "bull", z_composite: 1.65 },
            capital_h: { value: "H: 20.5 亿", trend: "南向博弈均衡", status: "neutral", z_score: 0.32, raw_5d: 20.5 },
            signal: {
                strategies: [
                    { key: "mr",   icon: "📐", name: "均值回归", signal: "2买/3卖",  metric: "偏离8只",   direction: "mixed" },
                    { key: "mom",  icon: "🚀", name: "动量轮动", signal: "AI领涨",   metric: "动量5.2%",  direction: "up" },
                    { key: "div",  icon: "🛡️", name: "红利防线", signal: "5/8趋势",  metric: "买入2只",   direction: "up" },
                    { key: "erp",  icon: "🌐", name: "ERP择时",  signal: "极度低估",  metric: "3.50%",    direction: "up" },
                    { key: "aiae", icon: "🌡️", name: "AIAE管控", signal: "中性均衡",  metric: "Cap65%",   direction: "neutral" },
                ],
                consensus: "3/5 看多",
                consensus_label: "偏多共振",
                status: "up",
                value: "MR 2买/3卖 · ERP 极度低估",
                trend: "DT 5/8趋 · AIAE 中性均衡 · MOM AI领涨"
            },
            erp: { value: "5.2%", trend: "估值中性", status: "neutral", desc: "偏低估 · 4Y分位10.8%", erp_pct: 10.8, signal_label: "标配持有" },
            regime_banner: { regime: "🟠 震荡偏多", temp: 52.3, advice: "🟡 中性均衡 (Cap 65%)", vix: 20.15, vix_label: "🟡 正常震荡", z_capital: 0.8, aiae_regime: 3, aiae_regime_cn: "中性均衡", aiae_cap: 65, aiae_v1: 22.3 },
            aiae_thermometer: { aiae_v1: 22.3, regime: 3, regime_cn: "中性均衡", regime_emoji: "🟡", regime_color: "#eab308", regime_name: "Regime III", cap: 65, slope: 0.3, slope_direction: "rising", margin_heat: 2.1, fund_position: 82.5, aiae_simple: 19.8, erp_value: 3.5, status: "fallback" },
            market_temp: {
                value: 52.3, label: "温暖 | 极度低估", advice: "🟡 中性均衡 (Cap 65%)",
                regime_name: "平衡模式", mindset: "⚖️ 仓位中型，等待分歧",
                market_vix_multiplier: 1.0, erp_z: 1.8, z_capital: 0.8,
                hub_confidence: 72,
                hub_composite: 62.5,
                hub_factors: {
                    aiae_regime:  { score: 55, weight: 0.40, label: "中性均衡" },
                    erp_value:    { score: 85, weight: 0.25, label: "极度低估" },
                    vix_fear:     { score: 78, weight: 0.15, label: "恐慌低位" },
                    capital_flow: { score: 63, weight: 0.10, label: "资金中性" },
                    macro_temp:   { score: 48, weight: 0.10, label: "宏观中性" },
                    aiae_temp:    { score: 55, weight: 0.15, label: "中性均衡" }
                },
                regime_weights: { div: 0.30, mr: 0.24, mom: 0.18, erp: 0.11, aiae_etf: 0.18 },
                strategy_positions: { div_pos: 18.5, mr_pos: 14.5, mom_pos: 11.0, erp_pos: 6.6, aiae_pos: 11.0, total: 61.6 },
                strategy_filters: { div: "正常", mr: "正常", mom: "正常" }
            }
        },
        sector_heatmap: [
            { name: "医药生物", change:  1.60, trend_5d:  0.8, rps: 91 },
            { name: "银行/金融", change: -0.99, trend_5d:  0.3, rps: 100 },
            { name: "酒/自选消费", change: -1.00, trend_5d:  0.2, rps: 75 },
            { name: "上证180/主板", change: -0.87, trend_5d: -0.6, rps: 58 },
            { name: "有色金属", change: -1.00, trend_5d: -1.8, rps: 25 },
            { name: "证券/非银", change: -0.88, trend_5d: -2.0, rps: 41 },
            { name: "计算机/AI", change: -0.44, trend_5d: -2.3, rps: 33 },
            { name: "中证传媒", change: -1.15, trend_5d: -2.9, rps: 50 },
            { name: "军工龙头", change: -1.17, trend_5d: -3.0, rps: 16 },
            { name: "半导体/芯片", change: -0.26, trend_5d: -3.6, rps: 8 },
            { name: "创业板/成长", change: -0.73, trend_5d: -3.8, rps: 83 },
            { name: "新能源车", change: -2.07, trend_5d: -5.7, rps: 66 }
        ],
        execution_lists: {
            buy_zone: [
                { name: "某AI行业龙头", code: "60XXXX.SH", pe: 15.2, score: 82.5, badge: "核心资产", badgeClass: "buy" },
                { name: "车规半导体标的", code: "00XXXX.SZ", pe: 22.1, score: 71.4, badge: "性价比较高", badgeClass: "buy" }
            ],
            danger_zone: [
                { name: "业绩衰退标的", code: "30XXXX.SZ", pe: 120.5, score: 18.2, badge: "严重泡沫", badgeClass: "sell" },
                { name: "高杠杆爆雷风险", code: "60XXXX.SH", metric: "彻底破位", score: 12.5, badge: "财务预警", badgeClass: "sell" }
            ]
        },
        strategy_status: {
            mr: { status_text: "发现极值猎物", status_class: "active", metric1: "54只", metric2: "全仓 80%" },
            mom: { status_text: "动能衰竭", status_class: "warning", metric1: "红利低波", metric2: "拥挤度 92%" },
            div: { status_text: "稳定防御", status_class: "dormant", metric1: "4.82%", metric2: "62%" },
            erp: { status_text: "ERP 极度低估", status_class: "active", metric1: "ERP 3.5%", metric2: "Z: +1.8" },
            aiae: { status_text: "🟡 中性均衡", status_class: "dormant", metric1: "AIAE 22.3%", metric2: "Cap 65%" }
        }
    };
    updateDashboard(fallbackData);
}

/**
 * 渲染行业热力图
 */
function renderHeatmap(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    // N3: 空状态兜底
    if (!data || data.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:40px 20px;color:#64748b;font-size:0.85rem;">📡 暂无行业轮动数据 · 请等待后端数据刷新</div>';
        return;
    }
    
    container.innerHTML = data.map(sector => {
        let intensityClass = '';
        const chg = sector.change;
        const trend5d = sector.trend_5d || 0;
        const rps = sector.rps || 0;
        
        if (chg >= 1.5) intensityClass = 'up-high';
        else if (chg >= 0.5) intensityClass = 'up-mid';
        else if (chg > 0) intensityClass = 'up-low';
        else if (chg <= -1.5) intensityClass = 'down-high';
        else if (chg <= -0.5) intensityClass = 'down-mid';
        else if (chg < 0) intensityClass = 'down-low';
        
        const sign = chg > 0 ? '+' : '';
        const trendSign = trend5d > 0 ? '+' : '';
        
        // 提示信息
        const tooltip = `5日累计: ${trendSign}${trend5d}% | RPS: ${rps} | MR: ${sector.mr_signal || '-'} | MOM: ${sector.mom_signal || '-'}`;
        
        // V5.0 信号角标
        let badges = '';
        if (sector.mr_signal === 'BUY' || sector.mr_signal === '买入') badges += '<span class="hm-badge hm-buy">📐</span>';
        else if (sector.mr_signal === 'SELL' || sector.mr_signal === '卖出') badges += '<span class="hm-badge hm-sell">📐</span>';
        if (sector.mom_signal === 'BUY' || sector.mom_signal === '买入') badges += '<span class="hm-badge hm-buy">🚀</span>';
        
        return `
            <div class="heatmap-cell ${intensityClass}" title="${tooltip}">
                ${badges ? `<div class="hm-badges">${badges}</div>` : ''}
                <span class="sector-name">${sector.name}</span>
                <span class="sector-change">${sign}${chg.toFixed(2)}%</span>
                <span class="sector-rps">5D:${trendSign}${trend5d.toFixed(1)}% · R:${rps}</span>
            </div>
        `;
    }).join('');
}

// Init when DOM loaded
document.addEventListener('DOMContentLoaded', () => {
    
    // 发起网络数据请求
    fetchQuantData();
    
    // UI/UX 亮点: 全局自动定时同步 (3分钟)
    setInterval(() => {
        if (!_isWarmingUp) {
            console.log("⌚ 全局定时同步触发...");
            fetchQuantData();
        }
    }, 180000);

    // 绑定刷新按钮事件 (V11.0: 防抖 + disable 防止并发)
    const refreshBtn = document.getElementById('refresh-btn');
    if(refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            if (refreshBtn.disabled) return;
            refreshBtn.disabled = true;
            const originalText = refreshBtn.innerText;
            refreshBtn.innerText = '拉取中...';
            refreshBtn.style.opacity = '0.6';
            
            // 如果处于预热状态，强制清掉 timer，走手动请求
            clearTimeout(_pollingTimer);
            
            fetchQuantData().finally(() => {
                setTimeout(() => {
                    refreshBtn.innerText = originalText;
                    refreshBtn.disabled = false;
                    refreshBtn.style.opacity = '1';
                }, 500);
            });
        });
    }

    // 导航交互动效
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const href = item.getAttribute('href');
            if (!href || href === '#') {
                e.preventDefault();
            }
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });

    // ERP 历史走势图异步加载
    fetchAndRenderERPChart();
});

// ====== ERP 历史走势 V3.0 · 四档区间可视化 (近11.3年) ======

let _erpDashboardChart = null;

/**
 * 从后端拉取 ERP 择时引擎数据并渲染图表
 * 降级策略: 后端未启动时显示友好提示
 */
async function fetchAndRenderERPChart() {
    const loadingEl = document.getElementById('erp-chart-loading');
    const chartEl = document.getElementById('erp-history-chart');
    
    if (!chartEl) return;
    
    // ECharts 库检测
    if (typeof echarts === 'undefined') {
        if (loadingEl) loadingEl.innerHTML = '⚠️ ECharts 可视化库未加载，图表不可用';
        return;
    }
    
    try {
        const resp = await fetch('/api/v1/strategy/erp-timing');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        
        if (json.status === 'success' && json.data && json.data.chart && json.data.chart.status === 'success') {
            // 隐藏 loading，显示图表
            if (loadingEl) loadingEl.style.display = 'none';
            chartEl.style.display = 'block';
            renderERPDashboardChart(json.data.chart, json.data);
        } else {
            if (loadingEl) loadingEl.innerHTML = '⚠️ ERP 数据暂不可用 (' + (json.message || '格式异常') + ')';
        }
    } catch (err) {
        console.warn('[ERP Chart] 拉取失败，降级处理:', err);
        if (loadingEl) {
            loadingEl.innerHTML = '📡 请启动 <code style="background:rgba(96,165,250,0.15);padding:2px 6px;border-radius:4px;color:#60a5fa;">python main.py</code> 以获取 ERP 历史数据';
        }
    }
}

/**
 * 渲染 ERP 历史走势 V3.0 · 四档区间可视化 (移植自 strategy.js)
 * 特性: markArea色带 + dataZoom缩放 + 极值标注 + M1叠加 + KPI卡片
 */
function renderERPDashboardChart(chart, signalData) {
    const dom = document.getElementById('erp-history-chart');
    if (!dom || typeof echarts === 'undefined') return;
    
    if (_erpDashboardChart) _erpDashboardChart = AC.disposeChart(_erpDashboardChart);
    _erpDashboardChart = AC.registerChart(echarts.init(dom));
    
    const stats = chart.stats || {};
    const hasM1 = chart.m1_yoy && chart.m1_yoy.some(v => v != null);

    // V3.0: 动态标题
    const titleEl = document.getElementById('erp-chart-title');
    if (titleEl) {
        const yrs = stats.date_range_years || '?';
        titleEl.textContent = '\u{1F4C8} ERP 历史走势 (近' + yrs + '年) · 四档区间可视化';
    }

    // V3.0: KPI 卡片
    renderERPDashboardKPIs(stats, signalData);

    // V3.0: markArea 四档色带
    const markAreaData = [
        [{ yAxis: stats.strong_buy_line, itemStyle: { color: 'rgba(16,185,129,0.08)' } }, { yAxis: (stats.max || 8) + 0.5 }],
        [{ yAxis: stats.overweight_line, itemStyle: { color: 'rgba(16,185,129,0.03)' } }, { yAxis: stats.strong_buy_line }],
        [{ yAxis: stats.underweight_line, itemStyle: { color: 'transparent' } }, { yAxis: stats.overweight_line }],
        [{ yAxis: stats.danger_line, itemStyle: { color: 'rgba(239,68,68,0.04)' } }, { yAxis: stats.underweight_line }],
        [{ yAxis: (stats.min || 2) - 0.5, itemStyle: { color: 'rgba(239,68,68,0.08)' } }, { yAxis: stats.danger_line }],
    ];

    // V3.0: markPoint — 当前值 + 历史极值
    const markPointData = [];
    const lastDate = chart.dates[chart.dates.length - 1];
    if (stats.current != null) {
        markPointData.push({
            coord: [lastDate, stats.current],
            name: '当前', symbol: 'pin', symbolSize: 44,
            itemStyle: { color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
            label: { formatter: '{@[1]}%', color: '#fff', fontSize: 10, fontWeight: 700 }
        });
    }
    const extremes = stats.extremes || [];
    extremes.forEach(e => {
        markPointData.push({
            coord: [e.date, e.value],
            name: e.type === 'max' ? '历史最高' : '历史最低',
            symbol: e.type === 'max' ? 'triangle' : 'arrow',
            symbolSize: 12, symbolRotate: e.type === 'min' ? 180 : 0,
            itemStyle: { color: e.type === 'max' ? '#10b981' : '#ef4444' },
            label: { show: true, formatter: e.value + '%', fontSize: 9, color: e.type === 'max' ? '#10b981' : '#ef4444', position: e.type === 'max' ? 'top' : 'bottom' }
        });
    });

    // 区间判定函数
    function getZoneLabel(v) {
        if (v >= (stats.strong_buy_line || 99)) return '\uD83D\uDFE2 强买区';
        if (v >= (stats.overweight_line || 99)) return '\uD83D\uDD35 超配区';
        if (v >= (stats.underweight_line || -99)) return '\u26AA 中性区';
        if (v >= (stats.danger_line || -99)) return '\uD83D\uDFE0 低配区';
        return '\uD83D\uDD34 危险区';
    }

    const legendData = ['ERP', 'PE-TTM', '10Y国债'];
    if (hasM1) legendData.push('M1同比');
    
    _erpDashboardChart.setOption({
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: '#334155',
            textStyle: { fontSize: 11, color: '#e2e8f0' },
            formatter: function(params) {
                let r = '<div style="font-size:0.7rem;color:#64748b;margin-bottom:4px;">' + params[0].axisValue + '</div>';
                params.forEach(p => {
                    if (p.value != null) {
                        const unit = p.seriesName === 'PE-TTM' ? 'x' : '%';
                        r += '<div>' + p.marker + ' ' + p.seriesName + ': <b>' + p.value + unit + '</b></div>';
                    }
                });
                // 找到 ERP 值并标注区间
                const erpParam = params.find(p => p.seriesName === 'ERP');
                if (erpParam && erpParam.value != null) {
                    r += '<div style="margin-top:3px;padding-top:3px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;">' + getZoneLabel(erpParam.value) + '</div>';
                }
                return r;
            }
        },
        legend: {
            data: legendData, top: 0,
            textStyle: { color: '#94a3b8', fontSize: 10 },
            selected: { '10Y国债': false }
        },
        toolbox: {
            right: 20, top: 0,
            feature: {
                saveAsImage: { title: '保存', pixelRatio: 2, backgroundColor: '#0f172a' },
                restore: { title: '重置' }
            },
            iconStyle: { borderColor: '#64748b' }
        },
        grid: { top: 40, bottom: 55, left: 50, right: hasM1 ? 90 : 50 },
        dataZoom: [
            { type: 'inside', start: 65, end: 100 },
            { type: 'slider', height: 16, bottom: 4, borderColor: 'rgba(255,255,255,0.06)',
              fillerColor: 'rgba(245,158,11,0.12)', handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
              textStyle: { color: '#64748b', fontSize: 9 },
              dataBackground: { lineStyle: { color: '#334155' }, areaStyle: { color: 'rgba(245,158,11,0.05)' } }
            }
        ],
        xAxis: {
            type: 'category', data: chart.dates, boundaryGap: false,
            axisLabel: { color: '#64748b', fontSize: 10, formatter: function(v) { return v.substring(0, 7); } },
            axisLine: { lineStyle: { color: '#334155' } }
        },
        yAxis: [
            { type: 'value', name: 'ERP %', nameTextStyle: { color: '#64748b', fontSize: 10 },
              axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
              splitLine: { lineStyle: { color: 'rgba(100,116,139,0.08)' } }
            },
            { type: 'value', name: 'PE-TTM', position: 'right',
              nameTextStyle: { color: '#3b82f6', fontSize: 10 },
              axisLabel: { color: '#3b82f680', fontSize: 9 },
              splitLine: { show: false }
            },
            hasM1 ? {
                type: 'value', name: 'M1%', nameTextStyle: { color: '#a78bfa', fontSize: 10 },
                position: 'right', offset: 40,
                axisLabel: { color: '#a78bfa', fontSize: 9, formatter: '{value}%' },
                splitLine: { show: false }
            } : null
        ].filter(Boolean),
        series: [
            {
                name: 'ERP', type: 'line', data: chart.erp, yAxisIndex: 0,
                lineStyle: { color: '#f59e0b', width: 2.5, shadowColor: 'rgba(245,158,11,0.2)', shadowBlur: 4 },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none', z: 10,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            { offset: 0, color: 'rgba(245,158,11,0.12)' },
                            { offset: 1, color: 'rgba(245,158,11,0)' }
                        ]
                    }
                },
                markLine: {
                    silent: true, symbol: 'none', lineStyle: { type: 'dashed', width: 1 },
                    data: [
                        { yAxis: stats.mean, label: { formatter: '均值 ' + stats.mean + '%', color: '#94a3b8', fontSize: 9 }, lineStyle: { color: '#64748b' } },
                        { yAxis: stats.overweight_line, label: { formatter: '超配 ' + stats.overweight_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98166' } },
                        { yAxis: stats.underweight_line, label: { formatter: '低配 ' + stats.underweight_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444466' } },
                        { yAxis: stats.strong_buy_line, label: { formatter: '强买 ' + stats.strong_buy_line + '%', color: '#10b981', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#10b98140', type: 'dotted' } },
                        { yAxis: stats.danger_line, label: { formatter: '危险 ' + stats.danger_line + '%', color: '#ef4444', fontSize: 9, position: 'insideEndTop' }, lineStyle: { color: '#ef444440', type: 'dotted' } }
                    ]
                },
                markArea: { silent: true, data: markAreaData },
                markPoint: {
                    data: markPointData,
                    animation: true, animationDuration: 600
                }
            },
            {
                name: 'PE-TTM', type: 'line', data: chart.pe_ttm, yAxisIndex: 1,
                lineStyle: { color: '#3b82f6', width: 1.5, type: 'dashed' },
                itemStyle: { color: '#3b82f6' }, symbol: 'none'
            },
            {
                name: '10Y国债', type: 'line', data: chart.yield_10y, yAxisIndex: 0,
                lineStyle: { color: '#ef4444', width: 1, type: 'dotted' },
                itemStyle: { color: '#ef4444' }, symbol: 'none'
            },
            hasM1 ? {
                name: 'M1同比', type: 'line', data: chart.m1_yoy, yAxisIndex: 2,
                lineStyle: { color: '#a78bfa', width: 2, type: 'solid' },
                itemStyle: { color: '#a78bfa' },
                symbol: 'none', smooth: true,
                areaStyle: {
                    color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [{offset:0,color:'rgba(167,139,250,0.10)'},{offset:1,color:'rgba(167,139,250,0)'}]
                    }
                }
            } : null
        ].filter(Boolean)
    });
}

/**
 * V3.0: ERP 图表 KPI 统计卡片 (Dashboard 版)
 */
function renderERPDashboardKPIs(stats, signalData) {
    const container = document.getElementById('erp-chart-kpis');
    if (!container) return;
    const snap = (signalData && signalData.current_snapshot) || {};
    const pct = snap.erp_percentile || '--';
    const deviation = stats.current_vs_mean;
    const devColor = deviation > 0 ? '#10b981' : (deviation < -5 ? '#ef4444' : '#f59e0b');
    const devSign = deviation > 0 ? '+' : '';

    container.innerHTML = [
        { label: '当前 ERP', value: (stats.current || '--') + '%', color: stats.current >= stats.overweight_line ? '#10b981' : (stats.current <= stats.underweight_line ? '#ef4444' : '#f59e0b') },
        { label: '均值偏离', value: devSign + deviation + '%', color: devColor },
        { label: '近4年分位', value: pct + '%', color: pct >= 70 ? '#10b981' : (pct <= 30 ? '#ef4444' : '#94a3b8') },
        { label: '超配区占比', value: (stats.buy_zone_pct || '--') + '%', color: '#10b981' },
    ].map(k => `<div style="flex:1;background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 12px;text-align:center;">
        <div style="font-size:0.65rem;color:#64748b;margin-bottom:3px;">${k.label}</div>
        <div style="font-size:1.1rem;font-weight:800;color:${k.color};">${k.value}</div>
    </div>`).join('');
}

// ERP 图表 + AIAE 仪表盘 — resize 由 AC (alphacore_utils.js) 统一管理
let _aiaeThermGauge = null;

// ====================================================================
//  AIAE 温度计 · 量化总览精简渲染引擎
// ====================================================================

function renderAIAEThermometer(d) {
    if (!d) return;
    // 使用全局 el() 工具函数

    // ── 仪表盘大字 ──
    const v1 = d.aiae_v1 || 0;
    if (el('aiae-thermo-val')) el('aiae-thermo-val').textContent = v1.toFixed(1);

    // ── ECharts 小仪表盘 ──
    try {
        const gaugeEl = el('aiae-thermo-gauge');
        if (gaugeEl && typeof echarts !== 'undefined') {
            if (_aiaeThermGauge) _aiaeThermGauge = AC.disposeChart(_aiaeThermGauge);
            _aiaeThermGauge = AC.registerChart(echarts.init(gaugeEl));
            const rc = d.regime_color || '#eab308';
            _aiaeThermGauge.setOption({
                series: [{
                    type: 'gauge',
                    startAngle: 200,
                    endAngle: -20,
                    min: 0,
                    max: 50,
                    pointer: {
                        show: true, length: '55%', width: 3.5,
                        itemStyle: { color: rc, shadowColor: rc, shadowBlur: 6 },
                        icon: 'triangle'
                    },
                    anchor: {
                        show: true, size: 8,
                        itemStyle: { color: '#0f172a', borderColor: rc, borderWidth: 2 }
                    },
                    axisLine: {
                        lineStyle: {
                            width: 12,
                            color: [
                                [0.24, '#10b981'], [0.32, '#3b82f6'],
                                [0.48, '#eab308'], [0.64, '#f97316'], [1, '#ef4444']
                            ]
                        }
                    },
                    axisTick: { length: 6, distance: -12, lineStyle: { color: 'auto', width: 1 } },
                    splitLine: { length: 10, distance: -12, lineStyle: { color: 'auto', width: 1.5 } },
                    splitNumber: 5,
                    axisLabel: {
                        distance: -30, color: '#64748b', fontSize: 8,
                        formatter: function(val) {
                            var m = {0:'0',10:'10',20:'20',30:'30',40:'40',50:'50'};
                            return m[val] || '';
                        }
                    },
                    detail: { show: false },
                    data: [{ value: Math.min(Math.max(v1, 0), 50) }],
                    animationDuration: 1000,
                    animationEasingUpdate: 'cubicOut'
                }]
            });
        }
    } catch(e) { console.warn('[AIAE Thermo] gauge skip:', e); }

    // ── 档位徽章 ──
    const regimeEl = el('aiae-thermo-regime');
    if (regimeEl) {
        regimeEl.textContent = (d.regime_emoji || '🟡') + ' ' + (d.regime_cn || '中性均衡');
        regimeEl.style.color = d.regime_color || '#eab308';
        regimeEl.style.borderColor = (d.regime_color || '#eab308') + '66';
        regimeEl.style.background = (d.regime_color || '#eab308') + '18';
    }

    // ── 月环比斜率 ──
    const slopeEl = el('aiae-thermo-slope');
    if (slopeEl) {
        const slope = d.slope || 0;
        const dir = d.slope_direction || 'flat';
        const arrow = dir === 'rising' ? '↗' : (dir === 'falling' ? '↘' : '→');
        slopeEl.textContent = '月环比: ' + arrow + ' ' + (slope > 0 ? '+' : '') + slope;
        slopeEl.style.color = dir === 'rising' ? '#f97316' : (dir === 'falling' ? '#10b981' : '#94a3b8');
    }

    // ── 五档高亮 ──
    const tiers = document.querySelectorAll('#aiae-thermo-tiers .at-tier');
    tiers.forEach(t => {
        const tier = parseInt(t.dataset.tier);
        t.classList.toggle('active', tier === d.regime);
    });

    // ── Cap 仓位 ──
    const cap = d.cap || 0;
    if (el('aiae-thermo-cap')) el('aiae-thermo-cap').textContent = cap + '%';
    if (el('aiae-thermo-cap-bar')) el('aiae-thermo-cap-bar').style.width = cap + '%';

    // ── 三大预警 ──
    // 融资热度
    const mh = d.margin_heat || 0;
    if (el('at-warn-margin')) {
        el('at-warn-margin').textContent = mh + '%';
        el('at-warn-margin').style.color = mh > 3.5 ? '#ef4444' : mh > 2.5 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-margin-bar')) {
        el('at-warn-margin-bar').style.width = Math.min(mh / 5 * 100, 100) + '%';
        el('at-warn-margin-bar').style.background = mh > 3.5 ? '#ef4444' : mh > 2.5 ? '#f59e0b' : '#10b981';
    }
    // 月斜率
    const absSlope = Math.abs(d.slope || 0);
    if (el('at-warn-slope')) {
        el('at-warn-slope').textContent = (d.slope > 0 ? '+' : '') + (d.slope || 0);
        el('at-warn-slope').style.color = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-slope-bar')) {
        el('at-warn-slope-bar').style.width = Math.min(absSlope / 3 * 100, 100) + '%';
        el('at-warn-slope-bar').style.background = absSlope > 1.5 ? '#ef4444' : absSlope > 0.8 ? '#f59e0b' : '#10b981';
    }
    // 基金仓位
    const fp = d.fund_position || 0;
    if (el('at-warn-fund')) {
        el('at-warn-fund').textContent = fp + '%';
        el('at-warn-fund').style.color = fp > 90 ? '#ef4444' : fp > 85 ? '#f59e0b' : '#10b981';
    }
    if (el('at-warn-fund-bar')) {
        el('at-warn-fund-bar').style.width = Math.min(fp / 100 * 100, 100) + '%';
        el('at-warn-fund-bar').style.background = fp > 90 ? '#ef4444' : fp > 85 ? '#f59e0b' : '#10b981';
    }

    // ── 数据来源 ──
    if (el('at-src-simple')) el('at-src-simple').textContent = 'AIAE_简: ' + (d.aiae_simple || 0) + '%';
    if (el('at-src-erp')) el('at-src-erp').textContent = 'ERP: ' + (d.erp_value || 0) + '%';

    // ── 操作指引 (按档位) ──
    const actionMap = {
        1: '🟢 Ⅰ级恐慌 · 分3批满仓进攻，越跌越买。优先宽基ETF (300/50/500)',
        2: '🔵 Ⅱ级低配 · 标准建仓区，按节奏买入。不因波动减仓，坚定持有',
        3: '🟡 Ⅲ级中性 · 维持均衡仓位，有纪律持有。到目标价就卖，不贪婪',
        4: '🟠 Ⅳ级偏热 · 禁止新开仓。每周减5%总仓位，优先清退高波动标的',
        5: '🔴 Ⅴ级过热 · 绝对禁止买入！3天内完成清仓，无例外执行'
    };
    if (el('aiae-thermo-action-text')) {
        el('aiae-thermo-action-text').textContent = actionMap[d.regime] || actionMap[3];
    }
}
