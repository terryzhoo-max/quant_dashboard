// ============================================================
// alphacore_utils.js — AlphaCore 共享工具库 (Phase 2)
// 被 strategy.html + treasury.html 共同引用
// 在 echarts.min.js 之后、页面 JS 之前加载
// ============================================================
(function() {
    'use strict';
    var AC = window.AlphaCore = window.AC = {};

    // ── DOM 工具函数 ──
    AC.setText = function(id, v) {
        var el = document.getElementById(id);
        if (el) el.textContent = v;
    };

    AC.setColor = function(id, c) {
        var el = document.getElementById(id);
        if (el) el.style.color = c;
    };

    AC.setHTML = function(id, html) {
        var el = document.getElementById(id);
        if (el) el.innerHTML = html;
    };

    // ── 实时时钟 ──
    AC.startClock = function(elementId) {
        elementId = elementId || 'st-time';
        function tick() {
            var now = new Date();
            var pad = function(n) { return n.toString().padStart(2, '0'); };
            var el = document.getElementById(elementId);
            if (el) el.textContent = now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) + ' ' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
        }
        tick();
        setInterval(tick, 1000);
    };

    // ── 导航高亮 ──
    AC.initNavigation = function() {
        var navItems = document.querySelectorAll('.nav-item');
        navItems.forEach(function(item) {
            item.addEventListener('click', function(e) {
                var href = item.getAttribute('href');
                if (!href || href === '#') e.preventDefault();
                navItems.forEach(function(nav) { nav.classList.remove('active'); });
                item.classList.add('active');
            });
        });
    };

    // ── Tab 切换系统 ──
    AC.initTabSystem = function(onTabSwitch) {
        var tabs = document.querySelectorAll('.st-tab');
        var reports = document.querySelectorAll('.st-report');
        tabs.forEach(function(tab) {
            tab.addEventListener('click', function() {
                var targetId = tab.dataset.report;
                tabs.forEach(function(t) { t.classList.remove('active'); });
                reports.forEach(function(r) { r.classList.remove('active'); });
                tab.classList.add('active');
                var target = document.getElementById(targetId);
                if (target) target.classList.add('active');
                var dash = document.querySelector('.dashboard');
                if (dash) dash.scrollTo({ top: 0, behavior: 'smooth' });
                if (typeof onTabSwitch === 'function') onTabSwitch(targetId);
            });
        });
    };

    // ── ECharts 统一 Resize 注册中心 ──
    AC._charts = new Set();

    AC.registerChart = function(chartInstance) {
        if (chartInstance) AC._charts.add(chartInstance);
        return chartInstance;
    };

    AC.disposeChart = function(chartInstance) {
        if (chartInstance) {
            AC._charts.delete(chartInstance);
            try { chartInstance.dispose(); } catch(e) {}
        }
        return null;
    };

    // 全局唯一 resize listener（200ms 防抖）
    var _resizeTimer = null;
    window.addEventListener('resize', function() {
        clearTimeout(_resizeTimer);
        _resizeTimer = setTimeout(function() {
            AC._charts.forEach(function(c) {
                try {
                    if (c && typeof c.resize === 'function' && !c.isDisposed()) {
                        c.resize();
                    } else if (c && c.isDisposed && c.isDisposed()) {
                        AC._charts.delete(c);
                    }
                } catch(e) {}
            });
        }, 200);
    });

})();
