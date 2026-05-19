/**
 * AlphaCore · 全局搜索引擎 (V27.0 P1-D)
 * =========================================
 * 激活所有页面的装饰性搜索栏，提供：
 *   - 标的代码/名称 → 跳转审计页
 *   - 导航页面 → 跳转对应功能
 *   - 宏观/策略关键词 → 跳转对应面板
 *   - Ctrl+K 快捷键唤醒
 *
 * 自动绑定: 所有 .search-bar input 元素
 */

(function () {
    'use strict';

    // ── 搜索索引 ──
    const SEARCH_INDEX = [
        // ═══ 导航页面 ═══
        { type: 'page', label: '量化总览',   alias: ['dashboard', '首页', 'index', '总览'],  href: './index.html',     icon: '📊' },
        { type: 'page', label: '因子分析',   alias: ['factor', '因子', '多因子', 'SMB', 'HML'],  href: './factor.html',   icon: '📈' },
        { type: 'page', label: '产业追踪',   alias: ['industry', '产业', '板块', '行业'],  href: './industry.html',  icon: '🏭' },
        { type: 'page', label: '策略中心',   alias: ['strategy', '策略', '信号', '均值回归', 'mean reversion'],  href: './strategy.html', icon: '⚙️' },
        { type: 'page', label: '量化回测',   alias: ['backtest', '回测', '历史测试'],  href: './backtest.html',  icon: '🧪' },
        { type: 'page', label: '海外策略',   alias: ['treasury', '海外', '美债', '利率', 'FRED', '美股'],  href: './treasury.html', icon: '🌐' },
        { type: 'page', label: '决策中枢',   alias: ['decision', '决策', 'JCS', 'AIAE', '投委会', 'hub'],  href: './decision.html', icon: '🧠' },
        { type: 'page', label: '深度审计',   alias: ['audit', '审计', '风控', '体检'],  href: './audit.html',     icon: '🔍' },
        { type: 'page', label: '投资组合',   alias: ['portfolio', '组合', '持仓', '仓位', 'P&L'],  href: './portfolio.html', icon: '💼' },

        // ═══ 个股深研 ═══
        { type: 'stock', label: '中芯国际', code: '688981.SH', alias: ['SMIC', '芯片', '半导体'],  href: './smic_audit.html', icon: '🔬' },
        { type: 'stock', label: '紫金矿业', code: '601899.SH', alias: ['黄金', '铜', '矿业', '有色'],  href: './zijin_audit.html', icon: '⛏️' },
        { type: 'stock', label: '比亚迪',   code: '002594.SZ', alias: ['BYD', '新能源车', 'EV', '电动车'],  href: './byd_audit.html', icon: '🚗' },
        { type: 'stock', label: '东方财富', code: '300059.SZ', alias: ['互联网券商', '基金销售'],  href: './eastmoney_audit.html', icon: '💹' },
        { type: 'stock', label: '工业富联', code: '601138.SH', alias: ['FII', '富士康', '代工', 'AI服务器'],  href: './fii_audit.html', icon: '🤖' },
        { type: 'stock', label: '沪电股份', code: '002463.SZ', alias: ['PCB', '电路板', '通信'],  href: './wus_audit.html', icon: '💻' },
        { type: 'stock', label: '深南电路', code: '002916.SZ', alias: ['SCC', 'IC载板', '封装基板'],  href: './scc_audit.html', icon: '📡' },

        // ═══ 核心 ETF 标的 ═══
        { type: 'etf', label: '沪深300ETF',   code: '510300.SH', alias: ['CSI300', '300'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '上证50ETF',    code: '510050.SH', alias: ['SSE50', '大盘'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '中证500ETF',   code: '510500.SH', alias: ['CSI500', '500'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '创业板ETF',    code: '159915.SZ', alias: ['GEM', '创业板'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '中证1000ETF',  code: '512100.SH', alias: ['CSI1000', '小盘'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '科创50ETF',    code: '588000.SH', alias: ['STAR50', '科创'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '科创芯片ETF',  code: '588200.SH', alias: ['芯片', '半导体ETF'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '半导体ETF',    code: '512480.SH', alias: ['chip', '芯片ETF'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '军工ETF',      code: '512660.SH', alias: ['defense', '国防军工'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '消费ETF',      code: '159928.SZ', alias: ['consumer', '消费'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '医药ETF',      code: '512010.SH', alias: ['pharma', '医药'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '新能源ETF',    code: '516160.SH', alias: ['new energy'],  href: './strategy.html', icon: '📊' },
        { type: 'etf', label: '标普500ETF',   code: '513500.SH', alias: ['SPX', 'S&P500', '美股'],  href: './treasury.html', icon: '🌐' },
        { type: 'etf', label: '纳指100ETF',   code: '513300.SH', alias: ['QQQ', 'NASDAQ', '纳斯达克'],  href: './treasury.html', icon: '🌐' },
        { type: 'etf', label: '恒生科技ETF',  code: '513130.SH', alias: ['HSTECH', '港股科技'],  href: './treasury.html', icon: '🌐' },
        { type: 'etf', label: '日经ETF',      code: '513520.SH', alias: ['NKY', '日经225', '日股'],  href: './treasury.html', icon: '🌐' },
        { type: 'etf', label: '黄金ETF',      code: '518880.SH', alias: ['gold', '黄金'],  href: './strategy.html', icon: '📊' },

        // ═══ 宏观/策略关键词 ═══
        { type: 'macro', label: 'VIX 恐慌指数',    alias: ['VIX', '波动率', '恐慌'],  href: './index.html#vix', icon: '⚡' },
        { type: 'macro', label: 'ERP 股权风险溢价', alias: ['ERP', '风险溢价', '估值'],  href: './index.html#erp', icon: '📐' },
        { type: 'macro', label: 'AIAE 宏观仓位',   alias: ['AIAE', '仓位', '配置', '资产配置'],  href: './decision.html', icon: '🎯' },
        { type: 'macro', label: 'JCS 联合置信度',   alias: ['JCS', '置信度', '信心'],  href: './decision.html', icon: '🧠' },
        { type: 'macro', label: '均值回归信号',     alias: ['MR', 'mean reversion', 'RSI', 'BIAS'],  href: './strategy.html', icon: '🔄' },
        { type: 'macro', label: '动量轮动策略',     alias: ['momentum', '动量', '轮动'],  href: './strategy.html', icon: '🚀' },
        { type: 'macro', label: 'Brinson 绩效归因', alias: ['Brinson', '归因', 'attribution'],  href: './portfolio.html', icon: '🧬' },
        { type: 'macro', label: 'MCTR 风险贡献',   alias: ['MCTR', '边际风险', '风险贡献'],  href: './portfolio.html', icon: '📐' },
        { type: 'macro', label: '五策略共振',       alias: ['共振', 'consensus', '策略矩阵'],  href: './index.html', icon: '🎯' },
        { type: 'macro', label: '波段守卫',         alias: ['swing', 'guard', '波段'],  href: './strategy.html', icon: '🛡️' },
    ];

    // ── 模糊搜索 ──
    function fuzzyMatch(query, item) {
        const q = query.toLowerCase();
        // Match label
        if (item.label.toLowerCase().includes(q)) return { score: 100, match: 'label' };
        // Match code
        if (item.code && item.code.toLowerCase().includes(q)) return { score: 90, match: 'code' };
        // Match aliases
        for (const a of (item.alias || [])) {
            if (a.toLowerCase().includes(q)) return { score: 80, match: a };
        }
        return null;
    }

    function search(query) {
        if (!query || query.length < 1) return [];
        const results = [];
        for (const item of SEARCH_INDEX) {
            const m = fuzzyMatch(query, item);
            if (m) {
                results.push({ ...item, score: m.score, matchedOn: m.match });
            }
        }
        results.sort((a, b) => b.score - a.score);
        return results.slice(0, 8);
    }

    // ── 类型标签 ──
    function typeTag(type) {
        const tags = {
            page:  { text: '页面',   cls: 'ac-search-tag-page' },
            stock: { text: '个股',   cls: 'ac-search-tag-stock' },
            etf:   { text: 'ETF',    cls: 'ac-search-tag-etf' },
            macro: { text: '宏观',   cls: 'ac-search-tag-macro' },
        };
        return tags[type] || { text: type, cls: '' };
    }

    // ── 渲染下拉面板 ──
    function renderDropdown(results, container) {
        if (!results.length) {
            container.innerHTML = '<div class="ac-search-empty">无匹配结果 · 试试其他关键词</div>';
            container.style.display = 'block';
            return;
        }

        let html = '';
        for (let i = 0; i < results.length; i++) {
            const r = results[i];
            const tag = typeTag(r.type);
            const codeStr = r.code ? `<span class="ac-search-code">${r.code}</span>` : '';
            html += `<a href="${r.href}" class="ac-search-result${i === 0 ? ' ac-search-active' : ''}" data-idx="${i}">`;
            html += `<span class="ac-search-icon">${r.icon}</span>`;
            html += `<span class="ac-search-label">${r.label}</span>`;
            html += codeStr;
            html += `<span class="ac-search-tag ${tag.cls}">${tag.text}</span>`;
            html += '</a>';
        }
        container.innerHTML = html;
        container.style.display = 'block';
    }

    // ── 注入 CSS ──
    function injectStyles() {
        if (document.getElementById('ac-search-styles')) return;
        const style = document.createElement('style');
        style.id = 'ac-search-styles';
        style.textContent = `
            .ac-search-dropdown {
                display: none;
                position: absolute;
                top: calc(100% + 4px);
                left: 0; right: 0;
                background: rgba(15, 17, 28, 0.98);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(99, 102, 241, 0.2);
                border-radius: 12px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 30px rgba(99, 102, 241, 0.08);
                z-index: 9999;
                max-height: 420px;
                overflow-y: auto;
                padding: 6px;
            }
            .ac-search-result {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 10px 14px;
                border-radius: 8px;
                text-decoration: none;
                color: rgba(255,255,255,0.85);
                font-size: 0.85rem;
                transition: background 0.15s;
            }
            .ac-search-result:hover, .ac-search-result.ac-search-active {
                background: rgba(99, 102, 241, 0.12);
                color: #fff;
            }
            .ac-search-icon { font-size: 1.1rem; flex-shrink: 0; width: 24px; text-align: center; }
            .ac-search-label { flex: 1; font-weight: 500; }
            .ac-search-code {
                font-family: 'Outfit', monospace;
                font-size: 0.75rem;
                color: rgba(255,255,255,0.4);
                margin-right: 4px;
            }
            .ac-search-tag {
                font-size: 0.65rem;
                padding: 2px 7px;
                border-radius: 4px;
                font-weight: 600;
                letter-spacing: 0.03em;
                flex-shrink: 0;
            }
            .ac-search-tag-page  { background: rgba(59,130,246,0.15); color: #60a5fa; }
            .ac-search-tag-stock { background: rgba(239,68,68,0.12); color: #f87171; }
            .ac-search-tag-etf   { background: rgba(16,185,129,0.12); color: #34d399; }
            .ac-search-tag-macro { background: rgba(245,158,11,0.12); color: #fbbf24; }
            .ac-search-empty {
                text-align: center;
                color: rgba(255,255,255,0.3);
                padding: 20px;
                font-size: 0.8rem;
            }
            .ac-search-hint {
                text-align: center;
                padding: 6px;
                font-size: 0.7rem;
                color: rgba(255,255,255,0.25);
                border-top: 1px solid rgba(255,255,255,0.06);
                margin-top: 4px;
            }
            .ac-search-kbd {
                display: inline-block;
                padding: 1px 5px;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 3px;
                font-size: 0.65rem;
                font-family: 'Outfit', monospace;
                margin: 0 2px;
            }
            .search-bar { position: relative; }
        `;
        document.head.appendChild(style);
    }

    // ── 绑定搜索栏 ──
    function bindSearchBars() {
        const searchBars = document.querySelectorAll('.search-bar');

        searchBars.forEach(bar => {
            const input = bar.querySelector('input');
            if (!input || input.dataset.acBound) return;
            input.dataset.acBound = 'true';

            // Create dropdown
            const dropdown = document.createElement('div');
            dropdown.className = 'ac-search-dropdown';
            bar.appendChild(dropdown);

            let activeIdx = 0;
            let currentResults = [];

            // Input handler
            input.addEventListener('input', () => {
                const q = input.value.trim();
                currentResults = search(q);
                activeIdx = 0;

                if (q.length === 0) {
                    dropdown.style.display = 'none';
                    return;
                }
                renderDropdown(currentResults, dropdown);
                if (currentResults.length > 0) {
                    dropdown.innerHTML += '<div class="ac-search-hint"><span class="ac-search-kbd">↑↓</span> 导航 · <span class="ac-search-kbd">Enter</span> 跳转 · <span class="ac-search-kbd">Esc</span> 关闭</div>';
                }
            });

            // Keyboard navigation
            input.addEventListener('keydown', (e) => {
                if (dropdown.style.display === 'none') return;
                const items = dropdown.querySelectorAll('.ac-search-result');
                if (!items.length) return;

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    items[activeIdx]?.classList.remove('ac-search-active');
                    activeIdx = (activeIdx + 1) % items.length;
                    items[activeIdx]?.classList.add('ac-search-active');
                    items[activeIdx]?.scrollIntoView({ block: 'nearest' });
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    items[activeIdx]?.classList.remove('ac-search-active');
                    activeIdx = (activeIdx - 1 + items.length) % items.length;
                    items[activeIdx]?.classList.add('ac-search-active');
                    items[activeIdx]?.scrollIntoView({ block: 'nearest' });
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    const active = items[activeIdx];
                    if (active) window.location.href = active.getAttribute('href');
                } else if (e.key === 'Escape') {
                    dropdown.style.display = 'none';
                    input.blur();
                }
            });

            // Close on blur
            input.addEventListener('blur', () => {
                setTimeout(() => { dropdown.style.display = 'none'; }, 200);
            });

            // Focus handler — show hint
            input.addEventListener('focus', () => {
                if (input.value.trim().length > 0) {
                    currentResults = search(input.value.trim());
                    renderDropdown(currentResults, dropdown);
                }
            });
        });
    }

    // ── Ctrl+K 快捷键 ──
    function bindShortcut() {
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const input = document.querySelector('.search-bar input');
                if (input) {
                    input.focus();
                    input.select();
                }
            }
        });
    }

    // ── 启动 ──
    function init() {
        injectStyles();
        bindSearchBars();
        bindShortcut();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
