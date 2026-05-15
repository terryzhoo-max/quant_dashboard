/**
 * AlphaCore · Service Worker V1.0
 * ================================
 * 策略:
 *   - 静态资源 (CSS/JS/Font): Cache-First (版本号哈希控制更新)
 *   - API 请求 (/api/v1/*): NetworkFirst, 失败回 IndexedDB 快照
 *   - HTML 页面: NetworkFirst, 离线回 app shell
 *   - CDN 资源 (ECharts/Fonts): Cache-First (长期缓存)
 */

const CACHE_VERSION = 'alphacore-v2';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const API_CACHE = `${CACHE_VERSION}-api`;

// 预缓存: 核心 app shell
const PRECACHE_URLS = [
  '/decision',
  '/static/css/styles.css',
  '/static/css/decision.css',
  '/static/css/visual_excellence.css',
  '/static/css/fonts.css',
  '/static/css/mobile.css',
  '/static/js/alphacore_utils.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// ── Install: 预缓存核心资源 ──
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      console.log('[SW] Pre-caching app shell');
      return cache.addAll(PRECACHE_URLS).catch(err => {
        console.warn('[SW] Pre-cache partial fail (non-blocking):', err);
      });
    })
  );
  self.skipWaiting();
});

// ── Activate: 清除旧缓存 ──
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== STATIC_CACHE && k !== API_CACHE)
            .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: 分策略路由 ──
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. API 请求: NetworkFirst
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request, API_CACHE));
    return;
  }

  // 2. CDN 资源 (ECharts, Fonts): Cache-First
  if (url.hostname.includes('cdn.jsdelivr.net') ||
      url.hostname.includes('fonts.loli.net') ||
      url.hostname.includes('fonts.gstatic.com')) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }

  // 3. 静态资源 (本站 CSS/JS): Cache-First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }

  // 4. HTML 页面: NetworkFirst
  if (event.request.mode === 'navigate') {
    event.respondWith(networkFirst(event.request, STATIC_CACHE));
    return;
  }

  // 5. 其他: 走网络
  event.respondWith(fetch(event.request));
});

// ── 策略函数 ──

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) {
      // 为 API 请求添加离线标识 header
      if (request.url.includes('/api/')) {
        const body = await cached.text();
        return new Response(body, {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
            'X-AlphaCore-Offline': 'true',
            'X-AlphaCore-Cache-Time': cached.headers.get('date') || 'unknown',
          },
        });
      }
      return cached;
    }
    // 离线且无缓存: 返回 offline shell
    if (request.mode === 'navigate') {
      return offlineResponse();
    }
    return new Response('Offline', { status: 503 });
  }
}

function offlineResponse() {
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AlphaCore · 离线模式</title>
  <style>
    body { font-family: 'Inter', -apple-system, sans-serif; background: #0f1219; color: #e2e8f0; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    .offline-card { text-align: center; padding: 40px; max-width: 400px; }
    .offline-icon { font-size: 4rem; margin-bottom: 20px; opacity: 0.8; }
    h1 { font-size: 1.4rem; margin-bottom: 12px; color: #3b82f6; }
    p { color: #94a3b8; font-size: 0.9rem; line-height: 1.6; }
    .retry-btn { margin-top: 24px; padding: 10px 28px; background: linear-gradient(135deg, #3b82f6, #2563eb); border: none; border-radius: 8px; color: white; font-weight: 600; cursor: pointer; font-size: 0.9rem; }
  </style>
</head>
<body>
  <div class="offline-card">
    <div class="offline-icon">📡</div>
    <h1>AlphaCore · 离线模式</h1>
    <p>当前无网络连接。恢复连接后，系统将自动同步最新数据。</p>
    <p style="color:#64748b;font-size:0.78rem;margin-top:8px;">上次同步的数据仍可在缓存中查看。</p>
    <button class="retry-btn" onclick="location.reload()">🔄 重试连接</button>
  </div>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}
