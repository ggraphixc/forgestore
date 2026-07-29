// ForgeStore Service Worker — PWA Offline Support
const CACHE_NAME = 'forgestore-v1';
const STATIC_CACHE = 'forgestore-static-v1';
const PAGE_CACHE = 'forgestore-pages-v1';
const API_CACHE = 'forgestore-api-v1';

// Static assets to pre-cache on install
const PRECACHE_URLS = [
  '/',
  '/shop/marketplace',
  '/static/css/output.css',
  '/static/css/forms-core.css',
  '/static/js/main.js',
  '/static/img/placeholder.svg',
  '/static/img/placeholder-product.svg',
];

// API paths eligible for offline caching (GET only)
const OFFLINE_API_PATHS = ['/api/app/sync', '/api/app/config', '/api/app/icon'];

// Install — pre-cache critical assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// Activate — clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== STATIC_CACHE && name !== PAGE_CACHE && name !== CACHE_NAME && name !== API_CACHE)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch strategies
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET, admin/vendor/logistics portals, and auth pages
  if (request.method !== 'GET') return;
  if (url.pathname.startsWith('/admin')) return;
  if (url.pathname.startsWith('/vendor')) return;
  if (url.pathname.startsWith('/driver')) return;
  if (url.pathname.startsWith('/logistics')) return;
  if (url.pathname.startsWith('/shop/login')) return;
  if (url.pathname.startsWith('/shop/register')) return;

  // Eligible API responses — network-first with offline fallback to cache
  if (url.pathname.startsWith('/api/app/')) {
    const isCacheable = OFFLINE_API_PATHS.some(p => url.pathname.startsWith(p));
    if (isCacheable) {
      event.respondWith(networkFirstWithCache(request, API_CACHE));
      return;
    }
    return;
  }

  // Skip remaining /api/ calls
  if (url.pathname.startsWith('/api/')) return;

  // Static assets — cache-first (long-lived)
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // Images from any origin — cache-first with network fallback
  if (request.destination === 'image' || url.pathname.match(/\.(jpg|jpeg|png|gif|webp|svg|ico)$/i)) {
    event.respondWith(cacheFirst(request, CACHE_NAME));
    return;
  }

  // Google Fonts — cache-first
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // External CDN assets — cache-first
  if (url.hostname !== location.hostname) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // HTML pages — stale-while-revalidate (fast, stays fresh)
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(staleWhileRevalidate(request, PAGE_CACHE));
    return;
  }

  // Everything else — network-first
  event.respondWith(networkFirst(request, CACHE_NAME));
});

// Cache-first: serve from cache, fallback to network
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
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

// Stale-while-revalidate: serve cache immediately, update in background
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request).then(async (response) => {
    if (response.ok) {
      await cache.put(request, response.clone());
    }
    return response;
  }).catch(() => {
    // Network failed, return cached or offline page
    return cached || offlinePage();
  });

  return cached || fetchPromise;
}

// Network-first: try network, fallback to cache
async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || offlinePage();
  }
}

// Network-first with cache: try network, fallback to cached JSON (for offline API)
async function networkFirstWithCache(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline', cart: [], wishlist: [], recent_orders: [] }), {
      headers: { 'Content-Type': 'application/json' },
      status: 503,
    });
  }
}

// Offline fallback page
function offlinePage() {
  return new Response(`
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Offline</title>
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
          background: #faf9f6;
          color: #1c1917;
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          text-align: center;
          padding: 2rem;
        }
        .offline-card {
          max-width: 400px;
          padding: 3rem 2rem;
          border-radius: 1.5rem;
          background: white;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06);
          border: 1px solid #e7e5e4;
        }
        .offline-icon {
          font-size: 4rem;
          margin-bottom: 1rem;
        }
        h1 {
          font-size: 1.5rem;
          font-weight: 700;
          margin-bottom: 0.5rem;
          color: #1c1917;
        }
        p {
          color: #78716c;
          margin-bottom: 1.5rem;
          line-height: 1.6;
        }
        .retry-btn {
          display: inline-block;
          padding: 0.75rem 2rem;
          background: #d97706;
          color: white;
          border: none;
          border-radius: 0.75rem;
          font-weight: 600;
          cursor: pointer;
          font-size: 0.9rem;
          transition: background 0.2s;
        }
        .retry-btn:hover { background: #b45309; }
      </style>
    </head>
    <body>
      <div class="offline-card">
        <div class="offline-icon">&#9889;</div>
        <h1>You're Offline</h1>
        <p>It looks like you've lost your internet connection. Check your network and try again.</p>
        <button class="retry-btn" onclick="location.reload()">Try Again</button>
      </div>
    </body>
    </html>
  `, {
    headers: { 'Content-Type': 'text/html' }
  });
}

// Listen for messages from the main thread
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
