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
