/**
 * AlphaCore V21.2 · 共享基础设施 (所有决策模块依赖)
 * ==================================================
 * 必须在所有 decision/ 子模块之前加载
 * 
 * 提供:
 *   - API_BASE: API 基础路径
 *   - _chartInstances: ECharts 实例管理器
 *   - _getChart(): 安全获取 ECharts 实例 (自动 dispose 旧实例)
 *   - _fmt(): 安全数值格式化
 *   - _riskMatrixCache: 风控护栏缓存
 */

const API_BASE = '/api/v1/decision';

/** ECharts 统一实例管理器: 防内存泄漏, 自动 dispose 旧实例 */
const _chartInstances = {};
function _getChart(domId) {
    const el = document.getElementById(domId);
    if (!el || typeof echarts === 'undefined') return null;
    if (_chartInstances[domId]) _chartInstances[domId].dispose();
    const chart = echarts.init(el);
    _chartInstances[domId] = chart;
    return chart;
}

/** 安全数值格式化: 防止 null/undefined.toFixed() 崩溃 */
const _fmt = (v, d = 1, fallback = '--') =>
    (v != null && !isNaN(v)) ? Number(v).toFixed(d) : fallback;

/** risk-matrix 响应缓存 (Tab1 风控护栏 + Tab3 风险矩阵共用) */
let _riskMatrixCache = null;

/** V22.0 O2: 颜色工具 — hex '#ff00ff' → '255,0,255' (CSS 变量注入用) */
const _hexToRgb = (hex) => {
    if (!hex || hex.length < 7) return '148,163,184';
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return isNaN(r) ? '148,163,184' : `${r},${g},${b}`;
};

/** V22.0 O4: AC 就绪标志 — 供各模块在调用前快速检查依赖就绪状态 */
window.AC_READY = typeof AC !== 'undefined';
