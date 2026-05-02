/* ═══════════════════════════════════════════════════════════════════ */
/*  AlphaCore · [公司中文名] — 品牌主题层                              */
/*  [Company English Name] Brand Theme                                */
/*                                                                     */
/*  使用说明:                                                          */
/*  1. 复制此文件并重命名为 {prefix}_audit.css                         */
/*  2. 全局替换 {prefix} 为公司前缀 (如 smic, byd, em, etc.)          */
/*  3. 修改 :root 中的品牌色 (只需改下方 6 个 HEX 值)                  */
/*  4. 在 HTML 中按顺序引入:                                           */
/*     <link href="./static/css/audit.css">                            */
/*     <link href="./static/css/{prefix}_audit.css">                   */
/*     <link href="./static/css/audit_bridge.css">                     */
/* ═══════════════════════════════════════════════════════════════════ */

/* ── 步骤 1: 修改品牌色 ── */
/* 只需修改以下 HEX 值, audit_bridge.css 会自动应用到所有组件 */
:root {
    --ac-panel-bg:           rgba(15, 23, 42, 0.65);
    --ac-panel-border:       rgba(255, 255, 255, 0.06);

    /* ★ 核心品牌色 — 替换为目标公司主色调 ★ */
    --ac-accent:             rgba(59, 130, 246, 0.25);      /* 主色 25% 透明 */
    --ac-accent-dim:         rgba(59, 130, 246, 0.07);      /* 主色 7% 透明 */
    --ac-accent-border:      rgba(59, 130, 246, 0.18);      /* 主色 18% 透明 */
    --ac-hero-gradient:      linear-gradient(90deg, #3b82f6, #6366f1, #a78bfa, #3b82f6);
    --ac-chart-bar:          linear-gradient(180deg, #3b82f6, #8b5cf6);
    --ac-verdict-gradient:   linear-gradient(90deg, #10b981, #3b82f6, #8b5cf6);
    --ac-conclusion-gradient:linear-gradient(90deg, #3b82f6, #8b5cf6);
    --ac-catalyst-color:     #3b82f6;

    /* ★ 品牌专属变量 — 可在 orb/logo-ring 中引用 ★ */
    /* --{prefix}-primary: #3b82f6; */
    /* --{prefix}-secondary: #8b5cf6; */
}

/* ── 步骤 2: Ambient Orbs (背景光效) ── */
/* 修改 rgba 色值匹配品牌色, 调整位置和动画时长实现差异化 */
.{prefix}-orb {
    position: fixed; border-radius: 50%;
    pointer-events: none; z-index: 0;
    filter: blur(120px); opacity: 0.45;
}
.{prefix}-orb-3 {
    top: 50%; left: 50%; width: 400px; height: 400px;
    background: rgba(59, 130, 246, 0.04);  /* ← 替换为品牌色 */
    animation: {prefix}Float 35s ease-in-out infinite reverse;
}
.{prefix}-orb-4 {
    bottom: -150px; right: -100px; width: 500px; height: 500px;
    background: rgba(99, 102, 241, 0.03);  /* ← 替换为辅助色 */
    animation: {prefix}Float 28s ease-in-out infinite;
}
@keyframes {prefix}Float {
    0%   { transform: translate(0,0) scale(1); }
    50%  { transform: translate(40px,-60px) scale(1.1); }
    100% { transform: translate(-20px,30px) scale(0.95); }
}

/* ── 步骤 3: Brand-specific overrides (可选) ── */
/* 以下样式覆盖 audit_bridge.css 的默认值, 只添加品牌独有的差异 */

.{prefix}-logo-ring {
    background: linear-gradient(135deg, rgba(59,130,246,0.2), rgba(99,102,241,0.1));
    border: 2px solid rgba(59,130,246,0.35);
    box-shadow: 0 0 30px rgba(59,130,246,0.12);
    --glow-color: rgba(59,130,246,0.15);  /* 驱动 audit_bridge 的 glowPulse */
}
.{prefix}-logo-text { color: #93c5fd; }  /* 品牌浅色 */
.{prefix}-ticker.a-share { background: rgba(239,68,68,0.1); color: #f87171; border: 1px solid rgba(239,68,68,0.18); }
.{prefix}-ticker.h-share { background: rgba(59,130,246,0.1); color: #60a5fa; border: 1px solid rgba(59,130,246,0.18); }
.{prefix}-sector-tag { background: rgba(139,92,246,0.07); color: #a78bfa; border: 1px solid rgba(139,92,246,0.12); }
.{prefix}-topbar-badge { color: #93c5fd; background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.18); }
.{prefix}-conclusion-title { color: #93c5fd; }
.{prefix}-conclusion-box {
    background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(99,102,241,0.03));
    border: 1px solid rgba(59,130,246,0.18);
}
.{prefix}-section-divider {
    background: linear-gradient(90deg, transparent, rgba(59,130,246,0.25), rgba(99,102,241,0.15), transparent);
}
