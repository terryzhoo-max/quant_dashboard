/**
 * AlphaCore · AI 决策助手 (V27.0 P2-A)
 * =========================================
 * 浮动聊天面板 — 可在任何页面唤醒。
 * 快捷键: Alt+A 或点击右下角 FAB 按钮。
 * 对话自动注入系统实时数据作为上下文。
 */
(function () {
    'use strict';

    const API = '/api/v1/assistant/chat';
    const MAX_HISTORY = 12; // 保留最近6轮

    let chatHistory = [];
    let isOpen = false;
    let isLoading = false;

    // ── 注入 DOM ──
    function injectUI() {
        if (document.getElementById('ac-ai-fab')) return;

        // FAB 按钮
        const fab = document.createElement('button');
        fab.id = 'ac-ai-fab';
        fab.innerHTML = '🤖';
        fab.title = 'AI 助手 (Alt+A)';
        fab.addEventListener('click', togglePanel);
        document.body.appendChild(fab);

        // 面板
        const panel = document.createElement('div');
        panel.id = 'ac-ai-panel';
        panel.innerHTML = `
            <div class="ai-panel-header">
                <div class="ai-panel-title">
                    <span class="ai-panel-icon">🤖</span>
                    <span>AlphaCore AI 助手</span>
                    <span class="ai-panel-badge">DeepSeek</span>
                </div>
                <div class="ai-panel-actions">
                    <button class="ai-btn-clear" id="ai-clear-btn" title="清空对话">🗑️</button>
                    <button class="ai-btn-close" id="ai-close-btn">✕</button>
                </div>
            </div>
            <div class="ai-messages" id="ai-messages">
                <div class="ai-msg ai-msg-system">
                    <div class="ai-msg-content">
                        你好！我是 AlphaCore AI 助手。我能基于你的<b>实时持仓、策略信号和宏观环境</b>回答问题。<br><br>
                        试试问我：
                        <div class="ai-quick-prompts">
                            <button class="ai-quick-btn" data-q="我的组合今天表现如何？">📊 今日表现</button>
                            <button class="ai-quick-btn" data-q="当前市场环境适合加仓吗？">🌡️ 加仓建议</button>
                            <button class="ai-quick-btn" data-q="哪些持仓风险最大？">⚠️ 风险排查</button>
                            <button class="ai-quick-btn" data-q="五大策略信号有什么矛盾？">🔬 信号分析</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="ai-input-area">
                <input type="text" id="ai-input" class="ai-input"
                       placeholder="输入问题... (Enter 发送)" autocomplete="off" />
                <button class="ai-send-btn" id="ai-send-btn">➤</button>
            </div>
        `;
        document.body.appendChild(panel);

        // 绑定事件
        document.getElementById('ai-close-btn').addEventListener('click', togglePanel);
        document.getElementById('ai-clear-btn').addEventListener('click', clearChat);
        document.getElementById('ai-send-btn').addEventListener('click', sendMessage);
        document.getElementById('ai-input').addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });

        // 快速问题按钮
        panel.querySelectorAll('.ai-quick-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById('ai-input').value = btn.dataset.q;
                sendMessage();
            });
        });

        // Alt+A 全局快捷键
        document.addEventListener('keydown', e => {
            if (e.altKey && e.key.toLowerCase() === 'a') {
                e.preventDefault();
                togglePanel();
            }
        });
    }

    function togglePanel() {
        const panel = document.getElementById('ac-ai-panel');
        const fab = document.getElementById('ac-ai-fab');
        if (!panel) return;
        isOpen = !isOpen;
        panel.classList.toggle('open', isOpen);
        fab.classList.toggle('active', isOpen);
        if (isOpen) {
            setTimeout(() => document.getElementById('ai-input')?.focus(), 200);
        }
    }

    function clearChat() {
        chatHistory = [];
        const container = document.getElementById('ai-messages');
        // 保留系统欢迎消息
        const msgs = container.querySelectorAll('.ai-msg:not(.ai-msg-system)');
        msgs.forEach(m => m.remove());
    }

    // ── 发送消息 ──
    async function sendMessage() {
        if (isLoading) return;
        const input = document.getElementById('ai-input');
        const text = input.value.trim();
        if (!text) return;

        input.value = '';
        appendMessage('user', text);
        chatHistory.push({ role: 'user', content: text });

        // 截断历史
        if (chatHistory.length > MAX_HISTORY) {
            chatHistory = chatHistory.slice(-MAX_HISTORY);
        }

        isLoading = true;
        const loadingId = appendMessage('assistant', '思考中...', true);

        try {
            const resp = await fetch(API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    history: chatHistory.slice(0, -1), // 不传当前 user msg (API会自动加)
                }),
            });

            const json = await resp.json();
            removeMessage(loadingId);

            if (json.code === 0 && json.data) {
                const reply = json.data.reply;
                appendMessage('assistant', reply);
                chatHistory.push({ role: 'assistant', content: reply });

                // 显示 provider 标签
                if (json.data.elapsed_ms) {
                    appendMeta(`${json.data.provider} · ${json.data.elapsed_ms}ms`);
                }
            } else {
                appendMessage('assistant', `❌ ${json.message || '请求失败'}`);
            }
        } catch (err) {
            removeMessage(loadingId);
            appendMessage('assistant', `❌ 网络错误: ${err.message}`);
        } finally {
            isLoading = false;
        }
    }

    // ── DOM 操作 ──
    let msgCounter = 0;

    function appendMessage(role, content, isLoading = false) {
        const container = document.getElementById('ai-messages');
        const id = `ai-msg-${++msgCounter}`;
        const div = document.createElement('div');
        div.id = id;
        div.className = `ai-msg ai-msg-${role}${isLoading ? ' ai-loading' : ''}`;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'ai-msg-content';

        if (role === 'assistant' && !isLoading) {
            // 渲染 markdown-lite (粗体/换行)
            contentDiv.innerHTML = content
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
                .replace(/【(.*?)】/g, '<span class="ai-section-tag">【$1】</span>')
                .replace(/\n/g, '<br>');
        } else if (isLoading) {
            contentDiv.innerHTML = '<span class="ai-typing">●●●</span>';
        } else {
            contentDiv.textContent = content;
        }

        div.appendChild(contentDiv);
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
        return id;
    }

    function appendMeta(text) {
        const container = document.getElementById('ai-messages');
        const div = document.createElement('div');
        div.className = 'ai-msg-meta';
        div.textContent = text;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    function removeMessage(id) {
        document.getElementById(id)?.remove();
    }

    // ── 注入 CSS ──
    function injectStyles() {
        if (document.getElementById('ac-ai-styles')) return;
        const style = document.createElement('style');
        style.id = 'ac-ai-styles';
        style.textContent = `
            /* ── FAB 按钮 ── */
            #ac-ai-fab {
                position: fixed; bottom: 28px; right: 28px; z-index: 10000;
                width: 56px; height: 56px; border-radius: 50%;
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border: none; cursor: pointer;
                font-size: 1.6rem; line-height: 56px; text-align: center;
                box-shadow: 0 4px 20px rgba(99,102,241,0.5), 0 0 40px rgba(99,102,241,0.15);
                transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
                animation: ac-fab-pulse 3s infinite;
            }
            #ac-ai-fab:hover {
                transform: scale(1.1);
                box-shadow: 0 6px 30px rgba(99,102,241,0.7);
            }
            #ac-ai-fab.active {
                background: linear-gradient(135deg, #4f46e5, #7c3aed);
                animation: none;
                transform: rotate(15deg) scale(0.95);
            }
            @keyframes ac-fab-pulse {
                0%, 100% { box-shadow: 0 4px 20px rgba(99,102,241,0.5); }
                50% { box-shadow: 0 4px 30px rgba(99,102,241,0.8), 0 0 60px rgba(139,92,246,0.2); }
            }

            /* ── 面板 ── */
            #ac-ai-panel {
                position: fixed; bottom: 96px; right: 28px; z-index: 9999;
                width: 420px; max-height: 580px;
                background: rgba(15, 17, 28, 0.96);
                backdrop-filter: blur(24px) saturate(1.4);
                -webkit-backdrop-filter: blur(24px) saturate(1.4);
                border: 1px solid rgba(99,102,241,0.2);
                border-radius: 16px;
                display: flex; flex-direction: column;
                box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 40px rgba(99,102,241,0.08);
                opacity: 0; transform: translateY(20px) scale(0.95);
                pointer-events: none;
                transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
            }
            #ac-ai-panel.open {
                opacity: 1; transform: translateY(0) scale(1);
                pointer-events: auto;
            }

            /* ── Header ── */
            .ai-panel-header {
                display: flex; justify-content: space-between; align-items: center;
                padding: 14px 18px;
                border-bottom: 1px solid rgba(255,255,255,0.06);
            }
            .ai-panel-title {
                display: flex; align-items: center; gap: 8px;
                font-size: 0.9rem; font-weight: 600; color: #e2e8f0;
            }
            .ai-panel-icon { font-size: 1.1rem; }
            .ai-panel-badge {
                font-size: 0.6rem; padding: 2px 6px; border-radius: 4px;
                background: rgba(99,102,241,0.2); color: #a5b4fc;
                font-family: 'Outfit', sans-serif; font-weight: 500;
            }
            .ai-panel-actions { display: flex; gap: 6px; }
            .ai-btn-clear, .ai-btn-close {
                background: none; border: none; cursor: pointer;
                font-size: 0.85rem; color: rgba(255,255,255,0.4);
                padding: 4px 6px; border-radius: 4px;
                transition: all 0.2s;
            }
            .ai-btn-clear:hover, .ai-btn-close:hover {
                color: #fff; background: rgba(255,255,255,0.08);
            }

            /* ── Messages ── */
            .ai-messages {
                flex: 1; overflow-y: auto; padding: 14px 16px;
                display: flex; flex-direction: column; gap: 10px;
                max-height: 400px; min-height: 200px;
                scrollbar-width: thin;
                scrollbar-color: rgba(255,255,255,0.1) transparent;
            }
            .ai-msg { display: flex; }
            .ai-msg-user { justify-content: flex-end; }
            .ai-msg-assistant { justify-content: flex-start; }
            .ai-msg-system { justify-content: center; }

            .ai-msg-content {
                max-width: 88%; padding: 10px 14px;
                border-radius: 12px; font-size: 0.82rem;
                line-height: 1.55; color: #e2e8f0;
            }
            .ai-msg-user .ai-msg-content {
                background: linear-gradient(135deg, #4f46e5, #6366f1);
                color: #fff; border-bottom-right-radius: 4px;
            }
            .ai-msg-assistant .ai-msg-content {
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.06);
                border-bottom-left-radius: 4px;
            }
            .ai-msg-system .ai-msg-content {
                background: rgba(99,102,241,0.06);
                border: 1px solid rgba(99,102,241,0.1);
                border-radius: 12px;
                max-width: 95%; font-size: 0.78rem;
                color: rgba(255,255,255,0.7);
            }
            .ai-msg-meta {
                text-align: right; font-size: 0.62rem;
                color: rgba(255,255,255,0.2); font-family: 'Outfit', sans-serif;
                padding-right: 4px;
            }

            .ai-section-tag {
                color: #a5b4fc; font-weight: 600;
            }

            /* ── Quick Prompts ── */
            .ai-quick-prompts {
                display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;
            }
            .ai-quick-btn {
                background: rgba(99,102,241,0.12); border: 1px solid rgba(99,102,241,0.2);
                color: #a5b4fc; padding: 4px 10px; border-radius: 6px;
                font-size: 0.72rem; cursor: pointer;
                transition: all 0.2s;
            }
            .ai-quick-btn:hover {
                background: rgba(99,102,241,0.25); border-color: rgba(99,102,241,0.4);
                color: #c7d2fe;
            }

            /* ── Input ── */
            .ai-input-area {
                display: flex; gap: 8px; padding: 12px 16px;
                border-top: 1px solid rgba(255,255,255,0.06);
            }
            .ai-input {
                flex: 1; background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px; padding: 10px 14px;
                color: #e2e8f0; font-size: 0.82rem;
                outline: none; transition: border-color 0.2s;
            }
            .ai-input:focus { border-color: rgba(99,102,241,0.5); }
            .ai-input::placeholder { color: rgba(255,255,255,0.25); }
            .ai-send-btn {
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border: none; border-radius: 8px; padding: 0 14px;
                color: #fff; font-size: 1rem; cursor: pointer;
                transition: all 0.2s;
            }
            .ai-send-btn:hover { transform: scale(1.05); }

            /* ── Loading ── */
            .ai-loading .ai-msg-content { opacity: 0.7; }
            .ai-typing {
                display: inline-block; font-size: 1.2rem; letter-spacing: 2px;
                animation: ac-typing 1.2s infinite;
            }
            @keyframes ac-typing {
                0%, 100% { opacity: 0.3; }
                50% { opacity: 1; }
            }

            /* ── Mobile ── */
            @media (max-width: 768px) {
                #ac-ai-panel {
                    width: calc(100vw - 24px); right: 12px; bottom: 130px;
                    max-height: 60vh;
                }
                #ac-ai-fab {
                    bottom: calc(64px + env(safe-area-inset-bottom, 0px));
                    right: 16px; width: 48px; height: 48px;
                    font-size: 1.3rem; line-height: 48px;
                }
            }
        `;
        document.head.appendChild(style);
    }

    // ── 初始化 ──
    function init() {
        injectStyles();
        injectUI();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
