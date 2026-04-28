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

    // ── 安全通信封装 (Batch 6.1, V17.3: GET免认证) ──
    AC.secureFetch = async function(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const isReadOnly = (method === 'GET' || method === 'HEAD');

        options.headers = options.headers || {};

        // GET/HEAD 请求免认证 (与后端 auth_middleware 一致)
        // 仅 POST/PUT/DELETE 需要 API Key
        if (!isReadOnly) {
            let apiKey = localStorage.getItem('alphacore_api_key');
            if (!apiKey) {
                apiKey = prompt("⚠️ 安全拦截：请输入您的系统 API Key (X-API-Key) 以继续该操作：");
                if (!apiKey) {
                    const err = new Error("未提供验证凭据，操作已取消。");
                    err.isCancelled = true;
                    alert(err.message);
                    throw err;
                }
                localStorage.setItem('alphacore_api_key', apiKey);
            }
            options.headers['X-API-Key'] = apiKey;
        }

        if (options.body && typeof options.body === 'string' && !options.headers['Content-Type']) {
            options.headers['Content-Type'] = 'application/json';
        }

        const res = await fetch(url, options);

        if (res.status === 401 || res.status === 403) {
            localStorage.removeItem('alphacore_api_key');
            let errMsg = "API Key 无效或已过期，请重新操作。";
            try {
                const errJson = await res.json();
                if (errJson.message) errMsg = errJson.message;
            } catch (e) {}
            alert("🔒 安全拦截: " + errMsg);
            const err = new Error(errMsg);
            err.status = res.status;
            throw err;
        }

        return res;
    };

})();
