// AlphaCore · 投资组合页面 JS
document.addEventListener('DOMContentLoaded', () => {
    // ====== 导航激活状态 ======
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const href = item.getAttribute('href');
            if (!href || href === '#') e.preventDefault();
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });

    // ====== 实时时间更新 ======
    function updateTime() {
        const now = new Date();
        const pad = n => n.toString().padStart(2, '0');
        const el = document.getElementById('pf-time');
        if (el) el.textContent = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    }
    updateTime();
    setInterval(updateTime, 1000);

    // ====== 报告标签切换 ======
    const tabs = document.querySelectorAll('.pf-tab');
    const reports = document.querySelectorAll('.pf-report');
    let chart2Rendered = false;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.dataset.report;
            tabs.forEach(t => t.classList.remove('active'));
            reports.forEach(r => r.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(targetId);
            if (target) target.classList.add('active');

            // 切换到 AI 云报告时懒加载图表
            if (targetId === 'report-aicloud' && !chart2Rendered) {
                chart2Rendered = true;
                setTimeout(() => renderAICloudChart(), 100);
            }

            // 滚动到顶部
            document.querySelector('.dashboard').scrollTo({ top: 0, behavior: 'smooth' });
        });
    });

    // ====== Chart.js 全局配置 ======
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";

    // ====== 报告一：伊朗石油 - 仓位配置环形图 ======
    renderAllocationChart();
});

function createDoughnut(canvasId, labels, data, colors, borderColors) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    new Chart(ctx.getContext('2d'), {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors,
                borderColor: borderColors,
                borderWidth: 2, hoverBorderWidth: 3, hoverOffset: 8, spacing: 3
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false, cutout: '55%',
            layout: { padding: 10 },
            plugins: {
                legend: {
                    position: 'right',
                    labels: { boxWidth: 14, boxHeight: 14, padding: 12, usePointStyle: true, pointStyle: 'rectRounded',
                        font: { size: 11.5, weight: '500' }, color: '#cbd5e1' }
                },
                tooltip: {
                    backgroundColor: 'rgba(13,16,23,0.95)', titleColor: '#fff', bodyColor: '#e2e8f0',
                    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, padding: 14, boxPadding: 6, usePointStyle: true,
                    callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed}%` }
                }
            },
            animation: { animateRotate: true, duration: 1200, easing: 'easeInOutQuart' }
        }
    });
}

function renderAllocationChart() {
    createDoughnut('pfAllocationChart',
        ['🛢️ 油气上游 25%','⛏️ 油服 20%','🚢 油运/LNG 15%','🛡️ 军工 10%','⚡ 新能源 10%','🥇 黄金 5%','💰 现金 10%','📉 对冲 5%'],
        [25, 20, 15, 10, 10, 5, 10, 5],
        ['rgba(59,130,246,0.8)','rgba(99,102,241,0.8)','rgba(14,165,233,0.8)','rgba(139,92,246,0.8)','rgba(16,185,129,0.8)','rgba(245,158,11,0.8)','rgba(148,163,184,0.6)','rgba(239,68,68,0.7)'],
        ['rgba(59,130,246,1)','rgba(99,102,241,1)','rgba(14,165,233,1)','rgba(139,92,246,1)','rgba(16,185,129,1)','rgba(245,158,11,1)','rgba(148,163,184,0.8)','rgba(239,68,68,1)']
    );
}

function renderAICloudChart() {
    createDoughnut('pfAllocationChart2',
        ['☁️ 云厂商 25%','🧠 AI芯片 20%','🏗️ AIDC/服务器 10%','🔧 算力租赁/CDN 15%','❄️ 液冷/电力 10%','💾 存储/HBM 10%','💰 现金 7%','📉 对冲 3%'],
        [25, 20, 10, 15, 10, 10, 7, 3],
        ['rgba(59,130,246,0.8)','rgba(139,92,246,0.8)','rgba(14,165,233,0.8)','rgba(99,102,241,0.8)','rgba(6,182,212,0.8)','rgba(245,158,11,0.8)','rgba(148,163,184,0.6)','rgba(239,68,68,0.7)'],
        ['rgba(59,130,246,1)','rgba(139,92,246,1)','rgba(14,165,233,1)','rgba(99,102,241,1)','rgba(6,182,212,1)','rgba(245,158,11,1)','rgba(148,163,184,0.8)','rgba(239,68,68,1)']
    );
}
