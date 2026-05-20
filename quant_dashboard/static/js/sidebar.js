/**
 * AlphaCore · 统一导航栏组件 (V27.0 P1-E)
 * ==========================================
 * 消灭 10+ 页面重复侧边栏代码，单一来源管理。
 * 
 * 使用方式:
 *   <aside class="sidebar" id="ac-sidebar"></aside>
 *   <script src="./static/js/sidebar.js?v=1"></script>
 * 
 * 自动功能:
 *   - 根据当前 URL 自动高亮 active 导航项
 *   - 侧边栏收缩/展开 toggle
 *   - 个股深研子菜单折叠
 */

(function () {
    'use strict';

    // ── 导航数据结构 ──
    const NAV_CONFIG = [
        {
            group: '情 报 中 心',
            items: [
                { href: './index.html',    icon: '📊', label: '量化总览' },
                { href: './factor.html',   icon: '📈', label: '因子分析' },
                { href: './industry.html', icon: '🏭', label: '产业追踪' },
            ]
        },
        {
            group: '策 略 实 验 室',
            items: [
                { href: './strategy.html',  icon: '⚙️', label: '策略中心' },
                { href: './backtest.html',  icon: '🧪', label: '量化回测', badge: 'Beta' },
                { href: './treasury.html',  icon: '🌐', label: '海外策略' },
            ]
        },
        {
            group: '科 学 决 策',
            items: [
                { href: './decision.html', icon: '🧠', label: '决策中枢' },
                { href: './report.html',   icon: '📄', label: '投委会简报', badge: 'PDF' },
            ]
        },
        {
            group: '研 究 审 计',
            items: [
                { href: './audit.html', icon: '🔍', label: '深度审计' },
            ],
            subMenu: {
                parentIcon: '📑',
                parentLabel: '个股深研',
                items: [
                    { href: './smic_audit.html',      icon: '🔬', label: '中芯国际', badgeColor: 'rgba(239,68,68,0.15)',  textColor: '#f87171', borderColor: 'rgba(239,68,68,0.3)' },
                    { href: './zijin_audit.html',     icon: '⛏️', label: '紫金矿业', badgeColor: 'rgba(245,158,11,0.15)', textColor: '#fbbf24', borderColor: 'rgba(245,158,11,0.3)' },
                    { href: './byd_audit.html',       icon: '🚗', label: '比亚迪',   badgeColor: 'rgba(16,185,129,0.15)',  textColor: '#34d399', borderColor: 'rgba(16,185,129,0.3)' },
                    { href: './eastmoney_audit.html', icon: '💹', label: '东方财富', badgeColor: 'rgba(37,99,235,0.15)',   textColor: '#60a5fa', borderColor: 'rgba(37,99,235,0.3)' },
                    { href: './fii_audit.html',       icon: '🤖', label: '工业富联', badgeColor: 'rgba(14,165,233,0.15)',  textColor: '#38bdf8', borderColor: 'rgba(14,165,233,0.3)' },
                    { href: './wus_audit.html',       icon: '💻', label: '沪电股份', badgeColor: 'rgba(236,72,153,0.15)',  textColor: '#f472b6', borderColor: 'rgba(236,72,153,0.3)' },
                    { href: './scc_audit.html',       icon: '📡', label: '深南电路', badgeColor: 'rgba(139,92,246,0.15)',  textColor: '#a855f7', borderColor: 'rgba(139,92,246,0.3)' },
                ]
            }
        },
        {
            group: '账 户 管 理',
            items: [
                { href: './portfolio.html', icon: '💼', label: '投资组合' },
            ]
        }
    ];

    // ── 当前页面匹配 ──
    function getCurrentPage() {
        const path = window.location.pathname;
        const filename = path.substring(path.lastIndexOf('/') + 1) || 'index.html';
        return './' + filename;
    }

    // ── 渲染导航 HTML ──
    function renderSidebar() {
        const currentPage = getCurrentPage();
        const isSubPage = NAV_CONFIG.some(g => 
            g.subMenu && g.subMenu.items.some(i => i.href === currentPage)
        );

        let html = '';

        // Logo
        html += '<div class="logo"><div class="logo-icon"></div><h1>AlphaCore</h1></div>';

        // Nav menu
        html += '<nav class="nav-menu">';

        for (const group of NAV_CONFIG) {
            html += `<div class="nav-group-title">${group.group}</div>`;

            for (const item of group.items) {
                const isActive = item.href === currentPage ? ' active' : '';
                const tooltip = item.label;
                html += `<a href="${item.href}" class="nav-item${isActive}" data-tooltip="${tooltip}">`;
                html += `<span class="icon">${item.icon}</span>`;
                html += `<span>${item.label}</span>`;
                if (item.badge) {
                    html += `<span class="badge-beta">${item.badge}</span>`;
                }
                html += '</a>';
            }

            // Sub-menu (个股深研)
            if (group.subMenu) {
                const sub = group.subMenu;
                const subOpen = isSubPage ? ' open' : '';
                html += `<div class="nav-parent${subOpen}" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">`;
                html += `<span class="icon">${sub.parentIcon}</span>`;
                html += `<span>${sub.parentLabel}</span>`;
                html += '<span class="nav-arrow">▶</span></div>';
                html += `<div class="nav-sub-group${subOpen}">`;

                for (const si of sub.items) {
                    const siActive = si.href === currentPage ? ' active' : '';
                    html += `<a href="${si.href}" class="nav-item${siActive}">`;
                    html += `<span class="icon">${si.icon}</span>`;
                    html += `<span>${si.label}</span>`;
                    html += `<span class="badge-beta" style="background:${si.badgeColor};color:${si.textColor};border-color:${si.borderColor};">DEEP</span>`;
                    html += '</a>';
                }

                html += '</div>';
            }
        }

        html += '</nav>';

        // Sidebar toggle
        html += '<button class="sidebar-toggle" id="sidebar-toggle" title="收缩/展开">';
        html += '<i class="toggle-icon">◀</i><span class="toggle-text">收起导航</span></button>';

        // User profile
        html += '<div class="user-profile">';
        html += '<img src="https://i.pravatar.cc/150?img=11" alt="User Avatar">';
        html += '<div class="user-info">';
        html += '<span class="name">基金经理 Pro</span>';
        html += '<span class="role">顶级投研权限</span>';
        html += '</div></div>';

        return html;
    }

    // ── 初始化侧边栏 toggle 行为 ──
    function initToggle() {
        const toggle = document.getElementById('sidebar-toggle');
        if (!toggle) return;

        const sidebar = toggle.closest('.sidebar') || document.querySelector('.sidebar');
        if (!sidebar) return;

        // 恢复收缩状态
        const collapsed = localStorage.getItem('ac-sidebar-collapsed') === 'true';
        if (collapsed) {
            sidebar.classList.add('collapsed');
        }

        toggle.addEventListener('click', function () {
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            localStorage.setItem('ac-sidebar-collapsed', isCollapsed);
        });
    }

    // ── 动态加载全局模块 (V27.0: 侧边栏作为全局组件分发中心) ──
    function loadGlobalModules() {
        // JS 模块
        const scripts = [
            './static/js/ai_assistant.js?v=2',
        ];
        for (const src of scripts) {
            if (!document.querySelector(`script[src="${src}"]`)) {
                const s = document.createElement('script');
                s.src = src;
                s.defer = true;
                document.body.appendChild(s);
            }
        }
        // CSS 模块 (移动端响应式)
        const styles = [
            './static/css/mobile.css?v=3',
        ];
        for (const href of styles) {
            if (!document.querySelector(`link[href="${href}"]`)) {
                const l = document.createElement('link');
                l.rel = 'stylesheet';
                l.href = href;
                document.head.appendChild(l);
            }
        }
    }

    // ── 移动端底部导航 (V27.0 P2-C) ──
    function injectMobileNav() {
        if (document.getElementById('ac-mobile-nav')) return;
        const currentPage = getCurrentPage();
        const tabs = [
            { href: './index.html',     icon: '📊', label: '总览' },
            { href: './decision.html',  icon: '🧠', label: '决策' },
            { href: './strategy.html',  icon: '⚙️', label: '策略' },
            { href: './portfolio.html', icon: '💼', label: '组合' },
            { href: './report.html',    icon: '📄', label: '简报' },
        ];
        const nav = document.createElement('nav');
        nav.id = 'ac-mobile-nav';
        nav.innerHTML = tabs.map(t => {
            const active = t.href === currentPage ? ' active' : '';
            return `<a href="${t.href}" class="${active}"><span class="mn-icon">${t.icon}</span>${t.label}</a>`;
        }).join('');
        document.body.appendChild(nav);
    }

    // ── 挂载 ──
    function mount() {
        const container = document.querySelector('.sidebar') || document.getElementById('ac-sidebar');
        if (!container) return;

        container.innerHTML = renderSidebar();
        initToggle();
        loadGlobalModules();
        injectMobileNav();
    }

    // DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();
