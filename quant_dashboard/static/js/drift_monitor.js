/**
 * AlphaCore · 策略漂移监控面板 (Drift Monitor V1.0)
 * ====================================================
 * 调用 /api/v1/decision/drift-status API
 * 渲染 5 维漂移检测卡片 + Regime 分布饼图
 */
(function () {
    'use strict';

    // ── 状态配色映射 ──
    const STATUS_CONFIG = {
        ok:       { icon: '🟢', color: '#10b981', dotCls: 'dot-ok',       cardCls: 'status-ok' },
        warning:  { icon: '🟡', color: '#fbbf24', dotCls: 'dot-warning',  cardCls: 'status-warning' },
        critical: { icon: '🔴', color: '#ef4444', dotCls: 'dot-critical', cardCls: 'status-critical' },
    };

    // ── 卡片元数据 ──
    const CARD_META = {
        accuracy:          { icon: '📊', title: '准确率漂移' },
        regime_shift:      { icon: '🌍', title: '环境覆盖' },
        jcs_trend:         { icon: '📈', title: 'JCS 趋势' },
        conflict_trend:    { icon: '⚡', title: '矛盾趋势' },
        regime_transition: { icon: '🔄', title: 'Regime 切换预警' },
    };

    // ECharts 饼图实例
    let _regimePieChart = null;
    // 防重复加载标记
    let _isLoading = false;

    /**
     * 主加载函数 — 由 Tab 切换或按钮触发
     */
    async function loadDriftStatus(force) {
        const container = document.getElementById('drift-monitor-container');
        if (!container) return;

        // 防重复
        if (_isLoading && !force) return;
        _isLoading = true;

        // 显示 loading
        container.innerHTML = `
            <div class="drift-loading">
                <div class="drift-loading-spinner"></div>
                <div class="drift-loading-text">正在检测策略漂移状态...</div>
            </div>
        `;

        try {
            const resp = await fetch('/api/v1/decision/drift-status', {
                signal: AbortSignal.timeout(15000)
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            if (data.status !== 'success') {
                throw new Error(data.message || '接口返回错误');
            }

            renderDriftPanel(container, data);
        } catch (err) {
            console.warn('[DriftMonitor] 加载失败:', err.message);
            container.innerHTML = `
                <div class="drift-error">
                    ⚠️ 漂移检测加载失败: ${err.message}<br>
                    <button class="drift-refresh-btn" onclick="loadDriftStatus(true)" style="margin-top:12px;">🔄 重试</button>
                </div>
            `;
        } finally {
            _isLoading = false;
        }
    }

    /**
     * 渲染完整面板
     */
    function renderDriftPanel(container, data) {
        const level = data.drift_level || 'ok';
        const levelCfg = STATUS_CONFIG[level] || STATUS_CONFIG.ok;
        const checkedAt = data.checked_at
            ? new Date(data.checked_at).toLocaleString('zh-CN', {
                  year: 'numeric', month: '2-digit', day: '2-digit',
                  hour: '2-digit', minute: '2-digit'
              })
            : '—';

        let html = '';

        // ── 综合状态头部 ──
        html += `
            <div class="drift-header">
                <div class="drift-header-title">🩺 策略健康度监控</div>
                <div class="drift-level-badge level-${level}">
                    ${levelCfg.icon} ${_levelLabel(level)}
                </div>
                <div class="drift-header-summary">${_escapeHtml(data.summary || '')}</div>
                <div class="drift-header-time">最后检测: ${checkedAt}</div>
                <button class="drift-refresh-btn" onclick="loadDriftStatus(true)">🔄 重新检测</button>
            </div>
        `;

        // ── 5 维卡片 ──
        html += '<div class="drift-cards-grid">';
        const checks = data.checks || {};
        const cardOrder = ['accuracy', 'regime_shift', 'jcs_trend', 'conflict_trend', 'regime_transition'];

        for (const key of cardOrder) {
            const check = checks[key];
            if (!check) continue;
            const meta = CARD_META[key] || { icon: '📋', title: key };
            const sCfg = STATUS_CONFIG[check.status] || STATUS_CONFIG.ok;

            html += `<div class="drift-card ${sCfg.cardCls}">`;
            // 头部
            html += `
                <div class="drift-card-head">
                    <span class="drift-card-icon">${meta.icon}</span>
                    <span class="drift-card-title">${meta.title}</span>
                </div>
            `;
            // 状态行
            html += `
                <div class="drift-card-status">
                    <span class="drift-status-dot ${sCfg.dotCls}"></span>
                    <span class="drift-card-label">${_escapeHtml(check.label || '')}</span>
                </div>
            `;
            // 关键指标
            html += '<div class="drift-card-metrics">';
            html += _renderMetrics(key, check);
            html += '</div>';

            // ── P1-A 视觉重构组件注入 ──
            if (key === 'accuracy' && check.recent_signals) {
                html += '<div class="drift-accuracy-grid-label">近期信号正误历史:</div>';
                html += '<div class="drift-accuracy-grid">';
                check.recent_signals.forEach(sig => {
                    const dotCls = sig === 1 ? 'dot-win' : (sig === 0 ? 'dot-lose' : 'dot-pending');
                    const tooltip = sig === 1 ? '正确 (✅)' : (sig === 0 ? '错误 (❌)' : '数据回填中');
                    html += `<span class="drift-grid-dot ${dotCls}" title="${tooltip}"></span>`;
                });
                html += '</div>';
            }

            if (key === 'jcs_trend' && check.history) {
                html += '<div class="drift-sparkline-wrap"><canvas id="drift-jcs-spark"></canvas></div>';
            }

            if (key === 'conflict_trend' && check.history) {
                html += '<div class="drift-sparkline-wrap"><canvas id="drift-conflict-spark"></canvas></div>';
            }

            if (key === 'regime_transition' && check.aiae_simple != null) {
                const minVal = 10;
                const maxVal = 35;
                const pct = ((check.aiae_simple - minVal) / (maxVal - minVal)) * 100;
                const cappedPct = Math.max(0, Math.min(100, pct));
                html += `
                <div class="drift-slider-wrap">
                    <div class="drift-slider-track">
                        <div class="drift-slider-bar" style="left:${cappedPct}%"></div>
                        <div class="drift-slider-notch" style="left:10%" title="R1↔R2 (12.5%)"></div>
                        <div class="drift-slider-notch" style="left:28%" title="R2↔R3 (17.0%)"></div>
                        <div class="drift-slider-notch" style="left:52%" title="R3↔R4 (23.0%)"></div>
                        <div class="drift-slider-notch" style="left:80%" title="R4↔R5 (30.0%)"></div>
                    </div>
                    <div class="drift-slider-labels">
                        <span>R1</span>
                        <span>R2</span>
                        <span>R3</span>
                        <span>R4</span>
                        <span>R5</span>
                    </div>
                </div>`;
            }

            // Regime 饼图占位 (仅 regime_shift 卡片)
            if (key === 'regime_shift' && check.regime_distribution) {
                html += '<div id="drift-regime-pie" class="drift-regime-chart"></div>';
            }

            // 详情
            if (check.detail) {
                html += `<div class="drift-card-detail">${_escapeHtml(check.detail)}</div>`;
            }

            html += '</div>';
        }
        html += '</div>';

        container.innerHTML = html;

        // ── 渲染 Regime 饼图 ──
        const regimeCheck = checks.regime_shift;
        if (regimeCheck && regimeCheck.regime_distribution) {
            _renderRegimePie(regimeCheck.regime_distribution);
        }

        // ── 渲染 JCS & 矛盾 Sparklines ──
        if (checks.jcs_trend && checks.jcs_trend.history) {
            _drawSparkline('drift-jcs-spark', checks.jcs_trend.history, '#3b82f6');
        }
        if (checks.conflict_trend && checks.conflict_trend.history) {
            _drawSparkline('drift-conflict-spark', checks.conflict_trend.history, '#fbbf24');
        }
    }

    /**
     * Canvas 绘制微型趋势折线图
     */
    function _drawSparkline(canvasId, data, color) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;

        // 对齐清晰的 Retina 分辨率
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = 42 * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = '42px';
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = 40;

        if (!data || data.length < 2) return;

        const minVal = Math.min(...data);
        const maxVal = Math.max(...data);
        const valRange = maxVal - minVal || 1;

        ctx.clearRect(0, 0, w, h);

        // 创建微弱阴影渐变
        const gradient = ctx.createLinearGradient(0, 0, 0, h);
        gradient.addColorStop(0, color + '2b');
        gradient.addColorStop(1, color + '00');

        ctx.beginPath();
        for (let i = 0; i < data.length; i++) {
            const x = (i / (data.length - 1)) * w;
            const y = h - ((data[i] - minVal) / valRange) * (h - 10) - 5;
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.6;
        ctx.stroke();

        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // 绘制最后一个元素高亮小点
        const lastX = w;
        const lastY = h - ((data[data.length - 1] - minVal) / valRange) * (h - 10) - 5;
        ctx.beginPath();
        ctx.arc(lastX - 2, lastY, 3, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = '#0f172a';
        ctx.stroke();
    }


    /**
     * 根据卡片类型渲染关键指标 chips
     */
    function _renderMetrics(key, check) {
        let chips = '';
        switch (key) {
            case 'accuracy':
                if (check.total_accuracy != null)  chips += `<span class="drift-metric-chip">总体 ${check.total_accuracy}%</span>`;
                if (check.recent_accuracy != null)  chips += `<span class="drift-metric-chip">近期 ${check.recent_accuracy}%</span>`;
                if (check.drift_pct != null)        chips += `<span class="drift-metric-chip" style="color:${check.drift_pct >= 0 ? '#10b981' : '#f87171'}">漂移 ${check.drift_pct > 0 ? '+' : ''}${check.drift_pct}%</span>`;
                break;
            case 'regime_shift':
                if (check.current_regime != null)   chips += `<span class="drift-metric-chip">R${check.current_regime}</span>`;
                if (check.coverage_pct != null)     chips += `<span class="drift-metric-chip">覆盖 ${check.coverage_pct}%</span>`;
                break;
            case 'jcs_trend':
                if (check.current_jcs != null)      chips += `<span class="drift-metric-chip">当前 ${check.current_jcs}</span>`;
                if (check.trend_30d != null)         chips += `<span class="drift-metric-chip" style="color:${check.trend_30d >= 0 ? '#10b981' : '#f87171'}">${check.trend_30d > 0 ? '+' : ''}${check.trend_30d}</span>`;
                break;
            case 'conflict_trend':
                if (check.current_conflicts != null) chips += `<span class="drift-metric-chip">当前 ${check.current_conflicts}</span>`;
                if (check.trend_30d != null)         chips += `<span class="drift-metric-chip">30d ${check.trend_30d > 0 ? '+' : ''}${check.trend_30d}</span>`;
                break;
            case 'regime_transition':
                if (check.aiae_simple != null)       chips += `<span class="drift-metric-chip">AIAE ${check.aiae_simple}</span>`;
                if (check.nearest_threshold != null)  chips += `<span class="drift-metric-chip">阈值 ${check.nearest_threshold}</span>`;
                if (check.distance != null)          chips += `<span class="drift-metric-chip" style="color:${check.distance <= 0.5 ? '#fbbf24' : '#10b981'}">距 ${check.distance}pt</span>`;
                break;
        }
        return chips;
    }

    /**
     * Regime 分布饼图 (ECharts)
     */
    function _renderRegimePie(distribution) {
        const dom = document.getElementById('drift-regime-pie');
        if (!dom || typeof echarts === 'undefined') return;

        // 销毁旧实例
        if (_regimePieChart) {
            if (typeof AC !== 'undefined') AC.disposeChart(_regimePieChart);
            _regimePieChart = null;
        }

        _regimePieChart = echarts.init(dom, 'dark');
        if (typeof AC !== 'undefined') AC.registerChart(_regimePieChart);

        const regimeColors = {
            '1': '#10b981', '2': '#3b82f6', '3': '#eab308',
            '4': '#f97316', '5': '#ef4444'
        };
        const regimeNames = {
            '1': 'R1 低估', '2': 'R2 偏低', '3': 'R3 中性',
            '4': 'R4 偏高', '5': 'R5 高估'
        };

        const pieData = Object.entries(distribution).map(([k, v]) => ({
            name: regimeNames[k] || `R${k}`,
            value: v,
            itemStyle: { color: regimeColors[k] || '#94a3b8' }
        }));

        _regimePieChart.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'item',
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#e2e8f0', fontSize: 11 },
                formatter: '{b}: {c}% ({d}%)'
            },
            series: [{
                type: 'pie',
                radius: ['35%', '65%'],
                center: ['50%', '50%'],
                avoidLabelOverlap: true,
                itemStyle: {
                    borderRadius: 4,
                    borderColor: 'rgba(15, 23, 42, 0.8)',
                    borderWidth: 2
                },
                label: {
                    show: true,
                    fontSize: 9,
                    color: '#94a3b8',
                    formatter: '{b}\n{c}%'
                },
                labelLine: {
                    length: 8,
                    length2: 6,
                    lineStyle: { color: 'rgba(255,255,255,0.15)' }
                },
                emphasis: {
                    itemStyle: {
                        shadowBlur: 10,
                        shadowOffsetX: 0,
                        shadowColor: 'rgba(0, 0, 0, 0.5)'
                    }
                },
                data: pieData
            }]
        });
    }

    /**
     * 漂移等级中文标签
     */
    function _levelLabel(level) {
        const map = { ok: '策略健康', warning: '轻度漂移', critical: '严重漂移' };
        return map[level] || level;
    }

    /**
     * HTML 转义 (防 XSS)
     */
    function _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ── 暴露全局函数供 Tab 系统调用 ──
    window.loadDriftStatus = loadDriftStatus;

})();
